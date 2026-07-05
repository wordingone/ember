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
} from "./rendering-pipeline.ts";
import { createLayoutNode } from "./layout-engine.ts";
import type { Style } from "./termio.ts";
import type { BorderStyleName } from "./border-glyphs.ts";

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
  try { p.layout.removeChild(child.layout); } catch { /* ignore */ }
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
    const node  = makeNode(kind, { style, text });
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
    const newStyle = extractStyle(nextProps);
    if (newStyle !== undefined) instance.style = newStyle;
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
  });

  const container: InkContainer = {
    rootNode,
    renderer,
    stream: options.stream,
    stdout: options.stdout,
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
    (_err: Error) => {},   // onUncaughtError
    (_err: Error) => {},   // onCaughtError
    (_err: Error) => {},   // onRecoverableError
    () => {},              // onDefaultTransitionIndicator
  );

  function _syncRender(el: ReactNode): void {
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
  }

  _syncRender(element);

  return {
    update(newElement: ReactElement): void {
      _syncRender(newElement);
    },
    unmount(): void {
      rec.updateContainer(null, root, null, null);
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
