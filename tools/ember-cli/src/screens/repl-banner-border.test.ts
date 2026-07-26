// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// repl-banner-border.test.ts — D1 (legibility scope addition): "the left orange banner has lost
// its BOTTOM BORDER; the box does not close." Mirrors repl.ts's real main-column composition
// (main-column: height=terminalRows, flexShrink:0 / banner: flexShrink:1, minHeight:0,
// overflow:"hidden" wrapping <Homescreen> / workspace: flexGrow:1, minHeight:0, overflow:"hidden")
// at a terminal height short enough that banner's intrinsic (auto) height plus workspace's own
// minimum content cannot both fit in terminalRows -- the height-squeeze this shape is built to
// resolve by shrinking banner. A synthetic isolated repro of the wrapper alone (border-content-
// clip.test.ts) did NOT reproduce this, so the defect depends on the real sibling-competition
// (banner flexShrink:1 vs workspace flexGrow:1 inside a fixed-height column), not on the wrapper
// in isolation.
import { describe, test, expect } from "bun:test";
import React from "react";
import { Box, Text } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { Homescreen } from "../components/logo-homescreen.ts";
import type { AppState } from "../state/app-state.ts";

function mountAndFrame(el: React.ReactElement, cols: number, rows: number) {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  const frame = buildFrame(cols, rows);
  parseRenderedIntoFrame(buf, frame, new StylePool());
  return frame.cells.map((row) => row.map((c) => c?.char ?? " ").join(""));
}

function minimalState(): AppState {
  return { model: "test-model", updateAvailable: undefined } as unknown as AppState;
}

function replLikeTree(terminalCols: number, terminalRows: number): React.ReactElement {
  const mainColumnWidth = terminalCols;
  return React.createElement(
    Box,
    { key: "main-column", flexDirection: "column", width: mainColumnWidth, minWidth: mainColumnWidth, height: terminalRows, flexShrink: 0, overflow: "hidden" },
    React.createElement(
      Box,
      { key: "banner", flexShrink: 1, minHeight: 0, overflow: "hidden" },
      React.createElement(Homescreen, { state: minimalState(), viewportWidth: mainColumnWidth }),
    ),
    React.createElement(
      Box,
      { key: "workspace", flexDirection: "column", flexGrow: 1, minHeight: 0, overflow: "hidden" },
      // A few lines of standing chrome that always want space -- the real workspace never
      // renders as truly empty (prompt line, status line, etc.).
      React.createElement(Text, { key: "l1" }, "prompt line"),
      React.createElement(Text, { key: "l2" }, "status line"),
      React.createElement(Text, { key: "l3" }, "another chrome row"),
    ),
  );
}

describe("D1: the Homescreen panel's bottom border under real repl.ts height pressure", () => {
  test("at an ample terminal height, the panel's bottom border renders (control)", () => {
    const lines = mountAndFrame(replLikeTree(100, 40), 100, 40);
    const borderRows = lines.filter((l) => l.includes("╰") || l.includes("╯"));
    expect(borderRows.length).toBeGreaterThan(0);
  });

  test("at a height too short for banner's intrinsic size + workspace's minimum, the panel still closes with a bottom border (never a silently missing edge)", () => {
    // Deliberately short: Homescreen's own panel needs several rows (title + identity block +
    // feeds + border top/bottom); 12 total rows leaves very little slack once workspace's 3
    // chrome lines are also demanded.
    const lines = mountAndFrame(replLikeTree(100, 12), 100, 12);
    const hasBottomCorner = lines.some((l) => l.includes("╰") && l.includes("╯"));
    const hasTopCorner = lines.some((l) => l.includes("╭") && l.includes("╮"));
    // If the top renders but the bottom does not, the box never closes -- exactly D1's report.
    if (hasTopCorner) {
      expect(hasBottomCorner).toBe(true);
    }
  });
});
