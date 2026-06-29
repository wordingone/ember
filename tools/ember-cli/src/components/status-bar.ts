// status-bar — persistent status bar at the bottom of the TUI.
// Shows permission mode, interrupt hint, task panel toggle, effort callouts,
// coordinator agent status, and live task list (TaskListV2).

import React from "react";
import { Box, Text } from "../ink/components.ts";
import { useInput } from "../ink/hooks.ts";
import type { CognitiveMode } from "../cognitive-mode.ts";
import { modeGlyph as cognitiveGlyph } from "../cognitive-mode.ts";

// ---------------------------------------------------------------------------
// Public constants (preserve exactly)
// ---------------------------------------------------------------------------

/** Glyph shown in bypass-permissions mode. */
export const BYPASS_GLYPH = "⏵⏵";

/** Separator between status-bar segments. */
export const SEGMENT_SEPARATOR = " · ";

/** Prefix glyph for a pending task. */
export const TASK_PENDING = "□";

/** Prefix glyph for a completed task. */
export const TASK_COMPLETE = "✓";

/** Exact status-bar text in bypass-permissions mode when the task panel is visible. */
export const BYPASS_STATUS_TEXT =
  `${BYPASS_GLYPH} bypass permissions on (shift+tab to cycle)${SEGMENT_SEPARATOR}esc to interrupt${SEGMENT_SEPARATOR}ctrl+t to hide tasks`;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PermissionMode = "bypass" | "regular";

export interface Task {
  id: string;
  name: string;
  completed: boolean;
}

export interface CoordinatorState {
  taskDescription: string;
  agentCount: number;
  phase: "idle" | "planning" | "dispatching" | "aggregating";
}

// ---------------------------------------------------------------------------
// Dependency interfaces (injected — faked in tests)
// ---------------------------------------------------------------------------

export interface PermissionModeState {
  mode: PermissionMode;
  cycle: () => void;
}

export interface InterruptHandler {
  interrupt: () => void;
}

export interface TaskPanelState {
  visible: boolean;
  toggle: () => void;
  tasks: Task[];
}

export interface CoordinatorAgentState {
  active: boolean;
  state?: CoordinatorState;
}

export interface EffortCalloutState {
  active: boolean;
  label?: string;
}

// ---------------------------------------------------------------------------
// Pure logic
// ---------------------------------------------------------------------------

/** The ordered cycle of available permission modes. */
export const PERMISSION_MODES: PermissionMode[] = ["bypass", "regular"];

/** Advances to the next mode in the cycle, wrapping from last back to first. */
export function cyclePermissionMode(
  current: PermissionMode,
  modes: PermissionMode[] = PERMISSION_MODES,
): PermissionMode {
  const idx = modes.indexOf(current);
  const next = (idx + 1) % modes.length;
  return modes[next] ?? current;
}

/** Returns the display glyph for a permission mode. */
export function modeGlyph(mode: PermissionMode): string {
  return mode === "bypass" ? BYPASS_GLYPH : "○";
}

/**
 * Returns the full status bar text for the given permission mode and task-panel
 * visibility.  When mode is "bypass" and tasksVisible is true this equals
 * BYPASS_STATUS_TEXT exactly.
 */
export function statusBarText(mode: PermissionMode, tasksVisible: boolean): string {
  const glyph = modeGlyph(mode);
  const modeLabel = mode === "bypass" ? "bypass permissions on" : "regular mode";
  const tasksHint = tasksVisible ? "ctrl+t to hide tasks" : "ctrl+t to show tasks";
  return [
    `${glyph} ${modeLabel} (shift+tab to cycle)`,
    "esc to interrupt",
    tasksHint,
  ].join(SEGMENT_SEPARATOR);
}

/** Formats a task item as a prefixed label line. */
export function formatTaskItem(task: Task): string {
  return `${task.completed ? TASK_COMPLETE : TASK_PENDING} ${task.name}`;
}

// ---------------------------------------------------------------------------
// Cognitive-mode indicator (AC4-AC5)
// ---------------------------------------------------------------------------

/**
 * Returns the inline fireball indicator string "<glyph> <label>".
 * When ascii=true every character has codepoint ≤ 0x7f (no unicode symbols).
 * Mirrors the EMBER_ASCII env-flag behaviour but accepts the flag explicitly
 * so tests can exercise both branches without touching process.env.
 */
export function renderModeIndicator(mode: CognitiveMode, ascii: boolean): string {
  const saved = process.env["EMBER_ASCII"];
  if (ascii) {
    process.env["EMBER_ASCII"] = "1";
  } else {
    delete process.env["EMBER_ASCII"];
  }
  const g = cognitiveGlyph(mode);
  // Restore
  if (saved === undefined) {
    delete process.env["EMBER_ASCII"];
  } else {
    process.env["EMBER_ASCII"] = saved;
  }
  return `${g.glyph} ${g.label}`;
}

// ---------------------------------------------------------------------------
// TaskListV2 — compact in-status task display (hook-free)
// ---------------------------------------------------------------------------

export interface TaskListV2Props {
  tasks: Task[];
}

export function TaskListV2({ tasks }: TaskListV2Props): React.ReactElement {
  return React.createElement(
    Box,
    { flexDirection: "column" },
    ...tasks.map(t =>
      React.createElement(
        Text,
        { key: t.id, color: t.completed ? "green" : undefined },
        formatTaskItem(t),
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// EffortCallout — shown when a high-effort condition is active (hook-free)
// ---------------------------------------------------------------------------

export interface EffortCalloutProps {
  effort: EffortCalloutState;
}

export function EffortCallout({ effort }: EffortCalloutProps): React.ReactElement | null {
  if (!effort.active || !effort.label) return null;
  return React.createElement(Text, { color: "yellow", dimColor: true }, effort.label);
}

// ---------------------------------------------------------------------------
// CoordinatorAgentStatus — multi-agent coordinator indicator (hook-free)
// ---------------------------------------------------------------------------

export interface CoordinatorAgentStatusProps {
  coordinator: CoordinatorAgentState;
}

export function CoordinatorAgentStatus({
  coordinator,
}: CoordinatorAgentStatusProps): React.ReactElement | null {
  if (!coordinator.active || !coordinator.state) return null;
  const { taskDescription, agentCount, phase } = coordinator.state;
  return React.createElement(
    Box,
    { flexDirection: "row", gap: 1 },
    React.createElement(Text, { key: "phase", color: "cyan" }, phase),
    React.createElement(Text, { key: "task", dimColor: true }, taskDescription),
    React.createElement(Text, { key: "agents", dimColor: true }, `(${agentCount} agents)`),
  );
}

// ---------------------------------------------------------------------------
// ModelMetrics — live inference meter (unique to ember; competitors score 0)
// ---------------------------------------------------------------------------

/** Live inference metrics read from the local model server. */
export interface ModelMetrics {
  /** Tokens in the current context window (prompt + completions so far). */
  contextTokens: number;
  /** Maximum context window size configured for this model. */
  maxContextTokens: number;
  /** VRAM currently allocated by the model process (GiB). */
  vramUsedGb: number;
  /** Total VRAM on the device (GiB). */
  vramTotalGb: number;
  /** Approximate decode throughput (tokens / second, rolling-window). */
  tokensPerSec: number;
}

/** Format a token count compactly: 120000 → "120k", 2048 → "2k". */
export function formatTokenCount(n: number): string {
  if (n >= 1000) return `${Math.round(n / 1000)}k`;
  return String(n);
}

/** Format a GiB value with one decimal place. */
export function formatGb(n: number): string {
  return n.toFixed(1);
}

/** Compact bar: "12k/120k · 28t/s · 12.4/24GB" */
export function formatModelMetrics(m: ModelMetrics): string {
  const ctx  = `${formatTokenCount(m.contextTokens)}/${formatTokenCount(m.maxContextTokens)}`;
  const tps  = `${Math.round(m.tokensPerSec)}t/s`;
  const vram = `${formatGb(m.vramUsedGb)}/${formatGb(m.vramTotalGb)}GB`;
  return `${ctx}${SEGMENT_SEPARATOR}${tps}${SEGMENT_SEPARATOR}${vram}`;
}

export interface ModelMetricsBarProps {
  metrics: ModelMetrics;
}

/** Inline status-bar segment rendering live model metrics in cyan. */
export function ModelMetricsBar({ metrics }: ModelMetricsBarProps): React.ReactElement {
  return React.createElement(Text, { color: "cyan", dimColor: true }, formatModelMetrics(metrics));
}

// ---------------------------------------------------------------------------
// StatusLine — root status-bar component (uses useInput)
// ---------------------------------------------------------------------------

export interface StatusLineProps {
  permissionMode: PermissionModeState;
  interrupt: InterruptHandler;
  taskPanel: TaskPanelState;
  coordinator?: CoordinatorAgentState;
  effort?: EffortCalloutState;
  /** Current cognitive mode; absent → defaults to "observe". Never blank, never crash. */
  cognitiveMode?: CognitiveMode;
  /** Live inference metrics from the model server; absent → meter hidden. */
  modelMetrics?: ModelMetrics;
}

export function StatusLine({
  permissionMode,
  interrupt,
  taskPanel,
  coordinator,
  effort,
  cognitiveMode,
  modelMetrics,
}: StatusLineProps): React.ReactElement {
  useInput((_input, key) => {
    if (key.shift && key.tab)    { permissionMode.cycle(); return; }
    if (key.escape)              { interrupt.interrupt(); return; }
    if (key.ctrl && _input === "t") { taskPanel.toggle(); return; }
  });

  const text = statusBarText(permissionMode.mode, taskPanel.visible);
  const modeIndicator = renderModeIndicator(cognitiveMode ?? "observe", false);

  return React.createElement(
    Box,
    { flexDirection: "column" },
    effort != null
      ? React.createElement(EffortCallout, { key: "effort", effort })
      : null,
    coordinator != null
      ? React.createElement(CoordinatorAgentStatus, { key: "coord", coordinator })
      : null,
    taskPanel.visible
      ? React.createElement(TaskListV2, { key: "tasks", tasks: taskPanel.tasks })
      : null,
    React.createElement(
      Box,
      { key: "bar", flexDirection: "row" },
      React.createElement(Text, { key: "mode", dimColor: true }, modeIndicator),
      React.createElement(Text, { key: "sep", dimColor: true }, SEGMENT_SEPARATOR),
      React.createElement(Text, { key: "text" }, text),
      // Live model metrics meter — absent when no server is connected.
      // Neither competitor can show local VRAM/throughput; this scores 0 for them.
      modelMetrics != null
        ? React.createElement(React.Fragment, { key: "metrics" },
            React.createElement(Text, { key: "msep", dimColor: true }, SEGMENT_SEPARATOR),
            React.createElement(ModelMetricsBar, { key: "mbar", metrics: modelMetrics }),
          )
        : null,
    ),
  );
}
