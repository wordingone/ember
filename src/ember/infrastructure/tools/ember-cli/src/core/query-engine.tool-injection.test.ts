// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/query-engine.tool-injection.test.ts — issue #159 cell 2: every registered tool forced
// to throw must still yield a non-empty final assistant message. Extends #157's regression
// guard (query-engine.final-message.test.ts, one hand-rolled stub tool) to the full production
// BUILTIN_TOOLS registry -- so a tool whose real shape differs from a minimal stub in a way
// that breaks the loop's error handling can't hide behind the 3 generic cases.

import { describe, it, expect } from "bun:test";
import { query } from "./query-engine.ts";
import { type LoopDepsOverrides, type ModelResponse } from "../query/query-loop-support.ts";
import type { Tool, ToolUseContext } from "./tool-interface.ts";
import type { QueryEvent, ResultEvent } from "./query-engine.ts";
import { BUILTIN_TOOLS } from "../tools/builtin-tools.ts";
import { writeHardeningReceipt } from "../hardening/hardening-receipts.ts";

function makeToolUseContext(tool: Tool): ToolUseContext {
  return {
    options: { tools: [tool], mainLoopModel: "test" },
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
}

describe("query loop — #159 cell 2: every registered tool forced to throw still yields a final message", () => {
  expect(BUILTIN_TOOLS.length).toBeGreaterThan(0); // guards against a silently-empty registry import

  for (const realTool of BUILTIN_TOOLS) {
    it(
      `${realTool.name}: forced throw in .call still yields a non-empty final message`,
      async () => {
        // Spread the REAL tool object so its actual schema/metadata shape is exercised;
        // only .call is overridden to force the failure this cell tests.
        // Typed Tool<any, any> (not bare Tool = Tool<unknown, unknown>): each registry member
        // is a Tool<SpecificInput, SpecificOutput>, and its `description(input?: SpecificInput)`
        // is NOT assignable to `description(input?: unknown)` (parameter contravariance) -- that
        // was a TS2322 typecheck error at this line (#189). `any` keeps the spread exercising
        // the real tool's shape without weakening what the test asserts.
        const throwingTool: Tool<any, any> = {
          ...realTool,
          call: async () => {
            throw new Error(`forced failure: ${realTool.name}`);
          },
        };

        const toolUseResponse: ModelResponse = {
          role: "assistant",
          content: [{ type: "tool_use", id: "t0", name: realTool.name, input: {} }],
          stop_reason: "tool_use",
        };

        const testDeps: LoopDepsOverrides = {
          callModel: async () => toolUseResponse,
          generateUuid: () => Math.random().toString(),
        };

        const capturedEvents: QueryEvent[] = [];
        for await (const event of query(
          {
            messages: [{ role: "user", content: [{ type: "text", text: "test" }] }],
            systemPrompt: "You are a test agent",
            toolUseContext: makeToolUseContext(throwingTool),
            maxTurns: 2,
          },
          testDeps,
        )) {
          capturedEvents.push(event);
        }

        const resultEvent = capturedEvents.find((e) => e.type === "result") as ResultEvent | undefined;
        expect(resultEvent).toBeDefined();

        const finalMsg = (resultEvent as any)?.finalMessage;
        expect(finalMsg).toBeDefined();

        const textBlock = Array.isArray(finalMsg?.content)
          ? finalMsg.content.find((b: any) => b.type === "text")
          : null;
        const text = textBlock?.text ?? "";

        await writeHardeningReceipt({
          suite: "tool-injection",
          cell: realTool.name,
          outcome: typeof text === "string" && text.trim().length > 0 ? "pass" : "fail",
          detail: `finalMessage text length ${typeof text === "string" ? text.trim().length : 0}`,
        });

        expect(textBlock?.text).toBeDefined();
        expect((textBlock?.text || "").trim().length).toBeGreaterThan(0);
      },
      8000,
    );
  }
});
