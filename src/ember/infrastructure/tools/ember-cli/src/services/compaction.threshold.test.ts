// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/compaction.threshold.test.ts -- #2372: compaction triggers on prompt tokens against
// the server's n_ctx, a forced run takes extra instructions, and the summary budget scales.

import { describe, it, expect } from "bun:test";
import {
  buildSummarySystemPrompt,
  createAutocompact,
  describeCompactionOutcome,
  estimatePromptMessageTokens,
  resolveAutoCompactFraction,
  resolveAutoCompactThresholdTokens,
  summaryBudgetTokens,
  SUMMARY_SYSTEM_PROMPT,
  type AutocompactDeps,
} from "./compaction.ts";
import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";

function msg(role: string, text: string): unknown {
  return { role, content: [{ type: "text", text }] };
}

function textOf(m: unknown): string {
  const c = (m as { content?: unknown }).content;
  return Array.isArray(c) ? String((c[0] as { text?: unknown }).text ?? "") : "";
}

function reply(text: string): ModelResponse {
  return { role: "assistant", content: [{ type: "text", text }], stop_reason: "end_turn" };
}

/** n alternating user/assistant messages, each about `chars` characters long. */
function convo(n: number, chars: number): unknown[] {
  return Array.from({ length: n }, (_, i) => msg(i % 2 === 0 ? "user" : "assistant", `m${i}-` + "x".repeat(chars)));
}

interface Harness {
  deps: AutocompactDeps;
  calls: CallModelParams[];
  store: { messages: unknown[] };
  marks: Array<{ secs: number; info?: { tokensBefore: number; tokensAfter: number } }>;
}

function harness(messages: unknown[], extra: Partial<AutocompactDeps> = {}): Harness {
  const calls: CallModelParams[] = [];
  const store = { messages };
  const marks: Harness["marks"] = [];
  const deps: AutocompactDeps = {
    callModel: async (p) => {
      calls.push(p);
      return reply("THE-SUMMARY");
    },
    getMessages: () => store.messages,
    setMessages: (m) => {
      store.messages = m;
    },
    markPostCompaction: (secs, info) => {
      marks.push(info === undefined ? { secs } : { secs, info });
    },
    env: {},
    ...extra,
  };
  return { deps, calls, store, marks };
}

describe("auto-compaction threshold math", () => {
  it("defaults to 85% of n_ctx", () => {
    expect(resolveAutoCompactFraction({})).toBe(0.85);
    expect(resolveAutoCompactThresholdTokens(262144, {})).toBe(Math.floor(262144 * 0.85));
  });

  it("honours EMBER_AUTO_COMPACT_FRACTION and ignores nonsense values", () => {
    expect(resolveAutoCompactThresholdTokens(100000, { EMBER_AUTO_COMPACT_FRACTION: "0.5" })).toBe(50000);
    expect(resolveAutoCompactFraction({ EMBER_AUTO_COMPACT_FRACTION: "1.7" })).toBe(0.85);
    expect(resolveAutoCompactFraction({ EMBER_AUTO_COMPACT_FRACTION: "abc" })).toBe(0.85);
  });

  it("EMBER_AUTO_COMPACT_WINDOW caps the window the fraction applies to, never raises it", () => {
    expect(resolveAutoCompactThresholdTokens(262144, { EMBER_AUTO_COMPACT_WINDOW: "100000" })).toBe(85000);
    expect(resolveAutoCompactThresholdTokens(50000, { EMBER_AUTO_COMPACT_WINDOW: "100000" })).toBe(42500);
  });

  it("scales the summary budget with context: at least 4096 tokens at 262144", () => {
    expect(summaryBudgetTokens(262144)).toBeGreaterThanOrEqual(4096);
    expect(summaryBudgetTokens(131072)).toBe(2048);
    expect(summaryBudgetTokens(8192)).toBe(1024);
    expect(summaryBudgetTokens(2048)).toBe(512); // never more than a quarter of a tiny context
    expect(summaryBudgetTokens(4_000_000)).toBe(8192);
  });
});

describe("auto-compaction trigger (#2372 acceptance: none below the threshold, one above)", () => {
  // 20 messages x ~400 chars -> roughly 2,100 prompt tokens.
  const messages = convo(20, 400);
  const tokens = messages.reduce<number>((s, m) => s + estimatePromptMessageTokens(m), 0);

  it("does not compact while the estimated prompt is below 85% of n_ctx", async () => {
    const h = harness(messages, { nCtx: Math.ceil(tokens / 0.8) }); // prompt is ~80% of the window
    const out = await createAutocompact(h.deps)();
    expect(out).toEqual({ status: "skipped", reason: "below-threshold" });
    expect(h.calls.length).toBe(0);
    expect(h.store.messages).toBe(messages);
    expect(h.marks.length).toBe(0);
  });

  it("compacts exactly once when the estimated prompt reaches 85% of n_ctx", async () => {
    const h = harness(messages, { nCtx: Math.floor(tokens / 0.9) }); // prompt is ~90% of the window
    const out = await createAutocompact(h.deps)();
    expect(out.status).toBe("compacted");
    expect(h.calls.length).toBe(1);
    expect(h.store.messages.length).toBe(1 + 6); // summary + keepRecent
    expect(textOf(h.store.messages[0])).toContain("THE-SUMMARY");
    expect(h.store.messages[h.store.messages.length - 1]).toBe(messages[messages.length - 1]);
    // a second run on the compacted log is below the threshold again: no second call
    const again = await createAutocompact(h.deps)();
    expect(again.status).toBe("skipped");
    expect(h.calls.length).toBe(1);
  });

  it("counts system prompt and tool schemas (overheadTokens) toward the threshold", async () => {
    const nCtx = Math.ceil(tokens / 0.8);
    const without = await createAutocompact(harness(messages, { nCtx }).deps)();
    const withOverhead = await createAutocompact(harness(messages, { nCtx, overheadTokens: () => Math.ceil(tokens * 0.1) }).deps)();
    expect(without.status).toBe("skipped");
    expect(withOverhead.status).toBe("compacted");
  });

  it("reports before/after token estimates to markPostCompaction and in the outcome", async () => {
    const h = harness(messages, { nCtx: Math.floor(tokens / 0.9) });
    const out = await createAutocompact(h.deps)();
    expect(out.status).toBe("compacted");
    if (out.status !== "compacted") return;
    expect(out.trigger).toBe("auto");
    expect(out.tokensBefore).toBe(tokens);
    expect(out.tokensAfter).toBeLessThan(out.tokensBefore);
    expect(h.marks.length).toBe(1);
    expect(h.marks[0]!.info).toEqual({ tokensBefore: out.tokensBefore, tokensAfter: out.tokensAfter });
  });

  it("requests a summary budget scaled from n_ctx", async () => {
    const h = harness(messages, { nCtx: 262144, env: { EMBER_AUTO_COMPACT_FRACTION: "0.001" } });
    await createAutocompact(h.deps)();
    expect(h.calls[0]!.maxTokens).toBeGreaterThanOrEqual(4096);
  });

  it("an unknown n_ctx keeps the legacy length rule", async () => {
    const h = harness(convo(4, 10), { nCtx: () => null });
    expect((await createAutocompact(h.deps)()).status).toBe("skipped");
    const h2 = harness(convo(20, 10), { nCtx: () => null });
    expect((await createAutocompact(h2.deps)()).status).toBe("compacted");
  });

  it("never starts the preserved tail on a tool result", async () => {
    const m = convo(12, 50);
    // index 6 (= 12 - keepRecent) is where the tail would start: make it a tool-result message
    m[6] = { role: "user", content: [{ type: "tool_result", tool_use_id: "t1", content: "r" }] };
    m[5] = { role: "assistant", content: [{ type: "tool_use", id: "t1", name: "Read", input: {} }] };
    const h = harness(m, { nCtx: 100 });
    const out = await createAutocompact(h.deps)();
    expect(out.status).toBe("compacted");
    // the assistant tool call (index 5) stays with its result
    expect(h.store.messages[1]).toBe(m[5]);
    expect(h.store.messages[2]).toBe(m[6]);
  });
});

describe("/compact [instructions] (forced run)", () => {
  it("compacts below the threshold and folds in everything but the system head", async () => {
    const m = [msg("system", "SYS"), ...convo(4, 20)];
    const h = harness(m, { nCtx: 262144 });
    const out = await createAutocompact(h.deps)({ force: true });
    expect(out.status === "compacted" && out.trigger).toBe("manual");
    expect(h.store.messages.length).toBe(2); // system + summary
    expect(h.store.messages[0]).toBe(m[0]);
    expect(h.marks.length).toBe(0); // the command reports a manual run itself
  });

  it("puts the extra instructions in the summary prompt that is sent", async () => {
    const h = harness(convo(6, 20));
    await createAutocompact(h.deps)({ force: true });
    await createAutocompact(harness(convo(6, 20), { callModel: h.deps.callModel }).deps)({
      force: true,
      instructions: "Keep every file path verbatim.",
    });
    expect(h.calls[0]!.systemPrompt).toBe(SUMMARY_SYSTEM_PROMPT);
    expect(h.calls[1]!.systemPrompt).toContain(SUMMARY_SYSTEM_PROMPT);
    expect(h.calls[1]!.systemPrompt).toContain("Keep every file path verbatim.");
    expect(h.calls[1]!.systemPrompt).not.toBe(h.calls[0]!.systemPrompt);
  });

  it("appends standing instructions before the one-shot ones", async () => {
    const h = harness(convo(6, 20), { getStandingInstructions: async () => "STANDING-RULE" });
    await createAutocompact(h.deps)({ force: true, instructions: "ONE-SHOT" });
    const p = h.calls[0]!.systemPrompt;
    expect(p.indexOf("STANDING-RULE")).toBeGreaterThan(p.indexOf(SUMMARY_SYSTEM_PROMPT));
    expect(p.indexOf("ONE-SHOT")).toBeGreaterThan(p.indexOf("STANDING-RULE"));
  });

  it("a failing instructions reader never blocks the compaction", async () => {
    const h = harness(convo(6, 20), {
      getStandingInstructions: async () => {
        throw new Error("disk gone");
      },
    });
    expect((await createAutocompact(h.deps)({ force: true })).status).toBe("compacted");
  });

  it("ends the summary request on a user turn so the model writes rather than continues", async () => {
    const h = harness(convo(6, 20));
    await createAutocompact(h.deps)({ force: true });
    const sent = h.calls[0]!.messages;
    expect((sent[sent.length - 1] as { role: string }).role).toBe("user");
  });

  it("says why nothing happened, and leaves the log alone on a model error", async () => {
    const empty = harness([]);
    expect(await createAutocompact(empty.deps)({ force: true })).toEqual({ status: "skipped", reason: "no-conversation" });
    const one = harness(convo(1, 5));
    expect(await createAutocompact(one.deps)({ force: true })).toEqual({ status: "skipped", reason: "too-short" });

    const m = convo(6, 20);
    const bad = harness(m, {
      callModel: async () => {
        throw new Error("server down");
      },
    });
    const out = await createAutocompact(bad.deps)({ force: true });
    expect(out).toEqual({ status: "skipped", reason: "model-error", detail: "server down" });
    expect(bad.store.messages).toBe(m);
  });
});

describe("compaction wording", () => {
  it("buildSummarySystemPrompt ignores blank extras", () => {
    expect(buildSummarySystemPrompt(undefined, "  ", "")).toBe(SUMMARY_SYSTEM_PROMPT);
    expect(buildSummarySystemPrompt("a", undefined, "b")).toContain("a\n\nb");
  });

  it("describeCompactionOutcome gives the before/after line", () => {
    expect(
      describeCompactionOutcome({ status: "compacted", trigger: "manual", tokensBefore: 41200, tokensAfter: 2100, elapsedSecs: 3 }),
    ).toBe("Conversation compacted: ~41,200 → ~2,100 tokens.");
    expect(describeCompactionOutcome({ status: "skipped", reason: "too-short" })).toContain("Nothing to compact");
    expect(describeCompactionOutcome({ status: "skipped", reason: "model-error", detail: "boom" })).toContain("boom");
  });

  it("estimatePromptMessageTokens does not double count the engine's mirror fields", () => {
    const plain = { role: "assistant", content: [{ type: "text", text: "x".repeat(400) }] };
    const mirrored = { ...plain, message: { content: plain.content }, toolUseResult: [{ content: "x".repeat(400) }] };
    expect(estimatePromptMessageTokens(mirrored)).toBe(estimatePromptMessageTokens(plain));
  });
});
