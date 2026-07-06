// components — React component library for terminal UIs.
// Provides Box, Text, RawAnsi, Newline, Spacer, Button, Link, AlternateScreen,
// App, ScrollBox, context providers, ErrorOverview, NoSelect.
// Renders to terminal cells via the ink rendering pipeline.

import React, { createContext, useContext, useRef, useEffect, useState, useCallback } from "react";
import type { ReactNode, CSSProperties, RefObject } from "react";
import type { Style } from "./termio.ts";
import {
  ENTER_ALT_SCREEN, EXIT_ALT_SCREEN,
  ENABLE_MOUSE_TRACKING, DISABLE_MOUSE_TRACKING,
  osc,
} from "./termio.ts";
import type { LayoutNode } from "./layout-engine.ts";
import type { TerminalEvent } from "./event-system.ts";

// ---------------------------------------------------------------------------
// Context types
// ---------------------------------------------------------------------------

export interface StdinContextValue {
  stdin: NodeJS.ReadableStream;
  setRawMode: (mode: boolean) => void;
  isRawModeSupported: boolean;
}

export interface TerminalSizeContextValue {
  columns: number;
  rows: number;
}

export interface TerminalFocusContextValue {
  isFocused: boolean;
}

export interface CursorDeclaration {
  row: number;
  col: number;
  visible: boolean;
  style?: "block" | "underline" | "bar";
}

export interface CursorDeclarationContextValue {
  declare: (cursor: CursorDeclaration | null) => void;
  current: CursorDeclaration | null;
}

export interface ClockContextValue {
  now: number;
}

// ---------------------------------------------------------------------------
// Context providers
// ---------------------------------------------------------------------------

export const StdinContext = createContext<StdinContextValue>({
  stdin: process.stdin,
  setRawMode: () => {},
  isRawModeSupported: false,
});

export const TerminalSizeContext = createContext<TerminalSizeContextValue>({
  columns: process.stdout.columns ?? 80,
  rows:    process.stdout.rows    ?? 24,
});

export const TerminalFocusContext = createContext<TerminalFocusContextValue>({
  isFocused: true,
});

export const CursorDeclarationContext = createContext<CursorDeclarationContextValue>({
  declare: () => {},
  current: null,
});

export const ClockContext = createContext<ClockContextValue>({
  now: Date.now(),
});

// ---------------------------------------------------------------------------
// AppContext — provides exit() hook
// ---------------------------------------------------------------------------

export interface AppContextValue {
  exit: (error?: Error) => void;
}

export const AppContext = createContext<AppContextValue>({
  exit: () => {},
});

// ---------------------------------------------------------------------------
// Chalk-like color resolver (minimal, maps string names to SGR codes)
// ---------------------------------------------------------------------------

const CHALK_COLORS: Record<string, Style> = {
  red:     { fg: { type: "named", index: 1 } },
  green:   { fg: { type: "named", index: 2 } },
  yellow:  { fg: { type: "named", index: 3 } },
  blue:    { fg: { type: "named", index: 4 } },
  magenta: { fg: { type: "named", index: 5 } },
  cyan:    { fg: { type: "named", index: 6 } },
  white:   { fg: { type: "named", index: 7 } },
  black:   { fg: { type: "named", index: 0 } },
  gray:    { fg: { type: "named", index: 8 } },
  grey:    { fg: { type: "named", index: 8 } },
};

function resolveColor(color: string | undefined): Style {
  if (!color) return {};
  if (color.startsWith("#")) {
    const hex = color.slice(1);
    const r = parseInt(hex.slice(0, 2), 16) || 0;
    const g = parseInt(hex.slice(2, 4), 16) || 0;
    const b = parseInt(hex.slice(4, 6), 16) || 0;
    return { fg: { type: "rgb", r, g, b } };
  }
  return CHALK_COLORS[color.toLowerCase()] ?? {};
}

function resolveBgColor(color: string | undefined): Style {
  if (!color) return {};
  if (color.startsWith("#")) {
    const hex = color.slice(1);
    const r = parseInt(hex.slice(0, 2), 16) || 0;
    const g = parseInt(hex.slice(2, 4), 16) || 0;
    const b = parseInt(hex.slice(4, 6), 16) || 0;
    return { bg: { type: "rgb", r, g, b } };
  }
  const named = CHALK_COLORS[color.toLowerCase()];
  if (named?.fg) return { bg: named.fg };
  return {};
}

// ---------------------------------------------------------------------------
// Box props
// ---------------------------------------------------------------------------

export interface BoxProps {
  // Layout
  flexDirection?: "row" | "column" | "row-reverse" | "column-reverse";
  flexWrap?: "nowrap" | "wrap" | "wrap-reverse";
  justifyContent?: "flex-start" | "center" | "flex-end" | "space-between" | "space-around" | "space-evenly";
  alignItems?: "stretch" | "flex-start" | "center" | "flex-end" | "baseline";
  alignContent?: "stretch" | "flex-start" | "center" | "flex-end" | "baseline";
  alignSelf?: "auto" | "stretch" | "flex-start" | "center" | "flex-end" | "baseline";
  gap?: number;
  rowGap?: number;
  columnGap?: number;
  width?: number | string;
  height?: number | string;
  minWidth?: number | string;
  maxWidth?: number | string;
  minHeight?: number | string;
  maxHeight?: number | string;
  flexGrow?: number;
  flexShrink?: number;
  flexBasis?: number | string;
  padding?: number;
  paddingTop?: number;
  paddingRight?: number;
  paddingBottom?: number;
  paddingLeft?: number;
  paddingX?: number;
  paddingY?: number;
  margin?: number;
  marginTop?: number;
  marginRight?: number;
  marginBottom?: number;
  marginLeft?: number;
  marginX?: number;
  marginY?: number;
  position?: "relative" | "absolute";
  top?: number | string;
  right?: number | string;
  bottom?: number | string;
  left?: number | string;
  display?: "flex" | "none";
  overflow?: "visible" | "hidden" | "scroll";

  // Visual
  borderStyle?: "single" | "double" | "round" | "bold" | "singleDouble" | "doubleSingle" | "classic";
  borderColor?: string;
  borderTopColor?: string;
  borderRightColor?: string;
  borderBottomColor?: string;
  borderLeftColor?: string;
  /** Text embedded in the top border edge (requires borderStyle). See ink/border-title.test.ts. */
  borderTitle?: string;
  backgroundColor?: string;

  // Events
  onClick?:         (event: TerminalEvent) => void;
  onFocus?:         (event: TerminalEvent) => void;
  onBlur?:          (event: TerminalEvent) => void;
  onKeyDown?:       (event: TerminalEvent) => void;
  onInput?:         (event: TerminalEvent) => void;
  onPaste?:         (event: TerminalEvent) => void;

  children?: ReactNode;
  key?: string | number;
}

// ---------------------------------------------------------------------------
// Box component
// ---------------------------------------------------------------------------

export const Box = React.forwardRef<HTMLDivElement, BoxProps>(function Box(
  { children, ...props },
  ref,
) {
  // Box renders as a <div> with flexbox style — the ink renderer maps this
  // to its layout engine when it builds the RenderNode tree.
  // For the purposes of this from-spec build, Box is a structural div.
  const style: CSSProperties = {
    display: props.display === "none" ? "none" : "flex",
    flexDirection: (props.flexDirection ?? "row") as CSSProperties["flexDirection"],
    flexWrap: (props.flexWrap ?? "nowrap") as CSSProperties["flexWrap"],
    justifyContent: (props.justifyContent ?? "flex-start") as CSSProperties["justifyContent"],
    alignItems: (props.alignItems ?? "stretch") as CSSProperties["alignItems"],
    gap: props.gap,
    rowGap: props.rowGap,
    columnGap: props.columnGap,
    width: props.width,
    height: props.height,
    minWidth: props.minWidth,
    maxWidth: props.maxWidth,
    minHeight: props.minHeight,
    maxHeight: props.maxHeight,
    flexGrow: props.flexGrow,
    flexShrink: props.flexShrink,
    flexBasis: props.flexBasis,
    padding: props.padding,
    paddingTop: props.paddingTop ?? props.paddingY,
    paddingRight: props.paddingRight ?? props.paddingX,
    paddingBottom: props.paddingBottom ?? props.paddingY,
    paddingLeft: props.paddingLeft ?? props.paddingX,
    margin: props.margin,
    marginTop: props.marginTop ?? props.marginY,
    marginRight: props.marginRight ?? props.marginX,
    marginBottom: props.marginBottom ?? props.marginY,
    marginLeft: props.marginLeft ?? props.marginX,
    position: props.position as CSSProperties["position"],
    top: props.top,
    right: props.right,
    bottom: props.bottom,
    left: props.left,
    overflow: props.overflow as CSSProperties["overflow"],
  };

  return React.createElement("div", {
    ref,
    style,
    "data-box": true,
    "data-border-style": props.borderStyle,
    "data-border-color": props.borderColor,
    "data-border-title": props.borderTitle,
    "data-background-color": props.backgroundColor,
    onClick: props.onClick as React.MouseEventHandler | undefined,
    onFocus: props.onFocus as React.FocusEventHandler | undefined,
    onBlur: props.onBlur as React.FocusEventHandler | undefined,
    onKeyDown: props.onKeyDown as React.KeyboardEventHandler | undefined,
    children,
  });
});

// ---------------------------------------------------------------------------
// Text component
// ---------------------------------------------------------------------------

export interface TextProps {
  color?: string;
  backgroundColor?: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strikethrough?: boolean;
  inverse?: boolean;
  dimColor?: boolean;
  wrap?: "wrap" | "end" | "truncate" | "truncate-end" | "truncate-middle" | "truncate-start";
  children?: ReactNode;
}

export function Text({ children, color, backgroundColor, bold, italic, underline,
                       strikethrough, inverse, dimColor }: TextProps): React.ReactElement {
  const colorStyle = resolveColor(color);
  const bgStyle    = resolveBgColor(backgroundColor);
  const style: Style = {
    ...colorStyle,
    ...bgStyle,
    bold:          bold          ?? undefined,
    italic:        italic        ?? undefined,
    underline:     underline     ?? undefined,
    strikethrough: strikethrough ?? undefined,
    inverse:       inverse       ?? undefined,
    dim:           dimColor      ?? undefined,
  };
  // Encode style as data attributes for the renderer to read
  return React.createElement("span", {
    "data-text": true,
    "data-style": JSON.stringify(style),
    style: {
      fontWeight:     bold      ? "bold"      : undefined,
      fontStyle:      italic    ? "italic"    : undefined,
      textDecoration: underline ? "underline" : strikethrough ? "line-through" : undefined,
      color:          color,
      backgroundColor: backgroundColor,
    } as CSSProperties,
    children,
  });
}

// ---------------------------------------------------------------------------
// RawAnsi component
// ---------------------------------------------------------------------------

export interface RawAnsiProps { children: string; }

export function RawAnsi({ children }: RawAnsiProps): React.ReactElement {
  return React.createElement("span", {
    "data-raw-ansi": true,
    children,
  });
}

// ---------------------------------------------------------------------------
// Newline component
// ---------------------------------------------------------------------------

export interface NewlineProps { count?: number; }

export function Newline({ count = 1 }: NewlineProps): React.ReactElement {
  return React.createElement("span", {
    "data-newline": true,
    "data-count": count,
    children: "\n".repeat(count),
  });
}

// ---------------------------------------------------------------------------
// Spacer component
// ---------------------------------------------------------------------------

export function Spacer(): React.ReactElement {
  return React.createElement(Box, { flexGrow: 1 });
}

// ---------------------------------------------------------------------------
// Button component
// ---------------------------------------------------------------------------

export interface ButtonProps extends BoxProps {
  onPress?: () => void;
  isFocused?: boolean;
}

export function Button({ onPress, isFocused, children, ...boxProps }: ButtonProps): React.ReactElement {
  // Plain arrow function — avoids useCallback dependency on React render context
  // (tests call Button({}) directly as a function; hooks would fail outside renderer).
  const handleKeyDown = (event: TerminalEvent): void => {
    const ke = event as { key?: string };
    if (ke.key === "return" || ke.key === "space") onPress?.();
  };

  return React.createElement(Box, {
    ...boxProps,
    onKeyDown: handleKeyDown,
    onClick: onPress as unknown as ((e: TerminalEvent) => void) | undefined,
    "data-focusable": true,
    "data-focused": isFocused,
    children,
  } as BoxProps & Record<string, unknown>);
}

// ---------------------------------------------------------------------------
// Link component
// ---------------------------------------------------------------------------

export interface LinkProps extends TextProps {
  url: string;
  fallback?: boolean;
}

export function Link({ url, fallback: _fallback, children, ...textProps }: LinkProps): React.ReactElement {
  return React.createElement("a", {
    "data-link": true,
    href: url,
    "data-osc8-url": url,
    children: React.createElement(Text, textProps, children),
  });
}

// ---------------------------------------------------------------------------
// AlternateScreen component
// ---------------------------------------------------------------------------

export interface AlternateScreenProps {
  enableMouseTracking?: boolean;
  children?: ReactNode;
}

export function AlternateScreen(
  { enableMouseTracking = true, children }: AlternateScreenProps,
): React.ReactElement {
  useEffect(() => {
    // On mount: ENTER_ALT_SCREEN → ENABLE_MOUSE_TRACKING
    process.stdout.write(ENTER_ALT_SCREEN);
    if (enableMouseTracking) process.stdout.write(ENABLE_MOUSE_TRACKING);
    return () => {
      // On unmount: DISABLE_MOUSE_TRACKING → EXIT_ALT_SCREEN
      if (enableMouseTracking) process.stdout.write(DISABLE_MOUSE_TRACKING);
      process.stdout.write(EXIT_ALT_SCREEN);
    };
  }, [enableMouseTracking]);

  return React.createElement(React.Fragment, null, children);
}

// ---------------------------------------------------------------------------
// ScrollBox component
// ---------------------------------------------------------------------------

export interface ScrollBoxHandle {
  scrollTo(offset: number): void;
  scrollUp(rows?: number): void;
  scrollDown(rows?: number): void;
  scrollToTop(): void;
  scrollToBottom(): void;
  getScrollPosition(): number;
  getContentHeight(): number;
  getViewportHeight(): number;
}

export interface ScrollBoxProps extends BoxProps {
  onScroll?: (position: number) => void;
}

export const ScrollBox = React.forwardRef<ScrollBoxHandle, ScrollBoxProps>(function ScrollBox(
  { onScroll, children, ...boxProps },
  ref,
) {
  const [scrollPos, setScrollPos] = useState(0);
  const contentHeightRef = useRef(0);
  const viewportHeightRef = useRef(0);

  const handle: ScrollBoxHandle = {
    scrollTo(offset) {
      const clamped = Math.max(0, Math.min(offset, contentHeightRef.current - viewportHeightRef.current));
      setScrollPos(clamped);
      onScroll?.(clamped);
    },
    scrollUp(rows = 1) { handle.scrollTo(scrollPos - rows); },
    scrollDown(rows = 1) { handle.scrollTo(scrollPos + rows); },
    scrollToTop() { handle.scrollTo(0); },
    scrollToBottom() { handle.scrollTo(contentHeightRef.current); },
    getScrollPosition() { return scrollPos; },
    getContentHeight() { return contentHeightRef.current; },
    getViewportHeight() { return viewportHeightRef.current; },
  };

  // Expose handle via ref
  React.useImperativeHandle(ref, () => handle);

  return React.createElement(Box, {
    ...boxProps,
    overflow: "hidden",
    "data-scroll-box": true,
    "data-scroll-pos": scrollPos,
    children: React.createElement("div", {
      style: { transform: `translateY(-${scrollPos}ch)` } as CSSProperties,
      children,
    }),
  } as BoxProps & Record<string, unknown>);
});

// ---------------------------------------------------------------------------
// App (root orchestrator)
// ---------------------------------------------------------------------------

export interface AppProps {
  children?: ReactNode;
  onExit?: (error?: Error) => void;
}

export function App({ children, onExit }: AppProps): React.ReactElement {
  const [columns, setColumns] = useState(process.stdout.columns ?? 80);
  const [rows,    setRows]    = useState(process.stdout.rows    ?? 24);
  const [isFocused, setIsFocused] = useState(true);
  const [now, setNow] = useState(Date.now());
  const [cursorDecl, setCursorDecl] = useState<CursorDeclaration | null>(null);

  useEffect(() => {
    const onResize = () => {
      // issue #286 root cause: on Windows, Bun's process.stdout.columns/rows (and
      // getWindowSize()) are snapshotted at stream-creation time and never refresh on their
      // own after a real console resize -- confirmed live (a minimal poll-only repro outside
      // this app never observed a change) and matches the documented Bun limitation
      // (oven-sh/bun#17803: "getWindowSize() doesn't update unless _refreshSize() is called").
      // Calling the private refresh hook first forces Bun to re-query the OS console buffer
      // size before we read columns/rows below; without it, neither the 'resize' event nor
      // this poller has a live value to read in the first place, no matter how often either
      // fires. Optional-chained + try/guarded because _refreshSize is a Bun-internal, not a
      // standard Node API -- harmless no-op if a future runtime removes it once fixed upstream.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      try { (process.stdout as any)._refreshSize?.(); } catch { /* not available; ignore */ }
      setColumns(process.stdout.columns ?? 80);
      setRows(process.stdout.rows ?? 24);
    };
    process.stdout.on("resize", onResize);

    // Bun-compiled binaries under Windows ConPTY also don't reliably emit the 'resize' event
    // itself (a real node-pty resize() call never fired it in this session's repro either), so
    // a live mid-session resize can silently never update columns/rows and the tree keeps
    // rendering at launch-time dimensions while the terminal hard-wraps the stale-width output.
    // This 250ms poller is the fallback: it re-checks the live dimensions (via onResize's own
    // refresh) on an interval and updates state only on an actual change, so the event listener
    // above still gives instant updates when it does fire, and the poller is the guarantee when
    // it doesn't. (app-resize.test.ts's second case names this exact poller.)
    const poll = setInterval(onResize, 250);
    return () => { process.stdout.off("resize", onResize); clearInterval(poll); };
  }, []);

  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, []);

  const exit = useCallback((error?: Error) => {
    onExit?.(error);
  }, [onExit]);

  const appCtx: AppContextValue = { exit };
  const sizeCtx: TerminalSizeContextValue = { columns, rows };
  const focusCtx: TerminalFocusContextValue = { isFocused };
  const clockCtx: ClockContextValue = { now };
  const cursorCtx: CursorDeclarationContextValue = {
    declare: setCursorDecl,
    current: cursorDecl,
  };

  return React.createElement(
    AppContext.Provider, { value: appCtx },
    React.createElement(TerminalSizeContext.Provider, { value: sizeCtx },
      React.createElement(TerminalFocusContext.Provider, { value: focusCtx },
        React.createElement(CursorDeclarationContext.Provider, { value: cursorCtx },
          React.createElement(ClockContext.Provider, { value: clockCtx },
            children,
          ),
        ),
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// ErrorOverview
// ---------------------------------------------------------------------------

export interface ErrorOverviewProps {
  error: Error;
  onDismiss?: () => void;
}

export function ErrorOverview({ error, onDismiss }: ErrorOverviewProps): React.ReactElement {
  return React.createElement(Box, {
    borderStyle: "single",
    borderColor: "red",
    flexDirection: "column",
    children: [
      React.createElement(Text, { key: "msg", color: "red", bold: true }, error.message),
      React.createElement(Text, { key: "stack" }, error.stack ?? ""),
      React.createElement(Text, { key: "hint", dimColor: true }, "Press Enter to dismiss"),
    ],
  });
}

// ---------------------------------------------------------------------------
// NoSelect
// ---------------------------------------------------------------------------

export interface NoSelectProps { children?: ReactNode; }

export function NoSelect({ children }: NoSelectProps): React.ReactElement {
  return React.createElement("span", {
    "data-no-select": true,
    style: { userSelect: "none" } as CSSProperties,
    children,
  });
}

// ---------------------------------------------------------------------------
// Border character sets
// ---------------------------------------------------------------------------

export const BORDER_CHARS = {
  single:       { tl: "┌", tr: "┐", bl: "└", br: "┘", h: "─", v: "│" },
  double:       { tl: "╔", tr: "╗", bl: "╚", br: "╝", h: "═", v: "║" },
  round:        { tl: "╭", tr: "╮", bl: "╰", br: "╯", h: "─", v: "│" },
  bold:         { tl: "┏", tr: "┓", bl: "┗", br: "┛", h: "━", v: "┃" },
  singleDouble: { tl: "╒", tr: "╕", bl: "╘", br: "╛", h: "═", v: "│" },
  doubleSingle: { tl: "╓", tr: "╖", bl: "╙", br: "╜", h: "─", v: "║" },
  classic:      { tl: "+", tr: "+", bl: "+", br: "+", h: "-", v: "|" },
} as const;

// ---------------------------------------------------------------------------
// Re-export termio constants components need
// ---------------------------------------------------------------------------

export { ENTER_ALT_SCREEN, EXIT_ALT_SCREEN, ENABLE_MOUSE_TRACKING, DISABLE_MOUSE_TRACKING, osc };
