// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// components/app-shell.ts — top-level composite shell.
// Composes the committed components into the app layout: trust gate, theme,
// session context, virtual transcript, and fullscreen pane split.
// Bundle: components/app-shell.ts (line 321041)

import React, {
  useState,
  useCallback,
  useEffect,
  useContext,
  createContext,
  memo,
} from "react";
import { join } from "path";
import { mkdir, writeFile } from "fs/promises";
import { emberStateRoot } from "../utils/ember-state-root.ts";
import { PointerEvent as InkPointerEvent } from "../ink/event-system.ts";
import { Box, Text, TerminalSizeContext } from "../ink/components.ts";
import { ThemeProvider } from "./design-system.ts";

// Re-export design-system tokens used by consumers of app-shell.
export { VISIBLE_RESULTS, DEBOUNCE_MS } from "./design-system.ts";

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

export const DEFAULT_WIDTH    = 80;
export const GITHUB_URL_LIMIT = 7250;
export const AUTO_DISMISS_MS  = 30_000;
export const TOKEN_CACHE_MAX  = 500;

/** Rows kept in the off-screen buffer beyond the viewport. */
const OFFSCREEN_FREEZE_ROWS = 5;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DebugFileOpts {
  cwd:       string;
  debugPort: number;
  pid:       number;
}

export interface TrustCtx {
  hasMcpServers:    boolean;
  hasHooks:         boolean;
  hasBashTools:     boolean;
  hasHelperScripts: boolean;
}

export interface ScrollState {
  atBottom:       boolean;
  userScrolledUp: boolean;
  messageCount:   number;
}

/** Minimal shape for messages stored in session context. */
export interface SessionMessage {
  id:   string;
  type: string;
  [key: string]: unknown;
}

/** Entry shape routed by the REPL renderer (renderMsgDispatch). Lives here as the
 *  app-shell-owned message type; repl.ts imports it from here. */
export interface MessageEntry {
  id: string;
  type: 'welcome' | 'user' | 'assistant' | 'tool_result';
  content: string;
  tool_use_id?: string;
  is_error?: boolean;
}

export interface SessionContextValue {
  sessionId:  string;
  cwd:        string;
  jsonlKey:   string;
  messages:   SessionMessage[];
  addMessage: (msg: SessionMessage) => void;
}

// ---------------------------------------------------------------------------
// Pure helpers (spec — preserve exactly)
// ---------------------------------------------------------------------------

/** Converts a cwd path to a safe filesystem key by replacing path separators. */
export function encodeCwdKey(cwd: string): string {
  return cwd.replace(/[:/\\]/g, "-");
}

/** Returns the external cockpit-state debug file paths for the given working directory. */
export function getDebugFilePaths(cwd: string): { debugPort: string; debugPid: string } {
  const dir = emberStateRoot(cwd);
  return {
    debugPort: join(dir, "debug-port"),
    debugPid:  join(dir, "debug-pid"),
  };
}

/** Writes debug-port and debug-pid into the external state root (creates it if needed). */
export async function writeDebugFiles(opts: DebugFileOpts): Promise<void> {
  const { debugPort, debugPid } = getDebugFilePaths(opts.cwd);
  const dir = emberStateRoot(opts.cwd);
  await mkdir(dir, { recursive: true });
  await writeFile(debugPort, String(opts.debugPort), "utf8");
  await writeFile(debugPid,  String(opts.pid),       "utf8");
}

/** Returns true when at least one trust-prompt condition is active. */
export function needsTrustDialog(ctx: TrustCtx): boolean {
  return ctx.hasMcpServers || ctx.hasHooks || ctx.hasBashTools || ctx.hasHelperScripts;
}

/** Splits terminal rows into message-list height and input-pane height. */
export function computePaneHeights(
  terminalRows: number,
  inputHeight:  number,
): { messageListHeight: number; inputPaneHeight: number } {
  const inputPaneHeight   = Math.max(0, inputHeight);
  const messageListHeight = Math.max(0, terminalRows - inputPaneHeight);
  return { messageListHeight, inputPaneHeight };
}

/**
 * Computes the next scroll state given the previous state, a new message
 * count, and whether the user has scrolled up.
 */
export function updateScrollState(
  current:         ScrollState,
  newMessageCount: number,
  userScrolledUp:  boolean,
): { state: ScrollState; shouldAutoScroll: boolean; showScrollIndicator: boolean } {
  const hasNewMessages      = newMessageCount > current.messageCount;
  const shouldAutoScroll    = !userScrolledUp && hasNewMessages;
  const showScrollIndicator = userScrolledUp && hasNewMessages;
  return {
    state: { atBottom: !userScrolledUp, userScrolledUp, messageCount: newMessageCount },
    shouldAutoScroll,
    showScrollIndicator,
  };
}

/**
 * React.memo comparator for OffscreenFreeze.
 * Returns true (skip update) only when both renders are fully off-screen.
 */
export function offscreenFreezeShouldSkipUpdate(
  prevIsOffscreen: boolean,
  nextIsOffscreen: boolean,
): boolean {
  return prevIsOffscreen && nextIsOffscreen;
}

// ---------------------------------------------------------------------------
// Contexts
// ---------------------------------------------------------------------------

export const SessionContext = createContext<SessionContextValue>({
  sessionId:  "",
  cwd:        "",
  jsonlKey:   "",
  messages:   [],
  addMessage: () => {},
});

/** Returns the current SessionContext value. */
export function useSession(): SessionContextValue {
  return useContext(SessionContext);
}

// ---------------------------------------------------------------------------
// OffscreenFreeze — memoised wrapper; skips re-render when fully off-screen
// ---------------------------------------------------------------------------

export const OffscreenFreeze = memo(
  function OffscreenFreezeInner({
    children,
  }: {
    children?:   React.ReactNode;
    isOffscreen?: boolean;
  }): React.ReactElement {
    return React.createElement(React.Fragment, null, children);
  },
  (
    prev: { isOffscreen?: boolean },
    next: { isOffscreen?: boolean },
  ) => offscreenFreezeShouldSkipUpdate(prev.isOffscreen ?? false, next.isOffscreen ?? false),
);

// ---------------------------------------------------------------------------
// VirtualMessageList — transcript view with off-screen freeze + scroll hint
// ---------------------------------------------------------------------------
export interface VirtualMessageWindow { start: number; end: number; offset: number }

export function virtualMessageWindow(messageCount: number, viewportRows: number, requestedOffset: number): VirtualMessageWindow {
  const count = Math.max(0, Math.floor(messageCount));
  const capacity = Math.max(1, Math.floor(viewportRows));
  const maxOffset = Math.max(0, count - capacity);
  const offset = Math.max(0, Math.min(maxOffset, Math.floor(requestedOffset)));
  const end = Math.max(0, count - offset);
  return {
    start: Math.max(0, end - capacity),
    end,
    offset,
  };
}


/** Rough rendered height of a message: wrapped lines of its text plus a header row.
 * Only bounds PageUp; layout itself never depends on it. `width` is the chat column's own width
 * (not the terminal's); the reply gutter and a little slack come off it. */
export function estimateMessageRows(msg: SessionMessage, width: number): number {
  const raw = (msg as Record<string, unknown>)["content"];
  const text = typeof raw === "string" ? raw : "";
  const w = Math.max(10, Math.floor(width) - 4);
  let rows = 1;
  for (const line of text.split("\n")) rows += Math.max(1, Math.ceil(line.length / w));
  return rows;
}

/** Estimated rows of the whole transcript. */
export function totalMessageRows(messages: readonly SessionMessage[], width: number): number {
  let total = 0;
  for (const m of messages) total += estimateMessageRows(m, width);
  return total;
}

/** Clamp a transcript row offset to what scrolling can reveal: the first message lands at the
 * top of the viewport. Past that there is nothing above it to show, only an empty screen
 * (#2381 U-PageUp), so the limit is the whole transcript minus one screenful. */
export function clampRowOffset(requested: number, messages: readonly SessionMessage[], viewportRows: number, width: number): number {
  const reachable = Math.max(0, totalMessageRows(messages, width) - Math.max(1, Math.floor(viewportRows)));
  return Math.max(0, Math.min(Math.floor(requested), reachable));
}

/** Scroll up by rows: hide the newest `rowOffset` estimated rows, trimming the
 * text of the message that straddles the cut. Bottom-anchored layout then shows
 * what was above. */
export function scrollMessagesByRows(messages: readonly SessionMessage[], rowOffset: number, width: number): SessionMessage[] {
  const out = messages.slice();
  let remaining = Math.max(0, Math.floor(rowOffset));
  while (remaining > 0 && out.length > 1) {
    const last = out[out.length - 1]!;
    const rows = estimateMessageRows(last, width);
    const raw = (last as Record<string, unknown>)["content"];
    if (rows <= remaining || typeof raw !== "string") {
      out.pop();
      remaining -= Math.min(rows, remaining);
      continue;
    }
    const lines = raw.split("\n");
    const keep = Math.max(1, lines.length - remaining);
    out[out.length - 1] = { ...last, content: lines.slice(0, keep).join("\n") } as SessionMessage;
    remaining = 0;
  }
  return out;
}

export interface VirtualMessageListProps {
  messages:      SessionMessage[];
  renderMessage: (msg: SessionMessage) => React.ReactElement | null;
  viewportRows:  number;
  /** PageUp/PageDown: rows the transcript is scrolled up from the bottom. */
  rowOffset?:    number;
  /** Terminal width, for estimating wrapped rows when scrolling by rows. */
  width?:        number;
}

export function VirtualMessageList({
  messages: allMessages,
  renderMessage,
  viewportRows,
  rowOffset = 0,
  width = 80,
}: VirtualMessageListProps): React.ReactElement {
  const messages = rowOffset > 0 ? scrollMessagesByRows(allMessages, rowOffset, width) : allMessages;
  // Scrolled to the very top: anchor the oldest message to the top edge. The estimates that got
  // us here can be a few rows off, and a bottom-anchored list that is a few rows short leaves the
  // top of the screen empty.
  const atTop = rowOffset > 0 && rowOffset >= totalMessageRows(allMessages, width) - viewportRows;
  const [scrollState, setScrollState] = useState<ScrollState>({
    atBottom:       true,
    userScrolledUp: false,
    messageCount:   messages.length,
  });
  const [showScrollIndicator, setShowScrollIndicator] = useState(false);
  const [scrollOffset, setScrollOffset] = useState(0);

  useEffect(() => {
    setScrollState((prev) => {
      const update = updateScrollState(prev, messages.length, prev.userScrolledUp);
      setShowScrollIndicator(update.showScrollIndicator);
      return update.state;
    });
  }, [messages.length]);

  const frozenThreshold = Math.max(0, messages.length - viewportRows - OFFSCREEN_FREEZE_ROWS);
  const window = virtualMessageWindow(messages.length, viewportRows, scrollOffset);
  const visibleMessages = messages.slice(window.start, window.end);

  // Column-reverse is intentional at the viewport boundary: the newest message is laid out
  // against the prompt and overflow is discarded above it. This makes clipping row-accurate
  // even when one rendered message occupies many terminal rows; message count is used only to
  // bound retained React work, never as a claim about rendered height.
  const entries = visibleMessages.map((msg, visibleIndex) => {
    const i = window.start + visibleIndex;
    return React.createElement(
      OffscreenFreeze,
      { key: msg.id, isOffscreen: i < frozenThreshold },
      renderMessage(msg),
    );
  }).reverse();

  if (atTop) {
    // A plain top-down column that fills the area it is given: the oldest message starts on the
    // first rows whatever the area's height turns out to be, so no height is assumed here.
    return React.createElement(
      Box,
      { flexDirection: "column", flexGrow: 1, minHeight: 0, overflow: "hidden" },
      React.createElement(Text, { key: "row-indicator", color: "cyan" }, "↑ top of the conversation · PageDown to return"),
      // Whole messages, not the row-trimmed list: nothing is cut, the area clips the rest.
      ...allMessages.slice(0, Math.max(1, viewportRows)).map((msg) =>
        React.createElement(OffscreenFreeze, { key: msg.id, isOffscreen: false }, renderMessage(msg))),
    );
  }

  return React.createElement(
    Box,
    {
      flexDirection: "column-reverse",
      flexGrow: 1,
      minHeight: 0,
      overflow: "hidden",
      onWheel: (event) => setScrollOffset((current) => virtualMessageWindow(
        messages.length, viewportRows, current + ((event as InkPointerEvent).deltaY < 0 ? 1 : -1),
      ).offset),
    },
    rowOffset > 0
      ? React.createElement(Text, { key: "row-indicator", color: "cyan" }, `↑ scrolled up ${rowOffset} rows · PageDown to return`)
      : null,
    ...entries,
    (showScrollIndicator || window.offset > 0)
      ? React.createElement(Text, { key: "indicator", color: "cyan" }, "↓ scroll to bottom")
      : null,
  );
}

// ---------------------------------------------------------------------------
// FullscreenLayout — two-pane split: scrollable message list + fixed input pane
// ---------------------------------------------------------------------------

export interface FullscreenLayoutProps {
  messageList:  React.ReactElement;
  promptInput:  React.ReactElement;
  inputHeight?: number;
}

export function FullscreenLayout({
  messageList,
  promptInput,
  inputHeight = 3,
}: FullscreenLayoutProps): React.ReactElement {
  const { rows }              = useContext(TerminalSizeContext);
  const { messageListHeight } = computePaneHeights(rows, inputHeight);

  return React.createElement(
    Box,
    { flexDirection: "column", height: rows },
    React.createElement(
      Box,
      { key: "msglist", flexDirection: "column", height: messageListHeight, overflow: "hidden" },
      messageList,
    ),
    React.createElement(
      Box,
      { key: "input", flexDirection: "column", height: inputHeight },
      promptInput,
    ),
  );
}

// ---------------------------------------------------------------------------
// AppRoot — app root: trust gate → theme → session context → layout
// ---------------------------------------------------------------------------

export interface AppRootProps {
  cwd:          string;
  /** Stable identity supplied by the live REPL when available. */
  sessionId?:   string;
  themeMode?:   "dark" | "light" | "auto";
  flags?:       Record<string, boolean | undefined>;
  trustCtx?:    TrustCtx;
  TrustDialog?: React.ComponentType<{ onAccept: () => void; onReject: () => void }>;
  PromptInput?: React.ComponentType<{ onSubmit: () => void }>;
  onExit?:      () => void;
}

/**
 * Derive the session identity used by AppRoot's command context.
 *
 * A checkout path is not a session identity: two live roots can share it.
 * Callers with an existing REPL identity pass it through; isolated AppRoot
 * mounts mint a process-local identity instead of collapsing onto cwd.
 */
export function sessionIdForAppRoot(cwd: string, sessionId?: string): string {
  const supplied = sessionId?.trim();
  return supplied && supplied.length > 0 ? supplied : crypto.randomUUID();
}

export function AppRoot({
  cwd,
  sessionId,
  themeMode = "dark",
  flags     = {},
  trustCtx  = {
    hasMcpServers:    false,
    hasHooks:         false,
    hasBashTools:     false,
    hasHelperScripts: false,
  },
  TrustDialog,
  PromptInput,
  onExit: _onExit,
}: AppRootProps): React.ReactElement {
  const [trustAccepted, setTrustAccepted] = useState(!needsTrustDialog(trustCtx));
  const [messages, setMessages]           = useState<SessionMessage[]>([]);
  const [appSessionId]                    = useState(() => sessionIdForAppRoot(cwd, sessionId));
  const { columns, rows }                 = useContext(TerminalSizeContext);

  const sessionCtx: SessionContextValue = {
    sessionId:  appSessionId,
    cwd,
    jsonlKey:   encodeCwdKey(cwd),
    messages,
    addMessage: useCallback(
      (msg: SessionMessage) => setMessages((prev) => [...prev, msg]),
      [],
    ),
  };

  useEffect(() => {
    writeDebugFiles({ cwd, debugPort: 0, pid: process.pid }).catch(() => {});
  }, [cwd]);

  const width = columns >= DEFAULT_WIDTH ? columns : DEFAULT_WIDTH;

  if (!trustAccepted && TrustDialog) {
    return React.createElement(
      ThemeProvider,
      { mode: themeMode, flags },
      React.createElement(TrustDialog, {
        onAccept: () => setTrustAccepted(true),
        onReject: () => setTrustAccepted(false),
      }),
    );
  }

  const promptInput = PromptInput
    ? React.createElement(PromptInput, { onSubmit: () => {} })
    : React.createElement(Box, null, React.createElement(Text, { dimColor: true }, "> "));

  const messageList = React.createElement(VirtualMessageList, {
    messages,
    renderMessage: (msg) =>
      React.createElement(Text, { key: msg.id }, String(msg["type"] ?? "")),
    viewportRows: rows,
  });

  return React.createElement(
    ThemeProvider,
    { mode: themeMode, flags },
    React.createElement(
      SessionContext.Provider,
      { value: sessionCtx },
      React.createElement(
        Box,
        { flexDirection: "column", width, height: rows },
        React.createElement(FullscreenLayout, { messageList, promptInput }),
      ),
    ),
  );
}
