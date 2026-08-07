// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/goal-continuation-wiring.test.ts — wiring-seam tests (ember issue #211,
// live acceptance leg b groundwork). Proves, at the unit level with the REAL
// engine + a real in-memory store, the exact property the compiled-binary
// acceptance test also has to demonstrate: a single external kick sustains an
// arbitrarily long autonomous chain, live-input preempts it immediately, and
// the chain stops cleanly once the goal leaves Active.

import { describe, it, expect } from "bun:test";
import * as continuationWiring from "./goal-continuation-wiring.ts";
const { createGoalContinuationPoke, isGoalContinuationFeatureEnabled } = continuationWiring;
import { createGoalContinuationEngine } from "./goal-continuation.ts";
import { createGoalStore, createInMemoryGoalPersistence } from "./goal-store.ts";
import type { ContinuationEligibilitySignals } from "./goal-continuation.ts";
import type { GoalReceiptWriter } from "../services/goal-receipts.ts";

function eligible(overrides: Partial<ContinuationEligibilitySignals> = {}): ContinuationEligibilitySignals {
  return {
    featureEnabled: true,
    planMode: false,
    turnActive: false,
    queuedUserInput: false,
    ...overrides,
  };
}

/** Waits for a chain of self-re-invoking microtask-scheduled pokes to settle. */
async function flushChain(turns = 10): Promise<void> {
  for (let i = 0; i < turns; i++) {
    await Promise.resolve();
    await Promise.resolve();
  }
}

describe("createGoalContinuationPoke — self-chaining across multiple autonomous turns", () => {
  it("sustains >=3 autonomous continuations from a single external kick, then stops cleanly at budget", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit", { tokenBudget: 300 });

    const kinds: string[] = [];
    const startTurn = async (prompt: string): Promise<void> => {
      kinds.push(prompt.includes("BUDGET LIMIT REACHED") ? "budget_wrapup" : "continue");
      store.recordUsage(100);
    };

    const poke = createGoalContinuationPoke({
      engine: createGoalContinuationEngine(),
      getStore: () => store,
      getEligibilitySignals: () => eligible(),
      startTurn,
    });

    poke(); // the single external kick — everything after this is autonomous
    await flushChain();

    // 100/200/300 usage -> 3 "continue" turns, then the 4th poke sees
    // usage>=budget and fires the wrap-up steer instead; the 5th poke sees
    // status BudgetLimited (not Active) and stops the chain on its own.
    expect(kinds).toEqual(["continue", "continue", "continue", "budget_wrapup"]);
    expect(store.getGoal()?.status).toBe("BudgetLimited");
  });

  it("never fires at all when the goal is not eligible on the very first poke", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");

    let calls = 0;
    const poke = createGoalContinuationPoke({
      engine: createGoalContinuationEngine(),
      getStore: () => store,
      getEligibilitySignals: () => eligible({ queuedUserInput: true }),
      startTurn: async () => { calls += 1; },
    });

    poke();
    await flushChain();
    expect(calls).toBe(0);
  });

  it("re-evaluates eligibility LIVE on every internal re-poke — queued user input arriving mid-chain preempts the very next hop", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit"); // no budget -- would otherwise chain forever

    let fireCount = 0;
    let userTypedSomething = false; // flips mid-chain, simulating a live keystroke

    const poke = createGoalContinuationPoke({
      engine: createGoalContinuationEngine(),
      getStore: () => store,
      // Re-read fresh every call -- proves the wiring never freezes a stale
      // snapshot of "is the user typing" from the moment of the first kick.
      getEligibilitySignals: () => eligible({ queuedUserInput: userTypedSomething }),
      startTurn: async () => {
        fireCount += 1;
        if (fireCount === 2) userTypedSomething = true; // user starts typing after turn 2
      },
    });

    poke();
    await flushChain();

    // Turn 1 and 2 fire; the poke queued right after turn 2 sees
    // queuedUserInput:true and stops -- the chain never reaches a 3rd turn.
    expect(fireCount).toBe(2);
  });

  it("a poke that arrives while the engine is already mid-turn no-ops without throwing (nested-suppression is harmless)", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    // tokenBudget:1 bounds the self-chain to exactly two fired turns (continue,
    // then budget_wrapup) once released -- without a bound, fully-eligible
    // signals forever would self-chain indefinitely and never let this test
    // (or the process) settle.
    store.createGoal("reach the summit", { tokenBudget: 1 });
    const engine = createGoalContinuationEngine();

    let released: () => void = () => {};
    const gate = new Promise<void>((resolve) => { released = resolve; });

    const poke = createGoalContinuationPoke({
      engine,
      getStore: () => store,
      getEligibilitySignals: () => eligible(),
      startTurn: async () => {
        await gate;
        store.recordUsage(1);
      },
    });

    poke(); // holds the semaphore open on `gate`
    await Promise.resolve();
    expect(engine.isInFlight()).toBe(true);

    // A second, independent poke arriving now must not throw and must not
    // double-fire -- it observes the held semaphore and no-ops.
    expect(() => poke()).not.toThrow();

    released();
    await flushChain();
    expect(engine.isInFlight()).toBe(false);
    expect(store.getGoal()?.status).toBe("BudgetLimited");
  });
});

describe("goal-continuation bounded re-arm (issue #279)", () => {
  it("recovers after a transient skip without another external poke", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("recover the lost wakeup");
    let turnActive = true;
    let fired = 0;
    let rearmPokes = 0;

    const poke = createGoalContinuationPoke({
      engine: createGoalContinuationEngine(),
      getStore: () => store,
      getEligibilitySignals: () => eligible({ turnActive }),
      startTurn: async () => {
        fired += 1;
        store.updateStatus("Complete", {
          completionAudit: { requirements: [{ id: "rearm", evidence: "test-receipt" }] },
        });
      },
    });

    type Rearm = (options: {
      poke: () => void;
      intervalMs?: number;
      featureEnabled?: () => boolean;
      shouldPoke?: () => boolean;
      scheduler?: {
        setInterval: (callback: () => void, intervalMs: number) => unknown;
        clearInterval: (handle: unknown) => void;
      };
    }) => () => void;
    const startRearm = (continuationWiring as unknown as {
      startGoalContinuationRearm: Rearm;
    }).startGoalContinuationRearm;

    const ticks: Array<() => void> = [];
    let cleared: unknown = null;
    const stop = startRearm({
      poke: () => { rearmPokes += 1; poke(); },
      shouldPoke: () => !turnActive,
      intervalMs: 25,
      scheduler: {
        setInterval: (callback, intervalMs) => {
          expect(intervalMs).toBe(25);
          ticks.push(callback);
          return "rearm-handle";
        },
        clearInterval: (handle) => { cleared = handle; },
      },
    });

    poke();
    await flushChain();
    expect(fired).toBe(0);

    ticks[0]?.();
    await flushChain();
    expect(rearmPokes).toBe(0);
    expect(fired).toBe(0);

    turnActive = false;
    ticks[0]?.();
    await flushChain();
    expect(rearmPokes).toBe(1);
    expect(fired).toBe(1);
    expect(store.getGoal()?.status).toBe("Complete");

    stop();
    expect(cleared).toBe("rearm-handle");
  });

  it("the same EMBER_GOAL_CONTINUATION kill switch suppresses re-arm pokes", async () => {
    const ticks: Array<() => void> = [];
    let pokes = 0;
    type Rearm = (options: {
      poke: () => void;
      featureEnabled: () => boolean;
      scheduler: {
        setInterval: (callback: () => void, intervalMs: number) => unknown;
        clearInterval: (handle: unknown) => void;
      };
    }) => () => void;
    const startRearm = (continuationWiring as unknown as {
      startGoalContinuationRearm: Rearm;
    }).startGoalContinuationRearm;
    const stop = startRearm({
      poke: () => { pokes += 1; },
      featureEnabled: () => false,
      scheduler: {
        setInterval: (callback) => { ticks.push(callback); return "disabled"; },
        clearInterval: () => {},
      },
    });

    ticks[0]?.();
    await flushChain();
    expect(pokes).toBe(0);
    stop();
  });
});
describe("createGoalContinuationPoke — receipt-store wiring (spec §7.1)", () => {
  function fakeWriter(): GoalReceiptWriter & { rows: Array<{ event: string; goalId?: string; detail?: Record<string, unknown> }> } {
    const rows: Array<{ event: string; goalId?: string; detail?: Record<string, unknown> }> = [];
    return {
      rows,
      filePath: "scratch/fake-receipts.jsonl",
      append: (event, goalId, detail) => {
        rows.push({ event, goalId, detail });
      },
    };
  }

  it("receipts a fired continuation as continuation_fired with its kind", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    const created = store.createGoal("reach the summit", { tokenBudget: 100 });
    if (!created.ok) throw new Error("test setup: createGoal failed");
    const writer = fakeWriter();

    const poke = createGoalContinuationPoke({
      engine: createGoalContinuationEngine(),
      getStore: () => store,
      getEligibilitySignals: () => eligible(),
      startTurn: async () => { store.recordUsage(100); },
      getReceiptWriter: () => writer,
    });

    poke();
    await flushChain();

    expect(writer.rows[0]).toEqual({ event: "continuation_fired", goalId: created.goal.goalId, detail: { kind: "continue" } });
  });

  it("receipts a skip as continuation_skipped when a goal exists, but never when there is no goal at all", async () => {
    const storeNoGoal = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    const writerNoGoal = fakeWriter();
    createGoalContinuationPoke({
      engine: createGoalContinuationEngine(),
      getStore: () => storeNoGoal,
      getEligibilitySignals: () => eligible(),
      startTurn: async () => {},
      getReceiptWriter: () => writerNoGoal,
    })();
    await flushChain();
    expect(writerNoGoal.rows).toEqual([]); // every ordinary non-goal turn stays silent

    const storeWithGoal = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    const createdWithGoal = storeWithGoal.createGoal("reach the summit");
    if (!createdWithGoal.ok) throw new Error("test setup: createGoal failed");
    const writerWithGoal = fakeWriter();
    createGoalContinuationPoke({
      engine: createGoalContinuationEngine(),
      getStore: () => storeWithGoal,
      getEligibilitySignals: () => eligible({ queuedUserInput: true }),
      startTurn: async () => {},
      getReceiptWriter: () => writerWithGoal,
    })();
    await flushChain();
    expect(writerWithGoal.rows).toEqual([
      { event: "continuation_skipped", goalId: createdWithGoal.goal.goalId, detail: { reason: "queued_user_input" } },
    ]);
  });
});

describe("isGoalContinuationFeatureEnabled", () => {
  const KEY = "EMBER_GOAL_CONTINUATION";

  function withEnv<T>(value: string | undefined, fn: () => T): T {
    const saved = process.env[KEY];
    if (value === undefined) delete process.env[KEY]; else process.env[KEY] = value;
    try {
      return fn();
    } finally {
      if (saved === undefined) delete process.env[KEY]; else process.env[KEY] = saved;
    }
  }

  it("is enabled by default when the env var is unset", () => {
    expect(withEnv(undefined, () => isGoalContinuationFeatureEnabled())).toBe(true);
  });

  it("EMBER_GOAL_CONTINUATION='0' disables it", () => {
    expect(withEnv("0", () => isGoalContinuationFeatureEnabled())).toBe(false);
  });

  it("any other value leaves it enabled", () => {
    expect(withEnv("1", () => isGoalContinuationFeatureEnabled())).toBe(true);
    expect(withEnv("false", () => isGoalContinuationFeatureEnabled())).toBe(true);
  });
});
