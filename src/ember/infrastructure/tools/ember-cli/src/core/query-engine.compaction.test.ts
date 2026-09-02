// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/query-engine.compaction.test.ts — locks the microcompact wiring into the
// agent loop. Without this, microcompact could silently revert to never-invoked
// (the exact unit-green-hides-functional class this fix addresses).

import { describe, it, expect } from "bun:test";
import { QueryEngine } from "./query-engine.ts";
import type {
  CallModelParams,
  ModelResponse,
  LoopDepsOverrides,
} from "../query/query-loop-support.ts";

function endTurn(): ModelResponse {
  return { role: "assistant", content: [{ type: "text", text: "ok" }], stop_reason: "end_turn" };
}

describe("query loop — microcompact wiring", () => {
  it("invokes deps.microcompact before callModel, and callModel sees its output", async () => {
    let microCalls = 0;
    let modelSawSentinel = false;
    const SENTINEL = { role: "system", content: "MICROCOMPACT_RAN" };

    const testDeps: LoopDepsOverrides = {
      // Prove ordering + data-flow: microcompact prepends a sentinel; if callModel
      // sees it, microcompact ran first and its output was passed through.
      microcompact: async (messages: unknown[]): Promise<unknown[]> => {
        microCalls++;
        return [SENTINEL, ...messages];
      },
      callModel: async (params: CallModelParams): Promise<ModelResponse> => {
        modelSawSentinel = params.messages[0] === SENTINEL;
        return endTurn();
      },
      generateUuid: () => "uuid-test",
    };

    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {} },
      testDeps,
    );

    for await (const _ev of engine.submitMessage("hello")) {
      // drain the turn
    }

    expect(microCalls).toBeGreaterThanOrEqual(1);
    expect(modelSawSentinel).toBe(true);
  });
});

describe("query loop — autocompact wiring", () => {
  it("invokes the engine autocompact once at the start of a live turn", async () => {
    let autoCalls = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async (): Promise<ModelResponse> => endTurn(),
      generateUuid: () => "u",
    };
    const engine = new QueryEngine(
      {
        getAppState: () => ({}),
        setAppState: () => {},
        autocompact: async () => {
          autoCalls++;
        },
      },
      testDeps,
    );
    for await (const _ev of engine.submitMessage("hi")) {
      // drain
    }
    expect(autoCalls).toBe(1);
  });

  it("the real engine autocompact condenses a large conversation into a summary", async () => {
    const initial: unknown[] = [{ role: "system", content: "SYS" }];
    for (let i = 0; i < 15; i++) {
      initial.push({
        role: i % 2 === 0 ? "user" : "assistant",
        content: [{ type: "text", text: "old-" + i }],
      });
    }

    const testDeps: LoopDepsOverrides = {
      callModel: async (p: CallModelParams): Promise<ModelResponse> => {
        if (p.systemPrompt.includes("Summarize the prior conversation")) {
          return {
            role: "assistant",
            content: [{ type: "text", text: "CONDENSED-SUMMARY" }],
            stop_reason: "end_turn",
          };
        }
        return endTurn();
      },
      generateUuid: () => "u",
    };

    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, initialMessages: initial },
      testDeps,
    );
    for await (const _ev of engine.submitMessage("new-question")) {
      // drain
    }

    const msgs = engine.getMessages();
    expect(msgs.length).toBeLessThan(initial.length); // older portion collapsed
    const hasSummary = msgs.some((m) => {
      const c = (m as { content?: unknown }).content;
      if (Array.isArray(c) && c[0] !== null && typeof c[0] === "object" && "text" in c[0]) {
        return String((c[0] as { text: unknown }).text).includes("CONDENSED-SUMMARY");
      }
      return false;
    });
    expect(hasSummary).toBe(true);
  });
});
