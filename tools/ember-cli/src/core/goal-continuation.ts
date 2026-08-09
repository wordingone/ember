// core/goal-continuation.ts — the event-driven autonomy loop (ember issue
// #211, the current "Continuation loop" section's "event-driven" contract).
// Every task/turn completion pokes
// maybeContinueIfIdle(): eligibility gates on genuine idleness (feature on,
// not plan mode, no active turn, NO QUEUED USER INPUT -- the user always
// preempts), a semaphore makes double-fire structurally impossible, and the
// goal is RE-READ right before commit so a race with a concurrent edit/clear
// loses safely (skip, release the reservation) rather than firing into stale
// state.

import type { GoalStore } from "./goal-store.ts";
import { renderContinuationPrompt, renderBudgetWrapUpPrompt } from "./goal-continuation-prompt.ts";

export type ContinuationSkipReason =
  | "feature_disabled"
  | "plan_mode"
  | "turn_active"
  | "queued_user_input"
  | "no_goal"
  | "goal_not_active"
  | "goal_changed_mid_check"
  | "already_in_flight";

/** Read ONCE, synchronously, at the top of every attempt -- these are the
 *  "genuine idleness" gates that must all hold before a semaphore is even
 *  requested. */
export interface ContinuationEligibilitySignals {
  featureEnabled: boolean;
  planMode: boolean;
  turnActive: boolean;
  /** The user ALWAYS preempts: true here skips unconditionally, regardless of
   *  goal state (the current "Continuation loop" section / acceptance leg (c)). */
  queuedUserInput: boolean;
}

export interface MaybeContinueDeps {
  store: GoalStore;
  getEligibilitySignals: () => ContinuationEligibilitySignals;
  /** Starts an ordinary turn with the given (hidden, marker-wrapped) prompt
   *  text -- "the loop reuses the same turn machinery" (the current
   *  "Continuation loop" section). Held
   *  across this async call while the semaphore is locked, so a slow turn
   *  never overlaps a second continuation attempt. */
  startTurn: (prompt: string) => Promise<void>;
}

export type ContinuationOutcome =
  | { fired: true; kind: "continue" | "budget_wrapup"; goalId: string }
  | { fired: false; reason: ContinuationSkipReason };

export interface GoalContinuationEngine {
  maybeContinueIfIdle(deps: MaybeContinueDeps): Promise<ContinuationOutcome>;
  /** True while a fire is in progress (a startTurn call is awaited). Exposed
   *  for tests proving the semaphore actually releases. */
  isInFlight(): boolean;
}

/**
 * Creates a fresh continuation engine with its OWN semaphore. Each REPL
 * session should own exactly one instance (module-level singleton in
 * production, per-test instance in unit tests) -- sharing one across
 * unrelated sessions would serialize their continuation fires against each
 * other for no reason.
 */
export function createGoalContinuationEngine(): GoalContinuationEngine {
  let locked = false;

  async function maybeContinueIfIdle(deps: MaybeContinueDeps): Promise<ContinuationOutcome> {
    const signals = deps.getEligibilitySignals();
    if (!signals.featureEnabled) return { fired: false, reason: "feature_disabled" };
    if (signals.planMode) return { fired: false, reason: "plan_mode" };
    if (signals.turnActive) return { fired: false, reason: "turn_active" };
    // User preemption is unconditional -- checked before the semaphore is even
    // requested, and before any goal state is consulted.
    if (signals.queuedUserInput) return { fired: false, reason: "queued_user_input" };

    if (locked) return { fired: false, reason: "already_in_flight" };
    locked = true;

    try {
      const firstRead = deps.store.getGoal();
      if (!firstRead) return { fired: false, reason: "no_goal" };
      if (firstRead.status !== "Active") return { fired: false, reason: "goal_not_active" };
      const goalId = firstRead.goalId;

      // Re-read right before commit (the current "Continuation loop" section):
      // a race with a concurrent
      // edit/clear that happened between the first read above and this line
      // must lose safely, never fire against stale state.
      const secondRead = deps.store.getGoal();
      if (!secondRead || secondRead.goalId !== goalId || secondRead.status !== "Active") {
        return { fired: false, reason: "goal_changed_mid_check" };
      }

      const overBudget =
        secondRead.tokenBudget !== undefined && secondRead.usage.tokensUsed >= secondRead.tokenBudget;

      if (overBudget) {
        const updated = deps.store.updateStatus("BudgetLimited");
        if (!updated.ok) {
          // Active -> BudgetLimited is always a legal transition per the state
          // machine, so this branch should be unreachable in practice -- but
          // never silently fire a turn against a store that just rejected the
          // transition it was asked to perform.
          return { fired: false, reason: "goal_changed_mid_check" };
        }
        const prompt = renderBudgetWrapUpPrompt({
          objective: secondRead.objective,
          tokensUsed: secondRead.usage.tokensUsed,
          tokenBudget: secondRead.tokenBudget,
          consecutiveBlockedTurns: secondRead.consecutiveBlockedTurns,
        });
        await deps.startTurn(prompt);
        return { fired: true, kind: "budget_wrapup", goalId };
      }

      const prompt = renderContinuationPrompt({
        objective: secondRead.objective,
        tokensUsed: secondRead.usage.tokensUsed,
        tokenBudget: secondRead.tokenBudget,
        consecutiveBlockedTurns: secondRead.consecutiveBlockedTurns,
      });
      await deps.startTurn(prompt);
      return { fired: true, kind: "continue", goalId };
    } finally {
      locked = false;
    }
  }

  return { maybeContinueIfIdle, isInFlight: () => locked };
}
