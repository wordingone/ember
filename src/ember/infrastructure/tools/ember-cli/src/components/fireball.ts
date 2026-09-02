// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// fireball.ts — the animated, ever-present cognitive-mode indicator ("the fireball").
// Increment 6 step B (operator regrade 2026-07-03): a signature, on-brand surface, not decoration
// or a deferrable "surface 6" -- state/specs/ember-fireball-cognitive-mode.md +
// specs/surface6-fireball-observatory.md are the source of truth; the approved Step-A visual
// target is state/design-mockups/fireball-cognitive-mode.html (palette + rasters reused verbatim,
// never reinvented). Clean-room: this spec + the listed modules only.
//
// B7 item 1 redesign (operator, same day: "the fire looks like a triangle" -- the prior FRAMES
// were a perfectly symmetric, linearly-tapered (+2 lit cols/row) isoceles blob) shipped a
// disconnected-tongue replacement that fared no better on the next regrade ("definitely not an
// animation... a weird pointy blob, looks nothing like a small flame. disappointed." -- 2026-07-03).
//
// b14 item 3 (2026-07-03): root-cause read on THAT shipped raster -- full width at the base
// narrowing to one point at the top (a cone/pyramid silhouette, not a flame's teardrop: narrow at
// BOTH ends, widest in the lower belly), plus disconnected tongues fragmenting the silhouette in
// one frame. Team-lead gated 4 candidates against the bar "small living flame at a glance" and
// picked candidate B ("Slender Candle-Lick"): narrower/taller, tip+base both pinched, ONE
// contiguous span per row and exactly 3 fixed-silhouette intensity frames. The authored historical
// sources below retain their color ranks, but stabilizeFrameOccupancy projects every frame onto
// frame 0's exact tip/base/centerline footprint before any public raster is returned.
// FIREBALL_IDLE_POSE_FRAME (index 0) is the reduced-motion/frozen pose and also carries
// the pulse's brightness peak (team-lead: "the most balanced silhouette").
//
// Two sizes ship, each with its own call site: "panel" (9x9, Homescreen's identity block,
// logo-homescreen.ts) and "compact" (3x5, repl.ts's bottom chrome strip). Both reuse the SAME
// candidate-B shape language (PANEL_TEMPLATE/COMPACT_TEMPLATE below -- transcribed verbatim from
// state/design-mockups/flame-candidates.readme.txt's Candidate B frames, with the pulse baked in
// as a color-only bump at the belly rows of the centered frame; zero shape/position changes) --
// only the PALETTE KEY assigned to each geometric "rank" varies per cognitive mode (MODE_RAMPS),
// so every mode keeps its own established color identity (idle=banked warm, inference/tool=full
// hot range, training=cool blue/cyan, error=muted/dying) while sharing the one approved shape.
//
// Pixel-art technique: each frame is a grid of palette-keyed cells, packed two pixel-rows per
// terminal row via half-block glyphs (foreground = upper pixel, background = lower pixel) --
// doubles vertical density versus one-cell-per-pixel rendering, while staying BMP-safe (U+2580/
// U+2584 are ordinary codepoints, not surrogate-pair emoji).
//
// Animation is frame-swap, not per-cell relayout: a caller-supplied tick selects among
// FIREBALL_FRAME_COUNT baked raster variants (pure, deterministic) -- cheap, frame-budgeted, and
// testable without a timer. The production caller (screens/repl.ts) reuses its mandatory one-second
// liveness cadence and selects FIREBALL_IDLE_POSE_FRAME under EMBER_REDUCED_MOTION / non-color /
// ascii, per the spec's degradation floor.

import React from "react";
import type { CognitiveMode } from "../cognitive-mode.ts";
import { Box, RawAnsi } from "../ink/components.ts";

// ---------------------------------------------------------------------------
// State derivation
// ---------------------------------------------------------------------------

/** The 5 states from the fireball spec's mapping table -- collapsed from the 8-value
 * CognitiveMode set (cognitive-mode.ts), the same source the status bar's mode indicator reads. */
export type FireballMode = "idle" | "inference" | "tool" | "training" | "error";

/**
 * Pure, total derivation. `trainingActive` (a live training run present, per
 * services/telemetry-watch.ts's ActiveRunState) overrides the cognitive mode outright --
 * TRAINING is "the uncontested mode no competitor even has" (spec) and must never be masked by a
 * concurrent orient/act tick just because the operator also sent a chat turn mid-run.
 *
 * Non-training mapping: observe->idle, act->tool, rollback->error, ask->idle (awaiting a human
 * decision reads as "waiting", the same as observe -- not "working"); orient/verify/consolidate/
 * report all collapse to "inference" (the fireball spec has no separate visual for them, and each
 * is genuinely an active/working phase).
 */
export function deriveFireballMode(mode: CognitiveMode, trainingActive: boolean): FireballMode {
  if (trainingActive) return "training";
  switch (mode) {
    case "observe":
    case "ask":
      return "idle";
    case "act":
      return "tool";
    case "rollback":
      return "error";
    case "orient":
    case "verify":
    case "consolidate":
    case "report":
    default:
      return "inference";
  }
}

// ---------------------------------------------------------------------------
// Palette (verbatim from the approved Step-A mockup -- reused, never reinvented)
// ---------------------------------------------------------------------------

const PALETTE: Record<string, string> = {
  r: "#7a1f0a", R: "#c43410", o: "#d4541c", O: "#ef7d1a",
  y: "#f5b338", Y: "#ffd766", w: "#fff6e0",
  b: "#5b8dff", B: "#9cc4ff", C: "#46c7e0", c: "#7fd6e6",
  g: "#4a4a52", s: "#2f2f37",
};

// ---------------------------------------------------------------------------
// Sizes
// ---------------------------------------------------------------------------

export type FireballSize = "panel" | "compact";

export const FIREBALL_DIMS: Record<FireballSize, { cols: number; rows: number }> = {
  panel:   { cols: 9, rows: 9 },
  compact: { cols: 3, rows: 5 },
};

export const FIREBALL_FRAME_COUNT = 3;
/** Reduced-motion / frozen-tick pose (team-lead, 2026-07-03 approval note on candidate B): the
 * fixed reference silhouette -- tallest, most symmetric, and brightest at the belly --
 * "the most balanced silhouette." */
export const FIREBALL_IDLE_POSE_FRAME = 0;

type RasterRow = string; // COLS chars, each a PALETTE key or " " (unlit)

// ---------------------------------------------------------------------------
// Approved shape templates (verbatim geometry from scratchpad/fireball-mock-gen.mjs's row() calls
// -- same literal placements team-lead rasterized and approved). Encoded here using the same
// 7-key palette rank (r < R < o < O < y < Y < w, dark-ember base -> bright-core tip) so every
// cognitive mode can be derived by recoloring the SAME shape, never by re-deriving positions.
// ---------------------------------------------------------------------------

function row(cols: number, placements: Array<[number, string]>): RasterRow {
  const arr = new Array(cols).fill(" ");
  for (const [col, ch] of placements) arr[col] = ch;
  return arr.join("");
}

const PANEL_TEMPLATE_SOURCE: RasterRow[][] = [
  // frame 0 (FIREBALL_IDLE_POSE_FRAME): canonical fixed occupancy and brightest pulse pose.
  // Belly rows (4,5) are bumped one rank brighter than the other two frames -- the baked-in
  // core-brightness pulse (team-lead's refinement note), positions unchanged from the approved mock.
  [
    row(9, [[4, "w"]]),
    row(9, [[4, "Y"]]),
    row(9, [[3, "y"], [4, "Y"], [5, "y"]]),
    row(9, [[3, "O"], [4, "y"], [5, "O"]]),
    row(9, [[2, "O"], [3, "O"], [4, "y"], [5, "O"], [6, "O"]]),
    row(9, [[2, "R"], [3, "O"], [4, "y"], [5, "O"], [6, "R"]]),
    row(9, [[3, "r"], [4, "R"], [5, "r"]]),
    row(9, [[3, "r"], [4, "R"], [5, "r"]]),
    row(9, [[4, "r"]]),
  ],
  // frame 1 source supplies dim-phase color ranks only; occupancy is normalized to frame 0 below; belly at
  // baseline (unbumped) rank -- the pulse's dim phase.
  //
  // Historical authored positions below supply color ranks only; the exported raster's tip,
  // mass, centerline, base, and bounds are normalized to frame 0 by stabilizeFrameOccupancy.
  [
    row(9, []),
    row(9, [[3, "w"]]),
    row(9, [[3, "Y"]]),
    row(9, [[3, "y"], [4, "Y"], [5, "y"]]),
    row(9, [[3, "O"], [4, "y"], [5, "O"]]),
    row(9, [[2, "o"], [3, "o"], [4, "O"], [5, "o"], [6, "o"]]),
    row(9, [[2, "R"], [3, "o"], [4, "O"], [5, "o"], [6, "R"]]),
    row(9, [[3, "r"], [4, "R"], [5, "r"]]),
    row(9, [[3, "r"]]),
  ],
  // frame 2 source supplies the other dim-phase color ranks only; occupancy is normalized below.
  //
  // Historical authored positions below supply color ranks only; the exported raster's tip,
  // mass, centerline, base, and bounds are normalized to frame 0 by stabilizeFrameOccupancy.
  [
    row(9, [[5, "w"]]),
    row(9, [[5, "Y"]]),
    row(9, [[3, "y"], [4, "Y"], [5, "y"]]),
    row(9, [[3, "O"], [4, "y"], [5, "O"]]),
    row(9, [[2, "o"], [3, "o"], [4, "O"], [5, "o"], [6, "o"]]),
    row(9, [[2, "R"], [3, "o"], [4, "O"], [5, "o"], [6, "R"]]),
    row(9, [[3, "r"], [4, "R"], [5, "r"]]),
    row(9, [[3, "r"], [4, "R"], [5, "r"]]),
    row(9, [[5, "r"]]),
  ],
];

const COMPACT_TEMPLATE_SOURCE: RasterRow[][] = [
  // frame 0 (FIREBALL_IDLE_POSE_FRAME): canonical compact occupancy; pulse-bright belly.
  [row(3, [[1, "Y"]]), row(3, [[0, "O"], [1, "y"], [2, "O"]]), row(3, [[0, "R"], [1, "r"], [2, "R"]])],
  // frame 1 source: baseline belly rank; occupancy is normalized to frame 0 below.
  //
  // Historical authored positions below supply color ranks only; the exported raster's tip,
  // mass, centerline, base, and bounds are normalized to frame 0 by stabilizeFrameOccupancy.
  [row(3, [[0, "Y"]]), row(3, [[0, "O"], [1, "o"], [2, "O"]]), row(3, [[0, "R"], [1, "r"], [2, "R"]])],
  // frame 2 source: alternate baseline rank; occupancy is normalized to frame 0 below.
  //
  // Historical authored positions below supply color ranks only; the exported raster's tip,
  // mass, centerline, base, and bounds are normalized to frame 0 by stabilizeFrameOccupancy.
  [row(3, [[2, "Y"]]), row(3, [[0, "O"], [1, "o"], [2, "O"]]), row(3, [[0, "R"], [1, "r"], [2, "R"]])],
];
const DIM_RANK: Record<string, string> = { w: "Y", Y: "y", y: "O", O: "o", o: "R", R: "r", r: "r" };

/** Preserve one fixed spatial silhouette; animation is a color/intensity pulse only. */
function stabilizeFrameOccupancy(frames: RasterRow[][]): RasterRow[][] {
  const stable = frames[0]!;
  return frames.map((frame, frameIndex) => frameIndex === 0
    ? [...stable]
    : stable.map((stableRow, rowIndex) => [...stableRow].map((cell, columnIndex) => {
        if (cell === " ") return " ";
        const authored = frame[rowIndex]?.[columnIndex];
        return authored && authored !== " " ? authored : (DIM_RANK[cell] ?? cell);
      }).join("")));
}

const PANEL_TEMPLATE = stabilizeFrameOccupancy(PANEL_TEMPLATE_SOURCE);
const COMPACT_TEMPLATE = stabilizeFrameOccupancy(COMPACT_TEMPLATE_SOURCE);

// COMPACT_TEMPLATE ships at 3 pixel-rows per frame (a compressed silhouette of the same shape
// language); pad to FIREBALL_DIMS.compact.rows (5) with blank rows so every frame is a uniform
// grid, matching PANEL_TEMPLATE's contract.
function padRows(frames: RasterRow[][], cols: number, rows: number): RasterRow[][] {
  return frames.map((frame) => {
    const padded = [...frame];
    while (padded.length < rows) padded.push(" ".repeat(cols));
    return padded;
  });
}
const COMPACT_TEMPLATE_PADDED = padRows(COMPACT_TEMPLATE, FIREBALL_DIMS.compact.cols, FIREBALL_DIMS.compact.rows);

// ---------------------------------------------------------------------------
// Per-mode recoloring -- same approved geometry, mode-specific palette ramp by rank.
// Rank order (dark-ember base -> bright-core tip): r < R < o < O < y < Y < w.
// ---------------------------------------------------------------------------

const RANK_OF: Record<string, number> = { r: 0, R: 1, o: 2, O: 3, y: 4, Y: 5, w: 6 };

/** 7-entry ramp, index = rank (0..6), value = the palette key that mode uses at that rank. */
const MODE_RAMPS: Record<FireballMode, string[]> = {
  // idle: banked/low-energy -- never reaches yellow or white-hot, stays warm-dim.
  idle:      ["r", "R", "o", "O", "o", "O", "O"],
  // inference: the full approved range, exactly as mocked (most "alive").
  inference: ["r", "R", "o", "O", "y", "Y", "w"],
  // tool: hot, distinct ordering from inference so the two read as related but not identical.
  tool:      ["r", "R", "O", "o", "Y", "y", "w"],
  // training: cool blue/cyan/white replacing the warm ramp -- same silhouette, training's own identity.
  training:  ["s", "g", "C", "B", "c", "B", "w"],
  // error: muted grey/dark red, never reaches a bright peak -- a dying-out fire.
  error:     ["s", "g", "g", "r", "R", "r", "g"],
};

function recolorRow(rowStr: RasterRow, ramp: string[]): RasterRow {
  let out = "";
  for (const ch of rowStr) {
    if (ch === " ") { out += " "; continue; }
    const rank = RANK_OF[ch];
    out += rank !== undefined ? ramp[rank] : ch;
  }
  return out;
}

function recolorFrames(template: RasterRow[][], ramp: string[]): RasterRow[][] {
  return template.map((frame) => frame.map((r) => recolorRow(r, ramp)));
}

const FRAMES: Record<FireballSize, Record<FireballMode, RasterRow[][]>> = {
  panel: {
    idle:      recolorFrames(PANEL_TEMPLATE, MODE_RAMPS.idle),
    inference: recolorFrames(PANEL_TEMPLATE, MODE_RAMPS.inference),
    tool:      recolorFrames(PANEL_TEMPLATE, MODE_RAMPS.tool),
    training:  recolorFrames(PANEL_TEMPLATE, MODE_RAMPS.training),
    error:     recolorFrames(PANEL_TEMPLATE, MODE_RAMPS.error),
  },
  compact: {
    idle:      recolorFrames(COMPACT_TEMPLATE_PADDED, MODE_RAMPS.idle),
    inference: recolorFrames(COMPACT_TEMPLATE_PADDED, MODE_RAMPS.inference),
    tool:      recolorFrames(COMPACT_TEMPLATE_PADDED, MODE_RAMPS.tool),
    training:  recolorFrames(COMPACT_TEMPLATE_PADDED, MODE_RAMPS.training),
    error:     recolorFrames(COMPACT_TEMPLATE_PADDED, MODE_RAMPS.error),
  },
};

/** Selects the frame for a size+mode+tick. Pure, deterministic; wraps for any integer tick. */
export function fireballRaster(size: FireballSize, mode: FireballMode, tick: number): RasterRow[] {
  const frames = FRAMES[size][mode];
  const n = frames.length;
  const idx = ((tick % n) + n) % n;
  return frames[idx]!;
}

// ---------------------------------------------------------------------------
// ASCII / degraded fallback
// ---------------------------------------------------------------------------

/** Single stable glyph per mode when truecolor pixel art can't render (EMBER_ASCII, NO_COLOR, or
 * reduced-motion) -- graceful degradation floor from the spec, never a partial/broken paint. */
const ASCII_GLYPH: Record<FireballMode, string> = {
  idle: "o",
  inference: "*",
  tool: "*",
  training: "^",
  error: "!",
};

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function hexToAnsiFg(hex: string): string {
  const clean = hex.replace(/^#/, "");
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `\x1b[38;2;${r};${g};${b}m`;
}

function hexToAnsiBg(hex: string): string {
  const clean = hex.replace(/^#/, "");
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `\x1b[48;2;${r};${g};${b}m`;
}

const RESET = "\x1b[0m";
const UPPER_HALF = "▀"; // ▀
const LOWER_HALF = "▄"; // ▄

/** Terminal line count when rendering in truecolor pixel-art mode (2 pixel-rows per line), per size. */
export const FIREBALL_COLOR_LINES: Record<FireballSize, number> = {
  panel:   Math.ceil(FIREBALL_DIMS.panel.rows / 2),
  compact: Math.ceil(FIREBALL_DIMS.compact.rows / 2),
};
/** Terminal line count when rendering the ascii/degraded fallback (always 1, both sizes). */
export const FIREBALL_ASCII_LINES = 1;

/**
 * Renders the fireball as an array of terminal text lines.
 *
 * - `ascii: true` or `color: false` -> the single-glyph fallback (FIREBALL_ASCII_LINES lines).
 * - otherwise -> FIREBALL_COLOR_LINES[size] lines of half-block pixel art.
 *
 * Line COUNT is fixed per size (independent of tick and of which cells happen to be lit), so the
 * fireball never causes layout jitter as it animates.
 */
export function renderFireballLines(
  size: FireballSize,
  mode: FireballMode,
  tick: number,
  opts: { ascii: boolean; color: boolean },
): string[] {
  if (opts.ascii || !opts.color) {
    return [ASCII_GLYPH[mode]];
  }

  const raster = fireballRaster(size, mode, tick);
  const cols = FIREBALL_DIMS[size].cols;
  const lines: string[] = [];
  for (let r = 0; r < raster.length; r += 2) {
    const top = raster[r] ?? " ".repeat(cols);
    const bot = raster[r + 1] ?? " ".repeat(cols);
    let line = "";
    for (let c = 0; c < cols; c++) {
      const tHex = PALETTE[top[c] ?? " "];
      const bHex = PALETTE[bot[c] ?? " "];
      if (!tHex && !bHex) {
        line += " ";
      } else if (tHex && bHex) {
        line += `${hexToAnsiFg(tHex)}${hexToAnsiBg(bHex)}${UPPER_HALF}${RESET}`;
      } else if (tHex) {
        line += `${hexToAnsiFg(tHex)}${UPPER_HALF}${RESET}`;
      } else {
        line += `${hexToAnsiFg(bHex!)}${LOWER_HALF}${RESET}`;
      }
    }
    lines.push(line);
  }
  return lines;
}

// ---------------------------------------------------------------------------
// React component -- pure given props; the caller owns the animation timer
// ---------------------------------------------------------------------------

export interface FireballProps {
  size:  FireballSize;
  mode:  FireballMode;
  tick:  number;
  ascii: boolean;
  color: boolean;
}

/** Fixed-footprint component: always renders the same number of lines for a given size/ascii/color
 * combination, so mounting it never reflows surrounding fixed chrome. */
export function Fireball({ size, mode, tick, ascii, color }: FireballProps): React.ReactElement {
  const lines = renderFireballLines(size, mode, tick, { ascii, color });
  return React.createElement(
    Box,
    { flexDirection: "column" },
    ...lines.map((line, i) =>
      React.createElement(React.Fragment, { key: String(i) }, React.createElement(RawAnsi, null, line)),
    ),
  );
}
