// services/liveness-heartbeat.ts — writes a per-render-cycle heartbeat file so external census
// tooling (issue #413) can tell a live cockpit process from a dead one without needing pixels.
//
// Incident this cures: the operator's cockpit pane sat frozen for up to ~11h after the binary had
// exited -- only the `cmd /k` wrapper kept the terminal pane open, the last-rendered frame (board
// summary included) looked exactly like a live cockpit, and nothing detected it: pane-existence
// (the window is open) and process-liveness (the binary is still running) are two different
// facts, and every external check only ever looked at the first. This module is the second fact,
// made checkable without a screenshot: a live process overwrites this file at least once/second
// (see screens/repl.ts's unconditional liveness tick); a dead process (frozen pane, exited binary)
// leaves it exactly where it was at exit, forever.
//
// Fail-open by design, same contract as services/operator-receipts.ts: a heartbeat write must
// never crash or delay the render loop. Every fs call is wrapped; failures are swallowed after a
// best-effort console warning. No fsync, no atomic rename (spec: "failure to write must never
// crash the UI" / "atomic rename or plain overwrite is fine") -- a torn/partial read on the reader
// side is caught by heartbeatAge's own parse try/catch and reported as unknown (null), never as a
// false-fresh age.

import fs from "node:fs";
import path from "node:path";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";

export interface LivenessHeartbeatRow {
  ts:      string; // ISO8601Z -- when this heartbeat was written
  pid:     number;
  version: string; // build SHA or package version, whatever the caller has at hand
}

export interface LivenessHeartbeatWriterOptions {
  /** Overrides the resolved repo root -- tests point this at a scratch directory. */
  repoRoot?: string;
  /** Overrides process.pid -- tests inject a fixed value. */
  pid?: number;
  /** Build SHA / package version stamped into every row. Defaults to "unknown" rather than
   *  guessing -- callers that have a real value (EMBER_VERSION env, package.json version)
   *  should always pass it explicitly. */
  version?: string;
}

export interface LivenessHeartbeatWriter {
  readonly filePath: string;
  /** Overwrites the heartbeat file with a fresh {ts, pid, version} row. Never throws. */
  write: (nowMs?: number) => void;
}

/** #413: tools/ember-cli/state/ is gitignored repo-wide -- the root .gitignore's bare `state/`
 *  pattern matches at any depth (verified via `git check-ignore -v
 *  tools/ember-cli/state/cockpit-heartbeat.json`), so this path needs no new .gitignore line and
 *  can never land in receipts/ (custody scans receipts only). */
export function createLivenessHeartbeatWriter(
  options: LivenessHeartbeatWriterOptions = {},
): LivenessHeartbeatWriter {
  const repoRoot = options.repoRoot ?? resolveEmberRepoRootOrCwd({}, "[liveness-heartbeat]");
  const pid      = options.pid ?? process.pid;
  const version  = options.version ?? "unknown";
  const dir      = path.join(repoRoot, "tools", "ember-cli", "state");
  const filePath = path.join(dir, "cockpit-heartbeat.json");

  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch (err) {
    console.warn(
      `[liveness-heartbeat] could not create ${dir}: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  return {
    filePath,
    write(nowMs = Date.now()) {
      const row: LivenessHeartbeatRow = { ts: new Date(nowMs).toISOString(), pid, version };
      try {
        fs.writeFileSync(filePath, JSON.stringify(row), "utf8");
      } catch (err) {
        console.warn(
          `[liveness-heartbeat] write failed: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    },
  };
}

/**
 * Reads the heartbeat file and returns its age in ms relative to `nowMs`, or `null` if the file
 * is missing, unreadable, or carries an unparseable/invalid `ts`. This is the single shared
 * primitive both an in-app staleness check and external census tooling call -- never re-derived
 * independently -- so the two surfaces can't drift on what "stale" means the way the board badge
 * and /cockpit's own age math drifted before receipt-age.ts unified them (#392/#404).
 */
export function heartbeatAge(filePath: string, nowMs: number = Date.now()): number | null {
  let raw: string;
  try {
    raw = fs.readFileSync(filePath, "utf8");
  } catch {
    return null;
  }

  let row: unknown;
  try {
    row = JSON.parse(raw);
  } catch {
    return null;
  }

  if (typeof row !== "object" || row === null || typeof (row as { ts?: unknown }).ts !== "string") {
    return null;
  }
  const ts = Date.parse((row as LivenessHeartbeatRow).ts);
  if (Number.isNaN(ts)) return null;

  return nowMs - ts;
}
