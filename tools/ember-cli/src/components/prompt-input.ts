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

export const MAX_INPUT_CHARS   = 1e4; // 10 000
export const FAST_HINT_MS      = 5000;
export const QUEUE_MAX_VISIBLE = 3;

export type InputMode      = "prompt" | "bash";
export type PermissionMode = "bypass" | "regular" | "plan";

export const MODE_GLYPHS: Record<InputMode, string> = {
  prompt: "❯", // ❯
  bash:   "!",
};

export const PERMISSION_MODES: PermissionMode[] = ["bypass", "regular", "plan"];

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
  insertText:          (ch: string) => void;
  /** Backspace: removes the character immediately BEFORE the cursor. */
  deleteBackward:      () => void;
  /** Delete key: removes the character immediately AFTER the cursor. */
  deleteForward:       () => void;
  moveCursorLeft:      () => void;
  moveCursorRight:     () => void;
  moveCursorHome:      () => void;
  moveCursorEnd:       () => void;
  paste:               (text: string) => void;
  stash:               () => void;
  restoreStash:        () => void;
  cyclePermissionMode: () => void;
  toggleFastMode:      () => void;
  openEditor:          () => void;
  openModelPicker:     () => void;
}

export interface PromptInputDeps {
  onEditorOpen?:      (text: string) => void;
  onModelPickerOpen?: () => void;
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
  if (key.alt   && input === "p") { actions.openModelPicker();    return true; }
  if (key.alt   && input === "o") { actions.toggleFastMode();     return true; }
  if (key.ctrl  && input === "g") { actions.openEditor();         return true; }
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
  const [permMode,  setPermMode]  = useState<PermissionMode>("bypass");
  const [pasted,    setPasted]    = useState<PastedContents | null>(null);
  const [isStashed, setIsStashed] = useState(false);
  const stashRef = useRef(new StashManager());
  const fastRef  = useRef(new FastModeHint());

  const parsed = parseInputMode(tc.text);

  const setText = useCallback((t: string) => {
    const truncated = t.slice(0, MAX_INPUT_CHARS);
    setTc({ text: truncated, cursor: truncated.length });
  }, []);

  const insertText = useCallback((ch: string) => {
    setTc(prev => insertAtCursor(prev.text, prev.cursor, ch));
  }, []);

  const deleteBackwardAction = useCallback(() => {
    setTc(prev => deleteBackward(prev.text, prev.cursor));
  }, []);

  const deleteForwardAction = useCallback(() => {
    setTc(prev => deleteForward(prev.text, prev.cursor));
  }, []);

  const moveCursorLeft = useCallback(() => {
    setTc(prev => ({ text: prev.text, cursor: moveCursorBy(prev.text, prev.cursor, -1) }));
  }, []);

  const moveCursorRight = useCallback(() => {
    setTc(prev => ({ text: prev.text, cursor: moveCursorBy(prev.text, prev.cursor, 1) }));
  }, []);

  const moveCursorHome = useCallback(() => {
    setTc(prev => ({ text: prev.text, cursor: 0 }));
  }, []);

  const moveCursorEnd = useCallback(() => {
    setTc(prev => ({ text: prev.text, cursor: prev.text.length }));
  }, []);

  const paste = useCallback((pastedText: string) => {
    setTc(current => {
      const result = applyPaste(current.text, pastedText);
      if (result.pastedContents) setPasted(result.pastedContents);
      return { text: result.text, cursor: result.text.length };
    });
  }, []);

  const stash = useCallback(() => {
    stashRef.current.stash(tc.text);
    setTc({ text: "", cursor: 0 });
    setIsStashed(true);
  }, [tc.text]);

  const restoreStash = useCallback(() => {
    const v = stashRef.current.restore();
    if (v !== null) setTc({ text: v, cursor: v.length });
    setIsStashed(false);
  }, []);

  const cyclePermissionMode = useCallback(() => {
    setPermMode(m => nextPermissionMode(m));
  }, []);

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
  });

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
    paste,
    stash,
    restoreStash,
    cyclePermissionMode,
    toggleFastMode,
    openEditor,
    openModelPicker,
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
  showStatusLine       = true,
  statusLine,
  suggestion,
  width                = 80,
}: PromptInputProps): React.ReactElement {
  const qDisplay    = computeQueueDisplay(queuedItems);
  const showShimmer = shouldShowShimmer(isProcessing, prefersReducedMotion);
  const permissionStatusLine = permissionModeStatusLine(state.permissionMode);
  const glyph       = modeGlyph(state.mode);

  // Transient notifications and processing chrome are not part of the persistent input panel.
  const above: React.ReactElement[] = [];
  for (const n of notifications) {
    above.push(
      React.createElement(Text, { key: n.id, color: n.kind === "error" ? "red" : "cyan" }, n.message),
    );
  }
  if (showShimmer) {
    above.push(React.createElement(Text, { key: "shimmer", dimColor: true }, "…"));
  }

  // Every persistent row owned by the input surface lives inside one closed rounded box.
  const boxChildren: (React.ReactElement | null)[] = [];
  if (state.isStashed) {
    boxChildren.push(React.createElement(Text, { key: "stash", dimColor: true }, state.stashNotice));
  }

  const cursor        = state.cursor ?? state.text.length;
  const availableCols = promptInputViewportWidth(width);
  const viewport      = computeInputViewport(state.text, cursor, availableCols);
  const before         = viewport.visibleText.slice(0, viewport.cursorCol);
  const atCursorChar   = viewport.visibleText[viewport.cursorCol] ?? " ";
  const after          = viewport.visibleText.slice(viewport.cursorCol + 1);
  const cursorAtEnd    = viewport.cursorCol === viewport.visibleText.length;

  boxChildren.push(
    React.createElement(
      Box, { key: "input" },
      React.createElement(Text, { bold: true, color: INPUT_BOX_BORDER_COLOR }, glyph),
      React.createElement(Text, null, ` ${before}`),
      React.createElement(Text, { inverse: true }, atCursorChar),
      after ? React.createElement(Text, null, after) : null,
      suggestion && cursorAtEnd
        ? React.createElement(Text, { dimColor: true }, suggestion)
        : null,
    ),
  );

  for (let i = 0; i < qDisplay.visible.length; i++) {
    const item = qDisplay.visible[i]!;
    boxChildren.push(React.createElement(Text, { key: `q${i}`, dimColor: true }, item));
  }
  if (qDisplay.overflowCount > 0) {
    boxChildren.push(
      React.createElement(Text, { key: "overflow", dimColor: true }, `+ ${qDisplay.overflowCount} more`),
    );
  }
  if (showStatusLine) {
    boxChildren.push(React.createElement(Text, { key: "status", dimColor: true }, permissionStatusLine));
  }
  if (statusLine != null) {
    boxChildren.push(
      React.createElement(Box, { key: "status-line", flexDirection: "column" }, statusLine),
    );
  }

  const safeWidth = Number.isFinite(width) ? Math.max(0, Math.floor(width)) : 0;
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
