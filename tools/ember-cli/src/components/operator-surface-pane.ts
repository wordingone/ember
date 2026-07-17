// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import React from "react";
import { Box, Text } from "../ink/components.ts";
import {
  ACTIVE_RUN_TTL_MS,
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
}

export interface OperatorSurfaceInput {
  telemetry: TelemetryState;
  activityLines: ActivityFeedLine[];
  sourceIdentity?: OperatorSourceIdentity;
  nowMs?: number;
  maxAgentLines?: number;
}

export interface OperatorSurfaceSnapshot {
  status: "RUNNING" | "IDLE_OR_STALE";
  metrics: string[];
  source: string;
  agentLines: string[];
}

function shortDigest(value: string, length: number = 12): string {
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

function finiteNumber(value: number | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function sourceLine(sourceIdentity: OperatorSourceIdentity | undefined): string {
  const commit = sourceIdentity?.publicCommit;
  const binary = sourceIdentity?.binarySha256;
  if (!commit || !/^[0-9a-f]{40}$/i.test(commit) || !binary || !/^[0-9a-f]{64}$/i.test(binary)) {
    return "SOURCE UNBOUND";
  }
  return `source ${shortDigest(commit)} binary ${shortDigest(binary)}`;
}

export function buildOperatorSurfaceSnapshot({
  telemetry,
  activityLines,
  sourceIdentity,
  nowMs = Date.now(),
  maxAgentLines = 6,
}: OperatorSurfaceInput): OperatorSurfaceSnapshot {
  const run = telemetry.activeRun;
  const runTs = run ? Date.parse(run.lastTs) : NaN;
  const fresh = Boolean(run && Number.isFinite(runTs) && nowMs - runTs <= ACTIVE_RUN_TTL_MS);
  const metrics: string[] = [];

  if (run && fresh) {
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
    status: fresh ? "RUNNING" : "IDLE_OR_STALE",
    metrics,
    source: sourceLine(sourceIdentity),
    agentLines,
  };
}

export interface OperatorSurfacePaneProps extends OperatorSurfaceInput {
  width?: number;
}

export function OperatorSurfacePane({ width, ...input }: OperatorSurfacePaneProps): React.ReactElement {
  const snapshot = buildOperatorSurfaceSnapshot(input);
  const statusColor = snapshot.status === "RUNNING" ? "green" : "yellow";
  const body = React.createElement(
    Box,
    {
      borderStyle: "single",
      borderColor: "cyan",
      borderTitle: "LIVE RUN / AGENT STREAM",
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
    React.createElement(Text, { key: "stream-title", color: "magenta", bold: true }, "AGENT STREAM"),
    ...snapshot.agentLines.map((line, index) => React.createElement(Text, { key: `agent-${index}`, dimColor: true, wrap: "truncate-end" }, line)),
  );

  return React.createElement("div", { "data-operator-surface": "right-pane" }, body);
}