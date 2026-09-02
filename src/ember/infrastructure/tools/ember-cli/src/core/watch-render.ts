// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/watch-render.ts — small receipts-tail helpers used by commands/world-state.ts's /cockpit
// (/board) "monitor" turn: scans the goalforge root's receipts/ tree for the newest N files and
// renders a short "<path> (<age>)" tail alongside the board panel.
//
// #405 cleanup: this file previously also hosted a "--watch ambient observatory mode"
// (parseWatchArgs/renderWatchHeader/renderRefreshError/runWatchCycle) that was never wired to any
// real entrypoint -- a full-tree import search found zero production callers. It had already misled
// two lanes into believing runWatchCycle was the boot screen's renderer (the actual boot-screen
// painter is components/logo-homescreen.ts's BoardSummary widget). Removed rather than left in place
// to mislead a third reader; findNewestReceipts/renderReceiptsTail below are the only exports this
// file ever had a real caller for. If ambient --watch mode is wanted later, rebuild it against the
// real CLI entrypoint from scratch, not by resurrecting this dead composer.

import { readdir, stat } from "fs/promises";
import path from "path";

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
