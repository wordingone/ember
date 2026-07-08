// components/activity-feed-pane.ts — issue #485 rung 1: the operator-visible half of the
// activity feed. Renders the tail of REAL observed events (receipt landings, outage windows,
// watchdog transitions, board runs) that the services/activity-feed.ts engine has actually
// rendered — never a fabricated/synthetic tick (GOAL.md P-C). Each line carries its artifact
// path so the feed doubles as an audit surface, per L2.

import React from "react";
import { Box, Text } from "../ink/components.ts";
import { formatReceiptAge } from "../core/receipt-age.ts";

// ---------------------------------------------------------------------------
// Types (owned here — services/activity-feed.ts imports these, mirroring the
// ModelMetrics convention: components/status-bar.ts owns the shape, the
// producing service imports the type).
// ---------------------------------------------------------------------------

export type ActivityFeedSource = "receipt" | "outage" | "watchdog" | "board";

export interface ActivityFeedLine {
  ts: string; // ISO8601Z — when the CLI actually rendered this event
  source: ActivityFeedSource;
  text: string;
  /** Artifact path this event points at (receipt file, marker, ledger, board file). */
  path?: string;
}

// ---------------------------------------------------------------------------
// Pure formatting (unit-testable without touching fs or React)
// ---------------------------------------------------------------------------

export const DEFAULT_VISIBLE_LINES = 6;
export const DEFAULT_PATH_MAX_LEN = 48;

/** Middle-truncates a long path: "very/long/path/to/file.json" -> "very/lo…o/file.json". */
export function truncateMiddle(value: string, maxLen: number = DEFAULT_PATH_MAX_LEN): string {
  if (value.length <= maxLen) return value;
  if (maxLen <= 1) return value.slice(0, Math.max(maxLen, 0));
  const keep = maxLen - 1; // reserve one column for the ellipsis glyph
  const head = Math.ceil(keep / 2);
  const tail = Math.floor(keep / 2);
  return `${value.slice(0, head)}…${value.slice(value.length - tail)}`;
}

/** Returns the last `maxVisible` lines, oldest-first — so rendering them in order puts the
 *  newest line at the bottom, matching a normal scrolling log. */
export function visibleActivityFeedLines(
  lines: ActivityFeedLine[],
  maxVisible: number = DEFAULT_VISIBLE_LINES,
): ActivityFeedLine[] {
  if (maxVisible <= 0) return [];
  return lines.slice(-maxVisible);
}

/** One display row: "<age> · [<source>] <text> [<truncated-path>]". */
export function formatActivityFeedLine(
  line: ActivityFeedLine,
  nowMs: number = Date.now(),
  pathMaxLen: number = DEFAULT_PATH_MAX_LEN,
): string {
  const age = formatReceiptAge(line.ts, nowMs);
  const pathSuffix = line.path ? ` [${truncateMiddle(line.path, pathMaxLen)}]` : "";
  return `${age} · [${line.source}] ${line.text}${pathSuffix}`;
}

/** Shown when the feed has never rendered a single real event — an honest absence statement,
 *  never a fabricated heartbeat (the exact failure mode issue #485 names: "a keyframed flame is
 *  a fabricated receipt in visual form"). */
export const EMPTY_STATE_TEXT = "activity: none observed yet";

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

export interface ActivityFeedPaneProps {
  lines: ActivityFeedLine[];
  maxVisible?: number;
  nowMs?: number;
}

export function ActivityFeedPane({
  lines,
  maxVisible = DEFAULT_VISIBLE_LINES,
  nowMs,
}: ActivityFeedPaneProps): React.ReactElement {
  const now = nowMs ?? Date.now();

  if (lines.length === 0) {
    return React.createElement(
      Box,
      { flexDirection: "column" },
      React.createElement(Text, { key: "empty", dimColor: true }, EMPTY_STATE_TEXT),
    );
  }

  const visible = visibleActivityFeedLines(lines, maxVisible);
  return React.createElement(
    Box,
    { flexDirection: "column" },
    ...visible.map((line, i) =>
      React.createElement(
        Text,
        { key: `activity-${i}`, dimColor: true },
        formatActivityFeedLine(line, now),
      ),
    ),
  );
}
