// core/receipt-age.ts — utilities for formatting board receipt age and detecting staleness.
// Converts ISO8601 timestamp to relative age ("2h14m ago") and determines if stale (>30min).

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

export function isReceiptStale(boardTs: string, nowMs: number = Date.now(), staleThresholdMs: number = 30 * 60 * 1000): boolean {
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
