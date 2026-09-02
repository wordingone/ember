// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/goal-runtime.test.ts — production singleton wiring tests. Verifies the
// lazy-construct + shared-singleton contract and the test-override seam.
//
// IMPORTANT: every case sets a fake store via setGoalStoreForTests BEFORE the
// first getGoalStore() call. Without an override, getGoalStore() resolves the
// REAL repo root and writes real files under .ember/goals + receipts/
// goal-sessions -- exactly the fs side effect these tests must never trigger
// against the actual working tree (same discipline operator-receipts.test.ts
// follows: its unit tests always pass an explicit repoRoot, never the
// production default).

import { describe, it, expect, afterEach } from "bun:test";
import {
  getGoalStore,
  setGoalStoreForTests,
  resetGoalRuntimeForTests,
} from "./goal-runtime.ts";
import { createGoalStore, createInMemoryGoalPersistence } from "./goal-store.ts";

describe("goal-runtime — getGoalStore", () => {
  afterEach(() => {
    resetGoalRuntimeForTests();
  });

  it("returns the SAME store instance across calls (shared singleton, not a fresh one per call)", () => {
    const fake = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    setGoalStoreForTests(fake);
    const a = getGoalStore();
    const b = getGoalStore();
    expect(a).toBe(b);
    expect(a).toBe(fake);
  });

  it("setGoalStoreForTests overrides whatever the lazy production store would have been", () => {
    const fake = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    fake.createGoal("test override objective");
    setGoalStoreForTests(fake);
    expect(getGoalStore().getGoal()?.objective).toBe("test override objective");
  });

  it("resetGoalRuntimeForTests clears the override — a subsequent override takes effect cleanly", () => {
    const fakeA = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    fakeA.createGoal("goal A");
    setGoalStoreForTests(fakeA);
    expect(getGoalStore()).toBe(fakeA);

    resetGoalRuntimeForTests();

    const fakeB = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    fakeB.createGoal("goal B");
    setGoalStoreForTests(fakeB);
    expect(getGoalStore()).toBe(fakeB);
    expect(getGoalStore()).not.toBe(fakeA);
    expect(getGoalStore().getGoal()?.objective).toBe("goal B");
  });
});
