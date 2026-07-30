// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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
import { resolveEmberRepoRoot } from "../utils/repo-root.ts";
import { isHeadlessCapture, HEADLESS_CAPTURE_ENV } from "./headless-capture.ts";
import type { TelemetryDiagnostics } from "./telemetry-watch.ts";

// Re-exported so this module's existing importers and tests keep one import site. The
// predicate itself lives in headless-capture.ts because the heartbeat is only ONE of the
// side effects a capture harness inherits -- see that module's header.
export { isHeadlessCapture, HEADLESS_CAPTURE_ENV };
/** @deprecated name kept for the tests that named it first; prefer isHeadlessCapture. */
export const shouldSuppressForHeadlessCapture = isHeadlessCapture;

export interface LivenessHeartbeatRow {
  ts:      string; // ISO8601Z -- when this heartbeat was written
  pid:     number;
  version: string; // build SHA or package version, whatever the caller has at hand
  telemetry?: TelemetryDiagnostics;
}

export interface LivenessHeartbeatWriterOptions {
  /** Overrides the resolved repo root -- tests point this at a scratch directory. */
  repoRoot?: string;
  /** Overrides process.env -- tests inject a fixed environment. */
  env?: Record<string, string | undefined>;
  /** Overrides process.pid -- tests inject a fixed value. */
  pid?: number;
  /** Build SHA / package version stamped into every row. Defaults to "unknown" rather than
   *  guessing -- callers that have a real value (EMBER_VERSION env, package.json version)
   *  should always pass it explicitly. */
  version?: string;
  /** Bounded telemetry diagnostics included in each heartbeat for external soak evidence.
   *  Provider failures or invalid values omit the snapshot; heartbeat writes remain fail-open. */
  telemetryDiagnostics?: () => TelemetryDiagnostics;
}

export interface LivenessHeartbeatWriter {
  /** null when the strict repo-root resolver failed at construction (PR954 round 2) --
   *  the writer is then INERT: write() is a no-op, nothing is ever created on disk. A
   *  caller that needs to know "is this writer live" checks filePath, not a separate
   *  flag. */
  readonly filePath: string | null;
  /** Overwrites the heartbeat file with a fresh {ts, pid, version} row. Never throws.
   *  A true no-op on an inert writer (filePath === null). */
  write: (nowMs?: number) => void;
}

const TELEMETRY_DIAGNOSTIC_KEYS = [
  "pollAttempts",
  "pollsCompleted",
  "overlapPollsSkipped",
  "channelBytesRead",
  "maxSingleReadBytes",
  "maxPollReadBytes",
  "partialLineBytes",
  "oversizedPartialLinesDropped",
] as const satisfies readonly (keyof TelemetryDiagnostics)[];

function telemetrySnapshot(
  provider: (() => TelemetryDiagnostics) | undefined,
): TelemetryDiagnostics | undefined {
  if (!provider) return undefined;
  try {
    const source = provider();
    const snapshot = {} as TelemetryDiagnostics;
    for (const key of TELEMETRY_DIAGNOSTIC_KEYS) {
      const value = source[key];
      if (!Number.isSafeInteger(value) || value < 0) return undefined;
      snapshot[key] = value;
    }
    return snapshot;
  } catch {
    return undefined;
  }
}

/** #413: tools/ember-cli/state/ is gitignored repo-wide -- the root .gitignore's bare `state/`
 *  pattern matches at any depth (verified via `git check-ignore -v
 *  tools/ember-cli/state/cockpit-heartbeat.json`), so this path needs no new .gitignore line and
 *  can never land in receipts/ (custody scans receipts only). */
export function createLivenessHeartbeatWriter(
  options: LivenessHeartbeatWriterOptions = {},
): LivenessHeartbeatWriter {
  const pid     = options.pid ?? process.pid;
  const version = options.version ?? "unknown";

  // ORDER IS LOAD-BEARING: this runs BEFORE repo-root resolution, so a capture run publishes
  // nothing even on the path where resolution SUCCEEDS -- which is every normal run, and the only
  // path that reaches the watchdog. Placing it after resolution would leave the defect intact and
  // only cover the failure case, which was already inert.
  if (isHeadlessCapture(options.env)) {
    console.warn(
      `[liveness-heartbeat] ${HEADLESS_CAPTURE_ENV}=1 -- this process is a capture harness, not ` +
        `the cockpit; heartbeat writer is INERT (no file will ever be created or written).`,
    );
    return {
      filePath: null,
      write() {
        // Deliberate no-op -- an inert writer never touches disk.
      },
    };
  }

  // PR954 round 2: the heartbeat path is authoritative state the watchdog polls -- it
  // must go through the STRICT resolver (resolveEmberRepoRoot), never
  // resolveEmberRepoRootOrCwd's silent cwd fallback (that fallback is reserved for
  // non-authoritative UI conveniences; see repo-root.ts). On resolution failure this
  // writer goes INERT: filePath=null, exactly one explicit warning, zero mkdir, zero
  // writes ever -- a heartbeat silently written to the wrong root is worse than no
  // heartbeat at all, because it manufactures a false "the cockpit is alive" signal at
  // a path the watchdog will never poll.
  let repoRoot: string;
  try {
    repoRoot = options.repoRoot ?? resolveEmberRepoRoot({});
  } catch (err) {
    console.warn(
      `[liveness-heartbeat] repo root resolution failed -- heartbeat writer is INERT ` +
        `(no file will ever be created or written): ${err instanceof Error ? err.message : String(err)}`,
    );
    return {
      filePath: null,
      write() {
        // Deliberate no-op -- an inert writer never touches disk.
      },
    };
  }

  const dir      = path.join(repoRoot, "tools", "ember-cli", "state");
  const filePath = path.join(dir, "cockpit-heartbeat.json");

  // #666 startup path-assert: name the exact file this process will write, so a divergence
  // from the path the watchdog logs on ITS side is visible in two adjacent log lines
  // instead of manifesting as a phantom-stale heartbeat and a duplicate cockpit.
  console.warn(`[liveness-heartbeat] writing heartbeat to ${filePath} (repo root ${repoRoot})`);

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
      const telemetry = telemetrySnapshot(options.telemetryDiagnostics);
      const row: LivenessHeartbeatRow = {
        ts: new Date(nowMs).toISOString(), pid, version,
        ...(telemetry ? { telemetry } : {}),
      };
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

/**
 * Reads and validates the heartbeat file's row (both `ts` AND `pid` present/well-typed), or
 * `null` otherwise. Deliberately separate from heartbeatAge above (never refactored to share
 * heartbeatAge's parse path) so #413's existing ts-only validation contract is untouched --
 * this is a NEW, stricter reader for issue #447's cockpit-restart-event detection
 * (core/monitor-render.ts's formatCockpitRestartEvent), which needs the row's actual `pid` to
 * report "pid P1 -> P2", not just an age number.
 */
export function readHeartbeatRow(filePath: string): LivenessHeartbeatRow | null {
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

  if (
    typeof row !== "object" ||
    row === null ||
    typeof (row as { ts?: unknown }).ts !== "string" ||
    typeof (row as { pid?: unknown }).pid !== "number"
  ) {
    return null;
  }
  return row as LivenessHeartbeatRow;
}
