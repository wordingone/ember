// homescreen-border-clip.test.ts — B2 regression found via PTY capture (not the isolated
// WelcomeV2-alone unit test, which passed because it never exercised the real parent layout):
// Homescreen's leftCol Box declares width:LEFT_PANEL_MAX_WIDTH (50), but its child WelcomeV2
// declares its OWN width:WELCOME_THRESHOLD (58) -- wider than its parent. In row-flex mode
// (viewportWidth >= LEFT_PANEL_MAX_WIDTH*2 == 100), the parent's declared width clips its
// children's overflow, so WelcomeV2's right border (columns 51-57 locally) never paints. In
// column/stacked mode (viewportWidth < 100) this mismatch is invisible by coincidence. Confirmed
// on the compiled binary (ember-step-b4.exe) via PTY capture at 100x32/125x32: topLeft/bottomLeft
// present, topRight/bottomRight absent.
import { describe, test, expect } from "bun:test";
import React from "react";
import { Homescreen } from "./logo-homescreen.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";

function mountAndCapture(el: React.ReactElement, cols: number, rows = 20): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  return buf;
}

describe("Homescreen's WelcomeV2 border at row-flex widths (>= 100 cols)", () => {
  for (const cols of [100, 125]) {
    test(`all four corners paint at width ${cols} (reproduces the PTY-caught clip)`, () => {
      const out = mountAndCapture(
        React.createElement(Homescreen, { state: {}, viewportWidth: cols }),
        cols,
      );
      expect(out).toContain("╭");
      expect(out).toContain("╰");
      expect(out).toContain("╮"); // FAILS before the fix -- clipped by leftCol's narrower width
      expect(out).toContain("╯"); // FAILS before the fix
    });
  }

  test("width 80 (column/stacked mode) still paints all four corners (regression guard)", () => {
    const out = mountAndCapture(
      React.createElement(Homescreen, { state: {}, viewportWidth: 80 }),
      80,
    );
    expect(out).toContain("╭");
    expect(out).toContain("╮");
    expect(out).toContain("╰");
    expect(out).toContain("╯");
  });
});

// Gate ask (B7 swap review): a pasted 170-col capture showed border rows and content rows
// appearing to end at different columns. `toContain` checks above can't tell -- they only prove
// a glyph exists somewhere. This uses the production frame parser to assert every panel row's
// right-border glyph lands at the SAME absolute column, at the two capture widths the gate uses.
// If this holds, the earlier visual mismatch was a paste-trimming artifact, not a real defect.
describe("right-border column uniformity (production frame parser, not raw string containment)", () => {
  for (const cols of [100, 170]) {
    test(`every panel row's right-edge glyph lands at the same column at width ${cols}`, () => {
      const rows = 50;
      const out = mountAndCapture(
        React.createElement(Homescreen, { state: { version: "0.0.0" }, viewportWidth: cols }),
        cols,
        rows,
      );
      const frame = buildFrame(cols, rows);
      parseRenderedIntoFrame(out, frame, new StylePool());

      const rightEdgeCols: number[] = [];
      for (let r = 0; r < rows; r++) {
        const rowStr = frame.cells[r].map((c) => c?.char ?? " ").join("");
        for (const glyph of ["│", "╮", "╯"]) {
          const idx = rowStr.lastIndexOf(glyph);
          if (idx >= 0) {
            rightEdgeCols.push(idx);
            break;
          }
        }
      }

      expect(rightEdgeCols.length).toBeGreaterThan(0);
      const distinct = new Set(rightEdgeCols);
      expect(distinct.size).toBe(1); // every border row ends at the same column
      expect([...distinct][0]).toBe(cols - 1); // and that column is the true right edge
    });
  }
});
