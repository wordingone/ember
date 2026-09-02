// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ink/chart.ts — pure chart widget over the Braille canvas primitive (braille-canvas.ts).
// No I/O, no React, no timers: series in, rendered rows out. The panel layer owns labels,
// borders, and the bound/unbound decision; this module only turns numbers into glyph rows.
//
// Contract (each clause is an acceptance row in the chart/host-telemetry spec):
// - RESAMPLE, NEVER TRUNCATE: a series longer than the dot width is bucketed, and each bucket
//   contributes BOTH its min and its max dot — a single-sample spike survives compression. A
//   mean-only downsample hides exactly the event the operator is watching for.
// - AUTOSCALE WITH A FLOOR: a constant series renders as a flat line at mid-height rather than
//   dividing by the zero range (no NaN glyph, no crash).
// - STRICT INTERIOR CLIPPING: the widget is handed an interior area and never paints outside
//   it. A zero or negative area renders nothing (empty array) rather than throwing.
// - DEGRADE RATHER THAN VANISH: at height 1 the chart renders as a single-row sparkline; the
//   curve is always present in some form.
// - NULL IS A GAP, NOT A ZERO: a null sample paints nothing at that x and is excluded from the
//   autoscale range computation. Zero is a reading and plots as the value 0.

import { createBrailleCanvas } from "./braille-canvas.ts";

export interface ChartArea {
  /** Interior width/height in terminal cells. Zero or negative renders nothing. */
  width: number;
  height: number;
}

export interface ChartOptions {
  /** Fixed y-bounds; omitted axes autoscale over the non-null samples. */
  yMin?: number;
  yMax?: number;
}

export interface ChartRender {
  /** Exactly `area.height` rows of exactly `area.width` cells (or [] for a degenerate area). */
  rows: string[];
  /** The y-range actually used (after autoscale + zero-range floor); null when nothing plotted. */
  yMin: number | null;
  yMax: number | null;
}

const SPARK_GLYPHS = "▁▂▃▄▅▆▇█";
const GAP_GLYPH = "·";

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** One bucket's surviving extremes. Nulls contribute nothing; an all-null bucket is a gap. */
interface Bucket {
  min: number;
  max: number;
}

/**
 * Min/max-per-bucket resample of `samples` into exactly `buckets` slots. Every sample lands in
 * exactly one bucket (proportional index), so the WHOLE history is represented — never a tail
 * truncation. When the series is shorter than the bucket count, samples map directly
 * (skip-path S2: the direct path still respects bounds because bucket index is clamped).
 */
export function resampleMinMax(samples: ReadonlyArray<number | null>, buckets: number): Array<Bucket | null> {
  const count = Math.floor(buckets);
  if (count <= 0 || samples.length === 0) return [];
  const out: Array<Bucket | null> = new Array(count).fill(null);
  if (samples.length <= count) {
    // Direct path: sample i -> bucket i (left-aligned; remaining buckets stay gaps).
    for (let i = 0; i < samples.length; i++) {
      const value = samples[i];
      if (!finite(value)) continue;
      const slot = Math.min(count - 1, i);
      out[slot] = { min: value, max: value };
    }
    return out;
  }
  for (let i = 0; i < samples.length; i++) {
    const value = samples[i];
    if (!finite(value)) continue;
    const slot = Math.min(count - 1, Math.floor((i / samples.length) * count));
    const existing = out[slot];
    out[slot] = existing
      ? { min: Math.min(existing.min, value), max: Math.max(existing.max, value) }
      : { min: value, max: value };
  }
  return out;
}

/** Autoscale over non-null buckets with a zero-range floor (a flat series gets a synthetic
 *  half-unit band each side so it plots mid-height instead of dividing by zero). */
function scaleRange(buckets: Array<Bucket | null>, options: ChartOptions): { min: number; max: number } | null {
  let min = finite(options.yMin) ? options.yMin : Number.POSITIVE_INFINITY;
  let max = finite(options.yMax) ? options.yMax : Number.NEGATIVE_INFINITY;
  if (!finite(options.yMin) || !finite(options.yMax)) {
    for (const bucket of buckets) {
      if (!bucket) continue;
      if (!finite(options.yMin)) min = Math.min(min, bucket.min);
      if (!finite(options.yMax)) max = Math.max(max, bucket.max);
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
  if (max - min === 0) {
    // Zero-range floor: widen symmetrically so the flat line sits at mid-height.
    const pad = Math.abs(min) > 0 ? Math.abs(min) * 0.5 : 0.5;
    return { min: min - pad, max: max + pad };
  }
  return { min, max };
}

/** Single-row sparkline degradation: one glyph per column, min/max-resampled, gaps for null. */
export function sparklineRow(samples: ReadonlyArray<number | null>, width: number, options: ChartOptions = {}): string {
  const columns = Math.floor(width);
  if (columns <= 0) return "";
  const buckets = resampleMinMax(samples, columns);
  const range = scaleRange(buckets, options);
  let row = "";
  for (let x = 0; x < columns; x++) {
    const bucket = buckets[x];
    if (!bucket || !range) {
      row += GAP_GLYPH;
      continue;
    }
    // Plot each bucket's MAX so a spike survives even at one row tall.
    const level = Math.max(0, Math.min(7, Math.floor(((bucket.max - range.min) / (range.max - range.min)) * 7.999)));
    row += SPARK_GLYPHS[level];
  }
  return row;
}

/**
 * Renders `samples` into a Braille chart of exactly `area.height` rows x `area.width` cells.
 * - area.width <= 0 or area.height <= 0: returns rows: [] (skip-path S1 — nothing, no throw).
 * - area.height === 1: single-row sparkline (degrade rather than vanish).
 * - Otherwise: Braille dots, min..max painted per bucket column so spikes survive.
 */
export function renderChart(samples: ReadonlyArray<number | null>, area: ChartArea, options: ChartOptions = {}): ChartRender {
  const width = Math.floor(area.width);
  const height = Math.floor(area.height);
  if (width <= 0 || height <= 0) return { rows: [], yMin: null, yMax: null };
  if (height === 1) {
    const buckets = resampleMinMax(samples, width);
    const range = scaleRange(buckets, options);
    return { rows: [sparklineRow(samples, width, options)], yMin: range?.min ?? null, yMax: range?.max ?? null };
  }
  const canvas = createBrailleCanvas(width, height);
  const buckets = resampleMinMax(samples, canvas.dotWidth);
  const range = scaleRange(buckets, options);
  if (range) {
    const span = range.max - range.min;
    const toDotY = (value: number): number => {
      const clamped = Math.max(range.min, Math.min(range.max, value));
      // y grows downward; highest value paints on dot row 0.
      return Math.max(0, Math.min(canvas.dotHeight - 1, Math.round((1 - (clamped - range.min) / span) * (canvas.dotHeight - 1))));
    };
    for (let x = 0; x < canvas.dotWidth; x++) {
      const bucket = buckets[x];
      if (!bucket) continue; // null sample -> gap, never a zero
      const yMax = toDotY(bucket.max);
      const yMin = toDotY(bucket.min);
      // Paint the full min..max span of the bucket so the compressed extreme is visible as a bar.
      for (let y = Math.min(yMax, yMin); y <= Math.max(yMax, yMin); y++) canvas.paint(x, y);
    }
  }
  return { rows: canvas.render(), yMin: range?.min ?? null, yMax: range?.max ?? null };
}
