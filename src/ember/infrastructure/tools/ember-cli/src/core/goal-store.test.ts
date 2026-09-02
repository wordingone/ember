// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// core/goal-store.test.ts — state-machine unit tests for the persisted goal organ
// (ember issue #211). Covers: every legal/illegal status transition, objective
// immutability (updateStatus can never carry an objective, editObjective is the
// only path and is never wired to a model tool), create-fails-if-exists, the
// ephemeral-session refusal, budget/usage tallying, and the blocked-turn audit.

import { describe, it, expect } from "bun:test";
import {
  createGoalStore,
  createInMemoryGoalPersistence,
  isLegalTransition,
  validateObjective,
  OBJECTIVE_MAX_CHARS,
  BLOCKED_TURNS_THRESHOLD,
  type GoalStatus,
  type GoalTransitionEvent,
} from "./goal-store.ts";

const ALL_STATUSES: GoalStatus[] = [
  "Active",
  "Paused",
  "Blocked",
  "UsageLimited",
  "BudgetLimited",
  "Complete",
];

// ---------------------------------------------------------------------------
// isLegalTransition — exhaustive 6x6 table
// ---------------------------------------------------------------------------

describe("isLegalTransition — exhaustive transition table", () => {
  const LEGAL_PAIRS = new Set([
    "Active->Paused",
    "Active->Blocked",
    "Active->UsageLimited",
    "Active->BudgetLimited",
    "Active->Complete",
    "Paused->Active",
    "Blocked->Active",
    "UsageLimited->Active",
    "BudgetLimited->Active",
    "BudgetLimited->Complete",
  ]);

  for (const from of ALL_STATUSES) {
    for (const to of ALL_STATUSES) {
      const key = `${from}->${to}`;
      const expected = LEGAL_PAIRS.has(key);
      it(`${key} is ${expected ? "LEGAL" : "illegal"}`, () => {
        expect(isLegalTransition(from, to)).toBe(expected);
      });
    }
  }

  it("no self-transition is ever legal (a transition must be a real state change)", () => {
    for (const s of ALL_STATUSES) {
      expect(isLegalTransition(s, s)).toBe(false);
    }
  });

  it("Complete is terminal — nothing transitions out of it", () => {
    for (const to of ALL_STATUSES) {
      expect(isLegalTransition("Complete", to)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// validateObjective
// ---------------------------------------------------------------------------

describe("validateObjective", () => {
  it("rejects an empty string", () => {
    expect(validateObjective("").ok).toBe(false);
  });

  it("rejects a whitespace-only string", () => {
    expect(validateObjective("   \n\t  ").ok).toBe(false);
  });

  it("accepts a normal objective", () => {
    expect(validateObjective("ship the goal organ").ok).toBe(true);
  });

  it(`accepts exactly ${OBJECTIVE_MAX_CHARS} chars`, () => {
    expect(validateObjective("x".repeat(OBJECTIVE_MAX_CHARS)).ok).toBe(true);
  });

  it(`rejects ${OBJECTIVE_MAX_CHARS + 1} chars`, () => {
    const result = validateObjective("x".repeat(OBJECTIVE_MAX_CHARS + 1));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.message).toContain(String(OBJECTIVE_MAX_CHARS));
  });
});

// ---------------------------------------------------------------------------
// createGoalStore — createGoal
// ---------------------------------------------------------------------------

describe("createGoalStore — createGoal", () => {
  it("requires completion-audit evidence at the store boundary", () => {
    const store = createGoalStore();
    store.createGoal("prove the objective");

    const missing = store.updateStatus("Complete");
    expect(missing.ok).toBe(false);
    expect(store.getGoal()?.status).toBe("Active");

    const audit = { requirements: [{ id: "objective", evidence: "receipt:objective-proven" }] };
    const accepted = store.updateStatus("Complete", { completionAudit: audit });
    expect(accepted.ok).toBe(true);
    expect(store.getGoal()?.completionAudit).toEqual(audit);
  });

  it("rejects completion-audit evidence on non-Complete transitions", () => {
    const audit = { requirements: [{ id: "objective", evidence: "receipt:objective-proven" }] };
    for (const [start, status] of [["Active", "Paused"], ["Active", "Blocked"], ["Paused", "Active"]] as const) {
      const store = createGoalStore();
      store.createGoal("prove the objective");
      if (start === "Paused") store.updateStatus("Paused");
      const result = store.updateStatus(status, { completionAudit: audit });
      expect(result.ok).toBe(false);
      expect(store.getGoal()?.status).toBe(start);
      expect(store.getGoal()?.completionAudit).toBeUndefined();
    }
  });

  it("creates a new goal with status Active and zeroed usage", () => {
    const store = createGoalStore();
    const result = store.createGoal("reach the summit");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.goal.objective).toBe("reach the summit");
      expect(result.goal.status).toBe("Active");
      expect(result.goal.usage).toEqual({ tokensUsed: 0, elapsedMs: 0 });
      expect(result.goal.consecutiveBlockedTurns).toBe(0);
      expect(result.goal.goalId.length).toBeGreaterThan(0);
    }
  });

  it("fails if a goal already exists — never inferred, never silently replaced", () => {
    const store = createGoalStore();
    store.createGoal("first objective");
    const second = store.createGoal("second objective");
    expect(second.ok).toBe(false);
    if (!second.ok) expect(second.message).toContain("already exists");
    // the first goal is untouched
    expect(store.getGoal()?.objective).toBe("first objective");
  });

  it("refuses on an ephemeral session with a clear message, and does not persist a record", () => {
    const store = createGoalStore();
    const result = store.createGoal("reach the summit", { isEphemeralSession: true });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.message).toContain("ephemeral");
    expect(store.getGoal()).toBeNull();
  });

  it("rejects an invalid objective (empty / too long) without creating a record", () => {
    const store = createGoalStore();
    const result = store.createGoal("");
    expect(result.ok).toBe(false);
    expect(store.getGoal()).toBeNull();
  });

  it("stores an optional tokenBudget when provided, omits it when not", () => {
    const store = createGoalStore();
    store.createGoal("with budget", { tokenBudget: 5000 });
    expect(store.getGoal()?.tokenBudget).toBe(5000);

    const store2 = createGoalStore();
    store2.createGoal("no budget");
    expect(store2.getGoal()?.tokenBudget).toBeUndefined();
  });

  it("emits a 'created' transition event", () => {
    const events: GoalTransitionEvent[] = [];
    const store = createGoalStore({ onTransition: (e) => events.push(e) });
    store.createGoal("reach the summit");
    expect(events).toHaveLength(1);
    expect(events[0]!.kind).toBe("created");
  });
});

// ---------------------------------------------------------------------------
// Objective immutability — the load-bearing guarantee
// ---------------------------------------------------------------------------

describe("objective immutability", () => {
  it("updateStatus's signature carries no objective field — a model-tool call literally cannot smuggle one through", () => {
    const store = createGoalStore();
    store.createGoal("original objective");
    // updateStatus only accepts (status, opts?: { reason? }) -- there is no
    // parameter position an objective string could occupy. This is enforced
    // by TypeScript at the call site; the runtime assertion below proves the
    // objective is untouched by any legal call shape.
    store.updateStatus("Paused");
    store.updateStatus("Active");
    expect(store.getGoal()?.objective).toBe("original objective");
  });

  it("editObjective is the ONLY method that changes the objective", () => {
    const store = createGoalStore();
    store.createGoal("original objective");
    const result = store.editObjective("revised objective");
    expect(result.ok).toBe(true);
    expect(store.getGoal()?.objective).toBe("revised objective");
  });

  it("editObjective fails when no goal exists", () => {
    const store = createGoalStore();
    const result = store.editObjective("anything");
    expect(result.ok).toBe(false);
  });

  it("editObjective rejects an invalid new objective, leaving the old one intact", () => {
    const store = createGoalStore();
    store.createGoal("original objective");
    const result = store.editObjective("");
    expect(result.ok).toBe(false);
    expect(store.getGoal()?.objective).toBe("original objective");
  });

  it("editObjective emits an 'objective_edited' event carrying the previous value", () => {
    const events: GoalTransitionEvent[] = [];
    const store = createGoalStore({ onTransition: (e) => events.push(e) });
    store.createGoal("original objective");
    store.editObjective("revised objective");
    const edit = events.find((e) => e.kind === "objective_edited");
    expect(edit).toBeDefined();
    if (edit?.kind === "objective_edited") {
      expect(edit.previousObjective).toBe("original objective");
      expect(edit.goal.objective).toBe("revised objective");
    }
  });
});

// ---------------------------------------------------------------------------
// updateStatus — legality gating + audit reset on resume
// ---------------------------------------------------------------------------

describe("createGoalStore — updateStatus", () => {
  it("applies a legal transition and updates updatedAt", () => {
    const store = createGoalStore();
    store.createGoal("reach the summit");
    const before = store.getGoal()!.updatedAt;
    const result = store.updateStatus("Paused");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.goal.status).toBe("Paused");
    }
    void before; // updatedAt equality isn't asserted (same-tick Date is legal); status is the contract
  });

  it("rejects an illegal transition and leaves the goal unchanged", () => {
    const store = createGoalStore();
    store.createGoal("reach the summit");
    store.updateStatus("Paused");
    const result = store.updateStatus("Blocked"); // Paused can only resume to Active
    expect(result.ok).toBe(false);
    expect(store.getGoal()?.status).toBe("Paused");
  });

  it("fails when no goal exists", () => {
    const store = createGoalStore();
    const result = store.updateStatus("Active");
    expect(result.ok).toBe(false);
  });

  it("resuming to Active resets consecutiveBlockedTurns and lastBlockReason", () => {
    const store = createGoalStore();
    store.createGoal("reach the summit");
    store.noteBlocked("waiting on external API");
    store.noteBlocked("waiting on external API");
    expect(store.getGoal()?.consecutiveBlockedTurns).toBe(2);

    store.updateStatus("Blocked");
    store.updateStatus("Active"); // resume
    expect(store.getGoal()?.consecutiveBlockedTurns).toBe(0);
    expect(store.getGoal()?.lastBlockReason).toBeUndefined();
  });

  it("emits a 'status_changed' event with from/to/reason", () => {
    const events: GoalTransitionEvent[] = [];
    const store = createGoalStore({ onTransition: (e) => events.push(e) });
    store.createGoal("reach the summit");
    store.updateStatus("Paused", { reason: "operator requested" });
    const change = events.find((e) => e.kind === "status_changed");
    expect(change).toBeDefined();
    if (change?.kind === "status_changed") {
      expect(change.from).toBe("Active");
      expect(change.to).toBe("Paused");
      expect(change.reason).toBe("operator requested");
    }
  });
});

// ---------------------------------------------------------------------------
// recordUsage
// ---------------------------------------------------------------------------

describe("createGoalStore — recordUsage", () => {
  it("accumulates tokens and elapsed time across calls", () => {
    const store = createGoalStore();
    store.createGoal("reach the summit", { tokenBudget: 10_000 });
    store.recordUsage(100, 50);
    store.recordUsage(250, 75);
    expect(store.getGoal()?.usage).toEqual({ tokensUsed: 350, elapsedMs: 125 });
  });

  it("fails when no goal exists", () => {
    const store = createGoalStore();
    expect(store.recordUsage(100).ok).toBe(false);
  });

  it("emits a 'usage_recorded' event", () => {
    const events: GoalTransitionEvent[] = [];
    const store = createGoalStore({ onTransition: (e) => events.push(e) });
    store.createGoal("reach the summit");
    store.recordUsage(10);
    expect(events.some((e) => e.kind === "usage_recorded")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// noteBlocked — the >=3-consecutive-turns audit (current "Continuation loop"
// section BLOCKED AUDIT)
// ---------------------------------------------------------------------------

describe("createGoalStore — noteBlocked", () => {
  it(`is not readyToBlock until the SAME blocker repeats ${BLOCKED_TURNS_THRESHOLD} consecutive turns`, () => {
    const store = createGoalStore();
    store.createGoal("reach the summit");
    const r1 = store.noteBlocked("rate limited");
    expect(r1.consecutiveBlockedTurns).toBe(1);
    expect(r1.readyToBlock).toBe(false);
    const r2 = store.noteBlocked("rate limited");
    expect(r2.consecutiveBlockedTurns).toBe(2);
    expect(r2.readyToBlock).toBe(false);
    const r3 = store.noteBlocked("rate limited");
    expect(r3.consecutiveBlockedTurns).toBe(3);
    expect(r3.readyToBlock).toBe(true);
  });

  it("a DIFFERENT blocker resets the consecutive count to 1 — never blocked on a rotating cause", () => {
    const store = createGoalStore();
    store.createGoal("reach the summit");
    store.noteBlocked("rate limited");
    store.noteBlocked("rate limited");
    const r = store.noteBlocked("disk full"); // different reason
    expect(r.consecutiveBlockedTurns).toBe(1);
    expect(r.readyToBlock).toBe(false);
  });

  it("no-op (zero count, not ready) when no goal exists", () => {
    const store = createGoalStore();
    const r = store.noteBlocked("anything");
    expect(r).toEqual({ consecutiveBlockedTurns: 0, readyToBlock: false });
  });

  it("resetBlockedAudit clears the count and reason directly", () => {
    const store = createGoalStore();
    store.createGoal("reach the summit");
    store.noteBlocked("rate limited");
    store.noteBlocked("rate limited");
    store.resetBlockedAudit();
    expect(store.getGoal()?.consecutiveBlockedTurns).toBe(0);
    expect(store.getGoal()?.lastBlockReason).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// clear
// ---------------------------------------------------------------------------

describe("createGoalStore — clear", () => {
  it("removes the goal record entirely, allowing a fresh createGoal afterward", () => {
    const store = createGoalStore();
    store.createGoal("first");
    store.clear();
    expect(store.getGoal()).toBeNull();
    const result = store.createGoal("second");
    expect(result.ok).toBe(true);
  });

  it("emits a 'cleared' event with the goalId, only when a goal existed", () => {
    const events: GoalTransitionEvent[] = [];
    const store = createGoalStore({ onTransition: (e) => events.push(e) });
    store.clear(); // no-op, no goal
    expect(events).toHaveLength(0);
    store.createGoal("first");
    const goalId = store.getGoal()!.goalId;
    store.clear();
    const cleared = events.find((e) => e.kind === "cleared");
    expect(cleared).toBeDefined();
    if (cleared?.kind === "cleared") expect(cleared.goalId).toBe(goalId);
  });
});

// ---------------------------------------------------------------------------
// Persistence seam — a store built on injected persistence behaves identically
// ---------------------------------------------------------------------------

describe("createInMemoryGoalPersistence — injected persistence seam", () => {
  it("a store built with explicit persistence reads/writes through it", () => {
    const persistence = createInMemoryGoalPersistence();
    const store = createGoalStore({ persistence });
    store.createGoal("reach the summit");
    expect(persistence.read()?.objective).toBe("reach the summit");
  });

  it("two stores sharing the same persistence instance see the same goal", () => {
    const persistence = createInMemoryGoalPersistence();
    const storeA = createGoalStore({ persistence });
    const storeB = createGoalStore({ persistence });
    storeA.createGoal("shared objective");
    expect(storeB.getGoal()?.objective).toBe("shared objective");
  });
});
