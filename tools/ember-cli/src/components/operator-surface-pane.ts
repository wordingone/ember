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
}

export type OperatorRunStatus = "RUNNING" | "STALE" | "IDLE" | "OFFLINE";

export interface OperatorSeriesPoint {
  runId: string;
  step: number;
  loss?: number;
  totalSteps?: number;
  throughput?: number;
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
  const stepMs = event.payload["step_ms"];
  const free = event.payload["free_gib"];
  const total = event.payload["total_gib"];
  const throughput = finiteNumber(stepMs) && stepMs > 0 ? 60_000 / stepMs : undefined;
  const vramUsedGib = finiteNumber(free) && finiteNumber(total) && free >= 0 && total > 0 && free <= total
    ? total - free
    : undefined;
  const gpuValue = event.payload["gpu_utilization_pct"];
  const gpuUtilizationPct = finiteNumber(gpuValue) && gpuValue >= 0 && gpuValue <= 100 ? gpuValue : undefined;
  if (loss === undefined && throughput === undefined && vramUsedGib === undefined && gpuUtilizationPct === undefined) return undefined;
  const totalStepsValue = event.payload["total_steps"];
  const totalSteps = finiteNumber(totalStepsValue) && Number.isInteger(totalStepsValue) && totalStepsValue > 0 ? totalStepsValue : undefined;
  return { runId, step, totalSteps, loss, throughput, vramUsedGib, gpuUtilizationPct, ts: event.ts };
}

function selectedRunId(telemetry: TelemetryState, nowMs: number): string | undefined {
  const activeId = telemetry.activeRun?.runId;
  if (typeof activeId === "string" && activeId.length > 0) {
    const hasValidatedActiveEvidence = telemetry.recentEvents.some((event) => {
      const point = validTrainStep(event, nowMs);
      return point?.runId === activeId;
    });
    if (hasValidatedActiveEvidence) return activeId;
  }
  for (let index = telemetry.recentEvents.length - 1; index >= 0; index -= 1) {
    const point = validTrainStep(telemetry.recentEvents[index]!, nowMs);
    if (point) return point.runId;
  }
  return undefined;
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

function familyLines(title: string, samples: OperatorMetricPoint[], unbound: string, maxPoints: number, checkpointSteps: Set<number>): string[] {
  if (samples.length === 0) return [`${unbound}: SOURCE UNBOUND`];
  return plotLines(title, samples, checkpointSteps, maxPoints);
}

/** Build bounded graphs only from valid, provenance-selected events belonging to one run. */
export function buildOperatorSurfaceGraphs(telemetry: TelemetryState, plotWidth: number = 80, nowMs: number = Date.now()): OperatorSurfaceGraphs {
  const maxPoints = Math.max(2, Math.floor(plotWidth) - 8);
  const runId = selectedRunId(telemetry, nowMs);
  const points = runId
    ? telemetry.recentEvents
        .map((event) => validTrainStep(event, nowMs))
        .filter((point): point is OperatorSeriesPoint => point?.runId === runId)
        .sort((left, right) => left.step - right.step || Date.parse(left.ts) - Date.parse(right.ts))
    : [];
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
  const throughput = valueSamples(points, (point) => point.throughput);
  const modelGrowth = eventMetricSamples(telemetry, runId, "model_growth", "value", nowMs);
  const capability = eventMetricSamples(telemetry, runId, "capability_score", "score", nowMs);
  const decorate = (lines: string[]): string[] =>
    channelIsOffline(telemetry, runId) ? decorateHistory(lines, "OFFLINE/HISTORICAL") : lines;
  const lossLines = decorate(loss);
  const resourceLines = decorate([
    "RESOURCE EFFICIENCY",
    ...familyLines("GPU utilization %", gpu, "GPU UTILIZATION", maxPoints, checkpointSteps),
    ...familyLines("VRAM GiB", vram, "VRAM", maxPoints, checkpointSteps),
    ...familyLines("throughput", throughput, "THROUGHPUT/SPEED", maxPoints, checkpointSteps),
  ]);
  const modelGrowthLines = decorate(familyLines("model growth", modelGrowth, "MODEL GROWTH", maxPoints, checkpointSteps));
  const capabilityLines = decorate(familyLines("capability score", capability, "CAPABILITY SCORES", maxPoints, checkpointSteps));
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

function channelIsOffline(telemetry: TelemetryState, selectedRunId?: string): boolean {
  const extended = telemetry as TelemetryState & { channelStatus?: string };
  return extended.channelStatus === "OFFLINE" || (selectedRunId !== undefined && telemetry.runStatus?.runId === selectedRunId && telemetry.runStatus.phase === "OFFLINE");
}

function decorateHistory(lines: string[], marker: "OFFLINE/HISTORICAL" | "STALE/HISTORICAL"): string[] {
  return lines.map((line) => /^(TRAINING\/LOSS|RESOURCE EFFICIENCY|MODEL GROWTH|CAPABILITY SCORES)(?::|\s|$)/.test(line)
    ? `${line} [${marker}]`
    : `${marker} ${line}`);
}
/** Derive status only from the same validated train-step evidence used by graphs. */
export function getOperatorRunStatus(telemetry: TelemetryState, nowMs: number = Date.now(), selectedRun?: string): OperatorRunStatus {
  const runId = selectedRun ?? selectedRunId(telemetry, nowMs);
  if (channelIsOffline(telemetry, runId)) return "OFFLINE";
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
export function buildOperatorSurfaceSnapshot({
  telemetry,
  activityLines,
  sourceIdentity,
  nowMs = Date.now(),
  maxAgentLines = 6,
  plotWidth = 80,
}: OperatorSurfaceInput): OperatorSurfaceSnapshot {
  const rawGraphs = buildOperatorSurfaceGraphs(telemetry, plotWidth, nowMs);
  const status = getOperatorRunStatus(telemetry, nowMs, rawGraphs.runId);
  const latestPoint = rawGraphs.points.length > 0 ? rawGraphs.points[rawGraphs.points.length - 1] : undefined;
  const metrics: string[] = [];

  if (latestPoint && status === "RUNNING") {
    if (finiteNumber(latestPoint.loss)) metrics.push(`loss ${latestPoint.loss.toFixed(2)}`);
    if (finiteNumber(latestPoint.step)) {
      metrics.push(latestPoint.totalSteps !== undefined
        ? `step ${latestPoint.step}/${latestPoint.totalSteps}`
        : `step ${latestPoint.step}`);
    }
    if (finiteNumber(latestPoint.throughput)) {
      metrics.push(`throughput ${latestPoint.throughput.toFixed(1)} step/min`);
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
    ? visible.map((line) => formatActivityFeedLine(line, nowMs))
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
): string {
  const finite = points.filter((point) => finiteNumber(point.value));
  const prefix = `${label.padEnd(20, " ")}${statusTag ? `${statusTag} ` : ""}`;
  if (finite.length === 0) return `${prefix}SOURCE UNBOUND`;
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

function compactSharedGraphLines(snapshot: OperatorSurfaceSnapshot, plotColumns: number): string[] {
  const checkpointSteps = new Set(snapshot.graphs.checkpoints.map((checkpoint) => checkpoint.step));
  const axisByStep = new Map<number, { step: number }>();
  for (const point of snapshot.graphs.points) axisByStep.set(point.step, { step: point.step });
  for (const point of snapshot.graphs.modelGrowthPoints) axisByStep.set(point.step, { step: point.step });
  for (const point of snapshot.graphs.capabilityPoints) axisByStep.set(point.step, { step: point.step });
  for (const step of checkpointSteps) axisByStep.set(step, { step });
  const axisSamples = sharedWindow([...axisByStep.values()].sort((left, right) => left.step - right.step), plotColumns, checkpointSteps);
  const stateTag = snapshot.status === "STALE" ? "STALE/HISTORICAL" : snapshot.status === "OFFLINE" ? "OFFLINE/HISTORICAL" : undefined;
  const pointMetric = (value: (point: OperatorSeriesPoint) => number | undefined) =>
    axisSamples.map((axisPoint) => {
      const point = snapshot.graphs.points.find((candidate) => candidate.step === axisPoint.step);
      return { step: axisPoint.step, value: point ? value(point) : undefined };
    });
  const eventMetric = (points: OperatorMetricPoint[]) =>
    axisSamples.map((axisPoint) => ({ step: axisPoint.step, value: points.find((point) => point.step === axisPoint.step)?.value }));
  const axis = axisSamples.length > 0
    ? `step/time ${axisSamples.map((point) => point.step).join(" ")}`
    : "step/time INSUFFICIENT REAL HISTORY";
  const marker = axisSamples.length > 0
    ? `checkpoint ${axisSamples.map((point) => checkpointSteps.has(point.step) ? "▲" : "·").join("")}`
    : "checkpoint INSUFFICIENT REAL HISTORY";
  return [
    `TRAINING/LOSS${stateTag ? ` [${stateTag}]` : ""}`,
    compactMetricLine("loss", pointMetric((point) => point.loss), plotColumns, stateTag),
    `RESOURCE EFFICIENCY${stateTag ? ` [${stateTag}]` : ""}`,
    compactMetricLine("GPU utilization %", pointMetric((point) => point.gpuUtilizationPct), plotColumns, stateTag),
    compactMetricLine("VRAM GiB", pointMetric((point) => point.vramUsedGib), plotColumns, stateTag),
    compactMetricLine("throughput/speed", pointMetric((point) => point.throughput), plotColumns, stateTag),
    `MODEL GROWTH${stateTag ? ` [${stateTag}]` : ""}`,
    compactMetricLine("model growth", eventMetric(snapshot.graphs.modelGrowthPoints), plotColumns, stateTag),
    `CAPABILITY SCORES${stateTag ? ` [${stateTag}]` : ""}`,
    compactMetricLine("capability score", eventMetric(snapshot.graphs.capabilityPoints), plotColumns, stateTag),
    boundedSurfaceLine(axis, plotColumns + 20),
    boundedSurfaceLine(marker, plotColumns + 20),
  ];
}
export function OperatorSurfacePane({
  width,
  height,
  terminalColumns,
  terminalRows,
  ...input
}: OperatorSurfacePaneProps): React.ReactElement {
  const terminalWidth = finiteNumber(terminalColumns) ? terminalColumns : 1727;
  const terminalHeight = finiteNumber(terminalRows) ? terminalRows : 1447;
  const effectiveWidth = Math.max(20, Math.min(finiteNumber(width) ? width : 36, terminalWidth));
  const effectiveHeight = Math.max(8, Math.min(finiteNumber(height) ? height : 24, terminalHeight));
  const snapshot = buildOperatorSurfaceSnapshot({
    ...input,
    plotWidth: Math.max(8, effectiveWidth - 4),
  });
  const statusColor = snapshot.status === "RUNNING" ? "green" : snapshot.status === "OFFLINE" ? "red" : "yellow";
  const plotColumns = Math.max(8, effectiveWidth - 24);
  const graphLines = compactSharedGraphLines(snapshot, plotColumns);
  const compactMetrics = snapshot.metrics.length > 0
    ? [boundedSurfaceLine(`METRICS ${snapshot.metrics.join(" | ")}`, effectiveWidth - 4)]
    : [];
  const compactAgentLines = snapshot.agentLines.slice(-1);
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
    ...compactMetrics.map((metric) => React.createElement(Text, { key: metric }, metric)),
    React.createElement(Text, { key: "source", dimColor: true }, snapshot.source),
    ...graphLines.map((line, index) => React.createElement(Text, { key: `graph-${index}`, dimColor: true, wrap: "truncate-end" }, line)),
    React.createElement(Text, { key: "stream-title", color: "magenta", bold: true }, "ACTIVITY/EVENT FEED"),
    ...compactAgentLines.map((line, index) => React.createElement(Text, { key: `agent-${index}`, dimColor: true, wrap: "truncate-end" }, line)),
  );

  return React.createElement("div", { "data-operator-surface": "right-pane" }, body);
}
