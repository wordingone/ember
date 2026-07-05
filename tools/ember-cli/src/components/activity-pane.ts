// components/activity-pane.ts — the R0 "SEE ITSELF" live activity panel. Renders the merged
// runs+receipts feed (services/activity-feed.ts) toggled on by /activity, following the same
// thin box-drawing + one-accent-color language as the slash-command dropdown (field-ux-map §8b/§9:
// Crush-style discipline, color always paired with a glyph, never color alone).
//
// Anti-fixture rail lives in the DATA layer (activity-feed.ts / runs-registry.ts /
// receipt-watch.ts), not here -- this component renders exactly the rows it is given and shows
// the honest empty state when given none. It never invents a row of its own.

import React from "react";
import { Box, Text } from "../ink/components.ts";
import { color, glyph, PANEL_BORDER_STYLE } from "./design-system.ts";
import { formatAge } from "../core/watch-render.ts";
import type { ActivityRow } from "../services/activity-feed.ts";

export const ACTIVITY_PANE_TITLE = "LIVE ACTIVITY";
export const ACTIVITY_PANE_EMPTY_TEXT = "no live activity";
export const ACTIVITY_PANE_MAX_ROWS = 10;

/** Kind → glyph, mirrors cognitive-mode.ts's own unicode/ascii pairing discipline. */
function kindGlyph(kind: ActivityRow["kind"]): string {
  if (kind === "run") return glyph("gear");
  return glyph("boardHex");
}

/** "12s ago" / "3m ago" -- reuses the existing observatory age formatter (core/watch-render.ts)
 * so every "how long ago" string in the TUI reads identically. `nowMs` is caller-injected so this
 * stays deterministically testable. */
export function formatRowAge(row: ActivityRow, nowMs: number): string {
  const rowMs = new Date(row.ts).getTime();
  if (Number.isNaN(rowMs)) return "unknown";
  return formatAge(nowMs - rowMs);
}

/** Truncates a long provenance path to fit a fixed budget, ellipsis in the MIDDLE (keeps both the
 * leading directory context and the trailing filename -- the part most useful for recognizing
 * which receipt this is) -- never a raw character-count clip that could hide the filename. */
export function truncatePathMiddle(path: string, maxLen: number): string {
  if (path.length <= maxLen) return path;
  if (maxLen <= 3) return path.slice(0, maxLen);
  const keep = maxLen - 3;
  const headLen = Math.ceil(keep / 2);
  const tailLen = Math.floor(keep / 2);
  return `${path.slice(0, headLen)}...${path.slice(path.length - tailLen)}`;
}

/** One row's display line, independent of color/glyph -- unit-testable without React. A row
 * whose provenance does NOT resolve is marked explicitly (never silently shown as if verified). */
export function formatActivityRowLine(row: ActivityRow, nowMs: number, pathWidth = 40): string {
  const age = formatRowAge(row, nowMs);
  const path = truncatePathMiddle(row.provenancePath, pathWidth);
  const provenanceFlag = row.provenanceResolves ? "" : " [unresolved]";
  return `${row.label} · ${age} · ${path}${provenanceFlag}`;
}

export interface ActivityPaneProps {
  rows: ActivityRow[];
  width: number;
  /** Wall-clock override for tests; defaults to Date.now() at render time. */
  now?: number;
}

export function ActivityPane({ rows, width, now }: ActivityPaneProps): React.ReactElement {
  const nowMs = now ?? Date.now();
  const visible = rows.slice(0, ACTIVITY_PANE_MAX_ROWS);
  const overflow = rows.length - visible.length;
  // Path budget leaves room for the glyph + label + age + separators within the panel width.
  const pathWidth = Math.max(10, width - 30);

  return React.createElement(
    Box,
    {
      flexDirection: "column",
      borderStyle: PANEL_BORDER_STYLE,
      borderColor: color("identity", "fg"),
      paddingX: 1,
    },
    React.createElement(Text, { key: "__title", bold: true, color: color("identity", "fg") }, ACTIVITY_PANE_TITLE),
    visible.length === 0
      ? React.createElement(Text, { key: "__empty", color: color("muted", "fg"), dimColor: true }, ACTIVITY_PANE_EMPTY_TEXT)
      : null,
    ...visible.map((row, i) =>
      React.createElement(
        Box,
        { key: `row-${i}`, flexDirection: "row" },
        React.createElement(Text, { color: color("primary", "fg") }, `${kindGlyph(row.kind)} `),
        React.createElement(
          Text,
          { color: row.provenanceResolves ? undefined : color("warning", "fg") },
          formatActivityRowLine(row, nowMs, pathWidth),
        ),
      ),
    ),
    overflow > 0
      ? React.createElement(Text, { key: "__overflow", color: color("muted", "fg"), dimColor: true }, `+${overflow} more`)
      : null,
  );
}
