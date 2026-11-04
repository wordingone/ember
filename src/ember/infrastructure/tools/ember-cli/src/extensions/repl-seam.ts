// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/repl-seam.ts — the few calls screens/repl.ts makes into the extension layer,
// kept here so the REPL file stays small and these rules are unit-testable without a TUI.

import { getActiveHookRunner, reportHookWarnings } from "./hooks.ts";
import { cancelAllLoops, hasActiveLoops } from "./scheduler.ts";

export interface PromptHookResult {
  blocked: boolean;
  /** Shown to the user when blocked. */
  reason?: string;
  /** The prompt to send: the original plus any context the hooks printed. */
  prompt: string;
}

/** UserPromptSubmit hooks: exit 2 blocks the prompt; stdout of a passing hook is added as context. */
export async function applyUserPromptSubmitHooks(prompt: string): Promise<PromptHookResult> {
  const runner = getActiveHookRunner();
  if (!runner?.hasHooks("UserPromptSubmit")) return { blocked: false, prompt };
  const outcome = await runner.run("UserPromptSubmit", { prompt }).catch(() => null);
  if (!outcome) return { blocked: false, prompt };
  reportHookWarnings(outcome);
  if (outcome.blocked) return { blocked: true, reason: outcome.reason, prompt };
  return {
    blocked: false,
    prompt: outcome.output ? `${prompt}\n\n[UserPromptSubmit hook output]\n${outcome.output}` : prompt,
  };
}

export interface StopHookResult {
  /** A Stop hook exited 2: the model should continue, with `reason` as the instruction. */
  continueWith?: string;
}

/**
 * Stop hooks run when a turn finished normally. Exit 2 asks the model to continue with the hook's
 * stderr as the instruction; `stopHookActive` is true when this turn was itself such a
 * continuation, in which case a second request is ignored so a hook cannot loop forever.
 */
export async function runStopHooks(stopHookActive: boolean): Promise<StopHookResult> {
  const runner = getActiveHookRunner();
  if (!runner?.hasHooks("Stop")) return {};
  const outcome = await runner.run("Stop", { stop_hook_active: stopHookActive }).catch(() => null);
  if (!outcome) return {};
  reportHookWarnings(outcome);
  if (outcome.blocked && !stopHookActive) {
    return { continueWith: outcome.reason ?? "A Stop hook asked you to continue." };
  }
  return {};
}

/** Esc: stops every /loop. Returns the notice to show, or null when no loop was running. */
export function stopLoopsOnEscape(): string | null {
  if (!hasActiveLoops()) return null;
  const n = cancelAllLoops();
  return `Stopped ${n} loop${n === 1 ? "" : "s"}.`;
}
