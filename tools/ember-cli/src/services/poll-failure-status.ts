// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/poll-failure-status.ts — issue #1701: services/poll-failure-dedup.ts (#1698/#1700)
// correctly stopped watcher pollers (memory-footprint, serving-topology) from bleeding raw
// stdout, but its window-republish design still surfaces a NEW activity-feed/transcript entry
// every POLL_FAILURE_DEDUP_INTERVAL_MS while a failure class stays active -- an idle OFFLINE
// cockpit's transcript becomes a monotone failure ticker within minutes, burying real operator
// activity. The steady state of a KNOWN, UNCHANGED failure class is STATUS, not news.
//
// This module replaces the dedup's role in screens/repl.ts (poll-failure-dedup.ts itself is
// left wired exactly as-is nowhere else and untouched -- its own tests keep describing a valid,
// independent rate-limiting utility). Instead of "collapse into one publish per window", this
// tracks a running per-classKey status (message, occurrence count, first-seen/last-seen time)
// and publishes a TRANSITION line -- never a per-tick or per-window repeat -- exactly three
// times per failure lifecycle: the class is first seen, its message changes, or it recovers
// (goes silent long enough that the poller is presumed healthy again). Between transitions the
// in-place status (getActiveStatuses()) is what the sticky status region renders from.

export interface PollFailureStatusEntry {
  classKey: string;
  /** Latest reported message for this class. */
  message: string;
  /** Total report() calls since this class was first seen (this streak, since the last recovery). */
  count: number;
  /** Epoch ms of the first report() call in this streak. */
  since: number;
  /** Epoch ms of the most recent report() call. */
  lastSeenAt: number;
}

export interface PollFailureStatusTrackerOptions {
  /** Clock injection for deterministic tests; defaults to Date.now. */
  now?: () => number;
  /** ms of report() silence after which an active class is presumed recovered. */
  recoveryAfterMs: number;
  /** Called exactly once per transition (started / message changed / recovered) with the line
   *  text to publish to the activity feed (and, from there, the durable ledger). */
  publishTransition: (text: string) => void;
}

export interface PollFailureStatusTracker {
  /** Reports one failure occurrence for `classKey`. Publishes a transition line only on
   *  first-seen or message-change; otherwise silently updates the in-place status. */
  report(classKey: string, message: string): void;
  /** Sweeps for classes gone silent >= recoveryAfterMs: publishes one "recovered" transition
   *  per lapsed class and removes it from the active set. Call periodically (e.g. from an
   *  existing render-side poll tick) -- never invoked internally on a timer of its own, so a
   *  caller that stops ticking (unmount) leaves no dangling timer behind. */
  sweep(): void;
  /** Snapshot of currently active (unrecovered) classes, oldest-first -- what the sticky status
   *  region renders. */
  getActiveStatuses(): PollFailureStatusEntry[];
}

function formatDurationCompact(ms: number): string {
  const clamped = Math.max(0, ms);
  const totalSec = Math.floor(clamped / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const totalMin = Math.floor(totalSec / 60);
  if (totalMin < 60) return `${totalMin}m${totalSec % 60}s`;
  const hours = Math.floor(totalMin / 60);
  return `${hours}h${totalMin % 60}m`;
}

export function formatFailureStartedLine(message: string): string {
  return message;
}

export function formatFailureMessageChangedLine(classKey: string, message: string): string {
  return `${classKey}: ${message} (failure detail changed)`;
}

export function formatFailureRecoveredLine(entry: PollFailureStatusEntry, recoveredAt: number): string {
  const duration = formatDurationCompact(recoveredAt - entry.since);
  const occurrences = entry.count === 1 ? "1 occurrence" : `${entry.count} occurrences`;
  return `${entry.classKey} recovered after ${occurrences} over ${duration}`;
}

export function createPollFailureStatusTracker(
  options: PollFailureStatusTrackerOptions,
): PollFailureStatusTracker {
  const now = options.now ?? Date.now;
  const active = new Map<string, PollFailureStatusEntry>();

  return {
    report(classKey: string, message: string): void {
      const ts = now();
      const existing = active.get(classKey);
      if (existing === undefined) {
        active.set(classKey, { classKey, message, count: 1, since: ts, lastSeenAt: ts });
        options.publishTransition(formatFailureStartedLine(message));
        return;
      }
      existing.count += 1;
      existing.lastSeenAt = ts;
      if (existing.message !== message) {
        existing.message = message;
        options.publishTransition(formatFailureMessageChangedLine(classKey, message));
      }
    },

    sweep(): void {
      const ts = now();
      for (const [classKey, entry] of active) {
        if (ts - entry.lastSeenAt >= options.recoveryAfterMs) {
          active.delete(classKey);
          options.publishTransition(formatFailureRecoveredLine(entry, ts));
        }
      }
    },

    getActiveStatuses(): PollFailureStatusEntry[] {
      return [...active.values()].sort((a, b) => a.since - b.since);
    },
  };
}
