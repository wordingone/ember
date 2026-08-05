// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/goal-organ-floor-conformance-642.test.ts — audit deliverable for issue
// #642 (refs #211): a clause-by-clause receipt suite mapping every floor clause
// to an EXECUTED test that would FAIL if the clause were violated. This file is
// the audit's evidence, separate from (and in addition to) the pre-existing
// goal-organ unit tests — each `describe` block below is tagged with its clause
// number so the conformance table in
// docs/archive/goal/goal-organ-floor-conformance-20260710.md can cite it directly.
//
// FLOOR SOURCE: the six frozen clauses enumerated in issue #642's body, which
// are the audit-scoped restatement of docs/goal-mode-mechanism.md ("Selection
// and persistence" -> clauses 1-2, "Continuation loop" -> clauses 3-6). The
// 2026-07-10 draft of this file also cited "GOAL.md §6"; that citation is
// retired here because GOAL.md §6 on current master is "Clean genesis and
// frozen-reference boundary", which has nothing to do with the goal organ.
// docs/goal-mode-mechanism.md is the sole document floor.
//
// AUDIT DISCIPLINE (per issue #642): this file never fixes anything. Where a
// clause is NOT enforced by code today, the test demonstrating that gap is
// committed here too — `.skip`, with a comment naming the filed sub-issue —
// so the gap is never silent and the suite still runs green.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import {
  createGoalStore,
  createInMemoryGoalPersistence,
  isLegalTransition,
  BLOCKED_TURNS_THRESHOLD,
  type GoalStatus,
} from "./goal-store.ts";
import { createGoalContinuationEngine, type ContinuationEligibilitySignals, type MaybeContinueDeps } from "./goal-continuation.ts";
import {
  createGoalContinuationPoke,
  startGoalContinuationRearm,
  type GoalContinuationRearmScheduler,
} from "./goal-continuation-wiring.ts";
import { GetGoalTool, CreateGoalTool, UpdateGoalTool, GOAL_TOOLS } from "../tools/goal-tools.ts";
import { setGoalStoreForTests, resetGoalRuntimeForTests } from "./goal-runtime.ts";
import type { ToolUseContext } from "./tool-interface.ts";

function fakeContext(overrides: Partial<ToolUseContext> = {}): ToolUseContext {
  return {
    options: {},
    abortController: new AbortController(),
    getAppState: () => ({}),
    setAppState: async () => {},
    messages: [],
    ...overrides,
  };
}

function eligible(overrides: Partial<ContinuationEligibilitySignals> = {}): ContinuationEligibilitySignals {
  return {
    featureEnabled: true,
    planMode: false,
    turnActive: false,
    queuedUserInput: false,
    ...overrides,
  };
}

afterEach(() => {
  resetGoalRuntimeForTests();
});

// ===========================================================================
// CLAUSE 1 — Persistent objective IMMUTABLE to the executor
// (GOAL.md §6 / docs/goal-mode-mechanism.md §1-§2)
// Code path: core/goal-store.ts (updateStatus signature carries no objective
// param) + tools/goal-tools.ts (update_goal's zod schema has no objective
// field; GOAL_TOOLS exposes no model-side objective-editing tool at all).
// ===========================================================================

describe("CLAUSE 1 — objective immutable to the executor", () => {
  it("the model-side tool surface (GOAL_TOOLS) exposes exactly get/create/update — no edit/set-objective tool exists for the model", () => {
    const names = GOAL_TOOLS.map((t) => t.name).sort();
    expect(names).toEqual(["create_goal", "get_goal", "update_goal"]);
  });

  it("update_goal REJECTS a payload carrying an objective field (schema has no such key, .strict())", () => {
    const result = UpdateGoalTool.validateInput?.({
      status: "Paused",
      objective: "attempted executor rewrite",
    });
    expect(result?.result).toBe(false);
  });

  it("a full round-trip of every legal status-only transition never changes the objective text", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("the one true objective");
    setGoalStoreForTests(store);

    await UpdateGoalTool.call({ status: "Paused" }, fakeContext());
    await UpdateGoalTool.call({ status: "Active" }, fakeContext());
    await UpdateGoalTool.call({ status: "Blocked", reason: "x" }, fakeContext());
    await UpdateGoalTool.call({ status: "Blocked", reason: "x" }, fakeContext());
    await UpdateGoalTool.call({ status: "Blocked", reason: "x" }, fakeContext());

    expect(store.getGoal()?.objective).toBe("the one true objective");
  });

  it("editObjective — the ONLY code path that can change the objective — is never reachable from any GOAL_TOOLS entry", () => {
    // Structural proof: every model tool call is routed through goal-runtime's
    // getGoalStore(); none of get_goal/create_goal/update_goal's implementations
    // reference editObjective (grepped at audit time — see conformance doc).
    // This test asserts the OBSERVABLE behavior side of that structural fact:
    // calling every model tool in sequence, on a store whose editObjective is
    // instrumented, proves it is never invoked by the model surface.
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    let editObjectiveCalls = 0;
    const instrumented = {
      ...store,
      editObjective: (obj: string) => {
        editObjectiveCalls += 1;
        return store.editObjective(obj);
      },
    };
    setGoalStoreForTests(instrumented);

    void CreateGoalTool.call({ objective: "start" }, fakeContext());
    return Promise.resolve()
      .then(() => UpdateGoalTool.call({ status: "Paused" }, fakeContext()))
      .then(() => UpdateGoalTool.call({ status: "Active" }, fakeContext()))
      .then(() => GetGoalTool.call({}, fakeContext()))
      .then(() => {
        expect(editObjectiveCalls).toBe(0);
      });
  });
});

// ===========================================================================
// CLAUSE 2 — STATUS-ONLY transitions (no free-form transitions)
// Code path: core/goal-store.ts LEGAL_TRANSITIONS + isLegalTransition;
// tools/goal-tools.ts MODEL_SETTABLE_STATUSES (a closed enum, not a free string).
// ===========================================================================

describe("CLAUSE 2 — status-only transitions, closed transition table", () => {
  const ALL_STATUSES: GoalStatus[] = ["Active", "Paused", "Blocked", "UsageLimited", "BudgetLimited", "Complete"];

  it("every transition not in the frozen legal set is rejected — exhaustive 6x6", () => {
    const LEGAL_PAIRS = new Set([
      "Active->Paused", "Active->Blocked", "Active->UsageLimited", "Active->BudgetLimited", "Active->Complete",
      "Paused->Active", "Blocked->Active", "UsageLimited->Active", "BudgetLimited->Active", "BudgetLimited->Complete",
    ]);
    let checked = 0;
    for (const from of ALL_STATUSES) {
      for (const to of ALL_STATUSES) {
        expect(isLegalTransition(from, to)).toBe(LEGAL_PAIRS.has(`${from}->${to}`));
        checked += 1;
      }
    }
    expect(checked).toBe(36);
  });

  it("the model-settable status enum rejects any value outside {Active,Paused,Blocked,Complete} — no free-form string reaches the store", () => {
    for (const forbidden of ["UsageLimited", "BudgetLimited", "InProgress", "Cancelled", "anything"]) {
      const result = UpdateGoalTool.validateInput?.({ status: forbidden });
      expect(result?.result).toBe(false);
    }
  });

  it("update_goal never accepts free-form transition metadata beyond status+reason (.strict() schema)", () => {
    const result = UpdateGoalTool.validateInput?.({
      status: "Paused",
      transition: "custom-free-form-shape",
    });
    expect(result?.result).toBe(false);
  });
});

// ===========================================================================
// CLAUSE 3 — Event-driven continue-on-idle with user preemption
// Code path: core/goal-continuation.ts (maybeContinueIfIdle) +
// core/goal-continuation-wiring.ts (createGoalContinuationPoke, the
// self-chaining seam). "Event-driven, no scheduler" per spec §3.
// ===========================================================================

describe("CLAUSE 3a — no polling: the engine never installs a timer of its own", () => {
  it("a full multi-turn autonomous chain completes without ANY call to setInterval or setTimeout", async () => {
    const originalSetInterval = globalThis.setInterval;
    const originalSetTimeout = globalThis.setTimeout;
    let intervalCalls = 0;
    let timeoutCalls = 0;
    // @ts-expect-error -- intentional instrumentation shim for the duration of this test
    globalThis.setInterval = (...args: unknown[]) => {
      intervalCalls += 1;
      // @ts-expect-error -- forwarding to the real implementation
      return originalSetInterval(...args);
    };
    // @ts-expect-error -- intentional instrumentation shim for the duration of this test
    globalThis.setTimeout = (...args: unknown[]) => {
      timeoutCalls += 1;
      // @ts-expect-error -- forwarding to the real implementation
      return originalSetTimeout(...args);
    };

    try {
      const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
      store.createGoal("reach the summit", { tokenBudget: 300 });
      const poke = createGoalContinuationPoke({
        engine: createGoalContinuationEngine(),
        getStore: () => store,
        getEligibilitySignals: () => eligible(),
        startTurn: async () => {
          store.recordUsage(100);
        },
      });
      poke();
      for (let i = 0; i < 10; i++) {
        await Promise.resolve();
        await Promise.resolve();
      }
    } finally {
      globalThis.setInterval = originalSetInterval;
      globalThis.setTimeout = originalSetTimeout;
    }

    expect(intervalCalls).toBe(0);
    expect(timeoutCalls).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// CLAUSE 3c — the ONE scheduler in the organ, and the gates that keep it
// floor-compatible. ORGAN EVOLUTION since this file's 2026-07-10 draft:
// startGoalContinuationRearm (goal-continuation-wiring.ts, added by PR #1158
// for issue #279) installs a 5s setInterval and is live in production
// (screens/repl.ts's useEffect). The clause-3a test above is scoped to the
// ENGINE and stays true, but on its own it would now give a false all-clear
// for the clause as a whole — so the deviation is pinned here explicitly
// rather than left to a passing test's silence.
//
// The deviation is recorded as DEVIATION-3c in
// docs/archive/goal/goal-organ-floor-conformance-20260710.md row 3. These tests fix the
// boundary that makes it subordinate rather than a second, competing loop:
// the timer is injectable, it cannot bypass preemption, the kill switch
// suppresses every tick, and no timer outlives its session.
// ---------------------------------------------------------------------------

describe("CLAUSE 3c — the re-arm timer is subordinate: it can never fire a continuation the event path would have refused", () => {
  function fakeScheduler(): GoalContinuationRearmScheduler & { tick(): void; cleared: () => boolean } {
    let cb: (() => void) | null = null;
    let cleared = false;
    return {
      setInterval: (callback: () => void) => {
        cb = callback;
        return "handle";
      },
      clearInterval: () => {
        cleared = true;
      },
      tick: () => cb?.(),
      cleared: () => cleared,
    };
  }

  it("the scheduler is fully injectable — a re-arm under test never reaches globalThis.setInterval", () => {
    const original = globalThis.setInterval;
    let globalCalls = 0;
    // @ts-expect-error -- intentional instrumentation shim for the duration of this test
    globalThis.setInterval = (...args: unknown[]) => {
      globalCalls += 1;
      // @ts-expect-error -- forwarding to the real implementation
      return original(...args);
    };
    try {
      const scheduler = fakeScheduler();
      const stop = startGoalContinuationRearm({
        poke: () => {},
        featureEnabled: () => true,
        scheduler,
      });
      stop();
    } finally {
      globalThis.setInterval = original;
    }
    expect(globalCalls).toBe(0);
  });

  it("a tick whose shouldPoke gate is closed NEVER calls the poke — user preemption survives the polling layer", () => {
    const scheduler = fakeScheduler();
    let pokes = 0;
    let preempted = true;
    const stop = startGoalContinuationRearm({
      poke: () => { pokes += 1; },
      featureEnabled: () => true,
      shouldPoke: () => !preempted, // production wires queuedUserInput/turnActive/status here
      scheduler,
    });

    scheduler.tick();
    scheduler.tick();
    expect(pokes).toBe(0); // preempted: the timer is inert, not merely delayed

    preempted = false;
    scheduler.tick();
    expect(pokes).toBe(1);
    stop();
  });

  it("the EMBER_GOAL_CONTINUATION kill switch suppresses every tick — disabling the feature disables the scheduler too", () => {
    const scheduler = fakeScheduler();
    let pokes = 0;
    const stop = startGoalContinuationRearm({
      poke: () => { pokes += 1; },
      featureEnabled: () => false,
      shouldPoke: () => true,
      scheduler,
    });
    scheduler.tick();
    scheduler.tick();
    expect(pokes).toBe(0);
    stop();
  });

  it("the returned cleanup clears the interval — no timer outlives its session", () => {
    const scheduler = fakeScheduler();
    const stop = startGoalContinuationRearm({
      poke: () => {},
      featureEnabled: () => true,
      scheduler,
    });
    expect(scheduler.cleared()).toBe(false);
    stop();
    expect(scheduler.cleared()).toBe(true);
  });

  it("a non-finite or non-positive interval is refused outright — the deviation cannot be widened into a busy loop", () => {
    for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(() =>
        startGoalContinuationRearm({ poke: () => {}, intervalMs: bad, scheduler: fakeScheduler() }),
      ).toThrow(RangeError);
    }
  });
});

describe("CLAUSE 3b — idle pokes continuation without any external caller polling for status", () => {
  let store: ReturnType<typeof createGoalStore>;
  beforeEach(() => {
    store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
  });

  it("a single poke, with no further external calls, autonomously drives the goal to BudgetLimited", async () => {
    store.createGoal("reach the summit", { tokenBudget: 250 });
    let fires = 0;
    const poke = createGoalContinuationPoke({
      engine: createGoalContinuationEngine(),
      getStore: () => store,
      getEligibilitySignals: () => eligible(),
      startTurn: async () => {
        fires += 1;
        store.recordUsage(100);
      },
    });
    poke(); // the ONE external kick
    for (let i = 0; i < 10; i++) await Promise.resolve();
    expect(fires).toBeGreaterThanOrEqual(3); // >=3 autonomous continuations, zero further external input
    expect(store.getGoal()?.status).toBe("BudgetLimited");
  });

  it("queued user input, arriving between two eligibility checks, preempts the very next hop unconditionally", async () => {
    store.createGoal("reach the summit"); // unbounded budget -- would otherwise chain forever
    let fireCount = 0;
    let userJustTyped = false;
    const engine = createGoalContinuationEngine();
    const outcome1 = await engine.maybeContinueIfIdle({
      store,
      getEligibilitySignals: () => eligible({ queuedUserInput: userJustTyped }),
      startTurn: async () => { fireCount += 1; },
    } satisfies MaybeContinueDeps);
    expect(outcome1.fired).toBe(true);

    userJustTyped = true; // simulates a live keystroke landing between turns
    const outcome2 = await engine.maybeContinueIfIdle({
      store,
      getEligibilitySignals: () => eligible({ queuedUserInput: userJustTyped }),
      startTurn: async () => { fireCount += 1; },
    } satisfies MaybeContinueDeps);
    expect(outcome2).toEqual({ fired: false, reason: "queued_user_input" });
    expect(fireCount).toBe(1);
  });
});

// ===========================================================================
// CLAUSE 4 — Completion audit must PROVE completion
// "an audit that merely fails to find remaining work is non-conforming BY
// DEFINITION" (issue #642). Code path searched: core/goal-store.ts
// updateStatus(), tools/goal-tools.ts UpdateGoalTool — NEITHER has any
// evidence/proof parameter or verification step for the Complete transition,
// unlike Blocked (which DOES have a code-enforced 3-consecutive-turn counter,
// see CLAUSE 5 below). The completion-audit requirement lives ENTIRELY in
// prompt doctrine text (core/goal-continuation-prompt.ts) with zero code-level
// enforcement — the model can call update_goal(status:"Complete") with no
// evidence field, no prior audit call, and no verification of any kind, and
// the transition succeeds unconditionally as long as it is state-machine-legal.
//
// GAP CONFIRMED — see docs/archive/goal/goal-organ-floor-conformance-20260710.md row 4.
// Tracked by sub-issue #663 (OPEN as of the 2026-08-03 re-run, which confirmed
// the gap still reproduces unchanged against current master). Test kept here,
// SKIPPED, so the gap is never silent and the suite stays green. Un-skip to
// reproduce.
// ===========================================================================

describe("CLAUSE 4 — GAP: update_goal(Complete) has zero code-level completion-proof requirement", () => {
  it.skip("[GAP #663 - tracked, see docs/archive/goal/goal-organ-floor-conformance-20260710.md row 4] update_goal(status:'Complete') should be REJECTED absent any recorded completion-audit evidence", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("ship a feature that provably does not exist yet");
    setGoalStoreForTests(store);

    // No completion audit was ever recorded anywhere in the store (no evidence
    // field exists on GoalRecord at all -- see core/goal-store.ts's data model).
    // A conforming organ MUST reject this call, or at minimum require the
    // caller to have supplied audit evidence. The current implementation does
    // neither: it accepts the transition unconditionally.
    const result = await UpdateGoalTool.call({ status: "Complete" }, fakeContext());
    const data = result.data as { ok: boolean; message?: string };

    // This is the assertion that FAILS today, proving the gap:
    expect(data.ok).toBe(false);
    expect(store.getGoal()?.status).not.toBe("Complete");
  });
});

// ===========================================================================
// CLAUSE 5 — Blocked only after repeated consecutive impasse
// (single failure != blocked)
// Code path: core/goal-store.ts noteBlocked()/BLOCKED_TURNS_THRESHOLD +
// tools/goal-tools.ts UpdateGoalTool's Blocked-specific gate.
// ===========================================================================

describe("CLAUSE 5 — Blocked requires the SAME blocker on >=3 consecutive goal turns", () => {
  it(`a single impasse (1 call) is NEVER sufficient to reach Blocked (threshold=${BLOCKED_TURNS_THRESHOLD})`, async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");
    setGoalStoreForTests(store);

    const result = await UpdateGoalTool.call({ status: "Blocked", reason: "single one-off failure" }, fakeContext());
    expect((result.data as { ok: boolean }).ok).toBe(false);
    expect(store.getGoal()?.status).toBe("Active");
  });

  it("the SAME blocker repeated exactly BLOCKED_TURNS_THRESHOLD times transitions to Blocked; one fewer does not", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");
    setGoalStoreForTests(store);

    for (let i = 0; i < BLOCKED_TURNS_THRESHOLD - 1; i++) {
      const r = await UpdateGoalTool.call({ status: "Blocked", reason: "same wall" }, fakeContext());
      expect((r.data as { ok: boolean }).ok).toBe(false);
    }
    expect(store.getGoal()?.status).toBe("Active");

    const finalCall = await UpdateGoalTool.call({ status: "Blocked", reason: "same wall" }, fakeContext());
    expect((finalCall.data as { ok: boolean }).ok).toBe(true);
    expect(store.getGoal()?.status).toBe("Blocked");
  });

  it("a DIFFERENT blocking reason each turn never accumulates toward Blocked (rotating causes are not an impasse)", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");
    setGoalStoreForTests(store);

    const reasons = ["reason A", "reason B", "reason C", "reason D", "reason E"];
    for (const reason of reasons) {
      const r = await UpdateGoalTool.call({ status: "Blocked", reason }, fakeContext());
      expect((r.data as { ok: boolean }).ok).toBe(false);
    }
    expect(store.getGoal()?.status).toBe("Active");
  });

  it("resuming to Active resets the impasse audit to zero — a fresh 3-in-a-row is required again", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit");
    setGoalStoreForTests(store);

    await UpdateGoalTool.call({ status: "Blocked", reason: "wall" }, fakeContext());
    await UpdateGoalTool.call({ status: "Blocked", reason: "wall" }, fakeContext());
    await UpdateGoalTool.call({ status: "Blocked", reason: "wall" }, fakeContext());
    expect(store.getGoal()?.status).toBe("Blocked");

    await UpdateGoalTool.call({ status: "Active" }, fakeContext()); // resume
    expect(store.getGoal()?.consecutiveBlockedTurns).toBe(0);

    const single = await UpdateGoalTool.call({ status: "Blocked", reason: "wall" }, fakeContext());
    expect((single.data as { ok: boolean }).ok).toBe(false); // one call post-resume is not enough
    expect(store.getGoal()?.status).toBe("Active");
  });
});

// ===========================================================================
// CLAUSE 6 — Budget as soft-landing status (never a hard kill)
// Code path: core/goal-continuation.ts's overBudget branch (Active ->
// BudgetLimited + renderBudgetWrapUpPrompt), core/goal-store.ts's transition
// table (BudgetLimited is a real status, not a process exit).
// ===========================================================================

describe("CLAUSE 6 — budget exhaustion degrades to BudgetLimited status, never a kill", () => {
  it("crossing the token budget transitions Active -> BudgetLimited and STILL fires a turn (a wrap-up steer), never aborts silently", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit", { tokenBudget: 1000 });
    store.recordUsage(1000);
    const engine = createGoalContinuationEngine();

    let startTurnWasCalled = false;
    let capturedPrompt = "";
    const outcome = await engine.maybeContinueIfIdle({
      store,
      getEligibilitySignals: () => eligible(),
      startTurn: async (prompt) => {
        startTurnWasCalled = true;
        capturedPrompt = prompt;
      },
    });

    expect(outcome.fired).toBe(true); // NOT a kill -- the loop keeps running one more turn
    expect(startTurnWasCalled).toBe(true);
    expect(store.getGoal()?.status).toBe("BudgetLimited"); // a real status, not a process exit
    expect(capturedPrompt.toLowerCase()).toContain("soft landing");
    expect(capturedPrompt).toContain("Do NOT call update_goal(status: \"Complete\")");
  });

  it("the wrap-up prompt explicitly forbids new substantive work and forbids completion-fraud at the budget edge", async () => {
    const store = createGoalStore({ persistence: createInMemoryGoalPersistence() });
    store.createGoal("reach the summit", { tokenBudget: 500 });
    store.recordUsage(500);
    const engine = createGoalContinuationEngine();

    let capturedPrompt = "";
    await engine.maybeContinueIfIdle({
      store,
      getEligibilitySignals: () => eligible(),
      startTurn: async (prompt) => { capturedPrompt = prompt; },
    });

    expect(capturedPrompt).toContain("do NOT start");
    expect(capturedPrompt.toLowerCase()).toContain("never itself a justification for a completion claim");
  });

  it("BudgetLimited is a real state a session can resume FROM — Active is a legal next transition (never terminal)", () => {
    expect(isLegalTransition("BudgetLimited", "Active")).toBe(true);
  });

  it("BudgetLimited is reachable ONLY through the system-managed continuation path, never through the model's update_goal tool directly", () => {
    // MODEL_SETTABLE_STATUSES (tools/goal-tools.ts) excludes BudgetLimited --
    // a model cannot self-report hitting budget to dodge the (doctrine-level)
    // completion audit; only a real token tally crossing the real budget can
    // fire this transition (core/goal-continuation.ts's overBudget check).
    const result = UpdateGoalTool.validateInput?.({ status: "BudgetLimited" });
    expect(result?.result).toBe(false);
  });
});
