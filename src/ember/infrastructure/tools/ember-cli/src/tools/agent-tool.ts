// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/agent-tool.ts — Agent tool: delegate a task to a subagent.
//
// The subagent is a fresh QueryEngine (own message history, tool subset) that
// reuses the parent's loop deps (callModel), so it talks to the SAME local
// model server -- no new server is started. Lifecycle is tracked with
// local-agent-task.ts (abort signal + status). Hard limits: nesting depth,
// per-run timeout, turn cap. Every failure is thrown as an Error, which the
// query loop reports as a tool error (is_error) -- never a crash.

import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";
import type { Tool, ToolUseContext } from "../core/tool-interface.ts";
import { QueryEngine } from "../core/query-engine.ts";
import type { QueryEngineConfig } from "../core/query-engine.ts";
import {
  createLocalAgentTask,
  markAgentComplete,
  markAgentError,
  markAgentStarted,
} from "../local-agent-task.ts";
import { asAgentId } from "../types/id-types.ts";

export const AGENT_MAX_DEPTH = 2;
export const AGENT_DEFAULT_TIMEOUT_MS = 300_000;
export const AGENT_DEFAULT_MAX_TURNS = 12;
const AGENT_TOOL_NAME = "Agent";

/** Tools a subagent never gets: interactive / session-level surfaces. */
const SUBAGENT_DENIED_TOOLS = new Set([
  "AskUserQuestion",
  "EnterPlanMode",
  "ExitPlanMode",
  "SendUserMessage",
  "EnterWorktree",
  "ExitWorktree",
  "CronCreate",
  "CronDelete",
  "CronList",
  "RemoteTrigger",
]);

export interface SubagentType {
  name: string;
  description: string;
  /** null = every non-denied tool; otherwise the allow-list of tool names. */
  allowedTools: readonly string[] | null;
  systemPrompt: string;
}

export const SUBAGENT_TYPES: Readonly<Record<string, SubagentType>> = {
  "general-purpose": {
    name: "general-purpose",
    description: "General-purpose agent with the full tool set (minus interactive tools).",
    allowedTools: null,
    systemPrompt:
      "You are a subagent working for a parent agent. Complete the delegated task using your tools. " +
      "When finished, reply with a concise final report; that text is returned to the parent verbatim.",
  },
  explore: {
    name: "explore",
    description: "Read-only research agent (Read, Glob, Grep). Cannot modify files.",
    allowedTools: ["Read", "Glob", "Grep"],
    systemPrompt:
      "You are a read-only exploration subagent. Search and read files to answer the delegated question. " +
      "You cannot modify anything. Finish with a concise factual report; it is returned to the parent verbatim.",
  },
};

const AgentInputSchema = z
  .object({
    description: z.string().describe("A short (3-5 word) description of the task"),
    prompt: z.string().describe("The full task for the subagent to perform"),
    subagent_type: z
      .string()
      .optional()
      .describe(`Subagent type: ${Object.keys(SUBAGENT_TYPES).join(" | ")} (default general-purpose)`),
  })
  .strict();

export type AgentInput = z.infer<typeof AgentInputSchema>;

export interface AgentOutput {
  agentId: string;
  subagentType: string;
  depth: number;
  turns: number;
  text: string;
}

function envInt(name: string, dflt: number): number {
  const raw = process.env[name];
  if (!raw) return dflt;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : dflt;
}

/** Tool subset for a subagent of the given type at the given depth. */
export function selectSubagentTools(
  parentTools: readonly Tool[],
  type: SubagentType,
  childDepth: number,
): Tool[] {
  return parentTools.filter((t) => {
    if (SUBAGENT_DENIED_TOOLS.has(t.name)) return false;
    if (t.name === AGENT_TOOL_NAME) {
      return type.allowedTools === null && childDepth < AGENT_MAX_DEPTH;
    }
    return type.allowedTools === null || type.allowedTools.includes(t.name);
  });
}

function textOf(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .filter(
      (b): b is { type: string; text: string } =>
        (b as { type?: string })?.type === "text" && typeof (b as { text?: unknown }).text === "string",
    )
    .map((b) => b.text)
    .join("\n")
    .trim();
}

export async function runSubagent(
  input: AgentInput,
  context: ToolUseContext,
  canUseTool?: unknown,
): Promise<AgentOutput> {
  const typeName = (input.subagent_type ?? "general-purpose").trim().toLowerCase();
  const type = SUBAGENT_TYPES[typeName];
  if (!type) {
    throw new Error(
      `Unknown subagent_type "${input.subagent_type}". Valid types: ${Object.keys(SUBAGENT_TYPES).join(", ")}`,
    );
  }
  if (!input.prompt || !input.prompt.trim()) {
    throw new Error("Agent prompt must be a non-empty string");
  }

  const parentDepth = context.agentDepth ?? 0;
  const childDepth = parentDepth + 1;
  if (childDepth > AGENT_MAX_DEPTH) {
    throw new Error(
      `Agent nesting depth limit reached (max ${AGENT_MAX_DEPTH}); do this work directly instead of delegating`,
    );
  }
  if (!context.loopDeps) {
    throw new Error("Agent tool unavailable: no model loop deps in this session context");
  }

  const timeoutMs = envInt("EMBER_AGENT_TIMEOUT_MS", AGENT_DEFAULT_TIMEOUT_MS);
  const maxTurns = envInt("EMBER_AGENT_MAX_TURNS", AGENT_DEFAULT_MAX_TURNS);
  const agentId = `agent-${crypto.randomUUID().slice(0, 8)}`;
  const task = createLocalAgentTask({
    agentId: asAgentId(agentId),
    parentAgentId: asAgentId(context.agentId ?? "main"),
    prompt: input.prompt,
  });
  const startedAt = Date.now();
  markAgentStarted(task);

  // Parent cancel propagates to the child.
  const parentSignal = context.abortController.signal;
  const onParentAbort = (): void => task.kill();
  if (parentSignal.aborted) task.kill();
  else parentSignal.addEventListener("abort", onParentAbort, { once: true });

  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeoutPromise = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      timedOut = true;
      task.kill();
      reject(new Error(`Subagent timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });
  timeoutPromise.catch(() => {});

  const tools = selectSubagentTools(context.options.tools ?? [], type, childDepth);
  const config: QueryEngineConfig = {
    cwd: context.cwd ?? process.cwd(),
    tools,
    commands: [],
    mcpClients: null,
    agents: null,
    canUseTool: canUseTool as QueryEngineConfig["canUseTool"],
    getAppState: context.getAppState,
    setAppState: context.setAppState,
    initialMessages: [],
    readFileCache: new Map<string, unknown>(),
    toolResultBudget: context.toolResultBudget,
    customSystemPrompt: type.systemPrompt,
    userSpecifiedModel: context.options.mainLoopModel,
    maxTurns,
    agentDepth: childDepth,
    agentId,
    abortSignal: task.signal,
  };

  const run = async (): Promise<AgentOutput> => {
    const engine = new QueryEngine(config, context.loopDeps);
    let turns = 0;
    let result:
      | { subtype: string; finalMessage?: { content?: unknown }; errorMessage?: string }
      | undefined;
    for await (const event of engine.submitMessage(input.prompt)) {
      if (event.type === "assistant") turns += 1;
      else if (event.type === "result") result = event as unknown as typeof result;
    }
    if (!result) throw new Error("Subagent ended without a result");
    if (result.subtype !== "success") {
      const detail = result.errorMessage ? `: ${result.errorMessage}` : "";
      const why =
        result.subtype === "max_turns"
          ? `hit the turn cap (${maxTurns})`
          : result.subtype === "abort"
            ? "was aborted"
            : `ended with ${result.subtype}`;
      throw new Error(`Subagent ${why}${detail}`);
    }
    const text = textOf(result.finalMessage?.content);
    if (!text) throw new Error("Subagent finished without producing any text");
    return { agentId, subagentType: type.name, depth: childDepth, turns, text };
  };

  const runPromise = run();
  runPromise.catch(() => {}); // a late failure after a timeout must not become unhandled
  try {
    const out = await Promise.race([runPromise, timeoutPromise]);
    markAgentComplete(task, out.text, startedAt);
    return out;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    markAgentError(task, msg);
    if (timedOut) throw new Error(`Subagent timed out after ${timeoutMs}ms`);
    throw err instanceof Error ? err : new Error(msg);
  } finally {
    if (timer) clearTimeout(timer);
    parentSignal.removeEventListener("abort", onParentAbort);
  }
}

export const AgentTool: Tool<AgentInput, AgentOutput> = buildTool<AgentInput, AgentOutput>({
  name: AGENT_TOOL_NAME,
  inputSchema: AgentInputSchema,
  description: () =>
    "Delegate a self-contained task to a subagent. The subagent runs its own conversation with its own " +
    "tool subset and returns only its final report. Give it a complete prompt (it cannot see this conversation). " +
    `subagent_type: ${Object.values(SUBAGENT_TYPES)
      .map((t) => `"${t.name}" (${t.description})`)
      .join("; ")}. ` +
    `Subagents may nest at most ${AGENT_MAX_DEPTH} levels deep.`,
  isReadOnly: () => false,
  isConcurrencySafe: () => false,
  maxResultSizeChars: 100_000,
  validateInput: (raw: unknown) => {
    const parsed = AgentInputSchema.safeParse(raw);
    if (!parsed.success) {
      return { result: false, message: parsed.error.message, errorCode: "invalid_input" };
    }
    return { result: true };
  },
  call: async (args, context, canUseTool) => {
    const data = await runSubagent(args, context, canUseTool);
    return { data };
  },
  mapToolResultToToolResultBlockParam: (out, toolUseId) => ({
    type: "tool_result",
    tool_use_id: toolUseId,
    content: out.text,
  }),
});
