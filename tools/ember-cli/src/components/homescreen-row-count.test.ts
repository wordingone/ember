// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// components/homescreen-row-count.test.ts — binds homescreenRowCount to the real render
// (2026-07-25 palette-overflow-render finding, state/operability-finding-palette-renders-broken).
//
// homescreenRowCount() is a SECOND source of truth for how many rows Homescreen occupies -- it
// mirrors the render arithmetic in its own comment rather than measuring it (this reconciler has
// no layout-measurement hook: no useLayout/onLayout/measureElement in ink/hooks.ts or
// ink/components.ts). Mirrors drift: someone edits Homescreen's structure, the render changes, the
// counter does not, and a caller sizing itself off the counter (the command palette) silently
// over-asks again -- the identical class of failure this whole fix exists to close, reintroduced
// with more code and a false sense of exactness.
//
// So this test does not trust the counter's own arithmetic -- it mounts the REAL Homescreen,
// reconstructs the REAL rendered screen (the same column-aware technique
// screens/palette-overflow-render.test.ts uses, from the reconciler's own absolute
// cursor-position escapes), counts the banner's genuinely occupied rows from that reconstruction,
// and asserts the count EQUALS what homescreenRowCount() returns for the identical props. If a
// future edit changes Homescreen's structure without updating homescreenRowCount to match, this is
// the assertion that fails, loudly, instead of a caller elsewhere silently mis-sizing itself.
//
// Three boardSummary shapes, spanning the case that made a fixed constant unsound in the first
// place (recentFeedEntries appends one line per topAttention entry with no cap): zero attention
// items (the placeholder path), a few, and enough to push the banner well past an ordinary
// terminal's height.

import { describe, it, expect } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { Homescreen, homescreenRowCount, type BoardSummary, type HomescreenProps } from "./logo-homescreen.ts";

/** Same column-aware reconstruction as screens/palette-overflow-render.test.ts: tracks the live
 * cursor via the reconciler's own `\x1b[(\d+);(\d+)H` addressing, places each printable character
 * at its true column, and returns one left-to-right string per row. */
function reconstructRows(out: string): Map<number, string> {
  const grid = new Map<number, Map<number, string>>();
  const TOKEN_RE = /\x1b\[(\d+);(\d+)H|\x1b\[[0-9;]*[A-Za-z]|[^\x1b]+/g;
  let row = 1;
  let col = 1;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(out))) {
    if (m[1] !== undefined && m[2] !== undefined) {
      row = parseInt(m[1], 10);
      col = parseInt(m[2], 10);
    } else if (m[0].startsWith("\x1b")) {
      // non-positioning escape (SGR/color/etc) -- doesn't move the cursor, skip
    } else {
      for (const ch of m[0]) {
        if (ch === "\n") { row++; col = 1; continue; }
        if (!grid.has(row)) grid.set(row, new Map());
        grid.get(row)!.set(col, ch);
        col++;
      }
    }
  }
  const rows = new Map<number, string>();
  for (const [r, cols] of grid) {
    const maxCol = Math.max(...cols.keys());
    let s = "";
    for (let c = 1; c <= maxCol; c++) s += cols.get(c) ?? " ";
    rows.set(r, s);
  }
  return rows;
}

/** Mounts Homescreen standalone (it takes viewportWidth/boardSummary as explicit props, not from
 * TerminalSizeContext, so no provider is needed) with generous stdout dimensions -- large enough
 * that nothing this test renders could ever be clipped by the mount's own stdout size, so the
 * reconstructed row count reflects Homescreen's true content height, never a clip artifact. */
function renderHomescreenRows(props: HomescreenProps): Map<number, string> {
  const chunks: string[] = [];
  const stream = { write(s: string): void { chunks.push(s); } };
  mountInk(React.createElement(Homescreen, props), { stream, stdout: { columns: 100, rows: 200 } });
  return reconstructRows(chunks.join(""));
}

/** Counts genuinely occupied rows: any reconstructed row containing at least one non-whitespace
 * character. Homescreen renders starting at row 1 with no leading blank rows (confirmed by every
 * existing capture in this codebase), so this is the banner's true occupied row count. */
function occupiedRowCount(rows: Map<number, string>): number {
  let count = 0;
  for (const text of rows.values()) {
    if (/\S/.test(text)) count++;
  }
  return count;
}

const BASE_STATE: HomescreenProps["state"] = {
  model:    "qwen3.6-27b",
  cwd:      "test-cwd",
  version:  "0.0.0",
  dataRoot: "test-cwd/data",
};

function boardSummaryWithAttention(count: number): BoardSummary {
  return {
    green: 40,
    total: 50,
    pctComplete: 80,
    topAttention: Array.from({ length: count }, (_, i) => `C(${i}) attention item ${i}`),
  };
}

describe("homescreenRowCount is bound to the real render (2026-07-25 palette-overflow-render finding)", () => {
  it("zero attention items (no boardSummary -- the honest-placeholder path)", () => {
    const props: HomescreenProps = { state: BASE_STATE, viewportWidth: 47, boardSummary: undefined, nowMs: 0 };
    const rows = renderHomescreenRows(props);
    expect(occupiedRowCount(rows)).toBe(homescreenRowCount(props));
  });

  it("a few attention items (ordinary live board state)", () => {
    const props: HomescreenProps = { state: BASE_STATE, viewportWidth: 47, boardSummary: boardSummaryWithAttention(3), nowMs: 0 };
    const rows = renderHomescreenRows(props);
    expect(occupiedRowCount(rows)).toBe(homescreenRowCount(props));
  });

  it("enough attention items to push the banner well past an ordinary terminal height", () => {
    const props: HomescreenProps = { state: BASE_STATE, viewportWidth: 47, boardSummary: boardSummaryWithAttention(20), nowMs: 0 };
    const rows = renderHomescreenRows(props);
    const occupied = occupiedRowCount(rows);
    expect(occupied).toBe(homescreenRowCount(props));
    // Sanity: this shape genuinely IS tall -- otherwise the assertion above would be trivially
    // satisfied by two small numbers agreeing for the wrong reason.
    expect(occupied).toBeGreaterThan(24);
  });
});
