// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import React from "react";
import { Box, Text } from "../ink/components.ts";
import {
  ACTIVE_RUN_TTL_MS,
  type TelemetryEvent,
  type TelemetryState,
} from "../services/telemetry-watch.ts";
import {
  EMPTY_STATE_TEXT,
  formatActivityFeedLine,
  visibleActivityFeedLines,
  type ActivityFeedLine,
} from "./activity-feed-pane.ts";
import { renderChart, sparklineRow } from "../ink/chart.ts";
import { HOST_METRIC_IDS, type HostMetricId, type HostMetricSeries, type HostTelemetrySnapshot } from "../services/host-telemetry-poller.ts";

export interface OperatorSourceIdentity {
  publicCommit?: string;
  binarySha256?: string;
  /** True only when the launch/installed-binary path independently bound both values. */
  sourceBindingVerified?: boolean;
}

export interface OperatorSurfaceInput {
  telemetry: TelemetryState;
  activityLines: ActivityFeedLine[];
  sourceIdentity?: OperatorSourceIdentity;
  nowMs?: number;
  maxAgentLines?: number;
  plotWidth?: number;
  /** Path-truncation budget for the activity-feed line's path suffix, shrunk by the caller to
   *  the ACTUAL pane width (legibility bar, 2026-07-26) rather than the fixed 48-char default —
   *  a narrow pane used to hand a 48-char-budgeted line to the outer renderer, which then
   *  silently hard-clipped it further with no marker at all. */
  pathMaxLen?: number;
  /** Host telemetry snapshot from useHostTelemetryPoller — needs no run in flight. When
   *  present, the six host curves are BOUND; SOURCE UNBOUND survives only for a source that
   *  genuinely has no producer wired. */
  host?: HostTelemetrySnapshot;
}

export type OperatorRunStatus = "RUNNING" | "STALE" | "IDLE" | "OFFLINE";
export type OperatorControlAction = "START" | "PAUSE" | "RESUME" | "RESTART";

export interface OperatorSeriesPoint {
  runId: string;
  step: number;
  loss?: number;
  totalSteps?: number;
  tokensPerSecond?: number;
  learningRate?: number;
  gpuWatts?: number;
  boardEnergyJoulesTotal?: number;
  vramUsedGib?: number;
  gpuUtilizationPct?: number;
  ts: string;
}

interface OperatorMetricPoint {
  step: number;
  ts: string;
  value: number;
}

export interface OperatorSurfaceGraphs {
  runId?: string;
  points: OperatorSeriesPoint[];
  loss: string[];
  resource: string[];
  modelGrowth: string[];
  capability: string[];
  training: string[];
  checkpoints: Array<{ step: number; label: "checkpoint" }>;
  modelGrowthPoints: Array<{ step: number; ts: string; value: number }>;
  capabilityPoints: Array<{ step: number; ts: string; value: number }>;
}

export interface OperatorSurfaceSnapshot {
  status: OperatorRunStatus;
  metrics: string[];
  source: string;
  agentLines: string[];
  graphs: OperatorSurfaceGraphs;
}

function shortDigest(value: string, length: number = 12): string {
  return value.length > length ? `${value.slice(0, length)}\u2026` : value;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function sourceLine(sourceIdentity: OperatorSourceIdentity | undefined): string {
  const commit = sourceIdentity?.publicCommit;
  const binary = sourceIdentity?.binarySha256;
  if (
    sourceIdentity?.sourceBindingVerified !== true ||
    !commit || !/^[0-9a-f]{40}$/i.test(commit) ||
    !binary || !/^[0-9a-f]{64}$/i.test(binary)
  ) {
    return "SOURCE UNVERIFIED/UNBOUND";
  }
  return `source ${shortDigest(commit)} binary ${shortDigest(binary)}`;
}

function eventRunId(event: TelemetryEvent): string | undefined {
  const runId = event.payload["run_id"];
  return typeof runId === "string" && runId.length > 0 ? runId : undefined;
}

function eventTime(event: TelemetryEvent): number {
  const time = Date.parse(event.ts);
  return Number.isFinite(time) ? time : NaN;
}

function validTrainStep(event: TelemetryEvent, nowMs: number = Date.now()): OperatorSeriesPoint | undefined {
  if (event.kind !== "train_step") return undefined;
  const runId = eventRunId(event);
  const step = event.payload["step"];
  const timestamp = eventTime(event);
  if (!runId || !finiteNumber(step) || !Number.isInteger(step) || step < 1 || !finiteNumber(timestamp) || timestamp > nowMs) return undefined;
  const lossValue = event.payload["loss"];
  const loss = finiteNumber(lossValue) ? lossValue : undefined;
  const directNonnegative = (value: unknown): number | undefined =>
    finiteNumber(value) && value >= 0 ? value : undefined;
  const tokensPerSecond = directNonnegative(event.payload["tokens_per_second"]);
  const learningRate = directNonnegative(event.payload["learning_rate"]);
  const gpuWatts = directNonnegative(event.payload["gpu_watts"]);
  const boardEnergyJoulesTotal = directNonnegative(event.payload["board_energy_joules_total"]);
  const free = event.payload["free_gib"];
  const total = event.payload["total_gib"];
  const vramUsedGib = finiteNumber(free) && finiteNumber(total) && free >= 0 && total > 0 && free <= total
    ? total - free
    : undefined;
  const gpuValue = event.payload["gpu_utilization_pct"];
  const gpuUtilizationPct = finiteNumber(gpuValue) && gpuValue >= 0 && gpuValue <= 100 ? gpuValue : undefined;
  if (loss === undefined && tokensPerSecond === undefined && learningRate === undefined && gpuWatts === undefined && boardEnergyJoulesTotal === undefined && vramUsedGib === undefined && gpuUtilizationPct === undefined) return undefined;
  const totalStepsValue = event.payload["total_steps"];
  const totalSteps = finiteNumber(totalStepsValue) && Number.isInteger(totalStepsValue) && totalStepsValue > 0 ? totalStepsValue : undefined;
  return { runId, step, totalSteps, loss, tokensPerSecond, learningRate, gpuWatts, boardEnergyJoulesTotal, vramUsedGib, gpuUtilizationPct, ts: event.ts };
}

interface SelectedRunEvidence {
  runId: string;
  latestTs: number;
}

function selectedRunEvidence(telemetry: TelemetryState, nowMs: number): SelectedRunEvidence | undefined {
  const latestByRun = new Map<string, number>();
  for (const event of telemetry.recentEvents) {
    const point = validTrainStep(event, nowMs);
    if (!point) continue;
    const timestamp = Date.parse(point.ts);
    const previous = latestByRun.get(point.runId);
    if (previous === undefined || timestamp > previous) latestByRun.set(point.runId, timestamp);
  }
  return [...latestByRun.entries()]
    .sort(([leftId, leftTs], [rightId, rightTs]) => rightTs - leftTs || (leftId < rightId ? -1 : leftId > rightId ? 1 : 0))
    .map(([runId, latestTs]) => ({ runId, latestTs }))[0];
}

const PLOT_GLYPHS = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588";

function formatTimeLabel(ts: string): string {
  const parsed = new Date(ts);
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString().slice(11, 19) : "??:??:??";
}

export const PLOT_PREFIX_WIDTH = 24;

function retainedIndices(sampleCount: number, maxPoints: number, checkpointIndices: Set<number>): number[] {
  if (sampleCount <= maxPoints) return Array.from({ length: sampleCount }, (_, index) => index);
  const count = Math.max(2, Math.min(sampleCount, Math.floor(maxPoints)));
  const required = new Set<number>([sampleCount - 1]);
  checkpointIndices.forEach((index) => { if (index >= 0 && index < sampleCount) required.add(index); });
  const selected = new Set<number>();
  const requiredSorted = [...required].sort((left, right) => left - right);
  if (requiredSorted.length > count) {
    selected.add(sampleCount - 1);
    for (let index = requiredSorted.length - 1; index >= 0 && selected.size < count; index -= 1) selected.add(requiredSorted[index]!);
  } else {
    selected.add(0);
    requiredSorted.forEach((index) => { if (selected.size < count) selected.add(index); });
    for (let index = 1; selected.size < count && index < sampleCount - 1; index += 1) selected.add(index);
  }
  selected.add(sampleCount - 1);
  return [...selected].sort((left, right) => left - right);
}

function downsampleSamples(samples: OperatorMetricPoint[], maxPoints: number, checkpointSteps: Set<number>): OperatorMetricPoint[] {
  const indices = retainedIndices(samples.length, maxPoints, new Set(samples.map((sample, index) => checkpointSteps.has(sample.step) ? index : -1).filter((index) => index >= 0)));
  return indices.map((index) => samples[index]!);
}
function alignedPlotLine(label: string, content: string): string {
  return `${label.padEnd(PLOT_PREFIX_WIDTH, " ")}${content}`;
}

function plotLines(
  title: string,
  samples: OperatorMetricPoint[],
  checkpointSteps: Set<number> = new Set(),
  maxPoints: number = 72,
): string[] {
  if (samples.length < 2) return [`${title.toUpperCase()}: INSUFFICIENT REAL HISTORY`, "INSUFFICIENT REAL HISTORY"];
  const plotted = downsampleSamples(samples, maxPoints, checkpointSteps);
  const values = plotted.map((sample) => sample.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const glyphs = values.map((value) => PLOT_GLYPHS[Math.min(7, Math.floor(span === 0 ? 7 : ((value - min) / span) * 7))]).join("");
  const axis = plotted.map((sample) => `${sample.step}@${formatTimeLabel(sample.ts)}`).join(" ");
  const lines = [
    `${title} range [${min.toFixed(2)}..${max.toFixed(2)}]`,
    `step/time ${axis}`,
    alignedPlotLine(`${title} plot `, glyphs),
  ];
  if (checkpointSteps.size > 0) {
    lines.push(alignedPlotLine("checkpoint plot ", plotted.map((sample) => checkpointSteps.has(sample.step) ? "\u25b2" : "\u00b7").join("")));
  }
  return lines;
}

function valueSamples(points: OperatorSeriesPoint[], value: (point: OperatorSeriesPoint) => number | undefined): OperatorMetricPoint[] {
  return points
    .map((point) => {
      const sample = value(point);
      return finiteNumber(sample) ? { step: point.step, ts: point.ts, value: sample } : undefined;
    })
    .filter((sample): sample is OperatorMetricPoint => sample !== undefined);
}

function eventMetricSamples(
  telemetry: TelemetryState,
  runId: string | undefined,
  kind: "model_growth" | "capability_score",
  key: "value" | "score",
  nowMs: number = Date.now(),
): OperatorMetricPoint[] {
  if (!runId) return [];
  return telemetry.recentEvents
    .filter((event) => event.kind === kind && eventRunId(event) === runId)
    .map((event) => {
      const step = event.payload["step"];
      const value = event.payload[key];
      return finiteNumber(step) && finiteNumber(value) && finiteNumber(eventTime(event)) && eventTime(event) <= nowMs
        ? { step, ts: event.ts, value }
        : undefined;
    })
    .filter((sample): sample is OperatorMetricPoint => sample !== undefined)
    .sort((left, right) => left.step - right.step || Date.parse(left.ts) - Date.parse(right.ts));
}

/**
 * "SOURCE UNBOUND" and "AWAITING FIRST SAMPLE" are different facts and must not share a
 * rendering: UNBOUND says this metric can never arrive right now (no live run to bind to);
 * AWAITING says the run IS live and could still produce it -- the run is simply not there yet
 * for this particular field. `isLive` is the selected run's RUNNING status, computed once by the
 * caller from the same evidence the rest of the pane already trusts (getOperatorRunStatus).
 */
function familyLines(title: string, samples: OperatorMetricPoint[], unbound: string, maxPoints: number, checkpointSteps: Set<number>, isLive: boolean): string[] {
  if (samples.length === 0) return [`${unbound}: ${isLive ? "AWAITING FIRST SAMPLE" : "SOURCE UNBOUND"}`];
  return plotLines(title, samples, checkpointSteps, maxPoints);
}

/** Build bounded graphs only from valid, provenance-selected events belonging to one run. */
export function buildOperatorSurfaceGraphs(telemetry: TelemetryState, plotWidth: number = 80, nowMs: number = Date.now()): OperatorSurfaceGraphs {
  const maxPoints = Math.max(2, Math.floor(plotWidth) - 8);
  const selection = selectedRunEvidence(telemetry, nowMs);
  const runId = selection?.runId;
  const rawPoints = runId
    ? telemetry.recentEvents
        .map((event) => validTrainStep(event, nowMs))
        .filter((point): point is OperatorSeriesPoint => point?.runId === runId)
        .sort((left, right) => left.step - right.step || Date.parse(left.ts) - Date.parse(right.ts))
    : [];
  let lastEnergy = Number.NEGATIVE_INFINITY;
  const points = rawPoints.map((point) => {
    if (point.boardEnergyJoulesTotal === undefined) return point;
    if (point.boardEnergyJoulesTotal < lastEnergy) {
      const { boardEnergyJoulesTotal: _rejected, ...truthfulPoint } = point;
      return truthfulPoint;
    }
    lastEnergy = point.boardEnergyJoulesTotal;
    return point;
  });
  const checkpoints = runId
    ? telemetry.recentEvents
        .filter((event) => event.kind === "checkpoint" && eventRunId(event) === runId)
        .map((event) => {
          const step = event.payload["step"];
          return finiteNumber(step) && step >= 0 && finiteNumber(eventTime(event)) && eventTime(event) <= nowMs ? { step, label: "checkpoint" as const } : undefined;
        })
        .filter((marker): marker is { step: number; label: "checkpoint" } => marker !== undefined)
        .sort((left, right) => left.step - right.step)
    : [];
  const checkpointSteps = new Set(checkpoints.map((marker) => marker.step));
  const loss = plotLines("loss", valueSamples(points, (point) => point.loss), checkpointSteps, maxPoints);
  const gpu = valueSamples(points, (point) => point.gpuUtilizationPct);
  const vram = valueSamples(points, (point) => point.vramUsedGib);
  const tokensPerSecond = valueSamples(points, (point) => point.tokensPerSecond);
  const learningRate = valueSamples(points, (point) => point.learningRate);
  const gpuWatts = valueSamples(points, (point) => point.gpuWatts);
  const boardEnergy = valueSamples(points, (point) => point.boardEnergyJoulesTotal);
  const modelGrowth = eventMetricSamples(telemetry, runId, "model_growth", "value", nowMs);
  const capability = eventMetricSamples(telemetry, runId, "capability_score", "score", nowMs);
  const latestTrainTs = selection?.latestTs;
  // Whether the selected run is live RIGHT NOW, by the same evidence the rest of the pane
  // already trusts -- gates the SOURCE UNBOUND / AWAITING FIRST SAMPLE choice below.
  const isLive = getOperatorRunStatus(telemetry, nowMs, runId) === "RUNNING";
  const decorate = (lines: string[]): string[] =>
    channelIsOffline(telemetry, runId, latestTrainTs) ? decorateHistory(lines, "OFFLINE/HISTORICAL") : lines;
  const lossLines = decorate(loss);
  const resourceLines = decorate([
    "RESOURCE EFFICIENCY",
    ...familyLines("GPU utilization %", gpu, "GPU UTILIZATION", maxPoints, checkpointSteps, isLive),
    ...familyLines("VRAM GiB", vram, "VRAM", maxPoints, checkpointSteps, isLive),
    ...familyLines("tokens/s", tokensPerSecond, "TOKENS/S", maxPoints, checkpointSteps, isLive),
    ...familyLines("learning rate", learningRate, "LEARNING RATE", maxPoints, checkpointSteps, isLive),
    ...familyLines("GPU watts", gpuWatts, "GPU WATTS", maxPoints, checkpointSteps, isLive),
    ...familyLines("board energy joules", boardEnergy, "ENERGY", maxPoints, checkpointSteps, isLive),
  ]);
  const modelGrowthLines = decorate(familyLines("model growth", modelGrowth, "MODEL GROWTH", maxPoints, checkpointSteps, isLive));
  const capabilityLines = decorate(familyLines("capability score", capability, "CAPABILITY SCORES", maxPoints, checkpointSteps, isLive));
  return {
    runId,
    points,
    loss: lossLines,
    resource: resourceLines,
    modelGrowth: modelGrowthLines,
    capability: capabilityLines,
    training: decorate(["TRAINING/LOSS", ...loss]),
    checkpoints,
    modelGrowthPoints: modelGrowth,
    capabilityPoints: capability,
  };
}

function channelIsOffline(telemetry: TelemetryState, selectedRunId?: string, latestTrainTs?: number): boolean {
  const extended = telemetry as TelemetryState & { channelStatus?: string };
  if (extended.channelStatus === "OFFLINE") return true;
  if (selectedRunId === undefined || latestTrainTs === undefined) return false;
  if (telemetry.runStatus?.runId !== selectedRunId || telemetry.runStatus.phase !== "OFFLINE") return false;
  const statusTs = Date.parse(telemetry.runStatus.lastTs);
  return Number.isFinite(statusTs) && statusTs >= latestTrainTs;
}

function decorateHistory(lines: string[], marker: "OFFLINE/HISTORICAL" | "STALE/HISTORICAL"): string[] {
  return lines.map((line) => /^(TRAINING\/LOSS|RESOURCE EFFICIENCY|MODEL GROWTH|CAPABILITY SCORES)(?::|\s|$)/.test(line)
    ? `${line} [${marker}]`
    : `${marker} ${line}`);
}
/** Derive status only from the same validated train-step evidence used by graphs. */
export function getOperatorRunStatus(telemetry: TelemetryState, nowMs: number = Date.now(), selectedRun?: string): OperatorRunStatus {
  const evidence = selectedRunEvidence(telemetry, nowMs);
  const runId = selectedRun ?? evidence?.runId;
  const latestTrainTs = evidence && runId === evidence.runId ? evidence.latestTs : undefined;
  if (channelIsOffline(telemetry, runId, latestTrainTs)) return "OFFLINE";
  if (!runId) return "IDLE";
  const eventTimes = telemetry.recentEvents
    .map((event) => validTrainStep(event, nowMs))
    .filter((point): point is OperatorSeriesPoint => point !== undefined && point.runId === runId)
    .map((point) => Date.parse(point.ts))
    .filter((timestamp): timestamp is number => finiteNumber(timestamp) && timestamp <= nowMs);
  if (eventTimes.length === 0) return "IDLE";
  const latest = Math.max(...eventTimes);
  return nowMs - latest <= ACTIVE_RUN_TTL_MS ? "RUNNING" : "STALE";
}
function newestPointByTimestamp(points: OperatorSeriesPoint[]): OperatorSeriesPoint | undefined {
  return points.reduce<OperatorSeriesPoint | undefined>((newest, point) => {
    if (!newest) return point;
    const pointTs = Date.parse(point.ts);
    const newestTs = Date.parse(newest.ts);
    return pointTs > newestTs || (pointTs === newestTs && point.step > newest.step) ? point : newest;
  }, undefined);
}
export function buildOperatorSurfaceSnapshot({
  telemetry,
  activityLines,
  sourceIdentity,
  nowMs = Date.now(),
  maxAgentLines = 6,
  plotWidth = 80,
  pathMaxLen,
}: OperatorSurfaceInput): OperatorSurfaceSnapshot {
  const rawGraphs = buildOperatorSurfaceGraphs(telemetry, plotWidth, nowMs);
  const status = getOperatorRunStatus(telemetry, nowMs, rawGraphs.runId);
  const latestPoint = newestPointByTimestamp(rawGraphs.points);
  const metrics: string[] = [];

  if (latestPoint && status === "RUNNING") {
    if (finiteNumber(latestPoint.loss)) metrics.push(`loss ${latestPoint.loss.toFixed(2)}`);
    if (finiteNumber(latestPoint.step)) {
      metrics.push(latestPoint.totalSteps !== undefined
        ? `step ${latestPoint.step}/${latestPoint.totalSteps}`
        : `step ${latestPoint.step}`);
    }
    if (finiteNumber(latestPoint.tokensPerSecond)) {
      metrics.push(`tokens/s ${latestPoint.tokensPerSecond.toFixed(1)}`);
    }
  }

  const governor = telemetry.lastGovernor;
  const validGovernor = governor
    && governor.runId === rawGraphs.runId
    && finiteNumber(governor.vramUsedGib)
    && finiteNumber(governor.vramTotalGib)
    && governor.vramTotalGib > 0
    && governor.vramUsedGib >= 0
    && governor.vramUsedGib <= governor.vramTotalGib;
  if (status === "RUNNING" && validGovernor) {
    metrics.push(`VRAM ${governor.vramUsedGib.toFixed(1)}/${governor.vramTotalGib.toFixed(1)} GiB`);
  }

  const decorateStale = (lines: string[]): string[] =>
    status === "STALE" ? decorateHistory(lines, "STALE/HISTORICAL") : lines;
  const graphs: OperatorSurfaceGraphs = status === "STALE"
    ? {
        ...rawGraphs,
        loss: decorateStale(rawGraphs.loss),
        resource: decorateStale(rawGraphs.resource),
        modelGrowth: decorateStale(rawGraphs.modelGrowth),
        capability: decorateStale(rawGraphs.capability),
        training: decorateStale(rawGraphs.training),
      }
    : rawGraphs;
  const checkpoint = telemetry.lastCheckpoint;
  if (
    status === "RUNNING" &&
    checkpoint &&
    checkpoint.runId === rawGraphs.runId
  ) {
    metrics.push(`checkpoint step ${checkpoint.step} ${shortDigest(checkpoint.checkpointManifestSha256)}`);
  }

  const visible = visibleActivityFeedLines(activityLines, maxAgentLines);
  const agentLines = visible.length > 0
    ? visible.map((line) => finiteNumber(pathMaxLen) ? formatActivityFeedLine(line, nowMs, pathMaxLen) : formatActivityFeedLine(line, nowMs))
    : [EMPTY_STATE_TEXT];

  return {
    status,
    metrics,
    source: sourceLine(sourceIdentity),
    agentLines,
    graphs,
  };
}

export interface OperatorSurfacePaneProps extends OperatorSurfaceInput {
  onControl?: (action: OperatorControlAction, runId?: string) => void;
  width?: number;
  height?: number;
  terminalColumns?: number;
  terminalRows?: number;
  /** Index into OPERATOR_CONTROL_ACTIONS currently holding keyboard traversal focus, or
   *  undefined when the pane itself does not have keyboard focus (R2b). Drives the visible
   *  focus marker — a control that is focused with no way to see which one is focused is the
   *  same failure class as a control that renders and does nothing. */
  focusedControlIndex?: number;
  /** Reason surfaced when a disabled control's accelerator or activation was attempted (R2b
   *  acceptance row 7) — silently doing nothing is the exact failure R2 was filed for. */
  disabledActionReason?: string;
}

// ---------------------------------------------------------------------------
// R2b — keyboard-reachable operator controls
// ---------------------------------------------------------------------------

/** Canonical traversal/visual order for the four operator controls. Exported so repl.ts's
 *  keyboard handler shares the exact same order and index space as this pane's rendering —
 *  divergence here would make "focus visits all four controls in visual order" a lie. */
export const OPERATOR_CONTROL_ACTIONS = ["START", "PAUSE", "RESUME", "RESTART"] as const;

/** Single-key accelerator per control (lowercase). Shown decorated in the control's own label
 *  via operatorControlLabel so the mnemonic is always visible, never a hidden binding. */
export const OPERATOR_CONTROL_ACCELERATORS: Record<OperatorControlAction, string> = {
  START: "s",
  PAUSE: "p",
  RESUME: "u",
  RESTART: "t",
};

/** Decorates the accelerator letter inside the action name itself, e.g. "[(S)TART]",
 *  "[RES(U)ME]" — derived generically from OPERATOR_CONTROL_ACCELERATORS rather than a
 *  hand-maintained label table, so the two can never drift apart. */
export function operatorControlLabel(action: OperatorControlAction): string {
  const accel = OPERATOR_CONTROL_ACCELERATORS[action].toUpperCase();
  const index = action.indexOf(accel);
  const decorated = index < 0
    ? `${action}(${accel})`
    : `${action.slice(0, index)}(${accel})${action.slice(index + 1)}`;
  return `[${decorated}]`;
}

const OPERATOR_CONTROL_DISABLED_REASONS: Record<OperatorControlAction, string> = {
  START: "a run is already active",
  PAUSE: "no running run",
  RESUME: "no paused run",
  RESTART: "no stale or offline run to restart",
};

/** Reason surfaced (R2b acceptance row 7) when a disabled control's accelerator or focused
 *  activation is attempted — a fixed, generic reason per action is sufficient; the point is
 *  that SOMETHING is surfaced rather than nothing. */
export function operatorControlDisabledReason(action: OperatorControlAction): string {
  return OPERATOR_CONTROL_DISABLED_REASONS[action];
}

/** Same enablement rule the pane's own render uses, exported so repl.ts's keyboard traversal
 *  and accelerator dispatch can skip/reject a disabled control using the IDENTICAL predicate —
 *  a second, hand-copied version of this rule is exactly how "looks reachable, isn't" bugs are
 *  born. */
export function isOperatorControlEnabled(
  action: OperatorControlAction,
  status: OperatorRunStatus,
  telemetry: TelemetryState,
): boolean {
  return action === "START" ? status === "IDLE"
    : action === "PAUSE" ? status === "RUNNING"
    : action === "RESUME" ? telemetry.runStatus?.phase === "PAUSED"
    : status === "STALE" || status === "OFFLINE";
}

/**
 * Pure traversal-step function: from `current` (use -1 to mean "not yet entered the set"), moves
 * `direction` (+1/-1) steps, skipping any index whose `enabledMask` entry is false, and returns
 * the landed index or null when the step runs off either end of the set (acceptance row 1's
 * "leaves the set", row 6's "the disabled control is skipped"). This is the SAME function
 * repl.ts's keyboard handler calls on every Tab/Arrow press and on pane-entry (entry is just
 * `nextOperatorFocusIndex(-1, 1, enabledMask)`) — there is no second, hand-copied traversal rule
 * that could drift from what actually ships.
 */
export function nextOperatorFocusIndex(
  current: number,
  direction: 1 | -1,
  enabledMask: readonly boolean[],
): number | null {
  let next = current + direction;
  while (next >= 0 && next < enabledMask.length && !enabledMask[next]) next += direction;
  return next >= 0 && next < enabledMask.length ? next : null;
}

/** The same {status, runId} pair the pane derives internally via buildOperatorSurfaceGraphs +
 *  getOperatorRunStatus, exposed so repl.ts's keyboard path can evaluate isOperatorControlEnabled
 *  and resolve the runId a dispatched control command targets, without re-deriving run selection
 *  by a second, divergent path. */
export function operatorControlStatus(
  telemetry: TelemetryState,
  nowMs: number = Date.now(),
): { status: OperatorRunStatus; runId?: string } {
  const graphs = buildOperatorSurfaceGraphs(telemetry, 80, nowMs);
  return { status: getOperatorRunStatus(telemetry, nowMs, graphs.runId), runId: graphs.runId };
}

function sharedWindow<T extends { step: number }>(samples: T[], maxPoints: number, checkpointSteps: Set<number> = new Set()): T[] {
  const indices = retainedIndices(samples.length, maxPoints, new Set(samples.map((sample, index) => checkpointSteps.has(sample.step) ? index : -1).filter((index) => index >= 0)));
  return indices.map((index) => samples[index]!);
}
function boundedSurfaceLine(line: string, width: number): string {
  return line.length <= width ? line : `${line.slice(0, Math.max(0, width - 1))}\u2026`;
}

/** A metric is growable (eligible to receive surplus interior height, R1d) once it has at least
 *  two real samples to plot -- the same threshold this function already used to choose the
 *  single-row spark path over SOURCE UNBOUND / INSUFFICIENT REAL HISTORY. Fewer than two real
 *  samples means there is nothing a taller plot would show, so those rows take no share. */
function metricIsGrowable(points: Array<{ step: number; value?: number }>): boolean {
  return points.filter((point) => finiteNumber(point.value)).length >= 2;
}

/** Renders one metric family at `rows` tall. `rows <= 1` is BYTE-IDENTICAL to the pre-R1d
 *  single-row sparkline (same per-point glyph mapping, not a resample) -- this is the exact-fit
 *  acceptance row (#4): a mount with no surplus must produce today's frame unchanged. `rows > 1`
 *  spends the Braille canvas's 4x vertical resolution via the SAME renderChart primitive
 *  host-telemetry curves already use, min/max-resampled so a spike still survives compression. */
function compactMetricLines(
  label: string,
  points: Array<{ step: number; value?: number }>,
  columns: number,
  statusTag: string | undefined,
  isLive: boolean,
  rows: number = 1,
): string[] {
  const finite = points.filter((point) => finiteNumber(point.value));
  const prefix = `${label.padEnd(20, " ")}${statusTag ? `${statusTag} ` : ""}`;
  if (finite.length === 0) return [`${prefix}${isLive ? "AWAITING FIRST SAMPLE" : "SOURCE UNBOUND"}`];
  if (finite.length < 2) return [`${prefix}INSUFFICIENT REAL HISTORY`];
  if (rows <= 1) {
    const min = Math.min(...finite.map((point) => point.value!));
    const max = Math.max(...finite.map((point) => point.value!));
    const span = max - min;
    const glyphs = points.map((point) => {
      if (!finiteNumber(point.value)) return "\u00b7";
      const level = span === 0 ? 7 : Math.floor(((point.value - min) / span) * 7);
      return PLOT_GLYPHS[Math.max(0, Math.min(7, level))];
    }).join("");
    return [`${prefix}${glyphs.slice(0, columns)}`];
  }
  const samples: Array<number | null> = points.map((point) => (finiteNumber(point.value) ? point.value! : null));
  const chart = renderChart(samples, { width: columns, height: Math.floor(rows) });
  const blankPrefix = " ".repeat(prefix.length);
  return chart.rows.map((row, index) => `${index === 0 ? prefix : blankPrefix}${row}`);
}

/**
 * One row-producing unit of the graph stream (R1d). `growable` blocks (metric families with at
 * least two real samples) are the ones surplus interior height distributes across; `render(1)`
 * on every block, fixed or chart, is EXACTLY today's flat line list -- the byte-identical
 * exact-fit case (acceptance #4) is nothing more than every block asked for its floor.
 */
interface GraphBlock {
  readonly growable: boolean;
  render(rows: number): string[];
}

function fixedBlock(line: string): GraphBlock {
  return { growable: false, render: () => [line] };
}

function chartBlock(growable: boolean, render: (rows: number) => string[]): GraphBlock {
  return { growable, render };
}

function compactSharedGraphBlocks(snapshot: OperatorSurfaceSnapshot, plotColumns: number, hostBound: boolean = false): GraphBlock[] {
  const checkpointSteps = new Set(snapshot.graphs.checkpoints.map((checkpoint) => checkpoint.step));
  const axisByStep = new Map<number, { step: number }>();
  for (const point of snapshot.graphs.points) axisByStep.set(point.step, { step: point.step });
  for (const step of checkpointSteps) axisByStep.set(step, { step });
  const axisSamples = sharedWindow([...axisByStep.values()].sort((left, right) => left.step - right.step), plotColumns, checkpointSteps);
  const stateTag = snapshot.status === "STALE" ? "STALE/HISTORICAL" : snapshot.status === "OFFLINE" ? "OFFLINE/HISTORICAL" : undefined;
  const isLive = snapshot.status === "RUNNING";
  const pointMetric = (value: (point: OperatorSeriesPoint) => number | undefined) =>
    axisSamples.map((axisPoint) => {
      const point = snapshot.graphs.points.find((candidate) => candidate.step === axisPoint.step);
      return { step: axisPoint.step, value: point ? value(point) : undefined };
    });
  const axis = axisSamples.length > 0
    ? `step/time ${axisSamples.map((point) => point.step).join(" ")}`
    : "step/time INSUFFICIENT REAL HISTORY";
  const marker = axisSamples.length > 0
    ? `checkpoint ${axisSamples.map((point) => checkpointSteps.has(point.step) ? "▲" : "·").join("")}`
    : "checkpoint INSUFFICIENT REAL HISTORY";
  const metricBlock = (label: string, points: Array<{ step: number; value?: number }>): GraphBlock =>
    chartBlock(metricIsGrowable(points), (rows) => compactMetricLines(label, points, plotColumns, stateTag, isLive, rows));
  // When the host-telemetry source is bound, its always-present VRAM/GPU curves make the
  // run-event GPU-utilization / VRAM / GPU-watts rows redundant — omitting them here is what
  // lets ten curves (four training + six host) fit the height budget without the layout engine
  // collapsing arbitrary rows. Without a bound host source the legacy full section stands.
  const gpuBlocks: GraphBlock[] = hostBound ? [] : [
    metricBlock("GPU utilization %", pointMetric((point) => point.gpuUtilizationPct)),
    metricBlock("VRAM GiB", pointMetric((point) => point.vramUsedGib)),
  ];
  const gpuWattsBlocks: GraphBlock[] = hostBound ? [] : [
    metricBlock("GPU watts", pointMetric((point) => point.gpuWatts)),
  ];
  return [
    fixedBlock(`TRAINING/LOSS${stateTag ? ` [${stateTag}]` : ""}`),
    metricBlock("loss", pointMetric((point) => point.loss)),
    fixedBlock(`RESOURCE EFFICIENCY${stateTag ? ` [${stateTag}]` : ""}`),
    ...gpuBlocks,
    metricBlock("tokens/s", pointMetric((point) => point.tokensPerSecond)),
    metricBlock("learning rate", pointMetric((point) => point.learningRate)),
    ...gpuWattsBlocks,
    metricBlock("energy joules", pointMetric((point) => point.boardEnergyJoulesTotal)),
    fixedBlock(boundedSurfaceLine(axis, plotColumns + 20)),
    fixedBlock(boundedSurfaceLine(marker, plotColumns + 20)),
  ];
}
/** Leading columns reserved for the keyboard-focus marker (R2b) — reserved UNCONDITIONALLY so
 *  gaining/losing keyboard focus never reflows the controls row; only the marker glyph itself
 *  changes. */
const FOCUS_MARKER_WIDTH = 2;
const FOCUS_MARKER_ON = "▸ ";
const FOCUS_MARKER_OFF = "  ";

/** Per-action label width including its own trailing gap (paddingRight:1 on the control's own
 *  Box) — used to pack controls into rows that never split a label mid-word (legibility bar,
 *  2026-07-26: "no control label is truncated — controls are the last thing to lose
 *  characters, never the first"). Measures the DECORATED label (accelerator-annotated, R2b),
 *  since that is what actually renders — measuring the bare action name would under-count. */
function controlLabelWidth(action: OperatorControlAction): number {
  return FOCUS_MARKER_WIDTH + operatorControlLabel(action).length + 1;
}

/** Packs the four control labels into as few rows as fit `availableWidth`, greedily, never
 *  splitting a label — every row always gets at least one full label even if that label alone
 *  exceeds `availableWidth` (a too-narrow pane gets its own row per control, not a clipped one).
 *  This REPLACES relying on flexWrap for the controls row: the layout engine declares a
 *  `flexWrap` property but never actually implements wrapping (dead prop, verified by reading
 *  layout-engine.ts), so a too-narrow controls row used to run past the pane and get raw-clipped
 *  by the outer overflow:"hidden" box with no marker at all ("[START] [PAUSE] [RESUME] [RES").
 *  Reflowing into rows here needs no layout-engine change and never truncates anything. */
export function layoutControlRows(actions: readonly string[], availableWidth: number): string[][] {
  const rows: string[][] = [[]];
  let used = 0;
  for (const action of actions) {
    const w = controlLabelWidth(action as OperatorControlAction);
    const current = rows[rows.length - 1]!;
    if (current.length > 0 && used + w > availableWidth) {
      rows.push([action]);
      used = w;
    } else {
      current.push(action);
      used += w;
    }
  }
  return rows;
}

export const HOST_METRIC_LABELS: Record<HostMetricId, string> = {
  memory: "host memory GiB",
  ram: "host RAM GiB",
  vram: "host VRAM GiB",
  cpu: "host CPU %",
  gpu: "host GPU %",
  disk: "host disk %",
};

/** A host series is growable (R1d) once it holds at least two REAL (non-null, finite) samples --
 *  the floor a taller plot needs to show anything a one-row sparkline doesn't already. A series
 *  that is unbound, empty, or entirely null stays at its single text/axis row and takes no
 *  share, same threshold `metricIsGrowable` uses for the training families. */
function hostSeriesIsGrowable(series: HostMetricSeries | undefined): boolean {
  if (!series) return false;
  let count = 0;
  for (const value of series.values) {
    if (value !== null && Number.isFinite(value)) count += 1;
    if (count >= 2) return true;
  }
  return false;
}

/**
 * One host-metric's lines, `rows` tall. ORDER INVARIANT (frozen spec): "is this source bound" is
 * decided FIRST, "does it have samples" only after. A bound-but-empty series renders an empty
 * axis (all-gap sparkline), and can NEVER fall through to the SOURCE UNBOUND path —
 * unbound-before-bound is the named defect. `rows <= 1` is BYTE-IDENTICAL to the pre-R1d single
 * line (same `sparklineRow` call); `rows > 1` spends the surplus via the same Braille
 * `renderChart` primitive the multi-row training families use.
 */
export function hostMetricLines(id: HostMetricId, series: HostMetricSeries | undefined, columns: number, rows: number = 1): string[] {
  const prefix = HOST_METRIC_LABELS[id].padEnd(20, " ");
  if (!series) return [`${prefix}SOURCE UNBOUND`]; // genuinely no producer wired
  // Bound from here down. Empty -> empty axis; null latest -> gap glyphs + the stated reason.
  const latest = series.values.length > 0 ? series.values[series.values.length - 1] : undefined;
  const reason = latest === null && series.unavailableReason ? ` [${series.unavailableReason}]` : "";
  // R1e (state/operator-pass-2026-07-26.md W3-diagnosed -- corrected root cause): the caller's
  // total line budget (`20 + plotColumns`, this component's own innerWidth) has ZERO slack beyond
  // `prefix.length + columns` -- the outer `boundedSurfaceLine` pass silently truncated any
  // trailing `reason` bracket the moment one was present, e.g. "loss SOURCE UNBOU…" losing the
  // reason text entirely rather than the axis losing a cell. Reserving `reason`'s own width out of
  // the plot budget up front keeps the line's TOTAL length identical to before (so nothing else
  // downstream changes) while the reason text itself survives instead of getting clipped.
  const spendWidth = Math.max(1, columns - reason.length);
  if (rows <= 1) {
    const spark = sparklineRow(series.values, spendWidth);
    return [`${prefix}${spark}${reason}`];
  }
  const chart = renderChart(series.values, { width: spendWidth, height: Math.floor(rows) });
  const blankPrefix = " ".repeat(prefix.length);
  return chart.rows.map((row, index) => {
    const label = index === 0 ? prefix : blankPrefix;
    const trailer = index === chart.rows.length - 1 ? reason : "";
    return `${label}${row}${trailer}`;
  });
}

/** Legacy single-line accessor, preserved for existing direct callers/tests: today's one-row
 *  rendering, byte-identical to before R1d. */
export function hostMetricLine(id: HostMetricId, series: HostMetricSeries | undefined, columns: number): string {
  return hostMetricLines(id, series, columns, 1)[0]!;
}

function hostTelemetryBlocks(host: HostTelemetrySnapshot | undefined, columns: number): GraphBlock[] {
  return [
    fixedBlock("HOST TELEMETRY"),
    ...HOST_METRIC_IDS.map((id) =>
      chartBlock(hostSeriesIsGrowable(host?.[id]), (rows) => hostMetricLines(id, host?.[id], columns, rows)),
    ),
  ];
}

/** The six always-present host curves. Present with or without a live run — that is the whole
 *  point: the resting panel is bound, and a live run ADDS training curves without dropping any
 *  of these. Legacy flat accessor: today's floor-only rendering, byte-identical to before R1d. */
export function hostTelemetryLines(host: HostTelemetrySnapshot | undefined, columns: number): string[] {
  return hostTelemetryBlocks(host, columns).flatMap((block) => block.render(1));
}

export function OperatorSurfacePane({
  width,
  height,
  terminalColumns,
  terminalRows,
  onControl,
  focusedControlIndex,
  disabledActionReason,
  ...input
}: OperatorSurfacePaneProps): React.ReactElement {
  const terminalWidth = finiteNumber(terminalColumns) ? terminalColumns : 1727;
  const terminalHeight = finiteNumber(terminalRows) ? terminalRows : 1447;
  const effectiveWidth = Math.max(20, Math.min(finiteNumber(width) ? width : 36, terminalWidth));
  const effectiveHeight = Math.max(8, Math.min(finiteNumber(height) ? height : 24, terminalHeight));
  // Inner content width once the pane's own borderStyle:"single" (1 col each side, line 616) AND
  // paddingX:1 (1 col each side, line 625) are BOTH accounted for — 4 columns total, not 2. This
  // under-counted (border-only omitted) before D2 (legibility scope addition, 2026-07): the
  // rendering pipeline's clip rect now structurally reserves the border column regardless (see
  // ink/rendering-pipeline.ts renderNodeToOutput), so the 2-column-too-generous bound could no
  // longer overwrite the border glyph itself, but it would still let boundedSurfaceLine's marker
  // land 2 columns later than the true content budget — i.e. silent hard-clipping (no marker) of
  // the last 2 characters by the render pipeline's own clip, exactly the "silent clipping" defect
  // class this whole pass exists to kill, just moved one layer down. innerWidth is the single
  // source of truth every line below is bounded against, so no line can ever reach the outer
  // overflow:"hidden" box wider than its true content budget, and any shortening always carries
  // a visible "…" marker (boundedSurfaceLine) rather than a raw, unmarked cut.
  const innerWidth = Math.max(1, effectiveWidth - 4);
  const adaptivePathMaxLen = Math.max(8, innerWidth - 20);
  const snapshot = buildOperatorSurfaceSnapshot({
    ...input,
    plotWidth: Math.max(8, effectiveWidth - 4),
    pathMaxLen: adaptivePathMaxLen,
  });
  const statusColor = snapshot.status === "RUNNING" ? "green" : snapshot.status === "OFFLINE" ? "red" : "yellow";
  const plotColumns = Math.max(8, effectiveWidth - 24);
  // Section order is height-contention policy: RESTING (no run points), the host curves ARE the
  // panel's content and lead; LIVE, the training sections lead and host follows, so a
  // height-constrained live viewport keeps its training headings (the pre-existing contract)
  // while the host curves remain present in the row stream for any viewport tall enough.
  // No host prop at all = the producer is not wired into this mount (legacy/test mounts); the
  // legacy families already render that state. A WIRED host with a missing/empty series is the
  // per-series bound/unbound decision inside hostMetricLine — that is where the order invariant
  // lives, and it is never skipped when the producer exists.
  const hostBlocks = input.host === undefined ? [] : hostTelemetryBlocks(input.host, plotColumns);
  const trainingBlocks = compactSharedGraphBlocks(snapshot, plotColumns, input.host !== undefined);
  // Section order is the height-contention policy (above); block order is what both the
  // end-trim and the R1d surplus-distribution below walk in, so "first ones in section order"
  // (the frozen remainder-placement rule) means exactly this array's order.
  const orderedGraphBlocks: GraphBlock[] = snapshot.graphs.points.length === 0
    ? [...hostBlocks, ...trainingBlocks]
    : [...trainingBlocks, ...hostBlocks];
  const growableBlockIndices = orderedGraphBlocks
    .map((block, index) => (block.growable ? index : -1))
    .filter((index) => index >= 0);
  // Every block at its floor (rows=1) is EXACTLY today's flat line list, one line per block —
  // the count the fixed-chrome budget below compares against, and the byte-identical output
  // acceptance row #4 requires when there is no surplus to distribute.
  const baselineBlockCount = orderedGraphBlocks.length;
  const compactMetrics = snapshot.metrics.length > 0
    ? [boundedSurfaceLine(`METRICS ${snapshot.metrics.join(" | ")}`, innerWidth)]
    : [];
  const compactAgentLines = snapshot.agentLines.slice(-1).map((line) => boundedSurfaceLine(line, innerWidth));
  const sourceLineText = boundedSurfaceLine(snapshot.source, innerWidth);

  const CONTROL_ACTIONS = OPERATOR_CONTROL_ACTIONS;
  const controlEnabled = (action: (typeof CONTROL_ACTIONS)[number]): boolean =>
    isOperatorControlEnabled(action, snapshot.status, input.telemetry);
  const renderControl = (action: (typeof CONTROL_ACTIONS)[number]): React.ReactElement => {
    const enabled = controlEnabled(action);
    const focused = focusedControlIndex === CONTROL_ACTIONS.indexOf(action);
    return React.createElement(
      Box,
      {
        key: `control-${action}`,
        flexShrink: 0,
        paddingRight: 1,
        onClick: enabled ? () => onControl?.(action, snapshot.graphs.runId) : undefined,
      },
      React.createElement(
        Text,
        { color: focused ? "cyan" : enabled ? "green" : "gray", bold: focused },
        `${focused ? FOCUS_MARKER_ON : FOCUS_MARKER_OFF}${operatorControlLabel(action)}`,
      ),
    );
  };
  const controlRows = layoutControlRows(CONTROL_ACTIONS, innerWidth);
  // Single row -> render flat, exactly as before (preserves the existing flat "controls" shape
  // at every width wide enough to hold all four labels). Multiple rows only when the pane is too
  // narrow for one row -> each row is its own full-width labels, never a clipped one.
  const controlsElement = controlRows.length <= 1
    ? React.createElement(
        Box,
        { key: "controls", flexDirection: "row", flexShrink: 0 },
        ...CONTROL_ACTIONS.map(renderControl),
      )
    : React.createElement(
        Box,
        { key: "controls", flexDirection: "column", flexShrink: 0 },
        ...controlRows.map((row, rowIndex) =>
          React.createElement(
            Box,
            { key: `controls-row-${rowIndex}`, flexDirection: "row", flexShrink: 0 },
            ...row.map((action) => renderControl(action as (typeof CONTROL_ACTIONS)[number])),
          ),
        ),
      );

  // Height budget (cure 2026-07-26): the pane used to emit every graph row and let the layout
  // engine clip against the pane height — under height pressure that engine collapses ARBITRARY
  // MIDDLE rows (the RESOURCE EFFICIENCY heading and the host VRAM curve were both observed
  // vanishing from the middle while rows above and below rendered). Arbitrary loss is the
  // defect; deterministic loss is not. So: count the fixed chrome rows EXACTLY as the body below
  // constructs them — 2 border rows + status + control rows + metrics + source + stream title +
  // agent lines (each a single non-wrapping Text row, every string already bounded to
  // innerWidth) — and trim the graph stream from the END to the remaining budget, stating the
  // drop on the last row. Trimming from the end keeps the precedence the section ordering
  // already encodes: leading training headings and curves survive, the host tail yields. When
  // the budget does not bind (graphLines fits), the stream passes through UNTOUCHED — zero
  // behaviour change for any mount with room, which is exactly what a chrome-row miscount would
  // break (the first attempt at this budget overcounted and truncated roomy mounts).
  const disabledReasonLines = disabledActionReason
    ? [boundedSurfaceLine(`${disabledActionReason}`, innerWidth)]
    : [];
  const fixedChromeRows = 2 + 1 + controlRows.length + disabledReasonLines.length + compactMetrics.length + 1 + 1 + compactAgentLines.length;
  const graphRowBudget = effectiveHeight - fixedChromeRows;
  // R1d: the pane used to stop here once end-trim didn't bind — a fitting or roomy mount passed
  // the flat one-row-per-chart stream through UNTOUCHED, which is exactly the under-subscribed
  // half this spec fills. The over-subscribed branch (graphRowBudget < baseline) is UNCHANGED:
  // trim from the end, state the drop, same as before. Only when there is genuine surplus
  // (graphRowBudget > baseline) does distribution run, and only across growable blocks; zero
  // growable blocks or zero/negative surplus falls through to the same untouched pass-through
  // the exact-fit case always had (skip-path S1/S6).
  const rawGraphLines: string[] = baselineBlockCount > graphRowBudget
    ? (() => {
        const baseline = orderedGraphBlocks.flatMap((block) => block.render(1));
        return graphRowBudget >= 1
          ? [
              ...baseline.slice(0, graphRowBudget - 1),
              `… ${baseline.length - (graphRowBudget - 1)} more rows`,
            ]
          : [];
      })()
    : (() => {
        const surplus = graphRowBudget - baselineBlockCount;
        if (surplus <= 0 || growableBlockIndices.length === 0) {
          return orderedGraphBlocks.flatMap((block) => block.render(1));
        }
        // Even growth across bound charts; the remainder goes to the FIRST ones in section
        // order (conjunction C2: deterministic across two renders of the same size).
        const perChart = Math.floor(surplus / growableBlockIndices.length);
        const remainder = surplus % growableBlockIndices.length;
        const rowsForBlock = new Map<number, number>();
        growableBlockIndices.forEach((blockIndex, orderIndex) => {
          rowsForBlock.set(blockIndex, 1 + perChart + (orderIndex < remainder ? 1 : 0));
        });
        return orderedGraphBlocks.flatMap((block, index) => block.render(rowsForBlock.get(index) ?? 1));
      })();
  const visibleGraphLines = rawGraphLines.map((line) => boundedSurfaceLine(line, innerWidth));

  const body = React.createElement(
    Box,
    {
      borderStyle: "single",
      borderColor: "cyan",
      borderTitle: "LIVE RUN / ACTIVITY/EVENT FEED",
      flexDirection: "column",
      width: effectiveWidth,
      height: effectiveHeight,
      minWidth: effectiveWidth,
      flexShrink: 0,
      overflow: "hidden",
      paddingX: 1,
    },
    React.createElement(Text, { key: "status", color: statusColor, bold: true, wrap: "truncate-end" }, snapshot.status),
    controlsElement,
    ...disabledReasonLines.map((line) => React.createElement(Text, { key: `disabled-reason-${line}`, color: "yellow", wrap: "truncate-end" }, line)),
    ...compactMetrics.map((metric) => React.createElement(Text, { key: metric, wrap: "truncate-end" }, metric)),
    React.createElement(Text, { key: "source", dimColor: true, wrap: "truncate-end" }, sourceLineText),
    ...visibleGraphLines.map((line, index) => React.createElement(Text, { key: `graph-${index}`, dimColor: true, wrap: "truncate-end" }, line)),
    React.createElement(Text, { key: "stream-title", color: "magenta", bold: true, wrap: "truncate-end" }, "ACTIVITY/EVENT FEED"),
    ...compactAgentLines.map((line, index) => React.createElement(Text, { key: `agent-${index}`, dimColor: true, wrap: "truncate-end" }, line)),
  );

  return React.createElement("div", { "data-operator-surface": "right-pane" }, body);
}
