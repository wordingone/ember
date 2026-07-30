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
  type CallModelParams,
} from "../query/query-loop-support.ts";
import type { PermissionBehavior, Tool, ToolUseContext } from "./tool-interface.ts";
import { createAutocompact } from "../services/compaction.ts";
import { markPostCompaction } from "../session-state.ts";
import { shouldRetry, computeRetryDelay, MAX_RETRY_ATTEMPTS } from "../api-backend.ts";
import { ModelHttpError, CHARS_PER_TOKEN_ESTIMATE } from "../services/api-openai-adapter.ts";

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
// Tool-result context budgeting (issue #157)
//
// A single oversized tool result (e.g. Read on a large file) can make the
// follow-up model call's prefill exceed n_ctx. Depending on the server, that
// either errors (handled fine by the try/catch around callModel below) or
// silently wedges: the connection stays open, no tokens generate, and the
// loop sits in the caller's spinner indefinitely (receipt:
// receipts/operator-sessions/session-20260705T234943Z.jsonl -- a 46,634-byte
// GOAL.md read into an 8192-token n_ctx slot, GPU idle, spinner alive >4min).
// This truncates every tool_result content string to a bounded budget BEFORE
// it enters the conversation -- the single seam all tools funnel through, so
// Read/Bash/PowerShell/Grep/Glob (and any future tool) are covered uniformly
// with no per-tool patching. This is the primary cure; session-init.ts's
// proactive prefill check (FM_91 checkPrefillOverflow) is the backstop for
// whatever still slips through (cumulative multi-turn history, etc).
// ---------------------------------------------------------------------------

/**
 * Default per-tool-result token budget when the caller supplies none via
 * ToolUseContext.toolResultBudget. Sized conservatively against the smallest
 * observed production n_ctx (8192 tokens/slot) -- leaves headroom for the
 * system prompt, conversation history, tool schemas, and generation within
 * one slot. session-init.ts derives a sharper value from the server's actual
 * /props n_ctx and threads it through toolResultBudget when available.
 */
const DEFAULT_TOOL_RESULT_MAX_TOKENS = 2000;
const DEFAULT_TOOL_RESULT_MAX_CHARS = Math.floor(
  DEFAULT_TOOL_RESULT_MAX_TOKENS * CHARS_PER_TOKEN_ESTIMATE,
);

function getToolResultMaxChars(ctx: ToolUseContext): number {
  const override = process.env["EMBER_TOOL_RESULT_MAX_CHARS"];
  if (override) {
    const n = parseInt(override, 10);
    if (!isNaN(n) && n > 0) return n;
  }
  return ctx.toolResultBudget?.maxChars ?? DEFAULT_TOOL_RESULT_MAX_CHARS;
}

/**
 * Truncates a tool_result content string to fit the budget, keeping a head
 * and tail slice with an explicit marker in between -- never a silent drop,
 * and re-reading with offset/limit remains possible for text-file results.
 */
function truncateToolResultContent(content: string, maxChars: number): string {
  if (content.length <= maxChars) return content;
  const headChars = Math.floor(maxChars * 0.6);
  const tailChars = Math.max(maxChars - headChars, 0);
  const head = content.slice(0, headChars);
  const tail = tailChars > 0 ? content.slice(content.length - tailChars) : "";
  const omitted = content.length - head.length - tail.length;
  return `${head}\n\n[...truncated ${omitted} chars of ${content.length} -- re-read with offset/limit for more...]\n\n${tail}`;
}

// ---------------------------------------------------------------------------
// Conversation-total context budgeting (issue #197)
//
// Per-result truncation (above) bounds any ONE tool result, but not the SUM
// of the assembled conversation. Operator session #5 (2026-07-06): a single
// turn burning five tool calls -- each result individually within its own
// 25%-of-n_ctx budget -- still summed past an 8192-token n_ctx and 400'd.
// Before every model call, estimate the total payload (system prompt + full
// history) and, if over budget, evict the OLDEST already-truncated
// tool_result contents (replacing them with a short marker) until it fits --
// never the current turn's live user prompt, never the most recent message.
// ---------------------------------------------------------------------------

/**
 * Conservative pre-init fallback conversation budget (chars), used only when
 * the caller supplies no ToolUseContext.toolResultBudget.conversationMaxChars
 * (e.g. a direct query() caller, or a test harness). In production this never
 * applies: session-init.ts's init() resolves the real n_ctx before
 * getLoopDeps() can return, so getToolResultBudget().conversationMaxChars is
 * always populated by the time a live turn runs.
 */
const DEFAULT_CONVERSATION_MAX_CHARS = DEFAULT_TOOL_RESULT_MAX_CHARS * 4;

function getConversationMaxChars(ctx: ToolUseContext): number {
  return ctx.toolResultBudget?.conversationMaxChars ?? DEFAULT_CONVERSATION_MAX_CHARS;
}

function estimateConversationChars(messages: unknown[], systemPrompt: string): number {
  return systemPrompt.length + JSON.stringify(messages).length;
}

const EVICTED_MARKER_PREFIX = "[evicted:";

/**
 * Looks up the tool_use block (name + a short input descriptor) that produced
 * a given tool_result, by scanning backward for the nearest preceding
 * assistant message carrying a matching tool_use id. Best-effort: falls back
 * to a generic label if the pairing can't be found (never blocks eviction).
 */
function describeToolUse(messages: unknown[], upToIndex: number, toolUseId: string): string {
  for (let i = upToIndex - 1; i >= 0; i--) {
    const m = messages[i] as EngineMessage;
    if (m.role !== "assistant" || !Array.isArray(m.content)) continue;
    const block = (m.content as Array<Record<string, unknown>>).find(
      (b) => b["type"] === "tool_use" && b["id"] === toolUseId,
    );
    if (!block) continue;
    const name = String(block["name"] ?? "tool");
    const input = block["input"] as Record<string, unknown> | undefined;
    const target =
      typeof input?.["file_path"] === "string" ? input["file_path"]
      : typeof input?.["path"] === "string" ? input["path"]
      : typeof input?.["pattern"] === "string" ? input["pattern"]
      : typeof input?.["command"] === "string" ? input["command"]
      : undefined;
    return target ? `${name} ${target}` : name;
  }
  return "tool result";
}

/**
 * Evicts the oldest tool_result contents (replacing them with a short
 * `[evicted: ...]` marker) until the estimated conversation size fits
 * `maxChars`, or every evictable result has been evicted. Never touches the
 * last message (the current turn's most recent content) so the model is
 * never blinded to what it just produced. Idempotent: an already-evicted
 * result is skipped, and the untouched-array reference is returned when
 * nothing needs evicting (preserves reference equality for callers/tests
 * relying on it, e.g. the microcompact-ordering test).
 */
function evictOldestToolResults(
  messages: unknown[],
  systemPrompt: string,
  maxChars: number,
): unknown[] {
  if (maxChars <= 0) return messages;
  if (estimateConversationChars(messages, systemPrompt) <= maxChars) return messages;

  const next = messages.slice();
  for (let i = 0; i < next.length - 1; i++) {
    const m = next[i] as EngineMessage;
    if (m.role !== "user" || !Array.isArray(m.toolUseResult) || m.toolUseResult.length === 0) {
      continue;
    }
    if (m.toolUseResult.every((r) => r.content.startsWith(EVICTED_MARKER_PREFIX))) continue;

    const evictedResults: ToolResultBlock[] = m.toolUseResult.map((r) => {
      if (r.content.startsWith(EVICTED_MARKER_PREFIX)) return r;
      const estTokens = Math.ceil(r.content.length / CHARS_PER_TOKEN_ESTIMATE);
      const label = describeToolUse(next, i, r.tool_use_id);
      return { ...r, content: `${EVICTED_MARKER_PREFIX} ${label} -- ${estTokens} tokens]` };
    });
    next[i] = { ...m, content: evictedResults, toolUseResult: evictedResults };

    if (estimateConversationChars(next, systemPrompt) <= maxChars) return next;
  }

  return next; // evicted everything evictable; session-init's proactive guard is the backstop
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
export type CanUseToolFn = (
  tool: Tool<any, any>,
  input: unknown,
  behavior: PermissionBehavior,
) => Promise<boolean>;

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

/**
 * Reported once per retried (not the original) attempt, before the backoff
 * wait begins (issue #197 Leg 3/4) -- lets a UI show a live "retrying" status
 * that is guaranteed to clear (the loop either yields another RetryAttemptInfo,
 * a terminal ResultEvent, or an assistant/user event; it never just stops).
 */
export interface RetryAttemptInfo {
  /** 1-based count of retry attempts made so far (the failed original call is not counted). */
  attempt: number;
  /** Ceiling this attempt count is bounded by (api-backend.ts's MAX_RETRY_ATTEMPTS). */
  maxAttempts: number;
  /** Backoff delay before the next attempt fires. */
  delayMs: number;
  /** HTTP status that triggered this retry, or null for a connection/timeout failure. */
  status: number | null;
  /** Short human-readable cause, e.g. "HTTP 503" or "connection error". */
  reason: string;
}

/** Extra config passed alongside QueryParams (elicitation, schema overrides). */
interface QueryConfig {
  handleElicitation?: (url: string) => Promise<void>;
  jsonSchema?: unknown;
  /** issue #197: notified before each retry's backoff wait; see RetryAttemptInfo. */
  onRetryAttempt?: (info: RetryAttemptInfo) => void;
}

// ---------------------------------------------------------------------------
// Retry policy (issue #197 Leg 3/4)
//
// The production callModel (session-init.ts's buildProductionCallModel) made
// exactly one attempt per turn: any failure -- a deterministic 400 as much as
// a transient connection drop -- terminated the turn immediately, and the
// REPL's "Retrying..." UI text (message-renderers.ts's SystemAPIErrorMessage,
// AC9: hidden until retryCount>3) was in practice ALWAYS shown on any
// terminal error because repl.ts's renderMsgDispatch defaulted the never-set
// retryCount to 4 -- a live claim of an in-progress retry that had never
// actually happened, let alone finished (operator session #5: "all 4 server
// slots idle, GPU 0%, yet Retrying... persists"). This wires the existing,
// already-unit-tested api-backend.ts classification/backoff helpers
// (shouldRetry/computeRetryDelay -- built for exactly this, never called from
// production code before) to the one seam that knows the real failure shape:
// a deterministic 4xx (except 429/408) throws straight through on the first
// attempt, exactly as before; a transient 5xx/timeout/connection failure gets
// bounded retries with backoff, each one reported via onRetryAttempt before
// its wait begins, so a caller can render live retry status -- and the
// caller-side retryCount default fix (repl.ts) means a message only ever
// claims "retrying" while a retry mechanism that can actually clear it exists.
// ---------------------------------------------------------------------------

/**
 * Transport-level error codes Bun's own fetch() actually throws for a
 * connection-level failure. Issue #197 acceptance leg C (kill the model
 * server mid-turn) exposed that Bun does NOT wrap these in a TypeError the
 * way the original classifier assumed -- it throws a plain `Error` carrying
 * a `.code` string. Measured directly (two live-process probes against the
 * real llama-server binary, one killed before any connection and one killed
 * mid-SSE-stream): a from-scratch refused connection throws
 * `Error("Unable to connect...")` with `code: "ConnectionRefused"`; a
 * mid-stream kill throws `Error("The socket connection was closed
 * unexpectedly...")` with `code: "ECONNRESET"`. Both are plain Errors, so
 * the old `err instanceof TypeError` check silently matched neither --
 * meaning a killed/crashed server produced ZERO retries and went straight
 * to a terminal error, never satisfying "bounded visible retries" at all.
 * The Node-style codes (ECONNREFUSED/ETIMEDOUT/EPIPE/EHOSTUNREACH/
 * EAI_AGAIN) are included too so this still holds under Node or a future
 * Bun version that reverts to Node-compatible codes.
 */
const RETRYABLE_TRANSPORT_ERROR_CODES = new Set([
  "ConnectionRefused",
  "ECONNRESET",
  "ECONNREFUSED",
  "ETIMEDOUT",
  "EPIPE",
  "EHOSTUNREACH",
  "EAI_AGAIN",
]);

/**
 * True only for recognized connection-level failure shapes -- a real
 * fetch() transport error (classified by `.code`, see
 * RETRYABLE_TRANSPORT_ERROR_CODES above; TypeError is also still accepted
 * as a fallback for runtimes/versions that DO wrap this way) or our OWN
 * request-timeout abort (an AbortError from session-init.ts's internal
 * AbortController, distinct from the user's abortController checked
 * separately below). Anything else -- a plain Error with no recognized
 * code, or a non-Error throw entirely -- is NOT a recognized transport
 * failure, so it is never retried: blindly retrying an unclassified
 * condition risks masking a real bug behind a multi-attempt backoff storm
 * instead of surfacing it (caught by query-engine.error-event.test.ts: a
 * synthetic plain-Error and a raw-string throw both regressed to a 5s
 * retry-storm timeout before this narrowing -- the first version of this
 * classifier treated "not a ModelHttpError" as "is a network error", which
 * is too broad).
 */
function isRetryableTransportError(err: unknown): boolean {
  if (err instanceof TypeError) return true;
  if (err instanceof Error && err.name === "AbortError") return true;
  if (err instanceof Error) {
    const code = (err as { code?: unknown }).code;
    if (typeof code === "string" && RETRYABLE_TRANSPORT_ERROR_CODES.has(code)) return true;
  }
  return false;
}

async function callModelWithRetry(
  deps: LoopDeps,
  callParams: CallModelParams,
  abortController: AbortController,
  onRetryAttempt?: (info: RetryAttemptInfo) => void,
): Promise<ModelResponse> {
  let attempt = 0;
  let count529 = 0;

  while (true) {
    try {
      return await deps.callModel(callParams);
    } catch (err) {
      // A user-initiated abort is never retried -- let the caller's own
      // abort handling take over exactly as it did before this loop existed.
      if (abortController.signal.aborted) throw err;

      const status = err instanceof ModelHttpError ? err.status : null;
      const isNetworkError = status === null && isRetryableTransportError(err);
      if (!shouldRetry(status, isNetworkError, attempt, count529, false)) throw err;

      if (status === 529) count529 += 1;
      const delayMs = computeRetryDelay(attempt);
      attempt += 1;
      onRetryAttempt?.({
        attempt,
        maxAttempts: MAX_RETRY_ATTEMPTS,
        delayMs,
        status,
        reason: status !== null ? `HTTP ${status}` : "connection error",
      });
      await deps.sleep(delayMs, abortController.signal);
    }
  }
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
      // Conversation-total budget (issue #197): evict oldest tool_results
      // BEFORE every model call so a multi-tool-call turn's SUM never
      // overflows n_ctx, even though each individual result already fits
      // its own per-result budget (getToolResultMaxChars, above).
      messages = evictOldestToolResults(
        messages,
        params.systemPrompt,
        getConversationMaxChars(params.toolUseContext),
      );
      response = await callModelWithRetry(
        deps,
        {
          messages,
          systemPrompt: params.systemPrompt,
          tools: toolsToEmberDefs(tools),
          model: params.toolUseContext.options.mainLoopModel ?? "default",
          maxTokens: params.maxOutputTokensOverride ?? 8192,
          skipCacheWrite: params.skipCacheWrite,
          abortSignal: params.toolUseContext.abortController.signal,
          jsonSchema: _config?.jsonSchema,
        },
        params.toolUseContext.abortController,
        _config?.onRetryAttempt,
      );
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
            const permission = await tool.checkPermissions(
              block.input,
              params.toolUseContext,
            );
            if (permission.behavior === "deny") {
              toolResultContent.push({
                type: "tool_result",
                tool_use_id: block.id,
                content: permission.message ?? `Tool use denied: ${tool.name}`,
                is_error: true,
              });
              break;
            }

            const sessionAllowed = params.canUseTool
              ? await params.canUseTool(tool, permission.updatedInput, permission.behavior)
              : permission.behavior === "allow";
            if (!sessionAllowed) {
              toolResultContent.push({
                type: "tool_result",
                tool_use_id: block.id,
                content: `Tool blocked by the active sandbox permission mode: ${tool.name}`,
                is_error: true,
              });
              break;
            }

            const result = await tool.call(
              permission.updatedInput,
              params.toolUseContext,
              params.canUseTool,
              undefined,
            );
            const blockParam = tool.mapToolResultToToolResultBlockParam(result.data, block.id);
            const rawContent =
              typeof blockParam.content === "string"
                ? blockParam.content
                : JSON.stringify(blockParam.content);
            toolResultContent.push({
              type: "tool_result",
              tool_use_id: block.id,
              content: truncateToolResultContent(
                rawContent,
                getToolResultMaxChars(params.toolUseContext),
              ),
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
            const rawErrContent = err instanceof Error ? err.message : String(err);
            toolResultContent.push({
              type: "tool_result",
              tool_use_id: block.id,
              content: truncateToolResultContent(
                rawErrContent,
                getToolResultMaxChars(params.toolUseContext),
              ),
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
  /**
   * Threaded to every ToolUseContext this engine builds: per-result budget
   * (issue #157) and conversation-total budget (issue #197).
   */
  toolResultBudget?: { maxChars: number; conversationMaxChars?: number };
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
  /** issue #197: notified before each retry's backoff wait; see RetryAttemptInfo. */
  onRetryAttempt?: (info: RetryAttemptInfo) => void;
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
        onRetryAttempt: this.config.onRetryAttempt,
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
      onRetryAttempt: this.config.onRetryAttempt,
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
      cwd: this.config.cwd ?? process.cwd(),
      getAppState: this.config.getAppState,
      setAppState: this.config.setAppState,
      setAppStateForTasks: (updater) => {
        void this.config.setAppState(updater);
      },
      readFileState: this.config.readFileCache,
      toolResultBudget: this.config.toolResultBudget,
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
