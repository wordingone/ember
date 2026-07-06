// commands/goal.ts — /goal slash command (ember issue #211, spec §2): set/view/
// clear the goal objective, available mid-task. This REPLACES the earlier
// bounded ~5-iteration prototype (a fixed-iteration loop wrapping
// QueryEngine.submitMessage, never wired into command-registry.ts's builtin
// list -- dead code) with the actual 1:1-ported mechanism: a persisted goal
// record (core/goal-store.ts) driving an EVENT-DRIVEN continuation engine
// (core/goal-continuation.ts), not a scheduler. The bounded-loop's
// event->fireball phase wiring is left for the separate flame-integration
// work (issue #214, spec §7.2) rather than folded in here.
//
// Command surface:
//   /goal <objective>   -- sets a NEW goal (if none exists) or EDITS the
//                          existing one (spec §2: "mid-flight edits inject an
//                          objective-updated steering prompt so the model
//                          re-anchors"). Either way, also pokes the
//                          continuation engine once so a genuinely idle
//                          session starts working immediately rather than
//                          waiting for the next unrelated turn to end.
//   /goal               -- view status (objective, status, usage/budget,
//                          blocked-turn count).
//   /goal clear         -- clears the goal record entirely.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import { getGoalStore, isCurrentSessionEphemeral } from "../core/goal-runtime.ts";
import type { GoalStore, GoalRecord } from "../core/goal-store.ts";
import { renderObjectiveUpdatedPrompt } from "../core/goal-continuation-prompt.ts";

// ---------------------------------------------------------------------------
// Steering injection — mirrors the existing OperatorInjector shape
// (services/operator-input.ts: canInjectNow/submit) so an objective-updated
// edit goes through the SAME "only when genuinely idle, real user input still
// wins" gate the operator-pipe feature already established, rather than a
// second competing injection path.
// ---------------------------------------------------------------------------

export interface GoalSteeringInjector {
  canInjectNow(): boolean;
  inject(prompt: string): void;
}

let _steeringInjectorProvider: (() => GoalSteeringInjector | null) | null = null;

/** screens/repl.ts calls this once, right after constructing its own
 *  OperatorInjector, so /goal's mid-task edits reuse the SAME idle-gated
 *  injection path (safe to call repeatedly; idempotent). */
export function setGoalSteeringInjectorProvider(
  provider: (() => GoalSteeringInjector | null) | null,
): void {
  _steeringInjectorProvider = provider;
}

export function resetGoalSteeringInjectorForTests(): void {
  _steeringInjectorProvider = null;
}

// ---------------------------------------------------------------------------
// Continuation kickoff — fire-and-forget poke so a freshly-created goal
// starts working immediately if the session happens to be idle right now,
// instead of waiting for some UNRELATED turn to end first.
// ---------------------------------------------------------------------------

let _continuationTrigger: (() => void) | null = null;

/** screens/repl.ts wires this to a single call into its continuation engine's
 *  maybeContinueIfIdle (fire-and-forget; the engine's own semaphore and
 *  eligibility gates make an extra/early poke here harmless). */
export function setGoalContinuationTrigger(trigger: (() => void) | null): void {
  _continuationTrigger = trigger;
}

export function resetGoalContinuationTriggerForTests(): void {
  _continuationTrigger = null;
}

// ---------------------------------------------------------------------------
// Status formatting
// ---------------------------------------------------------------------------

export function formatGoalStatus(goal: GoalRecord | null): string {
  if (!goal) return "no active goal. usage: /goal <objective>";

  const lines = [
    `objective: ${goal.objective}`,
    `status: ${goal.status}`,
    goal.tokenBudget !== undefined
      ? `usage: ${goal.usage.tokensUsed} / ${goal.tokenBudget} tokens`
      : `usage: ${goal.usage.tokensUsed} tokens (no budget set)`,
  ];
  if (goal.consecutiveBlockedTurns > 0) {
    lines.push(`consecutive same-blocker turns: ${goal.consecutiveBlockedTurns}`);
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// /goal command
// ---------------------------------------------------------------------------

export interface GoalCommandDeps {
  getStore?: () => GoalStore;
  isEphemeralSession?: () => boolean;
  getSteeringInjector?: () => GoalSteeringInjector | null;
  triggerContinuationCheck?: () => void;
}

/** Creates the /goal command with injected deps (test seam, same shape as commands/observatory.ts). */
export function createGoalCommand(deps: GoalCommandDeps = {}): RegistryCommand {
  const getStore = deps.getStore ?? getGoalStore;
  const isEphemeralSession = deps.isEphemeralSession ?? (() => isCurrentSessionEphemeral());
  const getSteeringInjector = deps.getSteeringInjector ?? (() => _steeringInjectorProvider?.() ?? null);
  const triggerContinuationCheck = deps.triggerContinuationCheck ?? (() => _continuationTrigger?.());

  return {
    name: "goal",
    description: "Set, view, or clear the goal objective: /goal <objective> | /goal | /goal clear",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, _ctx: CommandContext) {
      const trimmed = args.trim();
      const store = getStore();

      if (trimmed === "clear") {
        const existed = store.getGoal() !== null;
        store.clear();
        return {
          type: "message" as const,
          message: existed ? "goal cleared." : "no active goal to clear.",
        };
      }

      if (trimmed === "") {
        return { type: "message" as const, message: formatGoalStatus(store.getGoal()) };
      }

      const existing = store.getGoal();

      if (!existing) {
        const result = store.createGoal(trimmed, { isEphemeralSession: isEphemeralSession() });
        if (!result.ok) {
          return { type: "message" as const, message: `goal not set: ${result.message}` };
        }
        // Fire-and-forget: if the session happens to be idle right now, start
        // working immediately rather than waiting for an unrelated turn to end.
        triggerContinuationCheck();
        return {
          type: "message" as const,
          message: `goal set: ${result.goal.objective}\nstatus: ${result.goal.status}`,
        };
      }

      // Existing goal present -- this is a mid-task EDIT (spec §2), not a
      // second create. Objective immutability still holds for the MODEL:
      // this path is reachable only through the human-typed /goal command,
      // never through a model-side tool call.
      const editResult = store.editObjective(trimmed);
      if (!editResult.ok) {
        return { type: "message" as const, message: `objective not updated: ${editResult.message}` };
      }

      const injector = getSteeringInjector();
      const steeringPrompt = renderObjectiveUpdatedPrompt(editResult.goal.objective);
      let injected = false;
      if (injector && injector.canInjectNow()) {
        injector.inject(steeringPrompt);
        injected = true;
      }

      return {
        type: "message" as const,
        message:
          `objective updated: ${editResult.goal.objective}` +
          (injected
            ? "\n(steering message injected -- the model will re-anchor on the next turn)"
            : "\n(will re-anchor once the current turn finishes and the session is idle)"),
      };
    },
  };
}
