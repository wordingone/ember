// rawansi-diff-repaint.test.ts — probe for a suspected rendering-pipeline gap found while
// verifying the fireball's live-binary animation (increment 6 step B, operator regrade
// 2026-07-03). PTY capture on the compiled binary showed the fireball's rendered rows IDENTICAL
// across ~1.4s / ~10 animation ticks, despite fireball.test.ts proving renderFireballLines(...)
// itself changes cell-for-cell across ticks (pure logic is fine). This test isolates the ONE
// remaining suspect: does the diff-based repaint pipeline (diffFrames/parseRenderedIntoFrame)
// actually detect a change when a RawAnsi node's TEXT stays identical but its embedded truecolor
// escape codes differ (the fireball's idle-mode frame0 vs frame1: same lit cell, different hue)?

import { describe, test, expect } from "bun:test";
import {
  buildFrame,
  parseRenderedIntoFrame,
  diffFrames,
  StylePool,
} from "./rendering-pipeline.ts";
import { renderFireballLines } from "../components/fireball.ts";

describe("StylePool.intern -- root cause isolation", () => {
  // StylePool._key() is private; interned Style objects with different truecolor RGB values
  // must produce DIFFERENT StyleRef handles, or every downstream consumer (diffFrames, the
  // optimizer) is blind to color-only changes at the same screen position.
  test("two different truecolor fg RGB values intern to DIFFERENT StyleRefs", () => {
    const pool = new StylePool();
    const refA = pool.intern({ fg: { type: "rgb", r: 212, g: 84, b: 28 } });
    const refB = pool.intern({ fg: { type: "rgb", r: 239, g: 125, b: 26 } });
    expect(refA).not.toBe(refB);
  });

  test("two different indexed fg values intern to DIFFERENT StyleRefs", () => {
    const pool = new StylePool();
    const refA = pool.intern({ fg: { type: "indexed", index: 3 } });
    const refB = pool.intern({ fg: { type: "indexed", index: 9 } });
    expect(refA).not.toBe(refB);
  });

  test("the SAME truecolor fg RGB value interns to the SAME StyleRef (no ref-churn)", () => {
    const pool = new StylePool();
    const refA = pool.intern({ fg: { type: "rgb", r: 212, g: 84, b: 28 } });
    const refB = pool.intern({ fg: { type: "rgb", r: 212, g: 84, b: 28 } });
    expect(refA).toBe(refB);
  });
});

function frameFromRawAnsiLines(lines: string[], width: number, height: number, pool: StylePool) {
  // Mirrors renderNodeToOutput's raw-ansi branch: one cursorPosition(row+1, 1) + the raw string,
  // per line, exactly as Fireball's Box{column} of RawAnsi children would emit.
  let rendered = "";
  lines.forEach((line, i) => {
    rendered += `\x1b[${i + 1};1H`;
    rendered += line;
  });
  const frame = buildFrame(width, height);
  parseRenderedIntoFrame(rendered, frame, pool);
  return frame;
}

describe("RawAnsi content and the diff-based repaint pipeline", () => {
  test("two DIFFERENT-text raw-ansi frames are detected as changed (sanity control)", () => {
    const pool = new StylePool();
    const f1 = frameFromRawAnsiLines(["\x1b[31mX\x1b[0m"], 10, 4, pool);
    const f2 = frameFromRawAnsiLines(["\x1b[31mY\x1b[0m"], 10, 4, pool);
    const patch = diffFrames(f1, f2);
    expect(patch.changes.length).toBeGreaterThan(0);
  });

  test("same character, different truecolor fg -- diffFrames must still see a change", () => {
    const pool = new StylePool();
    const f1 = frameFromRawAnsiLines(["\x1b[38;2;212;84;28m▄\x1b[0m"], 10, 4, pool);
    const f2 = frameFromRawAnsiLines(["\x1b[38;2;239;125;26m▄\x1b[0m"], 10, 4, pool);
    const patch = diffFrames(f1, f2);
    expect(patch.changes.length).toBeGreaterThan(0);
  });

  test("the fireball's real idle frame0 vs frame1 (from fireball.ts) -- diffFrames must see the change", () => {
    const pool = new StylePool();
    const lines0 = renderFireballLines("compact", "idle", 0, { ascii: false, color: true });
    const lines1 = renderFireballLines("compact", "idle", 1, { ascii: false, color: true });
    // Confirms the two frames are NOT byte-identical strings (precondition for this test to mean
    // anything) -- fireball.test.ts already proves this at the pure-function level.
    expect(lines0).not.toEqual(lines1);

    const f1 = frameFromRawAnsiLines(lines0, 10, 4, pool);
    const f2 = frameFromRawAnsiLines(lines1, 10, 4, pool);
    const patch = diffFrames(f1, f2);
    expect(patch.changes.length).toBeGreaterThan(0);
  });
});
