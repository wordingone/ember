// services/finetune-control.ts — append-only control channel for governed finetune.
//
// The control channel is the write-back counterpart of the read-only telemetry channel:
// the CLI appends control directives that the training-side finetune script polls and obeys.
// All writes are append-only JSONL; validation is pure and rejects invalid commands before write.

import { appendFile } from "fs/promises";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FinetuneControlVerb = "start" | "stop" | "pause" | "resume" | "adjust";

export interface FinetuneControlCmd {
  verb: FinetuneControlVerb;
  runId?: string; // target run; "stop"/"pause"/"resume"/"adjust" require it
  lrScale?: number; // "adjust" only: multiply LR (0 < lrScale ≤ 10)
  ts: string; // ISO; injected by caller (no Date.now() inside pure fns)
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Repo-relative, mirroring the read-only telemetry channel's DEFAULT_CHANNEL_PATH
// (state/ember-telemetry.jsonl). Callers may override via emitControlCmd's path arg.
export const CONTROL_CHANNEL_PATH = "state/ember-finetune-control.jsonl";

// ---------------------------------------------------------------------------
// Validation (pure function)
// ---------------------------------------------------------------------------

/**
 * Validates a finetune control command.
 * Returns {ok:true} or {ok:false, reason:<string>}.
 * Pure function — no side effects, no I/O.
 *
 * Validation rules (AC5):
 * - `start`: no runId required; valid.
 * - `stop`, `pause`, `resume`: runId required.
 * - `adjust`: runId + lrScale both required; lrScale must be in (0, 10].
 * - Unknown verb: rejected.
 * - Governor cap: lrScale > 10 is rejected (CLI-side bound).
 */
export function validateControlCmd(cmd: FinetuneControlCmd): {
  ok: boolean;
  reason?: string;
} {
  const { verb, runId, lrScale } = cmd;

  // Validate verb
  const validVerbs = ["start", "stop", "pause", "resume", "adjust"];
  if (!validVerbs.includes(verb)) {
    return { ok: false, reason: `unknown verb: ${verb}` };
  }

  // start: no runId required
  if (verb === "start") {
    return { ok: true };
  }

  // stop, pause, resume: require runId
  if (["stop", "pause", "resume"].includes(verb)) {
    if (!runId) {
      return { ok: false, reason: `${verb} requires runId` };
    }
    return { ok: true };
  }

  // adjust: require both runId and lrScale
  if (verb === "adjust") {
    if (!runId) {
      return { ok: false, reason: "adjust requires runId" };
    }
    if (lrScale === undefined) {
      return { ok: false, reason: "adjust requires lrScale" };
    }
    // lrScale must be in (0, 10] — governed
    if (typeof lrScale !== "number" || lrScale <= 0 || lrScale > 10) {
      return {
        ok: false,
        reason: `lrScale must be in (0, 10]; got ${lrScale}`,
      };
    }
    return { ok: true };
  }

  return { ok: false, reason: "unexpected verb state" };
}

// ---------------------------------------------------------------------------
// Emission (write-back to channel)
// ---------------------------------------------------------------------------

/**
 * Emits a validated command to the control channel as one JSONL line.
 * Rejects invalid commands (throws) and never writes on validation failure.
 * Append-only: never truncates or overwrites.
 *
 * @param cmd - the control command to emit
 * @param path - optional override for channel path (defaults to CONTROL_CHANNEL_PATH)
 * @throws if the command fails validation
 */
export async function emitControlCmd(
  cmd: FinetuneControlCmd,
  path?: string,
): Promise<void> {
  // Validate before any I/O
  const result = validateControlCmd(cmd);
  if (!result.ok) {
    throw new Error(`invalid control command: ${result.reason}`);
  }

  // Append to channel
  const channelPath = path ?? CONTROL_CHANNEL_PATH;
  const line = JSON.stringify(cmd);
  await appendFile(channelPath, `${line}\n`);
}
