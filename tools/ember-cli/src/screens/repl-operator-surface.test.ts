// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { operatorSurfaceWidth } from "./repl.ts";

describe("repl operator surface layout", () => {
  test("keeps a bounded right pane while preserving a usable conversation column", () => {
    expect(operatorSurfaceWidth(80)).toBe(36);
    expect(operatorSurfaceWidth(120)).toBe(50);
    expect(operatorSurfaceWidth(240)).toBe(100);
  });
});