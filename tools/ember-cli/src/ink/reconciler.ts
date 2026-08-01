// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// reconciler — custom React→terminal renderer.
// Implements a react-reconciler HostConfig that maps React element trees
// to the ink rendering-pipeline's RenderNode graph, then drives double-buffered
// terminal output via createRenderer.

import React, { type ReactElement, type ReactNode } from "react";
import ReactReconcilerModule from "react-reconciler";
import {
  createRenderer,
  type RenderNode,
  type RenderNodeKind,
  type Renderer,
  type TextWrapMode,
} from "./rendering-pipeline.ts";
import { createLayoutNode } from "./layout-engine.ts";
import type { Style } from "./termio.ts";
import type { BorderStyleName } from "./border-glyphs.ts";
import { ClickEvent, PointerEvent, type MouseModifiers, type TerminalEvent } from "./event-system.ts";
import { _setMouseDispatcher } from "./hooks.ts";
import type { SgrMouseEvent } from "./termio.ts";

// ---------------------------------------------------------------------------
// Internal node — extends RenderNode with reconciler bookkeeping
// ---------------------------------------------------------------------------

interface InternalNode extends RenderNode {
  // text merging
  _mergedChildren?: InternalNode[];
  _mergedInto?:     InternalNode;
  // raw-ansi merging
  _rawChildren?: InternalNode[];
  _rawParent?:   InternalNode;
  _parent?: InternalNode | RootNode;
  onClick?: (event: TerminalEvent) => void;
  onMouseEnter?: (event: TerminalEvent) => void;
  onMouseMove?: (event: TerminalEvent) => void;
  onMouseLeave?: (event: TerminalEvent) => void;
  onMouseUp?: (event: TerminalEvent) => void;
  onWheel?: (event: TerminalEvent) => void;
}

interface RootNode {
  kind:     "root";
  children: InternalNode[];
  layout:   ReturnType<typeof createLayoutNode>;
}

// ---------------------------------------------------------------------------
// Container passed to createContainer
// ---------------------------------------------------------------------------

interface InkContainer {
  rootNode: RootNode;
  renderer: Renderer;
  stream:   { write(s: string): void };
  stdout:   { columns: number; rows: number };
  hoverTarget: HitTarget | null;
  leftPressSeen: boolean;
}

// ---------------------------------------------------------------------------
// CSS → flexbox enum converters (mirror the bundled transpilation)
// ---------------------------------------------------------------------------

type FlexDirCSS = string | undefined;

function cssToFlexDir(v: FlexDirCSS) {
  if (v === "column")         return "column"      as const;
  if (v === "row-reverse")    return "rowReverse"  as const;
  if (v === "column-reverse") return "columnReverse" as const;
  return "row" as const;
}

function cssToFlexWrap(v: string | undefined) {
  if (v === "wrap")         return "wrap"        as const;
  if (v === "wrap-reverse") return "wrapReverse" as const;
  return "noWrap" as const;
}

function cssToJustify(v: string | undefined) {
  if (v === "center")        return "center"       as const;
  if (v === "flex-end")      return "flexEnd"      as const;
  if (v === "space-between") return "spaceBetween" as const;
  if (v === "space-around")  return "spaceAround"  as const;
  if (v === "space-evenly")  return "spaceEvenly"  as const;
  return "flexStart" as const;
}

function cssToAlign(v: string | undefined) {
  if (v === "center")     return "center"    as const;
  if (v === "flex-end")   return "flexEnd"   as const;
  if (v === "flex-start") return "flexStart" as const;
  if (v === "baseline")   return "baseline"  as const;
  return "stretch" as const;
}

function toNum(v: unknown, fallback = 0): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const n = parseFloat(v);
    return isNaN(n) ? fallback : n;
  }
  return fallback;
}

function toSizeValue(v: unknown): number | "auto" | string {
  if (v === "auto" || v === undefined || v === null) return "auto";
  if (typeof v === "number") return v;
  if (typeof v === "string") return v;
  return "auto";
}

function applyBoxStyle(
  layout: ReturnType<typeof createLayoutNode>,
  style:  Record<string, unknown>,
): void {
  if (style["flexDirection"] !== undefined)
    layout.flexDirection = cssToFlexDir(style["flexDirection"] as string);
  if (style["flexWrap"] !== undefined)
    layout.flexWrap = cssToFlexWrap(style["flexWrap"] as string);
  if (style["justifyContent"] !== undefined)
    layout.justifyContent = cssToJustify(style["justifyContent"] as string);
  if (style["alignItems"] !== undefined)
    layout.alignItems = cssToAlign(style["alignItems"] as string);
  if (style["alignContent"] !== undefined)
    layout.alignContent = cssToAlign(style["alignContent"] as string);
  if (style["gap"] !== undefined)           layout.gap         = toNum(style["gap"]);
  if (style["rowGap"] !== undefined)        layout.rowGap      = toNum(style["rowGap"]);
  if (style["columnGap"] !== undefined)     layout.columnGap   = toNum(style["columnGap"]);
  if (style["width"] !== undefined)         layout.width       = toSizeValue(style["width"]) as ReturnType<typeof createLayoutNode>["width"];
  if (style["height"] !== undefined)        layout.height      = toSizeValue(style["height"]) as ReturnType<typeof createLayoutNode>["height"];
  if (style["minWidth"] !== undefined)      layout.minWidth    = toSizeValue(style["minWidth"]) as ReturnType<typeof createLayoutNode>["minWidth"];
  if (style["maxWidth"] !== undefined)      layout.maxWidth    = toSizeValue(style["maxWidth"]) as ReturnType<typeof createLayoutNode>["maxWidth"];
  if (style["minHeight"] !== undefined)     layout.minHeight   = toSizeValue(style["minHeight"]) as ReturnType<typeof createLayoutNode>["minHeight"];
  if (style["maxHeight"] !== undefined)     layout.maxHeight   = toSizeValue(style["maxHeight"]) as ReturnType<typeof createLayoutNode>["maxHeight"];
  if (style["flexGrow"] !== undefined)      layout.flexGrow    = toNum(style["flexGrow"]);
  if (style["flexShrink"] !== undefined)    layout.flexShrink  = toNum(style["flexShrink"]);
  if (style["flexBasis"] !== undefined)     layout.flexBasis   = toSizeValue(style["flexBasis"]) as ReturnType<typeof createLayoutNode>["flexBasis"];
  if (style["padding"] !== undefined)       layout.padding     = toNum(style["padding"]);
  if (style["paddingTop"] !== undefined)    layout.paddingTop  = toNum(style["paddingTop"]);
  if (style["paddingRight"] !== undefined)  layout.paddingRight  = toNum(style["paddingRight"]);
  if (style["paddingBottom"] !== undefined) layout.paddingBottom = toNum(style["paddingBottom"]);
  if (style["paddingLeft"] !== undefined)   layout.paddingLeft = toNum(style["paddingLeft"]);
  if (style["margin"] !== undefined)        layout.margin      = toNum(style["margin"]);
  if (style["marginTop"] !== undefined)     layout.marginTop   = toNum(style["marginTop"]);
  if (style["marginRight"] !== undefined)   layout.marginRight = toNum(style["marginRight"]);
  if (style["marginBottom"] !== undefined)  layout.marginBottom = toNum(style["marginBottom"]);
  if (style["marginLeft"] !== undefined)    layout.marginLeft  = toNum(style["marginLeft"]);
  // #561 P0-A / W4: overflow was declared on Box's props (components.ts) and on the LayoutNode
  // interface (layout-engine.ts), but never actually copied across here -- layout.overflow sat
  // at its default ("visible") forever regardless of what a caller passed, which is WHY
  // rendering-pipeline.ts's new overflow:"hidden" clip-rect enforcement had nothing to key off
  // of. This is the missing link between the two.
  if (style["overflow"] !== undefined)
    layout.overflow = style["overflow"] as ReturnType<typeof createLayoutNode>["overflow"];
}

// ---------------------------------------------------------------------------
// Node helpers
// ---------------------------------------------------------------------------

type Props = Record<string, unknown>;

function inferKind(type: string, props: Props): RenderNodeKind {
  if (props["data-raw-ansi"]) return "raw-ansi";
  if (props["data-text"])     return "text";
  if (props["data-newline"])  return "text";
  return "box";
}

function extractStyle(props: Props): Style | undefined {
  const ds = props["data-style"];
  if (typeof ds === "string") {
    try { return JSON.parse(ds) as Style; } catch { /* ignore */ }
  }
  return undefined;
}

function extractInitialText(props: Props): string | undefined {
  if (props["data-newline"]) {
    const count = typeof props["data-count"] === "number" ? props["data-count"] : 1;
    return "\n".repeat(count);
  }
  return undefined;
}

function extractTextWrap(props: Props): TextWrapMode | undefined {
  const value = props["data-text-wrap"];
  return typeof value === "string" ? value as TextWrapMode : undefined;
}

/** Extracts border intent from a Box's data-attrs onto the render node, and
 * reserves 1 layout cell per side when a borderStyle is present so children are
 * inset instead of painted under the border glyphs (B2 increment). */
function applyBorderProps(node: InternalNode, props: Props): void {
  const bs = props["data-border-style"];
  if (typeof bs === "string" && bs.length > 0) {
    node.borderStyle  = bs as BorderStyleName;
    node.layout.border = 1;
  } else {
    node.borderStyle   = undefined;
    node.layout.border = 0;
  }
  const bc = props["data-border-color"];
  node.borderColor = typeof bc === "string" ? bc : undefined;
  const bt = props["data-border-title"];
  node.borderTitle = typeof bt === "string" ? bt : undefined;
}

function makeNode(
  kind: RenderNodeKind,
  opts: Partial<InternalNode>,
): InternalNode {
  const layout = createLayoutNode();
  return { kind, children: [], layout, ...opts } as InternalNode;
}

function _stripAnsi(s: string): string {
  return s
    .replace(/\x1b\[[^A-Za-z]*[A-Za-z]/g, "")
    .replace(/\x1b\][^]*?(?:\x07|\x1b\\)/g, "")
    .replace(/\x1b./g, "");
}

// ---------------------------------------------------------------------------
// Tree mutation helpers
// ---------------------------------------------------------------------------

function _attachChild(parent: InternalNode | RootNode, child: InternalNode): void {
  child._parent = parent;
  if (parent.kind === "raw-ansi") {
    const rp = parent as InternalNode;
    if (child.kind === "text" && child.text !== undefined && !child.children.length) {
      rp.rawAnsi = (rp.rawAnsi ?? "") + child.text;
      const visual = _stripAnsi(rp.rawAnsi);
      rp.layout.width  = Math.max(visual.length, 1);
      rp.layout.height = 1;
      if (!rp._rawChildren) rp._rawChildren = [];
      rp._rawChildren.push(child);
      child._rawParent = rp;
      return;
    }
  }
  if (parent.kind === "text") {
    const mp = parent as InternalNode;
    if (child.kind === "text" && child.text !== undefined && !child.children.length) {
      if (!child.style || !Object.keys(child.style).length) {
        child.style = mp.style;
      }
      mp.text = (mp.text ?? "") + child.text;
      mp.layout.width  = mp.text.length;
      mp.layout.height = 1;
      if (!mp._mergedChildren) mp._mergedChildren = [];
      mp._mergedChildren.push(child);
      child._mergedInto = mp;
      return;
    }
  }
  const p = parent as { children: InternalNode[]; layout: ReturnType<typeof createLayoutNode> };
  if (!p.children.includes(child)) {
    p.children.push(child);
    p.layout.appendChild(child.layout);
  }
}

function _insertBefore(
  parent: InternalNode | RootNode,
  child:  InternalNode,
  before: InternalNode,
): void {
  const p = parent as { children: InternalNode[]; layout: ReturnType<typeof createLayoutNode> };
  const idx = p.children.indexOf(before);
  if (idx >= 0) {
    p.children.splice(idx, 0, child);
  } else {
    p.children.push(child);
  }
  p.layout.insertBefore(child.layout, before.layout);
}

function _detachChild(
  parent: InternalNode | RootNode,
  child:  InternalNode,
): void {
  if (child._mergedInto) {
    const owner = child._mergedInto;
    if (owner._mergedChildren) {
      owner._mergedChildren = owner._mergedChildren.filter(c => c !== child);
    }
    owner.text = (owner._mergedChildren ?? []).map(c => c.text ?? "").join("");
    child._mergedInto = undefined;
    return;
  }
  if (child._rawParent) {
    const owner = child._rawParent;
    if (owner._rawChildren) {
      owner._rawChildren = owner._rawChildren.filter(c => c !== child);
    }
    owner.rawAnsi = (owner._rawChildren ?? []).map(c => c.text ?? "").join("");
    child._rawParent = undefined;
    return;
  }
  const p = parent as { children: InternalNode[]; layout: ReturnType<typeof createLayoutNode> };
  const idx = p.children.indexOf(child);
  if (idx >= 0) p.children.splice(idx, 1);
  child._parent = undefined;
  try { p.layout.removeChild(child.layout); } catch { /* ignore */ }
}

interface HitTarget {
  node: InternalNode;
  left: number;
  top: number;
}

interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

function intersectRect(a: Rect, b: Rect): Rect {
  const x = Math.max(a.x, b.x);
  const y = Math.max(a.y, b.y);
  const right = Math.min(a.x + a.width, b.x + b.width);
  const bottom = Math.min(a.y + a.height, b.y + b.height);
  return {
    x,
    y,
    width: Math.max(0, right - x),
    height: Math.max(0, bottom - y),
  };
}

function contains(rect: Rect, col: number, row: number): boolean {
  return rect.width > 0 &&
    rect.height > 0 &&
    col >= rect.x &&
    col < rect.x + rect.width &&
    row >= rect.y &&
    row < rect.y + rect.height;
}

function hitTestNode(
  node: InternalNode,
  col: number,
  row: number,
  parentLeft: number,
  parentTop: number,
  clip: Rect,
): HitTarget | null {
  const left = parentLeft + node.layout.computedLeft;
  const top = parentTop + node.layout.computedTop;
  const rect = {
    x: left,
    y: top,
    width: node.layout.computedWidth,
    height: node.layout.computedHeight,
  };
  if (!contains(intersectRect(rect, clip), col, row)) return null;

  const childClip = node.layout.overflow === "hidden"
    ? intersectRect(clip, rect)
    : clip;
  for (let index = node.children.length - 1; index >= 0; index--) {
    const child = node.children[index] as InternalNode | undefined;
    if (!child) continue;
    const target = hitTestNode(child, col, row, left, top, childClip);
    if (target) return target;
  }

  return node.onClick || node.onMouseEnter || node.onMouseMove || node.onMouseLeave || node.onMouseUp || node.onWheel
    ? { node, left, top }
    : null;
}

function hitTest(container: InkContainer, input: SgrMouseEvent): HitTarget | null {
  const clip = {
    x: 0,
    y: 0,
    width: container.stdout.columns,
    height: container.stdout.rows,
  };
  let target: HitTarget | null = null;
  for (let index = container.rootNode.children.length - 1; index >= 0; index--) {
    const child = container.rootNode.children[index];
    if (!child) continue;
    target = hitTestNode(child, input.col, input.row, 0, 0, clip);
    if (target) break;
  }
  return target;
}

function pointerEvent(type: PointerEvent["type"], input: SgrMouseEvent, target: HitTarget, deltaY: -1 | 0 | 1 = 0): PointerEvent {
  return new PointerEvent(
    type, input.col, input.row,
    input.col - target.left, input.row - target.top,
    input.button, input.modifiers as MouseModifiers, deltaY,
  );
}

function bubble(target: HitTarget, event: PointerEvent, handler: "onMouseUp" | "onWheel"): void {
  let current: InternalNode | RootNode | undefined = target.node;
  while (current && current.kind !== "root") {
    const node = current as InternalNode;
    node[handler]?.(event);
    if (event.propagationStopped) break;
    current = node._parent;
  }
}

function dispatchClick(target: HitTarget, input: SgrMouseEvent): void {
  const event = new ClickEvent(
    input.col,
    input.row,
    input.col - target.left,
    input.row - target.top,
    false,
    input.button,
    input.modifiers as MouseModifiers,
    1,
  );
  let current: InternalNode | RootNode | undefined = target.node;
  while (current && current.kind !== "root") {
    const node = current as InternalNode;
    node.onClick?.(event);
    if (event.propagationStopped) break;
    current = node._parent;
  }
}

function dispatchMouseEvent(container: InkContainer, input: SgrMouseEvent): void {
  const target = hitTest(container, input);
  if (input.kind === "move") {
    const previous = container.hoverTarget;
    if (previous?.node !== target?.node) {
      if (previous) previous.node.onMouseLeave?.(pointerEvent("mouseleave", input, previous));
      if (target) target.node.onMouseEnter?.(pointerEvent("mouseenter", input, target));
      container.hoverTarget = target;
    }
    if (target) target.node.onMouseMove?.(pointerEvent("mousemove", input, target));
    return;
  }
  if (input.kind === "release") {
    const leftPressSeen = container.leftPressSeen;
    container.leftPressSeen = false;
    if (!target) return;
    bubble(target, pointerEvent("mouseup", input, target), "onMouseUp");
    // Windows Terminal may consume the press that activates its window while still delivering
    // the matching release after focus transfers. Treat a left-button release with no observed
    // press as the click. A press observed anywhere suppresses this fallback, preventing a drag
    // that begins outside a control and ends over it from becoming an accidental activation.
    if (input.button === 0 && !leftPressSeen) dispatchClick(target, input);
    return;
  }
  if (input.kind === "press" && input.button === 0) container.leftPressSeen = true;
  if (!target) {
    return;
  }
  if (input.kind === "wheel") {
    bubble(target, pointerEvent("wheel", input, target, input.deltaY), "onWheel");
    return;
  }
  if (input.button !== 0) return;
  dispatchClick(target, input);
}

// ---------------------------------------------------------------------------
// HostConfig
// ---------------------------------------------------------------------------

let _currentUpdatePriority = 4;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const hostConfig: any = {
  supportsMutation:   true,
  supportsPersistence: false,
  supportsHydration:  false,
  isPrimaryRenderer:  false,

  scheduleTimeout:   (fn: () => void, delay: number) => setTimeout(fn, delay),
  cancelTimeout:     (id: ReturnType<typeof setTimeout>) => clearTimeout(id),
  noTimeout:         -1,
  scheduleMicrotask: (fn: () => void) => queueMicrotask(fn),

  getRootHostContext:   (_container: InkContainer) => ({}),
  getChildHostContext:  (_parentCtx: object, _type: string, _container: InkContainer) => ({}),
  getPublicInstance:   (instance: InternalNode) => instance,

  setCurrentUpdatePriority(newPriority: number) {
    _currentUpdatePriority = newPriority;
  },
  getCurrentUpdatePriority() {
    return _currentUpdatePriority;
  },
  resolveUpdatePriority() {
    return _currentUpdatePriority;
  },

  // React 19 transition / form APIs (no-op for terminal renderer)
  NotPendingTransition: null as null,
  HostTransitionContext: React.createContext<null>(null),
  resetFormInstance(_form: unknown) {},
  requestPostPaintCallback(_callback: (time: number) => void) {},
  shouldAttemptEagerTransition(): boolean { return false; },
  trackSchedulerEvent() {},
  resolveEventType(): null  { return null; },
  resolveEventTimeStamp(): number { return Date.now(); },

  maySuspendCommit(_type: string, _props: Props): boolean { return false; },
  preloadInstance(_type: string, _props: Props): boolean  { return true; },
  startSuspendingCommit() {},
  suspendInstance(_type: string, _props: Props) {},
  waitForCommitToBeReady(): null { return null; },

  // Instance creation
  createInstance(type: string, props: Props): InternalNode {
    const kind  = inferKind(type, props);
    const style = extractStyle(props);
    const text  = extractInitialText(props);
    const node  = makeNode(kind, { style, text, textWrap: extractTextWrap(props) });
    node.onClick = typeof props["onClick"] === "function"
      ? props["onClick"] as (event: TerminalEvent) => void
      : undefined;
    for (const prop of ["onMouseEnter", "onMouseMove", "onMouseLeave", "onMouseUp", "onWheel"] as const) {
      node[prop] = typeof props[prop] === "function" ? props[prop] as (event: TerminalEvent) => void : undefined;
    }
    const s = props["style"];
    if (s && typeof s === "object") applyBoxStyle(node.layout, s as Record<string, unknown>);
    if (kind === "box") applyBorderProps(node, props);
    return node;
  },

  createTextInstance(text: string): InternalNode {
    const layout = createLayoutNode();
    layout.width  = text.length;
    layout.height = text.includes("\n")
      ? (text.match(/\n/g)?.length ?? 0) + 1
      : 1;
    return { kind: "text", children: [], layout, text };
  },

  // Child management
  appendInitialChild(parent: InternalNode, child: InternalNode) {
    _attachChild(parent, child);
  },
  appendChild(parent: InternalNode, child: InternalNode) {
    _attachChild(parent, child);
  },
  appendChildToContainer(container: InkContainer, child: InternalNode) {
    _attachChild(container.rootNode, child);
  },
  insertBefore(parent: InternalNode, child: InternalNode, beforeChild: InternalNode) {
    _insertBefore(parent, child, beforeChild);
  },
  insertInContainerBefore(
    container: InkContainer,
    child: InternalNode,
    beforeChild: InternalNode,
  ) {
    _insertBefore(container.rootNode, child, beforeChild);
  },
  removeChild(parent: InternalNode, child: InternalNode) {
    _detachChild(parent, child);
  },
  removeChildFromContainer(container: InkContainer, child: InternalNode) {
    _detachChild(container.rootNode, child);
  },
  clearContainer(container: InkContainer) {
    for (const child of [...container.rootNode.children]) {
      _detachChild(container.rootNode, child);
    }
  },

  // Update / commit
  finalizeInitialChildren(
    _instance: InternalNode,
    _type: string,
    _props: Props,
  ): boolean { return false; },

  commitUpdate(
    instance:  InternalNode,
    _type:     string,
    _prevProps: Props,
    nextProps: Props,
  ) {
    instance.onClick = typeof nextProps["onClick"] === "function"
      ? nextProps["onClick"] as (event: TerminalEvent) => void
      : undefined;
    for (const prop of ["onMouseEnter", "onMouseMove", "onMouseLeave", "onMouseUp", "onWheel"] as const) {
      instance[prop] = typeof nextProps[prop] === "function" ? nextProps[prop] as (event: TerminalEvent) => void : undefined;
    }
    const newStyle = extractStyle(nextProps);
    if (newStyle !== undefined) instance.style = newStyle;
    const newTextWrap = extractTextWrap(nextProps);
    if (newTextWrap !== undefined) instance.textWrap = newTextWrap;
    const newText = extractInitialText(nextProps);
    if (newText !== undefined) instance.text = newText;
    if (instance.kind === "raw-ansi") {
      const newRaw = typeof nextProps["children"] === "string"
        ? nextProps["children"]
        : undefined;
      if (newRaw !== undefined) instance.rawAnsi = newRaw;
    }
    const s = nextProps["style"];
    if (s && typeof s === "object") applyBoxStyle(instance.layout, s as Record<string, unknown>);
    if (instance.kind === "box") applyBorderProps(instance, nextProps);
  },

  commitTextUpdate(
    textInstance: InternalNode,
    _oldText: string,
    newText:  string,
  ) {
    textInstance.text         = newText;
    textInstance.layout.width = newText.length;
    textInstance.layout.height = newText.includes("\n")
      ? (newText.match(/\n/g)?.length ?? 0) + 1
      : 1;
    const mergedOwner = textInstance._mergedInto;
    if (mergedOwner) {
      mergedOwner.text         = (mergedOwner._mergedChildren ?? []).map(c => c.text ?? "").join("");
      mergedOwner.layout.width = mergedOwner.text.length;
    }
    const rawOwner = textInstance._rawParent;
    if (rawOwner) {
      rawOwner.rawAnsi        = (rawOwner._rawChildren ?? []).map(c => c.text ?? "").join("");
      const visual            = _stripAnsi(rawOwner.rawAnsi);
      rawOwner.layout.width   = Math.max(visual.length, 1);
      rawOwner.layout.height  = 1;
    }
  },

  commitMount(_domElement: InternalNode, _type: string, _newProps: Props) {},

  prepareForCommit(_containerInfo: InkContainer) { return null; },
  resetAfterCommit(container: InkContainer) {
    container.renderer.render(container.rootNode as unknown as RenderNode);
  },
  preparePortalMount(_containerInfo: InkContainer) {},
  shouldSetTextContent(_type: string, _props: Props): boolean { return false; },
  resetTextContent(_instance: InternalNode) {},
  hideInstance(_instance: InternalNode) {},
  hideTextInstance(_textInstance: InternalNode) {},
  unhideInstance(_instance: InternalNode, _props: Props) {},
  unhideTextInstance(_textInstance: InternalNode, _text: string) {},
  warnsIfNotActing:         false,
  afterActiveInstanceBlur:  () => {},
  beforeActiveInstanceBlur: () => {},
  detachDeletedInstance(_instance: InternalNode) {},
  getInstanceFromNode(_node: unknown): null { return null; },
  getInstanceFromScope(_scopeInstance: unknown): null { return null; },
  prepareScopeUpdate(_scopeInstance: unknown, _inst: InternalNode) {},
};

// ---------------------------------------------------------------------------
// Reconciler instance (created once at module load)
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const reconciler = (ReactReconcilerModule as any).default
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ? (ReactReconcilerModule as any).default(hostConfig)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  : (ReactReconcilerModule as any)(hostConfig);

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Handle returned by mountInk; allows updates and unmounting. */
export interface MountHandle {
  /** Re-render the tree with a new root element. */
  update(newElement: ReactElement): void;
  /** Unmount the tree and clean up the renderer. */
  unmount(): void;
  /** The ink container (for advanced use). */
  container: InkContainer;
}

export interface MountOptions {
  stream: { write(s: string): void };
  stdout: { columns: number; rows: number };
  debug?: boolean;
  onFirstFrameFlushed?: () => void;
  /** Fatal render/reconciliation error. Callers owning terminal modes must tear them down here. */
  onError?: (error: Error) => void;
}

/**
 * Mounts a React element into a terminal renderer.
 * Returns a MountHandle for updates and teardown.
 */
export function mountInk(element: ReactElement, options: MountOptions): MountHandle {
  const rootNode: RootNode = {
    kind:     "root",
    children: [],
    layout:   createLayoutNode(),
  };
  rootNode.layout.width         = options.stdout.columns;
  rootNode.layout.height        = options.stdout.rows;
  rootNode.layout.flexDirection = "column";

  const renderer = createRenderer({
    stream: options.stream,
    stdout: options.stdout,
    debug:  options.debug,
    onFirstFrameFlushed: options.onFirstFrameFlushed,
  });

  const container: InkContainer = {
    rootNode,
    renderer,
    stream: options.stream,
    stdout: options.stdout,
    hoverTarget: null,
    leftPressSeen: false,
  };

  let renderError: Error | null = null;
  const reportRenderError = (error: unknown): void => {
    const normalized = error instanceof Error ? error : new Error(String(error));
    if (renderError === null) {
      renderError = normalized;
      options.onError?.(normalized);
    }
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rec = reconciler as any;
  const root = rec.createContainer(
    container,
    0,    // LegacyRoot
    null, // hydrationCallbacks
    false, // isStrictMode
    null,  // concurrentUpdatesByDefaultOverride
    "",    // identifierPrefix
    (error: Error) => reportRenderError(error),   // onUncaughtError
    (_error: Error) => {},                       // onCaughtError (an ErrorBoundary still owns the tree)
    (_error: Error) => {},                       // onRecoverableError (React repaired the tree)
    () => {},              // onDefaultTransitionIndicator
  );

  function _syncRender(el: ReactNode): void {
    renderError = null;
    try {
      if (
        typeof rec.updateContainerSync === "function" &&
        typeof rec.flushSyncWork === "function"
      ) {
        rec.updateContainerSync(el, root, null, null);
        rec.flushSyncWork();
        if (typeof rec.flushPassiveEffects === "function") {
          rec.flushPassiveEffects();
        }
      } else {
        rec.updateContainer(el, root, null, null);
      }
    } catch (error) {
      reportRenderError(error);
      throw error;
    }
    if (renderError !== null) throw renderError;
  }

  _syncRender(element);
  const removeMouseDispatcher = _setMouseDispatcher(
    (event) => dispatchMouseEvent(container, event),
  );

  return {
    update(newElement: ReactElement): void {
      _syncRender(newElement);
    },
    unmount(): void {
      removeMouseDispatcher();
      _syncRender(null);
      renderer.unmount();
    },
    container,
  };
}

/**
 * Renders an app+REPL component pair into an existing root.
 * Used by the TUI entrypoint after launchRepl resolves both modules.
 */
export function renderAndRun(
  root:          { render(element: ReactElement): void },
  AppComponent:  React.ComponentType<Record<string, unknown>>,
  REPLComponent: React.ComponentType<Record<string, unknown>>,
  combinedProps: Record<string, unknown>,
): void {
  const element = React.createElement(
    AppComponent,
    combinedProps,
    React.createElement(REPLComponent, combinedProps),
  );
  root.render(element);
}
