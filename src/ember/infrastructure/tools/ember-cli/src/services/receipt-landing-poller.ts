// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/receipt-landing-poller.ts — issue #447: "last-receipt age" telemetry -- the newest
// file mtime anywhere under the repo's receipts/ tree, so the cockpit can show "receipts are
// landing" vs "nothing landed for N hours" independent of any specific board/run receipt.
//
// This is deliberately a CHEAP, BOUNDED scan, not an exhaustive walk: the real receipts/ tree
// accumulates files from every lane/run across the project's whole history (tens of thousands
// of entries is realistic), and re-stat'ing all of them on every poll tick would cost real I/O
// for a background TUI signal. Two bounds keep this honest without becoming a footgun:
//   - maxDepth: how many directory levels deep to recurse (receipts/<lane>/<file> is the modal
//     shape -- 2 levels -- so a modest bound covers real structure without walking forever).
//   - maxEntries: a total files-visited budget: once exhausted, the walk stops and returns
//     whatever newest mtime it found SO FAR, rather than blocking indefinitely on a
//     pathologically wide tree. A bounded-but-honest answer beats a slow/hanging one -- the
//     signal this feeds ("receipts landing" vs "nothing for N hours") tolerates being built
//     from a large sample rather than literally everything on disk.

import fs from "node:fs/promises";
import path from "node:path";
import { formatReceiptAge, isReceiptStale } from "../core/receipt-age.ts";

export const DEFAULT_MAX_WALK_DEPTH = 4;
export const DEFAULT_MAX_ENTRIES = 5000;

export interface ReceiptLandingResult {
  /** Path to the newest-mtime file found, relative to receiptsRoot. */
  relativePath: string;
  mtimeMs: number;
  /** True when maxEntries was hit before the walk finished -- the result is still the newest
   *  found among the entries actually visited, but callers may want to know the scan was
   *  partial (e.g. to avoid over-trusting an "idle" reading on a huge tree). */
  truncated: boolean;
}

export interface ReceiptLandingScanOptions {
  maxDepth?: number;
  maxEntries?: number;
}

/**
 * Finds the newest-mtime file anywhere under `receiptsRoot`, bounded by depth and a total
 * files-visited budget. Fails open throughout: an unreadable directory is skipped (never
 * thrown), and a missing root simply yields null (no receipts tree = nothing to report, not an
 * error).
 */
export async function findNewestReceiptMtime(
  receiptsRoot: string,
  options: ReceiptLandingScanOptions = {},
): Promise<ReceiptLandingResult | null> {
  const maxDepth = options.maxDepth ?? DEFAULT_MAX_WALK_DEPTH;
  const maxEntries = options.maxEntries ?? DEFAULT_MAX_ENTRIES;

  let best: { path: string; mtimeMs: number } | null = null;
  let visited = 0;
  let truncated = false;

  async function walk(dir: string, depth: number): Promise<void> {
    if (truncated || depth > maxDepth) return;
    let entries: import("node:fs").Dirent[];
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch {
      return; // unreadable dir -- skip, never throw
    }

    for (const entry of entries) {
      if (truncated) return;
      if (visited >= maxEntries) {
        truncated = true;
        return;
      }
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(full, depth + 1);
      } else if (entry.isFile()) {
        visited++;
        try {
          const st = await fs.stat(full);
          if (!best || st.mtimeMs > best.mtimeMs) {
            best = { path: full, mtimeMs: st.mtimeMs };
          }
        } catch {
          // Race: file vanished between readdir and stat -- skip it.
        }
      }
    }
  }

  try {
    await walk(receiptsRoot, 0);
  } catch {
    return null;
  }
  if (!best) return null;

  const resolved: { path: string; mtimeMs: number } = best;
  return {
    relativePath: path.relative(receiptsRoot, resolved.path),
    mtimeMs: resolved.mtimeMs,
    truncated,
  };
}

/** Converts a file mtime (epoch ms) into the same age-formatting primitives the rest of the
 *  cockpit already uses (core/receipt-age.ts) -- so "last receipt: 2h14m ago" / "STALE" never
 *  drifts from the board-age badge's own semantics. */
export function formatReceiptLandingAge(mtimeMs: number, nowMs: number = Date.now()): { text: string; stale: boolean } {
  const iso = new Date(mtimeMs).toISOString();
  return { text: formatReceiptAge(iso, nowMs), stale: isReceiptStale(iso, nowMs) };
}

/** Formats the last-receipt-landing feed line, e.g. "receipts: landing 3m ago" / red "receipts:
 *  STALE 3h ago" past the 2h threshold -- "receipts are landing" vs "nothing for N hours" at a
 *  glance, per issue #447. Returns null when no receipt was found anywhere (empty/missing
 *  receipts/ tree) -- never a fabricated reading. */
export function formatLastReceiptLine(
  result: ReceiptLandingResult | null,
  nowMs: number = Date.now(),
): { text: string; color?: string } | null {
  if (!result) return null;
  const { text, stale } = formatReceiptLandingAge(result.mtimeMs, nowMs);
  return stale
    ? { text: `receipts: STALE ${text}`, color: "red" }
    : { text: `receipts: landing ${text}` };
}

// ---------------------------------------------------------------------------
// React polling hook
// ---------------------------------------------------------------------------

/** Poll cadence: a bounded recursive walk every tick -- slow, matching the other file-scanning
 *  pollers here. 30s: this signal changes on the timescale of "did anything land recently",
 *  never worth sub-minute precision. */
export const DEFAULT_RECEIPT_LANDING_POLL_INTERVAL_MS = 30_000;

import { useEffect, useState } from "react";

export function useReceiptLandingPoller(
  receiptsRoot: string,
  intervalMs: number = DEFAULT_RECEIPT_LANDING_POLL_INTERVAL_MS,
): ReceiptLandingResult | null {
  const [state, setState] = useState<ReceiptLandingResult | null>(null);

  useEffect(() => {
    let active = true;

    const poll = async (): Promise<void> => {
      const result = await findNewestReceiptMtime(receiptsRoot);
      if (active) setState(result);
    };

    void poll();
    const id = setInterval(() => void poll(), intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [receiptsRoot, intervalMs]);

  return state;
}
