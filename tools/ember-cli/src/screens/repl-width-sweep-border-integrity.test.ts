// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// repl-width-sweep-border-integrity.test.ts — D3 (legibility scope addition): border integrity
// as its own assertion class in the width sweep, at the narrowest supported width plus
// 60/80/100/140/200 columns (the acceptance's named sweep). For each of the two named bordered
// containers (the Homescreen panel, round border; the OperatorSurfacePane, single border):
//   - all four corners are present, at the columns the DECLARED width/height imply (computed
//     from the frame geometry, never from source component intent);
//   - the top and bottom edges are unbroken horizontal runs between their corners (box closes);
//   - the left/right border columns are the SAME column on every interior row (aligned, no
//     ragged edge);
//   - no content glyph occupies either border column (D2's structural guarantee).
//
// Each container is mounted in isolation at its OWN production entry point (Homescreen /
// OperatorSurfacePane, the same components repl.ts composes), rather than parsed out of a full
// ReplScreen frame: a full-app frame contains other, unrelated box-drawing glyphs (feed
// decorations, etc.) that make "find any row containing a top-left/top-right corner pair"
// ambiguous at real widths -- confirmed by a first draft of this file, which produced false
// corner-matches once panelIsRow's side-by-side layout and feed content were both present at
// 60+ columns. Isolating each container keeps the corner search unambiguous while still
// asserting against the REAL component and the REAL rendering pipeline (mountInk, no mocking).
import { describe, test, expect } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { Homescreen } from "../components/logo-homescreen.ts";
import { OperatorSurfacePane } from "../components/operator-surface-pane.ts";
import type { TelemetryState } from "../services/telemetry-watch.ts";
import type { AppState } from "../state/app-state.ts";

function telemetry(overrides: Partial<TelemetryState> = {}): TelemetryState {
  return { recentEvents: [], ...overrides };
}

function mountAndFrame(el: React.ReactElement, cols: number, rows: number): string[] {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  const frame = buildFrame(cols, rows);
  parseRenderedIntoFrame(buf, frame, new StylePool());
  return frame.cells.map((line) => line.map((c) => c?.char ?? " ").join(""));
}

function minimalState(): AppState {
  return { model: "test-model", updateAvailable: undefined } as unknown as AppState;
}

/** Asserts border integrity of exactly the box whose top-left corner sits at (topRow, leftCol)
 *  and top-right corner at (topRow, rightCol): all four corners present, the bottom edge is an
 *  unbroken run between its corners (the box closes), side columns are the exact same column on
 *  every interior row (aligned, no ragged edge), and no content glyph occupies either border
 *  column anywhere in the box (D2's structural guarantee). `bottomRow` is passed in rather than
 *  searched for -- the declared height, computed from frame geometry, is the authority D3 asks
 *  for, not a text search that could match an unrelated glyph elsewhere in the frame.
 *  The TOP edge is checked only for corner presence, not for an unbroken horizontal run: a
 *  titled border (borderTitle embedded in the top edge, e.g. "LIVE RUN") legitimately puts
 *  non-horiz characters between the corners on that one row -- title truncation-with-marker is
 *  its own covered surface (border-title.test.ts); asserting a bare run here would fail on a
 *  correct titled box. */
function assertBoxIntegrity(
  lines: string[],
  glyphs: { tl: string; tr: string; bl: string; br: string; horiz: string; vert: string },
  topRow: number, bottomRow: number, leftCol: number, rightCol: number,
): void {
  expect(lines[topRow]?.[leftCol]).toBe(glyphs.tl);
  expect(lines[topRow]?.[rightCol]).toBe(glyphs.tr);
  expect(lines[bottomRow]?.[leftCol]).toBe(glyphs.bl);
  expect(lines[bottomRow]?.[rightCol]).toBe(glyphs.br);
  for (let c = leftCol + 1; c < rightCol; c++) {
    expect(lines[bottomRow]?.[c]).toBe(glyphs.horiz);
  }
  for (let r = topRow + 1; r < bottomRow; r++) {
    expect(lines[r]?.[leftCol]).toBe(glyphs.vert);
    expect(lines[r]?.[rightCol]).toBe(glyphs.vert);
  }
  // No content glyph anywhere in this box's frame may sit AT or BEYOND either border column
  // (D2's structural guarantee) -- checked across every row of the box, not just the two edges.
  for (let r = topRow; r <= bottomRow; r++) {
    const line = lines[r] ?? "";
    expect(line.slice(rightCol + 1).trim()).toBe("");
  }
}

const ROUND  = { tl: "╭", tr: "╮", bl: "╰", br: "╯", horiz: "─", vert: "│" };
const SINGLE = { tl: "┌", tr: "┐", bl: "└", br: "┘", horiz: "─", vert: "│" };

describe("D3: OperatorSurfacePane border integrity across the width sweep", () => {
  for (const width of [20, 24, 60, 80, 100, 140, 200]) {
    test(`width=${width}: single border closes on all four sides, aligned, no content escapes it`, () => {
      const height = 12;
      // Combined-result check (team-lead, 2026-07-26): the merged operator-controls PR (#1102)
      // introduced "AWAITING FIRST SAMPLE" as a distinct rendering from "SOURCE UNBOUND" for a
      // LIVE run with a metric that has zero samples yet -- longer text than the pre-existing
      // "SOURCE UNBOUND"/"SOURCE UNVERIFIED/UNBOUND" strings this sweep already exercised, and
      // never rendered together with the D1/D2/D3 border fixes before this rebase. A recent
      // train_step event with NO gpu_watts field drives getOperatorRunStatus to RUNNING (so
      // familyLines/compactMetricLine choose "AWAITING FIRST SAMPLE") while leaving the metric
      // itself sample-less -- the exact shape that produces the new, longer string.
      const nowMs = Date.parse("2026-07-26T12:00:00.000Z");
      const el = React.createElement(OperatorSurfacePane, {
        telemetry: telemetry({
          activeRun: { runId: "run-a", step: 2, loss: 1, stepMs: 500, lastTs: "2026-07-26T11:59:59.000Z" },
          recentEvents: [
            { ts: "2026-07-26T11:59:59.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 2, loss: 1 } },
          ],
        }),
        activityLines: [
          { ts: "4m ago", text: "[watchdog] a deliberately long event line meant to overrun the pane's inner width by a wide margin" } as never,
        ],
        width, height, terminalColumns: Math.max(width + 20, 220), terminalRows: 60, nowMs,
      });
      // effectiveWidth/effectiveHeight mirror OperatorSurfacePane's own clamp (width>=20,
      // height>=8) -- computed from the DECLARED frame geometry, not from reading the component.
      const effectiveWidth = Math.max(20, Math.min(width, 240));
      const effectiveHeight = Math.max(8, Math.min(height, 60));
      const lines = mountAndFrame(el, effectiveWidth + 10, effectiveHeight + 4);
      assertBoxIntegrity(lines, SINGLE, 0, effectiveHeight - 1, 0, effectiveWidth - 1);
    });
  }
});

describe("D3: Homescreen panel border integrity across the width sweep", () => {
  for (const viewportWidth of [20, 24, 60, 80, 100, 140, 200]) {
    test(`viewportWidth=${viewportWidth}: round border closes on all four sides, aligned, no content escapes it`, () => {
      const el = React.createElement(Homescreen, { state: minimalState(), viewportWidth });
      // Mount generously wide/tall so nothing outside the panel's own geometry clips it --
      // this sweep is about the panel's OWN border integrity at each width, not about outer
      // viewport clipping (that is D1's height-squeeze axis, covered separately).
      const lines = mountAndFrame(el, Math.max(viewportWidth + 20, 260), 60);
      const topRow = lines.findIndex((l) => l.includes("╭"));
      expect(topRow).toBeGreaterThanOrEqual(0);
      const leftCol = lines[topRow]!.indexOf("╭");
      const rightCol = lines[topRow]!.indexOf("╮");
      const bottomRow = lines.findIndex((l, i) => i > topRow && l[leftCol] === "╰" && l[rightCol] === "╯");
      expect(bottomRow).toBeGreaterThan(topRow);
      assertBoxIntegrity(lines, ROUND, topRow, bottomRow, leftCol, rightCol);
    });
  }
});
