# Spec — Surface #2 steerable half: `/watch` + CLI control of the finetune (task #53)

Status: OPEN. Surface #2 visible-half is DONE (telemetry channel renders live; `services/
telemetry-watch.ts` + `screens/repl.ts`). This spec adds the **steerable** half: the operator
can (a) toggle a live telemetry watch view via a slash command, and (b) start / stop / adjust a
governed micro-finetune from the CLI.

Implementation discipline: build from THIS spec + the listed existing modules only. Never read any predecessor
CLI. No founder/user names, and no predecessor-stack lineage (vendor names, prior-tool
identifiers, or agent dotfile directories) in code or comments.

Existing surface (read first, do not rewrite):
- `services/telemetry-watch.ts` — `startTelemetryWatch`, `getState`, `TelemetryEvent`,
  `GovernorSnapshot`, `ActiveRunState`, `TelemetryState`, `DEFAULT_CHANNEL_PATH`
  (`state/ember-telemetry.jsonl`), ring buffer 200, poll 500ms, active-run TTL 30s.
- `screens/repl.ts` — renders the telemetry line in the cockpit.
- `command-registry.ts` + `commands/*.ts` — slash-command registration pattern.

> **Coordination:** this touches `command-registry.ts`. Do NOT run concurrently with the
> surface-#6 build (also edits the registry). Dispatch only after #6 is merged.

---

## Part A — `/watch` command (ember-cli, non-GPU, fully testable)

`commands/watch.ts` + registry entry `watch`.
- **AC1:** registered in `command-registry.ts` as `watch` (no alias collision).
- **AC2:** `/watch` toggles the cockpit's live telemetry view on/off; returns a one-line status
  (`watching <channel>` / `watch off`). Idempotent (double-on stays on).
- **AC3:** `/watch <path>` overrides the channel path (defaults to `DEFAULT_CHANNEL_PATH`); a
  non-existent path returns a clear "channel not found" line, never crashes.
- **AC4:** the command uses the EXISTING `startTelemetryWatch`/`getState` API — it does not
  re-implement polling. Stopping `/watch` calls the handle's stop().

## Part B — finetune control channel (ember-cli writer half, non-GPU, testable)

A control channel is the write-back counterpart of the read-only telemetry channel: the CLI
appends control directives the finetune obeys. New module `services/finetune-control.ts`.

```ts
export type FinetuneControlVerb = "start" | "stop" | "pause" | "resume" | "adjust";
export interface FinetuneControlCmd {
  verb: FinetuneControlVerb;
  runId?: string;             // target run; "stop"/"pause"/"resume"/"adjust" require it
  lrScale?: number;           // "adjust" only: multiply LR (0 < lrScale ≤ 10)
  ts: string;                 // ISO; injected by caller (no Date.now() inside pure fns)
}
export const CONTROL_CHANNEL_PATH = "state/ember-finetune-control.jsonl"; // repo-relative, mirrors telemetry DEFAULT_CHANNEL_PATH
/** Validates a command; returns {ok:true} or {ok:false, reason}. Pure. */
export function validateControlCmd(cmd: FinetuneControlCmd): { ok: boolean; reason?: string };
/** Appends a validated command as one JSONL line. Rejects invalid (never writes). */
export async function emitControlCmd(cmd: FinetuneControlCmd, path?: string): Promise<void>;
```
- **AC5:** `validateControlCmd` rejects: `adjust` without lrScale or lrScale out of (0,10];
  `stop`/`pause`/`resume`/`adjust` without runId; unknown verb. `start` needs no runId.
- **AC6:** `emitControlCmd` appends exactly one JSONL line for a valid cmd; throws (writes
  nothing) for an invalid one. Append-only (never truncates the channel).
- **AC7:** governed-by-default: an `adjust` with lrScale > the cap (10) is rejected — the CLI
  cannot drive the finetune outside the governor envelope. (The training-side enforces the real
  VRAM/pacing governor; this is the CLI-side bound.)

## Part C — `/finetune` control command (ember-cli, non-GPU, testable)

`commands/finetune.ts` + registry entry `finetune` (alias `ft`).
- **AC8:** `/finetune start|stop|pause|resume|adjust [args]` parses to a `FinetuneControlCmd`,
  validates via Part B, and on success calls `emitControlCmd`; returns a one-line ack with the
  verb + runId. Invalid args → the validator's reason line, no write.
- **AC9:** `/finetune adjust <runId> <lrScale>` parses lrScale as a number; non-numeric or
  out-of-range → clear error, no write.

## Tests (test=spec; all CPU-only, no model/GPU/training)
`watch.test.ts`, `finetune-control.test.ts`, `finetune.test.ts`. Every AC ≥1 assertion. Suite
stays green (baseline = whatever it is post-#6; the only allowed pre-existing fail is
process-entry AC1/#37) and tsc=0. Drive the channel by writing fixture JSONL to a temp path —
never a real run.

## NOT in this spec (GPU-gated / training-track follow-ons, logged separately)
- The training-side reader: the governed finetune script polls `CONTROL_CHANNEL_PATH` and obeys
  stop/pause/resume/adjust under the real resource governor. (Python training track.)
- The **live receipt** for surface #2 steerable: the operator stops/adjusts a REAL governed
  micro-finetune from the CLI and the telemetry channel shows it obey, watched live. Rides the
  next GPU window (after keystone #60), folded with the C-GROW live run per GOAL.md #2.
