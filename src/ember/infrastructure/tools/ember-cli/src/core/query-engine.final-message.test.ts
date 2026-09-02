// core/query-engine.final-message.test.ts — issue #157: agent loop must always emit a final assistant message
//
// When the agent loop exits (via max_turns, errors, or other termination), it must
// always include a final non-empty assistant message in the result event.
// Silence (no closing message to the user) is indistinguishable from a hang.

import { describe, it, expect, beforeEach } from "bun:test";
import { query } from "./query-engine.ts";
import { type LoopDepsOverrides, type ModelResponse } from "../query/query-loop-support.ts";
import { buildTool, type Tool, type ToolUseContext } from "./tool-interface.ts";
import type { QueryEvent, ResultEvent } from "./query-engine.ts";

// Stub tools built via the canonical buildTool() factory (fills TOOL_DEFAULTS for the
// behavioral fields — isEnabled/isReadOnly/checkPermissions/etc.), matching the pattern in
// query-engine.conversation-budget.test.ts. The previous hand-rolled object literals were
// missing those required fields AND returned a malformed ToolResultBlockParam (no
// type/tool_use_id) — both standing typecheck errors on master (#189).

// Stub tool that throws
const failingTool: Tool = buildTool<unknown, unknown>({
  name: "failing_tool",
  description: () => "A tool that fails",
  inputJSONSchema: { type: "object", properties: {} },
  call: async () => {
    throw new Error("Tool execution failed: simulated failure");
  },
  mapToolResultToToolResultBlockParam: (data: unknown, id: string) => ({
    type: "tool_result" as const,
    tool_use_id: id,
    content: String(data),
    is_error: false,
  }),
});

// Stub tool that succeeds
const succeedingTool: Tool = buildTool<unknown, unknown>({
  name: "succeeding_tool",
  description: () => "A tool that succeeds",
  inputJSONSchema: { type: "object", properties: {} },
  call: async (): Promise<{ data: unknown }> => ({ data: "success result" }),
  mapToolResultToToolResultBlockParam: (data: unknown, id: string) => ({
    type: "tool_result" as const,
    tool_use_id: id,
    content: String(data),
    is_error: false,
  }),
});

describe("query loop — final message on termination (issue #157)", () => {
  let capturedEvents: QueryEvent[];

  beforeEach(() => {
    capturedEvents = [];
  });

  it("Case A: tool failures repeat → loop yields final message naming failure", async () => {
    // Stub model that always returns tool_use (forcing max_turns)
    const toolUseResponse: ModelResponse = {
      role: "assistant",
      content: [{ type: "tool_use", id: "t0", name: "failing_tool", input: {} }],
      stop_reason: "tool_use",
    };

    let callCount = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        callCount++;
        return toolUseResponse;
      },
      generateUuid: () => Math.random().toString(),
    };

    const toolUseContext: ToolUseContext = {
      options: { tools: [failingTool], mainLoopModel: "test" },
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
    };

    for await (const event of query(
      {
        messages: [{ role: "user", content: [{ type: "text", text: "test" }] }],
        systemPrompt: "You are a test agent",
        toolUseContext,
        maxTurns: 2,
      },
      testDeps,
    )) {
      capturedEvents.push(event);
    }

    const resultEvent = capturedEvents.find((e) => e.type === "result") as ResultEvent | undefined;
    expect(resultEvent).toBeDefined();

    // The fix: result event MUST carry a finalMessage
    const finalMsg = (resultEvent as any)?.finalMessage;
    // toBeDefined() takes no arguments in bun:test (unlike jest) -- the descriptive text lives
    // in the comment above, not a matcher argument (that was a TS2554 typecheck error, #189).
    expect(finalMsg).toBeDefined();

    // Message must have non-empty text content
    const textBlock = Array.isArray(finalMsg?.content)
      ? finalMsg.content.find((b: any) => b.type === "text")
      : null;
    expect(textBlock?.text).toBeDefined();
    expect((textBlock?.text || "").trim().length).toBeGreaterThan(0);
  });

  it("Case B: tool success then empty model response → yields final message", async () => {
    const toolUseResponse: ModelResponse = {
      role: "assistant",
      content: [{ type: "tool_use", id: "t0", name: "succeeding_tool", input: {} }],
      stop_reason: "tool_use",
    };

    const emptyResponse: ModelResponse = {
      role: "assistant",
      content: [],
      stop_reason: "end_turn",
    };

    let callIndex = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        return callIndex++ === 0 ? toolUseResponse : emptyResponse;
      },
      generateUuid: () => Math.random().toString(),
    };

    const toolUseContext: ToolUseContext = {
      options: { tools: [succeedingTool], mainLoopModel: "test" },
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
    };

    for await (const event of query(
      {
        messages: [{ role: "user", content: [{ type: "text", text: "test" }] }],
        systemPrompt: "You are a test agent",
        toolUseContext,
      },
      testDeps,
    )) {
      capturedEvents.push(event);
    }

    const resultEvent = capturedEvents.find((e) => e.type === "result") as ResultEvent | undefined;
    expect(resultEvent?.subtype).toBe("success");

    // Even though model returned empty, finalMessage must exist and have content
    const finalMsg = (resultEvent as any)?.finalMessage;
    // toBeDefined() takes no arguments in bun:test (unlike jest) -- see comment above.
    expect(finalMsg).toBeDefined();
    expect(Array.isArray(finalMsg?.content)).toBe(true);
  });

  it("Case C: normal flow (no tool use) unchanged → direct answer", async () => {
    const directResponse: ModelResponse = {
      role: "assistant",
      content: [{ type: "text", text: "Direct answer" }],
      stop_reason: "end_turn",
    };

    const testDeps: LoopDepsOverrides = {
      callModel: async () => directResponse,
      generateUuid: () => Math.random().toString(),
    };

    const toolUseContext: ToolUseContext = {
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
    };

    for await (const event of query(
      {
        messages: [{ role: "user", content: [{ type: "text", text: "test" }] }],
        systemPrompt: "You are a test agent",
        toolUseContext,
      },
      testDeps,
    )) {
      capturedEvents.push(event);
    }

    const resultEvent = capturedEvents.find((e) => e.type === "result") as ResultEvent | undefined;
    expect(resultEvent?.subtype).toBe("success");

    const finalMsg = (resultEvent as any)?.finalMessage;
    expect(finalMsg?.content[0]?.text).toBe("Direct answer");
  });
});
