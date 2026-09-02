// core/receipt-age.ts — utilities for formatting board receipt age and detecting staleness.
// Converts ISO8601 timestamp to relative age ("2h14m ago") and determines if stale (>2h, see
// isReceiptStale's own comment for why 2h and not the tighter value this started at).

export function formatReceiptAge(boardTs: string, nowMs: number = Date.now()): string {
  const receiptTime = parseIso8601(boardTs);
  if (!receiptTime) return "unknown";

  const ageMs = nowMs - receiptTime.getTime();
  if (ageMs < 0) return "future";

  const ageSeconds = Math.floor(ageMs / 1000);
  const ageMinutes = Math.floor(ageSeconds / 60);
  const ageHours = Math.floor(ageMinutes / 60);
  const ageDays = Math.floor(ageHours / 24);

  if (ageDays > 0) {
    return `${ageDays}d ago`;
  }
  if (ageHours > 0) {
    const mins = ageMinutes % 60;
    return mins > 0 ? `${ageHours}h${mins}m ago` : `${ageHours}h ago`;
  }
  if (ageMinutes > 0) {
    return `${ageMinutes}m ago`;
  }
  return "just now";
}

// #405 review: default was 30min, which cried wolf on the boot screen -- board runs are
// landing-driven (mandated within 45min of a merge, plus multi-hour natural gaps between landings),
// so a fresh receipt routinely read stale a refresh or two later (observed live in the same session:
// "board: 25m ago" then "STALE: 30m ago" for the same underlying receipt, one refresh apart). Red
// should mean "outside expected cadence", not "no one has merged in the last half hour" -- 2h
// matches the audit-loop's own cadence and is the signal actually worth a red badge.
// Exported (#412) so callers that need to reason about the threshold -- test fixtures especially --
// derive from this single source instead of re-hardcoding the number, which is exactly how the
// world-state.test.ts fixture went stale against this same value twice already.
export const DEFAULT_STALE_THRESHOLD_MS = 2 * 60 * 60 * 1000;

export function isReceiptStale(boardTs: string, nowMs: number = Date.now(), staleThresholdMs: number = DEFAULT_STALE_THRESHOLD_MS): boolean {
  const receiptTime = parseIso8601(boardTs);
  if (!receiptTime) return false;

  const ageMs = nowMs - receiptTime.getTime();
  return ageMs > staleThresholdMs;
}

function parseIso8601(ts: string): Date | null {
  if (ts.includes("-")) {
    const parsed = new Date(ts);
    return isNaN(parsed.getTime()) ? null : parsed;
  }

  if (ts.match(/^\d{8}T\d{6}Z$/)) {
    const year = parseInt(ts.slice(0, 4), 10);
    const month = parseInt(ts.slice(4, 6), 10) - 1;
    const day = parseInt(ts.slice(6, 8), 10);
    const hours = parseInt(ts.slice(9, 11), 10);
    const minutes = parseInt(ts.slice(11, 13), 10);
    const seconds = parseInt(ts.slice(13, 15), 10);
    const parsed = new Date(Date.UTC(year, month, day, hours, minutes, seconds));
    return isNaN(parsed.getTime()) ? null : parsed;
  }

  return null;
}
