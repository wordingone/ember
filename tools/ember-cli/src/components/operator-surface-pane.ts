// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import React from "react";
import { formatAgentEventLine, selectAgentEventRun, type AgentEventChannelStatus, type AgentJournalEvent } from "../services/agent-event-feed.ts";
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
  agentEvents?: AgentJournalEvent[];
  agentChannelStatus?: AgentEventChannelStatus;
}

export type OperatorRunStatus = "RUNNING" | "STALE" | "IDLE" | "OFFLINE";

export interface OperatorSeriesPoint {
  runId: string;
  step: number;
  loss: number;
  throughput: number;
  vramUsedGib: number;
  ts: string;
}

export interface OperatorSurfaceGraphs {
  runId?: string;
  points: OperatorSeriesPoint[];
  loss: string[];
  resource: string[];
  checkpoints: Array<{ step: number; label: "checkpoint" }>;
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

function validTrainStep(event: TelemetryEvent): OperatorSeriesPoint | undefined {
  if (event.kind !== "train_step") return undefined;
  const runId = eventRunId(event);
  const step = event.payload["step"];
  const loss = event.payload["loss"];
  const stepMs = event.payload["step_ms"];
  const free = event.payload["free_gib"];
  const total = event.payload["total_gib"];
  if (!runId || !finiteNumber(step) || !finiteNumber(loss) || !finiteNumber(stepMs) || stepMs <= 0 || !finiteNumber(eventTime(event))) return undefined;
  if (!finiteNumber(free) || !finiteNumber(total) || free < 0 || total <= 0 || free > total) return undefined;
  return {
    runId,
    step,
    loss,
    throughput: 60_000 / stepMs,
    vramUsedGib: total - free,
    ts: event.ts,
  };
}

function selectedRunId(telemetry: TelemetryState): string | undefined {
  const activeId = telemetry.activeRun?.runId;
  if (typeof activeId === "string" && activeId.length > 0) return activeId;
  for (let index = telemetry.recentEvents.length - 1; index >= 0; index -= 1) {
    const point = validTrainStep(telemetry.recentEvents[index]!);
    if (point) return point.runId;
  }
  return undefined;
}

function graphLines(title: string, points: OperatorSeriesPoint[], value: (point: OperatorSeriesPoint) => number): string[] {
  const samples = points.map(value).filter(finiteNumber);
  if (samples.length < 2) {
    return [`${title}: insufficient real history (${samples.length} point${samples.length === 1 ? "" : "s"})`];
  }
  const min = Math.min(...samples);
  const max = Math.max(...samples);
  return [
    `${title} [${min.toFixed(2)}..${max.toFixed(2)}]`,
    `steps ${points.map((point) => point.step).join(" ")}`,
    `${title.toLowerCase()} ${samples.map((sample) => sample.toFixed(2)).join(" ")}`,
  ];
}

/** Build bounded graphs only from valid train_step events belonging to one run. */
export function buildOperatorSurfaceGraphs(telemetry: TelemetryState): OperatorSurfaceGraphs {
  const runId = selectedRunId(telemetry);
  const points = runId
    ? telemetry.recentEvents
        .map(validTrainStep)
        .filter((point): point is OperatorSeriesPoint => point?.runId === runId)
        .sort((left, right) => left.step - right.step || eventTime({ ts: left.ts, kind: "", source: "", payload: {} }) - eventTime({ ts: right.ts, kind: "", source: "", payload: {} }))
    : [];
  const checkpoints = runId
    ? telemetry.recentEvents
        .filter((event) => event.kind === "checkpoint" && eventRunId(event) === runId)
        .map((event) => {
          const step = event.payload["step"];
          return finiteNumber(step) && step >= 0 ? { step, label: "checkpoint" as const } : undefined;
        })
        .filter((marker): marker is { step: number; label: "checkpoint" } => marker !== undefined)
        .sort((left, right) => left.step - right.step)
    : [];
  return {
    runId,
    points,
    loss: graphLines("loss", points, (point) => point.loss),
    resource: [
      ...graphLines("throughput", points, (point) => point.throughput),
      ...graphLines("VRAM GiB", points, (point) => point.vramUsedGib),
      points.length >= 2
        ? `steps ${points.map((point) => point.step).join(" ")}`
        : "resource axis: insufficient real history",
    ],
    checkpoints,
  };
}

function channelIsOffline(telemetry: TelemetryState): boolean {
  const extended = telemetry as TelemetryState & { channelStatus?: string };
  return extended.channelStatus === "OFFLINE" || telemetry.runStatus?.phase === "OFFLINE";
}

/** Distinguish no evidence (IDLE) from old evidence (STALE), including channel OFFLINE. */
export function getOperatorRunStatus(telemetry: TelemetryState, nowMs: number = Date.now()): OperatorRunStatus {
  if (channelIsOffline(telemetry)) return "OFFLINE";
  const eventTimes = telemetry.recentEvents
    .filter((event) => event.kind === "train_step" && eventRunId(event) !== undefined)
    .map(eventTime)
    .filter(finiteNumber);
  const activeTime = telemetry.activeRun ? Date.parse(telemetry.activeRun.lastTs) : NaN;
  if (finiteNumber(activeTime)) eventTimes.push(activeTime);
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
}: OperatorSurfaceInput): OperatorSurfaceSnapshot {
  const status = getOperatorRunStatus(telemetry, nowMs);
  const run = telemetry.activeRun;
  const metrics: string[] = [];

  if (run && status === "RUNNING") {
    if (finiteNumber(run.loss)) metrics.push(`loss ${run.loss.toFixed(2)}`);
    if (finiteNumber(run.step)) {
      metrics.push(run.totalSteps != null && finiteNumber(run.totalSteps)
        ? `step ${run.step}/${run.totalSteps}`
        : `step ${run.step}`);
    }
    if (finiteNumber(run.stepMs) && run.stepMs > 0) {
      metrics.push(`throughput ${(60_000 / run.stepMs).toFixed(1)} step/min`);
    }
  }

  const governor = telemetry.lastGovernor;
  if (governor && finiteNumber(governor.vramUsedGib) && finiteNumber(governor.vramTotalGib)) {
    metrics.push(`VRAM ${governor.vramUsedGib.toFixed(1)}/${governor.vramTotalGib.toFixed(1)} GiB`);
  }

  const checkpoint = telemetry.lastCheckpoint;
  if (checkpoint && /^[0-9a-f]{64}$/i.test(checkpoint.checkpointManifestSha256)) {
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
    graphs: buildOperatorSurfaceGraphs(telemetry),
  };
}

export interface OperatorSurfacePaneProps extends OperatorSurfaceInput {
  width?: number;
}

export function OperatorSurfacePane({ width, ...input }: OperatorSurfacePaneProps): React.ReactElement {
  const snapshot = buildOperatorSurfaceSnapshot(input);
  const agentEvents = selectAgentEventRun(input.agentEvents ?? [], input.maxAgentLines ?? 6);
  const statusColor = snapshot.status === "RUNNING" ? "green" : snapshot.status === "OFFLINE" ? "red" : "yellow";
  const graphLines = [
    "LOSS HISTORY",
    ...snapshot.graphs.loss,
    "RESOURCE HISTORY",
    ...snapshot.graphs.resource,
    snapshot.graphs.checkpoints.length > 0
      ? `checkpoints ${snapshot.graphs.checkpoints.map((marker) => marker.step).join(" ")}`
      : "checkpoints: none observed",
  ];
  const body = React.createElement(
    Box,
    {
      borderStyle: "single",
      borderColor: "cyan",
      borderTitle: "LIVE RUN / ACTIVITY/EVENT FEED",
      flexDirection: "column",
      width,
      minWidth: 36,
      flexShrink: 0,
      overflow: "hidden",
      paddingX: 1,
    },
    React.createElement(Text, { key: "status", color: statusColor, bold: true }, snapshot.status),
    ...snapshot.metrics.map((metric) => React.createElement(Text, { key: metric }, metric)),
    React.createElement(Text, { key: "source", dimColor: true }, snapshot.source),
    ...graphLines.map((line, index) => React.createElement(Text, { key: `graph-${index}`, dimColor: true, wrap: "truncate-end" }, line)),
    React.createElement(Text, { key: "stream-title", color: "magenta", bold: true }, "ACTIVITY/EVENT FEED"),
    ...snapshot.agentLines.map((line, index) => React.createElement(Text, { key: `agent-${index}`, dimColor: true, wrap: "truncate-end" }, line)),
    React.createElement(Text, { key: "agent-journal-title", color: "magenta", bold: true }, "AGENT EVENT JOURNAL"),
    ...(agentEvents.length > 0
      ? agentEvents.map((event, index) => React.createElement(Text, { key: `journal-${index}`, dimColor: true, wrap: "truncate-end" }, formatAgentEventLine(event)))
      : [React.createElement(Text, { key: "agent-journal-empty", dimColor: true }, input.agentChannelStatus === "OFFLINE" ? "agent journal: OFFLINE" : "agent journal: none observed")]),
  );

  return React.createElement("div", { "data-operator-surface": "right-pane" }, body);
}
