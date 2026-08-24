// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import {
  HyperlinkPool,
  Output,
  StylePool,
  buildFrame,
  createFrameParseScratch,
  parseRenderedIntoFrame,
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

describe("issue #898 full-frame allocation cure", () => {
  test("reuses one chunk buffer across changed, unchanged, and wide ANSI frames", () => {
    const stylePool = new StylePool();
    const hyperlinkPool = new HyperlinkPool();
    const output = new Output(stylePool, hyperlinkPool);
    const chunks = (output as unknown as { _chunks: string[] })._chunks;

    expect(Array.isArray(chunks)).toBe(true);

    const frames = [
      ["\x1b[1;1H", "plain", "\x1b[m"],
      [],
      ["\x1b[2;3H", "\x1b[38;2;1;2;3m", "界", "\x1b]8;;https://example.test\x1b\\", " link", "\x1b]8;;\x1b\\", "\x1b[m"],
    ];
    for (const frame of frames) {
      for (const segment of frame) output.write(segment);
      expect(output.flush()).toBe(frame.join(""));
      expect((output as unknown as { _chunks: string[] })._chunks).toBe(chunks);
      expect(chunks).toHaveLength(0);
    }
  });

  test("reuses CSI numeric scratch while preserving changed and wide ANSI cells", () => {
    const stylePool = new StylePool();
    const scratch = createFrameParseScratch();
    const codes = scratch.codes;
    const frame = buildFrame(8, 2);

    parseRenderedIntoFrame("\x1b[1;1H\x1b[31mA\x1b[m", frame, stylePool, scratch);
    expect(frame.cells[0]![0]!.char).toBe("A");
    expect(stylePool.lookup(frame.cells[0]![0]!.styleRef).fg).toEqual({ type: "named", index: 1 });

    parseRenderedIntoFrame("\x1b[2;2H\x1b[1;38;2;4;5;6m界Z\x1b[m", frame, stylePool, scratch);
    expect(frame.cells[1]![1]!.char).toBe("界");
    expect(frame.cells[1]![3]!.char).toBe("Z");
    expect(stylePool.lookup(frame.cells[1]![1]!.styleRef)).toMatchObject({
      bold: true,
      fg: { type: "rgb", r: 4, g: 5, b: 6 },
    });
    expect(scratch.codes).toBe(codes);
  });
});
