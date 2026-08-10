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
import type { ModelSeatState } from "../entrypoints/model-seat.ts";

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

/**
 * Exact status-bar text in bypass-permissions mode. Issue #1044 (operator demand,
 * 2026-07-24 screenshot): the always-on keybinding-advertisement chrome ("(shift+tab to
 * cycle)", "esc to interrupt", "ctrl+t to hide|show tasks") is removed from the bar --
 * the keybindings themselves stay live (useInput below is untouched). Only the minimal
 * mode indicator (glyph + label) survives, per the "broken must LOOK broken" precedent
 * (a bypass session must stay visually distinguishable from a regular one).
 */
export const BYPASS_STATUS_TEXT = `${BYPASS_GLYPH} bypass permissions on`;

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
 * Returns the status bar text for the given permission mode. `tasksVisible` is accepted
 * for call-site compatibility (task-panel toggle still lives via ctrl+t, see useInput in
 * StatusLine) but no longer changes the rendered text -- issue #1044 removed the
 * keybinding-hint chrome ("(shift+tab to cycle)", "esc to interrupt", "ctrl+t to
 * hide|show tasks") from the bar. When mode is "bypass" this equals BYPASS_STATUS_TEXT
 * exactly.
 */
export function statusBarText(mode: PermissionMode, _tasksVisible: boolean): string {
  const glyph = modeGlyph(mode);
  const modeLabel = mode === "bypass" ? "bypass permissions on" : "sandbox";
  return `${glyph} ${modeLabel}`;
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
// RoundtripAgeIndicator — issue #239 final acceptance clause: "Status line
// shows last-successful-model-roundtrip age." Unlike DegradedBanner (hidden
// while the circuit is closed/healthy), this is meant to render ALWAYS --
// its whole purpose is telling a wedged session (age climbs without bound,
// no successful roundtrip in a long time) apart from an idle-but-healthy one
// (just no recent traffic), even before any breaker has ever tripped.
// ---------------------------------------------------------------------------

export interface RoundtripAgeState {
  /** Epoch ms of the most recent successful model roundtrip, or null if none yet. */
  lastSuccessAt: number | null;
}

/** Formats a duration compactly: 900 -> "900ms", 45000 -> "45s", 125000 -> "2m5s". */
export function formatRoundtripAgeDuration(ageMs: number): string {
  const clamped = Math.max(0, ageMs);
  if (clamped < 1000) return `${Math.round(clamped)}ms`;
  const totalSec = Math.floor(clamped / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}m${sec}s`;
}

/**
 * Pure formatter: "last roundtrip <age> ago" once a call has ever succeeded,
 * or "no roundtrip yet" before the first one. `now` is injectable for tests.
 */
export function formatRoundtripAgeText(roundtripAge: RoundtripAgeState, now: number): string {
  if (roundtripAge.lastSuccessAt == null) return "no roundtrip yet";
  const ageMs = Math.max(0, now - roundtripAge.lastSuccessAt);
  return `last roundtrip ${formatRoundtripAgeDuration(ageMs)} ago`;
}

export interface RoundtripAgeIndicatorProps {
  roundtripAge: RoundtripAgeState;
  /** Current time (epoch ms); injectable for tests, defaults to Date.now(). */
  now?: number;
}

/** Always-visible status-bar segment — never hidden like DegradedBanner/OutageBanner,
 *  since showing liveness (or its absence) even when nothing else is active is the point. */
export function RoundtripAgeIndicator({ roundtripAge, now }: RoundtripAgeIndicatorProps): React.ReactElement {
  const resolvedNow = now ?? Date.now();
  return React.createElement(Text, { dimColor: true }, formatRoundtripAgeText(roundtripAge, resolvedNow));
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

/** Deterministic operator-facing model-seat state.  A selected owner label may
 * be shown while ABSENT/LOADING; endpoint and VRAM are disclosed only from the
 * existing Ember Lab resident projection (or as explicit unknown VRAM). */
export function formatModelSeatState(state: ModelSeatState): string {
  const phase = state.phase.toLowerCase();
  const owner = state.owner ? ` owner=${state.owner}` : "";
  const vram = state.vramBytes != null
    ? ` vram=${state.vramBytes}`
    : state.phase === "RESIDENT" ? " vram=unknown" : "";
  return `model seat ${phase}${owner}${vram}`;
}

export interface ModelMetricsBarProps {
  metrics: ModelMetrics;
}

/** Inline status-bar segment rendering live model metrics in cyan. */
export function ModelMetricsBar({ metrics }: ModelMetricsBarProps): React.ReactElement {
  return React.createElement(Text, { color: "cyan", dimColor: true }, formatModelMetrics(metrics));
}

// ---------------------------------------------------------------------------
// Width-aware segment reflow (legibility bar, 2026-07-26): the bar row used to append the mode
// indicator, the mode text ("bypass permissions on"), the model-metrics meter, and the roundtrip
// indicator with no width accounting at all — a narrow terminal let the outer renderer silently
// hard-clip the row mid-word ("bypass permissions on ·" with nothing after it and no marker).
// The core identity text is never dropped or truncated as long as it alone fits; DECORATIONS
// (the optional trailing segments) disappear in priority order under width pressure instead —
// "the layout reflows" for a status line means fewer segments, not a clipped one.
// ---------------------------------------------------------------------------

/** One optional trailing segment (its own separator is implicit: SEGMENT_SEPARATOR + text). */
export interface StatusBarOptionalSegment {
  key: string;
  text: string;
}

export interface FittedStatusBarLine {
  /** The core text, unmodified unless it alone exceeds `width` (then marker-truncated). */
  core: string;
  /** Optional segments that survive, in their original order. */
  kept: StatusBarOptionalSegment[];
}

/** Chooses which optional segments survive at `width` columns, dropping from the END of
 *  `optional` (lowest priority — callers order `optional` highest-priority first) until the
 *  core + surviving segments fit. `width` undefined/non-finite means "no constraint known yet"
 *  (e.g. first render before layout settles) — nothing is dropped. The core itself is truncated
 *  with a visible "…" marker only when it alone cannot fit even with zero optional segments —
 *  never a silent clip. */
export function fitStatusBarLine(
  core: string,
  optional: StatusBarOptionalSegment[],
  width: number | undefined,
): FittedStatusBarLine {
  if (width === undefined || !Number.isFinite(width) || width <= 0) return { core, kept: optional };
  const segmentWidth = (s: StatusBarOptionalSegment): number => SEGMENT_SEPARATOR.length + s.text.length;
  let kept = optional;
  while (kept.length > 0 && core.length + kept.reduce((sum, s) => sum + segmentWidth(s), 0) > width) {
    kept = kept.slice(0, -1);
  }
  if (core.length <= width) return { core, kept };
  if (width === 1) return { core: "…", kept: [] };
  return { core: `${core.slice(0, width - 1)}…`, kept: [] };
}

// ---------------------------------------------------------------------------
// StatusLine — root status-bar component (uses useInput)
// ---------------------------------------------------------------------------

export interface StatusLineProps {
  permissionMode: PermissionModeState;
  /** No interrupt accelerator is advertised until a real cancellation path exists. */
  interrupt?: InterruptHandler;
  taskPanel: TaskPanelState;
  /** Live owned-training state. Required so the Repl cannot silently detach the render seam. */
  telemetry: TelemetryState;
  coordinator?: CoordinatorAgentState;
  effort?: EffortCalloutState;
  /** Current cognitive mode; absent → defaults to "observe". Never blank, never crash. */
  cognitiveMode?: CognitiveMode;
  /** Live inference metrics from the model server; absent → meter hidden. */
  modelMetrics?: ModelMetrics;
  /** Live model-seat lifecycle, projected by the existing seat authority. */
  modelSeat?: ModelSeatState;
  /** issue #239: circuit-breaker degraded state; absent/inactive → banner hidden. */
  degraded?: DegradedBannerState;
  /** issue #475: planned-outage marker state; absent/inactive → banner hidden. Rendered
   *  ABOVE the degraded banner — it explains WHY the model may be unreachable, so the
   *  operator reads the "planned" context before the "degraded" symptom. */
  outage?: OutageBannerState;
  /** issue #239 final acceptance clause: last-successful-model-roundtrip age.
   *  Absent → indicator hidden (no guarded client wired yet); present → always rendered,
   *  healthy or degraded alike, so a wedge is visible even without a tripped circuit. */
  roundtripAge?: RoundtripAgeState;
  /** Render only the single bounded base bar; all transient detail rows remain in state. */
  compact?: boolean;
  /** Available column width for the bar row (mainColumnWidth from the caller). Absent → no
   *  width constraint is applied (legacy behavior). Legibility bar, 2026-07-26: without this,
   *  the bar row had no way to know it was about to overflow the pane it renders in. */
  width?: number;
}

export function StatusLine({
  permissionMode,
  taskPanel,
  telemetry,
  coordinator,
  effort,
  cognitiveMode,
  modelMetrics,
  modelSeat,
  degraded,
  outage,
  roundtripAge,
  compact = false,
  width,
}: StatusLineProps): React.ReactElement {
  useInput((_input, key) => {
    if (key.ctrl && _input === "t") { taskPanel.toggle(); return; }
  });

  const text = statusBarText(permissionMode.mode, compact ? false : taskPanel.visible);
  const modeIndicator = renderModeIndicator(cognitiveMode ?? "observe", false);
  const telemetryLabel = compact ? null : telemetryMemoKey(telemetry);

  // Core = "<mode glyph+label> · <bypass/regular text>" — the identity the operator must always
  // be able to read. Optional segments are ordered highest-priority FIRST: model metrics (ember's
  // unique-capability meter) survive longer than the roundtrip age indicator when width runs out.
  const coreText = `${modeIndicator}${SEGMENT_SEPARATOR}${text}`;
  const modelMetricsText = !compact && modelMetrics != null ? formatModelMetrics(modelMetrics) : null;
  // The seat lifecycle is control-plane state, not optional telemetry: keep
  // absent/loading/resident visible even in compact mode.
  const modelSeatText = modelSeat != null ? formatModelSeatState(modelSeat) : null;
  const roundtripText = !compact && roundtripAge != null ? formatRoundtripAgeText(roundtripAge, Date.now()) : null;
  const optionalSegments: StatusBarOptionalSegment[] = [
    ...(modelMetricsText != null ? [{ key: "metrics", text: modelMetricsText }] : []),
    ...(roundtripText != null ? [{ key: "roundtrip", text: roundtripText }] : []),
  ];
  const fitted = fitStatusBarLine(coreText, optionalSegments, width);
  const keptKeys = new Set(fitted.kept.map((s) => s.key));
  const coreOverflowed = fitted.core !== coreText;

  return React.createElement(
    // #561 P0-A: StatusLine is fixed bottom chrome, never a flex-shrink target — see the same
    // comment in prompt-input.ts. Without flexShrink:0, a transcript content flood proportionally
    // shrinks this box toward 0 rows and it vanishes from the frame.
    Box,
    { flexDirection: "column", flexShrink: 0 },
    !compact && outage != null
      ? React.createElement(OutageBanner, { key: "outage", outage })
      : null,
    !compact && degraded != null
      ? React.createElement(DegradedBanner, { key: "degraded", degraded })
      : null,
    !compact && effort != null
      ? React.createElement(EffortCallout, { key: "effort", effort })
      : null,
    !compact && coordinator != null
      ? React.createElement(CoordinatorAgentStatus, { key: "coord", coordinator })
      : null,
    modelSeatText != null
      ? React.createElement(Text, { key: "model-seat", color: "cyan", dimColor: true }, modelSeatText)
      : null,
    !compact && taskPanel.visible
      ? React.createElement(TaskListV2, { key: "tasks", tasks: taskPanel.tasks })
      : null,
    telemetryLabel != null
      ? React.createElement(Text, { key: "telemetry", color: "cyan", dimColor: true, wrap: "truncate-end" }, telemetryLabel)
      : null,
    React.createElement(
      Box,
      { key: "bar", flexDirection: "row", height: compact ? 1 : undefined, overflow: compact ? "hidden" : undefined },
      // Legibility bar (2026-07-26): the core identity text is never dropped and, once it alone
      // no longer fits `width`, renders as ONE marker-truncated string (fitted.core) instead of
      // three separate always-present fragments that the outer box used to hard-clip raw
      // ("bypass permissions on ·" with nothing after and no marker). coreOverflowed only ever
      // happens at pathologically narrow widths — every normal width keeps the original
      // mode/sep/text coloring.
      coreOverflowed
        ? React.createElement(Text, { key: "core", dimColor: true, wrap: "truncate-end" }, fitted.core)
        : React.createElement(React.Fragment, { key: "core" },
            React.createElement(Text, { key: "mode", dimColor: true, wrap: "truncate-end" }, modeIndicator),
            React.createElement(Text, { key: "sep", dimColor: true, wrap: "truncate-end" }, SEGMENT_SEPARATOR),
            React.createElement(Text, { key: "text", wrap: "truncate-end" }, text),
          ),
      // Live model metrics meter — absent when no server is connected, OR dropped first under
      // width pressure so the core identity text above always survives.
      // Neither competitor can show local VRAM/throughput; this scores 0 for them.
      !compact && modelMetrics != null && keptKeys.has("metrics")
        ? React.createElement(React.Fragment, { key: "metrics" },
            React.createElement(Text, { key: "msep", dimColor: true }, SEGMENT_SEPARATOR),
            React.createElement(ModelMetricsBar, { key: "mbar", metrics: modelMetrics }),
          )
        : null,
      // issue #239: always-visible last-successful-roundtrip age — never hidden the way
      // DegradedBanner is UNLESS width pressure demands it (legibility bar takes priority over
      // "never hidden": an unreadable wedge indicator helps nobody).
      !compact && roundtripAge != null && keptKeys.has("roundtrip")
        ? React.createElement(React.Fragment, { key: "roundtrip" },
            React.createElement(Text, { key: "rsep", dimColor: true }, SEGMENT_SEPARATOR),
            React.createElement(RoundtripAgeIndicator, { key: "rbar", roundtripAge }),
          )
        : null,
    ),
  );
}
