// core/goal-continuation.test.ts — eligibility-race tests for the event-driven
// continuation engine (ember issue #211). Covers acceptance leg (a) unit
// tests (state-machine-adjacent eligibility) and leg (c) user-preemption.

import { describe, it, expect, beforeEach } from "bun:test";
import {
  createGoalContinuationEngine,
  type MaybeContinueDeps,
  type ContinuationEligibilitySignals,
} from "./goal-continuation.ts";
import { createGoalStore, createInMemoryGoalPersistence, type GoalStore } from "./goal-store.ts";

function eligible(overrides: Partial<ContinuationEligibilitySignals> = {}): ContinuationEligibilitySignals {
  return {
    featureEnabled: true,
    planMode: false,
    turnActive: false,
    queuedUserInput: false,
    ...overrides,
  };
}

function makeDeps(
  store: GoalStore,
  signals: ContinuationEligibilitySignals,
  startTurn: (prompt: string) => Promise<void> = async () => {},
): MaybeContinueDeps {
  return { store, getEligibilitySignals: () => signals, startTurn };
}

let store: GoalStore;

beforeEach(() => {
  store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
});

// ---------------------------------------------------------------------------
// Eligibility gates
// ---------------------------------------------------------------------------

describe("maybeContinueIfIdle — eligibility gates", () => {
  it("skips when the feature is disabled", async () => {
    store.createGoal("reach the summit");
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(
      makeDeps(store, eligible({ featureEnabled: false })),
    );
    expect(outcome).toEqual({ fired: false, reason: "feature_disabled" });
  });

  it("skips in plan mode", async () => {
    store.createGoal("reach the summit");
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(makeDeps(store, eligible({ planMode: true })));
    expect(outcome).toEqual({ fired: false, reason: "plan_mode" });
  });

  it("skips when a turn is already active", async () => {
    store.createGoal("reach the summit");
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(makeDeps(store, eligible({ turnActive: true })));
    expect(outcome).toEqual({ fired: false, reason: "turn_active" });
  });

  it("skips when no goal exists", async () => {
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(makeDeps(store, eligible()));
    expect(outcome).toEqual({ fired: false, reason: "no_goal" });
  });

  it("skips when the goal exists but is not Active (e.g. Paused)", async () => {
    store.createGoal("reach the summit");
    store.updateStatus("Paused");
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(makeDeps(store, eligible()));
    expect(outcome).toEqual({ fired: false, reason: "goal_not_active" });
  });
});

// ---------------------------------------------------------------------------
// User preemption — acceptance leg (c): "queued user input suppresses
// continuation, always"
// ---------------------------------------------------------------------------

describe("maybeContinueIfIdle — user preemption (acceptance leg c)", () => {
  it("skips unconditionally when user input is queued, even with a fully eligible Active goal", async () => {
    store.createGoal("reach the summit");
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(
      makeDeps(store, eligible({ queuedUserInput: true })),
    );
    expect(outcome).toEqual({ fired: false, reason: "queued_user_input" });
  });

  it("queued user input wins even over multiple other-eligible signals simultaneously", async () => {
    store.createGoal("reach the summit");
    const engine = createGoalContinuationEngine();
    // Only queuedUserInput is the disqualifier; everything else says "go".
    const outcome = await engine.maybeContinueIfIdle(
      makeDeps(
        store,
        eligible({ featureEnabled: true, planMode: false, turnActive: false, queuedUserInput: true }),
      ),
    );
    expect(outcome.fired).toBe(false);
    if (!outcome.fired) expect(outcome.reason).toBe("queued_user_input");
  });

  it("never calls startTurn when preempted by queued user input", async () => {
    store.createGoal("reach the summit");
    let called = false;
    const engine = createGoalContinuationEngine();
    await engine.maybeContinueIfIdle(
      makeDeps(store, eligible({ queuedUserInput: true }), async () => {
        called = true;
      }),
    );
    expect(called).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// goal cleared/edited mid-check race (spec §3 step 3)
// ---------------------------------------------------------------------------

describe("maybeContinueIfIdle — goal changed mid-check race", () => {
  it("skips safely when the goal is CLEARED between the first read and the re-read", async () => {
    store.createGoal("reach the summit");
    let calls = 0;
    const racyStore: GoalStore = {
      ...store,
      getGoal: () => {
        calls += 1;
        if (calls === 1) return store.getGoal(); // first read: goal present, Active
        return null; // re-read: cleared concurrently
      },
    };
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(makeDeps(racyStore, eligible()));
    expect(outcome).toEqual({ fired: false, reason: "goal_changed_mid_check" });
  });

  it("skips safely when the goal's STATUS changed between the first read and the re-read", async () => {
    store.createGoal("reach the summit");
    const firstSnapshot = store.getGoal()!;
    let calls = 0;
    const racyStore: GoalStore = {
      ...store,
      getGoal: () => {
        calls += 1;
        if (calls === 1) return firstSnapshot; // Active
        return { ...firstSnapshot, status: "Paused" }; // changed concurrently
      },
    };
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(makeDeps(racyStore, eligible()));
    expect(outcome).toEqual({ fired: false, reason: "goal_changed_mid_check" });
  });

  it("skips safely when a DIFFERENT goal (new goalId) appears between reads", async () => {
    store.createGoal("reach the summit");
    const firstSnapshot = store.getGoal()!;
    let calls = 0;
    const racyStore: GoalStore = {
      ...store,
      getGoal: () => {
        calls += 1;
        if (calls === 1) return firstSnapshot;
        return { ...firstSnapshot, goalId: "a-completely-different-goal" };
      },
    };
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(makeDeps(racyStore, eligible()));
    expect(outcome).toEqual({ fired: false, reason: "goal_changed_mid_check" });
  });

  it("never calls startTurn on a mid-check race", async () => {
    store.createGoal("reach the summit");
    let calls = 0;
    const racyStore: GoalStore = {
      ...store,
      getGoal: () => {
        calls += 1;
        return calls === 1 ? store.getGoal() : null;
      },
    };
    let called = false;
    const engine = createGoalContinuationEngine();
    await engine.maybeContinueIfIdle(makeDeps(racyStore, eligible(), async () => { called = true; }));
    expect(called).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Double-fire semaphore
// ---------------------------------------------------------------------------

describe("maybeContinueIfIdle — double-fire semaphore", () => {
  it("a second concurrent call is skipped while the first is still in-flight", async () => {
    store.createGoal("reach the summit");
    const engine = createGoalContinuationEngine();

    let releaseFirstTurn: () => void = () => {};
    const firstTurnGate = new Promise<void>((resolve) => {
      releaseFirstTurn = resolve;
    });

    const firstCall = engine.maybeContinueIfIdle(
      makeDeps(store, eligible(), async () => {
        await firstTurnGate; // hold the lock open
      }),
    );

    // Give the first call's microtasks a chance to acquire the lock before
    // firing the second attempt.
    await Promise.resolve();
    expect(engine.isInFlight()).toBe(true);

    const secondOutcome = await engine.maybeContinueIfIdle(makeDeps(store, eligible()));
    expect(secondOutcome).toEqual({ fired: false, reason: "already_in_flight" });

    releaseFirstTurn();
    const firstOutcome = await firstCall;
    expect(firstOutcome.fired).toBe(true);
  });

  it("the semaphore releases after a successful fire — a subsequent call can fire again", async () => {
    store.createGoal("reach the summit");
    const engine = createGoalContinuationEngine();

    await engine.maybeContinueIfIdle(makeDeps(store, eligible()));
    expect(engine.isInFlight()).toBe(false);

    const second = await engine.maybeContinueIfIdle(makeDeps(store, eligible()));
    expect(second.fired).toBe(true);
  });

  it("the semaphore releases even when startTurn throws — never leaves the engine permanently locked", async () => {
    store.createGoal("reach the summit");
    const engine = createGoalContinuationEngine();

    await expect(
      engine.maybeContinueIfIdle(
        makeDeps(store, eligible(), async () => {
          throw new Error("turn blew up");
        }),
      ),
    ).rejects.toThrow("turn blew up");

    expect(engine.isInFlight()).toBe(false);
    const next = await engine.maybeContinueIfIdle(makeDeps(store, eligible()));
    expect(next.fired).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Normal fire — continuation prompt
// ---------------------------------------------------------------------------

describe("maybeContinueIfIdle — normal continuation fire", () => {
  it("fires with kind:'continue' and a prompt containing the objective", async () => {
    store.createGoal("reach the summit");
    let capturedPrompt = "";
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(
      makeDeps(store, eligible(), async (prompt) => {
        capturedPrompt = prompt;
      }),
    );
    expect(outcome.fired).toBe(true);
    if (outcome.fired) {
      expect(outcome.kind).toBe("continue");
      expect(outcome.goalId).toBe(store.getGoal()!.goalId);
    }
    expect(capturedPrompt).toContain("reach the summit");
    expect(capturedPrompt).toContain("GOAL CONTINUATION");
  });

  it("does not transition goal status on an ordinary (under-budget) fire", async () => {
    store.createGoal("reach the summit", { tokenBudget: 10_000 });
    const engine = createGoalContinuationEngine();
    await engine.maybeContinueIfIdle(makeDeps(store, eligible()));
    expect(store.getGoal()?.status).toBe("Active");
  });
});

// ---------------------------------------------------------------------------
// Budget wrap-up fire
// ---------------------------------------------------------------------------

describe("maybeContinueIfIdle — budget wrap-up fire", () => {
  it("transitions Active -> BudgetLimited and fires the wrap-up prompt when usage >= tokenBudget", async () => {
    store.createGoal("reach the summit", { tokenBudget: 1000 });
    store.recordUsage(1000);
    let capturedPrompt = "";
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(
      makeDeps(store, eligible(), async (prompt) => {
        capturedPrompt = prompt;
      }),
    );
    expect(outcome.fired).toBe(true);
    if (outcome.fired) expect(outcome.kind).toBe("budget_wrapup");
    expect(store.getGoal()?.status).toBe("BudgetLimited");
    expect(capturedPrompt.toLowerCase()).toContain("soft landing");
  });

  it("does NOT fire a wrap-up when usage is under budget", async () => {
    store.createGoal("reach the summit", { tokenBudget: 1000 });
    store.recordUsage(500);
    const engine = createGoalContinuationEngine();
    const outcome = await engine.maybeContinueIfIdle(makeDeps(store, eligible()));
    expect(outcome.fired).toBe(true);
    if (outcome.fired) expect(outcome.kind).toBe("continue");
    expect(store.getGoal()?.status).toBe("Active");
  });

  it("a subsequent maybe-continue call after BudgetLimited skips (not Active) until resumed", async () => {
    store.createGoal("reach the summit", { tokenBudget: 1000 });
    store.recordUsage(1000);
    const engine = createGoalContinuationEngine();
    await engine.maybeContinueIfIdle(makeDeps(store, eligible()));
    const next = await engine.maybeContinueIfIdle(makeDeps(store, eligible()));
    expect(next).toEqual({ fired: false, reason: "goal_not_active" });
  });
});
