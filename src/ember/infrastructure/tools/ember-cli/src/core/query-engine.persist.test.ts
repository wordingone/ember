// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/query-engine.persist.test.ts -- #2373: the engine reports every change to its message log
// (so the REPL can persist it) and a restored log is what the next turn is sent.

import { afterEach, describe, expect, it } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { QueryEngine } from "./query-engine.ts";
import type { CallModelParams, LoopDepsOverrides, ModelResponse } from "../query/query-loop-support.ts";
import { loadSessionFile, SessionWriter, sessionsDirFor, type MessageChange } from "../services/session-store.ts";

const made: string[] = [];
afterEach(() => {
  for (const d of made.splice(0)) rmSync(d, { recursive: true, force: true });
});

function reply(text: string): ModelResponse {
  return { role: "assistant", content: [{ type: "text", text }], stop_reason: "end_turn" };
}

function deps(answer: (p: CallModelParams) => string): { deps: LoopDepsOverrides; calls: CallModelParams[] } {
  const calls: CallModelParams[] = [];
  return {
    calls,
    deps: {
      callModel: async (p) => {
        calls.push(p);
        return reply(p.systemPrompt.includes("Summarize the prior conversation") ? "SUMMARY-TEXT" : answer(p));
      },
      generateUuid: () => "u",
    },
  };
}

async function drain(engine: QueryEngine, text: string): Promise<void> {
  for await (const _ev of engine.submitMessage(text)) {
    // drain
  }
}

describe("QueryEngine.onMessagesChanged", () => {
  it("reports the user message, then the assistant reply, as appends", async () => {
    const seen: MessageChange[] = [];
    const { deps: d } = deps(() => "noted");
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, onMessagesChanged: (c) => seen.push(c) },
      d,
    );
    await drain(engine, "remember PLUM");
    const flat = seen.flatMap((c) => (c.type === "append" ? c.messages : []));
    expect(seen.every((c) => c.type === "append")).toBe(true);
    expect(flat.length).toBe(2);
    expect(JSON.stringify(flat[0])).toContain("remember PLUM");
    expect((flat[1] as { role: string }).role).toBe("assistant");
    expect(engine.getMessages().length).toBe(2);
  });

  it("persists the prompt before the model answers, so an interrupted turn keeps it", async () => {
    const seen: MessageChange[] = [];
    const { deps: d } = deps(() => {
      // the user's message is already reported while the model is still being called
      expect(JSON.stringify(seen)).toContain("half-finished task");
      return "ok";
    });
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, onMessagesChanged: (c) => seen.push(c) },
      d,
    );
    await drain(engine, "half-finished task");
  });

  it("reports a compaction as a replace carrying the whole new log", async () => {
    const seen: MessageChange[] = [];
    const { deps: d } = deps(() => "ok");
    const initial = Array.from({ length: 12 }, (_, i) => ({
      role: i % 2 === 0 ? "user" : "assistant",
      content: [{ type: "text", text: `old-${i}` }],
    }));
    const engine = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, initialMessages: initial, onMessagesChanged: (c) => seen.push(c) },
      d,
    );
    const outcome = await engine.compact();
    expect(outcome.status).toBe("compacted");
    const replace = seen.find((c) => c.type === "replace");
    expect(replace?.messages.length).toBe(1);
    expect(JSON.stringify(replace?.messages[0])).toContain("SUMMARY-TEXT");
  });

  it("a session written from those changes restores to the same log (the model recalls the detail)", async () => {
    const home = mkdtempSync(join(tmpdir(), "ember-persist-"));
    made.push(home);
    const writer = new SessionWriter({ dir: sessionsDirFor("/proj", home), sessionId: "s1", cwd: "/proj" });

    const first = deps((p) => `I will remember it (${p.messages.length} messages)`);
    const engine1 = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, onMessagesChanged: (c) => writer.append(c) },
      first.deps,
    );
    await drain(engine1, "the secret word is PLUM-42");
    await drain(engine1, "ok");

    const restored = loadSessionFile(writer.path)!;
    expect(restored.skippedLines).toEqual([]);
    expect(restored.messages.length).toBe(engine1.getMessages().length);

    const second = deps((p) => (JSON.stringify(p.messages).includes("PLUM-42") ? "PLUM-42" : "no idea"));
    const engine2 = new QueryEngine(
      { getAppState: () => ({}), setAppState: () => {}, initialMessages: restored.messages },
      second.deps,
    );
    await drain(engine2, "what was the secret word?");
    const last = engine2.getMessages().at(-1) as { content: Array<{ text: string }> };
    expect(last.content[0]!.text).toBe("PLUM-42");
    // the history was sent, in order, ahead of the new question
    const sent = second.calls[0]!.messages as Array<{ content: Array<{ text?: string }> }>;
    expect(sent.length).toBe(engine1.getMessages().length + 1);
    expect(sent[0]!.content[0]!.text).toBe("the secret word is PLUM-42");
  });
});
