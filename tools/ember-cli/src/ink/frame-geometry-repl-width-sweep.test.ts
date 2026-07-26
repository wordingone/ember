// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Acceptance row 3 (R4b): the checker runs clean across the existing width sweep. Reuses the SAME
// sweep and the SAME lightweight standalone-mount pattern as
// screens/repl-width-sweep-border-integrity.test.ts's own D3 sweep (each container mounted in
// isolation at generous width/height so nothing outside its own geometry clips it) -- "the full
// existing width sweep" means the actual set already swept there, not a new arbitrary one. A full
// ReplScreen mounted 7 times in one bun invocation crashes the Windows bun runtime (confirmed);
// mounting the two named containers standalone, as that file already does safely, avoids it.
import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "./reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "./rendering-pipeline.ts";
import { Homescreen } from "../components/logo-homescreen.ts";
import { OperatorSurfacePane } from "../components/operator-surface-pane.ts";
import type { TelemetryState } from "../services/telemetry-watch.ts";
import { checkFrameGeometry } from "./frame-geometry.ts";

function telemetry(overrides: Partial<TelemetryState> = {}): TelemetryState {
  return { recentEvents: [], ...overrides };
}

function mountAndFrame(el: React.ReactElement, cols: number, rows: number): string[] {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  const frame = buildFrame(cols, rows);
  parseRenderedIntoFrame(buf, frame, new StylePool());
  return frame.cells.map((r) => r.map((c) => c?.char ?? " ").join(""));
}

describe("frame geometry — R4b acceptance row 3 (OperatorSurfacePane, existing width sweep)", () => {
  for (const width of [20, 24, 60, 80, 100, 140, 200]) {
    test(`width=${width}: checker runs clean, zero violations`, () => {
      const height = 12;
      const el = React.createElement(OperatorSurfacePane, {
        telemetry: telemetry({
          activeRun: { runId: "run-a", step: 2, loss: 1, stepMs: 500, lastTs: "2026-07-26T11:59:59.000Z" },
        }),
        activityLines: [],
        width, height, terminalColumns: Math.max(width + 20, 220), terminalRows: 60,
      });
      const effectiveWidth = Math.max(20, Math.min(width, 240));
      const effectiveHeight = Math.max(8, Math.min(height, 60));
      const lines = mountAndFrame(el, effectiveWidth + 10, effectiveHeight + 4);
      const result = checkFrameGeometry(lines);
      expect(result.violations).toEqual([]);
    });
  }
});

describe("frame geometry — R4b acceptance row 3 (Homescreen, existing width sweep)", () => {
  for (const viewportWidth of [20, 24, 60, 80, 100, 140, 200]) {
    test(`viewportWidth=${viewportWidth}: checker runs clean, zero violations, box not clipped`, () => {
      const el = React.createElement(Homescreen, {
        state: { model: "ember", cwd: process.cwd(), version: "0.0.0", dataRoot: "" },
        viewportWidth,
      });
      const lines = mountAndFrame(el, Math.max(viewportWidth + 20, 260), 60);
      const result = checkFrameGeometry(lines);
      expect(result.violations).toEqual([]);
      const panel = result.boxes.find((b) => b.styleName === "round");
      expect(panel).toBeDefined();
      expect(panel!.clipped).toBe(false);
    });
  }
});
