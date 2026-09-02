// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/compaction.edge.test.ts — edge/boundary hardening for the compaction
// service, complementing compaction.test.ts. Every assertion is pinned to the ACTUAL
// implementation behavior (read from compaction.ts), not assumed behavior: the goal is
// to lock the exact contract so a future "simplification" that quietly changes a guard
// is caught.

import { describe, it, expect } from "bun:test";
import {
  createMicrocompact,
  createAutocompact,
  estimateMessageTokens,
  type AutocompactDeps,
} from "./compaction.ts";
import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";

function msg(role: string, text: string): unknown {
  return { role, content: [{ type: "text", text }] };
}
function textOf(m: unknown): string {
  const content = (m as { content?: unknown }).content;
  if (Array.isArray(content) && content[0] !== null && typeof content[0] === "object" && "text" in content[0]) {
    return String((content[0] as { text: unknown }).text);
  }
  return "";
}
const BIG = "x".repeat(2000); // > TRUNCATE_KEEP*2+40 (440) so truncateText actually elides

// ---------------------------------------------------------------------------
// microcompact — boundary geometry
// ---------------------------------------------------------------------------

describe("microcompact edge — nothing to trim despite over budget", () => {
  it("with no leading system and n <= keepRecent, preserves every message verbatim", async () => {
    // protectedStart=0, recentStart=max(0,n-keepRecent)=0 -> all positions are 'recent'
    const messages = [msg("user", BIG), msg("assistant", BIG), msg("user", BIG)];
    const mc = createMicrocompact({ maxTokens: 1, keepRecent: 6 });
    const out = await mc(messages);
    expect(out.length).toBe(3);
    for (let i = 0; i < messages.length; i++) expect(out[i]).toBe(messages[i]); // same refs
  });

  it("keepRecent >= message count leaves only the system protected and nothing in the middle", async () => {
    const messages = [msg("system", "S"), msg("user", BIG), msg("assistant", BIG)];
    const mc = createMicrocompact({ maxTokens: 1, keepRecent: 10 });
    const out = await mc(messages);
    expect(out.length).toBe(3);
    for (let i = 0; i < messages.length; i++) expect(out[i]).toBe(messages[i]); // verbatim
  });
});

describe("microcompact edge — protection is positional, not size-based", () => {
  it("a huge message inside the recent window is preserved verbatim (recent never truncated)", async () => {
    const messages = [
      msg("system", "S"),
      msg("user", BIG + "-mid1"),
      msg("assistant", BIG + "-mid2"),
      msg("user", BIG + "-mid3"),
      msg("assistant", BIG + "-recentHUGE"), // recent + huge -> must survive verbatim
      msg("user", "r2"),
      msg("assistant", "r3"),
    ];
    const mc = createMicrocompact({ maxTokens: 100, keepRecent: 3 });
    const out = await mc(messages);
    expect(out.length).toBe(messages.length);
    expect(out[0]).toBe(messages[0]); // leading system verbatim
    expect(out[4]).toBe(messages[4]); // huge recent verbatim (NOT truncated despite size)
    expect(textOf(out[1])).toContain("truncated"); // middle elided
  });

  it("a system message NOT at index 0 is treated as middle and IS truncated", async () => {
    // proves 'leading system' means index 0 only
    const messages = [
      msg("user", BIG + "-A"),
      msg("assistant", BIG + "-B"),
      msg("user", BIG + "-C"),
      msg("system", BIG + "-LATE_SYSTEM"), // index 3, middle -> truncated
      msg("assistant", BIG + "-E"),
      msg("user", BIG + "-F"),
      msg("user", "r1"),
      msg("assistant", "r2"),
    ];
    const mc = createMicrocompact({ maxTokens: 100, keepRecent: 2 });
    const out = await mc(messages);
    expect(textOf(out[3])).toContain("truncated"); // late system body elided
    expect(textOf(out[3])).not.toBe(BIG + "-LATE_SYSTEM");
    expect(out[6]).toBe(messages[6]); // recent verbatim
    expect(out[7]).toBe(messages[7]);
  });
});

// ---------------------------------------------------------------------------
// autocompact — guard boundaries + extraction
// ---------------------------------------------------------------------------

describe("autocompact edge — no leading system message", () => {
  it("rewrites as [summary, ...recent] with no preserved system head", async () => {
    const recent = [
      msg("user", "r1"), msg("assistant", "r2"), msg("user", "r3"),
      msg("assistant", "r4"), msg("user", "r5"), msg("assistant", "r6"),
    ];
    const convo = [msg("user", "old1"), msg("assistant", "old2"), msg("user", "old3"), msg("user", "old4"), ...recent];
    let captured: unknown[] | null = null;
    let modelCalls = 0;
    const deps: AutocompactDeps = {
      callModel: async (): Promise<ModelResponse> => {
        modelCalls++;
        return { role: "assistant", content: [{ type: "text", text: "SUM-NOSYS" }], stop_reason: "end_turn" };
      },
      getMessages: () => convo,
      setMessages: (m) => { captured = m; },
      keepRecent: 6,
    };
    await createAutocompact(deps)();
    expect(modelCalls).toBe(1);
    const c = captured as unknown as unknown[];
    expect(c.length).toBe(1 + 6); // summary + recent, NO system head
    expect(textOf(c[0])).toContain("SUM-NOSYS"); // first element is the summary
    expect(c[c.length - 1]).toBe(recent[recent.length - 1]);
  });
});

describe("autocompact edge — cutoff guard distinct from minMessages guard", () => {
  it("does nothing when length > minMessages but nothing is older than the head", async () => {
    // system + 6 msgs = 7; minMessagesToCompact lowered to 2 so the first guard passes,
    // but cutoff = 7-6 = 1 <= headLen(1) -> the second guard returns (no model call).
    const convo = [
      msg("system", "S"), msg("user", "a"), msg("assistant", "b"),
      msg("user", "c"), msg("assistant", "d"), msg("user", "e"), msg("assistant", "f"),
    ];
    let modelCalls = 0;
    let setCalled = false;
    const deps: AutocompactDeps = {
      callModel: async (): Promise<ModelResponse> => {
        modelCalls++;
        return { role: "assistant", content: [{ type: "text", text: "X" }], stop_reason: "end_turn" };
      },
      getMessages: () => convo,
      setMessages: () => { setCalled = true; },
      keepRecent: 6,
      minMessagesToCompact: 2,
    };
    await createAutocompact(deps)();
    expect(modelCalls).toBe(0);
    expect(setCalled).toBe(false);
  });
});

describe("autocompact edge — response extraction", () => {
  it("concatenates multiple text blocks and bare-string blocks into one summary", async () => {
    const recent = [
      msg("user", "r1"), msg("assistant", "r2"), msg("user", "r3"),
      msg("assistant", "r4"), msg("user", "r5"), msg("assistant", "r6"),
    ];
    const convo = [msg("system", "S"), msg("user", "old1"), msg("assistant", "old2"), msg("user", "old3"), ...recent];
    let captured: unknown[] | null = null;
    const deps: AutocompactDeps = {
      callModel: async (): Promise<ModelResponse> => ({
        role: "assistant",
        content: [{ type: "text", text: "PART-A" }, "BARE-STRING", { type: "text", text: "PART-B" }],
        stop_reason: "end_turn",
      }),
      getMessages: () => convo,
      setMessages: (m) => { captured = m; },
      keepRecent: 6,
    };
    await createAutocompact(deps)();
    const c = captured as unknown as unknown[];
    const summary = textOf(c[1]);
    expect(summary).toContain("PART-A");
    expect(summary).toContain("BARE-STRING");
    expect(summary).toContain("PART-B");
  });

  it("succeeds (rewrites) even when markPostCompaction is not provided", async () => {
    const recent = [
      msg("user", "r1"), msg("assistant", "r2"), msg("user", "r3"),
      msg("assistant", "r4"), msg("user", "r5"), msg("assistant", "r6"),
    ];
    const convo = [msg("system", "S"), msg("user", "old1"), msg("assistant", "old2"), msg("user", "old3"), ...recent];
    let captured: unknown[] | null = null;
    const deps: AutocompactDeps = {
      callModel: async (): Promise<ModelResponse> => ({
        role: "assistant", content: [{ type: "text", text: "S2" }], stop_reason: "end_turn",
      }),
      getMessages: () => convo,
      setMessages: (m) => { captured = m; },
      keepRecent: 6,
      // markPostCompaction intentionally omitted -> exercises the `?.` optional path
    };
    await createAutocompact(deps)();
    expect(captured).not.toBeNull(); // setMessages still ran, no crash on absent hook
  });
});

// ---------------------------------------------------------------------------
// estimateMessageTokens — type handling
// ---------------------------------------------------------------------------

describe("estimateMessageTokens edge — input types", () => {
  it("counts a raw string by length/4", () => {
    expect(estimateMessageTokens("abcd")).toBe(1); // ceil(4/4)
    expect(estimateMessageTokens("abcde")).toBe(2); // ceil(5/4)
  });
  it("serializes objects with JSON.stringify", () => {
    expect(estimateMessageTokens({ role: "user" })).toBe(4); // '{"role":"user"}' = 15 -> ceil(15/4)
  });
  it("returns 0 for undefined (JSON.stringify -> undefined -> '')", () => {
    expect(estimateMessageTokens(undefined)).toBe(0);
  });
  it("treats null as the serialized literal 'null'", () => {
    expect(estimateMessageTokens(null)).toBe(1); // 'null' = 4 -> ceil(4/4)
  });
});
