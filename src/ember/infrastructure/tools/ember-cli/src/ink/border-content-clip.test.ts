// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// border-content-clip.test.ts — D1/D2/D3 (legibility scope addition, structural).
//
// D2 root cause: renderNodeToOutput's overflow:"hidden" child-clip-rect intersects with the
// box's FULL OUTER rect (lx, ly, lw, lh) -- the same rect paintBorder uses for the border
// glyphs themselves. Border insetting for CHILD POSITIONING already happens one layer up in
// layout-engine.ts (content-box x/y/width/height subtract border+padding, and reconciler.ts's
// applyBorderProps sets layout.border=1 whenever borderStyle is present -- B2 increment). But an
// unwrapped/overlong Text child is not constrained by its own declared width at paint time, only
// by whatever clipRect it inherits -- so a bordered overflow:"hidden" Box's clip rect must ALSO
// be inset by its own border width, or content that overruns its column budget paints straight
// onto (and past) the border glyphs paintBorder already drew. This is app-wide: every bordered
// overflow:"hidden" Box has this exposure, not just the operator-surface-pane the operator saw
// it on.
//
// D1/D3: border integrity (all four sides, corners, no content in a border column, aligned
// edges) is asserted here via the production frame parser (buildFrame/parseRenderedIntoFrame),
// counting where each border glyph SHOULD sit from the declared width/height and comparing
// against where it actually lands -- never from component source intent.
import { describe, test, expect } from "bun:test";
import React from "react";
import { Box, Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";

function mountAndFrame(el: React.ReactElement, cols: number, rows: number) {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  const frame = buildFrame(cols, rows);
  parseRenderedIntoFrame(buf, frame, new StylePool());
  const lines = frame.cells.map((row) => row.map((c) => c?.char ?? " ").join(""));
  return { raw: buf, frame, lines };
}

describe("D2: bordered overflow:hidden Box reserves its border column from content", () => {
  test("an overlong unwrapped Text child never paints on or past the box's own border glyphs", () => {
    // width=10 -> outer columns 0..9; single border consumes col 0 and col 9, leaving cols 1..8
    // (8 columns) for content. The child text is 30 'X's -- far more than 8 -- specifically to
    // overrun the content budget and expose whether the clip rect actually stops at the border.
    const el = React.createElement(
      Box,
      { width: 10, height: 3, borderStyle: "single", borderColor: "blue", overflow: "hidden" },
      React.createElement(Text, null, "X".repeat(30)),
    );
    const { lines } = mountAndFrame(el, 20, 6);
    // Middle row (row 1 of the 3-row box) is the content row.
    const contentRow = lines[1]!;
    expect(contentRow[0]).toBe("│"); // left border glyph must survive, unclobbered
    expect(contentRow[9]).toBe("│"); // right border glyph must survive, unclobbered
    // No content glyph ('X') may appear at or beyond either border column.
    expect(contentRow[0]).not.toBe("X");
    expect(contentRow[9]).not.toBe("X");
    // And nothing at all past column 9 on this row (outside the box entirely).
    expect(contentRow.slice(10).trim()).toBe("");
  });

  test("same exposure on a taller/wider realistic panel with a long single-line metric row", () => {
    const el = React.createElement(
      Box,
      { width: 24, height: 4, borderStyle: "single", borderColor: "cyan", overflow: "hidden", paddingX: 1 },
      React.createElement(Text, null, "SOURCE UNBOUND EXTRA LONG METRIC LINE THAT OVERRUNS"),
    );
    const { lines } = mountAndFrame(el, 40, 6);
    const contentRow = lines[1]!;
    expect(contentRow[0]).toBe("│");
    expect(contentRow[23]).toBe("│");
    expect(contentRow.slice(24).trim()).toBe("");
  });
});

describe("D1/D3: border integrity — all four sides, corners, alignment, at declared width/height", () => {
  test("a bordered Box under column pressure still closes on all four sides with corners intact", () => {
    // Declared width=12, height=4 -> border SHOULD sit at columns {0,11} and rows {0,3} of the
    // box's own local frame. Computed from the DECLARED geometry, not from what the component
    // intended to draw.
    const el = React.createElement(
      Box,
      { width: 12, height: 4, borderStyle: "single", borderColor: "yellow", overflow: "hidden" },
      React.createElement(Text, null, "content line one that is long enough to overrun the box"),
    );
    const { lines } = mountAndFrame(el, 20, 8);
    expect(lines[0]![0]).toBe("┌"); // top-left corner
    expect(lines[0]![11]).toBe("┐"); // top-right corner
    expect(lines[3]![0]).toBe("└"); // bottom-left corner
    expect(lines[3]![11]).toBe("┘"); // bottom-right corner
    // Bottom border row must be a full horizontal run between the corners -- the box must CLOSE.
    for (let c = 1; c < 11; c++) expect(lines[3]![c]).toBe("─");
    // Side columns aligned across every row -- no ragged edge.
    for (let r = 0; r < 4; r++) {
      expect(lines[r]![0]).not.toBe(" ");
      expect(lines[r]![11]).not.toBe(" ");
    }
  });

  test("a bordered Box nested inside a height-constrained flexShrink wrapper still renders its bottom border", () => {
    // Mirrors repl.ts's Homescreen-wrapping shape: Box{flexShrink:1,minHeight:0,overflow:'hidden'}
    // around a bordered child -- the reported D1 shape (left panel's bottom border missing under
    // height pressure).
    const inner = React.createElement(
      Box,
      { width: 14, height: 5, borderStyle: "round", borderColor: "yellow" },
      React.createElement(Text, null, "row a"),
      React.createElement(Text, null, "row b"),
    );
    const wrapper = React.createElement(
      Box,
      { flexShrink: 1, minHeight: 0, overflow: "hidden" },
      inner,
    );
    // Outer terminal has ample height (12 rows) for a 5-row panel -- any missing bottom border
    // here is caused by the wrapper itself, not by outer-viewport truncation.
    const { lines } = mountAndFrame(wrapper, 20, 12);
    expect(lines[0]![0]).toBe("╭");
    expect(lines[0]![13]).toBe("╮");
    expect(lines[4]![0]).toBe("╰"); // bottom-left corner: the assertion D1 is about
    expect(lines[4]![13]).toBe("╯"); // bottom-right corner
    for (let c = 1; c < 13; c++) expect(lines[4]![c]).toBe("─");
  });
});
