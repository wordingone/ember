// status-bar — persistent status bar at the bottom of the TUI.
// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Shows permission mode, interrupt hint, task panel toggle, effort callouts,
// coordinator agent status, and live task list (TaskListV2).
//
// #518: this used to also mount ActivityFeedPane -- completed-activity ticker lines pinned
// here, next to the input box (the operator's exact complaint: "activity lines with timestamps
// at the bottom of the statusline/input box... which is just... stupid"). That pane is gone from
// this file entirely; activity events now render as ActivityTranscriptBlock cards in the
// scrolling conversation history (see components/activity-feed-pane.ts, screens/repl.ts). The
// status bar keeps ONLY genuinely live, in-flight state (degraded banner, effort callout,
// coordinator phase, task list) -- never a feed of things that already happened.

import React from "react";
import { Box, Text } from "../ink/components.ts";
import { useInput } from "../ink/hooks.ts";
import type { CognitiveMode } from "../cognitive-mode.ts";
import { modeGlyph as cognitiveGlyph } from "../cognitive-mode.ts";
import { telemetryMemoKey } from "../services/telemetry-label.ts";
import type { TelemetryState } from "../services/telemetry-watch.ts";

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
// DegradedBanner — issue #239: persistent surface for a model-client circuit
// breaker in the OPEN (or half-open probing) state. "broken must LOOK
// broken" -- the operator's law this exists to satisfy: the 20h wedge
// incident had zero visible signal distinguishing "wedged" from "idle".
// Follows EffortCallout's hook-free, hidden-when-inactive convention.
// ---------------------------------------------------------------------------

export interface DegradedBannerState {
  active: boolean;
  endpoint?: string | null;
  lastStatus?: number | null;
  lastReason?: string | null;
  attemptCount?: number;
  /** Epoch ms the next half-open probe becomes eligible. */
  nextProbeAt?: number;
  /** True while a half-open probe attempt is currently in flight. */
  probing?: boolean;
}

/** Formats the countdown to the next half-open probe, e.g. "next probe in 15s". */
function formatProbeCountdown(nextProbeAt: number, now: number): string {
  const remainingMs = Math.max(0, nextProbeAt - now);
  const remainingSec = Math.ceil(remainingMs / 1000);
  return remainingSec > 0 ? `next probe in ${remainingSec}s` : "probing now";
}

/**
 * Pure formatter: endpoint, last status/error, attempt count, next-probe
 * time -- exactly the fields the dispatch spec's acceptance criteria name.
 * Returns "" when inactive (DegradedBanner renders null in that case).
 */
export function formatDegradedBannerText(banner: DegradedBannerState, now: number): string {
  if (!banner.active) return "";
  const endpointLabel = banner.endpoint ?? "unknown endpoint";
  const statusLabel = banner.lastStatus != null
    ? `HTTP ${banner.lastStatus}`
    : (banner.lastReason ?? "error");
  const attempts = banner.attemptCount ?? 0;
  const probeLabel = banner.probing
    ? "probing…"
    : (banner.nextProbeAt != null ? formatProbeCountdown(banner.nextProbeAt, now) : "");

  const parts = [`⚠ degraded: ${endpointLabel}`, statusLabel, `attempts ${attempts}`];
  if (probeLabel) parts.push(probeLabel);
  return parts.join(SEGMENT_SEPARATOR);
}

export interface DegradedBannerProps {
  degraded: DegradedBannerState;
  /** Current time (epoch ms); injectable for tests, defaults to Date.now(). */
  now?: number;
}

export function DegradedBanner({ degraded, now }: DegradedBannerProps): React.ReactElement | null {
  if (!degraded.active) return null;
  const resolvedNow = now ?? Date.now();
  return React.createElement(Text, { color: "red" }, formatDegradedBannerText(degraded, resolvedNow));
}

// ---------------------------------------------------------------------------
// OutageBanner — issue #475: cockpit banner for the frozen planned-outage.json
// marker contract (#464). The liveness watchdogs already honor a planned-outage
// window server-side (zero failure-counting while it's in effect); this is the
// SURFACE half -- without it, a planned maintenance window and an actual crash
// look identical to an operator glancing at the pane. Follows DegradedBanner's
// hook-free, hidden-when-inactive convention exactly.
// ---------------------------------------------------------------------------

export interface OutageBannerState {
  active: boolean;
  owner?: string;
  reason?: string;
  expires?: string;
}

/**
 * Pure formatter: "PLANNED OUTAGE (<owner>): <reason> — until <expires>" per issue #475's
 * spec text. Returns "" when inactive (OutageBanner renders null in that case).
 */
export function formatOutageBannerText(banner: OutageBannerState): string {
  if (!banner.active) return "";
  const owner = banner.owner ?? "unknown";
  const reason = banner.reason ?? "no reason given";
  const expires = banner.expires ?? "unknown";
  return `PLANNED OUTAGE (${owner}): ${reason} — until ${expires}`;
}

export interface OutageBannerProps {
  outage: OutageBannerState;
}

export function OutageBanner({ outage }: OutageBannerProps): React.ReactElement | null {
  if (!outage.active) return null;
  return React.createElement(Text, { color: "yellow" }, formatOutageBannerText(outage));
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
  /** Live owned-training state. Required so the Repl cannot silently detach the render seam. */
  telemetry: TelemetryState;
  coordinator?: CoordinatorAgentState;
  effort?: EffortCalloutState;
  /** Current cognitive mode; absent → defaults to "observe". Never blank, never crash. */
  cognitiveMode?: CognitiveMode;
  /** Live inference metrics from the model server; absent → meter hidden. */
  modelMetrics?: ModelMetrics;
  /** issue #239: circuit-breaker degraded state; absent/inactive → banner hidden. */
  degraded?: DegradedBannerState;
  /** issue #475: planned-outage marker state; absent/inactive → banner hidden. Rendered
   *  ABOVE the degraded banner — it explains WHY the model may be unreachable, so the
   *  operator reads the "planned" context before the "degraded" symptom. */
  outage?: OutageBannerState;
}

export function StatusLine({
  permissionMode,
  interrupt,
  taskPanel,
  telemetry,
  coordinator,
  effort,
  cognitiveMode,
  modelMetrics,
  degraded,
  outage,
}: StatusLineProps): React.ReactElement {
  useInput((_input, key) => {
    if (key.shift && key.tab)    { permissionMode.cycle(); return; }
    if (key.escape)              { interrupt.interrupt(); return; }
    if (key.ctrl && _input === "t") { taskPanel.toggle(); return; }
  });

  const text = statusBarText(permissionMode.mode, taskPanel.visible);
  const modeIndicator = renderModeIndicator(cognitiveMode ?? "observe", false);
  const telemetryLabel = telemetryMemoKey(telemetry);

  return React.createElement(
    // #561 P0-A: StatusLine is fixed bottom chrome, never a flex-shrink target — see the same
    // comment in prompt-input.ts. Without flexShrink:0, a transcript content flood proportionally
    // shrinks this box toward 0 rows and it vanishes from the frame.
    Box,
    { flexDirection: "column", flexShrink: 0 },
    outage != null
      ? React.createElement(OutageBanner, { key: "outage", outage })
      : null,
    degraded != null
      ? React.createElement(DegradedBanner, { key: "degraded", degraded })
      : null,
    effort != null
      ? React.createElement(EffortCallout, { key: "effort", effort })
      : null,
    coordinator != null
      ? React.createElement(CoordinatorAgentStatus, { key: "coord", coordinator })
      : null,
    taskPanel.visible
      ? React.createElement(TaskListV2, { key: "tasks", tasks: taskPanel.tasks })
      : null,
    telemetryLabel != null
      ? React.createElement(Text, { key: "telemetry", color: "cyan", dimColor: true }, telemetryLabel)
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
