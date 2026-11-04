// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/query-engine.history.test.ts -- #2382: the model's replies stay in the conversation
// even when the caller stops iterating at the result event, as the REPL does.

import { describe, expect, it } from "bun:test";
import { dropUnansweredToolCalls, QueryEngine, type EngineMessage } from "./query-engine.ts";
import type { CallModelParams, LoopDepsOverrides, ModelResponse } from "../query/query-loop-support.ts";
import type { MessageChange } from "../services/session-store.ts";

function reply(text: string): ModelResponse {
  return { role: "assistant", content: [{ type: "text", text }], stop_reason: "end_turn" };
}

function engineWith(answers: string[]): { engine: QueryEngine; calls: CallModelParams[]; seen: MessageChange[] } {
  const calls: CallModelParams[] = [];
  const seen: MessageChange[] = [];
  let i = 0;
  const deps: LoopDepsOverrides = {
    callModel: async (p) => {
      calls.push({ ...p, messages: [...p.messages] });
      return reply(answers[i++] ?? "extra");
    },
    generateUuid: () => "u",
  };
  const engine = new QueryEngine(
    { getAppState: () => ({}), setAppState: () => {}, onMessagesChanged: (c) => seen.push(c) },
    deps,
  );
  return { engine, calls, seen };
}

/** Iterates the way the REPL does: stops at the result event instead of draining. */
async function submitLikeRepl(engine: QueryEngine, text: string): Promise<void> {
  for await (const ev of engine.submitMessage(text)) {
    if ((ev as { type: string }).type === "result") break;
  }
}

function texts(messages: unknown[]): string[] {
  return messages.map((m) => {
    const msg = m as { role: string; content: unknown };
    const body = Array.isArray(msg.content)
      ? (msg.content as Array<{ text?: string }>).map((b) => b.text ?? "").join("")
      : String(msg.content);
    return `${msg.role}:${body}`;
  });
}

describe("#2382 assistant replies join the history", () => {
  it("keeps the reply when the caller breaks at the result event", async () => {
    const { engine, calls } = engineWith(["Blue Heron", "391"]);
    await submitLikeRepl(engine, "What is the project called?");
    await submitLikeRepl(engine, "What is 17 times 23?");
    expect(texts(engine.getMessages())).toEqual([
      "user:What is the project called?",
      "assistant:Blue Heron",
      "user:What is 17 times 23?",
      "assistant:391",
    ]);
    // the second request carries the first exchange, reply included
    expect(texts(calls[1]!.messages as unknown[])).toEqual([
      "user:What is the project called?",
      "assistant:Blue Heron",
      "user:What is 17 times 23?",
    ]);
  });

  it("reports the reply to the session writer, so a saved session is complete", async () => {
    const { engine, seen } = engineWith(["noted"]);
    await submitLikeRepl(engine, "remember PLUM");
    const flat = seen.flatMap((c) => (c.type === "append" ? c.messages : []));
    expect(texts(flat)).toEqual(["user:remember PLUM", "assistant:noted"]);
  });

  it("still keeps the reply when the caller drains the generator", async () => {
    const { engine } = engineWith(["a1"]);
    for await (const _ev of engine.submitMessage("q1")) {
      // drain
    }
    expect(texts(engine.getMessages())).toEqual(["user:q1", "assistant:a1"]);
  });
});

describe("dropUnansweredToolCalls", () => {
  const msg = (role: "user" | "assistant", content: unknown[]): EngineMessage =>
    ({ role, content, uuid: "u", timestamp: "t" });

  it("drops a trailing tool call whose result never arrived", () => {
    const turn = [
      msg("assistant", [{ type: "text", text: "let me look" }, { type: "tool_use", id: "t1", name: "Read", input: {} }]),
    ];
    expect(dropUnansweredToolCalls(turn)).toEqual([]);
  });

  it("keeps a tool call that has its result, and a final text reply", () => {
    const turn = [
      msg("assistant", [{ type: "tool_use", id: "t1", name: "Read", input: {} }]),
      msg("user", [{ type: "tool_result", tool_use_id: "t1", content: "x" }]),
      msg("assistant", [{ type: "text", text: "done" }]),
    ];
    expect(dropUnansweredToolCalls(turn)).toEqual(turn);
  });

  it("drops only the unanswered call after an answered one", () => {
    const turn = [
      msg("assistant", [{ type: "tool_use", id: "t1", name: "Read", input: {} }]),
      msg("user", [{ type: "tool_result", tool_use_id: "t1", content: "x" }]),
      msg("assistant", [{ type: "tool_use", id: "t2", name: "Bash", input: {} }]),
    ];
    expect(dropUnansweredToolCalls(turn)).toEqual(turn.slice(0, 2));
  });
});
