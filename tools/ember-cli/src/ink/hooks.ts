// hooks — React hooks for terminal interaction.
// Covers keyboard input, app context, animation, stdin, focus, title,
// viewport, text selection, and tab-status queries.

import { useEffect, useRef, useState, useContext } from "react";
import {
  AppContext,
  StdinContext,
  TerminalFocusContext,
  TerminalSizeContext,
} from "./components.ts";
import { osc } from "./termio.ts";
import type { SgrMousePress } from "./termio.ts";

// ---------------------------------------------------------------------------
// KeyboardKey — shape delivered to useInput handlers
// ---------------------------------------------------------------------------

export interface KeyboardKey {
  upArrow:   boolean; downArrow:  boolean;
  leftArrow: boolean; rightArrow: boolean;
  pageUp:    boolean; pageDown:   boolean;
  return:    boolean; escape:     boolean;
  tab:       boolean; backspace:  boolean;
  delete:    boolean; insert:     boolean;
  home:      boolean; end:        boolean;
  ctrl:  boolean; shift: boolean; alt: boolean; meta: boolean;
  f1:  boolean; f2:  boolean; f3:  boolean; f4:  boolean;
  f5:  boolean; f6:  boolean; f7:  boolean; f8:  boolean;
  f9:  boolean; f10: boolean; f11: boolean; f12: boolean;
}

// ---------------------------------------------------------------------------
// Internal keyboard handler registry
// ---------------------------------------------------------------------------

interface InputHandlerEntry {
  handler:  (input: string, key: KeyboardKey) => void;
  isActive: boolean;
}

const _inputHandlers: InputHandlerEntry[] = [];

function makeKeyboardKey(
  keyName: string,
  ke: { ctrl?: boolean; shift?: boolean; alt?: boolean; meta?: boolean },
): KeyboardKey {
  return {
    upArrow:    keyName === "up",
    downArrow:  keyName === "down",
    leftArrow:  keyName === "left",
    rightArrow: keyName === "right",
    pageUp:     keyName === "pageup",
    pageDown:   keyName === "pagedown",
    return:     keyName === "return",
    escape:     keyName === "escape",
    tab:        keyName === "tab",
    backspace:  keyName === "backspace",
    delete:     keyName === "delete",
    insert:     keyName === "insert",
    home:       keyName === "home",
    end:        keyName === "end",
    ctrl:  ke.ctrl  ?? false,
    shift: ke.shift ?? false,
    alt:   ke.alt   ?? false,
    meta:  ke.meta  ?? false,
    f1:  keyName === "f1",  f2:  keyName === "f2",
    f3:  keyName === "f3",  f4:  keyName === "f4",
    f5:  keyName === "f5",  f6:  keyName === "f6",
    f7:  keyName === "f7",  f8:  keyName === "f8",
    f9:  keyName === "f9",  f10: keyName === "f10",
    f11: keyName === "f11", f12: keyName === "f12",
  };
}

/**
 * Called by stdin-bridge to route a keypress to all registered active handlers.
 * @internal
 */
export function _deliverKeyEvent(
  keyName: string,
  ke: { ctrl?: boolean; shift?: boolean; alt?: boolean; meta?: boolean },
): void {
  const key   = makeKeyboardKey(keyName, ke);
  const input = keyName.length === 1 ? keyName : "";
  for (const entry of _inputHandlers) {
    if (entry.isActive) entry.handler(input, key);
  }
}

type MouseDispatcher = (event: SgrMousePress) => void;
let _mouseDispatcher: MouseDispatcher | null = null;

/** Installs the currently mounted renderer's pointer dispatcher. @internal */
export function _setMouseDispatcher(dispatcher: MouseDispatcher): () => void {
  _mouseDispatcher = dispatcher;
  return () => {
    if (_mouseDispatcher === dispatcher) _mouseDispatcher = null;
  };
}

/** Routes one decoded mouse press to the currently mounted renderer. @internal */
export function _deliverMouseEvent(event: SgrMousePress): void {
  _mouseDispatcher?.(event);
}

// ---------------------------------------------------------------------------
// Text-selection module state
// ---------------------------------------------------------------------------

let _selectionText: string | null = null;
const _selectionListeners: Array<() => void> = [];

function _notifySelectionChange(): void {
  for (const l of _selectionListeners) l();
}

/** Updates the module-level selection text and notifies subscribers. @internal */
export function _setSelectionText(text: string | null): void {
  _selectionText = text;
  _notifySelectionChange();
}

// ---------------------------------------------------------------------------
// Terminal title stack
// ---------------------------------------------------------------------------

const _titleStack: string[] = [];

// ---------------------------------------------------------------------------
// useInput
// ---------------------------------------------------------------------------

export interface UseInputOptions {
  /** When false the handler will not receive key events. Defaults to true. */
  isActive?: boolean;
}

/**
 * Registers a keyboard-input handler.  The handler receives a raw `input`
 * string (single printable character or "") and a `KeyboardKey` descriptor.
 */
export function useInput(
  handler: (input: string, key: KeyboardKey) => void,
  options?: UseInputOptions,
): void {
  const isActive = options?.isActive ?? true;
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const entry: InputHandlerEntry = {
      handler: (input, key) => handlerRef.current(input, key),
      isActive,
    };
    _inputHandlers.push(entry);
    return () => {
      const idx = _inputHandlers.indexOf(entry);
      if (idx >= 0) _inputHandlers.splice(idx, 1);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync isActive without re-registering
  useEffect(() => {
    const entry = _inputHandlers[_inputHandlers.length - 1];
    if (entry) entry.isActive = isActive;
  });
}

// ---------------------------------------------------------------------------
// useApp
// ---------------------------------------------------------------------------

/** Returns the app context: `{ exit(error?) }`. */
export function useApp(): { exit: (error?: Error) => void } {
  return useContext(AppContext);
}

// ---------------------------------------------------------------------------
// useAnimationFrame
// ---------------------------------------------------------------------------

/**
 * Calls `callback(dt)` every ~16 ms (≈60 fps) while `isActive` is true.
 * `dt` is the elapsed time in ms since the previous call.
 */
export function useAnimationFrame(
  callback: (dt: number) => void,
  isActive = true,
): void {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;
  const lastRef = useRef(Date.now());

  useEffect(() => {
    if (!isActive) return;
    const id = setInterval(() => {
      const now = Date.now();
      const dt  = now - lastRef.current;
      lastRef.current = now;
      callbackRef.current(dt);
    }, 16);
    return () => clearInterval(id);
  }, [isActive]);
}

// ---------------------------------------------------------------------------
// useAnimationTimer
// ---------------------------------------------------------------------------

/**
 * Interpolates from `from` to `to` over `duration` ms and returns the
 * current value, updating at ~60 fps.
 */
export function useAnimationTimer(
  from:     number,
  to:       number,
  duration: number,
): number {
  const startRef = useRef(Date.now());
  const [value, setValue] = useState(from);

  useEffect(() => {
    startRef.current = Date.now();
    const id = setInterval(() => {
      const elapsed = Date.now() - startRef.current;
      const t = Math.min(elapsed / duration, 1);
      const v = from + (to - from) * t;
      setValue(v);
      if (t >= 1) clearInterval(id);
    }, 16);
    return () => clearInterval(id);
  }, [from, to, duration]);

  return value;
}

// ---------------------------------------------------------------------------
// useInterval
// ---------------------------------------------------------------------------

/**
 * Calls `callback` every `delay` ms.  Pass `null` to pause.
 * The callback ref is always current — no need to include it in deps.
 */
export function useInterval(callback: () => void, delay: number | null): void {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (delay === null) return;
    const id = setInterval(() => callbackRef.current(), delay);
    return () => clearInterval(id);
  }, [delay]);
}

// ---------------------------------------------------------------------------
// useSelection
// ---------------------------------------------------------------------------

export interface SelectionState {
  isSelecting:    boolean;
  selectedText:   string | null;
  clearSelection: () => void;
}

/** Returns the current text-selection state and a clear function. */
export function useSelection(): SelectionState {
  const [, forceUpdate] = useState(0);

  useEffect(() => {
    const listener = () => forceUpdate(n => n + 1);
    _selectionListeners.push(listener);
    return () => {
      const idx = _selectionListeners.indexOf(listener);
      if (idx >= 0) _selectionListeners.splice(idx, 1);
    };
  }, []);

  return {
    isSelecting:  false,
    selectedText: _selectionText,
    clearSelection: () => { _setSelectionText(null); },
  };
}

// ---------------------------------------------------------------------------
// useStdin
// ---------------------------------------------------------------------------

/** Returns the stdin context (stream, setRawMode, isRawModeSupported). */
export function useStdin() {
  return useContext(StdinContext);
}

// ---------------------------------------------------------------------------
// useTerminalFocus
// ---------------------------------------------------------------------------

/** Returns the terminal-focus context (isFocused). */
export function useTerminalFocus() {
  return useContext(TerminalFocusContext);
}

// ---------------------------------------------------------------------------
// useTerminalTitle
// ---------------------------------------------------------------------------

/**
 * Sets the terminal window title via OSC 2.  Restores the previous title
 * (or clears it) on unmount.  Stacks correctly when nested.
 */
export function useTerminalTitle(title: string): void {
  useEffect(() => {
    _titleStack.push(title);
    process.stdout.write(osc(2, title));
    return () => {
      const idx = _titleStack.lastIndexOf(title);
      if (idx >= 0) _titleStack.splice(idx, 1);
      const parent = _titleStack[_titleStack.length - 1];
      if (parent !== undefined)
        process.stdout.write(osc(2, parent));
      else
        process.stdout.write(osc(2, ""));
    };
  }, [title]);
}

// ---------------------------------------------------------------------------
// useTerminalViewport
// ---------------------------------------------------------------------------

/** Returns the terminal dimensions context (columns, rows). */
export function useTerminalViewport() {
  return useContext(TerminalSizeContext);
}

// ---------------------------------------------------------------------------
// useTabStatus
// ---------------------------------------------------------------------------

/**
 * Queries a tab-status key via the iTerm2/WezTerm OSC 21337 protocol.
 * Returns `null` until the response arrives (or after 500 ms timeout).
 */
export function useTabStatus(key: string): string | null {
  const [value, setValue] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => { if (!cancelled) setValue(null); }, 500);

    const query = `\x1b]21337;${key}:query\x07`;
    process.stdout.write(query);

    const onData = (chunk: Buffer) => {
      const data = chunk.toString();
      const m = data.match(/\x1b\]21337;([^=]+)=([^\x07\x1b]+)/);
      if (m && m[1] === key && !cancelled) {
        clearTimeout(timer);
        setValue(m[2] ?? null);
        cancelled = true;
        process.stdin.off("data", onData);
      }
    };
    process.stdin.on("data", onData);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      process.stdin.off("data", onData);
    };
  }, [key]);

  return value;
}
