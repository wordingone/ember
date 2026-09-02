// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/poll-failure-dedup.ts — issue #1698: OFFLINE-mode watcher pollers
// (memory-footprint-live.ts, memory-footprint-service.ts, serving-topology-live.ts)
// used to console.warn on every failed tick. That write bypasses Ink's own frame-write
// channel entirely (Ink renders through an injected stream, never through the process's
// raw stdout/stderr), so at 1s/5s poll cadence the operator's screen accumulated dozens
// of interleaved raw fragments within minutes, overwriting arbitrary panel cells.
//
// This collapses repeated same-class failures into at most one published line per
// `intervalMs` window (leading edge: the first occurrence in a fresh window publishes
// immediately, carrying forward the suppressed count from the PRIOR window so no failure
// burst is silently dropped) instead of one raw write per tick.

export interface PollFailureDeduperOptions {
  /** Failures for the same classKey within this window collapse into one publish. */
  intervalMs: number;
  /** Clock injection for deterministic tests; defaults to Date.now. */
  now?: () => number;
  /** Where a de-duplicated failure line is sent (e.g. the activity feed). */
  publish: (text: string) => void;
}

export interface PollFailureDeduper {
  /** Reports one failure occurrence for `classKey`. May or may not publish. */
  report(classKey: string, message: string): void;
}

interface ClassWindow {
  windowStart: number;
  suppressedCount: number;
}

export function createPollFailureDeduper(options: PollFailureDeduperOptions): PollFailureDeduper {
  const windows = new Map<string, ClassWindow>();
  return {
    report(classKey: string, message: string): void {
      const now = options.now?.() ?? Date.now();
      const existing = windows.get(classKey);
      if (existing !== undefined && now - existing.windowStart < options.intervalMs) {
        existing.suppressedCount += 1;
        return;
      }
      const suffix =
        existing !== undefined && existing.suppressedCount > 0
          ? ` (+${existing.suppressedCount} more suppressed in the last ${options.intervalMs}ms)`
          : "";
      options.publish(`${message}${suffix}`);
      windows.set(classKey, { windowStart: now, suppressedCount: 0 });
    },
  };
}
