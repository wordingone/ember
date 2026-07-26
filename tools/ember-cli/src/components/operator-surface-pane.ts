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
import { sparklineRow } from "../ink/chart.ts";
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
}

function sharedWindow<T extends { step: number }>(samples: T[], maxPoints: number, checkpointSteps: Set<number> = new Set()): T[] {
  const indices = retainedIndices(samples.length, maxPoints, new Set(samples.map((sample, index) => checkpointSteps.has(sample.step) ? index : -1).filter((index) => index >= 0)));
  return indices.map((index) => samples[index]!);
}
function boundedSurfaceLine(line: string, width: number): string {
  return line.length <= width ? line : `${line.slice(0, Math.max(0, width - 1))}\u2026`;
}

function compactMetricLine(
  label: string,
  points: Array<{ step: number; value?: number }>,
  columns: number,
  statusTag: string | undefined,
  isLive: boolean,
): string {
  const finite = points.filter((point) => finiteNumber(point.value));
  const prefix = `${label.padEnd(20, " ")}${statusTag ? `${statusTag} ` : ""}`;
  if (finite.length === 0) return `${prefix}${isLive ? "AWAITING FIRST SAMPLE" : "SOURCE UNBOUND"}`;
  if (finite.length < 2) return `${prefix}INSUFFICIENT REAL HISTORY`;
  const min = Math.min(...finite.map((point) => point.value!));
  const max = Math.max(...finite.map((point) => point.value!));
  const span = max - min;
  const glyphs = points.map((point) => {
    if (!finiteNumber(point.value)) return "\u00b7";
    const level = span === 0 ? 7 : Math.floor(((point.value - min) / span) * 7);
    return PLOT_GLYPHS[Math.max(0, Math.min(7, level))];
  }).join("");
  return `${prefix}${glyphs.slice(0, columns)}`;
}

function compactSharedGraphLines(snapshot: OperatorSurfaceSnapshot, plotColumns: number, hostBound: boolean = false): string[] {
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
  // When the host-telemetry source is bound, its always-present VRAM/GPU curves make the
  // run-event GPU-utilization / VRAM / GPU-watts rows redundant — omitting them here is what
  // lets ten curves (four training + six host) fit the height budget without the layout engine
  // collapsing arbitrary rows. Without a bound host source the legacy full section stands.
  const gpuRows = hostBound ? [] : [
    compactMetricLine("GPU utilization %", pointMetric((point) => point.gpuUtilizationPct), plotColumns, stateTag, isLive),
    compactMetricLine("VRAM GiB", pointMetric((point) => point.vramUsedGib), plotColumns, stateTag, isLive),
  ];
  const gpuWattsRows = hostBound ? [] : [
    compactMetricLine("GPU watts", pointMetric((point) => point.gpuWatts), plotColumns, stateTag, isLive),
  ];
  return [
    `TRAINING/LOSS${stateTag ? ` [${stateTag}]` : ""}`,
    compactMetricLine("loss", pointMetric((point) => point.loss), plotColumns, stateTag, isLive),
    `RESOURCE EFFICIENCY${stateTag ? ` [${stateTag}]` : ""}`,
    ...gpuRows,
    compactMetricLine("tokens/s", pointMetric((point) => point.tokensPerSecond), plotColumns, stateTag, isLive),
    compactMetricLine("learning rate", pointMetric((point) => point.learningRate), plotColumns, stateTag, isLive),
    ...gpuWattsRows,
    compactMetricLine("energy joules", pointMetric((point) => point.boardEnergyJoulesTotal), plotColumns, stateTag, isLive),
    boundedSurfaceLine(axis, plotColumns + 20),
    boundedSurfaceLine(marker, plotColumns + 20),
  ];
}
/** Per-action label width including its own trailing gap (paddingRight:1 on the control's own
 *  Box) — used to pack controls into rows that never split a label mid-word (legibility bar,
 *  2026-07-26: "no control label is truncated — controls are the last thing to lose
 *  characters, never the first"). */
function controlLabelWidth(action: string): number {
  return `[${action}]`.length + 1;
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
    const w = controlLabelWidth(action);
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
export const HOST_METRIC_LABELS: Record<HostMetricId, string> = {
  memory: "host memory GiB",
  ram: "host RAM GiB",
  vram: "host VRAM GiB",
  cpu: "host CPU %",
  gpu: "host GPU %",
  disk: "host disk %",
};

/**
 * One host-metric line. ORDER INVARIANT (frozen spec): "is this source bound" is decided FIRST,
 * "does it have samples" only after. A bound-but-empty series renders an empty axis (all-gap
 * sparkline), and can NEVER fall through to the SOURCE UNBOUND path — unbound-before-bound is
 * the named defect.
 */
export function hostMetricLine(id: HostMetricId, series: HostMetricSeries | undefined, columns: number): string {
  const prefix = HOST_METRIC_LABELS[id].padEnd(20, " ");
  if (!series) return `${prefix}SOURCE UNBOUND`; // genuinely no producer wired
  // Bound from here down. Empty -> empty axis; null latest -> gap glyphs + the stated reason.
  const spark = sparklineRow(series.values, columns);
  const latest = series.values.length > 0 ? series.values[series.values.length - 1] : undefined;
  const reason = latest === null && series.unavailableReason ? ` [${series.unavailableReason}]` : "";
  return `${prefix}${spark}${reason}`;
}

/** The six always-present host curves. Present with or without a live run — that is the whole
 *  point: the resting panel is bound, and a live run ADDS training curves without dropping any
 *  of these. */
export function hostTelemetryLines(host: HostTelemetrySnapshot | undefined, columns: number): string[] {
  return ["HOST TELEMETRY", ...HOST_METRIC_IDS.map((id) => hostMetricLine(id, host?.[id], columns))];
}

export function OperatorSurfacePane({
  width,
  height,
  terminalColumns,
  terminalRows,
  onControl,
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
  const hostSection = input.host === undefined ? [] : hostTelemetryLines(input.host, plotColumns);
  const trainingSection = compactSharedGraphLines(snapshot, plotColumns, input.host !== undefined);
  // Both passes land here: the section ORDER is the height-contention policy above, and
  // every resulting line is then bounded against the pane's real inner width so any
  // shortening carries a visible marker instead of being silently hard-clipped by the
  // outer renderer (legibility bar, 2026-07-26). Order first, bound second — bounding
  // before assembly would measure the wrong strings.
  const graphLines = (snapshot.graphs.points.length === 0
    ? [...hostSection, ...trainingSection]
    : [...trainingSection, ...hostSection]
  ).map((line) => boundedSurfaceLine(line, innerWidth));
  const compactMetrics = snapshot.metrics.length > 0
    ? [boundedSurfaceLine(`METRICS ${snapshot.metrics.join(" | ")}`, innerWidth)]
    : [];
  const compactAgentLines = snapshot.agentLines.slice(-1).map((line) => boundedSurfaceLine(line, innerWidth));
  const sourceLineText = boundedSurfaceLine(snapshot.source, innerWidth);

  const CONTROL_ACTIONS = ["START", "PAUSE", "RESUME", "RESTART"] as const;
  const controlEnabled = (action: (typeof CONTROL_ACTIONS)[number]): boolean =>
    action === "START" ? snapshot.status === "IDLE"
      : action === "PAUSE" ? snapshot.status === "RUNNING"
      : action === "RESUME" ? input.telemetry.runStatus?.phase === "PAUSED"
      : snapshot.status === "STALE" || snapshot.status === "OFFLINE";
  const renderControl = (action: (typeof CONTROL_ACTIONS)[number]): React.ReactElement => {
    const enabled = controlEnabled(action);
    return React.createElement(
      Box,
      {
        key: `control-${action}`,
        flexShrink: 0,
        paddingRight: 1,
        onClick: enabled ? () => onControl?.(action, snapshot.graphs.runId) : undefined,
      },
      React.createElement(Text, { color: enabled ? "green" : "gray" }, `[${action}]`),
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
    React.createElement(Text, { key: "status", color: statusColor, bold: true }, snapshot.status),
    controlsElement,
    ...compactMetrics.map((metric) => React.createElement(Text, { key: metric }, metric)),
    React.createElement(Text, { key: "source", dimColor: true }, sourceLineText),
    ...graphLines.map((line, index) => React.createElement(Text, { key: `graph-${index}`, dimColor: true, wrap: "truncate-end" }, line)),
    React.createElement(Text, { key: "stream-title", color: "magenta", bold: true }, "ACTIVITY/EVENT FEED"),
    ...compactAgentLines.map((line, index) => React.createElement(Text, { key: `agent-${index}`, dimColor: true, wrap: "truncate-end" }, line)),
  );

  return React.createElement("div", { "data-operator-surface": "right-pane" }, body);
}
