// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ink/braille-canvas.ts — a reusable dot-plotting primitive over the Unicode Braille Patterns
// block (U+2800-U+28FF), giving 2x horizontal and 4x vertical resolution over plain cell-level
// plotting: a WxH-cell area addresses a (2W)x(4H) dot grid, one Braille character per cell.
//
// TECHNIQUE PORTED FROM ratatui (https://github.com/ratatui/ratatui, MIT licensed) — specifically
// its `PatternGrid<W, H>` (ratatui-widgets/src/canvas.rs) as instantiated for Braille
// (`Marker::Braille` -> `PatternGrid<2, 4>`): a per-cell 8-bit pattern stored row-major (bit index
// = col + W*row, so for 2x4: `pattern |= 1 << ((x % 2) + 2 * (y % 4))`), one bit per dot, ORed
// into the owning cell on paint. This is the technique being ported, not the code: ratatui's own
// `char_table` is a 256-entry precomputed lookup array; this module instead derives the same
// mapping algorithmically from the published Unicode dot-numbering below, so nothing here is a
// transcription of ratatui's source.
//
// Unicode Braille codepoint = 0x2800 + (bitmask using the historic embossed-braille dot order):
//   dot1 dot4        bit0 bit3
//   dot2 dot5    =    bit1 bit4
//   dot3 dot6        bit2 bit5
//   dot7 dot8        bit6 bit7
// Note the irregularity Unicode preserved from paper braille: the first three rows are strictly
// column-major (left column = dots 1-3 = bits 0-2, right column = dots 4-6 = bits 3-5), but the
// fourth row breaks that pattern (dot7/8 = bits 6/7, not "dots 7,8" continuing the column-major
// count that would have made them bits 6 and... still 6/7, coincidentally the same here, but the
// row itself is NOT part of either 3-tall column run). rowMajorBitToUnicodeBit below encodes
// exactly this, verified against every one of the 8 single-dot codepoints in
// braille-canvas.test.ts.
//
// A cell whose pattern is 0 (nothing painted) renders as a plain space, not the invisible-but-
// printable U+2800 "blank braille" glyph — several terminal/font combinations render U+2800 with
// a faint dotted outline, which would read as "something is here" when nothing was ever painted.

const CELL_DOT_WIDTH = 2;
const CELL_DOT_HEIGHT = 4;

/** Maps a row-major bit index (col + 2*row, 0-7) to its Unicode Braille dot-order bit index. */
function rowMajorBitToUnicodeBit(rowMajorBit: number): number {
  const row = Math.floor(rowMajorBit / CELL_DOT_WIDTH);
  const col = rowMajorBit % CELL_DOT_WIDTH;
  return row < 3 ? row + 3 * col : 6 + col;
}

/** Precomputed once: rowMajorPattern (0-255) -> the Braille character for that pattern. */
const PATTERN_TO_CHAR: string[] = Array.from({ length: 256 }, (_, pattern) => {
  if (pattern === 0) return " ";
  let unicodeBits = 0;
  for (let bit = 0; bit < 8; bit++) {
    if (pattern & (1 << bit)) unicodeBits |= 1 << rowMajorBitToUnicodeBit(bit);
  }
  return String.fromCodePoint(0x2800 + unicodeBits);
});

export interface BrailleCanvas {
  /** Width/height of the addressable area, in terminal cells. */
  readonly cellWidth: number;
  readonly cellHeight: number;
  /** Width/height of the addressable area, in dots (cellWidth*2, cellHeight*4). */
  readonly dotWidth: number;
  readonly dotHeight: number;
  /** Sets one dot at a zero-based dot coordinate. Out-of-bounds is a silent no-op (fail-open —
   *  a caller with an off-by-one in a resample loop degrades to a missing pixel, never a crash). */
  paint(x: number, y: number): void;
  /** Clears every painted dot back to blank, keeping the same resolution. */
  reset(): void;
  /** Renders the current dot state to `cellHeight` strings of `cellWidth` characters each. */
  render(): string[];
  /** Returns a NEW canvas at a different cell resolution. Never carries dots over — a resize is
   *  a fresh surface, because a dot grid resampled from a stale resolution is not the same data
   *  as the underlying series re-plotted at the new width (the series-to-dots resample is the
   *  chart layer's job, not this primitive's). */
  resize(cellWidth: number, cellHeight: number): BrailleCanvas;
}

export function createBrailleCanvas(cellWidth: number, cellHeight: number): BrailleCanvas {
  const width = Math.max(0, Math.floor(cellWidth));
  const height = Math.max(0, Math.floor(cellHeight));
  const dotWidth = width * CELL_DOT_WIDTH;
  const dotHeight = height * CELL_DOT_HEIGHT;
  let cells = new Uint8Array(width * height);

  return {
    cellWidth: width,
    cellHeight: height,
    dotWidth,
    dotHeight,
    paint(x: number, y: number): void {
      if (x < 0 || y < 0 || x >= dotWidth || y >= dotHeight) return;
      const cellX = Math.floor(x / CELL_DOT_WIDTH);
      const cellY = Math.floor(y / CELL_DOT_HEIGHT);
      const index = cellY * width + cellX;
      const rowMajorBit = (x % CELL_DOT_WIDTH) + CELL_DOT_WIDTH * (y % CELL_DOT_HEIGHT);
      cells[index] = (cells[index] ?? 0) | (1 << rowMajorBit);
    },
    reset(): void {
      cells = new Uint8Array(width * height);
    },
    render(): string[] {
      const lines: string[] = [];
      for (let row = 0; row < height; row++) {
        let line = "";
        for (let col = 0; col < width; col++) {
          line += PATTERN_TO_CHAR[cells[row * width + col] ?? 0];
        }
        lines.push(line);
      }
      return lines;
    },
    resize(nextCellWidth: number, nextCellHeight: number): BrailleCanvas {
      return createBrailleCanvas(nextCellWidth, nextCellHeight);
    },
  };
}
