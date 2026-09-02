// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/compaction.test.ts — behavioral tests for the real compaction service.
// Asserts micro-compaction actually trims (and only when over budget) and that
// auto-compaction summarizes-and-replaces while failing safe on model errors.

import { describe, it, expect } from "bun:test";
import {
  createMicrocompact,
  createAutocompact,
  estimateMessageTokens,
  type AutocompactDeps,
} from "./compaction.ts";
import type { ModelResponse } from "../query/query-loop-support.ts";

function msg(role: string, text: string): unknown {
  return { role, content: [{ type: "text", text }] };
}

function textOf(m: unknown): string {
  const content = (m as { content?: unknown }).content;
  if (
    Array.isArray(content) &&
    content[0] !== null &&
    typeof content[0] === "object" &&
    "text" in content[0]
  ) {
    return String((content[0] as { text: unknown }).text);
  }
  return "";
}

function modelResponse(text: string): ModelResponse {
  return { role: "assistant", content: [{ type: "text", text }], stop_reason: "end_turn" };
}

describe("microcompact — under budget", () => {
  it("returns the message list unchanged when total estimate is within budget", async () => {
    const messages = [msg("system", "S"), msg("user", "hi"), msg("assistant", "yo")];
    const mc = createMicrocompact({ maxTokens: 100000, keepRecent: 6 });
    const out = await mc(messages);
    expect(out).toBe(messages); // same reference: no work done
    expect(out.length).toBe(3);
  });

  it("returns an empty array unchanged", async () => {
    const mc = createMicrocompact({ maxTokens: 1 });
    const out = await mc([]);
    expect(out.length).toBe(0);
  });
});

describe("microcompact — over budget", () => {
  it("preserves length + system + recent verbatim and truncates middle bodies", async () => {
    const big = "x".repeat(2000);
    const messages = [
      msg("system", "SYS"),
      msg("user", big + "-A"),
      msg("assistant", big + "-B"),
      msg("user", big + "-C"),
      msg("assistant", big + "-D"),
      msg("user", "recent1"),
      msg("assistant", "recent2"),
      msg("user", "recent3"),
    ];
    const before = messages.reduce((s: number, m) => s + estimateMessageTokens(m), 0);
    const mc = createMicrocompact({ maxTokens: 100, keepRecent: 3 });
    const out = await mc(messages);

    expect(out.length).toBe(messages.length); // no message dropped
    expect(out[0]).toBe(messages[0]); // leading system verbatim
    expect(out[5]).toBe(messages[5]); // last keepRecent verbatim
    expect(out[6]).toBe(messages[6]);
    expect(out[7]).toBe(messages[7]);
    expect(textOf(out[1])).toContain("truncated"); // middle body elided
    expect(textOf(out[1])).not.toBe(big + "-A");

    const after = out.reduce((s: number, m) => s + estimateMessageTokens(m), 0);
    expect(after).toBeLessThan(before); // estimate genuinely reduced
  });

  it("never throws on malformed messages and passes them through", async () => {
    const big = "y".repeat(3000);
    const messages = [
      msg("system", "S"),
      42,
      null,
      msg("user", big),
      msg("user", "r1"),
      msg("user", "r2"),
      msg("user", "r3"),
    ];
    const mc = createMicrocompact({ maxTokens: 10, keepRecent: 2 });
    const out = await mc(messages);
    expect(out.length).toBe(messages.length);
    expect(out[1]).toBe(42); // number passed through
    expect(out[2]).toBeNull(); // null passed through
  });
});

describe("autocompact — small conversation", () => {
  it("does nothing (no model call, no rewrite) when below the compaction threshold", async () => {
    let setCalled = false;
    let modelCalls = 0;
    const deps: AutocompactDeps = {
      callModel: async () => {
        modelCalls++;
        return modelResponse("S");
      },
      getMessages: () => [msg("user", "a"), msg("user", "b")],
      setMessages: () => {
        setCalled = true;
      },
    };
    await createAutocompact(deps)();
    expect(modelCalls).toBe(0);
    expect(setCalled).toBe(false);
  });
});

describe("autocompact — large conversation", () => {
  it("summarizes the older portion and rewrites as [system, summary, ...recent]", async () => {
    const recent = [
      msg("user", "r1"),
      msg("assistant", "r2"),
      msg("user", "r3"),
      msg("assistant", "r4"),
      msg("user", "r5"),
      msg("assistant", "r6"),
    ];
    const convo = [msg("system", "SYS"), msg("user", "old1"), msg("assistant", "old2"), msg("user", "old3"), ...recent];

    let captured: unknown[] | null = null;
    let modelCalls = 0;
    let marked = false;
    const deps: AutocompactDeps = {
      callModel: async () => {
        modelCalls++;
        return modelResponse("SUMMARY-OF-OLD");
      },
      getMessages: () => convo,
      setMessages: (m) => {
        captured = m;
      },
      markPostCompaction: () => {
        marked = true;
      },
      keepRecent: 6,
    };
    await createAutocompact(deps)();

    expect(modelCalls).toBe(1);
    expect(marked).toBe(true);
    expect(captured).not.toBeNull();
    const c = captured as unknown as unknown[];
    expect(c.length).toBe(1 + 1 + 6); // system + summary + recent
    expect(c[0]).toBe(convo[0]); // system preserved
    expect(c[c.length - 1]).toBe(recent[recent.length - 1]); // recent tail preserved
    expect(textOf(c[1])).toContain("SUMMARY-OF-OLD"); // summary inserted
  });
});

describe("autocompact — fail-safe", () => {
  it("leaves the conversation unchanged when callModel rejects", async () => {
    const convo = [
      msg("system", "SYS"),
      msg("user", "old1"),
      msg("assistant", "old2"),
      msg("user", "old3"),
      msg("user", "r1"),
      msg("assistant", "r2"),
      msg("user", "r3"),
      msg("assistant", "r4"),
      msg("user", "r5"),
      msg("assistant", "r6"),
    ];
    let setCalled = false;
    let marked = false;
    const deps: AutocompactDeps = {
      callModel: async () => {
        throw new Error("model unavailable");
      },
      getMessages: () => convo,
      setMessages: () => {
        setCalled = true;
      },
      markPostCompaction: () => {
        marked = true;
      },
    };
    await createAutocompact(deps)();
    expect(setCalled).toBe(false);
    expect(marked).toBe(false);
  });

  it("leaves the conversation unchanged when the summary is empty", async () => {
    const convo = [
      msg("system", "SYS"),
      msg("user", "old1"),
      msg("assistant", "old2"),
      msg("user", "old3"),
      msg("user", "r1"),
      msg("assistant", "r2"),
      msg("user", "r3"),
      msg("assistant", "r4"),
      msg("user", "r5"),
      msg("assistant", "r6"),
    ];
    let setCalled = false;
    const deps: AutocompactDeps = {
      callModel: async () => modelResponse("   "),
      getMessages: () => convo,
      setMessages: () => {
        setCalled = true;
      },
    };
    await createAutocompact(deps)();
    expect(setCalled).toBe(false);
  });
});
