// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import {
  HyperlinkPool,
  Output,
  StylePool,
  serializePatchRuns,
  type FrameCell,
} from "./rendering-pipeline.ts";

interface RunFixture {
  row: number;
  startCol: number;
  cells: FrameCell[];
}

function legacyPerCellSerialization(
  runs: RunFixture[],
  stylePool: StylePool,
  hyperlinkPool: HyperlinkPool,
  geometryChanged: boolean,
): string {
  let buf = geometryChanged ? "\x1b[2J\x1b[H" : "";
  let prevStyleRef = 0;
  for (const run of runs) {
    buf += `\x1b[${run.row + 1};${run.startCol + 1}H`;
    for (const cell of run.cells) {
      const tmp = new Output(stylePool, hyperlinkPool);
      tmp.writeSGR(stylePool.lookup(cell.styleRef), stylePool.lookup(prevStyleRef));
      buf += tmp.flush();
      buf += cell.char;
      prevStyleRef = cell.styleRef;
    }
  }
  if (runs.length > 0) buf += "\x1b[m";
  return buf;
}

describe("issue #898 patch serialization allocation candidate", () => {
  test("fixed-N output stays byte-identical to the per-cell Output implementation", () => {
    const stylePool = new StylePool();
    const hyperlinkPool = new HyperlinkPool();
    const plain = stylePool.intern({});
    const red = stylePool.intern({ fg: { type: "indexed", index: 1 } });
    const inverse = stylePool.intern({ inverse: true });
    const refs = [plain, red, inverse, plain, red];
    const cells: FrameCell[] = Array.from({ length: 4096 }, (_, i) => ({
      char: String.fromCharCode(33 + (i % 90)),
      width: 1,
      styleRef: refs[i % refs.length]!,
      hyperlinkId: null,
    }));
    const runs: RunFixture[] = [
      { row: 0, startCol: 0, cells: cells.slice(0, 2048) },
      { row: 7, startCol: 3, cells: cells.slice(2048) },
    ];

    expect(serializePatchRuns(runs, stylePool, hyperlinkPool, true)).toBe(
      legacyPerCellSerialization(runs, stylePool, hyperlinkPool, true),
    );
  });

  test("an empty patch preserves the prior no-output behavior", () => {
    expect(serializePatchRuns([], new StylePool(), new HyperlinkPool(), false)).toBe("");
  });
});
