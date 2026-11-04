// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { RepeatFailureGuard } from "./repeat-failure-guard.ts";

describe("RepeatFailureGuard", () => {
  it("leaves a first failure untouched and nudges the second", () => {
    const g = new RepeatFailureGuard();
    expect(g.record("Write", { a: 1 }, true, "boom")).toBe("boom");
    expect(g.record("Write", { a: 1 }, true, "boom")).toContain("failed 2 times");
  });

  it("blocks the fourth identical attempt", () => {
    const g = new RepeatFailureGuard();
    for (let i = 0; i < 3; i++) {
      expect(g.shouldBlock("Write", { a: 1 })).toBeNull();
      g.record("Write", { a: 1 }, true, "boom");
    }
    expect(g.shouldBlock("Write", { a: 1 })).toContain("Not running Write again");
  });

  it("treats different input as a different call", () => {
    const g = new RepeatFailureGuard();
    for (let i = 0; i < 3; i++) g.record("Write", { a: 1 }, true, "boom");
    expect(g.shouldBlock("Write", { a: 2 })).toBeNull();
    expect(g.shouldBlock("Edit", { a: 1 })).toBeNull();
  });

  it("a success resets the count", () => {
    const g = new RepeatFailureGuard();
    for (let i = 0; i < 3; i++) g.record("Bash", { c: "x" }, true, "e");
    g.record("Bash", { c: "x" }, false, "ok");
    expect(g.shouldBlock("Bash", { c: "x" })).toBeNull();
  });
});
