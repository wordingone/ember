// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/query-engine.conversation-budget.test.ts — issue #197 Leg 1: per-result
// truncation (issue #157) bounds any ONE tool result, but not the SUM of the
// assembled conversation. Operator session #5 (2026-07-06): a single turn
// burning five tool calls -- each result individually within its own
// 25%-of-n_ctx budget -- still summed past an 8192-token n_ctx and 400'd.
// Before every model call, query() must estimate the total payload and, if
// over budget, evict the OLDEST tool_result contents (oldest-first, replaced
// with a short marker) until it fits -- never the current turn's live user
// prompt, never the most recent message.

import { describe, it, expect } from "bun:test";
import { query } from "./query-engine.ts";
import { type LoopDepsOverrides, type ModelResponse } from "../query/query-loop-support.ts";
import { buildTool, type Tool, type ToolUseContext } from "./tool-interface.ts";
import type { QueryEvent, UserEvent } from "./query-engine.ts";

function makeToolUseContext(overrides: Partial<ToolUseContext> = {}): ToolUseContext {
  return {
    options: { tools: [], mainLoopModel: "test" },
    abortController: new AbortController(),
    getAppState: () => ({}),
    setAppState: () => {},
    setAppStateForTasks: () => {},
    readFileState: new Map(),
    messages: [],
    appendSystemMessage: () => {},
    nestedMemoryAttachmentTriggers: new Set(),
    loadedNestedMemoryPaths: new Set(),
    dynamicSkillDirTriggers: new Set(),
    discoveredSkillNames: new Set(),
    fileReadingLimits: { maxTokens: 10000, maxSizeBytes: 1024 * 1024 },
    globLimits: { maxResults: 100 },
    toolUseId: "test_tool_use",
    setSDKStatus: undefined,
    ...overrides,
  } as ToolUseContext;
}

// Each result is individually small (well under any per-result budget) but
// FIVE of them together exceed a tight conversationMaxChars -- exactly the
// operator session #5 shape (5+ tool calls, none individually oversized).
const MEDIUM_CONTENT_LEN = 500;
function makeReadTool(content: string): Tool {
  return buildTool<unknown, unknown>({
    name: "Read",
    description: () => "reads a file",
    inputJSONSchema: { type: "object", properties: {} },
    call: async (): Promise<{ data: unknown }> => ({ data: content }),
    mapToolResultToToolResultBlockParam: (data: unknown, id: string) => ({
      type: "tool_result" as const,
      tool_use_id: id,
      content: String(data),
      is_error: false,
    }),
  });
}

/** Drives `callCount` rounds of tool_use before a final end_turn response. */
function makeMultiRoundDeps(callCount: number): {
  testDeps: LoopDepsOverrides;
  getCallHistory: () => unknown[][];
} {
  let round = 0;
  const callHistory: unknown[][] = [];
  const testDeps: LoopDepsOverrides = {
    callModel: async (params: { messages: unknown[] }) => {
      callHistory.push(params.messages);
      const response: ModelResponse =
        round < callCount
          ? {
              role: "assistant",
              content: [{ type: "tool_use", id: `t${round}`, name: "Read", input: { file_path: `/f${round}.txt` } }],
              stop_reason: "tool_use",
            }
          : { role: "assistant", content: [{ type: "text", text: "done" }], stop_reason: "end_turn" };
      round += 1;
      return response;
    },
    generateUuid: () => Math.random().toString(),
  };
  return { testDeps, getCallHistory: () => callHistory };
}

describe("query loop — conversation-total context budgeting (issue #197 Leg 1)", () => {
  it("evicts the OLDEST tool_result content first when the assembled conversation exceeds conversationMaxChars", async () => {
    const { testDeps, getCallHistory } = makeMultiRoundDeps(5);
    const toolUseContext = makeToolUseContext({
      options: { tools: [makeReadTool("X".repeat(MEDIUM_CONTENT_LEN))], mainLoopModel: "test" },
      // Each result ~500 chars; 5 of them + JSON overhead comfortably exceeds
      // this budget, forcing eviction of the earliest ones by the last call.
      toolResultBudget: { maxChars: 10_000, conversationMaxChars: 1_800 },
    });

    const events: QueryEvent[] = [];
    for await (const event of query(
      {
        messages: [{ role: "user", content: [{ type: "text", text: "read 5 files" }] }],
        systemPrompt: "test",
        toolUseContext,
      },
      testDeps,
    )) {
      events.push(event);
    }

    // The LAST callModel invocation's assembled messages are what we care about --
    // by then, 4 prior tool_results exist and the budget should have forced eviction.
    const history = getCallHistory();
    const lastCallMessages = history[history.length - 1] as Array<{
      role: string;
      toolUseResult?: Array<{ content: string }>;
    }>;

    const toolResultMsgs = lastCallMessages.filter(
      (m) => m.role === "user" && Array.isArray(m.toolUseResult) && m.toolUseResult.length > 0,
    );
    expect(toolResultMsgs.length).toBeGreaterThan(0);

    const evictedCount = toolResultMsgs.filter((m) =>
      m.toolUseResult!.every((r) => r.content.startsWith("[evicted:")),
    ).length;
    const liveCount = toolResultMsgs.length - evictedCount;

    // At least the earliest result(s) must have been evicted -- otherwise the
    // conversation-total budget did nothing.
    expect(evictedCount).toBeGreaterThan(0);

    // Eviction must proceed oldest-first: every evicted entry must appear
    // BEFORE every still-live entry in message order.
    let sawLive = false;
    for (const m of toolResultMsgs) {
      const isEvicted = m.toolUseResult!.every((r) => r.content.startsWith("[evicted:"));
      if (!isEvicted) sawLive = true;
      else if (sawLive) {
        throw new Error("an evicted entry appeared AFTER a live one -- eviction was not oldest-first");
      }
    }
    expect(liveCount).toBeGreaterThan(0);
  });

  it("never evicts when the assembled conversation already fits (identity, no markers)", async () => {
    const { testDeps } = makeMultiRoundDeps(2);
    const toolUseContext = makeToolUseContext({
      options: { tools: [makeReadTool("small")], mainLoopModel: "test" },
      toolResultBudget: { maxChars: 10_000, conversationMaxChars: 1_000_000 },
    });

    const events: QueryEvent[] = [];
    for await (const event of query(
      {
        messages: [{ role: "user", content: [{ type: "text", text: "read 2 files" }] }],
        systemPrompt: "test",
        toolUseContext,
      },
      testDeps,
    )) {
      events.push(event);
    }

    const userEvents = events.filter((e): e is UserEvent => e.type === "user");
    for (const ev of userEvents) {
      for (const r of ev.message.toolUseResult ?? []) {
        expect(r.content.startsWith("[evicted:")).toBe(false);
      }
    }
  });

  it("marker format names the evicted tool and an estimated token count", async () => {
    const { testDeps, getCallHistory } = makeMultiRoundDeps(5);
    const toolUseContext = makeToolUseContext({
      options: { tools: [makeReadTool("X".repeat(MEDIUM_CONTENT_LEN))], mainLoopModel: "test" },
      toolResultBudget: { maxChars: 10_000, conversationMaxChars: 1_800 },
    });

    for await (const _event of query(
      {
        messages: [{ role: "user", content: [{ type: "text", text: "read 5 files" }] }],
        systemPrompt: "test",
        toolUseContext,
      },
      testDeps,
    )) {
      // drain
    }

    const history = getCallHistory();
    const lastCallMessages = history[history.length - 1] as Array<{
      role: string;
      toolUseResult?: Array<{ content: string }>;
    }>;
    const evictedContents = lastCallMessages
      .filter((m) => m.role === "user" && Array.isArray(m.toolUseResult))
      .flatMap((m) => m.toolUseResult!.map((r) => r.content))
      .filter((c) => c.startsWith("[evicted:"));

    expect(evictedContents.length).toBeGreaterThan(0);
    for (const c of evictedContents) {
      expect(c).toMatch(/^\[evicted: Read \/f\d+\.txt -- \d+ tokens\]$/);
    }
  });

  it("never evicts the current turn's live user prompt or the most recent message", async () => {
    // A single round with a deliberately tiny conversationMaxChars: even the
    // pathological case (budget smaller than the live prompt itself) must
    // still leave the last message (the model's own tool_use / the pending
    // turn) untouched -- eviction only ever rewrites PAST tool_result rows.
    const { testDeps } = makeMultiRoundDeps(3);
    const toolUseContext = makeToolUseContext({
      options: { tools: [makeReadTool("X".repeat(MEDIUM_CONTENT_LEN))], mainLoopModel: "test" },
      toolResultBudget: { maxChars: 10_000, conversationMaxChars: 1 }, // pathologically tiny
    });

    const events: QueryEvent[] = [];
    for await (const event of query(
      {
        messages: [{ role: "user", content: [{ type: "text", text: "read 3 files" }] }],
        systemPrompt: "test",
        toolUseContext,
      },
      testDeps,
    )) {
      events.push(event);
    }

    // The loop must still reach a terminal success -- eviction never breaks
    // the turn even under an impossible budget (it evicts everything
    // evictable and lets session-init's proactive guard be the backstop).
    const result = events.find((e) => e.type === "result");
    expect(result).toBeDefined();
    expect((result as { subtype: string }).subtype).toBe("success");
  });
});
