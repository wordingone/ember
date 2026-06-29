// prompt-input.ts — keyboard-driven text input component for the REPL prompt.
// Bundle: components/prompt-input.ts (line 321412)

import React, { useState, useRef, useCallback } from "react";
import { Box, Text } from "../ink/components.ts";
import { useInput } from "../ink/hooks.ts";
import type { KeyboardKey } from "../ink/hooks.ts";

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
  mode:           InputMode;
  isStashed:      boolean;
  permissionMode: PermissionMode;
  pastedContents: PastedContents | null;
  stashNotice:    string;
}

export interface PromptInputActions {
  setText:             (t: string) => void;
  appendText:          (ch: string) => void;
  dropLastChar:        () => void;
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

export function permissionModeStatusLine(mode: PermissionMode): string {
  if (mode === "bypass") {
    return "⏵⏵ bypass permissions on (shift+tab to cycle) \xB7 esc to interrupt \xB7 ctrl+t to hide tasks";
  }
  return `${mode} mode (shift+tab to cycle) \xB7 esc to interrupt \xB7 ctrl+t to hide tasks`;
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
  const [text,      setText_]     = useState("");
  const [permMode,  setPermMode]  = useState<PermissionMode>("bypass");
  const [pasted,    setPasted]    = useState<PastedContents | null>(null);
  const [isStashed, setIsStashed] = useState(false);
  const stashRef = useRef(new StashManager());
  const fastRef  = useRef(new FastModeHint());

  const parsed = parseInputMode(text);

  const setText = useCallback((t: string) => {
    setText_(t.slice(0, MAX_INPUT_CHARS));
  }, []);

  const appendText = useCallback((ch: string) => {
    setText_(prev => (prev + ch).slice(0, MAX_INPUT_CHARS));
  }, []);

  const dropLastChar = useCallback(() => {
    setText_(prev => prev.slice(0, -1));
  }, []);

  const paste = useCallback((pastedText: string) => {
    setText_(current => {
      const result = applyPaste(current, pastedText);
      if (result.pastedContents) setPasted(result.pastedContents);
      return result.text;
    });
  }, []);

  const stash = useCallback(() => {
    stashRef.current.stash(text);
    setText_("");
    setIsStashed(true);
  }, [text]);

  const restoreStash = useCallback(() => {
    const v = stashRef.current.restore();
    if (v !== null) setText_(v);
    setIsStashed(false);
  }, []);

  const cyclePermissionMode = useCallback(() => {
    setPermMode(m => nextPermissionMode(m));
  }, []);

  const toggleFastMode = useCallback(() => {
    fastRef.current.toggle(Date.now());
  }, []);

  const openEditor = useCallback(() => {
    deps.onEditorOpen?.(text);
  }, [text, deps]);

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
    text,
    mode:           parsed.mode,
    isStashed,
    permissionMode: permMode,
    pastedContents: pasted,
    stashNotice:    stashRef.current.stashNotice,
  };

  const actions: PromptInputActions = {
    setText,
    appendText,
    dropLastChar,
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
  /** Dimmed ghost text rendered after the cursor — Tab accepts it into the input. */
  suggestion?:           string;
}

export function PromptInput({
  state,
  queuedItems          = [],
  notifications        = [],
  isProcessing         = false,
  prefersReducedMotion = false,
  showStatusLine       = true,
  suggestion,
}: PromptInputProps): React.ReactElement {
  const qDisplay    = computeQueueDisplay(queuedItems);
  const showShimmer = shouldShowShimmer(isProcessing, prefersReducedMotion);
  const statusLine  = permissionModeStatusLine(state.permissionMode);
  const glyph       = modeGlyph(state.mode);

  const children: (React.ReactElement | null)[] = [];

  for (const n of notifications) {
    children.push(
      React.createElement(Text, { key: n.id, color: n.kind === "error" ? "red" : "cyan" }, n.message),
    );
  }

  if (showShimmer) {
    children.push(React.createElement(Text, { key: "shimmer", dimColor: true }, "…"));
  }

  if (state.isStashed) {
    children.push(React.createElement(Text, { key: "stash", dimColor: true }, state.stashNotice));
  }

  children.push(
    React.createElement(
      Box, { key: "input" },
      React.createElement(Text, { bold: true }, glyph),
      React.createElement(Text, null, ` ${state.text}`),
      suggestion
        ? React.createElement(Text, { dimColor: true }, suggestion)
        : null,
    ),
  );

  for (let i = 0; i < qDisplay.visible.length; i++) {
    const item = qDisplay.visible[i]!;
    children.push(React.createElement(Text, { key: `q${i}`, dimColor: true }, item));
  }

  if (qDisplay.overflowCount > 0) {
    children.push(
      React.createElement(Text, { key: "overflow", dimColor: true }, `+ ${qDisplay.overflowCount} more`),
    );
  }

  if (showStatusLine) {
    children.push(
      React.createElement(Text, { key: "status", dimColor: true }, statusLine),
    );
  }

  return React.createElement(Box, { flexDirection: "column" }, ...children);
}
