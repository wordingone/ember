// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import { buildFrame, prepareFrame } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";

describe("renderer frame-buffer reuse", () => {
  test("clears and reuses a same-geometry frame without allocating new cells", () => {
    const frame = buildFrame(3, 2);
    const firstCell = frame.cells[0]![0]!;
    firstCell.char = "X";
    firstCell.width = 2;
    firstCell.styleRef = 7;
    firstCell.hyperlinkId = 11;

    const prepared = prepareFrame(frame, 3, 2);

    expect(prepared).toBe(frame);
    expect(prepared.cells[0]![0]).toBe(firstCell);
    for (const row of prepared.cells) {
      for (const cell of row) {
        expect(cell).toEqual({ char: " ", width: 1, styleRef: 0, hyperlinkId: null });
      }
    }
  });

  test("allocates a correctly sized frame when geometry changes", () => {
    const old = buildFrame(3, 2);
    const prepared = prepareFrame(old, 4, 1);

    expect(prepared).not.toBe(old);
    expect(prepared.width).toBe(4);
    expect(prepared.height).toBe(1);
    expect(prepared.cells).toHaveLength(1);
    expect(prepared.cells[0]).toHaveLength(4);
  });
});
