// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { test, expect } from "bun:test";
import { cursorLineMove } from "./prompt-input.ts";

const t = "abc\nde\nfghij";

test("up from the last line keeps the column, clamped to the shorter line", () => {
  expect(cursorLineMove(t, t.length, -1)).toBe(6); // end of "de"
  expect(cursorLineMove(t, 8, -1)).toBe(5);        // col 1 -> "e"
});
test("down from the first line", () => {
  expect(cursorLineMove(t, 2, 1)).toBe(6);
});
test("null at the edges so history gets the key", () => {
  expect(cursorLineMove(t, 1, -1)).toBeNull();
  expect(cursorLineMove(t, t.length, 1)).toBeNull();
  expect(cursorLineMove("single", 3, -1)).toBeNull();
});
