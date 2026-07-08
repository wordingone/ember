// services/board-ts-poller.ts — issue #420: cockpit boardTs live refresh; issue #433: board
// condition transitions (GREEN<->RED) surfaced as activity events on the same poll.
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
// #433 rides that same poll: whenever pollForNewerBoardTs finds a changed receipt, this hook
// diffs its rows (core/ember-world-state.ts's diffBoardConditions) against the previously-seen
// rows and formats one activity-feed line per changed condition (core/monitor-render.ts's
// formatBoardTransitionEvent) -- no new timer, no new service, riding the existing #420 poll.
//
// Same shape as model-metrics-poller.ts / circuit-breaker-banner-poller.ts: this hook is a thin
// setInterval/useState shell around pure, independently-tested functions (pollForNewerBoardTs +
// diffBoardConditions, tested in core/ember-world-state.test.ts; formatBoardTransitionEvent,
// tested in core/monitor-render.test.ts) -- it is not separately render-tested for the same
// reason those two poller hooks aren't: no React render cycle is needed to prove the polling
// projection is correct.

import { useEffect, useRef, useState } from "react";
import {
  findNewestBoardReceipt,
  pollForNewerBoardTs,
  diffBoardConditions,
  type BoardRow,
} from "../core/ember-world-state.ts";
import { formatBoardTransitionEvent } from "../core/monitor-render.ts";

/** Poll cadence for the live boardTs refresh -- #420 spec: "30-60s interval, NOT per-second". */
export const DEFAULT_BOARD_TS_POLL_INTERVAL_MS = 45_000;

/** Cap on the accumulated transition-event feed -- a long-lived session polling every 45s for
 * days should never grow this list unbounded. Newest events are prepended, so the cap simply
 * drops the oldest entries once exceeded (#433: no bar on a specific number, chosen to comfortably
 * cover "what changed recently" without becoming its own scroll-back log). */
export const MAX_BOARD_TRANSITION_EVENTS = 20;

export interface BoardTransitionFeedEntry {
  text: string;
  color?: string;
}

export interface BoardTsPollState {
  boardTs: string | null;
  /** Newest-first list of formatted transition events accumulated this session (capped at
   * MAX_BOARD_TRANSITION_EVENTS). Empty until the first genuine condition transition is detected
   * -- the first poll after boot never populates this (see diffBoardConditions' boot-suppression
   * contract). */
  events: BoardTransitionFeedEntry[];
}

/**
 * Polls `goalforgeRoot`'s board-receipts directory at `intervalMs` cadence for a receipt newer
 * than the one last seen. `boardTs` stays null until the first newer receipt lands -- the caller
 * keeps whatever boardTs it already has (typically from its own mount-time read) until then --
 * then the newest receipt's `ts` field from that point on. `events` accumulates one formatted
 * line per board-condition transition detected across polls (#433).
 *
 * Fails open: a missing directory, an unreadable file, or a torn/partial write never throws out
 * of this hook. The last known boardTs is held by the CALLER (this hook only reports changes), so
 * a failed tick simply changes nothing and the next tick tries again. A malformed receipt at seed
 * time (mount) is likewise swallowed -- the baseline is just empty, so the first fix-up poll
 * self-heals without ever throwing.
 */
export function useBoardTsPoller(
  goalforgeRoot: string,
  intervalMs: number = DEFAULT_BOARD_TS_POLL_INTERVAL_MS,
): BoardTsPollState {
  const [boardTs, setBoardTs] = useState<string | null>(null);
  const [events, setEvents] = useState<BoardTransitionFeedEntry[]>([]);
  const lastFilenameRef = useRef<string | undefined>(undefined);
  const lastRowsRef = useRef<BoardRow[]>([]);
  const seededRef = useRef(false);

  useEffect(() => {
    let active = true;
    seededRef.current = false;

    // Baseline: a full parse (not just the cheap filename peek #420 originally used) so #433's
    // diff has real rows to compare the FIRST detected change against -- without this, the first
    // genuine transition after boot would silently drop (diffed against an empty baseline looks
    // identical to "no prior receipt"). One JSON.parse of a small receipt at mount time only, never
    // repeated on steady-state ticks below. Fails open: a missing dir or malformed receipt at
    // mount just leaves the baseline empty rather than throwing.
    const seed = async (): Promise<void> => {
      try {
        const result = await findNewestBoardReceipt(goalforgeRoot);
        if (!active) return;
        lastFilenameRef.current = result?.filename;
        lastRowsRef.current = result?.parsed.rows ?? [];
      } catch {
        lastFilenameRef.current = undefined;
        lastRowsRef.current = [];
      } finally {
        if (active) seededRef.current = true;
      }
    };
    void seed();

    const poll = async (): Promise<void> => {
      if (!seededRef.current) return; // baseline not established yet -- wait for the next tick
      try {
        const result = await pollForNewerBoardTs(goalforgeRoot, lastFilenameRef.current);
        if (!active || !result) return;

        const transitions = diffBoardConditions(lastRowsRef.current, result.rows);
        lastFilenameRef.current = result.filename;
        lastRowsRef.current = result.rows;
        setBoardTs(result.boardTs);

        if (transitions.length > 0) {
          const counts = { green: result.green, red: result.red };
          const newEntries = transitions.map((t) => formatBoardTransitionEvent(t, counts));
          setEvents((prev) => [...newEntries, ...prev].slice(0, MAX_BOARD_TRANSITION_EVENTS));
        }
      } catch {
        // Fail open (#420 spec): a polling error never surfaces to the UI -- keep the last known
        // boardTs/events and simply retry on the next tick.
      }
    };
    const id = setInterval(() => void poll(), intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [goalforgeRoot, intervalMs]);

  return { boardTs, events };
}
