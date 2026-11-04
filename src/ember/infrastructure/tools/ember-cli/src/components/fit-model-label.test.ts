// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { test, expect } from "bun:test";
import { fitModelLabel } from "./logo-homescreen.ts";

test("keeps the model name when the seat prefix does not fit", () => {
  expect(fitModelLabel("OPEN_WEIGHTS: Qwen3.8-27B-UD-Q4_K_XL", 32)).toBe("Qwen3.8-27B-UD-Q4_K_XL");
});
test("fits untouched", () => {
  expect(fitModelLabel("OPEN_WEIGHTS: m", 32)).toBe("OPEN_WEIGHTS: m");
});
test("cuts a long name by character", () => {
  expect(fitModelLabel("OPEN_WEIGHTS: abcdefghij", 5)).toBe("abcd\u2026");
});
