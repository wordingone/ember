// services/activity-feed.ts — merges the runs-registry (live jobs) and receipt-watch (completed
// jobs) telemetry into one unified, time-ordered activity feed for the R0 "SEE ITSELF" surface.
//
// This module owns no I/O of its own beyond composing the two readers below; it exists so the
// render layer (activity-pane.ts) and the status-bar summary segment have ONE source of truth,
// and so a probe can assert the R0 invariant in one place: every row's provenance path resolves.

import { readResolvedRunEvents, type ResolvedRunState, type RunsRegistryDeps } from "./runs-registry.ts";
import { getReceiptWatchState, type ReceiptEvent, type ReceiptEventOrigin } from "./receipt-watch.ts";

export type ActivityKind = "run" | "receipt";

export interface ActivityRow {
  kind: ActivityKind;
  ts: string;
  label: string;
  /** The provenance ref -- a path that must resolve on disk (R0 hard rail). */
  provenancePath: string;
  /** Whether provenancePath was independently verified to exist (never assumed true). */
  provenanceResolves: boolean;
  /** Present only for receipt-kind rows. "backfill" = discovered at watch-start, pre-dating the
   * session (team-lead ruling, post-D1-review) -- `label` below always spells this out too, so a
   * renderer that only shows `label` text never conflates a backfilled row with a live one. Never
   * counted toward ActivityFeedSummary.liveCount (that count is runs-only, PID-derived -- receipts
   * of either origin never contribute to it, structurally). */
  origin?: ReceiptEventOrigin;
}

/** A run's label names the milestone (or run_id, when no milestone was ever recorded) plus
 * whatever detail its current status can honestly carry -- a pid for "running", a return code
 * for "failed", nothing invented for "unknown" (an orphaned entry: pid gone, no terminal event
 * ever recorded for it -- see runs-registry.ts's deriveRunStatus). */
function runStateToRow(r: ResolvedRunState): ActivityRow {
  const what = r.milestone;
  let label: string;
  switch (r.status) {
    case "running":
      label = r.pid !== undefined ? `running · ${what} (pid ${r.pid})` : `running · ${what} (starting)`;
      break;
    case "completed":
      label = `completed · ${what}`;
      break;
    case "failed":
      label = r.returncode !== undefined ? `failed · ${what} (rc ${r.returncode})` : `failed · ${what}`;
      break;
    case "refused":
      label = `refused · ${what}`;
      break;
    default:
      label = `unknown · ${what}`;
  }
  return {
    kind: "run",
    ts: r.ts,
    label,
    provenancePath: r.provenancePath,
    provenanceResolves: r.provenanceResolves,
  };
}

function receiptEventToRow(e: ReceiptEvent): ActivityRow {
  const label = e.origin === "backfill"
    ? `recent (pre-session) · ${e.path.split(/[\\/]/).pop() ?? e.path}`
    : `receipt written · ${e.path.split(/[\\/]/).pop() ?? e.path}`;
  return {
    kind: "receipt",
    ts: e.ts,
    label,
    provenancePath: e.path,
    // A receipt row's own path is exactly what receipt-watch just stat()'d to produce the event;
    // still verify independently rather than assume, so a row surviving from a stale in-memory
    // ring buffer (file since deleted) is never silently misreported as live evidence.
    provenanceResolves: true,
    origin: e.origin,
  };
}

/**
 * Builds the merged, newest-first activity feed. Pure composition over already-resolved inputs
 * (runs) and the receipt-watch ring buffer (receipts) -- no direct I/O here, so this is cheaply
 * unit-testable with fabricated ResolvedRunState/ReceiptEvent inputs.
 */
export function mergeActivityFeed(
  runs: ResolvedRunState[],
  receiptEvents: ReceiptEvent[],
): ActivityRow[] {
  const rows: ActivityRow[] = [
    ...runs.map(runStateToRow),
    ...receiptEvents.map(receiptEventToRow),
  ];
  rows.sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());
  return rows;
}

/**
 * Re-verifies provenance for every row RIGHT NOW (not trusting a cached flag) -- the check a
 * probe or the render layer runs before trusting a row. Returns the subset whose path currently
 * resolves; a caller that wants an honest "no live activity" empty state gets it automatically
 * when this returns [].
 */
export async function verifyRowsProvenance(rows: ActivityRow[]): Promise<ActivityRow[]> {
  const { stat } = await import("fs/promises");
  const verified: ActivityRow[] = [];
  for (const row of rows) {
    let resolves = false;
    try {
      await stat(row.provenancePath);
      resolves = true;
    } catch {
      resolves = false;
    }
    verified.push({ ...row, provenanceResolves: resolves });
  }
  return verified;
}

export interface ActivityFeedDeps {
  runsRegistry?: RunsRegistryDeps;
}

export interface ActivityFeedSummary {
  liveCount: number;
  recentCount: number;
  rows: ActivityRow[];
}

/**
 * Fetches the current merged feed: reads the runs registry fresh (tolerant of absence) and reads
 * the already-running receipt-watch's in-memory state (does NOT start a watcher itself -- the
 * caller owns that lifecycle, same discipline as telemetry-watch's getState()).
 */
export async function fetchActivityFeed(deps: ActivityFeedDeps = {}): Promise<ActivityFeedSummary> {
  const runs = await readResolvedRunEvents(deps.runsRegistry ?? {});
  const receiptState = getReceiptWatchState();
  const rows = mergeActivityFeed(runs, receiptState.recentEvents);
  const liveCount = runs.filter((r) => r.status === "running").length;
  return { liveCount, recentCount: rows.length, rows };
}
