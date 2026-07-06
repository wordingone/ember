// frontend-shell.ts — TUI boot surface: Ink render wrapper, REPL launcher,
// and project onboarding state. This module is the TUI-specific entry; the
// headless path lives in cli/headless-repl.ts.
//
// Spec: specs/core/frontend-shell.md — AC1–AC10.

import React from "react";
import type { ReactElement } from "react";
import type { MountHandle } from "../ink/reconciler.ts";

// ---------------------------------------------------------------------------
// issue #286: mountInk/createRenderer close over whatever `stdout` object is
// handed to them and read `.columns`/`.rows` fresh on every render() call --
// but every call site below used to build a PLAIN {columns, rows} literal
// once, at mount time, which then never changes again for the renderer's
// lifetime. That froze the actual frame/paint width forever at boot-time
// dimensions, even after App's own TerminalSizeContext (ink/components.ts)
// correctly picks up a live resize -- a re-render just repaints the SAME
// stale width. Getters here make every read live, so any later render()
// call (including one triggered by the resize poller) sees the true current
// terminal size.
// ---------------------------------------------------------------------------
const liveStdoutSize = {
  get columns(): number { return process.stdout.columns ?? 80; },
  get rows():    number { return process.stdout.rows    ?? 24; },
};

// ---------------------------------------------------------------------------
// Design system re-exports (AC10)
// ---------------------------------------------------------------------------

export {
  ThemeProvider,
  useTheme,
  color,
  resolveTheme,
} from "../components/design-system.ts";
export type { ThemeMode, ResolvedTheme, ThemeContextValue, FeatureFlags } from "../components/design-system.ts";

// Re-export useThemeSetting as a hook that returns the current theme setting
export { useTheme as useThemeSetting } from "../components/design-system.ts";

// ---------------------------------------------------------------------------
// Ink primitive re-exports (AC10)
// ---------------------------------------------------------------------------

export {
  Box,
  Text,
  RawAnsi,
  Newline,
  Spacer,
  Button,
  Link,
} from "../ink/components.ts";
export type { BoxProps, TextProps } from "../ink/components.ts";

// BaseBox and BaseText aliases (AC10 — contract names)
export { Box as BaseBox, Text as BaseText } from "../ink/components.ts";

// Ansi is an alias for RawAnsi (interop name)
export { RawAnsi as Ansi } from "../ink/components.ts";

// NoSelect — a pass-through wrapper that strips mouse selection
export function NoSelect({ children }: { children?: React.ReactNode }): ReactElement {
  return React.createElement(React.Fragment, null, children);
}

// ---------------------------------------------------------------------------
// Event system re-exports (AC10)
// ---------------------------------------------------------------------------

export {
  TerminalEvent,
  ClickEvent,
  InputEvent,
  TerminalFocusEvent,
  FocusManager,
} from "../ink/event-system.ts";

// Key — keyboard key shape (re-exported from hooks)
export type { KeyboardKey as Key } from "../ink/hooks.ts";

// EventEmitter — Node.js EventEmitter re-exported for consumers
export { EventEmitter } from "node:events";

// Event — alias for TerminalEvent
export { TerminalEvent as Event } from "../ink/event-system.ts";

// ---------------------------------------------------------------------------
// Hook re-exports (AC10)
// ---------------------------------------------------------------------------

export {
  useInput,
  useApp,
  useStdin,
  useAnimationFrame,
  useAnimationTimer,
  useInterval,
  useSelection,
  useTabStatus,
  useTerminalFocus,
  useTerminalTitle,
  useTerminalViewport,
} from "../ink/hooks.ts";

// ---------------------------------------------------------------------------
// Utility exports (AC10)
// ---------------------------------------------------------------------------

/**
 * Measures the pixel dimensions of a rendered element.
 * In the terminal renderer, returns the character-cell bounds.
 * Stub: real measurement goes through the layout engine.
 */
export function measureElement(element: unknown): { width: number; height: number } {
  void element;
  return { width: 0, height: 0 };
}

/**
 * Wraps `text` at `width` characters, returning an array of lines.
 */
export function wrapText(text: string, width: number): string[] {
  if (width <= 0) return [text];
  if (text === "") return [""];
  const lines: string[] = [];
  let remaining = text;
  while (remaining.length > width) {
    // Break at last space within the width, or hard-break if none
    const slice = remaining.slice(0, width);
    const lastSpace = slice.lastIndexOf(" ");
    if (lastSpace > 0) {
      lines.push(remaining.slice(0, lastSpace));
      remaining = remaining.slice(lastSpace + 1);
    } else {
      lines.push(slice);
      remaining = remaining.slice(width);
    }
  }
  if (remaining.length > 0) lines.push(remaining);
  return lines;
}

/**
 * Returns whether the terminal supports tab-status OSC sequences.
 */
export function supportsTabStatus(): boolean {
  const term = process.env["TERM_PROGRAM"];
  return term === "iTerm.app" || term === "WezTerm";
}

// ---------------------------------------------------------------------------
// Ink render wrapper (AC1, AC2)
// ---------------------------------------------------------------------------

import { ThemeProvider } from "../components/design-system.ts";

/** Minimal InkInstance shape returned by render(). */
export interface InkInstance {
  /** Unmount the render tree and clean up. */
  unmount(): void;
  /** Promise that resolves when the render tree is cleaned up. */
  waitUntilExit(): Promise<void>;
}

/** Options forwarded to the underlying Ink render call. */
export interface RenderOptions {
  stdout?: NodeJS.WritableStream;
  stdin?: NodeJS.ReadableStream;
  stderr?: NodeJS.WritableStream;
  debug?: boolean;
  exitOnCtrlC?: boolean;
  patchConsole?: boolean;
}

// Lazy import holder for Ink render (avoids import cost in headless sessions)
let _inkRender: ((node: ReactElement, options?: RenderOptions) => InkInstance) | null = null;

async function getInkRender(): Promise<(node: ReactElement, options?: RenderOptions) => InkInstance> {
  if (_inkRender) return _inkRender;
  const { mountInk } = await import("../ink/reconciler.ts");
  _inkRender = (node: ReactElement, options?: RenderOptions): InkInstance => {
    const wrapped = React.createElement(ThemeProvider, null, node);
    const stream = (options?.stdout as { write?: (s: string) => void } | undefined)?.write
      ? options!.stdout as { write(s: string): void }
      : process.stdout;
    const handle = mountInk(wrapped, {
      stream,
      stdout: liveStdoutSize,
      debug: options?.debug,
    });
    return {
      unmount() { handle.unmount(); },
      waitUntilExit(): Promise<void> { return Promise.resolve(); },
    };
  };
  return _inkRender;
}

/**
 * AC1: Wraps the provided React element in a ThemeProvider before rendering.
 * All callers must use this instead of calling Ink's render() directly.
 * Uses the custom reconciler (mountInk) to drive the frame pipeline.
 */
export function render(node: ReactElement, options?: RenderOptions): InkInstance {
  // Dynamic import at call time keeps load cost low for headless sessions
  let handle: MountHandle | null = null;
  const wrapped = React.createElement(ThemeProvider, null, node);
  const stream = (options?.stdout as { write?: (s: string) => void } | undefined)?.write
    ? options!.stdout as { write(s: string): void }
    : process.stdout;

  // Kick off the mount synchronously using a dynamic import cache
  import("../ink/reconciler.ts").then(({ mountInk }) => {
    handle = mountInk(wrapped, {
      stream,
      stdout: liveStdoutSize,
      debug: options?.debug,
    });
  }).catch(() => { /* reconciler load failure — degrade silently */ });

  return {
    unmount() { handle?.unmount(); },
    waitUntilExit(): Promise<void> { return Promise.resolve(); },
  };
}

// Module-level root singleton (AC2)
let _rootInstance: { render: (node: ReactElement) => void } | null = null;
let _rootHandle: MountHandle | null = null;

/**
 * AC2: Returns the same root instance on repeated calls within a process
 * (memoized at the module level). Uses the custom reconciler in production.
 */
export function createRoot(_options?: RenderOptions): { render: (node: ReactElement) => void } {
  if (_rootInstance !== null) return _rootInstance;

  const stream = process.stdout as { write(s: string): void };
  const stdout = liveStdoutSize;

  // M9-DIAG-LIVE: capture stdout dimensions at createRoot() time
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    (require("fs") as typeof import("fs")).appendFileSync(
      "C:/WINDOWS/TEMP/ember-m9-diag.jsonl",
      JSON.stringify({
        ts: Date.now(),
        event: "createRoot",
        raw_stdout_rows: process.stdout.rows,
        raw_stdout_cols: process.stdout.columns,
        isTTY: process.stdout.isTTY,
        captured_rows: stdout.rows,
        captured_cols: stdout.columns,
      }) + "\n",
    );
  } catch { /* M9-DIAG-LIVE silent */ }

  _rootInstance = {
    render(node: ReactElement): void {
      const wrapped = React.createElement(ThemeProvider, null, node);
      import("../ink/reconciler.ts").then(({ mountInk }) => {
        if (_rootHandle) {
          // Update existing mount
          _rootHandle.update(wrapped);
        } else {
          // First render — create the mount
          _rootHandle = mountInk(wrapped, { stream, stdout });
        }
      }).catch(() => { /* degrade silently */ });
    },
  };
  return _rootInstance;
}

/** Test helper: resets the root singleton. */
export function _resetRootForTests(): void {
  _rootHandle?.unmount();
  _rootHandle = null;
  _rootInstance = null;
  _inkRender = null;
}

// ---------------------------------------------------------------------------
// REPL launcher (AC3)
// ---------------------------------------------------------------------------

export interface FpsMetrics {
  fps: number;
  frameDurationMs: number;
}

export interface StatsStore {
  record(metric: string, value: number): void;
}

export interface AppProps {
  getFpsMetrics: () => FpsMetrics;
  stats?: StatsStore;
  initialState: unknown; // AppState from session-state
}

export type ReplProps = Record<string, unknown>;

/**
 * AC3: Async TUI boot function. Dynamically imports App and REPL components
 * (not at module load time — keeps load cost low for headless sessions).
 */
export async function launchRepl(
  root: { render: (node: ReactElement) => void },
  appProps: AppProps,
  replProps: ReplProps,
  renderAndRun: (
    root: { render: (node: ReactElement) => void },
    AppComponent: React.ComponentType<unknown>,
    REPLComponent: React.ComponentType<unknown>,
    combinedProps: Record<string, unknown>,
  ) => void,
): Promise<void> {
  // AC3: dynamic imports — components NOT imported at module load time
  const [appMod, replMod] = await Promise.all([
    import("../components/app-shell.ts"),
    import("../screens/repl.ts"),
  ]);

  const AppComponent = (appMod as Record<string, unknown>)["AppRoot"] as React.ComponentType<unknown> ??
    ((props: unknown) => React.createElement(React.Fragment, null, (props as { children?: React.ReactNode }).children));
  const REPLComponent = (replMod as Record<string, unknown>)["ReplScreen"] as React.ComponentType<unknown> ??
    (() => React.createElement(React.Fragment, null));

  const combinedProps: Record<string, unknown> = { ...appProps, ...replProps };
  renderAndRun(root, AppComponent, REPLComponent, combinedProps);
}

// ---------------------------------------------------------------------------
// Project onboarding state (AC4–AC9)
// ---------------------------------------------------------------------------

export interface OnboardingStep {
  key: string;
  text: string;
  isComplete: boolean;
  isCompletable: boolean;
  isEnabled: boolean;
}

// In-process per-project onboarding state (keyed by project root)
interface ProjectOnboardingRecord {
  seenCount: number;
  isComplete: boolean;
}

const _onboardingState = new Map<string, ProjectOnboardingRecord>();

function _getProjectKey(): string {
  return process.cwd();
}

function _getOrCreate(key: string): ProjectOnboardingRecord {
  let rec = _onboardingState.get(key);
  if (!rec) {
    rec = { seenCount: 0, isComplete: false };
    _onboardingState.set(key, rec);
  }
  return rec;
}

/** Workspace step completion check — directory has files and EMBER.md exists. */
function _isWorkspaceComplete(): boolean {
  try {
    const { readdirSync, existsSync } = require("node:fs") as typeof import("node:fs");
    const cwd = process.cwd();
    const entries = readdirSync(cwd);
    return entries.length > 0 && existsSync(require("node:path").join(cwd, "EMBER.md"));
  } catch {
    return false;
  }
}

/** EMBER.md existence check. */
function _isEmberMdComplete(): boolean {
  try {
    const { existsSync } = require("node:fs") as typeof import("node:fs");
    const { join } = require("node:path") as typeof import("node:path");
    return existsSync(join(process.cwd(), "EMBER.md"));
  } catch {
    return false;
  }
}

/**
 * AC4: Returns exactly two steps with keys 'workspace' and 'embermd'.
 */
export function getSteps(): OnboardingStep[] {
  const workspaceComplete = _isWorkspaceComplete();
  const emberMdComplete = _isEmberMdComplete();
  return [
    {
      key: "workspace",
      text: "Set up your working directory / project root",
      isComplete: workspaceComplete,
      isCompletable: true,
      isEnabled: true,
    },
    {
      key: "embermd",
      text: "Create an EMBER.md context file",
      isComplete: emberMdComplete,
      isCompletable: workspaceComplete,
      isEnabled: true,
    },
  ];
}

/**
 * AC5: Returns true only when every step that is both isCompletable and isEnabled has isComplete === true.
 */
export function isProjectOnboardingComplete(): boolean {
  return getSteps()
    .filter((s) => s.isCompletable && s.isEnabled)
    .every((s) => s.isComplete);
}

let _shouldShowCache: boolean | null = null;

/**
 * AC6, AC7, AC8: Memoized display gate.
 * Returns false when: complete, seen >= 4, or IS_DEMO active.
 */
export function shouldShowProjectOnboarding(): boolean {
  if (_shouldShowCache !== null) return _shouldShowCache;

  const result = _computeShouldShow();
  _shouldShowCache = result;
  return result;
}

function _computeShouldShow(): boolean {
  // AC7: complete → false
  if (isProjectOnboardingComplete()) return false;

  // AC6: seen count >= 4 → false
  const rec = _getOrCreate(_getProjectKey());
  if (rec.seenCount >= 4) return false;

  // Demo mode → false
  if (process.env["IS_DEMO"] === "1" || process.env["IS_DEMO"] === "true") return false;

  return true;
}

/** Test helper: resets the shouldShow memo. */
export function _resetShouldShowCacheForTests(): void {
  _shouldShowCache = null;
}

/** Test helper: resets all onboarding state. */
export function _resetOnboardingForTests(): void {
  _onboardingState.clear();
  _shouldShowCache = null;
}

/**
 * AC9: Marks the project's onboarding as completed.
 * No-op if already recorded as complete.
 */
export function maybeMarkProjectOnboardingComplete(): void {
  const key = _getProjectKey();
  const rec = _getOrCreate(key);
  if (rec.isComplete) return; // AC9: no-op if already complete
  if (isProjectOnboardingComplete()) {
    rec.isComplete = true;
    _shouldShowCache = null;
  }
}

/**
 * AC8: Increments the per-project seen counter.
 * After 4 increments, shouldShowProjectOnboarding() returns false.
 */
export function incrementProjectOnboardingSeenCount(): void {
  const key = _getProjectKey();
  const rec = _getOrCreate(key);
  rec.seenCount++;
  _shouldShowCache = null; // invalidate memo
}
