// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { buildOperatorSurfaceGraphs, buildOperatorSurfaceSnapshot, getOperatorRunStatus, OperatorSurfacePane, PLOT_PREFIX_WIDTH } from "./operator-surface-pane.ts";
import type { TelemetryState } from "../services/telemetry-watch.ts";
import type { ActivityFeedLine } from "./activity-feed-pane.ts";

const ellipsis = String.fromCodePoint(0x2026);
const activity: ActivityFeedLine[] = [
  { ts: "2026-07-17T17:30:00.000Z", source: "receipt", text: "checkpoint receipt landed", path: "receipts/run/checkpoint.json" },
];
function telemetry(overrides: Partial<TelemetryState> = {}): TelemetryState { return { recentEvents: [], ...overrides }; }

function train(runId: string, step: number, ts: string, loss: number, extra: Record<string, unknown> = {}): { ts: string; kind: string; source: string; payload: Record<string, unknown> } {
  return { ts, kind: "train_step", source: "journal", payload: { run_id: runId, step, loss, ...extra } };
}

describe("OperatorSurfacePane", () => {
  test("derives scalar status metrics and binds checkpoint to the active run", () => {
    const snapshot = buildOperatorSurfaceSnapshot({
      telemetry: telemetry({
        recentEvents: [train("run-1", 12, "2026-07-17T17:30:00.000Z", 1.25, { step_ms: 500, total_steps: 100 })],
        activeRun: { runId: "run-1", step: 12, totalSteps: 100, loss: 1.25, stepMs: 500, lastTs: "2026-07-17T17:30:00.000Z" },
        lastGovernor: { runId: "run-1", vramUsedGib: 7.5, vramTotalGib: 24, fractionApplied: 0.5 },
        lastCheckpoint: { runId: "run-1", step: 10, checkpointManifestSha256: "a".repeat(64), lastTs: "2026-07-17T17:29:00.000Z" },
      }),
      activityLines: activity,
      sourceIdentity: { publicCommit: "f".repeat(40), binarySha256: "b".repeat(64) },
      nowMs: Date.parse("2026-07-17T17:30:01.000Z"),
    });
    expect(snapshot.status).toBe("RUNNING");
    expect(snapshot.metrics).toEqual(["loss 1.25", "step 12/100", "throughput 120.0 step/min", "VRAM 7.5/24.0 GiB", `checkpoint step 10 ${"a".repeat(12)}${ellipsis}`]);
    expect(snapshot.source).toBe("SOURCE UNVERIFIED/UNBOUND");
    expect(snapshot.agentLines[0]).toContain("[receipt] checkpoint receipt landed [receipts/run/checkpoint.json]");
  });

  test("renders exact plotted glyph rows with a shared step/time axis and checkpoint marker", () => {
    const graphTelemetry = telemetry({
      recentEvents: [
        train("run-a", 2, "2026-07-17T17:30:01.000Z", 1.5, { step_ms: 500, free_gib: 10, total_gib: 24, gpu_utilization_pct: 60 }),
        train("run-a", 1, "2026-07-17T17:30:02.000Z", 2.5, { step_ms: 1000, free_gib: 9, total_gib: 24, gpu_utilization_pct: 50 }),
        train("run-a", 3, "2026-07-17T17:30:03.000Z", 1, { step_ms: 250, free_gib: 8, total_gib: 24, gpu_utilization_pct: 70 }),
        { ts: "2026-07-17T17:30:03.100Z", kind: "checkpoint", source: "journal", payload: { run_id: "run-a", step: 3, checkpoint_manifest_sha256: "a".repeat(64) } },
        { ts: "2026-07-17T17:30:03.200Z", kind: "checkpoint", source: "journal", payload: { run_id: "foreign", step: 77, checkpoint_manifest_sha256: "b".repeat(64) } },
        { ts: "2026-07-17T17:30:03.300Z", kind: "model_growth", source: "journal", payload: { run_id: "run-a", step: 1, value: 1 } },
        { ts: "2026-07-17T17:30:03.400Z", kind: "model_growth", source: "journal", payload: { run_id: "run-a", step: 2, value: 2 } },
        { ts: "2026-07-17T17:30:03.500Z", kind: "model_growth", source: "journal", payload: { run_id: "run-a", step: 3, value: 3 } },
        { ts: "2026-07-17T17:30:03.600Z", kind: "capability_score", source: "journal", payload: { run_id: "run-a", step: 1, score: 0.1 } },
        { ts: "2026-07-17T17:30:03.700Z", kind: "capability_score", source: "journal", payload: { run_id: "run-a", step: 2, score: 0.2 } },
        { ts: "2026-07-17T17:30:03.800Z", kind: "capability_score", source: "journal", payload: { run_id: "run-a", step: 3, score: 0.3 } },
      ],
      activeRun: { runId: "run-a", step: 3, loss: 1, stepMs: 250, lastTs: "2026-07-17T17:30:03.000Z" },
    });
    const graphs = buildOperatorSurfaceGraphs(graphTelemetry);
    const lossPlot = graphs.loss.find((line) => line.startsWith("loss plot "))!;
    const checkpointPlot = graphs.loss.find((line) => line.startsWith("checkpoint plot "))!;
    expect(lossPlot.slice(PLOT_PREFIX_WIDTH)).toBe(String.fromCodePoint(0x2588)+String.fromCodePoint(0x2583)+String.fromCodePoint(0x2581));
    expect(checkpointPlot.slice(PLOT_PREFIX_WIDTH)).toBe(String.fromCodePoint(0x00b7)+String.fromCodePoint(0x00b7)+String.fromCodePoint(0x25b2));
    expect(lossPlot.indexOf(String.fromCodePoint(0x2588))).toBe(checkpointPlot.indexOf(String.fromCodePoint(0x00b7)));
    expect(graphs.loss).not.toContain("loss 2.50 1.50 1.00");
    expect(graphs.resource.find((line) => line.startsWith("GPU utilization % plot "))!.slice(PLOT_PREFIX_WIDTH)).toBe("▁▄█");
    expect(graphs.resource.find((line) => line.startsWith("VRAM GiB plot "))!.slice(PLOT_PREFIX_WIDTH)).toBe("▄▁█");
    expect(graphs.resource.find((line) => line.startsWith("throughput plot "))!.slice(PLOT_PREFIX_WIDTH)).toBe("▁▃█");
    expect(graphs.modelGrowth.find((line) => line.startsWith("model growth plot "))!.slice(PLOT_PREFIX_WIDTH)).toBe("▁▄█");
    expect(graphs.capability.find((line) => line.startsWith("capability score plot "))!.slice(PLOT_PREFIX_WIDTH)).toBe("▁▄█");
    expect(graphs.checkpoints).toEqual([{ step: 3, label: "checkpoint" }]);
  });

  test("loss-only evidence remains usable while resource families fail closed", () => {
    const graphs = buildOperatorSurfaceGraphs(telemetry({ recentEvents: [
      train("run-a", 1, "2026-07-17T17:30:01.000Z", 2),
      train("run-a", 2, "2026-07-17T17:30:02.000Z", 1),
    ] }));
    expect(graphs.loss.find((line) => line.startsWith("loss plot "))!.slice(PLOT_PREFIX_WIDTH)).toBe(String.fromCodePoint(0x2588)+String.fromCodePoint(0x2581));
    expect(graphs.resource).toContain("GPU UTILIZATION: SOURCE UNBOUND");
    expect(graphs.resource).toContain("VRAM: SOURCE UNBOUND");
    expect(graphs.resource).toContain("THROUGHPUT/SPEED: SOURCE UNBOUND");
  });

  test("filters mixed runs, malformed points, and foreign checkpoint events", () => {
    const graphs = buildOperatorSurfaceGraphs(telemetry({
      recentEvents: [
        train("run-a", 1, "2026-07-17T17:30:01.000Z", 2, { step_ms: 1000, free_gib: 10, total_gib: 24 }),
        train("run-b", 99, "2026-07-17T17:30:02.000Z", 99, { step_ms: 1, free_gib: 1, total_gib: 24 }),
        train("run-a", 2, "2026-07-17T17:30:03.000Z", Number.NaN, { step_ms: Number.POSITIVE_INFINITY, free_gib: 9, total_gib: 24 }),
        { ts: "2026-07-17T17:30:03.500Z", kind: "checkpoint", source: "journal", payload: { run_id: "run-b", step: 88, checkpoint_manifest_sha256: "b".repeat(64) } },
      ],
      activeRun: { runId: "run-a", step: 1, loss: 2, stepMs: 1000, lastTs: "2026-07-17T17:30:01.000Z" },
    }));
    expect(graphs.runId).toBe("run-a");
    expect(graphs.points.map((point) => point.step)).toEqual([1, 2]);
    expect(graphs.loss.join("\n")).not.toContain("99");
    expect(graphs.checkpoints).toEqual([]);
  });

  test("uses only the latest real run when activeRun is absent", () => {
    const graphs = buildOperatorSurfaceGraphs(telemetry({ recentEvents: [
      train("old-run", 1, "2026-07-17T17:30:01.000Z", 3, { step_ms: 1000, free_gib: 10, total_gib: 24 }),
      train("new-run", 1, "2026-07-17T17:30:02.000Z", 2, { step_ms: 500, free_gib: 9, total_gib: 24 }),
      train("new-run", 2, "2026-07-17T17:30:03.000Z", 1, { step_ms: 250, free_gib: 8, total_gib: 24 }),
    ] }));
    expect(graphs.runId).toBe("new-run");
    expect(graphs.points.map((point) => point.step)).toEqual([1, 2]);
    expect(graphs.points.every((point) => point.runId === "new-run")).toBe(true);
  });

  test("selects the newest validated run timestamp independent of arrival order or stale activeRun", () => {
    const now = Date.parse("2026-07-17T17:31:00.000Z");
    const newest = train("new-run", 4, "2026-07-17T17:30:59.000Z", 1, { step_ms: 500 });
    const delayed = train("old-run", 99, "2026-07-17T17:30:00.000Z", 9, { step_ms: 1000 });
    for (const recentEvents of [[newest, delayed], [delayed, newest]]) {
      const graphs = buildOperatorSurfaceGraphs(telemetry({
        recentEvents,
        activeRun: { runId: "old-run", step: 99, loss: 9, stepMs: 1000, lastTs: delayed.ts },
      }), 80, now);
      expect(graphs.runId).toBe("new-run");
      expect(graphs.points.every((point) => point.runId === "new-run")).toBe(true);
    }
  });
  test("does not fabricate empty/one-point trends and labels missing families", () => {
    expect(buildOperatorSurfaceGraphs(telemetry()).loss).toContain("INSUFFICIENT REAL HISTORY");
    expect(buildOperatorSurfaceGraphs(telemetry()).modelGrowth).toEqual(["MODEL GROWTH: SOURCE UNBOUND"]);
    expect(buildOperatorSurfaceGraphs(telemetry()).capability).toEqual(["CAPABILITY SCORES: SOURCE UNBOUND"]);
    expect(buildOperatorSurfaceGraphs(telemetry({ recentEvents: [train("run-a", 1, "2026-07-17T17:30:01.000Z", 2)] })).loss).toContain("INSUFFICIENT REAL HISTORY");
  });

  test("OFFLINE history is explicit and stale checkpoint from another run is not shown", () => {
    const snapshot = buildOperatorSurfaceSnapshot({ telemetry: telemetry({ channelStatus: "OFFLINE", recentEvents: [train("run-a", 1, "2026-07-17T17:30:01.000Z", 2, { step_ms: 1000, free_gib: 10, total_gib: 24 })], lastCheckpoint: { runId: "foreign", step: 9, checkpointManifestSha256: "b".repeat(64), lastTs: "2026-07-17T17:30:02.000Z" } }), activityLines: [] });
    expect(snapshot.status).toBe("OFFLINE");
    expect(snapshot.metrics.some((line) => line.startsWith("checkpoint"))).toBe(false);
    expect(snapshot.graphs.loss.every((line) => line.includes("OFFLINE/HISTORICAL"))).toBe(true);
  });

  test("distinguishes idle, stale, and offline using real evidence", () => {
    const now = Date.parse("2026-07-17T17:31:00.000Z");
    expect(getOperatorRunStatus(telemetry(), now)).toBe("IDLE");
    expect(getOperatorRunStatus(telemetry({ recentEvents: [train("run-a", 1, "2026-07-17T17:30:00.000Z", 2)] }), now)).toBe("STALE");
    expect(getOperatorRunStatus(telemetry({ recentEvents: [train("future", 1, "2099-01-01T00:00:00.000Z", 2)] }), now)).toBe("IDLE");
    expect(getOperatorRunStatus(telemetry({ recentEvents: [{ ts: "2026-07-17T17:30:30.000Z", kind: "train_step", source: "journal", payload: { run_id: "invalid", step: 7 } }] }), now)).toBe("IDLE");
    expect(getOperatorRunStatus(telemetry({ channelStatus: "OFFLINE" } as any), now)).toBe("OFFLINE");
  });

  test("binds status to the selected graph run instead of maxing across runs", () => {
    const now = Date.parse("2026-07-17T17:31:00.000Z");
    const telemetryState = telemetry({ recentEvents: [
      train("run-b", 8, "2026-07-17T17:30:59.000Z", 1),
      train("run-a", 3, "2026-07-17T17:30:00.000Z", 2),
    ] });
    expect(getOperatorRunStatus(telemetryState, now)).toBe("RUNNING");
  });

  test("does not let an older selected-run OFFLINE status override newer train evidence", () => {
    const now = Date.parse("2026-07-17T17:31:00.000Z");
    const trainEvent = train("run-a", 1, "2026-07-17T17:30:59.000Z", 2, { step_ms: 500 });
    const oldOffline = { runId: "run-a", phase: "OFFLINE", modelChat: "OFFLINE", lastTs: "2026-07-17T17:30:00.000Z" } as const;
    const currentOffline = { ...oldOffline, lastTs: trainEvent.ts };
    expect(getOperatorRunStatus(telemetry({ recentEvents: [trainEvent], runStatus: oldOffline }), now)).toBe("RUNNING");
    expect(getOperatorRunStatus(telemetry({ recentEvents: [trainEvent], runStatus: currentOffline }), now)).toBe("OFFLINE");
  });

  test("derives scalar metrics from the newest timestamp, not the highest step", () => {
    const snapshot = buildOperatorSurfaceSnapshot({
      telemetry: telemetry({ recentEvents: [
        train("run-a", 100, "2026-07-17T17:30:00.000Z", 9, { step_ms: 1000 }),
        train("run-a", 10, "2026-07-17T17:30:59.000Z", 1, { step_ms: 500 }),
      ] }),
      activityLines: [],
      nowMs: Date.parse("2026-07-17T17:31:00.000Z"),
    });
    expect(snapshot.metrics).toContain("loss 1.00");
    expect(snapshot.metrics).toContain("step 10");
    expect(snapshot.metrics).toContain("throughput 120.0 step/min");
    expect(snapshot.metrics).not.toContain("loss 9.00");
    expect(snapshot.metrics).not.toContain("step 100");
  });
  test("does not apply retained OFFLINE run status to a different selected run", () => {
    const now = Date.parse("2026-07-17T17:30:03.000Z");
    const snapshot = buildOperatorSurfaceSnapshot({
      telemetry: telemetry({
        recentEvents: [train("run-b", 2, "2026-07-17T17:30:02.000Z", 1, { step_ms: 500 })],
        runStatus: { runId: "run-a", phase: "OFFLINE", modelChat: "OFFLINE", lastTs: "2026-07-17T17:30:01.000Z" },
      }),
      activityLines: [],
      nowMs: now,
    });
    expect(snapshot.status).toBe("RUNNING");
    expect(snapshot.graphs.loss.some((line) => line.includes("OFFLINE/HISTORICAL"))).toBe(false);
  });
  test("source env claims stay unverified without independent binding", () => {
    const snapshot = buildOperatorSurfaceSnapshot({ telemetry: telemetry(), activityLines: [], sourceIdentity: { publicCommit: "f".repeat(40), binarySha256: "b".repeat(64) } });
    expect(snapshot.source).toBe("SOURCE UNVERIFIED/UNBOUND");
  });

  test("mounted pane renders all four bounded families and stays inside narrow terminal bounds", () => {
    const element = OperatorSurfacePane({ telemetry: telemetry({ recentEvents: [train("run-a", 1, "2026-07-17T17:30:01.000Z", 2, { step_ms: 1000, free_gib: 10, total_gib: 24 }), train("run-a", 2, "2026-07-17T17:30:02.000Z", 1, { step_ms: 500, free_gib: 9, total_gib: 24 }), { ts: "2026-07-17T17:30:02.100Z", kind: "checkpoint", source: "journal", payload: { run_id: "run-a", step: 2, checkpoint_manifest_sha256: "a".repeat(64) } }], activeRun: { runId: "run-a", step: 2, loss: 1, stepMs: 500, lastTs: "2026-07-17T17:30:02.000Z" } }), activityLines: [], width: 60, height: 20, terminalColumns: 60, terminalRows: 20, nowMs: Date.parse("2026-07-17T17:30:03.000Z") });
    const body = (element as any).props.children;
    const rows = (body.props.children as any[]).map((child) => child?.props?.children).filter((value) => typeof value === "string");
    expect(body.props.width).toBeLessThanOrEqual(60);
    expect(body.props.height).toBeLessThanOrEqual(20);
    expect(rows.some((row: string) => row.includes("TRAINING/LOSS"))).toBe(true);
    expect(rows.some((row: string) => row.includes("RESOURCE EFFICIENCY"))).toBe(true);
    expect(rows.some((row: string) => row.includes("MODEL GROWTH"))).toBe(true);
    expect(rows.some((row: string) => row.includes("CAPABILITY SCORES"))).toBe(true);
    expect(rows.some((row: string) => row.includes("checkpoint ·▲"))).toBe(true);
    expect(rows).not.toContain("AGENT STREAM");
  });

  test("real Ink viewport keeps all four family headings visible at 60x20", () => {
    const chunks: string[] = [];
    const stdout = { columns: 60, rows: 20 };
    const element = React.createElement(OperatorSurfacePane, {
      telemetry: telemetry({
        recentEvents: [
          train("run-a", 1, "2026-07-17T17:30:01.000Z", 2, { step_ms: 1000, free_gib: 10, total_gib: 24 }),
          train("run-a", 2, "2026-07-17T17:30:02.000Z", 1, { step_ms: 500, free_gib: 9, total_gib: 24 }),
        ],
        activeRun: { runId: "run-a", step: 2, loss: 1, stepMs: 500, lastTs: "2026-07-17T17:30:02.000Z" },
        lastGovernor: { runId: "run-a", vramUsedGib: 14, vramTotalGib: 24, fractionApplied: 0.5 },
      }),
      activityLines: [],
      width: 60,
      height: 20,
      terminalColumns: 60,
      terminalRows: 20,
    });
    const handle = mountInk(element, { stream: { write(s: string) { chunks.push(s); } }, stdout });
    handle.unmount();
    const frame = buildFrame(60, 20);
    parseRenderedIntoFrame(chunks.join(""), frame, new StylePool());
    const rows = frame.cells.map((row) => row.map((cell) => cell?.char ?? " ").join(""));
    for (const heading of ["TRAINING/LOSS", "RESOURCE EFFICIENCY", "MODEL GROWTH", "CAPABILITY SCORES"]) {
      expect(rows.some((row) => row.includes(heading))).toBe(true);
    }
    expect(rows.some((row) => row.includes("STALE") || row.includes("RUNNING"))).toBe(true);
  });

  test("real Ink viewport remains bounded at 80x24", () => {
    const chunks: string[] = [];
    const telemetryState = telemetry({
      recentEvents: [
        train("run-a", 1, "2026-07-17T17:30:01.000Z", 2, { step_ms: 1000, free_gib: 10, total_gib: 24 }),
        train("run-a", 2, "2026-07-17T17:30:02.000Z", 1, { step_ms: 500, free_gib: 9, total_gib: 24 }),
      ],
      activeRun: { runId: "run-a", step: 2, loss: 1, stepMs: 500, lastTs: "2026-07-17T17:30:02.000Z" },
    });
    const handle = mountInk(React.createElement(OperatorSurfacePane, {
      telemetry: telemetryState,
      activityLines: [],
      width: 80,
      height: 24,
      terminalColumns: 80,
      terminalRows: 24,
      nowMs: Date.parse("2026-07-17T17:30:03.000Z"),
    }), { stream: { write(s: string) { chunks.push(s); } }, stdout: { columns: 80, rows: 24 } });
    handle.unmount();
    const frame = buildFrame(80, 24);
    parseRenderedIntoFrame(chunks.join(""), frame, new StylePool());
    const rows = frame.cells.map((row) => row.map((cell) => cell?.char ?? " ").join(""));
    for (const heading of ["TRAINING/LOSS", "RESOURCE EFFICIENCY", "MODEL GROWTH", "CAPABILITY SCORES"]) {
      expect(rows.some((row) => row.includes(heading))).toBe(true);
    }
    expect(rows.some((row) => row.includes("step/time"))).toBe(true);
    expect(rows.some((row) => row.includes("checkpoint"))).toBe(true);
    expect(rows.filter((row) => row.includes("step/time")).length).toBe(1);
    expect(rows.filter((row) => row.includes("checkpoint")).length).toBe(1);
    expect(rows.some((row) => row.includes(String.fromCodePoint(0x2588)))).toBe(true);
    expect(rows.some((row) => row.includes("loss 2 1"))).toBe(false);
  });
  test("downsamples long histories to plot width while preserving checkpoint alignment", () => {
    const events = Array.from({ length: 20 }, (_, index) =>
      train("run-long", index + 1, `2026-07-17T17:30:${String(index).padStart(2, "0")}.000Z`, 20 - index, {
        step_ms: 500,
        free_gib: 10,
        total_gib: 24,
      }),
    );
    events.push({ ts: "2026-07-17T17:30:20.100Z", kind: "checkpoint", source: "journal", payload: { run_id: "run-long", step: 10, checkpoint_manifest_sha256: "a".repeat(64) } });
    const graphs = (buildOperatorSurfaceGraphs as any)(telemetry({ recentEvents: events }), 20);
    const plot = graphs.loss.find((line: string) => line.startsWith("loss plot ")) as string;
    const marker = graphs.loss.find((line: string) => line.startsWith("checkpoint plot ")) as string;
    const glyphs = plot.slice(PLOT_PREFIX_WIDTH);
    expect(glyphs.length).toBeLessThanOrEqual(12);
    expect(marker.slice(PLOT_PREFIX_WIDTH).length).toBe(glyphs.length);
    expect(plot.indexOf(String.fromCodePoint(0x2588))).toBe(marker.indexOf(String.fromCodePoint(0x00b7)));
  });

  test("stale evidence is labeled historical and unbound VRAM is not shown as live", () => {
    const snapshot = buildOperatorSurfaceSnapshot({
      telemetry: telemetry({
        recentEvents: [train("run-a", 1, "2026-07-17T17:30:00.000Z", 2, { step_ms: 1000, free_gib: 10, total_gib: 24 })],
        lastGovernor: { runId: "run-a", vramUsedGib: 14, vramTotalGib: 24, fractionApplied: 0.5 },
        lastCheckpoint: { runId: "run-a", step: 1, checkpointManifestSha256: "a".repeat(64), lastTs: "2026-07-17T17:30:00.000Z" },
      }),
      activityLines: [],
      nowMs: Date.parse("2026-07-17T18:30:00.000Z"),
    });
    expect(snapshot.status).toBe("STALE");
    expect(snapshot.metrics.some((line) => line.includes("VRAM"))).toBe(false);
    expect(snapshot.metrics.some((line) => line.startsWith("checkpoint"))).toBe(false);
    expect(snapshot.graphs.loss.every((line) => line.includes("STALE/HISTORICAL"))).toBe(true);
  });

  test("rejects injected invalid governor totals at the render boundary", () => {
    const telemetryState = telemetry({
      recentEvents: [train("run-boundary", 1, "2026-07-17T17:30:01.000Z", 2, { step_ms: 1000 })],
      lastGovernor: { runId: "run-boundary", vramUsedGib: -1, vramTotalGib: 0, fractionApplied: 0.5 },
    });
    const snapshot = buildOperatorSurfaceSnapshot({ telemetry: telemetryState, activityLines: [], nowMs: Date.parse("2026-07-17T17:30:02.000Z") });
    expect(snapshot.status).toBe("RUNNING");
    expect(snapshot.metrics.some((line) => line.startsWith("VRAM"))).toBe(false);
  });
  test("parses resource-only events independently, bounds GPU utilization, and rejects future timestamps", () => {
    const graphs = buildOperatorSurfaceGraphs(telemetry({
      recentEvents: [
        { ts: "2026-07-17T17:30:01.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-r", step: 1, step_ms: 1000, free_gib: 10, total_gib: 24, gpu_utilization_pct: 120 } },
        { ts: "2026-07-17T17:30:02.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-r", step: 2, step_ms: 500, free_gib: 9, total_gib: 24, gpu_utilization_pct: 50 } },
        { ts: "2099-01-01T00:00:00.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-r", step: 3, step_ms: 250, free_gib: 8, total_gib: 24, gpu_utilization_pct: 50 } },
      ],
    }));
    expect(graphs.points.map((point) => point.step)).toEqual([1, 2]);
    expect(graphs.loss).toContain("LOSS: INSUFFICIENT REAL HISTORY");
    expect(graphs.resource.some((line: string) => line.startsWith("throughput plot "))).toBe(true);
    expect(graphs.resource).toContain("GPU UTILIZATION %: INSUFFICIENT REAL HISTORY");
  });

  test("uses one union step grid with gaps instead of left-packing families", () => {
    const events = [
      train("run-grid", 1, "2026-07-17T17:30:01.000Z", 3, { step_ms: 1000 }),
      train("run-grid", 2, "2026-07-17T17:30:02.000Z", 2, { step_ms: 900 }),
      train("run-grid", 3, "2026-07-17T17:30:03.000Z", 1, { step_ms: 800 }),
      { ts: "2026-07-17T17:30:02.100Z", kind: "model_growth", source: "journal", payload: { run_id: "run-grid", step: 2, value: 20 } },
      { ts: "2026-07-17T17:30:03.100Z", kind: "model_growth", source: "journal", payload: { run_id: "run-grid", step: 3, value: 30 } },
      { ts: "2026-07-17T17:30:04.100Z", kind: "model_growth", source: "journal", payload: { run_id: "run-grid", step: 4, value: 40 } },
      { ts: "2026-07-17T17:30:02.200Z", kind: "capability_score", source: "journal", payload: { run_id: "run-grid", step: 2, score: 0.2 } },
      { ts: "2026-07-17T17:30:03.200Z", kind: "capability_score", source: "journal", payload: { run_id: "run-grid", step: 3, score: 0.3 } },
      { ts: "2026-07-17T17:30:04.200Z", kind: "capability_score", source: "journal", payload: { run_id: "run-grid", step: 4, score: 0.4 } },
    ];
    const element = OperatorSurfacePane({ telemetry: telemetry({ recentEvents: events }), activityLines: [], width: 80, height: 24, terminalColumns: 80, terminalRows: 24, nowMs: Date.parse("2026-07-17T17:30:05.000Z") });
    const body = (element as any).props.children;
    const text = (body.props.children as any[]).map((child) => child?.props?.children).filter((value) => typeof value === "string") as string[];
    expect(text.find((line) => line.startsWith("step/time"))).toContain("1 2 3 4");
    const modelLine = text.find((line) => line.startsWith("model growth"))!;
    const capabilityLine = text.find((line) => line.startsWith("capability score"))!;
    expect(modelLine.slice(20, 24).startsWith(String.fromCodePoint(0x00b7))).toBe(true);
    expect(capabilityLine.slice(20, 24).startsWith(String.fromCodePoint(0x00b7))).toBe(true);
  });

  test("retains final point and latest checkpoint markers when markers exceed capacity", () => {
    const events = Array.from({ length: 20 }, (_, index) => train("run-markers", index + 1, `2026-07-17T17:30:${String(index).padStart(2, "0")}.000Z`, 20 - index, { step_ms: 500 }));
    for (let step = 2; step <= 20; step += 1) events.push({ ts: `2026-07-17T17:30:${String(step).padStart(2, "0")}.500Z`, kind: "checkpoint", source: "journal", payload: { run_id: "run-markers", step, checkpoint_manifest_sha256: "a".repeat(64) } });
    const graphs = buildOperatorSurfaceGraphs(telemetry({ recentEvents: events }), 12, Date.parse("2026-07-17T17:31:00.000Z"));
    const axis = graphs.loss.find((line) => line.startsWith("step/time "))!;
    const marker = graphs.loss.find((line) => line.startsWith("checkpoint plot "))!;
    expect(axis).toContain("20@");
    expect(marker.slice(PLOT_PREFIX_WIDTH).length).toBeLessThanOrEqual(4);
    expect(marker.slice(PLOT_PREFIX_WIDTH)).toContain(String.fromCodePoint(0x25b2));
  });
  test("renders a truthful activity pane title", () => {
    const element = OperatorSurfacePane({ telemetry: telemetry(), activityLines: [], width: 48 });
    expect((element as any).props["data-operator-surface"]).toBe("right-pane");
    expect((element as any).props.children.props.borderTitle).toBe("LIVE RUN / ACTIVITY/EVENT FEED");
  });
});
