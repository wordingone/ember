// rendering-pipeline — terminal renderer core: object pools, screen buffer,
// double-buffered diff, optimizer, and render entry point.
// Cross-layer deps (event-system) are injected as optional interfaces.

import type { Style, ColorValue } from "./termio.ts";
import { cursorPosition, applyAnsiCodes } from "./termio.ts";
import type { LayoutNode } from "./layout-engine.ts";
import { resolveBorderGlyphs, type BorderStyleName } from "./border-glyphs.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type StyleRef = number;

export interface CellDescriptor {
  char: string;
  width: number;
  style: StyleRef;
  hyperlinkId: number | null;
  _pooled?: boolean;
}

export interface ClipRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

// ---------------------------------------------------------------------------
// StylePool
// ---------------------------------------------------------------------------

/**
 * Interns Style objects; equal styles share the same handle.
 * Handle 0 is always the default (empty) style.
 */
export class StylePool {
  private _styles: Style[] = [{}];
  private _keys:   string[] = [this._key({})];

  private _key(s: Style): string {
    return JSON.stringify(s, Object.keys(s).sort());
  }

  intern(style: Style): StyleRef {
    const k = this._key(style);
    const idx = this._keys.indexOf(k);
    if (idx >= 0) return idx;
    this._styles.push(style);
    this._keys.push(k);
    return this._styles.length - 1;
  }

  lookup(ref: StyleRef): Style {
    return this._styles[ref] ?? {};
  }
}

// ---------------------------------------------------------------------------
// HyperlinkPool
// ---------------------------------------------------------------------------

export interface HyperlinkEntry { id: string | null; uri: string; }

/** Interns (id, uri) pairs; returns stable integer handles. */
export class HyperlinkPool {
  private _entries: HyperlinkEntry[] = [];

  intern(id: string | null, uri: string): number {
    const idx = this._entries.findIndex(e => e.id === id && e.uri === uri);
    if (idx >= 0) return idx;
    this._entries.push({ id, uri });
    return this._entries.length - 1;
  }

  lookup(handle: number): HyperlinkEntry {
    return this._entries[handle] ?? { id: null, uri: "" };
  }
}

// ---------------------------------------------------------------------------
// CharPool
// ---------------------------------------------------------------------------

const POOL_INITIAL_SIZE = 2048;

/** Fixed-size pool of CellDescriptors to avoid per-frame allocation. */
export class CharPool {
  private _free: CellDescriptor[] = [];

  constructor(size = POOL_INITIAL_SIZE) {
    for (let i = 0; i < size; i++) {
      this._free.push({ char: " ", width: 1, style: 0, hyperlinkId: null, _pooled: false });
    }
  }

  acquire(): CellDescriptor {
    const c = this._free.pop();
    if (c) { c._pooled = true; return c; }
    return { char: " ", width: 1, style: 0, hyperlinkId: null, _pooled: true };
  }

  release(cell: CellDescriptor): void {
    cell.char = " "; cell.width = 1; cell.style = 0;
    cell.hyperlinkId = null; cell._pooled = false;
    this._free.push(cell);
  }
}

// ---------------------------------------------------------------------------
// Screen buffer
// ---------------------------------------------------------------------------

export class Screen {
  private _cells: CellDescriptor[][] = [];
  width  = 0;
  height = 0;

  constructor(private _pool: CharPool) {}

  resize(width: number, height: number): void {
    const newCells: CellDescriptor[][] = [];
    for (let r = 0; r < height; r++) {
      const row: CellDescriptor[] = [];
      for (let c = 0; c < width; c++) {
        const existing = this._cells[r]?.[c];
        row.push(existing ?? this._pool.acquire());
      }
      newCells.push(row);
    }
    // Release orphan cells
    for (let r = 0; r < this._cells.length; r++) {
      const oldRow = this._cells[r]!;
      const keepCols = r < height ? width : 0;
      for (let c = keepCols; c < oldRow.length; c++) {
        this._pool.release(oldRow[c]!);
      }
    }
    this._cells = newCells;
    this.width  = width;
    this.height = height;
  }

  clear(): void {
    for (const row of this._cells)
      for (const cell of row) {
        cell.char = " "; cell.width = 1;
        cell.style = 0; cell.hyperlinkId = null;
      }
  }

  getCell(row: number, col: number): CellDescriptor {
    return this._cells[row]?.[col] ?? { char: " ", width: 1, style: 0, hyperlinkId: null };
  }

  setCell(row: number, col: number, cell: CellDescriptor): void {
    if (row < 0 || row >= this.height || col < 0 || col >= this.width) return;
    const existing = this._cells[row]?.[col];
    if (existing && existing !== cell) {
      // copy fields
      existing.char        = cell.char;
      existing.width       = cell.width;
      existing.style       = cell.style;
      existing.hyperlinkId = cell.hyperlinkId;
    }
  }
}

// ---------------------------------------------------------------------------
// Output
// ---------------------------------------------------------------------------

/** Accumulates terminal output sequences for one frame. */
export class Output {
  private _buf = "";

  constructor(
    private _stylePool: StylePool,
    private _hyperlinkPool: HyperlinkPool,
  ) {}

  write(text: string): void { this._buf += text; }

  /** Emit minimal SGR transition from previousStyle → style. */
  writeSGR(style: Style, previousStyle: Style): void {
    // Fast path: same style handle
    if (style === previousStyle) return;
    if (JSON.stringify(style) === JSON.stringify(previousStyle)) return;

    const changes: string[] = [];
    let needsReset = false;

    // Detect attribute removals — requires reset
    if (previousStyle.bold && !style.bold)          needsReset = true;
    if (previousStyle.dim  && !style.dim)           needsReset = true;
    if (previousStyle.italic && !style.italic)      needsReset = true;
    if (previousStyle.underline && !style.underline) needsReset = true;
    if (previousStyle.inverse && !style.inverse)    needsReset = true;
    if (previousStyle.strikethrough && !style.strikethrough) needsReset = true;
    if (previousStyle.fg && !style.fg) needsReset = true;
    if (previousStyle.bg && !style.bg) needsReset = true;

    if (needsReset) {
      this._buf += "\x1b[m";
      // Re-apply all attributes in new style
      if (style.bold)          changes.push("1");
      if (style.dim)           changes.push("2");
      if (style.italic)        changes.push("3");
      if (style.underline)     changes.push("4");
      if (style.inverse)       changes.push("7");
      if (style.strikethrough) changes.push("9");
      if (style.fg) changes.push(this._fgCode(style.fg));
      if (style.bg) changes.push(this._bgCode(style.bg));
      if (changes.length > 0) this._buf += `\x1b[${changes.join(";")}m`;
      return;
    }

    // Only additions — can be done without reset
    if (style.bold && !previousStyle.bold)          changes.push("1");
    if (style.dim  && !previousStyle.dim)           changes.push("2");
    if (style.italic && !previousStyle.italic)      changes.push("3");
    if (style.underline && !previousStyle.underline) changes.push("4");
    if (style.inverse && !previousStyle.inverse)    changes.push("7");
    if (style.strikethrough && !previousStyle.strikethrough) changes.push("9");

    // Color changes
    if (style.fg && JSON.stringify(style.fg) !== JSON.stringify(previousStyle.fg))
      changes.push(this._fgCode(style.fg));
    if (style.bg && JSON.stringify(style.bg) !== JSON.stringify(previousStyle.bg))
      changes.push(this._bgCode(style.bg));

    if (changes.length > 0) this._buf += `\x1b[${changes.join(";")}m`;
  }

  private _fgCode(c: ColorValue): string {
    if (c.type === "rgb") return `38;2;${c.r};${c.g};${c.b}`;
    if (c.type === "indexed") return `38;5;${c.index}`;
    return c.index < 8 ? `${30 + c.index}` : `${90 + c.index - 8}`;
  }

  private _bgCode(c: ColorValue): string {
    if (c.type === "rgb") return `48;2;${c.r};${c.g};${c.b}`;
    if (c.type === "indexed") return `48;5;${c.index}`;
    return c.index < 8 ? `${40 + c.index}` : `${100 + c.index - 8}`;
  }

  writeHyperlinkOpen(id: string | null, uri: string): void {
    const params = id ? `id=${id}` : "";
    this._buf += `\x1b]8;${params};${uri}\x1b\\`;
  }

  writeHyperlinkClose(): void {
    this._buf += "\x1b]8;;\x1b\\";
  }

  /** Return accumulated string and reset. */
  flush(): string {
    const s = this._buf;
    this._buf = "";
    return s;
  }
}

// ---------------------------------------------------------------------------
// Frame and Patch
// ---------------------------------------------------------------------------

export interface FrameCell {
  char: string;
  width: number;
  styleRef: StyleRef;
  hyperlinkId: number | null;
}

export interface Frame {
  cells: FrameCell[][];
  width: number;
  height: number;
}

export interface PatchChange {
  row: number;
  col: number;
  cell: FrameCell;
}

export interface Patch {
  changes: PatchChange[];
}

// ---------------------------------------------------------------------------
// RenderNode (the virtual DOM node the pipeline works with)
// ---------------------------------------------------------------------------

export type RenderNodeKind = "box" | "text" | "raw-ansi" | "root";

export interface RenderNode {
  kind: RenderNodeKind;
  children: RenderNode[];
  layout: LayoutNode;
  /** For text nodes: the text content. */
  text?: string;
  /** For text nodes: applied style. */
  style?: Style;
  /** Raw ANSI string for raw-ansi nodes. */
  rawAnsi?: string;
  /** For box nodes: perimeter style name (undefined = no border painted). */
  borderStyle?: BorderStyleName;
  /** For box nodes: border glyph color (chalk-style name or #rrggbb hex). */
  borderColor?: string;
  /** For box nodes: text embedded in the top border edge (D4 titled-panel composition). */
  borderTitle?: string;
}

// ---------------------------------------------------------------------------
// charCache — memoizes CellDescriptor for single-char strings
// ---------------------------------------------------------------------------

export const charCache = new Map<string, CellDescriptor>();

// Pre-populate ASCII printable range
for (let i = 0x20; i <= 0x7e; i++) {
  const ch = String.fromCharCode(i);
  charCache.set(ch, { char: ch, width: 1, style: 0, hyperlinkId: null });
}

/** Visual width of a character (1 for most; 2 for CJK/emoji). */
function charWidth(ch: string): number {
  const cp = ch.codePointAt(0) ?? 0;
  // Wide CJK ranges (simplified check)
  if ((cp >= 0x1100 && cp <= 0x115f) ||
      (cp >= 0x2e80 && cp <= 0x303f) ||
      (cp >= 0x3040 && cp <= 0x9fff) ||
      (cp >= 0xac00 && cp <= 0xd7af) ||
      (cp >= 0xf900 && cp <= 0xfaff) ||
      (cp >= 0xff01 && cp <= 0xff60) ||
      (cp >= 0x1f300 && cp <= 0x1f9ff))
    return 2;
  return 1;
}

// ---------------------------------------------------------------------------
// Border painting — box borderStyle/borderColor/borderTitle rendered as a real
// perimeter (B2 increment). Lives here, not components.ts, because painting is
// a rendering-pipeline concern; components.ts only ever drops the declarative
// intent into data-attrs (mirrors how text/raw-ansi nodes are painted here too).
// ---------------------------------------------------------------------------

const BORDER_NAMED_FG: Record<string, number> = {
  black: 0, red: 1, green: 2, yellow: 3, blue: 4, magenta: 5, cyan: 6, white: 7,
  gray: 8, grey: 8,
};

/** Resolves a chalk-style color name or #rrggbb hex into a border Style. Border
 * colors are always foreground-only (glyphs, never a filled background). */
function resolveBorderColorStyle(colorName: string | undefined): Style {
  if (!colorName) return {};
  if (colorName.startsWith("#")) {
    const hex = colorName.slice(1);
    const r = parseInt(hex.slice(0, 2), 16) || 0;
    const g = parseInt(hex.slice(2, 4), 16) || 0;
    const b = parseInt(hex.slice(4, 6), 16) || 0;
    return { fg: { type: "rgb", r, g, b } };
  }
  const idx = BORDER_NAMED_FG[colorName.toLowerCase()];
  return idx !== undefined ? { fg: { type: "named", index: idx } } : {};
}

/** Paints a box's perimeter (all 4 edges) at its own layout rect, clipped to
 * clipRect exactly like text painting. Embeds borderTitle in the top edge when
 * given (falls back to a truncated title, never throwing, when it overflows the
 * available inner width). No-ops when the box is too small to hold a border. */
function paintBorder(
  node: RenderNode,
  output: Output,
  lx: number, ly: number, lw: number, lh: number,
  clipRect: ClipRect,
): void {
  if (!node.borderStyle || lw < 2 || lh < 2) return;
  const glyphs = resolveBorderGlyphs(node.borderStyle);
  const style  = resolveBorderColorStyle(node.borderColor);
  const inner  = Math.max(0, lw - 2);

  const writeAt = (row: number, col: number, ch: string): void => {
    if (col < clipRect.x || col >= clipRect.x + clipRect.width) return;
    if (row < clipRect.y || row >= clipRect.y + clipRect.height) return;
    output.write(cursorPosition(row + 1, col + 1));
    output.writeSGR(style, {});
    output.write(ch);
  };

  // Top edge — plain horizontal run, or with the title embedded just after the
  // corner glyph (a much-too-long title truncates to `inner` rather than throwing
  // or being silently dropped).
  let topMid: string;
  if (node.borderTitle && node.borderTitle.length > 0) {
    const padded = ` ${node.borderTitle} `;
    if (padded.length <= inner) {
      const leftFill  = 1;
      const rightFill = Math.max(0, inner - leftFill - padded.length);
      topMid = glyphs.horizontal.repeat(leftFill) + padded + glyphs.horizontal.repeat(rightFill);
    } else {
      const truncated = node.borderTitle.slice(0, inner);
      topMid = truncated + glyphs.horizontal.repeat(Math.max(0, inner - truncated.length));
    }
  } else {
    topMid = glyphs.horizontal.repeat(inner);
  }
  const topRow = glyphs.topLeft + topMid + glyphs.topRight;
  for (let i = 0; i < topRow.length && i < lw; i++) writeAt(ly, lx + i, topRow[i]!);

  // Side edges — vertical glyph at the leftmost/rightmost column of every row
  // strictly between the top and bottom edges.
  for (let r = 1; r < lh - 1; r++) {
    writeAt(ly + r, lx, glyphs.vertical);
    writeAt(ly + r, lx + lw - 1, glyphs.vertical);
  }

  // Bottom edge — plain horizontal run, no title.
  const bottomRow = glyphs.bottomLeft + glyphs.horizontal.repeat(inner) + glyphs.bottomRight;
  for (let i = 0; i < bottomRow.length && i < lw; i++) writeAt(ly + lh - 1, lx + i, bottomRow[i]!);

  // Self-terminating (style-bleed.test.ts): every glyph write above assumes the SAME
  // always-empty previous style text painting does, so a colored border leaves the real
  // terminal state non-default with nothing downstream aware it must reset. Explicitly
  // closing out the color here, once, keeps the border's own paint self-contained instead
  // of leaking into whatever renders immediately after it.
  if (style.fg || style.bg) output.write("\x1b[m");
}

// ---------------------------------------------------------------------------
// renderNodeToOutput
// ---------------------------------------------------------------------------

/**
 * Recursively renders a layout node subtree into an Output, starting at
 * terminal position (x, y), clipped to clipRect.
 */
export function renderNodeToOutput(
  node: RenderNode,
  output: Output,
  x: number,
  y: number,
  clipRect: ClipRect,
  stylePool: StylePool,
  hyperlinkPool: HyperlinkPool,
): void {
  const lx = x + node.layout.computedLeft;
  const ly = y + node.layout.computedTop;
  const lw = node.layout.computedWidth;
  const lh = node.layout.computedHeight;

  // clip check
  if (lx >= clipRect.x + clipRect.width) return;
  if (ly >= clipRect.y + clipRect.height) return;
  if (lx + lw <= clipRect.x) return;
  if (ly + lh <= clipRect.y) return;

  if (node.kind === "text" && node.text !== undefined) {
    const style = node.style ?? {};
    // Write each character
    let col = lx;
    const row = ly;
    for (const ch of node.text) {
      if (col >= clipRect.x + clipRect.width) break;
      if (col >= clipRect.x && row >= clipRect.y && row < clipRect.y + clipRect.height) {
        const ref = stylePool.intern(style);
        output.write(cursorPosition(row + 1, col + 1));
        const prevStyle = stylePool.lookup(0);
        output.writeSGR(style, prevStyle);
        output.write(ch);
      }
      col += charWidth(ch);
    }
  } else if (node.kind === "raw-ansi" && node.rawAnsi !== undefined) {
    output.write(cursorPosition(ly + 1, lx + 1));
    output.write(node.rawAnsi);
  } else if (node.kind === "box" && node.borderStyle) {
    paintBorder(node, output, lx, ly, lw, lh, clipRect);
  }

  // Recurse into children
  for (const child of node.children) {
    renderNodeToOutput(child, output, lx, ly, clipRect, stylePool, hyperlinkPool);
  }
}

// ---------------------------------------------------------------------------
// LogUpdate diff
// ---------------------------------------------------------------------------

/** Compare two frames cell-by-cell; produce minimal patch. */
export function diffFrames(prev: Frame | null, curr: Frame): Patch {
  const changes: PatchChange[] = [];
  for (let r = 0; r < curr.height; r++) {
    for (let c = 0; c < curr.width; c++) {
      const cell = curr.cells[r]?.[c];
      if (!cell) continue;
      if (prev) {
        const p = prev.cells[r]?.[c];
        if (p &&
            p.char === cell.char &&
            p.styleRef === cell.styleRef &&
            p.hyperlinkId === cell.hyperlinkId) {
          continue;
        }
      }
      changes.push({ row: r, col: c, cell });
      // Wide char: right half
      if (cell.width === 2 && c + 1 < curr.width) {
        const right = curr.cells[r]?.[c + 1];
        if (right) changes.push({ row: r, col: c + 1, cell: right });
      }
    }
  }
  return { changes };
}

// ---------------------------------------------------------------------------
// Optimizer
// ---------------------------------------------------------------------------

interface Run {
  row: number;
  startCol: number;
  cells: FrameCell[];
}

/** Merges adjacent changed cells in the same row into contiguous runs. */
export function optimizePatch(patch: Patch): Run[] {
  const runs: Run[] = [];
  // Sort by row then col
  const sorted = [...patch.changes].sort((a, b) =>
    a.row !== b.row ? a.row - b.row : a.col - b.col);

  let current: Run | null = null;
  for (const change of sorted) {
    if (current && change.row === current.row &&
        change.col === current.startCol + current.cells.length) {
      current.cells.push(change.cell);
    } else {
      if (current) runs.push(current);
      current = { row: change.row, startCol: change.col, cells: [change.cell] };
    }
  }
  if (current) runs.push(current);
  return runs;
}

// ---------------------------------------------------------------------------
// buildFrame — converts a rendered Output string into a Frame
// ---------------------------------------------------------------------------

/** Builds a Frame from direct cell writes (simplified: text-first approach). */
export function buildFrame(width: number, height: number): Frame {
  const cells: FrameCell[][] = [];
  for (let r = 0; r < height; r++) {
    const row: FrameCell[] = [];
    for (let c = 0; c < width; c++) {
      row.push({ char: " ", width: 1, styleRef: 0, hyperlinkId: null });
    }
    cells.push(row);
  }
  return { cells, width, height };
}

/** Write text into a Frame at the given position. */
export function writeToFrame(
  frame: Frame, text: string, row: number, col: number, styleRef: StyleRef,
): void {
  let c = col;
  for (const ch of text) {
    if (c >= frame.width) break;
    const cell = frame.cells[row]?.[c];
    if (cell) { cell.char = ch; cell.styleRef = styleRef; cell.hyperlinkId = null; }
    const w = charWidth(ch);
    if (w === 2 && c + 1 < frame.width) {
      const right = frame.cells[row]?.[c + 1];
      if (right) { right.char = ""; right.width = 2; right.styleRef = styleRef; }
    }
    c += w;
  }
}

// ---------------------------------------------------------------------------
// nodeCache
// ---------------------------------------------------------------------------

export interface CachedNodeLayout {
  layoutVersion: number;
}

export const nodeCache = new WeakMap<RenderNode, CachedNodeLayout>();

// ---------------------------------------------------------------------------
// Renderer
// ---------------------------------------------------------------------------

export interface RendererOptions {
  stream: { write(s: string): void };
  stdout: { columns: number; rows: number };
  debug?: boolean;
}

export interface Renderer {
  render(rootNode: RenderNode): void;
  unmount(): void;
  clear(): void;
}

/** Creates a stateful double-buffered renderer. */
export function createRenderer(options: RendererOptions): Renderer {
  const { stream, stdout } = options;
  const stylePool    = new StylePool();
  const hyperlinkPool = new HyperlinkPool();

  let prevFrame: Frame | null = null;
  let currentFrame: Frame | null = null;

  return {
    render(rootNode: RenderNode): void {
      const w = stdout.columns;
      const h = stdout.rows;

      // Build output for the whole frame
      const output = new Output(stylePool, hyperlinkPool);
      const clipRect: ClipRect = { x: 0, y: 0, width: w, height: h };

      // Run layout
      rootNode.layout.calculateLayout(w, h, "ltr");

      renderNodeToOutput(rootNode, output, 0, 0, clipRect, stylePool, hyperlinkPool);
      const rendered = output.flush();

      // Build current frame from rendered output by re-parsing
      const frame = buildFrame(w, h);

      // Simple parse: extract cursorPosition + text sequences from rendered output
      parseRenderedIntoFrame(rendered, frame, stylePool);

      currentFrame = frame;

      // Diff
      const patch = diffFrames(prevFrame, currentFrame);
      const runs  = optimizePatch(patch);

      // Write minimal output
      let buf = "";
      let prevStyleRef: StyleRef = 0;
      for (const run of runs) {
        buf += cursorPosition(run.row + 1, run.startCol + 1);
        for (const cell of run.cells) {
          const style = stylePool.lookup(cell.styleRef);
          const prevStyle = stylePool.lookup(prevStyleRef);
          const tmp = new Output(stylePool, hyperlinkPool);
          tmp.writeSGR(style, prevStyle);
          buf += tmp.flush();
          buf += cell.char;
          prevStyleRef = cell.styleRef;
        }
      }
      if (buf) stream.write(buf);

      // M9-DIAG-LIVE: capture per-paint diagnostic for live root-cause
      try {
        const _diagIsFirst = !prevFrame;
        const _diagRow28 = "\x1b[29;1H";
        const _diagRow29 = "\x1b[30;1H";
        const _diagR28i = buf.indexOf(_diagRow28);
        const _diagR29i = buf.indexOf(_diagRow29);
        const _diagEntry = JSON.stringify({
          ts: Date.now(),
          paint: _diagIsFirst ? "first" : "subsequent",
          h, w,
          buf_len: buf.length,
          has_row28: _diagR28i >= 0,
          has_row29: _diagR29i >= 0,
          row28_ctx: _diagR28i >= 0 ? buf.slice(_diagR28i, Math.min(_diagR28i + 60, buf.length)) : null,
          row29_ctx: _diagR29i >= 0 ? buf.slice(_diagR29i, Math.min(_diagR29i + 60, buf.length)) : null,
          live_stdout_rows: process.stdout.rows ?? null,
          live_stdout_cols: process.stdout.columns ?? null,
        });
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        (require("fs") as typeof import("fs")).appendFileSync(
          "C:/WINDOWS/TEMP/ember-m9-diag.jsonl",
          _diagEntry + "\n",
        );
      } catch { /* M9-DIAG-LIVE silent */ }

      prevFrame = currentFrame;
    },

    unmount(): void {
      prevFrame = null;
      currentFrame = null;
    },

    clear(): void {
      prevFrame = null;
    },
  };
}

// ---------------------------------------------------------------------------
// parseRenderedIntoFrame — extract cells from a rendered terminal sequence
// ---------------------------------------------------------------------------

export function parseRenderedIntoFrame(rendered: string, frame: Frame, stylePool: StylePool): void {
  // Parse cursor-position + SGR + text sequences
  let pos = 0;
  let curRow = 0;
  let curCol = 0;
  let currentStyleRef: StyleRef = 0;

  while (pos < rendered.length) {
    if (rendered[pos] === "\x1b" && rendered[pos + 1] === "[") {
      // CSI sequence
      const start = pos;
      pos += 2;
      let params = "";
      while (pos < rendered.length && !/[A-Za-z@\[\\\]^_`]/.test(rendered[pos] ?? "")) {
        params += rendered[pos] ?? "";
        pos++;
      }
      const final = rendered[pos] ?? "";
      pos++;

      if (final === "H") {
        // cursorPosition
        const parts = params.split(";");
        curRow = Math.max(0, (parseInt(parts[0] ?? "1", 10) || 1) - 1);
        curCol = Math.max(0, (parseInt(parts[1] ?? "1", 10) || 1) - 1);
      } else if (final === "m") {
        // SGR
        if (params === "" || params === "0") {
          currentStyleRef = 0;
        } else {
          // Parse SGR codes back to style
          const codes = params.split(";").map(s => parseInt(s, 10));
            const style = applyAnsiCodes(codes, stylePool.lookup(currentStyleRef));
          currentStyleRef = stylePool.intern(style);
        }
      }
      void start;
    } else if (rendered[pos] === "\x1b" && rendered[pos + 1] === "]") {
      // OSC — skip to ST or BEL
      pos += 2;
      while (pos < rendered.length) {
        if (rendered[pos] === "\x07") { pos++; break; }
        if (rendered[pos] === "\x1b" && rendered[pos + 1] === "\\") { pos += 2; break; }
        pos++;
      }
    } else {
      // Printable character
      const ch = rendered[pos] ?? "";
      pos++;
      if (curRow < frame.height && curCol < frame.width) {
        const cell = frame.cells[curRow]?.[curCol];
        if (cell && ch >= " ") {
          cell.char = ch;
          cell.styleRef = currentStyleRef;
        }
      }
      curCol += charWidth(ch);
    }
  }
}
