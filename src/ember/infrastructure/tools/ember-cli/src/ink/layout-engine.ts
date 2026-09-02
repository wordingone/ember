// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// layout-engine — pure TypeScript flexbox adapter.
// Implements the LayoutNode interface the renderer uses; abstracts away
// the underlying layout engine (spec says Yoga WASM; we implement an
// equivalent minimal flexbox in pure TS so no WASM binding is needed).

// ---------------------------------------------------------------------------
// Geometry types (plain data objects — interop contract)
// ---------------------------------------------------------------------------

export interface Point     { x: number; y: number; }
export interface Size      { width: number; height: number; }
export interface Rectangle { x: number; y: number; width: number; height: number; }
export interface Edges     { top: number; right: number; bottom: number; left: number; }

// ---------------------------------------------------------------------------
// Flex enums
// ---------------------------------------------------------------------------

export type FlexDirection    = "row" | "column" | "rowReverse" | "columnReverse";
export type FlexWrap         = "noWrap" | "wrap" | "wrapReverse";
export type JustifyContent   = "flexStart" | "center" | "flexEnd" | "spaceBetween" | "spaceAround" | "spaceEvenly";
export type AlignItems       = "stretch" | "flexStart" | "center" | "flexEnd" | "baseline";
export type AlignContent     = AlignItems;
export type AlignSelf        = AlignItems | "auto";
export type PositionType     = "relative" | "absolute";
export type Display          = "flex" | "none";
export type Overflow         = "visible" | "hidden" | "scroll";

export type SizeValue = number | "auto" | `${number}%`;

// ---------------------------------------------------------------------------
// LayoutNode interface (interop — preserve exactly)
// ---------------------------------------------------------------------------

export interface LayoutNode {
  // Hierarchy
  appendChild(child: LayoutNode): void;
  insertBefore(child: LayoutNode, before: LayoutNode): void;
  removeChild(child: LayoutNode): void;
  getChildCount(): number;
  getChild(index: number): LayoutNode;

  // Flex container properties
  flexDirection: FlexDirection;
  flexWrap: FlexWrap;
  justifyContent: JustifyContent;
  alignItems: AlignItems;
  alignContent: AlignContent;
  alignSelf: AlignSelf;
  gap: number;
  rowGap: number;
  columnGap: number;

  // Sizing
  width: SizeValue;
  height: SizeValue;
  minWidth: SizeValue;
  maxWidth: SizeValue;
  minHeight: SizeValue;
  maxHeight: SizeValue;
  flexGrow: number;
  flexShrink: number;
  flexBasis: SizeValue;

  // Spacing
  padding: number;
  paddingTop: number;
  paddingRight: number;
  paddingBottom: number;
  paddingLeft: number;
  margin: number;
  marginTop: number | "auto";
  marginRight: number | "auto";
  marginBottom: number | "auto";
  marginLeft: number | "auto";
  border: number;
  borderTop: number;
  borderRight: number;
  borderBottom: number;
  borderLeft: number;

  // Position
  positionType: PositionType;
  top: SizeValue;
  right: SizeValue;
  bottom: SizeValue;
  left: SizeValue;

  // Display
  display: Display;
  overflow: Overflow;

  // Layout results (read after calculateLayout)
  computedLeft: number;
  computedTop: number;
  computedWidth: number;
  computedHeight: number;
  computedPadding: Edges;
  computedBorder: Edges;
  computedMargin: Edges;
  hasNewLayout: boolean;

  // Compute
  calculateLayout(width: number | undefined, height: number | undefined, direction: "ltr" | "rtl"): void;

  /** Free underlying resources. After free(), the node must not be used. */
  free(): void;
}

// ---------------------------------------------------------------------------
// Internal node implementation
// ---------------------------------------------------------------------------

function resolveSize(v: SizeValue, parentSize: number): number {
  if (v === "auto") return 0;
  if (typeof v === "string" && v.endsWith("%")) {
    return Math.floor(parseFloat(v) * parentSize / 100);
  }
  return typeof v === "number" ? v : 0;
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

class FlexNode implements LayoutNode {
  private _children: FlexNode[] = [];
  private _freed = false;

  // --- layout properties ---
  flexDirection:  FlexDirection  = "row";
  flexWrap:       FlexWrap       = "noWrap";
  justifyContent: JustifyContent = "flexStart";
  alignItems:     AlignItems     = "stretch";
  alignContent:   AlignContent   = "flexStart";
  alignSelf:      AlignSelf      = "auto";
  gap        = 0;
  rowGap     = 0;
  columnGap  = 0;

  width:     SizeValue = "auto";
  height:    SizeValue = "auto";
  minWidth:  SizeValue = 0;
  maxWidth:  SizeValue = Infinity;
  minHeight: SizeValue = 0;
  maxHeight: SizeValue = Infinity;
  flexGrow   = 0;
  flexShrink = 1;
  flexBasis: SizeValue = "auto";

  padding       = 0;
  paddingTop    = 0;
  paddingRight  = 0;
  paddingBottom = 0;
  paddingLeft   = 0;
  margin: number       = 0;
  marginTop:    number | "auto" = 0;
  marginRight:  number | "auto" = 0;
  marginBottom: number | "auto" = 0;
  marginLeft:   number | "auto" = 0;
  border       = 0;
  borderTop    = 0;
  borderRight  = 0;
  borderBottom = 0;
  borderLeft   = 0;

  positionType: PositionType = "relative";
  top:   SizeValue = 0;
  right: SizeValue = 0;
  bottom: SizeValue = 0;
  left:  SizeValue = 0;

  display:  Display  = "flex";
  overflow: Overflow = "visible";

  // --- computed results ---
  computedLeft   = 0;
  computedTop    = 0;
  computedWidth  = 0;
  computedHeight = 0;
  computedPadding: Edges = { top: 0, right: 0, bottom: 0, left: 0 };
  computedBorder:  Edges = { top: 0, right: 0, bottom: 0, left: 0 };
  computedMargin:  Edges = { top: 0, right: 0, bottom: 0, left: 0 };
  hasNewLayout = false;

  // ---------------------------------------------------------------------------
  // Hierarchy
  // ---------------------------------------------------------------------------

  appendChild(child: LayoutNode): void {
    if (this._freed) throw new Error("appendChild on freed node");
    const c = child as FlexNode;
    if (!this._children.includes(c)) this._children.push(c);
  }

  insertBefore(child: LayoutNode, before: LayoutNode): void {
    const idx = this._children.indexOf(before as FlexNode);
    const c = child as FlexNode;
    if (idx < 0) { this._children.push(c); return; }
    this._children.splice(idx, 0, c);
  }

  removeChild(child: LayoutNode): void {
    const idx = this._children.indexOf(child as FlexNode);
    if (idx >= 0) {
      this._children.splice(idx, 1);
      (child as FlexNode).free();
    }
  }

  getChildCount(): number { return this._children.length; }
  getChild(index: number): LayoutNode {
    const c = this._children[index];
    if (!c) throw new Error(`No child at index ${index}`);
    return c;
  }

  free(): void { this._freed = true; }

  // ---------------------------------------------------------------------------
  // calculateLayout — resolves all descendant geometry
  // ---------------------------------------------------------------------------

  calculateLayout(
    width: number | undefined,
    height: number | undefined,
    _direction: "ltr" | "rtl",
  ): void {
    const availW = width  ?? 0;
    const availH = height ?? 0;
    // Root-freeze fix (#114): mountInk seeds this.width/this.height once, at mount, from
    // whatever the terminal size was at that instant (a plain number, never "auto"). Every
    // later call here passes the LIVE terminal size as width/height -- but _layout()'s own
    // self-size resolution is `this.width === "auto" ? availW : resolveSize(this.width, rootW)`,
    // so once this.width is a definite (non-"auto") number it wins over the live argument
    // FOREVER, and that frozen number is also `rootW` for the whole descendant tree (any
    // percentage-width node resolves against it). The renderer's own live-getter stdout and
    // the resize-driven paint/clear logic (rendering-pipeline.ts) were both already correct;
    // only the actual computed geometry stayed pinned at boot size. calculateLayout's width/
    // height parameters are the authoritative live size for a top-level call (this is the only
    // place a tree gets laid out from the real root), so they must always overwrite the root's
    // stored style, exactly like Yoga's YGNodeCalculateLayout(root, width, height, dir) treats
    // its arguments as authoritative regardless of the root node's own style.
    this.width  = availW;
    this.height = availH;
    // Capture root's prev BEFORE layout so _markNewLayout sees the right baseline.
    const prev = { w: this.computedWidth, h: this.computedHeight,
                   l: this.computedLeft, t: this.computedTop };
    this._layout(availW, availH, availW, availH);
    // Mark root hasNewLayout after the full tree has settled (including all cross-aligns).
    this._markNewLayout(prev);
  }

  _layout(availW: number, availH: number, rootW: number, rootH: number): void {
    // display:none — zero out geometry; caller (parent positioning loop or
    // calculateLayout) will call _markNewLayout with the correct prev values.
    if (this.display === "none") {
      this.computedWidth = 0; this.computedHeight = 0;
      this.computedLeft = 0;  this.computedTop = 0;
      return;
    }

    // Resolve self size
    const selfW = this.width === "auto" ? availW : resolveSize(this.width, rootW);
    const selfH = this.height === "auto" ? availH : resolveSize(this.height, rootH);

    // Resolve padding / border
    const pt = this.paddingTop    || this.padding;
    const pr = this.paddingRight  || this.padding;
    const pb = this.paddingBottom || this.padding;
    const pl = this.paddingLeft   || this.padding;
    const bt = this.borderTop    || this.border;
    const br = this.borderRight  || this.border;
    const bb = this.borderBottom || this.border;
    const bl = this.borderLeft   || this.border;
    this.computedPadding = { top: pt, right: pr, bottom: pb, left: pl };
    this.computedBorder  = { top: bt, right: br, bottom: bb, left: bl };
    const mt = typeof this.marginTop    === "number" ? this.marginTop    : 0;
    const mr = typeof this.marginRight  === "number" ? this.marginRight  : 0;
    const mb = typeof this.marginBottom === "number" ? this.marginBottom : 0;
    const ml = typeof this.marginLeft   === "number" ? this.marginLeft   : 0;
    this.computedMargin = { top: mt, right: mr, bottom: mb, left: ml };

    // Inner content area
    const innerW = selfW - pl - pr - bl - br;
    const innerH = selfH - pt - pb - bt - bb;

    // Layout children
    const isRow = this.flexDirection === "row" || this.flexDirection === "rowReverse";
    const isReverse = this.flexDirection === "rowReverse" || this.flexDirection === "columnReverse";
    const effGap = isRow ? (this.columnGap || this.gap) : (this.rowGap || this.gap);
    const visibleChildren = this._children.filter(c => c.display !== "none");

    // Capture each child's geometry BEFORE layout so _markNewLayout can compare
    // against pre-layout values AFTER cross-align has been applied.
    // (Without this deferral, _markNewLayout inside child._layout would compare
    // against stale stretched values from the previous pass.)
    const childPrevMap = new Map<FlexNode, { w: number; h: number; l: number; t: number }>();
    for (const child of visibleChildren) {
      childPrevMap.set(child, { w: child.computedWidth, h: child.computedHeight,
                                 l: child.computedLeft, t: child.computedTop });
    }

    // First pass: layout each child with available inner space
    for (const child of visibleChildren) {
      child._layout(innerW, innerH, rootW, rootH);
    }

    // Flex main axis
    const mainSize  = isRow ? innerW : innerH;
    const baseSizes = visibleChildren.map(c => isRow ? c.computedWidth : c.computedHeight);
    const totalBase = baseSizes.reduce((a, b) => a + b, 0) +
                      Math.max(0, visibleChildren.length - 1) * effGap;
    let freeSpace   = mainSize - totalBase;

    // Distribute flexGrow
    if (freeSpace > 0) {
      const totalGrow = visibleChildren.reduce((s, c) => s + c.flexGrow, 0);
      if (totalGrow > 0) {
        for (const child of visibleChildren) {
          if (child.flexGrow > 0) {
            const extra = Math.floor(freeSpace * child.flexGrow / totalGrow);
            if (isRow) child.computedWidth  += extra;
            else       child.computedHeight += extra;
          }
        }
      }
    }

    // Shrink: when children overflow a DEFINITE main size, clamp using each child's OWN
    // flexShrink weight (real CSS flex-shrink semantics: cut_i ∝ flexShrink_i * base_i).
    // B6 W4' fix: previously this cut EVERY child proportionally to its base size alone,
    // ignoring flexShrink entirely — a child explicitly marked flexShrink:0 (e.g. a status bar
    // or prompt row that must never be crushed) was shrunk right alongside its flex-grow
    // siblings whenever total content exceeded the viewport. flexShrink:0 children are now
    // excluded from the deficit pool outright; the deficit lands only on flexShrink>0 children,
    // weighted by (flexShrink * base). Every existing child defaults to flexShrink:1 (unchanged
    // field default), so for any tree where nothing opts into flexShrink:0 this reduces to
    // exactly the old plain-proportional-to-base formula — fully backward compatible.
    // Auto-sized parents are excluded — their overflow feeds content resolution.
    const mainIsDefinite = isRow ? this.width !== "auto" : this.height !== "auto";
    if (freeSpace < 0 && mainIsDefinite && totalBase > 0) {
      const deficit = -freeSpace;
      const weightedBase = visibleChildren.reduce((s, c) => {
        const base = isRow ? c.computedWidth : c.computedHeight;
        return s + (c.flexShrink > 0 ? c.flexShrink * base : 0);
      }, 0);
      if (weightedBase > 0) {
        // Running-cumulative rounding (bucket/largest-remainder style): each child's cut is the
        // DELTA between successive rounded cumulative shares, not an independently-rounded share.
        // Independent per-child rounding (the naive `Math.ceil` version this replaced) can round
        // UP on every child and overshoot the true integer deficit by several rows, leaving a
        // gap nothing occupies — exactly the "status bar lands one row short of the true last
        // row" defect this was built to catch.
        let idealCumulative = 0;
        let appliedSoFar    = 0;
        for (const child of visibleChildren) {
          if (child.flexShrink <= 0) continue;
          const base       = isRow ? child.computedWidth : child.computedHeight;
          const weight     = child.flexShrink * base;
          idealCumulative += deficit * weight / weightedBase;
          const target     = Math.round(idealCumulative);
          const cut        = Math.min(base, Math.max(0, target - appliedSoFar));
          appliedSoFar    += cut;
          if (isRow) child.computedWidth  = base - cut;
          else       child.computedHeight = base - cut;
        }
      }
    }

    // Re-layout pass for children whose main-axis size CHANGED via grow/shrink above.
    //
    // Bug (B7 item 2 re-verification, operator regrade 2026-07-03): the "first pass" loop above
    // calls child._layout(innerW, innerH, ...) using THIS node's own pre-distribution inner size
    // for EVERY child, so an "auto"-height/width child (selfH/selfW = availH/availW when
    // this.height/width === "auto", see the top of this method) measures itself against the FULL
    // undistributed space, not its true post-grow/shrink share. That child's OWN internal
    // positioning -- justify-content offset (mainSize-driven), cross-align stretch, and its own
    // "auto" self-size resolution -- was computed during that SAME single _layout() call, using
    // the stale (pre-distribution) mainSize. A flexGrow:1, auto-height, justifyContent:"flex-end"
    // container (exactly repl.ts's transcript Box, alongside flexShrink:0 siblings like the
    // prompt/status bar) anchored its child using the WRONG offset -- e.g. 39 instead of the
    // correct 35 in a 46-row transcript, a discrepancy exactly equal to the reserved sibling
    // rows the first pass didn't yet know to exclude (see bottom-anchor.test.ts's flexGrow/shrink
    // regression test). Re-invoking _layout with the child's now-FINAL main-axis size fixes its
    // internal positioning; the size restore immediately after guards against that child's own
    // "auto self-size" resolution (line ~415 below) overwriting the flex-distributed size with a
    // content-sum instead (transcript itself is "auto"-height, sized by flexGrow, not content).
    visibleChildren.forEach((child, i) => {
      const finalMain = isRow ? child.computedWidth : child.computedHeight;
      if (finalMain === baseSizes[i]) return; // untouched by grow/shrink -- first pass already correct
      const relayoutInnerW = isRow ? finalMain : innerW;
      const relayoutInnerH = isRow ? innerH : finalMain;
      child._layout(relayoutInnerW, relayoutInnerH, rootW, rootH);
      if (isRow) child.computedWidth  = finalMain;
      else       child.computedHeight = finalMain;
    });

    // Position children along main axis
    let cursor = isRow ? pl + bl : pt + bt;
    const relChildren  = visibleChildren.filter(c => c.positionType === "relative");
    const absChildren  = visibleChildren.filter(c => c.positionType === "absolute");

    // justify-content offset
    const relTotal = relChildren.reduce((s, c) => s + (isRow ? c.computedWidth : c.computedHeight), 0) +
                     Math.max(0, relChildren.length - 1) * effGap;
    const relFree  = mainSize - relTotal;
    let startOffset = 0;
    let spacing     = 0;
    switch (this.justifyContent) {
      case "center":        startOffset = Math.floor(relFree / 2); break;
      case "flexEnd":       startOffset = isReverse ? 0 : relFree; break;
      case "spaceBetween":  spacing = relChildren.length > 1 ? Math.floor(relFree / (relChildren.length - 1)) : 0; break;
      case "spaceAround":
        spacing = relChildren.length > 0 ? Math.floor(relFree / relChildren.length) : 0;
        startOffset = Math.floor(spacing / 2);
        break;
      case "spaceEvenly":
        spacing = relChildren.length > 0 ? Math.floor(relFree / (relChildren.length + 1)) : 0;
        startOffset = spacing;
        break;
      default: break;
    }
    if (isReverse && this.justifyContent === "flexStart") startOffset = relFree;
    cursor += startOffset;

    // Cross space used by stretch/align in a ROW: an auto-height row resolves its
    // cross size from CONTENT (max natural child height), never from the
    // provisional avail-based innerH — otherwise stretch blows auto-height
    // children to full screen height before the row's own auto resolution runs.
    const rowCross = (isRow && this.height === "auto")
      ? relChildren.reduce((m, c) => Math.max(m, c.computedHeight), 0)
      : innerH;

    const positionedChildren = isReverse ? [...relChildren].reverse() : relChildren;
    for (let ci = 0; ci < positionedChildren.length; ci++) {
      const child = positionedChildren[ci]!;
      if (isRow) {
        child.computedLeft = cursor;
        // align items cross-axis (may modify child.computedHeight via stretch)
        child.computedTop  = this._crossAlign(child, rowCross, pt + bt);
      } else {
        child.computedTop  = cursor;
        // align items cross-axis (may modify child.computedWidth via stretch)
        child.computedLeft = this._crossAlign(child, innerW, pl + bl);
      }
      cursor += (isRow ? child.computedWidth : child.computedHeight);
      cursor += ci < positionedChildren.length - 1 ? (effGap + spacing) : 0;
      // _markNewLayout AFTER cross-align so it sees the final stretched geometry.
      child._markNewLayout(childPrevMap.get(child)!);
    }

    // Absolute children: position relative to parent content box
    for (const child of absChildren) {
      child.computedLeft = resolveSize(child.left, selfW);
      child.computedTop  = resolveSize(child.top, selfH);
      child._markNewLayout(childPrevMap.get(child)!);
    }

    // Resolve self height when "auto" (sum children if column, max if row)
    if (this.height === "auto" && this.display === "flex") {
      if (!isRow) {
        const total = relChildren.reduce((s, c) => s + c.computedHeight, 0) +
                      Math.max(0, relChildren.length - 1) * effGap;
        this.computedHeight = total + pt + pb + bt + bb;
      } else {
        const maxH = relChildren.reduce((m, c) => Math.max(m, c.computedHeight), 0);
        this.computedHeight = maxH + pt + pb + bt + bb;
      }
    } else {
      this.computedHeight = selfH;
    }

    if (this.width === "auto" && this.display === "flex") {
      if (isRow) {
        const total = relChildren.reduce((s, c) => s + c.computedWidth, 0) +
                      Math.max(0, relChildren.length - 1) * effGap;
        this.computedWidth = total + pl + pr + bl + br;
      } else {
        const maxW = relChildren.reduce((m, c) => Math.max(m, c.computedWidth), 0);
        this.computedWidth = maxW + pl + pr + bl + br;
      }
    } else {
      this.computedWidth = selfW;
    }

    // Apply min/max constraints
    this.computedWidth  = clamp(this.computedWidth,
      resolveSize(this.minWidth, rootW), resolveSize(this.maxWidth, rootW) || Infinity);
    this.computedHeight = clamp(this.computedHeight,
      resolveSize(this.minHeight, rootH), resolveSize(this.maxHeight, rootH) || Infinity);

    // Note: _markNewLayout for THIS node is called by the parent's positioning loop,
    // or by calculateLayout for the root. Do NOT call it here.
  }

  private _crossAlign(child: FlexNode, crossSpace: number, offset: number): number {
    const isRow = this.flexDirection === "row" || this.flexDirection === "rowReverse";
    const childSize = isRow ? child.computedHeight : child.computedWidth;
    const effective = child.alignSelf !== "auto" ? child.alignSelf : this.alignItems;
    switch (effective) {
      case "center":    return offset + Math.floor((crossSpace - childSize) / 2);
      case "flexEnd":   return offset + crossSpace - childSize;
      case "stretch":
        // CSS flexbox: stretch only when the child has no explicit cross-axis size.
        // An explicit numeric or percentage value means the child already determined
        // its cross-axis extent; we must not override it.
        if (isRow) {
          if (child.height === "auto") child.computedHeight = crossSpace;
        } else {
          if (child.width === "auto") child.computedWidth = crossSpace;
        }
        return offset;
      default: return offset;
    }
  }

  private _markNewLayout(prev: { w: number; h: number; l: number; t: number }): void {
    this.hasNewLayout =
      prev.w !== this.computedWidth  ||
      prev.h !== this.computedHeight ||
      prev.l !== this.computedLeft   ||
      prev.t !== this.computedTop;
  }
}

// ---------------------------------------------------------------------------
// Factory (interop — preserve exactly)
// ---------------------------------------------------------------------------

/** Allocates a new unattached layout node with Yoga-default values. */
export function createLayoutNode(): LayoutNode {
  return new FlexNode();
}
