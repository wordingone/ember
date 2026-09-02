// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// rendering-pipeline — terminal renderer core: object pools, screen buffer,
// double-buffered diff, optimizer, and render entry point.
// Cross-layer deps (event-system) are injected as optional interfaces.

import type { Style, ColorValue } from "./termio.ts";
import { cursorPosition, applyAnsiCodes } from "./termio.ts";
import type { LayoutNode } from "./layout-engine.ts";
import { resolveBorderGlyphs, type BorderStyleName } from "./border-glyphs.ts";
import type { RendererDiagnostic } from "./renderer-diagnostic.ts";
import type { HeapAttributionDiagnostic } from "./heap-attribution-diagnostic.ts";

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

  /** Order-independent key covering the FULL style, nested color values included.
   * B2 fix: the prior `JSON.stringify(s, Object.keys(s).sort())` passed the sorted
   * key list as JSON.stringify's ARRAY REPLACER, which filters to that allow-list
   * at every nesting level -- not just the top. That silently stripped every key
   * inside a ColorValue (type/r/g/b or type/index), collapsing e.g. an orange RGB
   * fg and an unrelated teal RGB fg to the identical key `{"fg":{}}`. Two visually
   * distinct colors then interned to the SAME pool slot, and whichever was
   * written first "won" every later lookup of that slot -- exactly the bleed
   * pattern that made the reconstructed Homescreen's border/fireball colors read
   * wrong (#168 pixel-gate bounce). Serializing each key's value independently
   * (no replacer) keeps nested contents intact while staying order-independent. */
  private _key(s: Style): string {
    const keys = (Object.keys(s) as (keyof Style)[]).sort();
    return keys.map(k => `${k}:${JSON.stringify(s[k])}`).join(",");
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

  /** Number of interned slots, including the permanent default at handle 0. */
  size(): number {
    return this._styles.length;
  }

  /** issue #1455: this pool is intern-only for the renderer's entire process lifetime -- every
   *  distinct style identity ever painted (down to the RGB channel) is retained forever with no
   *  eviction. A bounded terminal palette stabilizes at a handful of slots and never calls this;
   *  a caller that paints continuously-unique styles (a numeric-driven gradient, a per-tick
   *  computed color) would otherwise grow this array without bound for as long as the cockpit
   *  stays up. Drops every interned style except the default. Every StyleRef issued before this
   *  call is invalidated -- the caller MUST force a full repaint (bypass any diff against a frame
   *  painted before the reset) so a stale ref is never looked up against the new index space. */
  reset(): void {
    this._styles = [{}];
    this._keys = [this._key({})];
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

  /** Number of interned slots. */
  size(): number {
    return this._entries.length;
  }

  /** issue #1455: same intern-only, never-evicted shape as StylePool (see its reset() for the
   *  full rationale) -- distinct (id, uri) pairs accumulate for the renderer's entire lifetime.
   *  Every handle issued before this call is invalidated; the caller MUST force a full repaint. */
  reset(): void {
    this._entries = [];
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
  /** Reused across flushes so full-frame rendering does not build a fresh chain of rope
   * intermediates for every pass. The joined string remains the only per-frame aggregate. */
  private readonly _chunks: string[] = [];

  constructor(
    private _stylePool: StylePool,
    private _hyperlinkPool: HyperlinkPool,
  ) {}

  write(text: string): void {
    if (text.length > 0) this._chunks.push(text);
  }

  /** Discard a partial frame after a prior render exception without replacing chunk storage. */
  reset(): void {
    this._chunks.length = 0;
  }

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
      this._chunks.push("\x1b[m");
      // Re-apply all attributes in new style
      if (style.bold)          changes.push("1");
      if (style.dim)           changes.push("2");
      if (style.italic)        changes.push("3");
      if (style.underline)     changes.push("4");
      if (style.inverse)       changes.push("7");
      if (style.strikethrough) changes.push("9");
      if (style.fg) changes.push(this._fgCode(style.fg));
      if (style.bg) changes.push(this._bgCode(style.bg));
      if (changes.length > 0) this._chunks.push(`\x1b[${changes.join(";")}m`);
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

    if (changes.length > 0) this._chunks.push(`\x1b[${changes.join(";")}m`);
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
    this._chunks.push(`\x1b]8;${params};${uri}\x1b\\`);
  }

  writeHyperlinkClose(): void {
    this._chunks.push("\x1b]8;;\x1b\\");
  }

  /** Return accumulated string and reset. */
  flush(): string {
    const s = this._chunks.length === 0
      ? ""
      : this._chunks.length === 1
        ? this._chunks[0]!
        : this._chunks.join("");
    this.reset();
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
export type TextWrapMode =
  | "wrap"
  | "end"
  | "truncate"
  | "truncate-end"
  | "truncate-middle"
  | "truncate-start";

export interface RenderNode {
  kind: RenderNodeKind;
  children: RenderNode[];
  layout: LayoutNode;
  /** For text nodes: the text content. */
  text?: string;
  /** Per-node text overflow policy. Text defaults to word wrapping. */
  textWrap?: TextWrapMode;
  /** Frame-local transformed text. Source text remains immutable in `text`. */
  renderedText?: string;
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

function textWidth(value: string): number {
  let width = 0;
  for (const ch of value) width += charWidth(ch);
  return width;
}

function takeCells(value: string, maxWidth: number, fromEnd = false): string {
  if (maxWidth <= 0) return "";
  const chars = [...value];
  const selected: string[] = [];
  let width = 0;
  const iterable = fromEnd ? chars.reverse() : chars;
  for (const ch of iterable) {
    const next = charWidth(ch);
    if (width + next > maxWidth) break;
    selected.push(ch);
    width += next;
  }
  return fromEnd ? selected.reverse().join("") : selected.join("");
}

function truncateText(value: string, width: number, mode: TextWrapMode): string {
  if (textWidth(value) <= width) return value;
  if (width <= 0) return "";
  if (width === 1) return "…";
  const contentWidth = width - 1;
  if (mode === "truncate-start") return `…${takeCells(value, contentWidth, true)}`;
  if (mode === "truncate-middle") {
    const leftWidth = Math.ceil(contentWidth / 2);
    const rightWidth = Math.floor(contentWidth / 2);
    return `${takeCells(value, leftWidth)}…${takeCells(value, rightWidth, true)}`;
  }
  return `${takeCells(value, contentWidth)}…`;
}

function wrapLogicalLine(value: string, width: number): string[] {
  if (value.length === 0) return [""];
  const remaining = [...value];
  const lines: string[] = [];
  while (remaining.length > 0) {
    let used = 0;
    let end = 0;
    let lastWhitespace = -1;
    while (end < remaining.length) {
      const next = charWidth(remaining[end]!);
      if (used + next > width) break;
      used += next;
      if (/\s/u.test(remaining[end]!)) lastWhitespace = end;
      end++;
    }
    if (end === remaining.length) {
      lines.push(remaining.join("").trimEnd());
      break;
    }
    if (end === 0) {
      // A double-width glyph in a one-cell region cannot be represented faithfully.
      // Keep it as the next row's sole payload rather than looping or dropping it.
      end = 1;
    } else if (lastWhitespace > 0 && (used < width || !/\s/u.test(remaining[end]!))) {
      end = lastWhitespace;
    }
    lines.push(remaining.splice(0, end).join("").trimEnd());
    while (remaining.length > 0 && /\s/u.test(remaining[0]!)) remaining.shift();
  }
  return lines;
}

/** Applies the Text contract to source text without changing the source bytes. */
export function formatTextForWidth(
  value: string,
  width: number,
  mode: TextWrapMode = "wrap",
): string {
  const safeWidth = Math.max(1, Math.floor(width));
  if (mode !== "wrap") {
    return truncateText(value.split("\n")[0] ?? "", safeWidth, mode);
  }
  return value
    .split("\n")
    .flatMap((line) => wrapLogicalLine(line, safeWidth))
    .join("\n");
}

function intrinsicTextDimensions(value: string): { width: number; height: number } {
  const lines = value.split("\n");
  return {
    width: Math.max(1, ...lines.map(textWidth)),
    height: Math.max(1, lines.length),
  };
}

function resetTextLayout(node: RenderNode): void {
  if (node.kind === "text" && node.text !== undefined) {
    const intrinsic = intrinsicTextDimensions(node.text);
    node.renderedText = undefined;
    node.layout.width = intrinsic.width;
    node.layout.height = intrinsic.height;
  }
  for (const child of node.children) resetTextLayout(child);
}

function fitTextLayout(node: RenderNode, parentContentWidth: number): boolean {
  let changed = false;
  if (node.kind === "text" && node.text !== undefined) {
    const intrinsic = intrinsicTextDimensions(node.text);
    const computed = node.layout.computedWidth > 0 ? node.layout.computedWidth : intrinsic.width;
    const available = Math.max(1, Math.min(intrinsic.width, computed, parentContentWidth));
    const formatted = formatTextForWidth(node.text, available, node.textWrap ?? "wrap");
    const fitted = intrinsicTextDimensions(formatted);
    node.renderedText = formatted;
    if (node.layout.width !== available || node.layout.height !== fitted.height) changed = true;
    node.layout.width = available;
    node.layout.height = fitted.height;
  }

  const borderLeft = node.layout.borderLeft || node.layout.border;
  const borderRight = node.layout.borderRight || node.layout.border;
  const paddingLeft = node.layout.paddingLeft || node.layout.padding;
  const paddingRight = node.layout.paddingRight || node.layout.padding;
  const ownContentWidth = Math.max(
    1,
    node.layout.computedWidth - borderLeft - borderRight - paddingLeft - paddingRight,
  );
  const contentOriginX = borderLeft + paddingLeft;
  for (const child of node.children) {
    // A later child in a row (or a child with a left margin) starts partway
    // across the parent's content box. Giving every child the full parent
    // width formats text beyond the parent's right clip and silently drops
    // those cells. Fit against the cells actually remaining from its laid-out
    // origin so wrapped text and painted text share one boundary.
    const childOffset = Math.max(0, child.layout.computedLeft - contentOriginX);
    const childAvailableWidth = Math.max(1, ownContentWidth - childOffset);
    changed = fitTextLayout(child, childAvailableWidth) || changed;
  }
  return changed;
}

function calculateLayoutWithText(rootNode: RenderNode, width: number, height: number): void {
  resetTextLayout(rootNode);
  rootNode.layout.calculateLayout(width, height, "ltr");
  // One pass establishes container constraints; the next makes wrapped row counts part
  // of flex layout. A third pass handles a parent whose new height changes a descendant.
  for (let pass = 0; pass < 3; pass++) {
    const changed = fitTextLayout(rootNode, width);
    if (!changed) break;
    rootNode.layout.calculateLayout(width, height, "ltr");
  }
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

/** Threads the REAL, currently-active style across an entire render() pass (text nodes, border
 * paint, and every recursive call), instead of each write site assuming it starts from a blank
 * terminal. #343: writeSGR's "additions-only" fast path only removes an attribute when the style
 * it's diffing AGAINST actually still has it set -- if every call lies and claims "previous style
 * is always {}" (as both call sites here used to), an attribute a PRIOR write left active (e.g.
 * the cursor's inverse) never gets the removal codes it needs, and the next write's own attributes
 * (e.g. a dim rule line's "2") land ON TOP of it instead of replacing it -- producing exactly the
 * observed bold+dim+inverse ("\x1b[1;2;7m") stack over what should be a plain dim "─" rule. */
export interface PrevStyleTracker { current: Style; }

/** Truncates a border title to `width` cells with a trailing "…" marker — never a bare
 *  codepoint slice with nothing to show a viewer that content was lost. `width <= 0` returns
 *  "" (paintBorder's fill loop handles the empty case); `width === 1` returns just the marker. */
function truncateBorderTitle(title: string, width: number): string {
  if (width <= 0) return "";
  if (width === 1) return "…";
  return `${title.slice(0, width - 1)}…`;
}

/**
 * Computes which absolute row a bordered box's bottom edge paints on, given an ancestor's
 * clip (R4b, state/operator-pass-2026-07-26.md W2 / frame-geometry.ts). Mirrors the D1 pin
 * decision below exactly -- shared so paintBorder and the child-clip computation in
 * renderNodeToOutput can never disagree about which row the border claims.
 */
function pinnedBorderBottomRow(ly: number, lh: number, clipRect: ClipRect): number {
  const naturalBottomRow = ly + lh - 1;
  const visibleBottomRow = Math.min(naturalBottomRow, clipRect.y + clipRect.height - 1);
  return (ly >= clipRect.y && visibleBottomRow > ly) ? visibleBottomRow : naturalBottomRow;
}

interface NodePaintTarget {
  writeAt(row: number, col: number, ch: string, style: Style): void;
  writeRawAnsiAt(row: number, col: number, rawAnsi: string): void;
  resetStyle(): void;
}

class AnsiNodePaintTarget implements NodePaintTarget {
  constructor(
    private readonly output: Output,
    private readonly stylePool: StylePool,
    private readonly previousStyle: PrevStyleTracker,
  ) {}

  writeAt(row: number, col: number, ch: string, style: Style): void {
    this.stylePool.intern(style);
    this.output.write(cursorPosition(row + 1, col + 1));
    this.output.writeSGR(style, this.previousStyle.current);
    this.previousStyle.current = style;
    this.output.write(ch);
  }

  writeRawAnsiAt(row: number, col: number, rawAnsi: string): void {
    this.output.write(cursorPosition(row + 1, col + 1));
    this.output.write(rawAnsi);
    this.previousStyle.current = {};
  }

  resetStyle(): void {
    this.output.write("\x1b[m");
    this.previousStyle.current = {};
  }
}

function decimalDigits(value: number): number {
  const n = Math.abs(Math.trunc(value));
  if (n < 10) return 1;
  if (n < 100) return 2;
  if (n < 1_000) return 3;
  if (n < 10_000) return 4;
  if (n < 100_000) return 5;
  if (n < 1_000_000) return 6;
  return String(n).length;
}

function sameColor(a: ColorValue | undefined, b: ColorValue | undefined): boolean {
  if (a === b) return true;
  if (a === undefined || b === undefined || a.type !== b.type) return false;
  if (a.type === "rgb" && b.type === "rgb") return a.r === b.r && a.g === b.g && a.b === b.b;
  return "index" in a && "index" in b && a.index === b.index;
}

function sameStyle(a: Style, b: Style): boolean {
  return a === b || (
    a.bold === b.bold
    && a.dim === b.dim
    && a.italic === b.italic
    && a.underline === b.underline
    && a.inverse === b.inverse
    && a.strikethrough === b.strikethrough
    && sameColor(a.fg, b.fg)
    && sameColor(a.bg, b.bg)
  );
}

function styleTransitionNeedsReset(style: Style, previousStyle: Style): boolean {
  return Boolean(
    (previousStyle.bold && !style.bold)
    || (previousStyle.dim && !style.dim)
    || (previousStyle.italic && !style.italic)
    || (previousStyle.underline && !style.underline)
    || (previousStyle.inverse && !style.inverse)
    || (previousStyle.strikethrough && !style.strikethrough)
    || (previousStyle.fg && !style.fg)
    || (previousStyle.bg && !style.bg)
  );
}

function normalizedStyle(style: Style): Style {
  const normalized: Style = {};
  if (style.bold) normalized.bold = true;
  if (style.dim) normalized.dim = true;
  if (style.italic) normalized.italic = true;
  if (style.underline) normalized.underline = true;
  if (style.inverse) normalized.inverse = true;
  if (style.strikethrough) normalized.strikethrough = true;
  if (style.fg) normalized.fg = style.fg;
  if (style.bg) normalized.bg = style.bg;
  return normalized;
}

function applyVirtualStyleTransition(
  style: Style,
  previousEmissionStyle: Style,
  previousFrameStyle: Style,
): Style {
  if (sameStyle(style, previousEmissionStyle)) return previousFrameStyle;
  if (styleTransitionNeedsReset(style, previousEmissionStyle)) return normalizedStyle(style);
  const addBold = Boolean(style.bold && !previousEmissionStyle.bold);
  const addDim = Boolean(style.dim && !previousEmissionStyle.dim);
  const addItalic = Boolean(style.italic && !previousEmissionStyle.italic);
  const addUnderline = Boolean(style.underline && !previousEmissionStyle.underline);
  const addInverse = Boolean(style.inverse && !previousEmissionStyle.inverse);
  const addStrike = Boolean(style.strikethrough && !previousEmissionStyle.strikethrough);
  const changeFg = Boolean(style.fg && !sameColor(style.fg, previousEmissionStyle.fg));
  const changeBg = Boolean(style.bg && !sameColor(style.bg, previousEmissionStyle.bg));
  if (!(addBold || addDim || addItalic || addUnderline || addInverse || addStrike || changeFg || changeBg)) {
    return previousFrameStyle;
  }
  const next: Style = { ...previousFrameStyle };
  if (addBold) next.bold = true;
  if (addDim) next.dim = true;
  if (addItalic) next.italic = true;
  if (addUnderline) next.underline = true;
  if (addInverse) next.inverse = true;
  if (addStrike) next.strikethrough = true;
  if (changeFg) next.fg = style.fg!;
  if (changeBg) next.bg = style.bg!;
  return next;
}

function colorSgrLength(color: ColorValue, foreground: boolean): number {
  if (color.type === "rgb") {
    return 7 + decimalDigits(color.r) + decimalDigits(color.g) + decimalDigits(color.b);
  }
  if (color.type === "indexed") return 5 + decimalDigits(color.index);
  const code = color.index < 8
    ? (foreground ? 30 : 40) + color.index
    : (foreground ? 90 : 100) + color.index - 8;
  return decimalDigits(code);
}

function sgrTransitionByteLength(style: Style, previousStyle: Style): number {
  if (sameStyle(style, previousStyle)) return 0;
  const needsReset = styleTransitionNeedsReset(style, previousStyle);
  let items = 0;
  let payloadBytes = 0;
  const add = (bytes: number): void => {
    if (items > 0) payloadBytes += 1;
    payloadBytes += bytes;
    items += 1;
  };
  const addAll = needsReset;
  if (style.bold && (addAll || !previousStyle.bold)) add(1);
  if (style.dim && (addAll || !previousStyle.dim)) add(1);
  if (style.italic && (addAll || !previousStyle.italic)) add(1);
  if (style.underline && (addAll || !previousStyle.underline)) add(1);
  if (style.inverse && (addAll || !previousStyle.inverse)) add(1);
  if (style.strikethrough && (addAll || !previousStyle.strikethrough)) add(1);
  if (style.fg && (addAll || !sameColor(style.fg, previousStyle.fg))) add(colorSgrLength(style.fg, true));
  if (style.bg && (addAll || !sameColor(style.bg, previousStyle.bg))) add(colorSgrLength(style.bg, false));
  return (needsReset ? 3 : 0) + (items > 0 ? payloadBytes + 3 : 0);
}

/** Direct frame producer for the hot cockpit path. It intentionally carries a diagnostic-only
 * count of the bytes the legacy full-frame ANSI oracle would have emitted; frame correctness must
 * never depend on that counter. */
export class FrameRenderTarget implements NodePaintTarget {
  private frame: Frame | null = null;
  private emissionStyle: Style = {};
  private frameStyle: Style = {};
  private styleRefs = new WeakMap<Style, StyleRef>();
  renderedByteLength = 0;

  constructor(
    private readonly stylePool: StylePool,
    private readonly scratch: FrameParseScratch,
  ) {}

  begin(frame: Frame): void {
    this.frame = frame;
    this.emissionStyle = {};
    this.frameStyle = {};
    this.renderedByteLength = 0;
  }

  resetStyleCache(): void {
    this.styleRefs = new WeakMap<Style, StyleRef>();
  }

  private styleRef(style: Style): StyleRef {
    const cached = this.styleRefs.get(style);
    if (cached !== undefined) return cached;
    const ref = this.stylePool.intern(style);
    this.styleRefs.set(style, ref);
    return ref;
  }

  writeAt(row: number, col: number, ch: string, style: Style): void {
    this.renderedByteLength += 4 + decimalDigits(row + 1) + decimalDigits(col + 1);
    this.renderedByteLength += sgrTransitionByteLength(style, this.emissionStyle);
    this.renderedByteLength += Buffer.byteLength(ch);
    this.frameStyle = applyVirtualStyleTransition(style, this.emissionStyle, this.frameStyle);
    this.emissionStyle = style;
    const cell = this.frame?.cells[row]?.[col];
    if (cell) {
      cell.char = ch;
      cell.styleRef = this.styleRef(this.frameStyle);
      cell.hyperlinkId = null;
    }
  }

  writeRawAnsiAt(row: number, col: number, rawAnsi: string): void {
    this.renderedByteLength += 4 + decimalDigits(row + 1) + decimalDigits(col + 1);
    this.renderedByteLength += Buffer.byteLength(rawAnsi);
    if (this.frame) {
      const finalStyleRef = parseRenderedIntoFrame(
        rawAnsi,
        this.frame,
        this.stylePool,
        this.scratch,
        row,
        col,
        this.styleRef(this.frameStyle),
      );
      this.frameStyle = this.stylePool.lookup(finalStyleRef);
    }
    this.emissionStyle = {};
  }

  resetStyle(): void {
    this.renderedByteLength += 3;
    this.emissionStyle = {};
    this.frameStyle = {};
  }
}

/** Paints a box's perimeter (all 4 edges) at its own layout rect, clipped to
 * clipRect exactly like text painting. Embeds borderTitle in the top edge when
 * given (falls back to a truncated title, never throwing, when it overflows the
 * available inner width). No-ops when the box is too small to hold a border. */
function paintBorder(
  node: RenderNode,
  target: NodePaintTarget,
  lx: number, ly: number, lw: number, lh: number,
  clipRect: ClipRect,
): void {
  if (!node.borderStyle || lw < 2 || lh < 2) return;
  const glyphs = resolveBorderGlyphs(node.borderStyle);
  const style  = resolveBorderColorStyle(node.borderColor);
  const inner  = Math.max(0, lw - 2);

  // D1 (legibility scope addition, 2026-07): "the left orange banner has lost its bottom
  // border -- the box does not close." Root cause: an ancestor's overflow:"hidden" (a Box
  // flexShrink'ing under height pressure, e.g. repl.ts's `banner` wrapper around <Homescreen>)
  // can hand this node a clipRect whose bottom edge sits ABOVE this box's own bottomRow
  // (ly + lh - 1) while its topRow (ly) is still fully visible -- so the top edge painted fine
  // and the bottom edge's writeAt() calls below all silently dropped, leaving an open-ended box.
  // A bordered box should never render with one edge visible and the other silently missing:
  // when the natural bottom edge falls outside the visible extent but the top edge and at least
  // one more row below it are still visible, PIN the bottom edge to the last visible row instead
  // of its own computedHeight-1 -- sacrificing interior content rows rather than the box's own
  // closing edge. This is the render-time enforcement of "a container always closes" for every
  // bordered Box, not just this one call site.
  //
  // R4b correction (state/operator-pass-2026-07-26.md W2, frame-geometry.ts): the "already
  // independently clipped by the normal per-row/per-child clip, so no double-paint" assumption
  // above was WRONG for a box whose own height resolves via the layout engine's "auto" content-sum
  // (layout-engine.ts line ~461) rather than a definite number -- an ancestor's overflow crop pins
  // *this* border to a row inside the box's real interior, but the child clip computed in
  // renderNodeToOutput was intersected only against THIS box's own (unclipped, full-natural-height)
  // interior, so a content row at exactly the pinned row was still "visible" by that separate
  // check and got painted on the identical cell the border claims (the homescreen bottom-border
  // content-bleed: NATIVE_HINT text sharing a row with "╰"). Fixed at the shared root: whenever a
  // bordered box's children are given a clip (renderNodeToOutput, below), that clip's bottom is now
  // additionally bounded by this same pinnedBorderBottomRow() -- the border row is never also a
  // legal content row, independent of whether the box declared its own overflow:"hidden".
  const bottomRow_ = pinnedBorderBottomRow(ly, lh, clipRect);

  const writeAt = (row: number, col: number, ch: string): void => {
    if (col < clipRect.x || col >= clipRect.x + clipRect.width) return;
    if (row < clipRect.y || row >= clipRect.y + clipRect.height) return;
    target.writeAt(row, col, ch, style);
  };

  // Top edge — plain horizontal run, or with the title embedded just after the
  // corner glyph. A too-long title never silently loses characters (legibility bar,
  // 2026-07-26): it either drops its padding spaces to fit, or truncates with a
  // visible "…" marker — the same discipline as clipToWidth/truncateAnsiLineToWidth
  // elsewhere in this app. A raw `.slice(0, inner)` here was indistinguishable from
  // an intentionally short title (no marker at all).
  let topMid: string;
  if (node.borderTitle && node.borderTitle.length > 0) {
    const padded = ` ${node.borderTitle} `;
    if (padded.length <= inner) {
      const leftFill  = 1;
      const rightFill = Math.max(0, inner - leftFill - padded.length);
      topMid = glyphs.horizontal.repeat(leftFill) + padded + glyphs.horizontal.repeat(rightFill);
    } else if (node.borderTitle.length <= inner) {
      // Fits without its wrapping spaces — not a content loss, just less breathing room.
      const leftFill = Math.min(1, inner - node.borderTitle.length);
      topMid = glyphs.horizontal.repeat(leftFill)
        + node.borderTitle
        + glyphs.horizontal.repeat(Math.max(0, inner - leftFill - node.borderTitle.length));
    } else {
      const truncated = truncateBorderTitle(node.borderTitle, inner);
      topMid = truncated + glyphs.horizontal.repeat(Math.max(0, inner - truncated.length));
    }
  } else {
    topMid = glyphs.horizontal.repeat(inner);
  }
  const topRow = glyphs.topLeft + topMid + glyphs.topRight;
  for (let i = 0; i < topRow.length && i < lw; i++) writeAt(ly, lx + i, topRow[i]!);

  // Side edges — vertical glyph at the leftmost/rightmost column of every row strictly between
  // the top edge and the (possibly pinned) bottom edge.
  for (let r = ly + 1; r < bottomRow_; r++) {
    writeAt(r, lx, glyphs.vertical);
    writeAt(r, lx + lw - 1, glyphs.vertical);
  }

  // Bottom edge — plain horizontal run, no title. Painted at bottomRow_ (pinned to the last
  // visible row when the box's true bottom edge is clipped away — see above), not unconditionally
  // at ly + lh - 1.
  const bottomRow = glyphs.bottomLeft + glyphs.horizontal.repeat(inner) + glyphs.bottomRight;
  for (let i = 0; i < bottomRow.length && i < lw; i++) writeAt(bottomRow_, lx + i, bottomRow[i]!);

  // Self-terminating (style-bleed.test.ts): a colored border leaves the real terminal state
  // non-default with nothing downstream aware it must reset. Explicitly closing out the color
  // here, once, keeps the border's own paint self-contained instead of leaking into whatever
  // renders immediately after it -- and updates the shared tracker to match, so the NEXT write
  // (text/border, sibling or child) correctly sees the terminal as default again.
  if (style.fg || style.bg) {
    target.resetStyle();
  }
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
  // #343: shared across the WHOLE tree walk (one per render() pass) so every write site knows
  // the real, currently-active style instead of each independently assuming "starts from {}".
  // Optional + defaulted so any external caller still constructing a bare 7-arg call keeps working.
  prevStyleTracker: PrevStyleTracker = { current: {} },
): void {
  renderNodeToTarget(
    node,
    new AnsiNodePaintTarget(output, stylePool, prevStyleTracker),
    x,
    y,
    clipRect,
  );
}

function renderNodeToTarget(
  node: RenderNode,
  target: NodePaintTarget,
  x: number,
  y: number,
  clipRect: ClipRect,
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
    // Write each character, handling newlines to advance to the next row.
    // #561: a right-edge overflow used to `break` out of the WHOLE loop -- correct for a
    // single-line node, but for multi-line text (node.text containing '\n') that silently
    // dropped every subsequent line the moment the FIRST line ran past the clip width. Skipping
    // just the out-of-bounds char (instead of aborting the loop) lets a later '\n' still reset
    // col and resume painting on the next row.
    let col = lx;
    let row = ly;
    for (const ch of node.renderedText ?? node.text) {
      if (ch === "\n") {
        row++;
        col = lx;
        continue;
      }
      const inBounds =
        col >= clipRect.x && col < clipRect.x + clipRect.width &&
        row >= clipRect.y && row < clipRect.y + clipRect.height;
      if (inBounds) {
        target.writeAt(row, col, ch, style);
      }
      col += charWidth(ch);
    }
  } else if (node.kind === "raw-ansi" && node.rawAnsi !== undefined) {
    target.writeRawAnsiAt(ly, lx, node.rawAnsi);
  } else if (node.kind === "box" && node.borderStyle) {
    paintBorder(node, target, lx, ly, lw, lh, clipRect);
  }

  // #561 P0-A / W4: overflow:"hidden" has always been a declared layout property
  // (layout-engine.ts's LayoutNode.overflow) but was never enforced here -- the SAME clipRect
  // flowed unchanged into every descendant regardless of an ancestor's own overflow:"hidden",
  // so oversized content painted straight through a box's own boundary into whatever sat below
  // or beside it (the operator's corrupted-banner report: "left column blank, content offset to
  // mid-right"; confirmed with a minimal two-column repro where a wide overflow:"hidden" child's
  // text overwrote its sibling's text mid-line). Intersecting clipRect with this node's own
  // painted rect -- only when it declares overflow:"hidden", and only for what gets passed to
  // its OWN children -- makes overflow:"hidden" actually clip, without touching the default
  // ("visible") behavior any other node relies on.
  // D2 (legibility scope addition, 2026-07): the intersect rect below used to be the box's FULL
  // OUTER rect (lx, ly, lw, lh) -- the exact same rect paintBorder uses for the border glyphs
  // themselves. layout-engine.ts already insets CHILD POSITIONING by border width (reconciler.ts's
  // applyBorderProps sets layout.border=1 whenever borderStyle is present), but an unwrapped/
  // overlong Text child is not constrained by its own declared width at paint time -- only by
  // whatever clipRect it inherits. So a bordered overflow:"hidden" Box's clip rect must ALSO be
  // inset by its own border width, or overrunning content paints straight onto (and past) the
  // border glyphs paintBorder already drew -- the operator's report: a watchdog line breaking
  // through the blue container's right border, drawn OVER the border character and out past it.
  // Mirrors layout-engine.ts lines ~272-275's own bt/br/bb/bl fallback-to-`border` computation so
  // the two insets can never disagree. Zero-width/height when a border would consume the whole
  // box is clamped by intersectClipRect's own Math.max(0, ...), same as any other empty rect.
  const bt = node.layout.borderTop    || node.layout.border;
  const br = node.layout.borderRight  || node.layout.border;
  const bb = node.layout.borderBottom || node.layout.border;
  const bl = node.layout.borderLeft   || node.layout.border;
  let childClipRect: ClipRect = node.layout.overflow === "hidden"
    ? intersectClipRect(clipRect, { x: lx + bl, y: ly + bt, width: lw - bl - br, height: lh - bt - bb })
    : clipRect;

  // R4b (frame-geometry.ts, state/operator-pass-2026-07-26.md W2): a bordered box's own bottom
  // edge can get PINNED to a row inside its real interior (paintBorder's D1 mechanism above, when
  // an ancestor's overflow crop cuts this box short). That pin uses the box's INHERITED clipRect --
  // the SAME `clipRect` this function received, not the just-computed childClipRect -- so this must
  // reuse the identical calculation to guarantee agreement. Without this, a bordered box whose own
  // height resolves via "auto" content-sum (unaware of the ancestor crop) hands its children a
  // clip bounded only by ITS OWN full natural interior, and a content row landing exactly on the
  // pinned border row was still "visible" by that separate check -- painted onto the identical
  // cell the border claims. Reserving the pinned row exclusively for the border (children clip
  // stops one row above it) is the fix; a no-op when no ancestor crop is pinning anything (the
  // pinned row then equals the box's own natural bottom, already excluded by the border inset).
  if (node.borderStyle) {
    const pinnedBottom = pinnedBorderBottomRow(ly, lh, clipRect);
    const clippedBottom = Math.min(childClipRect.y + childClipRect.height, pinnedBottom);
    childClipRect = { ...childClipRect, height: Math.max(0, clippedBottom - childClipRect.y) };
  }

  // Recurse into children
  for (const child of node.children) {
    renderNodeToTarget(child, target, lx, ly, childClipRect);
  }
}

/** Render directly into a reusable Frame without materializing or reparsing a full-frame ANSI
 * string. The returned byte count is diagnostic-only and mirrors the legacy oracle's stream size. */
export function renderNodeToFrame(
  node: RenderNode,
  frame: Frame,
  x: number,
  y: number,
  clipRect: ClipRect,
  stylePool: StylePool,
  scratch: FrameParseScratch,
  target: FrameRenderTarget = new FrameRenderTarget(stylePool, scratch),
): number {
  target.begin(frame);
  renderNodeToTarget(node, target, x, y, clipRect);
  return target.renderedByteLength;
}

/** Intersects two clip rectangles; an empty (non-overlapping) result has width/height clamped
 *  to 0 rather than going negative, so downstream `>=`/`<` bounds checks correctly exclude
 *  everything instead of wrapping into a bogus positive range. */
export function intersectClipRect(a: ClipRect, b: ClipRect): ClipRect {
  const x0 = Math.max(a.x, b.x);
  const y0 = Math.max(a.y, b.y);
  const x1 = Math.min(a.x + a.width, b.x + b.width);
  const y1 = Math.min(a.y + a.height, b.y + b.height);
  return { x: x0, y: y0, width: Math.max(0, x1 - x0), height: Math.max(0, y1 - y0) };
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

export interface Run {
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

/** Serializes optimized patch runs without allocating a temporary Output for every changed cell. */
export function serializePatchRuns(
  runs: readonly Run[],
  stylePool: StylePool,
  hyperlinkPool: HyperlinkPool,
  geometryChanged: boolean,
): string {
  let buf = geometryChanged ? "\x1b[2J\x1b[H" : "";
  if (runs.length === 0) return buf;

  const sgrOutput = new Output(stylePool, hyperlinkPool);
  let prevStyleRef: StyleRef = 0;
  for (const run of runs) {
    buf += cursorPosition(run.row + 1, run.startCol + 1);
    for (const cell of run.cells) {
      const style = stylePool.lookup(cell.styleRef);
      const prevStyle = stylePool.lookup(prevStyleRef);
      sgrOutput.writeSGR(style, prevStyle);
      buf += sgrOutput.flush();
      buf += cell.char;
      prevStyleRef = cell.styleRef;
    }
  }
  // issue #310: every non-empty patch is self-terminating so the next render starts from the
  // default terminal style assumed by prevStyleRef=0.
  return buf + "\x1b[m";
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

/**
 * Returns a blank frame for the requested geometry. A matching frame is cleared in place so the
 * renderer can alternate two screen buffers instead of allocating width*height cell objects on
 * every clock/telemetry repaint.
 */
export function prepareFrame(reusable: Frame | null, width: number, height: number): Frame {
  if (!reusable || reusable.width !== width || reusable.height !== height) {
    return buildFrame(width, height);
  }
  for (const row of reusable.cells) {
    for (const cell of row) {
      cell.char = " ";
      cell.width = 1;
      cell.styleRef = 0;
      cell.hyperlinkId = null;
    }
  }
  return reusable;
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

export interface RendererStream {
  write(s: string): boolean | void;
  once?(event: "drain", listener: () => void): unknown;
}

export interface RendererOptions {
  stream: RendererStream;
  stdout: { columns: number; rows: number };
  debug?: boolean;
  /** Called exactly once, after this renderer writes its first non-empty frame. */
  onFirstFrameFlushed?: () => void;
  /** Receives failures from the drain-triggered repaint, which runs outside React's commit. */
  onError?: (error: unknown) => void;
  /** Test-only injection point: supply the same pool instance a test already holds a reference
   *  to, so it can observe .size()/call .reset() directly instead of inferring pool state from
   *  rendered bytes. Production callers never pass these -- omitting them preserves the exact
   *  prior behavior (a fresh, renderer-owned pool). */
  stylePool?: StylePool;
  hyperlinkPool?: HyperlinkPool;
  /** Optional #898 diagnostic sink. It only observes counters and never wraps stdout. */
  diagnostic?: RendererDiagnostic;
  /** Optional #898 post-GC attribution sink. Environment-absent production omits it. */
  heapAttributionDiagnostic?: HeapAttributionDiagnostic;
}

export interface Renderer {
  render(rootNode: RenderNode): void;
  unmount(): void;
  clear(): void;
}

/** issue #1455 self-limit: hard ceiling on distinct interned styles/hyperlinks a renderer
 *  retains before StylePool.reset()/HyperlinkPool.reset() sheds it and forces a full repaint.
 *  4096 is generous headroom above any bounded terminal palette this cockpit actually paints
 *  (a handful of named colors + a handful of true-color values) -- normal operation never
 *  approaches it, so this never fires in the common case and only bounds the pathological one. */
export const STYLE_POOL_CAP = 4096;
export const HYPERLINK_POOL_CAP = 4096;

/** Creates a stateful double-buffered renderer. */
export function createRenderer(options: RendererOptions): Renderer {
  const { stream, stdout } = options;
  const stylePool    = options.stylePool    ?? new StylePool();
  const hyperlinkPool = options.hyperlinkPool ?? new HyperlinkPool();
  const diagnostic = options.diagnostic;
  const heapAttributionDiagnostic = options.heapAttributionDiagnostic;
  const frameParseScratch = createFrameParseScratch();
  // issue #898: the cockpit hot path writes directly into the reusable frame. The legacy
  // Output+parse route remains exported as a differential-test oracle only.
  const frameRenderTarget = new FrameRenderTarget(stylePool, frameParseScratch);

  let prevFrame: Frame | null = null;
  let spareFrame: Frame | null = null;
  let firstFrameFlushed = false;
  // issue #898: Node accepts the chunk that makes write() return false, but callers must not
  // enqueue another chunk until "drain". While that chunk owns the native queue, coalesce all
  // later React commits by doing no rendering work. The drain callback bypasses the stale diff
  // and repaints the full latest tree, because the terminal never observed any of those
  // suppressed intermediate frames.
  let backpressured = false;
  let forceFullRepaintAfterDrain = false;
  let pendingRootNode: RenderNode | null = null;
  // issue #286: the diff in diffFrames() only ever iterates curr's own width/height, so on a
  // resize to SMALLER dimensions, cells the previous (larger) frame held outside the new bounds
  // are never targeted by any patch -- they're simply never mentioned again. That's fine on a
  // real terminal ONLY if the terminal itself guarantees those cells are gone; ConPTY (and,
  // per the operator's own screenshots, real terminals too) can reflow/carry old wide-frame
  // content into rows the new narrower frame never touches, leaving stale fragments (this is
  // exactly the "stray border fragment" / "disconnected header" class of defect). Tracking the
  // last-painted width/height and forcing a full clear + full repaint (bypass the diff entirely)
  // the moment either changes guarantees no off-frame leftovers survive a live resize.
  let prevW = -1;
  let prevH = -1;

  const renderer: Renderer = {
    render(rootNode: RenderNode): void {
      diagnostic?.recordRenderCall(backpressured);
      if (backpressured) {
        pendingRootNode = rootNode;
        diagnostic?.maybeEmit(stylePool.size(), hyperlinkPool.size());
        return;
      }

      const w = stdout.columns;
      const h = stdout.rows;
      let geometryChanged = forceFullRepaintAfterDrain || w !== prevW || h !== prevH;
      prevW = w;
      prevH = h;

      // issue #1455: StylePool/HyperlinkPool are intern-only for this renderer's entire process
      // lifetime (see StylePool.reset()'s comment for why that is otherwise unbounded). A cap
      // breach resets both pools and is treated EXACTLY like a geometry change -- prevFrame's
      // cells hold styleRef/hyperlinkId indices into the pool about to be cleared, and diffFrames
      // compares those as raw index equality (never dereferenced), so diffing against them after
      // a reset could silently skip a cell whose visual style actually changed just because its
      // stale index happens to collide with a freshly-reused one. Forcing the same bypass-the-diff
      // full-repaint path already proven correct for resizes is the only reset that can't produce
      // that bug. This never fires for a bounded terminal palette -- it exists for the caller that
      // isn't one.
      if (stylePool.size() > STYLE_POOL_CAP || hyperlinkPool.size() > HYPERLINK_POOL_CAP) {
        stylePool.reset();
        hyperlinkPool.reset();
        frameRenderTarget.resetStyleCache();
        geometryChanged = true;
      }

      const clipRect: ClipRect = { x: 0, y: 0, width: w, height: h };

      // Run layout
      calculateLayoutWithText(rootNode, w, h);

      const frame = prepareFrame(spareFrame, w, h);
      const renderedBytes = renderNodeToFrame(
        rootNode,
        frame,
        0,
        0,
        clipRect,
        stylePool,
        frameParseScratch,
        frameRenderTarget,
      );

      // Diff -- force a full repaint (nothing carried from prevFrame) on any geometry change,
      // so a shrink never leaves stale off-frame content unaddressed.
      const previousFrame = prevFrame;
      const patch = diffFrames(geometryChanged ? null : previousFrame, frame);
      const runs  = optimizePatch(patch);

      diagnostic?.recordRenderPass({
        fullRepaint: geometryChanged,
        renderedFrameUtf8Bytes: renderedBytes,
        diffCells: patch.changes.length,
        optimizedRuns: runs.length,
      });

      // Write minimal output -- clear-screen first on a geometry change so any terminal-side
      // reflow of the previous (differently-sized) frame's content can't leave visible remnants
      // outside the cells this frame's diff will actually (re)write.
      const buf = serializePatchRuns(runs, stylePool, hyperlinkPool, geometryChanged);
      // issue #310: serializePatchRuns' unconditional trailing reset ensures the real terminal is
      // always left in a default state at the end of each patch write. Without this, a
      // non-default style (e.g.
      // the cursor's inverse) painted as the last cell in a patch leaves the terminal inverted;
      // the NEXT render() call assumes prevStyleRef=0 (empty state) but the terminal is actually
      // non-empty, so plain content needing no SGR is written without SGR and inherits the
      // stale inverse. The reset makes each patch self-terminating, breaking the cross-patch leak.
      heapAttributionDiagnostic?.recordRenderPass({
        frameWidth: w,
        frameHeight: h,
        frameCellCount: w * h,
        patchChanges: patch.changes.length,
        optimizedRuns: runs.length,
        renderedBytes,
        patchBufferBytes: Buffer.byteLength(buf),
        stylePoolSize: stylePool.size(),
        hyperlinkPoolSize: hyperlinkPool.size(),
      });
      if (buf) {
        const accepted = stream.write(buf);
        diagnostic?.recordStreamWrite(Buffer.byteLength(buf), accepted !== false);
        forceFullRepaintAfterDrain = false;
        if (accepted === false) {
          if (typeof stream.once !== "function") {
            throw new Error("renderer stream returned false without a drain listener");
          }
          backpressured = true;
          pendingRootNode = rootNode;
          try {
            stream.once("drain", () => {
              const latestRootNode = pendingRootNode;
              pendingRootNode = null;
              backpressured = false;
              forceFullRepaintAfterDrain = true;
              if (latestRootNode !== null) {
                try {
                  diagnostic?.recordDrainRepaint();
                  renderer.render(latestRootNode);
                } catch (error) {
                  if (options.onError === undefined) throw error;
                  options.onError(error);
                }
              }
            });
          } catch (error) {
            backpressured = false;
            throw error;
          }
        }
        if (!firstFrameFlushed) {
          firstFrameFlushed = true;
          options.onFirstFrameFlushed?.();
        }
      }

      prevFrame = frame;
      spareFrame = previousFrame?.width === w && previousFrame.height === h
        ? previousFrame
        : null;
      diagnostic?.maybeEmit(stylePool.size(), hyperlinkPool.size());
    },

    unmount(): void {
      backpressured = false;
      forceFullRepaintAfterDrain = false;
      pendingRootNode = null;
      prevFrame = null;
      spareFrame = null;
      diagnostic?.close();
      heapAttributionDiagnostic?.close();
    },

    clear(): void {
      prevFrame = null;
      spareFrame = null;
    },
  };
  return renderer;
}

// ---------------------------------------------------------------------------
// parseRenderedIntoFrame — extract cells from a rendered terminal sequence
// ---------------------------------------------------------------------------

/** Renderer-lifetime scratch for CSI numeric parameters. */
export interface FrameParseScratch {
  readonly codes: number[];
}

export function createFrameParseScratch(): FrameParseScratch {
  return { codes: [] };
}

function csiParam(
  rendered: string,
  start: number,
  end: number,
  ordinal: number,
  fallback: number,
): number {
  let currentOrdinal = 0;
  let value = 0;
  let hasDigit = false;
  let stopped = false;
  for (let i = start; i <= end; i += 1) {
    const code = i < end ? rendered.charCodeAt(i) : 59;
    if (code === 59) {
      if (currentOrdinal === ordinal) return hasDigit ? value : fallback;
      currentOrdinal += 1;
      value = 0;
      hasDigit = false;
      stopped = false;
    } else if (!stopped && code >= 48 && code <= 57) {
      value = value * 10 + code - 48;
      hasDigit = true;
    } else {
      stopped = true;
    }
  }
  return fallback;
}

function fillCsiCodes(rendered: string, start: number, end: number, codes: number[]): void {
  codes.length = 0;
  let value = 0;
  let hasDigit = false;
  let stopped = false;
  for (let i = start; i <= end; i += 1) {
    const code = i < end ? rendered.charCodeAt(i) : 59;
    if (code === 59) {
      codes.push(hasDigit ? value : Number.NaN);
      value = 0;
      hasDigit = false;
      stopped = false;
    } else if (!stopped && code >= 48 && code <= 57) {
      value = value * 10 + code - 48;
      hasDigit = true;
    } else {
      stopped = true;
    }
  }
}

export function parseRenderedIntoFrame(
  rendered: string,
  frame: Frame,
  stylePool: StylePool,
  scratch: FrameParseScratch = createFrameParseScratch(),
  startRow = 0,
  startCol = 0,
  startStyleRef: StyleRef = 0,
): StyleRef {
  // Parse cursor-position + SGR + text sequences
  let pos = 0;
  let curRow = startRow;
  let curCol = startCol;
  let currentStyleRef: StyleRef = startStyleRef;

  while (pos < rendered.length) {
    if (rendered[pos] === "\x1b" && rendered[pos + 1] === "[") {
      // CSI sequence
      pos += 2;
      const paramsStart = pos;
      while (pos < rendered.length) {
        const code = rendered.charCodeAt(pos);
        if (code >= 0x40 && code <= 0x7e) break;
        pos += 1;
      }
      const paramsEnd = pos;
      const final = rendered[pos] ?? "";
      pos++;

      if (final === "H") {
        // cursorPosition
        curRow = Math.max(0, (csiParam(rendered, paramsStart, paramsEnd, 0, 1) || 1) - 1);
        curCol = Math.max(0, (csiParam(rendered, paramsStart, paramsEnd, 1, 1) || 1) - 1);
      } else if (final === "m") {
        // SGR
        if (paramsStart === paramsEnd
            || (paramsEnd === paramsStart + 1 && rendered.charCodeAt(paramsStart) === 48)) {
          currentStyleRef = 0;
        } else {
          // Parse SGR codes back to style
          fillCsiCodes(rendered, paramsStart, paramsEnd, scratch.codes);
          const style = applyAnsiCodes(scratch.codes, stylePool.lookup(currentStyleRef));
          currentStyleRef = stylePool.intern(style);
        }
      }
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
  return currentStyleRef;
}
