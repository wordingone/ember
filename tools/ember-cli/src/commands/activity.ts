// commands/activity.ts — /activity slash command. Toggles the receipt-watch on/off and, on
// every invocation, prints a real multi-line snapshot of the merged runs+receipts feed --
// same shape as /observatory's runObservatory (header + body, pure and independently testable).
// The status bar's own "unprompted" activity segment (components/status-bar.ts) is fed by the
// SAME services/activity-feed.ts on an always-on poll independent of this command; /activity is
// the on-demand DETAILED view, not the only place the R0 surface is visible.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import {
  startReceiptWatch,
  getReceiptWatchState,
  type ReceiptWatchHandle,
} from "../services/receipt-watch.ts";
import { fetchActivityFeed, type ActivityFeedSummary } from "../services/activity-feed.ts";
import { formatActivityRowLine } from "../components/activity-pane.ts";

const HEADER = "=== Activity: live runs + recent receipts ===";
const MAX_ROWS_DISPLAY = 10;

/**
 * Deterministic multi-line view of a feed summary. Pure function of already-fetched data (no
 * I/O), so it is directly testable without touching the filesystem or a running watcher.
 */
export function runActivityReport(summary: ActivityFeedSummary, nowMs: number): string {
  const lines: string[] = [HEADER];

  if (summary.rows.length === 0) {
    lines.push("no live activity");
    return lines.join("\n");
  }

  lines.push(`${summary.liveCount} live · ${summary.recentCount} recent`);
  for (const row of summary.rows.slice(0, MAX_ROWS_DISPLAY)) {
    lines.push(`  ${formatActivityRowLine(row, nowMs)}`);
  }
  const overflow = summary.rows.length - MAX_ROWS_DISPLAY;
  if (overflow > 0) lines.push(`  +${overflow} more`);

  return lines.join("\n");
}

interface ActivityDeps {
  startReceiptWatch?: typeof startReceiptWatch;
  getReceiptWatchState?: typeof getReceiptWatchState;
  fetchActivityFeed?: typeof fetchActivityFeed;
  now?: () => number;
}

/** Creates the /activity command with injected deps (test seam, same shape as createWatchCommand). */
export function createActivityCommand(deps: ActivityDeps = {}): RegistryCommand {
  const startWatch = deps.startReceiptWatch ?? startReceiptWatch;
  const fetchFeed = deps.fetchActivityFeed ?? fetchActivityFeed;
  const now = deps.now ?? Date.now;
  void (deps.getReceiptWatchState ?? getReceiptWatchState); // reserved for future direct-state reads

  let watchHandle: ReceiptWatchHandle | null = null;
  let isWatching = false;

  return {
    name: "activity",
    description: "Show live runs + recent receipts; first call also starts the background watch",
    isEnabled(): boolean {
      return true;
    },
    async execute(_args: string, _ctx: CommandContext) {
      if (!isWatching) {
        watchHandle = startWatch();
        isWatching = true;
      }
      const summary = await fetchFeed();
      return { type: "message" as const, message: runActivityReport(summary, now()) };
    },
  };
}
