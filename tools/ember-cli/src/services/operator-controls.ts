// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/operator-controls.ts — the ONE production entry point that turns an
// OperatorSurfacePane click (or its keyboard-equivalent) into a real effect on the run.
//
// The pane itself only renders intent — an OperatorControlAction. This module is what makes
// that intent real: it validates, then appends the corresponding FinetuneControlCmd(s) to the
// governed control channel that a training-side poller obeys (services/finetune-control.ts).
// A handler that fires and changes nothing is exactly the defect this module exists to remove.
//
// RESTART has no dedicated wire verb — the control-channel spec's verb set is
// start/stop/pause/resume/adjust (specs/surface2-steerable-watch-control.md AC5). RESTART is
// therefore defined as "stop" THEN "start", sequential and awaited: a rejected "stop" leg means
// "start" never runs, so there is no such thing as a half-restart.
//
// Validation always runs BEFORE any write (per verb, per leg) — a rejected action is a fail-
// closed no-op with a named reason, never a silent handler-fired-nothing-happened click.

import {
  emitControlCmd,
  validateControlCmd,
  CONTROL_CHANNEL_PATH,
  type FinetuneControlCmd,
  type FinetuneControlVerb,
} from "./finetune-control.ts";

export type OperatorControlAction = "START" | "PAUSE" | "RESUME" | "RESTART";

export interface OperatorControlDeps {
  emit: (cmd: FinetuneControlCmd, path?: string) => Promise<void>;
  now: () => number;
  channelPath?: string;
}

export interface OperatorControlResult {
  ok: boolean;
  emitted: FinetuneControlCmd[];
  error?: string;
}

const defaultDeps: Omit<OperatorControlDeps, "channelPath"> = {
  emit: emitControlCmd,
  now: Date.now,
};

function verbsFor(action: OperatorControlAction): FinetuneControlVerb[] {
  switch (action) {
    case "START":
      return ["start"];
    case "PAUSE":
      return ["pause"];
    case "RESUME":
      return ["resume"];
    case "RESTART":
      return ["stop", "start"];
  }
}

function commandFor(verb: FinetuneControlVerb, runId: string | undefined, ts: string): FinetuneControlCmd {
  return verb === "start" ? { verb, ts } : { verb, runId, ts };
}

/**
 * Drives the real control channel for a single pane action. Emits one command per verb in
 * `verbsFor(action)`, in order, awaiting each before the next — never fired concurrently, so a
 * rejected leg always halts the sequence before any later leg's write.
 */
export async function driveOperatorControl(
  action: OperatorControlAction,
  runId: string | undefined,
  deps: Partial<OperatorControlDeps> = {},
): Promise<OperatorControlResult> {
  const emit = deps.emit ?? defaultDeps.emit;
  const now = deps.now ?? defaultDeps.now;
  const channelPath = deps.channelPath ?? CONTROL_CHANNEL_PATH;
  const emitted: FinetuneControlCmd[] = [];
  for (const verb of verbsFor(action)) {
    const cmd = commandFor(verb, runId, new Date(now()).toISOString());
    const validation = validateControlCmd(cmd);
    if (!validation.ok) {
      return { ok: false, emitted, error: `${action}: ${validation.reason}` };
    }
    await emit(cmd, channelPath);
    emitted.push(cmd);
  }
  return { ok: true, emitted };
}
