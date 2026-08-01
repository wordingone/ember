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

/** Returns the .ember/ debug file paths for the given working directory. */
export function getDebugFilePaths(cwd: string): { debugPort: string; debugPid: string } {
  const dir = join(cwd, ".ember");
  return {
    debugPort: join(dir, "debug-port"),
    debugPid:  join(dir, "debug-pid"),
  };
}

/** Writes debug-port and debug-pid into cwd/.ember/ (creates the dir if needed). */
export async function writeDebugFiles(opts: DebugFileOpts): Promise<void> {
  const { debugPort, debugPid } = getDebugFilePaths(opts.cwd);
  const dir = join(opts.cwd, ".ember");
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


export interface VirtualMessageListProps {
  messages:      SessionMessage[];
  renderMessage: (msg: SessionMessage) => React.ReactElement | null;
  viewportRows:  number;
}

export function VirtualMessageList({
  messages,
  renderMessage,
  viewportRows,
}: VirtualMessageListProps): React.ReactElement {
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
  themeMode?:   "dark" | "light" | "auto";
  flags?:       Record<string, boolean | undefined>;
  trustCtx?:    TrustCtx;
  TrustDialog?: React.ComponentType<{ onAccept: () => void; onReject: () => void }>;
  PromptInput?: React.ComponentType<{ onSubmit: () => void }>;
  onExit?:      () => void;
}

export function AppRoot({
  cwd,
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
  const { columns, rows }                 = useContext(TerminalSizeContext);

  const sessionCtx: SessionContextValue = {
    sessionId:  cwd,
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
