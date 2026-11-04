// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/session-control.ts -- how slash commands reach state the REPL owns.
//
// /compact and /resume act on the live engine and transcript, which only the REPL holds (as
// /clear already does). The REPL registers closures here on mount; commands call them. With
// nothing registered (headless, tests) every call reports that no session is attached.

import type { CompactionOutcome } from "./compaction.ts";

export interface SessionControl {
  /** Compacts the live conversation now; `instructions` is appended to the summary prompt. */
  compact(instructions: string): Promise<CompactionOutcome>;
}

let control: SessionControl | null = null;

export function setSessionControl(next: SessionControl | null): void {
  control = next;
}

export function getSessionControl(): SessionControl | null {
  return control;
}
