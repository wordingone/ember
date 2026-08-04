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
import { CommandBarPane, DEFAULT_COMMAND_BAR_MAX_ROWS } from "./command-bar-pane.ts";
import {
  buildCommandButtons,
  commandBarRowCount,
  type CommandButton,
  type CommandButtonActivation,
} from "../services/command-buttons.ts";
import type { RegistryCommand } from "../types/command-types.ts";
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

function telemetryRunStatusId(telemetry: TelemetryState): string | undefined {
  const runId = telemetry.runStatus?.runId;
  return typeof runId === "string" && runId.trim().length > 0 ? runId : undefined;
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

export const OPERATOR_GRAPH_CARD_MIN_HEIGHT = 3;
export const OPERATOR_GRAPH_CARD_MAX_HEIGHT = 5;

export type OperatorGraphCardId = HostMetricId | "loss" | "tokens" | "learning-rate" | "energy" | "gpu-watts";

const OPERATOR_GRAPH_CARD_COLORS: Record<OperatorGraphCardId, string> = {
  memory: "cyan",
  ram: "blue",
  vram: "magenta",
  cpu: "green",
  gpu: "red",
  disk: "yellow",
  loss: "yellow",
  tokens: "cyan",
  "learning-rate": "blue",
  energy: "magenta",
  "gpu-watts": "red",
};

export function operatorGraphCardColor(id: OperatorGraphCardId): string {
  return OPERATOR_GRAPH_CARD_COLORS[id];
}

export interface OperatorGraphCardLayout {
  cardHeight: number;
  visibleCardCount: number;
  hiddenCardCount: number;
}

/** Responsive vertical allocation with a hard legibility cap. A huge terminal can no longer turn
 *  one trace into dozens of rows; a tight terminal keeps whole cards and reports the hidden tail. */
export const OPERATOR_GRAPH_CARD_MIN_WIDTH = 32;

export function operatorGraphGridColumns(_width: number): 1 {
  return 1;
}

export function operatorGraphCardLayout(
  cardCount: number,
  rowBudget: number,
  columns: number = 1,
): OperatorGraphCardLayout {
  const count = Math.max(0, Math.floor(cardCount));
  const budget = Math.max(0, Math.floor(rowBudget));
  const columnCount = Math.max(1, Math.floor(columns));
  if (count === 0 || budget < OPERATOR_GRAPH_CARD_MIN_HEIGHT) {
    return { cardHeight: OPERATOR_GRAPH_CARD_MIN_HEIGHT, visibleCardCount: 0, hiddenCardCount: count };
  }
  const gridRows = Math.ceil(count / columnCount);
  const allFitHeight = Math.floor(budget / gridRows);
  if (allFitHeight >= OPERATOR_GRAPH_CARD_MIN_HEIGHT) {
    return {
      cardHeight: Math.min(OPERATOR_GRAPH_CARD_MAX_HEIGHT, allFitHeight),
      visibleCardCount: count,
      hiddenCardCount: 0,
    };
  }
  const visibleGridRows = Math.max(0, Math.floor((budget - 1) / OPERATOR_GRAPH_CARD_MIN_HEIGHT));
  const visible = Math.max(0, Math.min(count, visibleGridRows * columnCount));
  return {
    cardHeight: OPERATOR_GRAPH_CARD_MIN_HEIGHT,
    visibleCardCount: visible,
    hiddenCardCount: count - visible,
  };
}

function exactCell(text: string, width: number): string {
  const target = Math.max(0, Math.floor(width));
  if (text.length > target) return target <= 1 ? text.slice(0, target) : `${text.slice(0, target - 1)}~`;
  return text.padEnd(target, " ");
}

/** Produces only the card interior; the renderer-owned Box supplies every border cell and title.
 *  The sample window is bounded to the drawable width before charting. */
export function renderOperatorGraphCard(
  _title: string,
  values: Array<number | null> | undefined,
  unit: string,
  width: number,
  height: number,
  unavailableReason?: string,
): string[] {
  const cardWidth = Math.max(8, Math.floor(width));
  const cardHeight = Math.max(OPERATOR_GRAPH_CARD_MIN_HEIGHT, Math.min(OPERATOR_GRAPH_CARD_MAX_HEIGHT, Math.floor(height)));
  const innerWidth = cardWidth - 2;
  const lines: string[] = [];
  const finiteValues = (values ?? []).filter((value): value is number => value !== null && Number.isFinite(value));
  const interiorRows = cardHeight - 2;
  if (values === undefined) {
    lines.push(exactCell(" SOURCE UNBOUND", innerWidth));
    while (lines.length < interiorRows) lines.push(" ".repeat(innerWidth));
  } else if (finiteValues.length === 0) {
    lines.push(exactCell(` ${unavailableReason ?? "AWAITING FIRST SAMPLE"}`, innerWidth));
    while (lines.length < interiorRows) lines.push(" ".repeat(innerWidth));
  } else {
    const latest = finiteValues[finiteValues.length - 1]!;
    const min = Math.min(...finiteValues);
    const max = Math.max(...finiteValues);
    const stats = `${latest.toFixed(2)} ${unit} | min ${min.toFixed(2)} max ${max.toFixed(2)}`;
    if (interiorRows === 1) {
      const sparkWidth = Math.max(1, innerWidth - stats.length - 3);
      const bounded = values.slice(-sparkWidth);
      lines.push(exactCell(` ${stats} ${sparklineRow(bounded, sparkWidth)}`, innerWidth));
    } else {
      lines.push(exactCell(` ${stats}`, innerWidth));
      const plotRows = interiorRows - 1;
      const bounded = values.slice(-Math.max(2, innerWidth * 2));
      const chart = renderChart(bounded, { width: innerWidth, height: plotRows });
      for (const row of chart.rows) lines.push(exactCell(row, innerWidth));
    }
  }
  while (lines.length < interiorRows) lines.push(" ".repeat(innerWidth));
  return lines.slice(0, interiorRows);
}

export interface OperatorGraphCardSpec {
  id: OperatorGraphCardId;
  title: string;
  values: Array<number | null> | undefined;
  unit: string;
  unavailableReason?: string;
}

export interface OperatorGraphCardRowSegment {
  text: string;
  color: string;
}

export interface OperatorGraphCardRenderRow {
  segments: OperatorGraphCardRowSegment[];
}

export function renderOperatorGraphCardRows(
  cards: OperatorGraphCardSpec[],
  width: number,
  rowBudget: number,
): { layout: OperatorGraphCardLayout; rows: OperatorGraphCardRenderRow[] } {
  const totalWidth = Math.max(8, Math.floor(width));
  const columns = operatorGraphGridColumns(totalWidth);
  const layout = operatorGraphCardLayout(cards.length, rowBudget, columns);
  const gapWidth = columns - 1;
  const usableWidth = totalWidth - gapWidth;
  const baseWidth = Math.floor(usableWidth / columns);
  const remainder = usableWidth % columns;
  const columnWidths = Array.from({ length: columns }, (_, index) => baseWidth + (index < remainder ? 1 : 0));
  const rows: OperatorGraphCardRenderRow[] = [];

  for (let start = 0; start < layout.visibleCardCount; start += columns) {
    const group = cards.slice(start, Math.min(start + columns, layout.visibleCardCount));
    const rendered = columnWidths.map((columnWidth, columnIndex) => {
      const card = group[columnIndex];
      return card
        ? {
            color: operatorGraphCardColor(card.id),
            lines: renderOperatorGraphCard(
              card.title,
              card.values,
              card.unit,
              columnWidth,
              layout.cardHeight,
              card.unavailableReason,
            ),
          }
        : { color: "gray", lines: Array.from({ length: layout.cardHeight }, () => " ".repeat(columnWidth)) };
    });
    for (let lineIndex = 0; lineIndex < Math.max(1, layout.cardHeight - 2); lineIndex += 1) {
      const segments: OperatorGraphCardRowSegment[] = [];
      rendered.forEach((card, columnIndex) => {
        if (columnIndex > 0) segments.push({ text: " ", color: "gray" });
        segments.push({ text: card.lines[lineIndex]!, color: card.color });
      });
      rows.push({ segments });
    }
  }

  if (layout.hiddenCardCount > 0 && rows.length < Math.max(0, Math.floor(rowBudget))) {
    rows.push({
      segments: [{
        text: exactCell(`… ${layout.hiddenCardCount} more charts`, totalWidth),
        color: "yellow",
      }],
    });
  }
  return { layout, rows };
}

function cardValues(
  points: OperatorSeriesPoint[],
  runBound: boolean,
  read: (point: OperatorSeriesPoint) => number | undefined,
): Array<number | null> | undefined {
  if (!runBound) return undefined;
  return points.map((point) => {
    const value = read(point);
    return finiteNumber(value) ? value : null;
  });
}

/** Adapts the already validated/provenance-selected snapshot into presentation-only cards. */
export function buildOperatorGraphCardSpecs(
  snapshot: OperatorSurfaceSnapshot,
  host: HostTelemetrySnapshot | undefined,
): OperatorGraphCardSpec[] {
  const runBound = snapshot.graphs.runId !== undefined;
  const missingReason = snapshot.status === "RUNNING"
    ? "AWAITING FIRST SAMPLE"
    : snapshot.status === "STALE"
      ? "STALE/HISTORICAL"
      : snapshot.status === "OFFLINE"
        ? "OFFLINE/HISTORICAL"
        : "SOURCE UNBOUND";
  const training: OperatorGraphCardSpec[] = [
    { id: "loss", title: "LOSS", values: cardValues(snapshot.graphs.points, runBound, (point) => point.loss), unit: "", unavailableReason: missingReason },
    { id: "tokens", title: "TOKENS/S", values: cardValues(snapshot.graphs.points, runBound, (point) => point.tokensPerSecond), unit: "tok/s", unavailableReason: missingReason },
    { id: "learning-rate", title: "LEARNING RATE", values: cardValues(snapshot.graphs.points, runBound, (point) => point.learningRate), unit: "", unavailableReason: missingReason },
    { id: "energy", title: "ENERGY", values: cardValues(snapshot.graphs.points, runBound, (point) => point.boardEnergyJoulesTotal), unit: "J", unavailableReason: missingReason },
  ];
  if (host === undefined) {
    training.splice(1, 0,
      { id: "gpu", title: "GPU", values: cardValues(snapshot.graphs.points, runBound, (point) => point.gpuUtilizationPct), unit: "%", unavailableReason: missingReason },
      { id: "vram", title: "VRAM", values: cardValues(snapshot.graphs.points, runBound, (point) => point.vramUsedGib), unit: "GiB", unavailableReason: missingReason },
      { id: "gpu-watts", title: "GPU POWER", values: cardValues(snapshot.graphs.points, runBound, (point) => point.gpuWatts), unit: "W", unavailableReason: missingReason },
    );
  }
  const hostCards: OperatorGraphCardSpec[] = host === undefined
    ? []
    : HOST_METRIC_IDS.map((id) => {
        const series = host[id];
        return {
          id,
          title: HOST_METRIC_LABELS[id].toUpperCase(),
          values: series?.values,
          unit: series?.unit ?? "",
          unavailableReason: series?.unavailableReason,
        };
      });
  return snapshot.graphs.points.length === 0 ? [...hostCards, ...training] : [...training, ...hostCards];
}
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
  if (runId && latestTrainTs !== undefined && telemetry.runStatus?.runId === runId) {
    const statusTs = Date.parse(telemetry.runStatus.lastTs);
    if (Number.isFinite(statusTs) && statusTs >= latestTrainTs) {
      if (telemetry.runStatus.phase === "FAILED") return "STALE";
      if (telemetry.runStatus.phase === "COMPLETE") return "IDLE";
    }
  }
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
  hoveredControl?: OperatorControlAction;
  onControlHover?: (action: OperatorControlAction | undefined) => void;
  height?: number;
  terminalColumns?: number;
  activityScrollOffset?: number;
  onActivityScroll?: (deltaY: -1 | 1) => void;
  terminalRows?: number;
  /** Index into OPERATOR_CONTROL_ACTIONS currently holding keyboard traversal focus, or
   *  undefined when the pane itself does not have keyboard focus (R2b). Drives the visible
   *  focus marker — a control that is focused with no way to see which one is focused is the
   *  same failure class as a control that renders and does nothing. */
  focusedControlIndex?: number;
  /** Reason surfaced when a disabled control's accelerator or activation was attempted (R2b
   *  acceptance row 7) — silently doing nothing is the exact failure R2 was filed for. */
  disabledActionReason?: string;

  // -------------------------------------------------------------------------
  // #1399 — the command buttons live HERE, with the run controls
  // -------------------------------------------------------------------------
  /** The live command registry. Present -> the command bar renders directly under the run
   *  controls; absent -> the pane is exactly what it was before #1399, which is what keeps every
   *  existing mount of this component (and its tests) meaningful. */
  commands?: readonly RegistryCommand[];
  /** Row budget for the command bar, from `commandBarMaxRows(terminalRows)`. */
  commandBarMaxRows?: number;
  hoveredCommand?: string;
  onHoverCommand?: (name: string | undefined) => void;
  onCommandActivate?: (activation: CommandButtonActivation, button: CommandButton) => void;
  commandPage?: number;
  onCommandPageChange?: (page: number) => void;
  commandNotice?: string;
}

// ---------------------------------------------------------------------------
// R2b — keyboard-reachable operator controls
// ---------------------------------------------------------------------------

/** Canonical traversal/visual order for the four operator controls. Exported so repl.ts's
 *  keyboard handler shares the exact same order and index space as this pane's rendering —
 *  divergence here would make "focus visits all four controls in visual order" a lie. */
export const OPERATOR_CONTROL_ACTIONS = ["START", "PAUSE", "RESUME", "RESTART"] as const;

/** Plain, button-shaped label. Direct letter accelerators were removed after the operator made
 * the interaction contract explicit: these are mouse controls with ordinary Tab/arrow plus
 * Enter/Space accessibility, not mnemonic command advertisements. */
export function operatorControlLabel(action: OperatorControlAction): string {
  return `[${action}]`;
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
  const pausedRunId = telemetry.runStatus?.phase === "PAUSED" ? telemetryRunStatusId(telemetry) : undefined;
  return {
    status: getOperatorRunStatus(telemetry, nowMs, graphs.runId),
    runId: pausedRunId ?? graphs.runId,
  };
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
  hoveredControl,
  onControlHover,
  activityScrollOffset = 0,
  onActivityScroll,
  onControl,
  focusedControlIndex,
  disabledActionReason,
  commands,
  commandBarMaxRows,
  hoveredCommand,
  onHoverCommand,
  onCommandActivate,
  commandPage,
  onCommandPageChange,
  commandNotice,
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
  const graphCards = buildOperatorGraphCardSpecs(snapshot, input.host);
  const compactMetrics = snapshot.metrics.length > 0
    ? [boundedSurfaceLine(`METRICS ${snapshot.metrics.join(" | ")}`, innerWidth)]
    : [];
  const activityIndex = Math.max(0, snapshot.agentLines.length - 1 - Math.max(0, Math.floor(activityScrollOffset)));
  const compactAgentLines = snapshot.agentLines.slice(activityIndex, activityIndex + 1)
    .map((line) => boundedSurfaceLine(line, innerWidth));
  const sourceLineText = boundedSurfaceLine(snapshot.source, innerWidth);

  const CONTROL_ACTIONS = OPERATOR_CONTROL_ACTIONS;
  const controlEnabled = (action: (typeof CONTROL_ACTIONS)[number]): boolean =>
    isOperatorControlEnabled(action, snapshot.status, input.telemetry);
  const selectedControlRunId = input.telemetry.runStatus?.phase === "PAUSED"
    ? telemetryRunStatusId(input.telemetry) ?? snapshot.graphs.runId
    : snapshot.graphs.runId;
  const renderControl = (action: (typeof CONTROL_ACTIONS)[number]): React.ReactElement => {
    const enabled = controlEnabled(action);
    const focused = focusedControlIndex === CONTROL_ACTIONS.indexOf(action);
    const hovered = enabled && hoveredControl === action;
    return React.createElement(
      Box,
      {
        key: `control-${action}`,
        flexShrink: 0,
        paddingRight: 1,
        onClick: enabled ? () => onControl?.(action, selectedControlRunId) : undefined,
        onMouseEnter: enabled ? () => onControlHover?.(action) : undefined,
        onMouseLeave: enabled ? () => onControlHover?.(undefined) : undefined,
      },
      React.createElement(
        Text,
        { color: focused ? "cyan" : enabled ? "green" : "gray", bold: focused || hovered, inverse: hovered },
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

  // #1399: the command buttons render HERE, immediately under the run controls, because that is
  // where the operator looks for a control. Two things make the two groups read as distinct
  // blocks rather than one long bracket run: the run controls carry an UPPERCASE label set under
  // their own `run control` caption, and every command group opens with its own dim caption
  // (`launch`, `inspect`, `govern`, `more`) supplied by the bar itself.
  const commandButtons = commands ? buildCommandButtons(commands) : [];
  const commandRowBudget = commandBarMaxRows ?? DEFAULT_COMMAND_BAR_MAX_ROWS;
  const commandBarRows = commandButtons.length === 0
    ? 0
    : commandBarRowCount(
        commandButtons,
        innerWidth,
        commandRowBudget,
        commandPage ?? 0,
        commandNotice !== undefined,
      );
  const controlsCaption = commandButtons.length > 0 ? "run control" : undefined;
  const commandBarElement = commandButtons.length === 0
    ? null
    : React.createElement(CommandBarPane, {
        key: "command-bar",
        commands: commands!,
        width: innerWidth,
        maxRows: commandRowBudget,
        ...(hoveredCommand !== undefined ? { hoveredCommand } : {}),
        ...(onHoverCommand ? { onHoverCommand } : {}),
        ...(onCommandActivate ? { onActivate: onCommandActivate } : {}),
        page: commandPage ?? 0,
        ...(onCommandPageChange ? { onPageChange: onCommandPageChange } : {}),
        ...(commandNotice !== undefined ? { notice: commandNotice } : {}),
      });

  // Reserve exact rows for borders, status, controls, provenance, and activity. The remaining
  // budget belongs exclusively to whole bounded chart cards; hidden cards are disclosed rather
  // than relying on Ink to collapse arbitrary middle rows.
  const disabledReasonLines = disabledActionReason
    ? [boundedSurfaceLine(`${disabledActionReason}`, innerWidth)]
    : [];
  // The activity viewport is always exactly two rows high: its title plus either one event row or
  // one intentionally blank row. Counting only compactAgentLines.length allowed Yoga to reclaim
  // the RUNNING/IDLE status row whenever the feed was empty.
  const activityViewportRows = 2;
  const fixedChromeRows = 2 + 1 + controlRows.length + (controlsCaption ? 1 : 0) + commandBarRows
    + disabledReasonLines.length + compactMetrics.length + 1 + activityViewportRows;
  const graphRowBudget = effectiveHeight - fixedChromeRows;
  // Card height responds only within the tested three-to-five-row legibility range. Constrained
  // panes retain deterministic leading cards and one explicit hidden-card count.
  const graphLayout = operatorGraphCardLayout(graphCards.length, graphRowBudget, 1);
  const visibleGraphCards = graphCards.slice(0, graphLayout.visibleCardCount);

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
    React.createElement(Box, { key: "status-row", height: 1, flexShrink: 0 }, React.createElement(Text, { color: statusColor, bold: true, wrap: "truncate-end" }, snapshot.status)),
    controlsCaption
      ? React.createElement(Box, { key: "controls-caption", height: 1, flexShrink: 0 },
          React.createElement(Text, { dimColor: true, bold: true, wrap: "truncate-end" },
            boundedSurfaceLine(controlsCaption, innerWidth)))
      : null,
    controlsElement,
    commandBarElement,
    ...disabledReasonLines.map((line) => React.createElement(Box, { key: `disabled-reason-${line}`, height: 1, flexShrink: 0 }, React.createElement(Text, { color: "yellow", wrap: "truncate-end" }, line))),
    ...compactMetrics.map((metric) => React.createElement(Box, { key: metric, height: 1, flexShrink: 0 }, React.createElement(Text, { wrap: "truncate-end" }, metric))),
    React.createElement(Box, { key: "source-row", height: 1, flexShrink: 0 }, React.createElement(Text, { dimColor: true, wrap: "truncate-end" }, sourceLineText)),
    ...visibleGraphCards.map((card) => React.createElement(
      Box,
      {
        key: `graph-${card.id}`,
        borderStyle: "single",
        borderColor: operatorGraphCardColor(card.id),
        borderTitle: card.title,
        flexDirection: "column",
        flexShrink: 0,
        width: innerWidth,
        height: graphLayout.cardHeight,
        overflow: "hidden",
      },
      ...renderOperatorGraphCard(
        card.title,
        card.values,
        card.unit,
        innerWidth,
        graphLayout.cardHeight,
        card.unavailableReason,
      ).map((line, index) => React.createElement(Text, {
        key: `graph-${card.id}-${index}`,
        color: operatorGraphCardColor(card.id),
        wrap: "truncate-end",
      }, line)),
    )),
    graphLayout.hiddenCardCount > 0
      ? React.createElement(Box, { key: "hidden-graphs-row", height: 1, flexShrink: 0 }, React.createElement(Text, { color: "yellow", wrap: "truncate-end" },
          boundedSurfaceLine(`\u2026 ${graphLayout.hiddenCardCount} more charts`, innerWidth)))
      : null,
    React.createElement(
      Box,
      { key: "activity-scroll-region", flexDirection: "column", height: 2, flexShrink: 0, overflow: "hidden",
        onWheel: onActivityScroll ? (event: any) => onActivityScroll(event.deltaY) : undefined },
      React.createElement(Text, { key: "stream-title", color: "magenta", bold: true, wrap: "truncate-end" }, "ACTIVITY/EVENT FEED"),
      ...compactAgentLines.map((line, index) => React.createElement(Text, { key: `agent-${index}`, dimColor: true, wrap: "truncate-end" }, line)),
    ),
  );

  return React.createElement("div", { "data-operator-surface": "right-pane" }, body);
}
