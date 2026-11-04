// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Blind test W30 (issue #2381): replies that stop mid-sentence. The server ends such a reply with
// finish_reason "length"; the client used to report it as a normal end of turn. It now records
// the reason and puts a visible line at the end of the reply.

import { afterEach, describe, expect, it, mock } from "bun:test";
import { buildProductionCallModel } from "./session-init.ts";
import { createSseParserContext, processSseLine, replyCutOffNotice } from "../services/api-openai-adapter.ts";

function sseReader(lines: string[]) {
  const chunk = new TextEncoder().encode(lines.map((l) => `${l}\n\n`).join(""));
  let sent = false;
  return {
    read: async () => {
      if (!sent) { sent = true; return { done: false, value: chunk }; }
      return { done: true, value: undefined };
    },
    releaseLock: () => {},
  };
}

const delta = (content: string, finish: string | null = null) =>
  `data: ${JSON.stringify({ choices: [{ index: 0, finish_reason: finish, delta: { content } }] })}`;

async function reply(lines: string[], maxTokens = 256) {
  globalThis.fetch = mock(async () => ({ ok: true, body: { getReader: () => sseReader(lines) } }) as unknown as Response) as unknown as typeof fetch;
  const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 8192 });
  return callModel({ messages: [{ role: "user" as const, content: "hi" }], systemPrompt: "s", tools: [], model: "m", maxTokens });
}

describe("W30: a reply the server cut off says so", () => {
  const origFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = origFetch; });

  it("the parser records the finish reason", async () => {
    const ctx = createSseParserContext({ initialState: "text" });
    expect(ctx.finishReason).toBeNull();
    await processSseLine(delta("Hello"), ctx);
    expect(ctx.finishReason).toBeNull();
    await processSseLine(delta("", "length"), ctx);
    expect(ctx.finishReason).toBe("length");
    expect(ctx.sawFinishReason).toBe(true);
  });

  it("finish_reason length: the text ends with the cut-off line, naming the limit", async () => {
    const r = await reply([delta("The first half of a sen"), delta("", "length")], 256);
    const text = (r.content as Array<{ type: string; text?: string }>).filter((b) => b.type === "text").map((b) => b.text).join("");
    expect(text.startsWith("The first half of a sen")).toBe(true);
    expect(text).toContain("[Reply cut off");
    expect(text).toContain("256");
    expect(text.endsWith(replyCutOffNotice(256))).toBe(true);
    // The turn is still a turn: it stays in the history as an ordinary assistant reply.
    expect(r.stop_reason).toBe("end_turn");
  });

  it("finish_reason length with nothing written: the notice is the reply, so the screen is not blank", async () => {
    const r = await reply([delta("", "length")]);
    const text = (r.content as Array<{ type: string; text?: string }>).filter((b) => b.type === "text").map((b) => b.text).join("");
    expect(text).toBe(replyCutOffNotice(256));
  });

  it("finish_reason stop: the reply is untouched", async () => {
    const r = await reply([delta("A whole sentence."), delta("", "stop")]);
    const text = (r.content as Array<{ type: string; text?: string }>).filter((b) => b.type === "text").map((b) => b.text).join("");
    expect(text).toBe("A whole sentence.");
  });

  it("a cut-off tool call keeps its own handling and gets no notice", async () => {
    const call = `data: ${JSON.stringify({ choices: [{ index: 0, finish_reason: null, delta: { tool_calls: [{ index: 0, id: "t1", function: { name: "Write", arguments: '{"file_path":"a.txt","con' } }] } }] })}`;
    const r = await reply([call, delta("", "length")]);
    const blocks = r.content as Array<{ type: string; text?: string }>;
    expect(blocks.some((b) => b.type === "tool_use")).toBe(true);
    expect(blocks.some((b) => b.type === "text" && (b.text ?? "").includes("Reply cut off"))).toBe(false);
    expect(r.stop_reason).toBe("tool_use");
  });

  it("replyCutOffNotice without a known limit still reads", () => {
    expect(replyCutOffNotice()).toContain("output limit");
    expect(replyCutOffNotice()).not.toContain("undefined");
  });
});
