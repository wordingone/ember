// core/query-engine.tool-result-budget.test.ts — issue #157 Leg 1: an oversized tool
// result must never enter the conversation whole. A large Read/Bash/Grep/etc. output can
// push the follow-up model call's prefill past n_ctx; depending on the server that either
// errors (already handled by the callModel try/catch) or silently wedges the connection
// with no tokens generating (receipt: receipts/operator-sessions/
// session-20260705T234943Z.jsonl -- 46,634-byte docs/authority/GOAL.md read vs an 8192-token n_ctx slot,
// GPU idle, spinner alive >4min). query() must truncate every tool_result content string
// to a bounded budget, head+tail with an explicit marker, applied uniformly at the single
// assembly seam so every tool is covered -- not per-tool patches.

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

const hugeContent = "X".repeat(50_000);

const bigReadTool: Tool = buildTool<unknown, unknown>({
  name: "Read",
  description: () => "reads a file",
  inputJSONSchema: { type: "object", properties: {} },
  call: async (): Promise<{ data: unknown }> => ({ data: hugeContent }),
  mapToolResultToToolResultBlockParam: (data: unknown, id: string) => ({
    type: "tool_result" as const,
    tool_use_id: id,
    content: String(data),
    is_error: false,
  }),
});

describe("query loop — tool-result context budgeting (issue #157 Leg 1)", () => {
  it("truncates an oversized tool result to the configured budget, keeping head+tail and a marker", async () => {
    const toolUseResponse: ModelResponse = {
      role: "assistant",
      content: [{ type: "tool_use", id: "t0", name: "Read", input: {} }],
      stop_reason: "tool_use",
    };
    const finalResponse: ModelResponse = {
      role: "assistant",
      content: [{ type: "text", text: "done" }],
      stop_reason: "end_turn",
    };

    let callIndex = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => (callIndex++ === 0 ? toolUseResponse : finalResponse),
      generateUuid: () => Math.random().toString(),
    };

    const toolUseContext = makeToolUseContext({
      options: { tools: [bigReadTool], mainLoopModel: "test" },
      toolResultBudget: { maxChars: 1000 },
    });

    const events: QueryEvent[] = [];
    for await (const event of query(
      {
        messages: [{ role: "user", content: [{ type: "text", text: "read the file" }] }],
        systemPrompt: "test",
        toolUseContext,
      },
      testDeps,
    )) {
      events.push(event);
    }

    const userEvent = events.find((e) => e.type === "user") as UserEvent | undefined;
    expect(userEvent).toBeDefined();
    const toolResultContent = userEvent!.message.toolUseResult?.[0]?.content ?? "";

    expect(toolResultContent.length).toBeLessThan(hugeContent.length);
    // Under the 1000-char budget plus marker overhead -- nowhere near the original 50,000.
    expect(toolResultContent.length).toBeLessThan(1200);
    expect(toolResultContent).toContain("truncated");
    expect(toolResultContent).toContain("50000");
    // Head and tail slices are both real content, not just the marker.
    expect(toolResultContent.startsWith("X")).toBe(true);
    expect(toolResultContent.endsWith("X")).toBe(true);
  });

  it("leaves a small tool result completely untouched (no marker, no truncation)", async () => {
    const smallContent = "line one\nline two\nline three";
    const smallTool: Tool = {
      ...bigReadTool,
      call: async () => ({ data: smallContent }),
    };
    const toolUseResponse: ModelResponse = {
      role: "assistant",
      content: [{ type: "tool_use", id: "t0", name: "Read", input: {} }],
      stop_reason: "tool_use",
    };
    const finalResponse: ModelResponse = {
      role: "assistant",
      content: [{ type: "text", text: "done" }],
      stop_reason: "end_turn",
    };
    let callIndex = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => (callIndex++ === 0 ? toolUseResponse : finalResponse),
      generateUuid: () => Math.random().toString(),
    };
    const toolUseContext = makeToolUseContext({
      options: { tools: [smallTool], mainLoopModel: "test" },
      toolResultBudget: { maxChars: 1000 },
    });

    const events: QueryEvent[] = [];
    for await (const event of query(
      {
        messages: [{ role: "user", content: [{ type: "text", text: "read the file" }] }],
        systemPrompt: "test",
        toolUseContext,
      },
      testDeps,
    )) {
      events.push(event);
    }
    const userEvent = events.find((e) => e.type === "user") as UserEvent | undefined;
    expect(userEvent!.message.toolUseResult?.[0]?.content).toBe(smallContent);
  });

  it("falls back to a conservative default budget when ToolUseContext carries none", async () => {
    const toolUseResponse: ModelResponse = {
      role: "assistant",
      content: [{ type: "tool_use", id: "t0", name: "Read", input: {} }],
      stop_reason: "tool_use",
    };
    const finalResponse: ModelResponse = {
      role: "assistant",
      content: [{ type: "text", text: "done" }],
      stop_reason: "end_turn",
    };
    let callIndex = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => (callIndex++ === 0 ? toolUseResponse : finalResponse),
      generateUuid: () => Math.random().toString(),
    };
    // No toolResultBudget set at all.
    const toolUseContext = makeToolUseContext({
      options: { tools: [bigReadTool], mainLoopModel: "test" },
    });

    const events: QueryEvent[] = [];
    for await (const event of query(
      {
        messages: [{ role: "user", content: [{ type: "text", text: "read the file" }] }],
        systemPrompt: "test",
        toolUseContext,
      },
      testDeps,
    )) {
      events.push(event);
    }
    const userEvent = events.find((e) => e.type === "user") as UserEvent | undefined;
    const content = userEvent!.message.toolUseResult?.[0]?.content ?? "";
    expect(content.length).toBeLessThan(hugeContent.length);
    expect(content).toContain("truncated");
  });
});
