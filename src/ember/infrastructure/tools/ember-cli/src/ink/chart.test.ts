// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { renderChart, resampleMinMax, sparklineRow } from "./chart.ts";

const GAP = "·";

function paintedColumns(rows: string[]): Set<number> {
  const painted = new Set<number>();
  for (const row of rows) {
    for (let x = 0; x < row.length; x++) {
      if (row[x] !== " ") painted.add(x);
    }
  }
  return painted;
}

describe("chart widget", () => {
  // Acceptance row 3: 600 samples into an 80-dot plot — full history, spike survives.
  test("row 3: min/max resample keeps a single-sample spike visible at 600->80 compression", () => {
    const samples: Array<number | null> = Array.from({ length: 600 }, () => 1);
    samples[300] = 100; // one-tick spike mid-history
    const area = { width: 40, height: 4 }; // 80 dots wide
    const result = renderChart(samples, area);
    expect(result.yMax).toBe(100); // spike participated in autoscale -> it was retained
    // The spike's bucket paints near the TOP dot row; a flat-only render would have nothing
    // in the top half. Assert some glyph in the top canvas row around the spike's column.
    const topRow = result.rows[0]!;
    expect(topRow.trim().length).toBeGreaterThan(0);
    // Full history: both the first and last buckets carry paint (no tail truncation).
    const buckets = resampleMinMax(samples, 80);
    expect(buckets[0]).not.toBeNull();
    expect(buckets[79]).not.toBeNull();
    expect(buckets.some((bucket) => bucket !== null && bucket.max === 100)).toBe(true);
  });

  // Acceptance row 4: constant series — flat line, no divide-by-zero, no NaN glyph.
  test("row 4: constant series renders a flat mid-height line with no NaN", () => {
    const result = renderChart(Array.from({ length: 50 }, () => 7), { width: 20, height: 4 });
    expect(result.rows).toHaveLength(4);
    const joined = result.rows.join("");
    expect(joined).not.toContain("NaN");
    expect(joined.trim().length).toBeGreaterThan(0); // the line is present
    // Flat line sits mid-height: top and bottom rows stay empty.
    expect(result.rows[0]!.trim()).toBe("");
    expect(result.rows[3]!.trim()).toBe("");
    expect(result.yMin).not.toBe(result.yMax); // zero-range floor widened the band
  });

  // Skip-path S1: zero/negative area renders nothing rather than throwing.
  test("S1: zero and negative areas render nothing and never throw", () => {
    for (const area of [{ width: 0, height: 4 }, { width: 10, height: 0 }, { width: -3, height: -1 }]) {
      const result = renderChart([1, 2, 3], area);
      expect(result.rows).toEqual([]);
    }
    expect(sparklineRow([1, 2], 0)).toBe("");
  });

  // Skip-path S2: sample count below plot width — direct path still respects bounds.
  test("S2: fewer samples than dots maps directly and stays inside the area", () => {
    const result = renderChart([1, 5, 3], { width: 30, height: 3 });
    expect(result.rows).toHaveLength(3);
    for (const row of result.rows) expect(row.length).toBe(30);
    // Direct path is left-aligned: painted columns stay within the first ceil(3/2) cells.
    const painted = paintedColumns(result.rows);
    for (const x of painted) expect(x).toBeLessThan(2);
  });

  // Conjunction C3: zero samples AND a resize — no crash, no stale dimensions.
  test("C3: empty series renders empty at one size and again after a resize", () => {
    const first = renderChart([], { width: 20, height: 4 });
    expect(first.rows).toHaveLength(4);
    for (const row of first.rows) expect(row).toBe(" ".repeat(20));
    const resized = renderChart([], { width: 7, height: 2 });
    expect(resized.rows).toHaveLength(2);
    for (const row of resized.rows) expect(row).toBe(" ".repeat(7)); // new dims, nothing stale
  });

  // Conjunction C4: a null sample does not participate in the range computation.
  test("C4: null is a gap and is excluded from autoscale", () => {
    const result = renderChart([10, null, 12], { width: 3, height: 2 });
    expect(result.yMin).toBe(10);
    expect(result.yMax).toBe(12); // null neither dragged the range to 0 nor NaN'd it
    const spark = sparklineRow([10, null, 12], 3);
    expect(spark[1]).toBe(GAP); // the null column is a gap glyph, not a zero-level bar
  });

  // Acceptance row 6: zero is a reading, distinct from unavailable.
  test("row 6: a literal 0 plots as the value 0, not as a gap", () => {
    const spark = sparklineRow([0, null, 0], 3);
    expect(spark[0]).not.toBe(GAP);
    expect(spark[1]).toBe(GAP);
    expect(spark[2]).not.toBe(GAP);
  });

  // Degrade rather than vanish: height 1 renders a single-row sparkline.
  test("degrade: height 1 renders a sparkline row, never an empty result", () => {
    const result = renderChart([1, 9, 2, 8], { width: 4, height: 1 });
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0]!.length).toBe(4);
    expect(result.rows[0]!).not.toBe(" ".repeat(4));
  });

  // Strict interior clipping: every row is exactly the given width; out-of-range values clamp.
  test("clipping: extreme values clamp to the interior area", () => {
    const result = renderChart([1e9, -1e9, 5], { width: 10, height: 3 }, { yMin: 0, yMax: 10 });
    expect(result.rows).toHaveLength(3);
    for (const row of result.rows) expect(row.length).toBe(10);
  });
});
