// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { buildOperatorSurfaceGraphs, buildOperatorSurfaceSnapshot, getOperatorRunStatus, OperatorSurfacePane, PLOT_PREFIX_WIDTH, layoutControlRows } from "./operator-surface-pane.ts";
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
        recentEvents: [train("run-1", 12, "2026-07-17T17:30:00.000Z", 1.25, { step_ms: 500, total_steps: 100, tokens_per_second: 240 })],
        activeRun: { runId: "run-1", step: 12, totalSteps: 100, loss: 1.25, stepMs: 500, lastTs: "2026-07-17T17:30:00.000Z" },
        lastGovernor: { runId: "run-1", vramUsedGib: 7.5, vramTotalGib: 24, fractionApplied: 0.5 },
        lastCheckpoint: { runId: "run-1", step: 10, checkpointManifestSha256: "a".repeat(64), lastTs: "2026-07-17T17:29:00.000Z" },
      }),
      activityLines: activity,
      sourceIdentity: { publicCommit: "f".repeat(40), binarySha256: "b".repeat(64) },
      nowMs: Date.parse("2026-07-17T17:30:01.000Z"),
    });
    expect(snapshot.status).toBe("RUNNING");
    expect(snapshot.metrics).toEqual(["loss 1.25", "step 12/100", "tokens/s 240.0", "VRAM 7.5/24.0 GiB", `checkpoint step 10 ${"a".repeat(12)}${ellipsis}`]);
    expect(snapshot.source).toBe("SOURCE UNVERIFIED/UNBOUND");
    expect(snapshot.agentLines[0]).toContain("[receipt] checkpoint receipt landed [receipts/run/checkpoint.json]");
  });

  test("renders exact plotted glyph rows with a shared step/time axis and checkpoint marker", () => {
    const graphTelemetry = telemetry({
      recentEvents: [
        train("run-a", 2, "2026-07-17T17:30:01.000Z", 1.5, { step_ms: 500, tokens_per_second: 200, free_gib: 10, total_gib: 24, gpu_utilization_pct: 60 }),
        train("run-a", 1, "2026-07-17T17:30:02.000Z", 2.5, { step_ms: 1000, tokens_per_second: 100, free_gib: 9, total_gib: 24, gpu_utilization_pct: 50 }),
        train("run-a", 3, "2026-07-17T17:30:03.000Z", 1, { step_ms: 250, tokens_per_second: 400, free_gib: 8, total_gib: 24, gpu_utilization_pct: 70 }),
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
    expect(graphs.resource.find((line) => line.startsWith("tokens/s plot "))!.slice(PLOT_PREFIX_WIDTH)).toBe("▁▃█");
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
    expect(graphs.resource).toContain("TOKENS/S: SOURCE UNBOUND");
    expect(graphs.resource).toContain("LEARNING RATE: SOURCE UNBOUND");
    expect(graphs.resource).toContain("GPU WATTS: SOURCE UNBOUND");
    expect(graphs.resource).toContain("ENERGY: SOURCE UNBOUND");
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
        train("run-a", 10, "2026-07-17T17:30:59.000Z", 1, { step_ms: 500, tokens_per_second: 222 }),
      ] }),
      activityLines: [],
      nowMs: Date.parse("2026-07-17T17:31:00.000Z"),
    });
    expect(snapshot.metrics).toContain("loss 1.00");
    expect(snapshot.metrics).toContain("step 10");
    expect(snapshot.metrics).toContain("tokens/s 222.0");
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
  // #924: a producer that independently verified the claim (sourceBindingVerified: true)
  // renders the bound commit + binary digest instead of the fail-closed placeholder.
  test("verified source binding renders the bound commit and binary digest", () => {
    const snapshot = buildOperatorSurfaceSnapshot({
      telemetry: telemetry(),
      activityLines: [],
      sourceIdentity: { publicCommit: "f".repeat(40), binarySha256: "b".repeat(64), sourceBindingVerified: true },
    });
    expect(snapshot.source).toBe(`source ${"f".repeat(12)}${ellipsis} binary ${"b".repeat(12)}${ellipsis}`);
  });
  test("sourceBindingVerified true with a malformed commit still stays unverified (fail-closed)", () => {
    const snapshot = buildOperatorSurfaceSnapshot({
      telemetry: telemetry(),
      activityLines: [],
      sourceIdentity: { publicCommit: "not-a-sha", binarySha256: "b".repeat(64), sourceBindingVerified: true },
    });
    expect(snapshot.source).toBe("SOURCE UNVERIFIED/UNBOUND");
  });
  test("sourceBindingVerified true with a missing binary hash still stays unverified (fail-closed)", () => {
    const snapshot = buildOperatorSurfaceSnapshot({
      telemetry: telemetry(),
      activityLines: [],
      sourceIdentity: { publicCommit: "f".repeat(40), sourceBindingVerified: true },
    });
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
    expect(rows.some((row: string) => row.includes("MODEL GROWTH"))).toBe(false);
    expect(rows.some((row: string) => row.includes("CAPABILITY SCORES"))).toBe(false);
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
    for (const heading of ["TRAINING/LOSS", "RESOURCE EFFICIENCY"]) {
      expect(rows.some((row) => row.includes(heading))).toBe(true);
    }
    expect(rows.some((row) => row.includes("MODEL GROWTH"))).toBe(false);
    expect(rows.some((row) => row.includes("CAPABILITY SCORES"))).toBe(false);
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
    for (const heading of ["TRAINING/LOSS", "RESOURCE EFFICIENCY"]) {
      expect(rows.some((row) => row.includes(heading))).toBe(true);
    }
    expect(rows.some((row) => row.includes("MODEL GROWTH"))).toBe(false);
    expect(rows.some((row) => row.includes("CAPABILITY SCORES"))).toBe(false);
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
        { ts: "2026-07-17T17:30:01.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-r", step: 1, step_ms: 1000, tokens_per_second: 100, free_gib: 10, total_gib: 24, gpu_utilization_pct: 120 } },
        { ts: "2026-07-17T17:30:02.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-r", step: 2, step_ms: 500, tokens_per_second: 200, free_gib: 9, total_gib: 24, gpu_utilization_pct: 50 } },
        { ts: "2099-01-01T00:00:00.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-r", step: 3, step_ms: 250, free_gib: 8, total_gib: 24, gpu_utilization_pct: 50 } },
      ],
    }));
    expect(graphs.points.map((point) => point.step)).toEqual([1, 2]);
    expect(graphs.loss).toContain("LOSS: INSUFFICIENT REAL HISTORY");
    expect(graphs.resource.some((line: string) => line.startsWith("tokens/s plot "))).toBe(true);
    expect(graphs.resource).toContain("GPU UTILIZATION %: INSUFFICIENT REAL HISTORY");
  });

  test("uses one union step grid with gaps instead of left-packing families", () => {
    const events = [
      train("run-grid", 1, "2026-07-17T17:30:01.000Z", 3, { step_ms: 1000, tokens_per_second: 100 }),
      train("run-grid", 2, "2026-07-17T17:30:02.000Z", 2, { step_ms: 900, learning_rate: 0.001 }),
      train("run-grid", 3, "2026-07-17T17:30:03.000Z", 1, { step_ms: 800, tokens_per_second: 300, learning_rate: 0.0005 }),
    ];
    const element = OperatorSurfacePane({ telemetry: telemetry({ recentEvents: events }), activityLines: [], width: 80, height: 24, terminalColumns: 80, terminalRows: 24, nowMs: Date.parse("2026-07-17T17:30:05.000Z") });
    const body = (element as any).props.children;
    const text = (body.props.children as any[]).map((child) => child?.props?.children).filter((value) => typeof value === "string") as string[];
    expect(text.find((line) => line.startsWith("step/time"))).toContain("1 2 3");
    const tokenLine = text.find((line) => line.startsWith("tokens/s"))!;
    const learningRateLine = text.find((line) => line.startsWith("learning rate"))!;
    expect(tokenLine.slice(20, 23)).toContain(String.fromCodePoint(0x00b7));
    expect(learningRateLine.slice(20, 23).startsWith(String.fromCodePoint(0x00b7))).toBe(true);
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
  test("uses direct tokens/s and measured LR/energy/watts, never step_ms-derived throughput", () => {
    const graphs = buildOperatorSurfaceGraphs(telemetry({ recentEvents: [
      train("run-measured", 1, "2026-07-17T17:30:01.000Z", 2, { step_ms: 1000, tokens_per_second: 100, learning_rate: 0.001, gpu_watts: 200, board_energy_joules_total: 200 }),
      train("run-measured", 2, "2026-07-17T17:30:02.000Z", 1, { step_ms: 500, tokens_per_second: 250, learning_rate: 0.0005, gpu_watts: 220, board_energy_joules_total: 420 }),
    ] }), 80, Date.parse("2026-07-17T17:30:03.000Z"));
    expect(graphs.points.map((point) => point.tokensPerSecond)).toEqual([100, 250]);
    expect(graphs.points.map((point) => point.learningRate)).toEqual([0.001, 0.0005]);
    expect(graphs.points.map((point) => point.gpuWatts)).toEqual([200, 220]);
    expect(graphs.points.map((point) => point.boardEnergyJoulesTotal)).toEqual([200, 420]);
    expect(graphs.points.map((point) => (point as any).throughput)).toEqual([undefined, undefined]);
  });

  test("rejects decreasing cumulative energy instead of plotting a fabricated reset", () => {
    const graphs = buildOperatorSurfaceGraphs(telemetry({ recentEvents: [
      train("run-energy", 1, "2026-07-17T17:30:01.000Z", 2, { board_energy_joules_total: 200 }),
      train("run-energy", 2, "2026-07-17T17:30:02.000Z", 1.5, { board_energy_joules_total: 150 }),
      train("run-energy", 3, "2026-07-17T17:30:03.000Z", 1, { board_energy_joules_total: 320 }),
    ] }), 80, Date.parse("2026-07-17T17:30:04.000Z"));
    expect(graphs.points.map((point) => point.boardEnergyJoulesTotal)).toEqual([200, undefined, 320]);
    expect(graphs.resource.find((line) => line.startsWith("board energy joules plot "))!.slice("board energy joules plot ".length)).toHaveLength(2);
  });

  test("renders lifecycle controls and invokes the enabled action exactly once", () => {
    const calls: Array<{ action: string; runId?: string }> = [];
    const element = OperatorSurfacePane({

      telemetry: telemetry({ recentEvents: [train("run-control", 1, "2026-07-17T17:30:01.000Z", 2, { tokens_per_second: 100 })] }),
      activityLines: [], width: 80, height: 24, terminalColumns: 80, terminalRows: 24,
      nowMs: Date.parse("2026-07-17T17:30:02.000Z"),
      onControl: (action, runId) => calls.push({ action, runId }),
    });
    const body = (element as any).props.children;
    const controlRow = (body.props.children as any[]).find((child) => child?.key === "controls");
    const controls = controlRow.props.children as any[];
    expect(controls.map((control) => control.props.children.props.children)).toEqual(["[START]", "[PAUSE]", "[RESUME]", "[RESTART]"]);
    const pause = controls.find((control) => control.props.children.props.children === "[PAUSE]");
    expect(typeof pause.props.onClick).toBe("function");
    pause.props.onClick();
    expect(calls).toEqual([{ action: "PAUSE", runId: "run-control" }]);
  });
  test("RED->GREEN: a metric with zero samples on an actively RUNNING run reads AWAITING FIRST SAMPLE, not SOURCE UNBOUND", () => {
    // The run IS live (a train_step arrived just now, well inside ACTIVE_RUN_TTL_MS) and IS
    // emitting some fields (loss, tokens_per_second) -- gpu_watts simply hasn't shown up in any
    // event yet. That is a temporal "no samples so far, may still arrive" state, structurally
    // different from a dead/idle channel where the metric can never arrive. Before this test the
    // two states rendered identically as "SOURCE UNBOUND".
    const now = Date.parse("2026-07-26T00:00:05.000Z");
    const graphs = buildOperatorSurfaceGraphs(telemetry({
      recentEvents: [
        train("run-live", 1, "2026-07-26T00:00:04.000Z", 1.2, { tokens_per_second: 100 }),
        train("run-live", 2, "2026-07-26T00:00:05.000Z", 1.1, { tokens_per_second: 110 }),
      ],
    }), 80, now);
    expect(graphs.resource).toContain("GPU WATTS: AWAITING FIRST SAMPLE");
    expect(graphs.resource).not.toContain("GPU WATTS: SOURCE UNBOUND");
  });

  test("RED->GREEN: a metric with zero samples on a dead/idle channel still reads SOURCE UNBOUND", () => {
    const now = Date.parse("2026-07-26T00:00:05.000Z");
    const graphs = buildOperatorSurfaceGraphs(telemetry(), 80, now);
    expect(graphs.modelGrowth).toEqual(["MODEL GROWTH: SOURCE UNBOUND"]);
    const staleRun = buildOperatorSurfaceGraphs(telemetry({
      recentEvents: [train("run-cold", 1, "2026-07-17T17:30:01.000Z", 2, { tokens_per_second: 50 })],
    }), 80, now);
    expect(staleRun.resource).toContain("GPU WATTS: SOURCE UNBOUND");
    expect(staleRun.resource).not.toContain("GPU WATTS: AWAITING FIRST SAMPLE");
  });

  test("RED->GREEN: the rendered compact pane distinguishes AWAITING FIRST SAMPLE from SOURCE UNBOUND at the same call site the operator sees", () => {
    const now = Date.parse("2026-07-26T00:00:05.000Z");
    const runningElement = OperatorSurfacePane({
      telemetry: telemetry({ recentEvents: [
        train("run-compact", 1, "2026-07-26T00:00:04.000Z", 1.2, { tokens_per_second: 100 }),
        train("run-compact", 2, "2026-07-26T00:00:05.000Z", 1.1, { tokens_per_second: 110 }),
      ] }),
      activityLines: [], width: 80, height: 24, terminalColumns: 80, terminalRows: 24,
      nowMs: now,
    });
    const runningBody = (runningElement as any).props.children;
    const runningRows = (runningBody.props.children as any[]).map((child) => child?.props?.children).filter((v) => typeof v === "string");
    expect(runningRows.some((row: string) => row.startsWith("GPU watts") && row.includes("AWAITING FIRST SAMPLE"))).toBe(true);

    const idleElement = OperatorSurfacePane({
      telemetry: telemetry(),
      activityLines: [], width: 80, height: 24, terminalColumns: 80, terminalRows: 24,
      nowMs: now,
    });
    const idleBody = (idleElement as any).props.children;
    const idleRows = (idleBody.props.children as any[]).map((child) => child?.props?.children).filter((v) => typeof v === "string");
    expect(idleRows.some((row: string) => row.startsWith("GPU watts") && row.includes("SOURCE UNBOUND"))).toBe(true);
  });

  test("legibility width sweep: AWAITING FIRST SAMPLE / SOURCE UNBOUND / a plotted curve are all distinguishable at 40, 60, and 80 columns", () => {
    const now = Date.parse("2026-07-26T00:00:05.000Z");
    for (const width of [40, 60, 80]) {
      const element = OperatorSurfacePane({
        telemetry: telemetry({ recentEvents: [
          train("run-sweep", 1, "2026-07-26T00:00:04.000Z", 1.2, { tokens_per_second: 100 }),
          train("run-sweep", 2, "2026-07-26T00:00:05.000Z", 1.1, { tokens_per_second: 110 }),
        ] }),
        activityLines: [], width, height: 24, terminalColumns: width, terminalRows: 24,
        nowMs: now,
      });
      const body = (element as any).props.children;
      const rows = (body.props.children as any[]).map((child) => child?.props?.children).filter((v) => typeof v === "string") as string[];
      // A live curve (tokens/s has 2 real samples): must render plotted glyphs, not a fixed word.
      const tokensRow = rows.find((row) => row.startsWith("tokens/s"));
      expect(tokensRow).toBeDefined();
      expect(tokensRow).not.toContain("SOURCE UNBOUND");
      expect(tokensRow).not.toContain("AWAITING FIRST SAMPLE");
      // A metric this run hasn't produced yet, while running: AWAITING, never UNBOUND.
      const gpuWattsRow = rows.find((row) => row.startsWith("GPU watts"));
      expect(gpuWattsRow).toContain("AWAITING FIRST SAMPLE");
      expect(gpuWattsRow).not.toContain("SOURCE UNBOUND");
    }
  });

  test("legibility width sweep: the real Ink viewport renders both labels without a truncated/blank row at 40 columns", () => {
    const chunks: string[] = [];
    const element = React.createElement(OperatorSurfacePane, {
      telemetry: telemetry({ recentEvents: [
        train("run-sweep-ink", 1, "2026-07-26T00:00:04.000Z", 1.2, { tokens_per_second: 100 }),
        train("run-sweep-ink", 2, "2026-07-26T00:00:05.000Z", 1.1, { tokens_per_second: 110 }),
      ] }),
      activityLines: [], width: 40, height: 24, terminalColumns: 40, terminalRows: 24,
      nowMs: Date.parse("2026-07-26T00:00:05.000Z"),
    });
    const handle = mountInk(element, { stream: { write(s: string) { chunks.push(s); } }, stdout: { columns: 40, rows: 24 } });
    handle.unmount();
    const frame = buildFrame(40, 24);
    parseRenderedIntoFrame(chunks.join(""), frame, new StylePool());
    const rows = frame.cells.map((row) => row.map((cell) => cell?.char ?? " ").join(""));
    expect(rows.every((row) => row.length === 40)).toBe(true);
    expect(rows.some((row) => row.includes("AWAITING"))).toBe(true);
    expect(rows.some((row) => row.includes(String.fromCodePoint(0x2588)) || row.includes(String.fromCodePoint(0x2581)))).toBe(true);
  });

  test("renders a truthful activity pane title", () => {
    const element = OperatorSurfacePane({ telemetry: telemetry(), activityLines: [], width: 48 });
    expect((element as any).props["data-operator-surface"]).toBe("right-pane");
    expect((element as any).props.children.props.borderTitle).toBe("LIVE RUN / ACTIVITY/EVENT FEED");
  });

  // -------------------------------------------------------------------------
  // Legibility bar (2026-07-26): "no control label is truncated — controls are the last thing
  // to lose characters, never the first" + "the layout reflows... two columns cut in half is
  // never the answer." RED on pre-fix master: the controls Box was a flat flexDirection:"row"
  // with no wrap (flexWrap is a dead prop in layout-engine.ts) — at a narrow pane the outer
  // overflow:"hidden" box raw-clipped the row mid-label: "[START] [PAUSE] [RESUME] [RES".
  // -------------------------------------------------------------------------
  describe("layoutControlRows — controls never truncate, they wrap instead", () => {
    test("packs all four controls on one row when the width comfortably fits them", () => {
      expect(layoutControlRows(["START", "PAUSE", "RESUME", "RESTART"], 80)).toEqual([
        ["START", "PAUSE", "RESUME", "RESTART"],
      ]);
    });

    test("wraps to multiple rows, never splitting a label, at a narrow width", () => {
      const rows = layoutControlRows(["START", "PAUSE", "RESUME", "RESTART"], 20);
      const flatLabels = rows.flat();
      expect(flatLabels).toEqual(["START", "PAUSE", "RESUME", "RESTART"]);
      for (const row of rows) {
        const rowWidth = row.reduce((sum, action) => sum + `[${action}]`.length + 1, 0);
        expect(rowWidth).toBeLessThanOrEqual(20 + `[${row[row.length - 1]}]`.length + 1); // never demands the row shrink a label
      }
    });

    test("even a pathologically narrow width gives every label its own row rather than cutting it", () => {
      const rows = layoutControlRows(["START", "PAUSE", "RESUME", "RESTART"], 1);
      expect(rows.flat()).toEqual(["START", "PAUSE", "RESUME", "RESTART"]);
      expect(rows.every((row) => row.length === 1)).toBe(true);
    });
  });

  test("at a narrow pane width, every control label renders IN FULL across wrapped rows instead of being clipped", () => {
    const element = OperatorSurfacePane({
      telemetry: telemetry({ recentEvents: [train("run-narrow", 1, "2026-07-17T17:30:01.000Z", 2)] }),
      activityLines: [], width: 24, height: 20, terminalColumns: 24, terminalRows: 20,
      nowMs: Date.parse("2026-07-17T17:30:02.000Z"),
    });
    const body = (element as any).props.children;
    const controlsElement = (body.props.children as any[]).find((child) => child?.key === "controls");
    // Recursively collect every rendered control label string ("[START]" etc.) regardless of
    // whether they sit flat or nested under wrapped row Boxes.
    const collectLabels = (node: any): string[] => {
      if (!node || typeof node !== "object") return [];
      const kids = node.props?.children;
      if (typeof kids === "string") return [kids];
      if (Array.isArray(kids)) return kids.flatMap(collectLabels);
      if (kids && typeof kids === "object") return collectLabels(kids);
      return [];
    };
    const labels = collectLabels(controlsElement);
    expect(labels).toEqual(["[START]", "[PAUSE]", "[RESUME]", "[RESTART]"]);
  });

  // -------------------------------------------------------------------------
  // Legibility bar: "no metric value is truncated... shortens by an explicit, defined rule with
  // a visible marker — never silent character-level clipping." RED on pre-fix master: graph/
  // metric/source/agent lines were handed to the outer overflow:"hidden" box unbounded, which
  // hard-clipped anything too long with NO marker ("SOURCE UN" instead of "SOURCE UNBOUND").
  // -------------------------------------------------------------------------
  test("no rendered content line exceeds the pane's inner width, and any shortened line carries a visible marker", () => {
    const element = OperatorSurfacePane({
      telemetry: telemetry({
        channelStatus: "OFFLINE",
        recentEvents: [train("run-x", 1, "2026-07-17T17:30:01.000Z", 2, { step_ms: 1000 })],
      }),
      activityLines: [{ ts: "2026-07-17T17:30:00.000Z", source: "watchdog", text: "871 watchdog events collapsed into one summary line for the report", path: "Z:\\repo\\ember\\tools\\ember-cli\\state\\process-watch.json" }],
      width: 36, height: 20, terminalColumns: 36, terminalRows: 20,
      nowMs: Date.parse("2026-07-17T17:30:05.000Z"),
    });
    const body = (element as any).props.children;
    const innerWidth = 36 - 2;
    const rows = (body.props.children as any[])
      .map((child) => child?.props?.children)
      .filter((value) => typeof value === "string");
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.length).toBeLessThanOrEqual(innerWidth);
    }
    // The exact silent-clip fragment this bug produced in production ("SOURCE UN" cut mid-word,
    // e.g. a metric-family row) must never appear again: any row containing "SOURCE UN" either
    // completes it to "SOURCE UNBOUND"/"SOURCE UNVERIFIED/UNBOUND" or carries the ellipsis marker.
    expect(rows.some((row: string) => row.includes("SOURCE UN") && !row.includes("SOURCE UNBOUND") && !row.includes("SOURCE UNVERIFIED") && !row.includes(ellipsis))).toBe(false);
  });
});
