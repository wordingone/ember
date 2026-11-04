// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Blind test U39: model reasoning must never be shown as an ordinary reply line.
import { test, expect } from "bun:test";
import { processSseLine, createSseParserContext } from "./api-openai-adapter.ts";

const line = (content: string) =>
  `data: ${JSON.stringify({ choices: [{ delta: { content } }] })}`;

async function run(parts: string[]) {
  const ctx = createSseParserContext();
  for (const p of parts) await processSseLine(line(p), ctx);
  return ctx;
}

test("<think> split across deltas, after whitespace, with the answer in the same delta", async () => {
  const ctx = await run(["\n", "<th", "ink>plan the ", "steps</think>\n\nHello!"]);
  expect(ctx.thinkingBuffer).toBe("plan the steps");
  expect(ctx.textBuffer).toBe("Hello!");
});

test("<thinking> still works", async () => {
  const ctx = await run(["<thinking>x</thinking>", "y"]);
  expect(ctx.thinkingBuffer).toBe("x");
  expect(ctx.textBuffer).toBe("y");
});

test("plain replies, including ones starting with <", async () => {
  expect((await run(["Hi ", "there"])).textBuffer).toBe("Hi there");
  expect((await run(["<b>bold</b>"])).textBuffer).toBe("<b>bold</b>");
});
