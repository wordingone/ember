// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// components/activity-feed-pane.ts — issue #485 rung 1 / #518: the operator-visible half of the
// activity feed. Renders REAL observed events (receipt landings, outage windows, watchdog
// transitions, board runs) that the services/activity-feed.ts engine has actually rendered —
// never a fabricated/synthetic tick (GOAL.md P-C). Each line carries its artifact path so the
// feed doubles as an audit surface, per L2.
//
// #518 (operator category correction, second receipt): the ActivityFeedPane ticker below used
// to be mounted inside the StatusLine, pinned near the statusline/input box — "literal, activity
// lines with timestamps at the bottom... which is just... stupid." That is a status feed, not
// what an operator recognizes as an agentic session's activity. ActivityTranscriptBlock (bottom
// of this file) is the fix: each event now renders as a card in the conversation SCROLLBACK, at
// its temporal position, in the same visual language as the tool-run/write cards elsewhere in
// the transcript (the "└ " convention from tool-result-renderers.ts) — never a dim ticker row.
// ActivityFeedPane itself is kept only because its pure formatters (truncateMiddle,
// visibleActivityFeedLines, formatActivityFeedLine) are still genuinely useful and pinned by
// existing tests; the component is no longer mounted anywhere in the live app (see
// status-bar.ts / screens/repl.ts, which now route activity events through
// ActivityTranscriptBlock instead).

import React from "react";
import { Box, Text } from "../ink/components.ts";
import { formatReceiptAge } from "../core/receipt-age.ts";

// ---------------------------------------------------------------------------
// Types (owned here — services/activity-feed.ts imports these, mirroring the
// ModelMetrics convention: components/status-bar.ts owns the shape, the
// producing service imports the type).
// ---------------------------------------------------------------------------

export type ActivityFeedSource = "receipt" | "outage" | "watchdog" | "board" | "goal";

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

/** Left-truncates a path with a leading ellipsis marker: "…/tail/of/path" — drops the front and
 *  keeps the tail (the most identifying part of a path: the filename and its nearest parent
 *  directories), consistently everywhere a path renders (legibility bar, 2026-07-26: "paths
 *  truncate from the left with a marker, consistently everywhere" — before this, one path
 *  rendered middle-truncated via truncateMiddle above and another rendered raw and got hard-
 *  clipped by the outer terminal renderer with no marker at all, in the SAME frame). Never grows
 *  the string; a budget of 1 renders just the marker; a budget <= 0 renders "". */
export function truncatePathLeft(value: string, maxLen: number = DEFAULT_PATH_MAX_LEN): string {
  if (maxLen <= 0) return "";
  if (value.length <= maxLen) return value;
  if (maxLen === 1) return "…";
  return `…${value.slice(value.length - (maxLen - 1))}`;
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
  const pathSuffix = line.path ? ` [${truncatePathLeft(line.path, pathMaxLen)}]` : "";
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

// ---------------------------------------------------------------------------
// ActivityTranscriptBlock — #518: the same event, rendered as a transcript
// card instead of a ticker row. This is what screens/repl.ts mounts for a
// `{type: "activity"}` SessionMessage, at the message's position in the
// scrolling history — never in the status bar.
// ---------------------------------------------------------------------------

/** Absolute local time for a transcript block header, matching the exemplar's
 *  scheduled-task-marker style (an absolute anchor, never a relative "Nm ago"
 *  ticker — transcript position already conveys recency). Same-day events
 *  show time only ("9:59pm"); anything from an earlier day is prefixed with
 *  a numeric M/D date ("7/8 9:59pm") to keep the format locale/name-neutral. */
export function formatActivityBlockTimestamp(ts: string, nowMs: number = Date.now()): string {
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  const now = new Date(nowMs);

  let hours = d.getHours();
  const ampm = hours >= 12 ? "pm" : "am";
  hours = hours % 12;
  if (hours === 0) hours = 12;
  const minutes = String(d.getMinutes()).padStart(2, "0");
  const timeStr = `${hours}:${minutes}${ampm}`;

  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) return timeStr;
  return `${d.getMonth() + 1}/${d.getDate()} ${timeStr}`;
}

export interface ActivitySourceDisplay {
  label: string;
  color: string;
}

/** One glyph for every activity block ("✻", the exemplar's own scheduled/background-marker
 *  glyph) — deliberately distinct from BLACK_CIRCLE ("●", message-renderers.ts), which marks
 *  something that happened THIS turn (a tool call, an assistant line). "✻" marks something the
 *  organism did OUTSIDE the turn (a receipt landing, a board run, a watchdog transition) — the
 *  reader tells the two apart by glyph, same as the exemplar's tool cards vs its
 *  "✻ Running scheduled task" marker. Per state/field-ux-map.md §9's field-sourced design rule
 *  ("one consistent glyph vocabulary... never an emoji salad; pair color with an icon for
 *  state"), the SOURCE is carried by color + label text, never by a bespoke per-source glyph. */
export const ACTIVITY_GLYPH = "✻";

/** Per-source class tag (label + color) — the exemplar's "class tag where applicable (model
 *  tier, lane name, run id)" requirement, applied to the activity engine's real event
 *  sources. Glyph is shared (ACTIVITY_GLYPH); only color + label vary by source.
 *  `goal` (ember issue #211 §7 delta 4, "goal receipts feed the board"): a goal-organ
 *  transition or autonomous continuation fire, tailed from receipts/goal-sessions/*.jsonl —
 *  distinct color from the other four so an autonomous goal turn is visually distinguishable
 *  from an ordinary receipt/board/watchdog/outage event at a glance. */
export const ACTIVITY_SOURCE_DISPLAY: Record<ActivityFeedSource, ActivitySourceDisplay> = {
  receipt:  { label: "Receipt landed", color: "green" },
  board:    { label: "Board run",      color: "cyan" },
  watchdog: { label: "Watchdog",       color: "yellow" },
  outage:   { label: "Outage window",  color: "red" },
  goal:     { label: "Goal",           color: "magenta" },
};

export interface ActivityTranscriptBlockProps {
  line: ActivityFeedLine;
  nowMs?: number;
  pathMaxLen?: number;
}

/** One transcript block: a header card ("<glyph> <label> (<time>)"), the event
 *  text on a "└ " row (same convention UserToolSuccessMessage uses for tool
 *  output), and — only when the event carries one — a dim path reference row.
 *  No age ticker, no bracket-source prefix: the card's OWN position in the
 *  scrollback is the time signal, matching how a tool-run or write card reads. */
export function ActivityTranscriptBlock({
  line,
  nowMs,
  pathMaxLen = DEFAULT_PATH_MAX_LEN,
}: ActivityTranscriptBlockProps): React.ReactElement {
  const display = ACTIVITY_SOURCE_DISPLAY[line.source];
  const time = formatActivityBlockTimestamp(line.ts, nowMs ?? Date.now());

  const header = React.createElement(
    Box,
    { key: "header", flexDirection: "row" },
    React.createElement(Text, { key: "glyph", color: display.color }, `${ACTIVITY_GLYPH} `),
    React.createElement(Text, { key: "label", dimColor: true }, `${display.label} (${time})`),
  );

  const body = React.createElement(
    Box,
    { key: "body", flexDirection: "row" },
    React.createElement(Text, { key: "arrow", dimColor: true }, "└ "),
    React.createElement(Text, { key: "text", wrap: "wrap" }, line.text),
  );

  const pathRow = line.path
    ? React.createElement(
        Box,
        { key: "path", flexDirection: "row" },
        React.createElement(Text, { key: "indent", dimColor: true }, "  "),
        React.createElement(
          Text,
          { key: "value", dimColor: true, italic: true },
          truncatePathLeft(line.path, pathMaxLen),
        ),
      )
    : null;

  return React.createElement(
    Box,
    { flexDirection: "column" },
    header,
    body,
    pathRow,
  );
}
