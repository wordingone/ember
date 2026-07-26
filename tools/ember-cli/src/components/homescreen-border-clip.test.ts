// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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

// ---------------------------------------------------------------------------
// Panel height under POPULATED live state (added 2026-07-25, from an independent review of the
// spine-on-first-screen PR).
//
// Every case above mounts `state: {}` with no board summary, no update line and no launch-root
// disclosure. That binds the 20-row budget to one reconstructed frame, which is not the same as
// binding it to the quantity: the disclosure row fires exactly when the operator launches from a
// worktree, the update line fires on any available update, and the recent feed's entries grow with
// live telemetry, condition transitions and the attention list — a list with no upper bound at all.
// Each of those was reachable in ordinary operation against a budget the code itself described as
// having "no slack".
//
// So these cases mount the states the fixture omitted. They pass because the recent feed is now
// budgeted against what the left column actually spends, rather than because the numbers happened
// to line up on the day someone measured them.
describe("panel height is structural, not observed, at 80x20", () => {
  const boardSummary = {
    green: 4, total: 9, pctComplete: 44,
    topAttention: ["C2 attention line", "C4 attention line", "C6 attention line",
                   "C7 attention line", "C8 attention line"],
    boardTs: "2026-07-25T00:00:00Z",
    liveTelemetry: { gpu: { text: "gpu: idle" }, activeRun: { text: "run: none" },
                     lastReceipt: { text: "receipt: 2h" } },
    recentTransitions: [{ text: "board: C(-1) GREEN->RED" }, { text: "board: C(-2) RED->GREEN" }],
  } as never;

  const cases: Array<[string, Record<string, unknown>]> = [
    ["populated board",                 { boardSummary }],
    ["launch-root disclosure",          { state: { dataRoot: "R:/canonical" }, launchDir: "R:/elsewhere" }],
    ["update line",                     { state: { updateAvailable: "9.9.9" } }],
    ["all three at once (worst case)",  { state: { dataRoot: "R:/canonical", updateAvailable: "9.9.9" },
                                          launchDir: "R:/elsewhere", boardSummary }],
  ];

  for (const [name, props] of cases) {
    test(`all four corners paint with ${name}`, () => {
      const out = mountAndCapture(
        React.createElement(Homescreen, {
          state: {}, viewportWidth: 80, viewportHeight: 20, nowMs: 0, ...props,
        }),
        80,
      );
      expect(out).toContain("╭");
      expect(out).toContain("╮");
      expect(out).toContain("╰");
      expect(out).toContain("╯"); // FAILS before the budget fix: panel runs past row 20
    });
  }

  test("content dropped by the budget is reported, never silently absent", () => {
    const out = mountAndCapture(
      React.createElement(Homescreen, {
        state: {}, viewportWidth: 80, viewportHeight: 20, nowMs: 0, boardSummary,
      }),
      80,
    );
    // The overflow line is one row by construction, so the summary of the truncation cannot itself
    // be what overflows the budget.
    expect(out).toMatch(/\+\d+ more/);
  });
});
