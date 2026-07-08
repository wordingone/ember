// core/watch-render.ts — pure/small-I/O helpers for the REPL's `--watch` ambient observatory mode.
// Kept separate from repl-render.ts (interactive prompt/wrap/banner) and monitor-render.ts (the
// board itself): this module owns only what's specific to unattended, timer-driven refresh --
// arg parsing, the watch header line, the newest-receipts tail, the refresh-error line, and the
// single-cycle composer (runWatchCycle). Deliberately NOT in ember-world-state-repl.ts: that file
// calls main() unconditionally at import time, so anything a test needs to import directly (like
// runWatchCycle) has to live somewhere import-safe -- same reasoning that keeps monitor-render.ts
// and repl-render.ts as separate pure modules.

import { readdir, stat } from "fs/promises";
import path from "path";
import { buildEmberWorldState, GOALFORGE_ROOT } from "./ember-world-state.ts";
import { renderMonitorPanel, colorEnabledFor } from "./monitor-render.ts";

// ---------------------------------------------------------------------------
// --watch / --interval arg parsing
// ---------------------------------------------------------------------------

export const DEFAULT_INTERVAL_SEC = 30;
export const MIN_INTERVAL_SEC = 5;

export interface WatchArgs {
  watch: boolean;
  intervalSec: number;
}

/** Parses argv (already sliced to just the CLI args, e.g. process.argv.slice(2)). Unknown
 * flags/values never throw -- an unparsable --interval falls back to the default, and any
 * requested interval below MIN_INTERVAL_SEC is floored, never rejected. */
export function parseWatchArgs(argv: string[]): WatchArgs {
  const watch = argv.includes("--watch");
  let intervalSec = DEFAULT_INTERVAL_SEC;
  const idx = argv.indexOf("--interval");
  if (idx !== -1 && argv[idx + 1] !== undefined) {
    const parsed = Number(argv[idx + 1]);
    if (Number.isFinite(parsed)) intervalSec = parsed;
  }
  return { watch, intervalSec: Math.max(MIN_INTERVAL_SEC, intervalSec) };
}

// ---------------------------------------------------------------------------
// Header / error lines
// ---------------------------------------------------------------------------

export function renderWatchHeader(now: Date, intervalSec: number): string {
  return `EMBER OBSERVATORY  ${now.toLocaleTimeString()}  refresh ${intervalSec}s`;
}

export function renderRefreshError(reason: string, intervalSec: number): string {
  return `refresh failed (${reason}), retrying in ${intervalSec}s`;
}

// ---------------------------------------------------------------------------
// Newest-receipts tail
// ---------------------------------------------------------------------------

export interface ReceiptStat {
  path: string; // goalforge-root-relative, forward-slashed
  mtimeMs: number;
}

/** "4m ago" / "12s ago" / "3h ago" / "2d ago" -- floors to whole units, never negative. */
export function formatAge(ms: number): string {
  const clamped = Math.max(0, ms);
  const sec = Math.floor(clamped / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

/** Recursively scans `<goalforgeRoot>/receipts` for the `count` most-recently-modified files.
 * Returns [] (never throws) if the directory is missing or unreadable -- a transient/missing
 * receipts tree during a refresh degrades to an empty tail, not a crash. */
export async function findNewestReceipts(
  goalforgeRoot: string,
  count: number = 3,
): Promise<ReceiptStat[]> {
  const dir = path.join(goalforgeRoot, "receipts");
  type DirentLike = { name: string; parentPath?: string; path?: string; isFile(): boolean };
  let entries: DirentLike[];
  try {
    entries = (await readdir(dir, { recursive: true, withFileTypes: true })) as unknown as DirentLike[];
  } catch {
    return [];
  }
  const files = entries.filter((e) => e.isFile());
  const stats = await Promise.all(
    files.map(async (e) => {
      const full = path.join(e.parentPath ?? e.path ?? dir, e.name);
      try {
        const s = await stat(full);
        return { path: path.relative(goalforgeRoot, full).replace(/\\/g, "/"), mtimeMs: s.mtimeMs };
      } catch {
        return null;
      }
    }),
  );
  const valid = stats.filter((s): s is ReceiptStat => s !== null);
  valid.sort((a, b) => b.mtimeMs - a.mtimeMs);
  return valid.slice(0, count);
}

/** Renders the 3-line (or fewer, if fewer receipts exist) tail: "<path> (<age>)" per line, e.g.
 * "receipts/c7-selftest-....json (4m ago)" -- formatAge() already includes the trailing "ago". */
export function renderReceiptsTail(receipts: ReceiptStat[], nowMs: number): string[] {
  if (receipts.length === 0) return ["no receipts found"];
  return receipts.map((r) => `${r.path} (${formatAge(nowMs - r.mtimeMs)})`);
}

// ---------------------------------------------------------------------------
// Single-refresh-cycle composer
// ---------------------------------------------------------------------------

const CLEAR_SCREEN = "\x1b[2J\x1b[H";

export interface WatchCycleOptions {
  intervalSec: number;
  isTTY: boolean;
  colorEnabled: boolean;
  goalforgeRoot?: string; // override for tests; defaults to the real GOALFORGE_ROOT below
  now?: Date; // override for tests
}

/**
 * Renders exactly ONE watch refresh as an array of lines -- exported standalone so tests can run
 * a single cycle directly without a timer or a spawned process. Rebuilds EmberWorldState fresh
 * every call (buildEmberWorldState() never caches -- see core/ember-world-state.ts), so a new
 * receipt landing between calls is picked up on the very next cycle. On any failure (a receipt
 * mid-write, a transient FS error, a missing goalforge root) this returns a one-line error message
 * instead of throwing -- the caller's timer loop must survive indefinitely.
 */
export async function runWatchCycle(opts: WatchCycleOptions): Promise<string[]> {
  const now = opts.now ?? new Date();
  const root = opts.goalforgeRoot ?? GOALFORGE_ROOT;
  const lines: string[] = [opts.isTTY ? CLEAR_SCREEN : "----------------------------------------"];
  try {
    const state = await buildEmberWorldState({ goalforgeRoot: root });
    const receipts = await findNewestReceipts(root, 3);
    lines.push(renderWatchHeader(now, opts.intervalSec));
    // Use renderMonitorPanel with boardTs to show the staleness badge on boot, same as /world-state
    const width = 100; // default width for watch cycles (matches terminal standard)
    lines.push(...renderMonitorPanel(state, {
      colorEnabled: opts.colorEnabled,
      width,
      boardTs: state.monitor.boardTs,
      nowMs: now.getTime()
    }));
    lines.push(...renderReceiptsTail(receipts, now.getTime()));
  } catch (err) {
    lines.push(renderRefreshError((err as Error).message, opts.intervalSec));
  }
  return lines;
}
