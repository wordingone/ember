// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ink/braille-canvas.test.ts — RED-first for the Braille sub-cell plotting primitive.
// See braille-canvas.ts for the technique attribution and derivation of the bit mapping.
import { describe, expect, test } from "bun:test";
import { createBrailleCanvas } from "./braille-canvas.ts";

describe("createBrailleCanvas", () => {
  test("resolution is 2x horizontal, 4x vertical dots per terminal cell", () => {
    const canvas = createBrailleCanvas(4, 2);
    expect(canvas.cellWidth).toBe(4);
    expect(canvas.cellHeight).toBe(2);
    expect(canvas.dotWidth).toBe(8);
    expect(canvas.dotHeight).toBe(8);
  });

  test("an untouched canvas renders as blank spaces, not the invisible U+2800 glyph", () => {
    const canvas = createBrailleCanvas(3, 1);
    expect(canvas.render()).toEqual(["   "]);
  });

  test("painting exactly one dot at the cell origin renders dot-1 alone (U+2801)", () => {
    const canvas = createBrailleCanvas(1, 1);
    canvas.paint(0, 0);
    expect(canvas.render()).toEqual(["⠁"]);
  });

  test("painting all 8 dot positions in one cell renders the full cell (U+28FF)", () => {
    const canvas = createBrailleCanvas(1, 1);
    for (let y = 0; y < 4; y++) for (let x = 0; x < 2; x++) canvas.paint(x, y);
    expect(canvas.render()).toEqual(["⣿"]);
  });

  // Cross-checks against the actual published Unicode Braille Patterns block (U+2800-U+28FF),
  // not against ratatui's own precomputed lookup table (this module derives the mapping from
  // the Unicode dot-numbering directly -- see braille-canvas.ts).
  test("each of the 8 dot positions maps to its documented Unicode codepoint in isolation", () => {
    const expected: Array<{ x: number; y: number; codepoint: number }> = [
      { x: 0, y: 0, codepoint: 0x2801 }, // dot 1
      { x: 0, y: 1, codepoint: 0x2802 }, // dot 2
      { x: 0, y: 2, codepoint: 0x2804 }, // dot 3
      { x: 1, y: 0, codepoint: 0x2808 }, // dot 4
      { x: 1, y: 1, codepoint: 0x2810 }, // dot 5
      { x: 1, y: 2, codepoint: 0x2820 }, // dot 6
      { x: 0, y: 3, codepoint: 0x2840 }, // dot 7
      { x: 1, y: 3, codepoint: 0x2880 }, // dot 8
    ];
    for (const { x, y, codepoint } of expected) {
      const canvas = createBrailleCanvas(1, 1);
      canvas.paint(x, y);
      expect(canvas.render()).toEqual([String.fromCodePoint(codepoint)]);
    }
  });

  test("a dot coordinate maps to the correct cell across a multi-cell canvas", () => {
    const canvas = createBrailleCanvas(2, 1);
    canvas.paint(2, 0); // first dot column of the SECOND cell (dotWidth=4, cell boundary at x=2)
    expect(canvas.render()).toEqual([" ⠁"]);
  });

  test("painting out of bounds is a fail-open no-op, never throws", () => {
    const canvas = createBrailleCanvas(2, 2);
    expect(() => canvas.paint(-1, 0)).not.toThrow();
    expect(() => canvas.paint(0, -1)).not.toThrow();
    expect(() => canvas.paint(999, 0)).not.toThrow();
    expect(() => canvas.paint(0, 999)).not.toThrow();
    expect(canvas.render()).toEqual(["  ", "  "]);
  });

  test("reset clears every painted dot back to blank", () => {
    const canvas = createBrailleCanvas(1, 1);
    canvas.paint(0, 0);
    canvas.paint(1, 3);
    canvas.reset();
    expect(canvas.render()).toEqual([" "]);
  });

  test("resize creates a fresh canvas at the new resolution without retaining stale dots", () => {
    const canvas = createBrailleCanvas(1, 1);
    canvas.paint(0, 0);
    const resized = canvas.resize(2, 1);
    expect(resized.dotWidth).toBe(4);
    expect(resized.dotHeight).toBe(4);
    expect(resized.render()).toEqual(["  "]);
  });
});
