// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// fireball.test.ts — cognitive-mode fireball indicator.
// B7 item 1 redesign (operator: "the fire looks like a triangle" -- 2026-07-03 regrade, mocks
// approved both sizes): the old raster was a perfectly symmetric, linearly-tapered isoceles
// shape (+2 lit cols/row, single centered blob). The approved replacement
// (scratchpad/fireball-mock-gen.mjs -> state/design-mockups/fireball-{panel,compact}.mockup.ansi.txt)
// is asymmetric per row, has 1-2 disconnected tongues (a real gap mid-row, not one contiguous
// span), drifts its peak column/height across exactly 4 frames, and ships at TWO sizes: "panel"
// (9x9, for the Homescreen identity block) and "compact" (3x5, for repl.ts's bottom chrome strip).
// Clean-room: tests only against this module's public API + cognitive-mode.ts's real CognitiveMode.

import { describe, test, expect } from "bun:test";
import type { CognitiveMode } from "../cognitive-mode.ts";
import {
  deriveFireballMode,
  fireballRaster,
  renderFireballLines,
  FIREBALL_DIMS,
  FIREBALL_FRAME_COUNT,
  FIREBALL_IDLE_POSE_FRAME,
  type FireballMode,
  type FireballSize,
} from "./fireball.ts";

describe("deriveFireballMode", () => {
  test("trainingActive overrides every cognitive mode -- TRAINING is uncontested", () => {
    const allModes: CognitiveMode[] = [
      "observe", "orient", "act", "verify", "consolidate", "ask", "report", "rollback",
    ];
    for (const m of allModes) {
      expect(deriveFireballMode(m, true)).toBe("training");
    }
  });

  test("maps each cognitive mode to a fireball mode when training is not active", () => {
    const expected: Record<CognitiveMode, FireballMode> = {
      observe:     "idle",
      orient:      "inference",
      act:         "tool",
      verify:      "inference",
      consolidate: "inference",
      ask:         "idle",
      report:      "inference",
      rollback:    "error",
    };
    for (const [mode, want] of Object.entries(expected) as [CognitiveMode, FireballMode][]) {
      expect(deriveFireballMode(mode, false)).toBe(want);
    }
  });
});

const SIZES: FireballSize[] = ["panel", "compact"];
const MODES: FireballMode[] = ["idle", "inference", "tool", "training", "error"];

describe("FIREBALL_DIMS", () => {
  test("panel is 9x9, compact is 3x5 -- the two sizes team-lead reviewed and approved", () => {
    expect(FIREBALL_DIMS.panel).toEqual({ cols: 9, rows: 9 });
    expect(FIREBALL_DIMS.compact).toEqual({ cols: 3, rows: 5 });
  });
});

describe("fireballRaster", () => {
  test("returns a per-size ROWSxCOLS grid for every mode", () => {
    for (const size of SIZES) {
      const { cols, rows } = FIREBALL_DIMS[size];
      for (const m of MODES) {
        const raster = fireballRaster(size, m, 0);
        expect(raster.length).toBe(rows);
        for (const rowStr of raster) expect(rowStr.length).toBe(cols);
      }
    }
  });

  test("ships exactly 3 fixed-silhouette intensity frames per mode", () => {
    expect(FIREBALL_FRAME_COUNT).toBe(3);
    for (const size of SIZES) {
      for (const m of MODES) {
        const seen = new Set<string>();
        for (let t = 0; t < FIREBALL_FRAME_COUNT; t++) {
          seen.add(JSON.stringify(fireballRaster(size, m, t)));
        }
        // not every frame need differ from every other, but the cycle must exist -- at least 2
        // genuinely distinct rasters across the 3-tick cycle (real animation, not a no-op loop).
        expect(seen.size).toBeGreaterThanOrEqual(2);
      }
    }
  });

  test("is deterministic -- same size+mode+tick always returns the same raster", () => {
    expect(fireballRaster("panel", "inference", 3)).toEqual(fireballRaster("panel", "inference", 3));
  });

  test("animation is real -- consecutive ticks change the raster for an active mode", () => {
    const a = fireballRaster("panel", "inference", 0);
    const b = fireballRaster("panel", "inference", 1);
    expect(a).not.toEqual(b);
  });

  test("negative and large ticks wrap without throwing, and wrap consistently mod 3", () => {
    expect(() => fireballRaster("compact", "idle", -7)).not.toThrow();
    expect(() => fireballRaster("compact", "idle", 10_000)).not.toThrow();
    expect(fireballRaster("panel", "idle", 3)).toEqual(fireballRaster("panel", "idle", 0));
    expect(fireballRaster("panel", "idle", -1)).toEqual(fireballRaster("panel", "idle", 2));
  });

  test("FIREBALL_IDLE_POSE_FRAME is a valid, real frame index reserved for the reduced-motion/frozen pose", () => {
    // b14 item 3 (candidate B, 2026-07-03): frame 0 is the centered, tallest, brightest-pulse
    // fixed reference pose -- the natural balanced silhouette.
    expect(FIREBALL_IDLE_POSE_FRAME).toBe(0);
    expect(FIREBALL_IDLE_POSE_FRAME).toBeGreaterThanOrEqual(0);
    expect(FIREBALL_IDLE_POSE_FRAME).toBeLessThan(FIREBALL_FRAME_COUNT);
  });
});

// b14 item 3 (2026-07-03): the original "triangle" shape was rejected, and a follow-up redesign
// that split into disconnected tongues fared no better ("weird pointy blob... looks nothing like a
// small flame"). Team-lead's gate verdict: candidate B ("Slender Candle-Lick") -- narrow at BOTH
// ends, widest in the belly, ONE contiguous span per row and a fixed spatial footprint -- is the only candidate
// that reads as a flame at a glance. These tests assert candidate B's actual properties, replacing
// the earlier (rejected) disconnected-tongue design's tests.
describe("fireballRaster — candidate B teardrop shape (not the old triangle, not disconnected tongues)", () => {
  function litCols(rowStr: string): number[] {
    const cols: number[] = [];
    for (let c = 0; c < rowStr.length; c++) if (rowStr[c] !== " ") cols.push(c);
    return cols;
  }

  test("panel: every lit row is ONE contiguous span (a teardrop silhouette, never disconnected tongues)", () => {
    for (const m of MODES) {
      for (let t = 0; t < FIREBALL_FRAME_COUNT; t++) {
        for (const rowStr of fireballRaster("panel", m, t)) {
          const cols = litCols(rowStr);
          for (let i = 1; i < cols.length; i++) {
            expect(cols[i]! - cols[i - 1]!).toBe(1);
          }
        }
      }
    }
  });

  test("panel: narrow at both the tip (top) and the base (bottom), widest in the belly (a teardrop, not a cone)", () => {
    for (const m of MODES) {
      const raster = fireballRaster("panel", m, FIREBALL_IDLE_POSE_FRAME);
      const widths = raster.map((r) => litCols(r).length);
      const nonZero = widths.filter((w) => w > 0);
      const maxWidth = Math.max(...nonZero);
      const first = nonZero[0]!;
      const last = nonZero[nonZero.length - 1]!;
      expect(first).toBeLessThan(maxWidth);
      expect(last).toBeLessThan(maxWidth);
    }
  });

  // Same scoping rationale: a 3-column canvas has too few rows/widths to distinguish "linear
  // taper" from "not" (compact's own approved geometry is a 1-2-3 width climb over its 3 real
  // rows, which is too short a run to judge a taper pattern against). Panel's 9x9 canvas is where
  // the operator's literal complaint -- "the fire looks like a triangle" (linear +2/row climb) --
  // was made and where the fix must show.
  test("panel: row widths do NOT form the old linear +2/row taper (not a solid isoceles triangle)", () => {
    for (const m of MODES) {
      const raster = fireballRaster("panel", m, 0);
      const widths = raster.map((r) => litCols(r).length).filter((w) => w > 0);
      expect(widths.length).toBeGreaterThanOrEqual(3);
      // A perfectly linear taper has a CONSTANT difference between every consecutive pair.
      const diffs = new Set<number>();
      for (let i = 1; i < widths.length; i++) diffs.add(widths[i]! - widths[i - 1]!);
      expect(diffs.size).toBeGreaterThan(1);
    }
  });

  test("animation changes intensity without moving any lit cell, tip, or base", () => {
    for (const size of SIZES) {
      for (const m of MODES) {
        const masks = new Set<string>();
        for (let t = 0; t < FIREBALL_FRAME_COUNT; t++) {
          const raster = fireballRaster(size, m, t);
          masks.add(raster.map((row) => [...row].map((cell) => cell === " " ? " " : "#").join("")).join("\n"));
        }
        expect(masks.size).toBe(1);
      }
    }
  });

  // Team-lead's refinement on the candidate B gate verdict (2026-07-03): "add a subtle
  // A core-brightness pulse keeps the fixed silhouette alive without translating any lit cell.
  // FIREBALL_IDLE_POSE_FRAME carries the brightness peak; the other two frames are dim phases.
  test("panel/compact: the belly/core is brighter at FIREBALL_IDLE_POSE_FRAME than at the other intensity frames", () => {
    // "inference" mode uses the identity rank ramp (r,R,o,O,y,Y,w unchanged), so counting raw
    // bright-rank characters directly reflects rank, with no per-mode recoloring to account for.
    const BRIGHT = new Set(["y", "Y", "w"]);
    function brightCount(rows: string[]): number {
      let n = 0;
      for (const r of rows) for (const ch of r) if (BRIGHT.has(ch)) n++;
      return n;
    }
    for (const size of SIZES) {
      const bellyRows = size === "panel" ? [4, 5] : [1]; // the widest row(s) per size
      const counts: number[] = [];
      for (let t = 0; t < FIREBALL_FRAME_COUNT; t++) {
        const raster = fireballRaster(size, "inference", t);
        counts.push(brightCount(bellyRows.map((r) => raster[r]!)));
      }
      const idlePoseCount = counts[FIREBALL_IDLE_POSE_FRAME]!;
      for (let t = 0; t < FIREBALL_FRAME_COUNT; t++) {
        if (t === FIREBALL_IDLE_POSE_FRAME) continue;
        expect(idlePoseCount).toBeGreaterThan(counts[t]!);
      }
    }
  });
});

describe("renderFireballLines", () => {
  test("ascii mode returns a single BMP-safe (in fact ASCII-safe) glyph line per mode, per size", () => {
    for (const size of SIZES) {
      for (const m of MODES) {
        const lines = renderFireballLines(size, m, 0, { ascii: true, color: true });
        expect(lines.length).toBeGreaterThan(0);
        const joined = lines.join("");
        for (const ch of joined) {
          expect(ch.codePointAt(0)!).toBeLessThanOrEqual(0x7f);
        }
      }
    }
  });

  test("NO_COLOR (color:false) also degrades to the ascii-safe fallback, never partial color", () => {
    const lines = renderFireballLines("compact", "training", 0, { ascii: false, color: false });
    const joined = lines.join("");
    expect(joined).not.toContain("\x1b[");
  });

  test("truecolor mode emits ANSI escapes for an active (non-idle-blank) raster", () => {
    const lines = renderFireballLines("panel", "training", 0, { ascii: false, color: true });
    expect(lines.some((l) => l.includes("\x1b[38;2;"))).toBe(true);
  });

  test("animation is real end-to-end -- rendered lines differ across ticks in color mode", () => {
    const a = renderFireballLines("panel", "inference", 0, { ascii: false, color: true });
    const b = renderFireballLines("panel", "inference", 1, { ascii: false, color: true });
    expect(a).not.toEqual(b);
  });

  test("fixed footprint per size -- line count never varies across mode or tick (no layout jitter)", () => {
    for (const size of SIZES) {
      const counts = new Set<number>();
      for (const m of MODES) {
        for (const tick of [0, 1, 2, 5]) {
          counts.add(renderFireballLines(size, m, tick, { ascii: false, color: true }).length);
        }
      }
      expect(counts.size).toBe(1);

      const asciiCounts = new Set<number>();
      for (const m of MODES) {
        asciiCounts.add(renderFireballLines(size, m, 0, { ascii: true, color: true }).length);
      }
      expect(asciiCounts.size).toBe(1);
    }
  });

  test("panel renders MORE lines than compact (9 pixel-rows vs 5, at the same half-block packing)", () => {
    const panelLines   = renderFireballLines("panel", "idle", 0, { ascii: false, color: true });
    const compactLines = renderFireballLines("compact", "idle", 0, { ascii: false, color: true });
    expect(panelLines.length).toBeGreaterThan(compactLines.length);
  });
});

// issue #54 (fixed-canvas invariant, part 1 of the frozen fix spec): the RENDERED half-block output
// -- not just the raw RasterRow templates -- must be exactly FIREBALL_DIMS[size].cols columns wide
// after stripping ANSI color codes, on EVERY frame/mode/size. Raw .length (including the embedded
// SGR escape sequences) genuinely varies frame-to-frame -- more lit cells means more escape-code
// bytes -- so this asserts the visible/rendered width specifically, the same measurement
// ink/reconciler.ts's own layout code uses (strip ANSI, then measure), never raw .length on the
// ANSI-laden glyph art. This is the string-canvas half of #54's fix spec; it already holds today
// (confirmed by a diagnostic receipt before this test was written) -- this test locks it so a
// future art edit can't silently reintroduce a rendered-width mismatch.
describe("issue #54: rendered fireball output is a fixed-width canvas (no per-frame width variance)", () => {
  function stripAnsi(s: string): string {
    return s
      .replace(/\x1b\[[^A-Za-z]*[A-Za-z]/g, "")
      .replace(/\x1b\][^]*?(?:\x07|\x1b\\)/g, "")
      .replace(/\x1b./g, "");
  }

  test("every rendered line, every frame/mode/size, has ANSI-stripped width exactly FIREBALL_DIMS.cols", () => {
    for (const size of SIZES) {
      const { cols } = FIREBALL_DIMS[size];
      for (const m of MODES) {
        for (let t = 0; t < FIREBALL_FRAME_COUNT; t++) {
          const lines = renderFireballLines(size, m, t, { ascii: false, color: true });
          for (const line of lines) {
            expect(stripAnsi(line).length).toBe(cols);
          }
        }
      }
    }
  });

  test("raw .length (ANSI included) is NOT a reliable width measurement -- it genuinely varies while the stripped width stays constant (documents why raw .length must never be used for this glyph art)", () => {
    const rawLengths = new Set<number>();
    for (let t = 0; t < FIREBALL_FRAME_COUNT; t++) {
      const lines = renderFireballLines("panel", "inference", t, { ascii: false, color: true });
      for (const line of lines) rawLengths.add(line.length);
    }
    // Not asserting a specific count -- just that raw length is NOT a constant, which is exactly
    // the trap the fix spec warns against ("no raw .length on glyph art").
    expect(rawLengths.size).toBeGreaterThan(1);
  });
});

// issue #54 redundant lower-bound: the wide mass remains fixed too. The stronger test above binds
// the complete occupancy mask, including tip and base; this retains the older extent invariant as
// a focused diagnostic without granting any exception for tip motion.
describe("issue #54: the wide flame mass remains pinned within the stronger fixed-occupancy contract", () => {
  function litCols(rowStr: string): number[] {
    const cols: number[] = [];
    for (let c = 0; c < rowStr.length; c++) if (rowStr[c] !== " ") cols.push(c);
    return cols;
  }

  test("for every size and mode, the union column extent of all width>1 rows is identical across all 3 ticks", () => {
    for (const size of SIZES) {
      for (const m of MODES) {
        const extents: Array<[number, number]> = [];
        for (let t = 0; t < FIREBALL_FRAME_COUNT; t++) {
          const raster = fireballRaster(size, m, t);
          let min = Infinity;
          let max = -Infinity;
          for (const rowStr of raster) {
            const cols = litCols(rowStr);
            if (cols.length > 1) {
              min = Math.min(min, cols[0]!);
              max = Math.max(max, cols[cols.length - 1]!);
            }
          }
          expect(min).not.toBe(Infinity); // every mode/size has at least one width>1 row
          extents.push([min, max]);
        }
        const [first, ...rest] = extents;
        for (const e of rest) expect(e).toEqual(first);
      }
    }
  });
});
