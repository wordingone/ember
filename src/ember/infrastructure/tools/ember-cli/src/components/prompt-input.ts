// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// prompt-input.ts — keyboard-driven text input component for the REPL prompt.
// Bundle: components/prompt-input.ts (line 321412)

import React, { useState, useRef, useCallback } from "react";
import { Box, Text } from "../ink/components.ts";
import { useInput } from "../ink/hooks.ts";
import type { KeyboardKey } from "../ink/hooks.ts";
import { color, PANEL_BORDER_STYLE } from "./design-system.ts";

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

// Blind test: a 10 000-character cap silently cut ordinary pastes (a log, a file). 200 000
// characters is roughly 50k tokens, half the served context; past it the REPL says so.
export const MAX_INPUT_CHARS   = 200_000;
export const FAST_HINT_MS      = 5000;
export const QUEUE_MAX_VISIBLE = 3;

export type InputMode      = "prompt" | "bash";
export type PermissionMode = "bypass" | "regular" | "plan";
export const DEFAULT_PROMPT_PERMISSION_MODE: PermissionMode = "regular";

export const MODE_GLYPHS: Record<InputMode, string> = {
  prompt: "❯", // ❯
  bash:   "!",
};

export const PERMISSION_MODES: PermissionMode[] = [
  DEFAULT_PROMPT_PERMISSION_MODE,
  "bypass",
  "plan",
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ParsedInput {
  mode:  InputMode;
  value: string;
}

export interface PastedContents {
  originalLength:  number;
  truncatedAt:     number;
  truncatedLength: number;
}

export interface ApplyPasteResult {
  text:           string;
  pastedContents: PastedContents | null;
}

export interface Notification {
  id:      string;
  message: string;
  kind:    "info" | "error";
}

export interface PromptInputState {
  text:           string;
  /** Index into `text` (0..text.length) where the next insert/delete acts. Optional for callers
   * that construct state directly (tests, fixtures) -- PromptInput treats an absent cursor as
   * "at the end of text" (the pre-P0-#64 behavior), so existing fixtures are unaffected. */
  cursor?:        number;
  mode:           InputMode;
  isStashed:      boolean;
  permissionMode: PermissionMode;
  pastedContents: PastedContents | null;
  stashNotice:    string;
}

export interface PromptInputActions {
  setText:             (t: string) => void;
  /** Inserts at the current cursor position (mid-line insert when the cursor isn't at the end;
   * ordinary typing keeps the cursor at the end, so this also covers plain append). */
  /** Returns true when the insertion was cut at MAX_INPUT_CHARS. */
  insertText:          (ch: string) => boolean;
  /** Backspace: removes the character immediately BEFORE the cursor. */
  deleteBackward:      () => void;
  /** Delete key: removes the character immediately AFTER the cursor. */
  deleteForward:       () => void;
  moveCursorLeft:      () => void;
  moveCursorRight:     () => void;
  moveCursorHome:      () => void;
  moveCursorEnd:       () => void;
  /** Moves the cursor to an absolute offset (clamped). */
  setCursor:           (cursor: number) => void;
  paste:               (text: string) => void;
  stash:               () => void;
  restoreStash:        () => void;
  cyclePermissionMode: () => void;
  toggleFastMode:      () => void;
  openEditor:          () => void;
  openModelPicker:     () => void;
  /**
   * issue #251: returns the LIVE text+cursor synchronously, bypassing React's render cycle.
   * A caller that needs the up-to-the-instant buffer content -- most importantly a same-tick
   * Enter handler reading the text just inserted by preceding keystrokes in the SAME synchronous
   * keyboard burst -- must call this instead of reading the `PromptInputState` object returned
   * from render, which only reflects state as of the last completed render and is proven stale
   * mid-burst (see the module doc comment on `usePromptInput` below).
   */
  getSnapshot:         () => TextCursor;
}

export interface PromptInputDeps {
  onEditorOpen?:      (text: string) => void;
  onModelPickerOpen?: () => void;
  /**
   * Whether this hook's key handler is live. Defaults to true.
   *
   * Ink's `_deliverKeyEvent` (ink/hooks.ts) dispatches every keypress to EVERY registered handler
   * whose `isActive` is true, and a handler returning does not stop propagation. So a second
   * surface that also claims the keyboard — the operator-control pane — does not take keys away
   * from this hook by owning its own branch; both handlers run on the same keystroke. Shift+Tab
   * would traverse the pane AND cycle permission mode; Ctrl+S would stash the prompt AND dispatch
   * a control; Escape would exit the pane AND restore a stash.
   *
   * The only place that fact can be honoured is here, at registration, because `isActive` is the
   * one mechanism the dispatcher consults. Callers that hand keyboard authority to another surface
   * pass false for the duration.
   */
  keyboardActive?:    boolean;
  /** Controlled permission mode for callers that own the execution authority state. */
  permissionMode?:    PermissionMode;
  /** Controlled cycle callback; prevents a second internal authority state from drifting. */
  onPermissionModeCycle?: () => void;
}

export interface QueueDisplay {
  visible:       string[];
  overflowCount: number;
}

export interface PromptKeyActions {
  stash:               () => void;
  openModelPicker:     () => void;
  toggleFastMode:      () => void;
  openEditor:          () => void;
  cyclePermissionMode: () => void;
  restoreStash:        () => void;
  acceptSuggestion?:   () => void;
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function parseInputMode(text: string): ParsedInput {
  if (text.startsWith("!")) {
    return { mode: "bash", value: text.slice(1) };
  }
  return { mode: "prompt", value: text };
}

export function modeGlyph(mode: InputMode): string {
  // The classic Windows console font has no ❯ and draws a "missing glyph" box (blind test).
  if (mode === "prompt" && process.env["EMBER_ASCII_GLYPHS"] === "1") return ">";
  return MODE_GLYPHS[mode];
}

export function applyPaste(current: string, pasted: string): ApplyPasteResult {
  const combined = current + pasted;
  if (combined.length <= MAX_INPUT_CHARS) {
    return { text: combined, pastedContents: null };
  }
  const truncated = combined.slice(0, MAX_INPUT_CHARS);
  return {
    text: truncated,
    pastedContents: {
      originalLength:  combined.length,
      truncatedAt:     MAX_INPUT_CHARS,
      truncatedLength: truncated.length,
    },
  };
}

// ---------------------------------------------------------------------------
// Cursor-aware editing (P0 #64 fix, 2026-07-03): replaces the previous append-at-end /
// pop-from-end-only model. See prompt-input.test.ts's "cursor-aware text editing" describe
// block for the failing-receipt-driven rationale (real-PTY proof that a long, overflowing
// single-line input silently truncated past the visible column budget, making backspace
// presses on the invisible tail produce zero rendered change -- indistinguishable from a dead
// key).
// ---------------------------------------------------------------------------

export interface TextCursor {
  text:   string;
  cursor: number;
}

/** Up/Down inside a multi-line draft: the cursor offset on the line above/below, keeping the
 *  column where possible; null when already on the first/last line (the key then belongs to
 *  prompt history). */
export function cursorLineMove(text: string, cursor: number, dir: -1 | 1): number | null {
  const c = clampCursor(cursor, text.length);
  const lineStart = text.lastIndexOf("\n", c - 1) + 1;
  const col = c - lineStart;
  if (dir < 0) {
    if (lineStart === 0) return null;
    const prevStart = text.lastIndexOf("\n", lineStart - 2) + 1;
    return Math.min(prevStart + col, lineStart - 1);
  }
  const lineEnd = text.indexOf("\n", c);
  if (lineEnd < 0) return null;
  const nextStart = lineEnd + 1;
  const nextEnd = text.indexOf("\n", nextStart);
  return Math.min(nextStart + col, nextEnd < 0 ? text.length : nextEnd);
}

export function clampCursor(cursor: number, length: number): number {
  return Math.max(0, Math.min(cursor, length));
}

export function insertAtCursor(text: string, cursor: number, insertion: string): TextCursor {
  const c        = clampCursor(cursor, text.length);
  const combined = text.slice(0, c) + insertion + text.slice(c);
  const result   = combined.slice(0, MAX_INPUT_CHARS);
  return { text: result, cursor: Math.min(c + insertion.length, result.length) };
}

export function deleteBackward(text: string, cursor: number): TextCursor {
  const c = clampCursor(cursor, text.length);
  if (c === 0) return { text, cursor: c };
  return { text: text.slice(0, c - 1) + text.slice(c), cursor: c - 1 };
}

export function deleteForward(text: string, cursor: number): TextCursor {
  const c = clampCursor(cursor, text.length);
  if (c >= text.length) return { text, cursor: c };
  return { text: text.slice(0, c) + text.slice(c + 1), cursor: c };
}

export function moveCursorBy(text: string, cursor: number, delta: number): number {
  return clampCursor(cursor + delta, text.length);
}

export interface InputViewport {
  visibleText: string;
  cursorCol:   number;
}

/** Computes the visible slice of `text` and the cursor's column within it, keeping the cursor
 * always in view. Right-biased: when the cursor is past the current window's right edge, the
 * window scrolls just far enough to put the cursor at the last visible column (matches the
 * behavior of a normal shell readline / CLI single-line input). This is the direct cure for the
 * "invisible-tail truncation" defect class -- text longer than `width` is windowed instead of
 * silently clipped, so every edit at the cursor is within the rendered viewport. */
export function computeInputViewport(text: string, cursor: number, width: number): InputViewport {
  const w = Math.max(0, width);
  const c = clampCursor(cursor, text.length);
  if (w === 0 || text.length <= w) {
    return { visibleText: w === 0 ? "" : text, cursorCol: w === 0 ? 0 : c };
  }
  const maxStart = text.length - w;
  const start    = Math.max(0, Math.min(c - w + 1, maxStart));
  return { visibleText: text.slice(start, start + w), cursorCol: c - start };
}

export interface InputRow { text: string; cursorCol: number | null }
export interface InputRows { rows: InputRow[]; hiddenAbove: number; hiddenBelow: number }

/** Wrap the prompt into rows of `width` cells, honouring typed newlines, and keep at
 * most `maxRows` of them on screen around the cursor. A long prompt used to show
 * only its last `width` characters on one line. */
export function computeInputRows(text: string, cursor: number, width: number, maxRows = 8): InputRows {
  const w = Math.max(1, Math.floor(width));
  const c = clampCursor(cursor, text.length);
  const all: InputRow[] = [];
  let offset = 0;
  let cursorRow = 0;
  const lines = text.split("\n");
  lines.forEach((line, li) => {
    const chunks = line.length === 0 ? [""] : (line.match(new RegExp(`[\\s\\S]{1,${w}}`, "g")) ?? [""]);
    // A line that exactly fills its last row still needs a row for a cursor at its end.
    if (line.length > 0 && line.length % w === 0) chunks.push("");
    chunks.forEach((chunk, ci) => {
      const start = offset + ci * w;
      const isLast = ci === chunks.length - 1;
      const inRow = c >= start && (c < start + chunk.length || (isLast && c === start + chunk.length));
      if (inRow) cursorRow = all.length;
      all.push({ text: chunk, cursorCol: inRow ? c - start : null });
    });
    offset += line.length + (li < lines.length - 1 ? 1 : 0);
  });
  const n = Math.max(1, Math.floor(maxRows));
  const first = Math.max(0, Math.min(cursorRow - n + 1, all.length - n));
  const top = Math.max(0, first);
  return { rows: all.slice(top, top + n), hiddenAbove: top, hiddenBelow: Math.max(0, all.length - top - n) };
}

export function computeQueueDisplay(items: string[]): QueueDisplay {
  const visible       = items.slice(0, QUEUE_MAX_VISIBLE);
  const overflowCount = Math.max(0, items.length - QUEUE_MAX_VISIBLE);
  return { visible, overflowCount };
}

export function shouldShowShimmer(isProcessing: boolean, prefersReducedMotion: boolean): boolean {
  return isProcessing && !prefersReducedMotion;
}

export function nextPermissionMode(current: PermissionMode): PermissionMode {
  const idx  = PERMISSION_MODES.indexOf(current);
  const next = PERMISSION_MODES[(idx + 1) % PERMISSION_MODES.length];
  return next ?? "regular";
}

// issue #1044: keybinding-hint chrome ("(shift+tab to cycle)", "esc to interrupt",
// "ctrl+t to hide|show tasks") removed -- keybindings stay live via status-bar.ts's
// useInput, only the always-on textual advertisement goes. This function is currently
// DEAD in production (repl.ts:showStatusLine is always false) but kept in sync with
// status-bar.ts's statusBarText() so no stale copy of the old hint string survives.
export function permissionModeStatusLine(mode: PermissionMode): string {
  if (mode === "bypass") {
    return "⏵⏵ bypass permissions on";
  }
  return `${mode} mode`;
}

export function handlePromptInputKey(
  input:     string,
  key:       KeyboardKey,
  actions:   PromptKeyActions,
  isStashed: boolean,
): boolean {
  if (key.ctrl  && input === "s") { actions.stash();              return true; }
  if (key.shift && key.tab)                           { actions.cyclePermissionMode();    return true; }
  if (!key.shift && key.tab && actions.acceptSuggestion) { actions.acceptSuggestion();       return true; }
  if (key.escape && isStashed)                        { actions.restoreStash();           return true; }
  return false;
}

// ---------------------------------------------------------------------------
// StashManager — single-slot text stash with restore
// ---------------------------------------------------------------------------

export class StashManager {
  private _stash: string | null = null;

  get isStashed(): boolean   { return this._stash !== null; }
  get stashNotice(): string  { return "Input stashed \xB7 press Esc to restore"; }

  stash(input: string): void { this._stash = input; }

  restore(): string | null {
    const v     = this._stash;
    this._stash = null;
    return v;
  }
}

// ---------------------------------------------------------------------------
// FastModeHint — shown once for FAST_HINT_MS ms
// ---------------------------------------------------------------------------

export class FastModeHint {
  private _shownCount   = 0;
  private _visibleUntil: number | null = null;

  toggle(now: number): boolean {
    if (this._shownCount >= 1) return false;
    this._shownCount++;
    this._visibleUntil = now + FAST_HINT_MS;
    return true;
  }

  isVisible(now: number): boolean {
    return this._visibleUntil !== null && now < this._visibleUntil;
  }
}

// ---------------------------------------------------------------------------
// usePromptInput — stateful input hook
// ---------------------------------------------------------------------------

export function usePromptInput(
  deps: PromptInputDeps = {},
): [PromptInputState, PromptInputActions] {
  // text + cursor are updated together (P0 #64): a single state object so every transition
  // computes a mutually-consistent pair in one reducer call, rather than two separate useState
  // calls racing against each other across renders.
  const [tc,        setTc]        = useState<TextCursor>({ text: "", cursor: 0 });
  const [internalPermMode, setInternalPermMode] = useState<PermissionMode>(DEFAULT_PROMPT_PERMISSION_MODE);
  const permMode = deps.permissionMode ?? internalPermMode;
  const [pasted,    setPasted]    = useState<PastedContents | null>(null);
  const [isStashed, setIsStashed] = useState(false);
  const stashRef = useRef(new StashManager());
  const fastRef  = useRef(new FastModeHint());

  // issue #251 ("full line + Enter in one synchronous write burst is silently dropped"): a
  // real terminal write() burst decodes into several `_deliverKeyEvent` calls (one per
  // character, then one for Enter) that all run synchronously, in order, in the SAME JS turn --
  // React never gets a chance to render between them. Every caller that reads state via the
  // `tc` useState value (including a consumer's own `inputState.text` closure, e.g. repl.ts's
  // Enter handler) sees whatever `tc` was as of the LAST completed render, so an Enter delivered
  // in the same burst as the preceding characters reads the buffer as it was BEFORE any of them
  // landed -- empty, on a fresh line -- and the "nothing typed" guard silently no-ops the whole
  // submission. Splitting the write (character(s), then Enter as its own write()) gives React a
  // chance to render in between, which is why that path always worked and made this look
  // input-length- or word-count-related rather than a batching race.
  //
  // tcRef is the fix: a plain ref that every mutation below updates FIRST, synchronously and
  // unconditionally, before also calling `setTc` to schedule the matching re-render. Because
  // tcRef.current is written immediately (not deferred to React's next render), a same-tick
  // `getSnapshot()` call always returns the fully caught-up value, burst or no burst.
  const tcRef = useRef<TextCursor>(tc);

  const updateTc = useCallback((fn: (prev: TextCursor) => TextCursor) => {
    const next = fn(tcRef.current);
    tcRef.current = next;
    setTc(next);
    return next;
  }, []);

  const parsed = parseInputMode(tc.text);

  const setText = useCallback((t: string) => {
    updateTc(() => {
      const truncated = t.slice(0, MAX_INPUT_CHARS);
      return { text: truncated, cursor: truncated.length };
    });
  }, [updateTc]);

  const insertText = useCallback((ch: string) => {
    let cut = false;
    updateTc(prev => {
      cut = prev.text.length + ch.length > MAX_INPUT_CHARS;
      return insertAtCursor(prev.text, prev.cursor, ch);
    });
    return cut;
  }, [updateTc]);

  const deleteBackwardAction = useCallback(() => {
    updateTc(prev => deleteBackward(prev.text, prev.cursor));
  }, [updateTc]);

  const deleteForwardAction = useCallback(() => {
    updateTc(prev => deleteForward(prev.text, prev.cursor));
  }, [updateTc]);

  const moveCursorLeft = useCallback(() => {
    updateTc(prev => ({ text: prev.text, cursor: moveCursorBy(prev.text, prev.cursor, -1) }));
  }, [updateTc]);

  const moveCursorRight = useCallback(() => {
    updateTc(prev => ({ text: prev.text, cursor: moveCursorBy(prev.text, prev.cursor, 1) }));
  }, [updateTc]);

  const moveCursorHome = useCallback(() => {
    updateTc(prev => ({ text: prev.text, cursor: 0 }));
  }, [updateTc]);

  const moveCursorEnd = useCallback(() => {
    updateTc(prev => ({ text: prev.text, cursor: prev.text.length }));
  }, [updateTc]);

  const setCursor = useCallback((cursor: number) => {
    updateTc(prev => ({ text: prev.text, cursor: clampCursor(cursor, prev.text.length) }));
  }, [updateTc]);

  const paste = useCallback((pastedText: string) => {
    updateTc(current => {
      const result = applyPaste(current.text, pastedText);
      if (result.pastedContents) setPasted(result.pastedContents);
      return { text: result.text, cursor: result.text.length };
    });
  }, [updateTc]);

  const stash = useCallback(() => {
    stashRef.current.stash(tcRef.current.text);
    updateTc(() => ({ text: "", cursor: 0 }));
    setIsStashed(true);
  }, [updateTc]);

  const restoreStash = useCallback(() => {
    const v = stashRef.current.restore();
    if (v !== null) updateTc(() => ({ text: v, cursor: v.length }));
    setIsStashed(false);
  }, [updateTc]);

  const getSnapshot = useCallback((): TextCursor => tcRef.current, []);

  const cyclePermissionMode = useCallback(() => {
    if (deps.onPermissionModeCycle) {
      deps.onPermissionModeCycle();
      return;
    }
    setInternalPermMode(m => nextPermissionMode(m));
  }, [deps.onPermissionModeCycle]);

  const toggleFastMode = useCallback(() => {
    fastRef.current.toggle(Date.now());
  }, []);

  const openEditor = useCallback(() => {
    deps.onEditorOpen?.(tc.text);
  }, [tc.text, deps]);

  const openModelPicker = useCallback(() => {
    deps.onModelPickerOpen?.();
  }, [deps]);

  useInput((_input, key) => {
    handlePromptInputKey(_input, key, {
      stash,
      openModelPicker,
      toggleFastMode,
      openEditor,
      cyclePermissionMode,
      restoreStash,
    }, isStashed);
  }, { isActive: deps.keyboardActive ?? true });

  const state: PromptInputState = {
    text:           tc.text,
    cursor:         tc.cursor,
    mode:           parsed.mode,
    isStashed,
    permissionMode: permMode,
    pastedContents: pasted,
    stashNotice:    stashRef.current.stashNotice,
  };

  const actions: PromptInputActions = {
    setText,
    insertText,
    deleteBackward:  deleteBackwardAction,
    deleteForward:   deleteForwardAction,
    moveCursorLeft,
    moveCursorRight,
    moveCursorHome,
    moveCursorEnd,
    setCursor,
    paste,
    stash,
    restoreStash,
    cyclePermissionMode,
    toggleFastMode,
    openEditor,
    openModelPicker,
    getSnapshot,
  };

  return [state, actions];
}

// ---------------------------------------------------------------------------
// PromptInput — stateless rendering component
// ---------------------------------------------------------------------------

export interface PromptInputProps {
  state:                 PromptInputState;
  queuedItems?:          string[];
  notifications?:        Notification[];
  isProcessing?:         boolean;
  prefersReducedMotion?: boolean;
  /** Collapse all transient rows while the slash palette owns vertical space. */
  compact?:              boolean;
  showStatusLine?:       boolean;
  /** The real REPL StatusLine, supplied by screens/repl.ts and rendered inside the border. */
  statusLine?:           React.ReactNode;
  /** Dimmed ghost text rendered after the cursor — Tab accepts it into the input. */
  suggestion?:           string;
  /** Terminal width for the rounded input region; absent → 80 (mirrors StatusLine's width convention). */
  width?:                number;
}

/** Issue #243: use the shared rounded panel token rather than open horizontal rules. */
const INPUT_BOX_BORDER_COLOR = color("primary", "fg");

/** Content columns remaining after left/right border, horizontal padding, and the glyph prefix. */
export function promptInputViewportWidth(width: number): number {
  if (!Number.isFinite(width)) return 0;
  return Math.max(0, Math.floor(width) - 6);
}

export function PromptInput({
  state,
  queuedItems          = [],
  notifications        = [],
  isProcessing         = false,
  prefersReducedMotion = false,
  compact              = false,
  showStatusLine       = true,
  statusLine,
  suggestion,
  width                = 80,
}: PromptInputProps): React.ReactElement {
  const qDisplay    = computeQueueDisplay(compact ? [] : queuedItems);
  const showShimmer = !compact && shouldShowShimmer(isProcessing, prefersReducedMotion);
  const permissionStatusLine = permissionModeStatusLine(state.permissionMode);
  const glyph       = modeGlyph(state.mode);
  const safeWidth   = Number.isFinite(width) ? Math.max(0, Math.floor(width)) : 0;

  // Transient notifications and processing chrome are not part of the persistent input panel.
  const above: React.ReactElement[] = [];
  for (const n of compact ? [] : notifications) {
    above.push(
      React.createElement(Text, { key: n.id, color: n.kind === "error" ? "red" : "cyan" }, n.message),
    );
  }
  // No separate "…" shimmer row: the spinner line ("Thinking… 3s · Esc to interrupt") already
  // says work is in progress, and the lone "…" read as a stray character (blind test).
  void showShimmer;

  // Every persistent row owned by the input surface lives inside one closed rounded box.
  const boxChildren: (React.ReactElement | null)[] = [];
  if (!compact && state.isStashed) {
    boxChildren.push(React.createElement(Text, { key: "stash", dimColor: true }, state.stashNotice));
  }

  const cursor        = state.cursor ?? state.text.length;
  const availableCols = promptInputViewportWidth(width);
  const cursorAtEnd   = cursor >= state.text.length;
  const inputRows     = computeInputRows(state.text, cursor, Math.max(1, availableCols), compact ? 1 : 8);

  if (inputRows.hiddenAbove > 0) {
    boxChildren.push(React.createElement(Text, { key: "input-above", dimColor: true }, `  … ${inputRows.hiddenAbove} more line(s) above`));
  }
  inputRows.rows.forEach((row, i) => {
    const prefix = i === 0 && inputRows.hiddenAbove === 0
      ? React.createElement(Text, { bold: true, color: INPUT_BOX_BORDER_COLOR }, glyph)
      : React.createElement(Text, null, " ");
    if (row.cursorCol === null) {
      boxChildren.push(React.createElement(Box, { key: `input-${i}` }, prefix, React.createElement(Text, null, ` ${row.text}`)));
      return;
    }
    const before = row.text.slice(0, row.cursorCol);
    const atCursorChar = row.text[row.cursorCol] ?? " ";
    const after = row.text.slice(row.cursorCol + 1);
    boxChildren.push(
      React.createElement(
        Box, { key: i === 0 ? "input" : `input-${i}` },
        prefix,
        React.createElement(Text, null, ` ${before}`),
        React.createElement(Text, { inverse: true }, atCursorChar),
        after ? React.createElement(Text, null, after) : null,
        !compact && suggestion && cursorAtEnd
          ? React.createElement(Text, { dimColor: true }, suggestion)
          : null,
      ),
    );
  });
  if (inputRows.hiddenBelow > 0) {
    boxChildren.push(React.createElement(Text, { key: "input-below", dimColor: true }, `  … ${inputRows.hiddenBelow} more line(s) below`));
  }

  for (let i = 0; i < qDisplay.visible.length; i++) {
    const item = qDisplay.visible[i]!;
    boxChildren.push(React.createElement(Text, { key: `q${i}`, dimColor: true }, item));
  }
  if (qDisplay.overflowCount > 0) {
    boxChildren.push(
      React.createElement(Text, { key: "overflow", dimColor: true }, `+ ${qDisplay.overflowCount} more`),
    );
  }
  if (!compact && showStatusLine) {
    boxChildren.push(React.createElement(Text, { key: "status", dimColor: true }, permissionStatusLine));
  }
  if (statusLine != null) {
    boxChildren.push(
      React.createElement(Box, { key: "status-line", flexDirection: "column", width: Math.max(0, safeWidth - 4), overflow: "hidden" }, statusLine),
    );
  }

  const box = React.createElement(
    Box,
    {
      key:           "input-box",
      flexDirection: "column",
      borderStyle:   PANEL_BORDER_STYLE,
      borderColor:   INPUT_BOX_BORDER_COLOR,
      paddingX:      1,
      width:          safeWidth,
    },
    ...boxChildren,
  );

  // #561 P0-A: fixed bottom chrome, never a flex-shrink target.
  return React.createElement(Box, { flexDirection: "column", flexShrink: 0 }, ...above, box);
}
