// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2381 U-spark: the right panel's sparklines drew in Braille, which the Windows console host
// renders as empty boxes. The charts now draw in block characters (U+2581-2588) and "·" for a gap.
import { expect, test } from "bun:test";
import { renderChart, sparklineRow } from "./chart.ts";

const BRAILLE = /[\u2800-\u28ff]/;
const ALLOWED = /^[\u2581-\u2588\u00b7 ]*$/;

const ramp = Array.from({ length: 40 }, (_, i) => i);
const wave = Array.from({ length: 40 }, (_, i) => 50 + 40 * Math.sin(i / 3));
const gaps: Array<number | null> = [1, null, 3, null, null, 9, 2, 8];

test("sparkline rows contain only block glyphs and the gap dot, for ramps, waves and gaps", () => {
  for (const series of [ramp, wave, gaps]) {
    for (const width of [4, 12, 30, 60]) {
      const row = sparklineRow(series, width);
      expect(row).not.toMatch(BRAILLE);
      expect(row).toMatch(ALLOWED);
    }
  }
});

test("multi-row charts draw in block glyphs too, never Braille", () => {
  for (const series of [ramp, wave, gaps]) {
    for (const [width, height] of [[20, 1], [20, 3], [40, 5]] as const) {
      for (const row of renderChart(series, { width, height }).rows) {
        expect(row).not.toMatch(BRAILLE);
        expect(row).toMatch(ALLOWED);
      }
    }
  }
});
