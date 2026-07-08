// services/board-ts-poller.ts — issue #420: cockpit boardTs live refresh.
//
// screens/repl.ts's home-screen mount reads the newest totality-board receipt exactly once (see
// core/ember-world-state.ts's buildEmberWorldState, called from the mount useEffect) -- a NEW
// receipt landing while the cockpit keeps running was never picked up, so the badge kept aging
// against a receipt that was no longer the newest one on disk. This hook is the live half: it
// polls the SAME receipts-totality directory on a slow (30-60s) cadence and hands back a fresh
// boardTs the moment a newer receipt appears, using core/ember-world-state.ts's #420
// pollForNewerBoardTs primitive so steady-state ticks are a directory listing, never a
// JSON.parse, unless the newest filename actually changed.
//
// Same shape as model-metrics-poller.ts / circuit-breaker-banner-poller.ts: this hook is a thin
// setInterval/useState shell around a pure, independently-tested function
// (pollForNewerBoardTs, tested in core/ember-world-state.test.ts) -- it is not separately
// render-tested for the same reason those two poller hooks aren't: no React render cycle is
// needed to prove the polling projection is correct.

import { useEffect, useRef, useState } from "react";
import { peekNewestBoardReceiptFilename, pollForNewerBoardTs } from "../core/ember-world-state.ts";

/** Poll cadence for the live boardTs refresh -- #420 spec: "30-60s interval, NOT per-second". */
export const DEFAULT_BOARD_TS_POLL_INTERVAL_MS = 45_000;

/**
 * Polls `goalforgeRoot`'s board-receipts directory at `intervalMs` cadence for a receipt newer
 * than the one last seen. Returns null until the first newer receipt lands -- the caller keeps
 * whatever boardTs it already has (typically from its own mount-time read) until then -- then the
 * newest receipt's `ts` field from that point on.
 *
 * Fails open: a missing directory, an unreadable file, or a torn/partial write never throws out
 * of this hook. The last known boardTs is held by the CALLER (this hook only reports changes), so
 * a failed tick simply changes nothing and the next tick tries again.
 */
export function useBoardTsPoller(
  goalforgeRoot: string,
  intervalMs: number = DEFAULT_BOARD_TS_POLL_INTERVAL_MS,
): string | null {
  const [boardTs, setBoardTs] = useState<string | null>(null);
  const lastFilenameRef = useRef<string | undefined>(undefined);
  const seededRef = useRef(false);

  useEffect(() => {
    let active = true;
    seededRef.current = false;

    // Cheap baseline (directory listing + name sort only, no parse): establishes which receipt
    // screens/repl.ts's own mount-time read already picked up, so the FIRST interval tick doesn't
    // treat that same receipt as "new" and pay for a pointless re-parse.
    const seed = async (): Promise<void> => {
      const filename = await peekNewestBoardReceiptFilename(goalforgeRoot);
      if (!active) return;
      lastFilenameRef.current = filename ?? undefined;
      seededRef.current = true;
    };
    void seed();

    const poll = async (): Promise<void> => {
      if (!seededRef.current) return; // baseline not established yet -- wait for the next tick
      try {
        const result = await pollForNewerBoardTs(goalforgeRoot, lastFilenameRef.current);
        if (!active || !result) return;
        lastFilenameRef.current = result.filename;
        setBoardTs(result.boardTs);
      } catch {
        // Fail open (#420 spec): a polling error never surfaces to the UI -- keep the last known
        // boardTs and simply retry on the next tick.
      }
    };
    const id = setInterval(() => void poll(), intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [goalforgeRoot, intervalMs]);

  return boardTs;
}
