// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/goal-continuation-wiring.ts — wires the goal continuation engine
// (core/goal-continuation.ts) into a real turn loop (ember issue #211, live
// acceptance leg b). Pure logic, no React/ink — screens/repl.ts supplies the
// live refs/callbacks; this file is the seam that makes the loop actually
// chain across multiple autonomous turns with zero human input.
//
// SELF-CHAINING RATIONALE: core/goal-continuation.ts's maybeContinueIfIdle
// holds its semaphore for the FULL DURATION of the fired turn, by design
// ("Held across this async call while the semaphore is locked, so a slow
// turn never overlaps a second continuation attempt" — that file's own
// MaybeContinueDeps.startTurn doc). That means a poke arriving from INSIDE
// the fired turn's own completion (e.g. the fired turn's submitPrompt
// finishing and, per the wiring below, poking again) always sees the lock
// still held and no-ops harmlessly — it is still "inside" the outer call.
// If nothing else re-poked, the autonomous chain would silently die after
// exactly one continuation. createGoalContinuationPoke's `.then()` fixes
// this: once the OUTER call's own semaphore has genuinely released (its
// `await startTurn(...)` has resolved), THIS function re-invokes itself if
// that call fired — so a single external kick (the end of a real human/
// operator turn) is enough to sustain an arbitrarily long autonomous chain,
// bounded only by budget/blocked/complete/user-preemption, exactly as spec
// (docs/contracts/goal-mode-mechanism.md "Continuation loop") requires.

import type {
  GoalContinuationEngine,
  ContinuationEligibilitySignals,
} from "./goal-continuation.ts";
import type { GoalStore } from "./goal-store.ts";
import type { GoalReceiptWriter } from "../services/goal-receipts.ts";

export interface GoalContinuationWiringDeps {
  engine: GoalContinuationEngine;
  getStore: () => GoalStore;
  /** Re-evaluated on every poke (including self-chained re-pokes) — must read
   *  LIVE state, never a snapshot, so a user keystroke or operator-pipe line
   *  arriving between pokes is honored the very next time this fires. */
  getEligibilitySignals: () => ContinuationEligibilitySignals;
  startTurn: (prompt: string) => Promise<void>;
  /** Optional — production wires core/goal-runtime.ts's getGoalReceiptWriter().
   *  Every fire and every skip-while-a-goal-exists is receipted here (spec
   *  §7.1: "every transition and continuation fire ALSO appends to the
   *  receipt store"); omitted in unit tests, which assert on outcomes
   *  directly instead. A "no goal at all" skip is never receipted — that is
   *  every ordinary REPL turn in every session that never touches /goal, and
   *  would otherwise spam the receipt store for users who never opt in. */
  getReceiptWriter?: () => GoalReceiptWriter | null;
}

/**
 * Returns a fire-and-forget poke function. Safe to call after EVERY
 * submitPrompt completion — human-typed, operator-injected, or a
 * continuation/wrap-up turn this same chain fired — a poke that arrives
 * while the engine's own semaphore is still held simply no-ops
 * ({fired:false, reason:"already_in_flight"}) and is not itself an error.
 */
export function createGoalContinuationPoke(deps: GoalContinuationWiringDeps): () => void {
  function poke(): void {
    void deps.engine
      .maybeContinueIfIdle({
        store: deps.getStore(),
        getEligibilitySignals: deps.getEligibilitySignals,
        startTurn: deps.startTurn,
      })
      .then((outcome) => {
        const writer = deps.getReceiptWriter?.() ?? null;
        if (writer) {
          if (outcome.fired) {
            writer.append("continuation_fired", outcome.goalId, { kind: outcome.kind });
          } else if (outcome.reason !== "no_goal" && deps.getStore().getGoal()) {
            writer.append("continuation_skipped", deps.getStore().getGoal()?.goalId, {
              reason: outcome.reason,
            });
          }
        }
        if (outcome.fired) poke();
      });
  }
  return poke;
}

export interface GoalContinuationRearmScheduler {
  setInterval(callback: () => void, intervalMs: number): unknown;
  clearInterval(handle: unknown): void;
}

export interface GoalContinuationRearmOptions {
  poke: () => void;
  intervalMs?: number;
  featureEnabled?: () => boolean;
  shouldPoke?: () => boolean;
  scheduler?: GoalContinuationRearmScheduler;
}

/**
 * Low-frequency resurrection layer for a poke skipped by a transient gate.
 * The event-driven path remains primary; this timer only re-evaluates the same
 * live eligibility gates and never bypasses the engine semaphore or user
 * preemption. The returned cleanup owns the interval for one mounted session.
 */
export function startGoalContinuationRearm(
  options: GoalContinuationRearmOptions,
): () => void {
  const intervalMs = options.intervalMs ?? 5_000;
  if (!Number.isFinite(intervalMs) || intervalMs <= 0) {
    throw new RangeError("goal continuation re-arm interval must be finite and positive");
  }
  const featureEnabled = options.featureEnabled ?? isGoalContinuationFeatureEnabled;
  const scheduler = options.scheduler ?? {
    setInterval: (callback: () => void, delayMs: number): unknown =>
      globalThis.setInterval(callback, delayMs),
    clearInterval: (handle: unknown): void =>
      globalThis.clearInterval(handle as ReturnType<typeof globalThis.setInterval>),
  };
  const handle = scheduler.setInterval(() => {
    if (featureEnabled() && (options.shouldPoke?.() ?? true)) options.poke();
  }, intervalMs);
  return () => scheduler.clearInterval(handle);
}
/**
 * Feature kill-switch for the autonomous continuation loop (the current
 * "Continuation loop" section's feature boundary:
 * "feature on" is its own gate, independent of goal existence/state).
 * EMBER_GOAL_CONTINUATION='0' disables; unset or any other value enables —
 * same "'0' means off" convention as EMBER_SYNTAX_HIGHLIGHT (process-entry.ts).
 */
export function isGoalContinuationFeatureEnabled(): boolean {
  return process.env["EMBER_GOAL_CONTINUATION"] !== "0";
}
