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

    // nCtx 60 puts the ~16 short messages above the 85% threshold (about 51 tokens).
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, initialMessages: initial, nCtx: 60 },
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

// ---------------------------------------------------------------------------
// #2372: token-based trigger, /compact, standing instructions
// ---------------------------------------------------------------------------

const isSummaryRequest = (p: CallModelParams): boolean => p.systemPrompt.includes("Summarize the prior conversation");

function oldConversation(n: number, chars: number): unknown[] {
  return Array.from({ length: n }, (_, i) => ({
    role: i % 2 === 0 ? "user" : "assistant",
    content: [{ type: "text", text: `old-${i} ` + "x".repeat(chars) }],
  }));
}

function recordingDeps(summaryText = "CONDENSED-SUMMARY"): { deps: LoopDepsOverrides; calls: CallModelParams[] } {
  const calls: CallModelParams[] = [];
  const deps: LoopDepsOverrides = {
    callModel: async (p: CallModelParams): Promise<ModelResponse> => {
      calls.push(p);
      return isSummaryRequest(p)
        ? { role: "assistant", content: [{ type: "text", text: summaryText }], stop_reason: "end_turn" }
        : endTurn();
    },
    generateUuid: () => "u",
  };
  return { deps, calls };
}

async function drain(engine: QueryEngine, text: string): Promise<void> {
  for await (const _ev of engine.submitMessage(text)) {
    // drain
  }
}

describe("query engine — token-based auto-compaction (#2372)", () => {
  it("does not compact below 85% of n_ctx, and compacts once above it", async () => {
    // 20 messages of ~400 chars is about 2,100 tokens.
    const below = recordingDeps();
    const roomy = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, initialMessages: oldConversation(20, 400), nCtx: 4000 },
      below.deps,
    );
    await drain(roomy, "next");
    expect(below.calls.filter(isSummaryRequest).length).toBe(0);
    expect(roomy.getMessages().length).toBeGreaterThan(20);

    const above = recordingDeps();
    const tight = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, initialMessages: oldConversation(20, 400), nCtx: 2400 },
      above.deps,
    );
    await drain(tight, "next");
    expect(above.calls.filter(isSummaryRequest).length).toBe(1);
    expect(tight.getMessages().length).toBeLessThan(20);
  });

  it("charges the system prompt toward the threshold", async () => {
    const { deps, calls } = recordingDeps();
    const engine = new QueryEngine(
      {
        getAppState: () => ({}),
        setAppState: () => {},
        initialMessages: oldConversation(20, 400),
        nCtx: 2800, // messages alone are ~75% of this
        customSystemPrompt: "S".repeat(1600), // +400 tokens pushes the prompt past 85%
      },
      deps,
    );
    await drain(engine, "next");
    expect(calls.filter(isSummaryRequest).length).toBe(1);
  });

  it("a settled compaction is not repeated on the next turn", async () => {
    const { deps, calls } = recordingDeps();
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, initialMessages: oldConversation(20, 400), nCtx: 2400 },
      deps,
    );
    await drain(engine, "one");
    await drain(engine, "two");
    expect(calls.filter(isSummaryRequest).length).toBe(1);
  });
});

describe("query engine — compact() (the /compact command)", () => {
  it("folds the conversation into a summary the next turn is built from", async () => {
    const { deps, calls } = recordingDeps("FACT: the build token is PLUM-42");
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, initialMessages: oldConversation(6, 40), nCtx: 262144 },
      deps,
    );
    const outcome = await engine.compact("keep every identifier");
    expect(outcome.status).toBe("compacted");
    expect(engine.getMessages().length).toBe(1);

    const summaryCall = calls.find(isSummaryRequest)!;
    expect(summaryCall.systemPrompt).toContain("keep every identifier");
    expect(summaryCall.maxTokens).toBeGreaterThanOrEqual(4096);

    await drain(engine, "what is the build token?");
    const turnCall = calls.filter((c) => !isSummaryRequest(c)).pop()!;
    expect(JSON.stringify(turnCall.messages)).toContain("PLUM-42");
    expect(JSON.stringify(turnCall.messages)).not.toContain("old-0");
  });

  it("appends the standing instructions to the summary prompt", async () => {
    const { deps, calls } = recordingDeps();
    const engine = new QueryEngine(
      {
        getAppState: () => ({}),
        setAppState: () => {},
        initialMessages: oldConversation(6, 40),
        compactInstructions: async () => "ALWAYS-KEEP-TEST-NAMES",
      },
      deps,
    );
    await engine.compact();
    expect(calls.find(isSummaryRequest)!.systemPrompt).toContain("ALWAYS-KEEP-TEST-NAMES");
  });

  it("says so when there is nothing to compact", async () => {
    const { deps, calls } = recordingDeps();
    const engine = new QueryEngine({ getAppState: () => ({}), setAppState: () => {} }, deps);
    expect(await engine.compact()).toEqual({ status: "skipped", reason: "no-conversation" });
    expect(calls.length).toBe(0);
  });
});
