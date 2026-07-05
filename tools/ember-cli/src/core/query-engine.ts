// core/query-engine.ts — the agent query loop and streaming QueryEngine class.
//
// Provides:
//   - query(): an async generator that drives a single multi-turn agent conversation.
//   - QueryEngine: a stateful wrapper that maintains message history across calls.
//
// L3: depends on query/query-loop-support (LoopDeps, createLoopDeps, buildLoopConfig)
//     and core/tool-interface (Tool, ToolUseContext).

import {
  createLoopDeps,
  buildLoopConfig,
  type LoopDeps,
  type LoopDepsOverrides,
  type ModelResponse,
} from "../query/query-loop-support.ts";
import type { Tool, ToolUseContext } from "./tool-interface.ts";
import { createAutocompact } from "../services/compaction.ts";
import { markPostCompaction } from "../session-state.ts";

// ---------------------------------------------------------------------------
// Internal types
// ---------------------------------------------------------------------------

/** A tool_use block extracted from an assistant message content array. */
interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: unknown;
}

/** A tool_result block pushed into the user message after tool execution. */
interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: string;
  is_error?: boolean;
}

/** Shape of a message in the engine's internal conversation log. */
export interface EngineMessage {
  role: "user" | "assistant";
  content: unknown[];
  uuid: string;
  timestamp: string;
  /** Only on assistant messages — the full raw model response. */
  message?: ModelResponse;
  /** Only on tool-result user messages — the tool result blocks. */
  toolUseResult?: ToolResultBlock[];
}

/** Description options passed to tool.description() during schema assembly. */
interface DescriptionOpts {
  isNonInteractiveSession: boolean;
  toolPermissionContext: null;
  tools: Tool[];
}

// ---------------------------------------------------------------------------
// MCP elicitation error detection
// ---------------------------------------------------------------------------

interface McpElicitationError extends Error {
  code: number;
  url: string;
}

function isMcpElicitationError(err: unknown): err is McpElicitationError {
  if (!(err instanceof Error)) return false;
  const e = err as Partial<McpElicitationError>;
  return typeof e.code === "number" && e.code === -32042 && typeof e.url === "string";
}

// ---------------------------------------------------------------------------
// Final message synthesis
// ---------------------------------------------------------------------------

/**
 * Synthesizes a final assistant message when the loop terminates without one.
 * Used when max_turns is reached, on error, or on abort — ensures the user
 * always receives some closing text rather than silence.
 */
function synthesizeFinalMessage(
  reason: "max_turns" | "error" | "abort",
  lastToolResults?: ToolResultBlock[],
): ModelResponse {
  let text = "";

  switch (reason) {
    case "max_turns":
      text = "I reached the maximum number of turns for this conversation. ";
      if (lastToolResults && lastToolResults.length > 0) {
        const failedTools = lastToolResults.filter((r) => r.is_error);
        if (failedTools.length > 0) {
          text += `Unable to complete your request due to ${failedTools.length} tool failure${failedTools.length > 1 ? "s" : ""}.`;
        } else {
          text += "Please review the tool results above.";
        }
      }
      break;

    case "error":
      text =
        "An error occurred while processing your request. Unable to complete the operation.";
      break;

    case "abort":
      text = "The conversation was interrupted. Please try again.";
      break;
  }

  // Ensure non-empty
  if (!text.trim()) {
    text = "Operation terminated. Unable to produce a result.";
  }

  return {
    role: "assistant",
    content: [{ type: "text", text }],
    stop_reason: "end_turn" as const,
  };
}

// ---------------------------------------------------------------------------
// Tool schema conversion
// ---------------------------------------------------------------------------

function extractToolUseBlocks(content: unknown[]): ToolUseBlock[] {
  return content.filter(
    (b): b is ToolUseBlock =>
      typeof b === "object" && b !== null && (b as { type?: string }).type === "tool_use",
  );
}

function toolsToEmberDefs(
  tools: Tool[],
): Array<{ name: string; description: string; input_schema: Record<string, unknown> }> {
  const descOpts: DescriptionOpts = {
    isNonInteractiveSession: true,
    toolPermissionContext: null,
    tools: [],
  };
  return tools.map((tool) => ({
    name: tool.name,
    description: tool.description(undefined, descOpts),
    input_schema: tool.inputJSONSchema ?? ({ type: "object", properties: {} } as Record<string, unknown>),
  }));
}

// ---------------------------------------------------------------------------
// Query loop event types
// ---------------------------------------------------------------------------

export interface AssistantEvent {
  type: "assistant";
  message: ModelResponse;
}

export interface UserEvent {
  type: "user";
  message: EngineMessage;
}

export interface ResultEventSuccess {
  type: "result";
  subtype: "success";
  durationMs: number;
  usage?: ModelResponse["usage"];
  finalMessage: ModelResponse;
}

export interface ResultEventError {
  type: "result";
  subtype: "error";
  durationMs: number;
  finalMessage?: ModelResponse;
  errorMessage?: string;
}

export interface ResultEventErrorMaxTokens {
  type: "result";
  subtype: "error_max_tokens";
  durationMs: number;
  finalMessage: ModelResponse;
}

export interface ResultEventAbort {
  type: "result";
  subtype: "abort";
  durationMs: number;
  finalMessage?: ModelResponse;
}

export interface ResultEventMaxTurns {
  type: "result";
  subtype: "max_turns";
  durationMs: number;
  finalMessage?: ModelResponse;
}

export type ResultEvent =
  | ResultEventSuccess
  | ResultEventError
  | ResultEventErrorMaxTokens
  | ResultEventAbort
  | ResultEventMaxTurns;

export type QueryEvent = AssistantEvent | UserEvent | ResultEvent;

// ---------------------------------------------------------------------------
// Query params
// ---------------------------------------------------------------------------

/** Predicate that gates whether a given tool may be called. */
export type CanUseToolFn = (tool: Tool, input: unknown) => Promise<boolean>;

export interface QueryParams {
  messages: unknown[];
  systemPrompt: string;
  userContext?: Record<string, unknown>;
  systemContext?: Record<string, unknown>;
  canUseTool?: CanUseToolFn;
  toolUseContext: ToolUseContext;
  fallbackModel?: string;
  maxTurns?: number;
  maxOutputTokensOverride?: number;
  skipCacheWrite?: boolean;
}

/** Extra config passed alongside QueryParams (elicitation, schema overrides). */
interface QueryConfig {
  handleElicitation?: (url: string) => Promise<void>;
  jsonSchema?: unknown;
}

// ---------------------------------------------------------------------------
// query() — the core async generator
// ---------------------------------------------------------------------------

/**
 * Drives a single multi-turn agent conversation.
 *
 * Yields QueryEvents for each assistant message, user (tool-result) message,
 * and the terminal result event. Callers accumulate events to build the
 * turn's message log.
 *
 * @param params - Request parameters including messages, system prompt, and context.
 * @param _testDeps - Optional LoopDeps overrides (for testing).
 * @param _config - Optional per-invocation config (elicitation handler, JSON schema).
 */
export async function* query(
  params: QueryParams,
  _testDeps?: LoopDepsOverrides,
  _config?: QueryConfig,
): AsyncGenerator<QueryEvent> {
  const deps: LoopDeps = createLoopDeps(_testDeps);
  buildLoopConfig(); // reads env; result unused at loop level (reserved for future use)

  let messages = [...params.messages];
  let completeModelTurns = 0;
  const maxTurns = params.maxTurns ?? 100;
  const startTime = Date.now();
  const tools = params.toolUseContext.options.tools ?? [];

  while (completeModelTurns < maxTurns) {
    let response: ModelResponse;
    try {
      // Micro-compaction: minimally trim the running log when it nears the
      // context budget (identity when under budget). Persists forward.
      messages = await deps.microcompact(messages);
      response = await deps.callModel({
        messages,
        systemPrompt: params.systemPrompt,
        tools: toolsToEmberDefs(tools),
        model: params.toolUseContext.options.mainLoopModel ?? "default",
        maxTokens: params.maxOutputTokensOverride ?? 8192,
        skipCacheWrite: params.skipCacheWrite,
        abortSignal: params.toolUseContext.abortController.signal,
        jsonSchema: _config?.jsonSchema,
      });
    } catch (err) {
      if (params.toolUseContext.abortController.signal.aborted) {
        const abortMsg = synthesizeFinalMessage("abort");
        yield { type: "result", subtype: "abort", durationMs: Date.now() - startTime, finalMessage: abortMsg };
        return;
      }
      const errorMsg = synthesizeFinalMessage("error");
      const errorMessage = err instanceof Error ? err.message : String(err);
      yield {
        type: "result",
        subtype: "error",
        durationMs: Date.now() - startTime,
        finalMessage: errorMsg,
        errorMessage,
      };
      return;
    }

    yield { type: "assistant", message: response };

    // Null stop_reason: model is still generating (streaming mid-turn) — accumulate
    if (response.stop_reason === null) {
      const thinkingMsg: EngineMessage = {
        role: "assistant",
        content: Array.isArray(response.content) ? response.content : [],
        uuid: deps.generateUuid(),
        timestamp: new Date().toISOString(),
        message: response,
      };
      messages = [...messages, thinkingMsg];
      continue;
    }

    completeModelTurns += 1;

    // Terminal: end_turn / stop_sequence — conversation complete
    if (
      response.stop_reason === "end_turn" ||
      response.stop_reason === "stop_sequence"
    ) {
      const finalMsg: EngineMessage = {
        role: "assistant",
        content: Array.isArray(response.content) ? response.content : [],
        uuid: deps.generateUuid(),
        timestamp: new Date().toISOString(),
        message: response,
      };
      messages = [...messages, finalMsg];
      yield {
        type: "result",
        subtype: "success",
        durationMs: Date.now() - startTime,
        usage: response.usage,
        finalMessage: response,
      };
      return;
    }

    // Tool use: execute each block and assemble a tool_result user message
    if (response.stop_reason === "tool_use") {
      const assistantMsg: EngineMessage = {
        role: "assistant",
        content: Array.isArray(response.content) ? response.content : [],
        uuid: deps.generateUuid(),
        timestamp: new Date().toISOString(),
        message: response,
      };
      messages = [...messages, assistantMsg];

      const contentBlocks: unknown[] = Array.isArray(response.content)
        ? response.content
        : [];
      const toolUseBlocks = extractToolUseBlocks(contentBlocks);
      const toolResultContent: ToolResultBlock[] = [];

      for (const block of toolUseBlocks) {
        if (params.toolUseContext.abortController.signal.aborted) break;

        const tool = tools.find((t) => t.name === block.name);
        if (!tool) {
          toolResultContent.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: `Unknown tool: ${block.name}`,
            is_error: true,
          });
          continue;
        }

        let retries = 0;
        while (retries <= 1) {
          try {
            const result = await tool.call(
              block.input,
              params.toolUseContext,
              params.canUseTool,
              undefined,
            );
            const blockParam = tool.mapToolResultToToolResultBlockParam(result.data, block.id);
            toolResultContent.push({
              type: "tool_result",
              tool_use_id: block.id,
              content:
                typeof blockParam.content === "string"
                  ? blockParam.content
                  : JSON.stringify(blockParam.content),
              is_error: blockParam.is_error,
            });
            break;
          } catch (err) {
            if (
              retries === 0 &&
              isMcpElicitationError(err) &&
              _config?.handleElicitation
            ) {
              await _config.handleElicitation(err.url);
              retries += 1;
              continue;
            }
            toolResultContent.push({
              type: "tool_result",
              tool_use_id: block.id,
              content: err instanceof Error ? err.message : String(err),
              is_error: true,
            });
            break;
          }
        }
      }

      const toolResultMsg: EngineMessage = {
        role: "user",
        content: toolResultContent,
        uuid: deps.generateUuid(),
        timestamp: new Date().toISOString(),
        toolUseResult: toolResultContent,
      };
      messages = [...messages, toolResultMsg];
      yield { type: "user", message: toolResultMsg };
      continue;
    }

    // max_tokens: model hit the output cap
    yield {
      type: "result",
      subtype: "error_max_tokens",
      durationMs: Date.now() - startTime,
      finalMessage: response,
    };
    return;
  }

  // Exceeded max turns: synthesize a final message from tool results if available
  let lastToolResults: ToolResultBlock[] | undefined;
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i] as EngineMessage;
    if (msg.role === "user" && msg.toolUseResult) {
      lastToolResults = msg.toolUseResult;
      break;
    }
  }
  const maxTurnsMsg = synthesizeFinalMessage("max_turns", lastToolResults);
  yield {
    type: "result",
    subtype: "max_turns",
    durationMs: Date.now() - startTime,
    finalMessage: maxTurnsMsg,
  };
}

// ---------------------------------------------------------------------------
// QueryEngine — stateful conversation driver
// ---------------------------------------------------------------------------

/** Configuration for a QueryEngine instance. */
export interface QueryEngineConfig {
  cwd?: string;
  tools?: Tool[];
  commands?: unknown[];
  mcpClients?: unknown;
  agents?: unknown;
  canUseTool?: CanUseToolFn;
  getAppState: () => unknown;
  setAppState: (updater: (prev: unknown) => unknown) => void | Promise<void>;
  initialMessages?: unknown[];
  readFileCache?: Map<string, unknown>;
  customSystemPrompt?: string;
  appendSystemPrompt?: string;
  userSpecifiedModel?: string;
  fallbackModel?: string;
  thinkingConfig?: unknown;
  maxTurns?: number;
  maxBudgetUsd?: number;
  taskBudget?: unknown;
  jsonSchema?: unknown;
  verbose?: boolean;
  replayUserMessages?: boolean;
  setSDKStatus?: unknown;
  handleElicitation?: (url: string) => Promise<void>;
  /** Test-only override for the conversation-store-bound autocompact. */
  autocompact?: () => Promise<void>;
}

/**
 * Stateful agent engine: maintains the full conversation message log across
 * successive submitMessage() calls.
 *
 * On construction, if `replayUserMessages` is set and `initialMessages` are
 * provided, user-role initial messages are queued for replay before the first
 * live user turn.
 */
export class QueryEngine {
  private config: QueryEngineConfig;
  private messages: unknown[];
  private _replayQueue: unknown[];
  private testDeps: LoopDepsOverrides | undefined;
  private _autocompact: (() => Promise<void>) | null = null;

  constructor(config: QueryEngineConfig, testDeps?: LoopDepsOverrides) {
    this.config = config;
    this.testDeps = testDeps;

    if (config.replayUserMessages && config.initialMessages?.length) {
      this._replayQueue = config.initialMessages.filter(
        (m) => (m as { role?: string }).role === "user",
      );
      this.messages = [];
    } else {
      this._replayQueue = [];
      this.messages = config.initialMessages?.slice() ?? [];
    }
  }

  /**
   * Returns the conversation-store-bound autocompact: it rewrites this engine's
   * own message log via a model-generated summary. Built lazily and cached; a
   * config-provided override (tests) takes precedence.
   */
  private _getAutocompact(deps: LoopDeps): () => Promise<void> {
    if (this.config.autocompact) return this.config.autocompact;
    if (!this._autocompact) {
      this._autocompact = createAutocompact({
        callModel: deps.callModel,
        getMessages: () => this.messages,
        setMessages: (m) => {
          this.messages = m;
        },
        markPostCompaction,
        model: this.config.userSpecifiedModel,
      });
    }
    return this._autocompact;
  }

  /**
   * Submits a user message and drives the agent loop, yielding QueryEvents
   * until the turn reaches a terminal result (success, error, abort, etc.).
   *
   * Replays any queued initial user messages before processing the live turn.
   */
  async *submitMessage(userMessage: string): AsyncGenerator<QueryEvent> {
    const deps = createLoopDeps(this.testDeps);

    // --- Replay phase: process queued initial messages first ---
    while (this._replayQueue.length > 0) {
      const replayMsg = this._replayQueue.shift() as EngineMessage;
      this.messages = [...this.messages, replayMsg];

      const replayAbort = new AbortController();
      const replayCtx = this._buildToolUseContext(replayAbort);
      const replayParams: QueryParams = {
        messages: this.messages,
        systemPrompt: this.config.customSystemPrompt ?? "",
        userContext: {},
        systemContext: {},
        canUseTool: this.config.canUseTool,
        toolUseContext: replayCtx,
        fallbackModel: this.config.fallbackModel,
        maxTurns: this.config.maxTurns,
      };
      const replayConfigExtras: QueryConfig = {
        handleElicitation: this.config.handleElicitation,
        jsonSchema: this.config.jsonSchema,
      };

      const replayTurnMessages: EngineMessage[] = [];
      for await (const event of query(replayParams, this.testDeps, replayConfigExtras)) {
        yield event;
        if (event.type === "assistant") {
          replayTurnMessages.push({
            role: "assistant",
            content: Array.isArray(event.message.content) ? event.message.content : [],
            uuid: deps.generateUuid(),
            timestamp: new Date().toISOString(),
            message: event.message,
          });
        } else if (event.type === "user") {
          replayTurnMessages.push(event.message);
        }
      }
      this.messages = [...this.messages, ...replayTurnMessages];
    }

    // --- Live turn: add the user message and run the loop ---
    const userMsg: EngineMessage = {
      role: "user",
      content: [{ type: "text", text: userMessage }],
      uuid: deps.generateUuid(),
      timestamp: new Date().toISOString(),
    };
    this.messages = [...this.messages, userMsg];

    // Auto-compaction: when the conversation has grown large, condense the older
    // portion into a model-generated summary before running the turn. No-ops when
    // the log is short; fails safe (a model error leaves the log unchanged).
    await this._getAutocompact(deps)();

    const abortController = new AbortController();
    const toolUseContext = this._buildToolUseContext(abortController);
    const params: QueryParams = {
      messages: this.messages,
      systemPrompt: this.config.customSystemPrompt ?? "",
      userContext: {},
      systemContext: {},
      canUseTool: this.config.canUseTool,
      toolUseContext,
      fallbackModel: this.config.fallbackModel,
      maxTurns: this.config.maxTurns,
    };
    const configExtras: QueryConfig = {
      handleElicitation: this.config.handleElicitation,
      jsonSchema: this.config.jsonSchema,
    };

    const turnMessages: EngineMessage[] = [];
    for await (const event of query(params, this.testDeps, configExtras)) {
      yield event;
      if (event.type === "assistant") {
        turnMessages.push({
          role: "assistant",
          content: Array.isArray(event.message.content) ? event.message.content : [],
          uuid: deps.generateUuid(),
          timestamp: new Date().toISOString(),
          message: event.message,
        });
      } else if (event.type === "user") {
        turnMessages.push(event.message);
      }
    }
    this.messages = [...this.messages, ...turnMessages];
  }

  /** Returns the full message history accumulated so far. */
  getMessages(): unknown[] {
    return this.messages;
  }

  /** Constructs the ToolUseContext that each query() invocation receives. */
  private _buildToolUseContext(abortController: AbortController): ToolUseContext {
    const deps = createLoopDeps(this.testDeps);
    return {
      options: {
        tools: this.config.tools,
        commands: this.config.commands,
        verbose: this.config.verbose,
        thinkingConfig: this.config.thinkingConfig,
        mcpClients: this.config.mcpClients,
        mainLoopModel: this.config.userSpecifiedModel,
        customSystemPrompt: this.config.customSystemPrompt,
        appendSystemPrompt: this.config.appendSystemPrompt,
        maxBudgetUsd: this.config.maxBudgetUsd,
      },
      abortController,
      getAppState: this.config.getAppState,
      setAppState: this.config.setAppState,
      setAppStateForTasks: (updater) => {
        void this.config.setAppState(updater);
      },
      readFileState: this.config.readFileCache,
      messages: [...this.messages],
      appendSystemMessage: () => {},
      nestedMemoryAttachmentTriggers: new Set<string>(),
      loadedNestedMemoryPaths: new Set<string>(),
      dynamicSkillDirTriggers: new Set<string>(),
      discoveredSkillNames: new Set<string>(),
      fileReadingLimits: {
        maxTokens: 100_000,
        maxSizeBytes: 5 * 1024 * 1024,
      },
      globLimits: { maxResults: 1000 },
      toolUseId: deps.generateUuid(),
      setSDKStatus: this.config.setSDKStatus,
    };
  }
}
