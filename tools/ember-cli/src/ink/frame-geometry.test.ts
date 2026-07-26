// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// frame-geometry.test.ts — pure-unit acceptance rows for R4b (state/specs/ember-cli-chart-height-
// and-frame-geometry.md) that need no real ReplScreen mount. The mount-backed rows (1, 2, 3, and
// the homescreen right-edge regression guard) live one-per-file under
// ink/frame-geometry-repl-*.test.ts -- Windows bun crashes when more than one ReplScreen mount
// runs in a single `bun test` invocation, so every mount-bearing acceptance row is isolated.
// Acceptance-row-to-test map (full map, also carried in the delivery report):
//   row 1 -> frame-geometry-repl-90x40.test.ts
//   row 2 -> frame-geometry-repl-60x30.test.ts + frame-geometry-repl-120x44.test.ts
//   row 3 -> frame-geometry-repl-width-sweep.test.ts
//   row 4 -> this file, "FAILS on a deliberately corrupted frame" (mandatory, not optional)
//   row 5 -> this file, "nested boxes are both checked, neither mistaken for the other"
//   row 6 -> this file, "a frame with no boxes passes rather than throwing"
//   skip-path row -> this file, "a box clipped off-frame is reported clipped, not silently passed"
import { describe, expect, test } from "bun:test";
import { checkFrameGeometry } from "./frame-geometry.ts";

describe("frame geometry — R4b acceptance (pure-unit rows)", () => {
  test("row 4 (NOT OPTIONAL): a deliberately corrupted frame -- content written into a border cell -- FAILS", () => {
    const clean = [
      "╭────╮",
      "│ ab │",
      "╰────╯",
    ];
    // Corrupt the bottom border row: overwrite one of its border cells with a content glyph.
    const corrupted = clean.slice();
    corrupted[2] = "╰─X──╯";
    const cleanResult = checkFrameGeometry(clean);
    expect(cleanResult.violations).toEqual([]);
    const corruptedResult = checkFrameGeometry(corrupted);
    expect(corruptedResult.violations.length).toBeGreaterThan(0);
    expect(corruptedResult.violations.some((v) => v.kind === "content-in-border-row")).toBe(true);
  });

  test("row 5: nested boxes -- inner and outer both discovered and checked independently", () => {
    const frame = [
      "╭──────────╮",
      "│ ╭──────╮ │",
      "│ │ hi   │ │",
      "│ ╰──────╯ │",
      "│          │",
      "╰──────────╯",
    ];
    const result = checkFrameGeometry(frame);
    expect(result.violations).toEqual([]);
    expect(result.boxes.length).toBe(2);
    const outer = result.boxes.find((b) => b.leftCol === 0)!;
    const inner = result.boxes.find((b) => b.leftCol === 2)!;
    expect(outer.clipped).toBe(false);
    expect(inner.clipped).toBe(false);
    expect(outer.topRow).toBe(0);
    expect(outer.bottomRow).toBe(5);
    expect(inner.topRow).toBe(1);
    expect(inner.bottomRow).toBe(3);

    // Corrupt only the INNER box's border and confirm the OUTER box is unaffected (not mistaken
    // for the corrupted one) while a violation is still reported against the inner box.
    const innerCorrupted = frame.slice();
    innerCorrupted[3] = "│ ╰─Y────╯ │";
    const corruptedResult = checkFrameGeometry(innerCorrupted);
    expect(corruptedResult.violations.length).toBeGreaterThan(0);
    const outerAfter = corruptedResult.boxes.find((b) => b.leftCol === 0)!;
    expect(outerAfter.clipped).toBe(false);
    const outerViolation = corruptedResult.violations.some((v) => v.box.leftCol === 0);
    expect(outerViolation).toBe(false);
  });

  test("row 6: a frame with no boxes passes rather than throwing", () => {
    const frame = ["plain text", "no borders here", "   "];
    expect(() => checkFrameGeometry(frame)).not.toThrow();
    const result = checkFrameGeometry(frame);
    expect(result.boxes).toEqual([]);
    expect(result.violations).toEqual([]);
  });

  test("skip-path row: a box clipped off-frame (no matching bottom edge within the frame) is reported clipped, not silently passed", () => {
    const frame = [
      "╭────╮",
      "│ ab │",
      "│ cd │",
      // no bottom edge at all -- the box runs off the bottom of the frame
    ];
    const result = checkFrameGeometry(frame);
    expect(result.boxes.length).toBe(1);
    expect(result.boxes[0]!.clipped).toBe(true);
    // A clipped box contributes no violations of its own (it was only half seen).
    expect(result.violations).toEqual([]);
  });
});
