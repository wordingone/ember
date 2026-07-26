// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ink/frame-geometry.ts — structural frame-geometry checker (R4b, frozen spec:
// state/specs/ember-cli-chart-height-and-frame-geometry.md). Discovers every bordered box in a
// rendered frame from ITS OWN corner glyphs -- no component names, no assumed coordinates, no
// caller-supplied box list -- then asserts: every border row is corner-closed at both ends,
// every border column holds only border glyphs, and no content glyph appears in any border row
// or column. A checker that must be told where the boxes are cannot find a defect in a box
// nobody thought to name, which is exactly how the homescreen bottom-border defect survived R4
// (state/operator-pass-2026-07-26.md, W2): R4's own assertions were pointed at two named entry
// points, not at every box on the screen.

type CornerRole = "topLeft" | "topRight" | "bottomLeft" | "bottomRight";

interface StyleGlyphs {
  name: string;
  topLeft: string;
  topRight: string;
  bottomLeft: string;
  bottomRight: string;
  horizontal: string;
  vertical: string;
}

// Mirrors ink/border-glyphs.ts's BORDER_SETS literally, kept INDEPENDENT of resolveBorderGlyphs
// (which is EMBER_ASCII-env-gated and collapses every style to the same set when that flag is
// on): this checker must recognize whichever glyphs actually appear in a frame handed to it,
// regardless of the CURRENT process's ascii-mode state, since that frame may have been produced
// under either mode.
const STYLES: readonly StyleGlyphs[] = [
  { name: "single", topLeft: "┌", topRight: "┐", bottomLeft: "└", bottomRight: "┘", horizontal: "─", vertical: "│" },
  { name: "double", topLeft: "╔", topRight: "╗", bottomLeft: "╚", bottomRight: "╝", horizontal: "═", vertical: "║" },
  { name: "round", topLeft: "╭", topRight: "╮", bottomLeft: "╰", bottomRight: "╯", horizontal: "─", vertical: "│" },
  { name: "bold", topLeft: "┏", topRight: "┓", bottomLeft: "┗", bottomRight: "┛", horizontal: "━", vertical: "┃" },
  { name: "singleDouble", topLeft: "╓", topRight: "╖", bottomLeft: "╙", bottomRight: "╜", horizontal: "─", vertical: "║" },
  { name: "doubleSingle", topLeft: "╒", topRight: "╕", bottomLeft: "╘", bottomRight: "╛", horizontal: "═", vertical: "│" },
  { name: "classic", topLeft: "+", topRight: "+", bottomLeft: "+", bottomRight: "+", horizontal: "-", vertical: "|" },
];

interface CornerMatch {
  style: StyleGlyphs;
  role: CornerRole;
}

function buildCornerIndex(): Map<string, CornerMatch[]> {
  const index = new Map<string, CornerMatch[]>();
  for (const style of STYLES) {
    for (const role of ["topLeft", "topRight", "bottomLeft", "bottomRight"] as const) {
      const glyph = style[role];
      const list = index.get(glyph) ?? [];
      list.push({ style, role });
      index.set(glyph, list);
    }
  }
  return index;
}

const CORNER_INDEX = buildCornerIndex();

// A style whose four corner glyphs are not all distinct cannot be read positionally: `classic`
// uses "+" for all four, so every "+" in a frame indexes as a candidate top-left and each of a
// box's other three corners is re-read as the top-left of a box that does not exist. On a clean
// 3-line classic box that produced FOUR boxes -- one real, three spurious and `clipped` -- with
// violations empty, which made any count-or-all-unclipped authority unusable in EMBER_ASCII and
// contradicted this file's stated mode-independence (found by review at 2c7b8fa, not by a test:
// the suite had no classic case at all).
const AMBIGUOUS_CORNERS = new Set(
  STYLES.filter((s) => new Set([s.topLeft, s.topRight, s.bottomLeft, s.bottomRight]).size < 4).map((s) => s.name),
);

/**
 * For an ambiguous-corner style only, a candidate top-left must additionally carry the style's
 * horizontal glyph immediately to its right and its vertical glyph immediately below. That is
 * false for the other three roles by construction (a top-right has the horizontal on its LEFT, a
 * bottom-left the vertical ABOVE, a bottom-right both behind it), so the role confusion dies.
 *
 * Deliberately NOT applied to distinct-corner styles, and the reason is the tempting wrong fix:
 * applied universally it would turn a genuinely clipped Unicode box at a frame edge from
 * "reported clipped" into "never seen", destroying the exact signal `clipped` exists to carry.
 * It reads only the two immediate neighbours for the same reason -- a real classic box whose
 * top-right runs off-frame still enters discovery and is still reported clipped.
 */
function isStructuralTopLeft(grid: string[][], row: number, col: number, style: StyleGlyphs): boolean {
  if (!AMBIGUOUS_CORNERS.has(style.name)) return true;
  if ((grid[row]?.[col + 1] ?? "") !== style.horizontal) return false;
  if ((grid[row + 1]?.[col] ?? "") !== style.vertical) return false;
  return true;
}

export interface FrameBox {
  topRow: number;
  bottomRow: number;
  leftCol: number;
  rightCol: number;
  styleName: string;
  /** True when a required edge/corner never resolved within the frame -- the box runs off-frame
   *  and was only half seen (skip-path: reported here, never silently dropped or force-failed). */
  clipped: boolean;
}

export type FrameGeometryViolationKind =
  | "row-not-corner-closed"
  | "border-column-impure"
  | "content-in-border-row";

export interface FrameGeometryViolation {
  box: FrameBox;
  kind: FrameGeometryViolationKind;
  row?: number;
  col?: number;
  detail: string;
}

export interface FrameGeometryResult {
  boxes: FrameBox[];
  violations: FrameGeometryViolation[];
}

/**
 * Finds every top-left corner in the grid and, for each, tries to close a box: the matching
 * top-right on the SAME row (same style, scanning right), the matching bottom-left in the SAME
 * column (same style, scanning down), then the matching bottom-right on that bottom row. Nested
 * boxes are handled for free -- each box's own four corners are discovered independently of any
 * other box's. A required edge that never resolves marks the box `clipped` instead of being
 * silently skipped or force-failed as a normal violation.
 */
function discoverBoxes(grid: string[][]): FrameBox[] {
  const boxes: FrameBox[] = [];
  const height = grid.length;
  for (let row = 0; row < height; row += 1) {
    const line = grid[row]!;
    for (let col = 0; col < line.length; col += 1) {
      const matches = CORNER_INDEX.get(line[col]!);
      if (!matches) continue;
      for (const { style, role } of matches) {
        if (role !== "topLeft") continue;
        if (!isStructuralTopLeft(grid, row, col, style)) continue;
        let rightCol = -1;
        for (let c = col + 1; c < line.length; c += 1) {
          if (line[c] === style.topRight) {
            rightCol = c;
            break;
          }
        }
        if (rightCol < 0) {
          boxes.push({ topRow: row, bottomRow: row, leftCol: col, rightCol: line.length - 1, styleName: style.name, clipped: true });
          continue;
        }
        let bottomRow = -1;
        for (let r = row + 1; r < height; r += 1) {
          if ((grid[r]?.[col] ?? "") === style.bottomLeft) {
            bottomRow = r;
            break;
          }
        }
        if (bottomRow < 0) {
          boxes.push({ topRow: row, bottomRow: height - 1, leftCol: col, rightCol, styleName: style.name, clipped: true });
          continue;
        }
        const bottomLine = grid[bottomRow]!;
        const hasBottomRight = (bottomLine[rightCol] ?? "") === style.bottomRight;
        boxes.push({ topRow: row, bottomRow, leftCol: col, rightCol, styleName: style.name, clipped: !hasBottomRight });
      }
    }
  }
  return boxes;
}

function styleFor(name: string): StyleGlyphs {
  return STYLES.find((candidate) => candidate.name === name)!;
}

/**
 * Checks every discovered box against the frozen invariant: every border row is corner-closed at
 * both ends, every border column holds only border glyphs, and no content glyph appears in any
 * border row or column.
 *
 * The TOP row is exempted from full purity (not from corner-closure) for exactly one reason: a
 * Box's own `borderTitle` legitimately embeds non-border text between its corners, and this
 * codebase never titles a bottom border -- the same exemption the pre-existing
 * repl-width-sweep-border-integrity.test.ts already documents for its own (component-named)
 * checks. Corner closure still applies to the top row; full purity still applies to the bottom
 * row and both side columns, which is exactly where the homescreen content-in-border-row defect
 * lives (state/operator-pass-2026-07-26.md, W2).
 */
export function checkFrameGeometry(rows: readonly string[]): FrameGeometryResult {
  const grid = rows.map((line) => [...line]);
  const boxes = discoverBoxes(grid);
  const violations: FrameGeometryViolation[] = [];
  for (const box of boxes) {
    if (box.clipped) continue; // skip-path: reported as clipped, not checked further
    const style = styleFor(box.styleName);
    const topLine = grid[box.topRow]!;
    const bottomLine = grid[box.bottomRow]!;
    if (topLine[box.leftCol] !== style.topLeft || topLine[box.rightCol] !== style.topRight) {
      violations.push({ box, kind: "row-not-corner-closed", row: box.topRow, detail: "top row is not corner-closed at both ends" });
    }
    if (bottomLine[box.leftCol] !== style.bottomLeft || bottomLine[box.rightCol] !== style.bottomRight) {
      violations.push({ box, kind: "row-not-corner-closed", row: box.bottomRow, detail: "bottom row is not corner-closed at both ends" });
    }
    for (let c = box.leftCol + 1; c < box.rightCol; c += 1) {
      const cell = bottomLine[c] ?? "";
      if (cell !== style.horizontal) {
        violations.push({ box, kind: "content-in-border-row", row: box.bottomRow, col: c, detail: `bottom border row holds a non-border glyph ${JSON.stringify(cell)}` });
      }
    }
    for (let r = box.topRow + 1; r < box.bottomRow; r += 1) {
      const line = grid[r] ?? [];
      const left = line[box.leftCol] ?? "";
      const right = line[box.rightCol] ?? "";
      if (left !== style.vertical) {
        violations.push({ box, kind: "border-column-impure", row: r, col: box.leftCol, detail: `left border column holds a non-border glyph ${JSON.stringify(left)}` });
      }
      if (right !== style.vertical) {
        violations.push({ box, kind: "border-column-impure", row: r, col: box.rightCol, detail: `right border column holds a non-border glyph ${JSON.stringify(right)}` });
      }
    }
  }
  return { boxes, violations };
}
