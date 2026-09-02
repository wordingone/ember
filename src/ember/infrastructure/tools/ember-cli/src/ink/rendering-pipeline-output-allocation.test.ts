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
  prepareFrame,
  renderNodeToFrame,
  renderNodeToOutput,
  serializePatchRuns,
  type FrameCell,
  type RenderNode,
} from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import { createLayoutNode } from "./layout-engine.ts";

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

describe("issue #898 direct-to-frame cure", () => {
  test("matches the legacy ANSI oracle for composed clipped, styled, wide, and raw-ANSI trees", () => {
    const layout = (left: number, top: number, width: number, height: number) => {
      const node = createLayoutNode();
      node.computedLeft = left;
      node.computedTop = top;
      node.computedWidth = width;
      node.computedHeight = height;
      return node;
    };
    const text = (
      value: string,
      left: number,
      top: number,
      style: RenderNode["style"] = {},
    ): RenderNode => ({
      kind: "text",
      children: [],
      layout: layout(left, top, 12, 2),
      text: value,
      renderedText: value,
      style,
    });
    const roots: RenderNode[] = [
      {
        kind: "root",
        children: [
          text("plain界Z", 0, 0),
          text("RGB", 2, 1, { bold: true, fg: { type: "rgb", r: 4, g: 5, b: 6 } }),
          { kind: "raw-ansi", children: [], layout: layout(1, 2, 10, 1), rawAnsi: "\x1b[33mA\x1b]8;;https://example.test\x1b\\B\x1b]8;;\x1b\\\x1b[m" },
        ],
        layout: layout(0, 0, 16, 4),
      },
      {
        kind: "box",
        children: [text("clip-me-across-the-border", 1, 1, { inverse: true })],
        layout: layout(0, 0, 10, 4),
        borderStyle: "round",
        borderColor: "cyan",
        borderTitle: "wide界title",
        overflow: "hidden",
      },
      {
        kind: "root",
        children: [
          text("界Q", 2, 1, { fg: { type: "named", index: 1 } }),
          text("x", 2, 1, { underline: true }),
        ],
        layout: layout(0, 0, 16, 4),
      },
      {
        kind: "root",
        children: [
          { kind: "raw-ansi", children: [], layout: layout(0, 0, 2, 1), rawAnsi: "\x1b[4;35mR" },
          text("P", 2, 0),
        ],
        layout: layout(0, 0, 16, 4),
      },
      { kind: "root", children: [], layout: layout(0, 0, 16, 4) },
    ];

    let legacyFrame = buildFrame(16, 4);
    let directFrame = buildFrame(16, 4);
    const legacyScratch = createFrameParseScratch();
    const directScratch = createFrameParseScratch();
    for (const [rootIndex, root] of roots.entries()) {
      const legacyStyles = new StylePool();
      const legacyLinks = new HyperlinkPool();
      const output = new Output(legacyStyles, legacyLinks);
      renderNodeToOutput(root, output, 0, 0, { x: 0, y: 0, width: 16, height: 4 }, legacyStyles, legacyLinks);
      const rendered = output.flush();
      legacyFrame = prepareFrame(legacyFrame, 16, 4);
      parseRenderedIntoFrame(rendered, legacyFrame, legacyStyles, legacyScratch);

      const directStyles = new StylePool();
      directFrame = prepareFrame(directFrame, 16, 4);
      const measuredBytes = renderNodeToFrame(
        root,
        directFrame,
        0,
        0,
        { x: 0, y: 0, width: 16, height: 4 },
        directStyles,
        directScratch,
      );

      expect(measuredBytes).toBe(Buffer.byteLength(rendered));
      for (let row = 0; row < legacyFrame.height; row += 1) {
        for (let col = 0; col < legacyFrame.width; col += 1) {
          const legacyCell = legacyFrame.cells[row]![col]!;
          const directCell = directFrame.cells[row]![col]!;
          expect({ rootIndex, row, col, char: directCell.char, width: directCell.width, style: directStyles.lookup(directCell.styleRef), hyperlinkId: directCell.hyperlinkId }).toEqual({
            rootIndex,
            row,
            col,
            char: legacyCell.char,
            width: legacyCell.width,
            style: legacyStyles.lookup(legacyCell.styleRef),
            hyperlinkId: legacyCell.hyperlinkId,
          });
        }
      }
    }
  });
});
