// commands/goal.ts — /goal <objective> slash command: a bounded ~GOAL_MAX_ITERATIONS-iteration
// loop wrapping QueryEngine.submitMessage(), publishing real setLoopPhase() transitions per event
// (the SAME event -> phase derivation screens/repl.ts's key.return handler uses inline, extracted
// here as deriveLoopPhaseForEvent so it's independently testable) -- this feeds the existing,
// already-built fireball/cognitive-mode rendering, which until now no command ever drove.
//
// Also maintains a module-level GoalSegmentSnapshot (getGoalStatus/resetGoalStatusForTests) for
// the status-bar's persistent GOAL segment (components/status-bar.ts), following the exact
// poll-from-repl pattern already used for the R0 activity segment.
//
// Bounded, never open-ended: the loop always stops at maxIterations regardless of model behavior
// -- an autonomy-relinquishment-ladder rail, not a heuristic "the model said it's done" guess
// (inferring completion from free-text content would be exactly the kind of unverified signal the
// R0 anti-fixture discipline forbids).

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import type { QueryEvent } from "../core/query-engine.ts";
import { setLoopPhase } from "../state/app-state.ts";

export const GOAL_MAX_ITERATIONS = 5;

export type GoalRunStatus = "running" | "completed" | "aborted" | "error";

export interface GoalStatusSnapshot {
  objective: string;
  /** 1-based current iteration; 0 before the first iteration starts. */
  step: number;
  maxSteps: number;
  /** The LoopPhase label at the moment of the last observed event ("idle" before start / after
   * a clean finish). Same vocabulary state/app-state.ts's setLoopPhase() accepts. */
  phase: string;
  status: GoalRunStatus;
}

let _goalStatus: GoalStatusSnapshot | null = null;

/** Read by the status-bar GOAL segment (and any poller); null when no goal loop has run yet in
 * this session. Never cleared back to null after a run finishes -- the last snapshot (status:
 * "completed"/"error"/"aborted") stays visible until a new /goal call overwrites it, same as the
 * activity segment never blanks itself back to "nothing fetched yet" once fetched once. */
export function getGoalStatus(): GoalStatusSnapshot | null {
  return _goalStatus;
}

/** Test-only reset -- isolates module-level state between test cases. */
export function resetGoalStatusForTests(): void {
  _goalStatus = null;
}

/**
 * The event -> LoopPhase mapping screens/repl.ts's key.return handler applies inline to
 * QueryEngine events. Extracted here (not imported FROM repl.ts, to avoid an L4-screen -> L3-
 * command dependency) so goal.ts's loop uses the identical, already-proven convention rather than
 * inventing a second one. Returns null for "result" events -- those are terminal for the current
 * sub-turn, not a phase in their own right; the caller decides the next transition.
 */
export function deriveLoopPhaseForEvent(
  event: QueryEvent,
): "tool_call" | "streaming_text" | "tool_result" | null {
  if (event.type === "assistant") {
    const raw = event.message.content;
    const invokesTool =
      Array.isArray(raw) && (raw as Array<{ type?: string }>).some((b) => b.type === "tool_use");
    return invokesTool ? "tool_call" : "streaming_text";
  }
  if (event.type === "user") return "tool_result";
  return null;
}

/** The minimal QueryEngine surface goal.ts needs -- keeps this module testable with a fake
 * engine instead of constructing a full QueryEngine (tools/cwd/system-prompt wiring). */
export interface GoalEngineLike {
  submitMessage(userMessage: string): AsyncGenerator<QueryEvent>;
}

export interface GoalLoopDeps {
  /** Builds each iteration's user-turn prompt from the objective + step counters. Overridable
   * for tests; defaults to a plain deterministic template (no model call of its own). */
  buildIterationPrompt?: (objective: string, step: number, maxSteps: number) => string;
}

function defaultBuildIterationPrompt(objective: string, step: number, maxSteps: number): string {
  return step === 1
    ? `Goal: ${objective}\n\nBegin working toward this goal now. You have ${maxSteps} bounded ` +
        `iterations total; use them efficiently and report real, verifiable progress at each step.`
    : `Continue toward the goal: ${objective}\n\n(step ${step}/${maxSteps})`;
}

/**
 * Drives the bounded goal loop: up to `maxIterations` calls to engine.submitMessage(), each
 * streaming QueryEvents that publish real setLoopPhase() transitions (lighting the existing
 * fireball) and update the module-level GoalStatusSnapshot (feeding the status-bar GOAL segment).
 *
 * Returns the final snapshot. Stops early only on a genuine engine error/abort (never on an
 * inferred "the model thinks it's done" heuristic) -- an error mid-iteration ends the run at
 * status:"error" rather than silently completing early.
 */
export async function runGoalLoop(
  engine: GoalEngineLike,
  objective: string,
  maxIterations: number = GOAL_MAX_ITERATIONS,
  deps: GoalLoopDeps = {},
): Promise<GoalStatusSnapshot> {
  const buildPrompt = deps.buildIterationPrompt ?? defaultBuildIterationPrompt;

  _goalStatus = { objective, step: 0, maxSteps: maxIterations, phase: "idle", status: "running" };

  for (let step = 1; step <= maxIterations; step++) {
    _goalStatus = { ..._goalStatus, step, status: "running" };
    const prompt = buildPrompt(objective, step, maxIterations);

    try {
      for await (const event of engine.submitMessage(prompt)) {
        const phase = deriveLoopPhaseForEvent(event);
        if (phase) {
          setLoopPhase(phase);
          _goalStatus = { ..._goalStatus, phase };
        }
        if (event.type === "result" && (event.subtype === "error" || event.subtype === "abort")) {
          setLoopPhase("error");
          _goalStatus = { ..._goalStatus, phase: "error", status: "error" };
          return _goalStatus;
        }
      }
    } catch (err) {
      setLoopPhase("error");
      _goalStatus = {
        ..._goalStatus,
        phase: "error",
        status: "error",
      };
      return _goalStatus;
    }
  }

  setLoopPhase("idle");
  _goalStatus = { ..._goalStatus, phase: "idle", status: "completed" };
  return _goalStatus;
}

// ---------------------------------------------------------------------------
// /goal slash command
// ---------------------------------------------------------------------------

let _engineProvider: (() => GoalEngineLike | null) | null = null;

/**
 * Registers the live engine the /goal command should drive. screens/repl.ts calls this once,
 * right after it lazy-inits its own QueryEngine, so /goal reuses the SAME conversation-state
 * engine instead of constructing a second, competing one. Safe to call repeatedly (idempotent).
 */
export function setGoalEngineProvider(provider: (() => GoalEngineLike | null) | null): void {
  _engineProvider = provider;
}

/** Test-only reset. */
export function resetGoalEngineProviderForTests(): void {
  _engineProvider = null;
}

interface GoalCommandDeps {
  getEngine?: () => GoalEngineLike | null;
  maxIterations?: number;
  runLoop?: typeof runGoalLoop;
}

/** Creates the /goal command with injected deps (test seam, same shape as createActivityCommand). */
export function createGoalCommand(deps: GoalCommandDeps = {}): RegistryCommand {
  const getEngine = deps.getEngine ?? (() => _engineProvider?.() ?? null);
  const maxIterations = deps.maxIterations ?? GOAL_MAX_ITERATIONS;
  const runLoop = deps.runLoop ?? runGoalLoop;

  return {
    name: "goal",
    description: "Start a bounded autonomous goal-mode loop: /goal <objective>",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, _ctx: CommandContext) {
      const objective = args.trim();
      if (!objective) {
        return { type: "message" as const, message: "usage: /goal <objective>" };
      }
      const engine = getEngine();
      if (!engine) {
        // Honest failure, not a fabricated "started" claim: no live session engine exists yet
        // (matches the R0 anti-fixture rule -- never report progress on a run that isn't real).
        return {
          type: "message" as const,
          message: "no active session engine yet -- send at least one message first, then /goal <objective>",
        };
      }
      // Fire-and-forget, same non-blocking pattern as /activity's background watch start: the
      // command returns immediately so the TUI stays responsive; the status-bar GOAL segment
      // (fed by getGoalStatus() on a poll) is what shows live progress, not this return message.
      void runLoop(engine, objective, maxIterations);
      return {
        type: "message" as const,
        message: `goal loop started: ${objective} (bounded to ${maxIterations} iterations)`,
      };
    },
  };
}
