// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { virtualMessageWindow } from "./app-shell.ts";

describe("fixed transcript viewport", () => {
  test("stays bottom-anchored at offset zero", () => {
    expect(virtualMessageWindow(10, 3, 0)).toEqual({ start: 7, end: 10, offset: 0 });
  });

  test("wheel offset reveals older messages without exceeding the finite viewport", () => {
    expect(virtualMessageWindow(10, 3, 2)).toEqual({ start: 5, end: 8, offset: 2 });
  });

  test("clamps empty, oversized, and negative inputs", () => {
    expect(virtualMessageWindow(0, 3, 50)).toEqual({ start: 0, end: 0, offset: 0 });
    expect(virtualMessageWindow(2, 5, 50)).toEqual({ start: 0, end: 2, offset: 0 });
    expect(virtualMessageWindow(10, 3, -4)).toEqual({ start: 7, end: 10, offset: 0 });
  });
});
