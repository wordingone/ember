// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { buildOperatorSurfaceGraphs, buildOperatorSurfaceSnapshot, getOperatorRunStatus, OperatorSurfacePane } from "./operator-surface-pane.ts";
import type { TelemetryState } from "../services/telemetry-watch.ts";
import type { ActivityFeedLine } from "./activity-feed-pane.ts";

const ellipsis = String.fromCodePoint(0x2026);
const activity: ActivityFeedLine[] = [
  { ts: "2026-07-17T17:30:00.000Z", source: "receipt", text: "checkpoint receipt landed", path: "receipts/run/checkpoint.json" },
];

function telemetry(overrides: Partial<TelemetryState> = {}): TelemetryState {
  return { recentEvents: [], ...overrides };
}

describe("OperatorSurfacePane", () => {
  test("derives loss, progress, throughput, VRAM, checkpoint, source identity, and real agent lines", () => {
    const snapshot = buildOperatorSurfaceSnapshot({
      telemetry: telemetry({
        activeRun: { runId: "run-1", step: 12, totalSteps: 100, loss: 1.25, stepMs: 500, lastTs: "2026-07-17T17:30:00.000Z" },
        lastGovernor: { vramUsedGib: 7.5, vramTotalGib: 24, fractionApplied: 0.5 },
        lastCheckpoint: { runId: "run-1", step: 10, checkpointManifestSha256: "a".repeat(64), lastTs: "2026-07-17T17:29:00.000Z" },
      }),
      activityLines: activity,
      sourceIdentity: { publicCommit: "f".repeat(40), binarySha256: "b".repeat(64) },
      nowMs: Date.parse("2026-07-17T17:30:01.000Z"),
    });

    expect(snapshot.status).toBe("RUNNING");
    expect(snapshot.metrics).toEqual([
      "loss 1.25",
      "step 12/100",
      "throughput 120.0 step/min",
      "VRAM 7.5/24.0 GiB",
      `checkpoint step 10 ${"a".repeat(12)}${ellipsis}`,
    ]);
    expect(snapshot.source).toBe("SOURCE UNVERIFIED/UNBOUND");
    expect(snapshot.agentLines[0]).toContain("[receipt] checkpoint receipt landed [receipts/run/checkpoint.json]");
  });

  test("fails closed with explicit idle/source-unbound state when evidence is absent", () => {
    const snapshot = buildOperatorSurfaceSnapshot({ telemetry: telemetry(), activityLines: [] });
    expect(snapshot.status).toBe("IDLE");
    expect(snapshot.metrics).toEqual([]);
    expect(snapshot.source).toBe("SOURCE UNVERIFIED/UNBOUND");
    expect(snapshot.agentLines).toEqual(["activity: none observed yet"]);
  });

  test("turns multiple real train_step points into ordered loss and VRAM/throughput graphs", () => {
    const graphTelemetry = telemetry({
      recentEvents: [
        { ts: "2026-07-17T17:30:01.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 2, loss: 1.5, step_ms: 500, free_gib: 10, total_gib: 24 } },
        { ts: "2026-07-17T17:30:02.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 1, loss: 2.5, step_ms: 1000, free_gib: 9, total_gib: 24 } },
        { ts: "2026-07-17T17:30:03.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 3, loss: 1, step_ms: 250, free_gib: 8, total_gib: 24 } },
        { ts: "2026-07-17T17:30:03.100Z", kind: "checkpoint", source: "journal", payload: { run_id: "run-a", step: 3, checkpoint_manifest_sha256: "a".repeat(64) } },
        { ts: "2026-07-17T17:30:03.200Z", kind: "checkpoint", source: "journal", payload: { run_id: "foreign", step: 77, checkpoint_manifest_sha256: "b".repeat(64) } },
      ],
      activeRun: { runId: "run-a", step: 3, loss: 1, stepMs: 250, lastTs: "2026-07-17T17:30:03.000Z" },
    });
    const graphs = buildOperatorSurfaceGraphs(graphTelemetry);
    expect(graphs.loss.join("\n")).toContain("loss [1.00..2.50]");
    expect(graphs.loss.join("\n")).toContain("steps 1 2 3");
    expect(graphs.loss.join("\n").indexOf("1.00")).toBeLessThan(graphs.loss.join("\n").indexOf("2.50"));
    expect(graphs.resource.join("\n")).toContain("throughput");
    expect(graphs.resource.join("\n")).toContain("VRAM");
    expect(graphs.resource.join("\n")).toContain("steps 1 2 3");
    expect(graphs.checkpoints).toEqual([{ step: 3, label: "checkpoint" }]);
  });

  test("filters mixed run ids and malformed/nonfinite points without combining evidence", () => {
    const graphTelemetry = telemetry({
      recentEvents: [
        { ts: "2026-07-17T17:30:01.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 1, loss: 2, step_ms: 1000, free_gib: 10, total_gib: 24 } },
        { ts: "2026-07-17T17:30:02.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-b", step: 99, loss: 99, step_ms: 1, free_gib: 1, total_gib: 24 } },
        { ts: "2026-07-17T17:30:03.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 2, loss: Number.NaN, step_ms: Number.POSITIVE_INFINITY, free_gib: 9, total_gib: 24 } },
        { ts: "2026-07-17T17:30:04.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 3, loss: 1, step_ms: 500, free_gib: 8, total_gib: 24 } },
      ],
      activeRun: { runId: "run-a", step: 3, loss: 1, stepMs: 500, lastTs: "2026-07-17T17:30:04.000Z" },
    });
    const graphs = buildOperatorSurfaceGraphs(graphTelemetry);
    expect(graphs.runId).toBe("run-a");
    expect(graphs.loss.join("\n")).toContain("steps 1 3");
    expect(graphs.loss.join("\n")).not.toContain("99");
    expect(graphs.loss.join("\n")).not.toContain("NaN");
    expect(graphs.resource.join("\n")).not.toContain("Infinity");
  });

  test("uses only the latest real run when activeRun is absent", () => {
    const graphs = buildOperatorSurfaceGraphs(telemetry({ recentEvents: [
      { ts: "2026-07-17T17:30:01.000Z", kind: "train_step", source: "journal", payload: { run_id: "old-run", step: 1, loss: 3, step_ms: 1000, free_gib: 10, total_gib: 24 } },
      { ts: "2026-07-17T17:30:02.000Z", kind: "train_step", source: "journal", payload: { run_id: "new-run", step: 1, loss: 2, step_ms: 500, free_gib: 9, total_gib: 24 } },
      { ts: "2026-07-17T17:30:03.000Z", kind: "train_step", source: "journal", payload: { run_id: "new-run", step: 2, loss: 1, step_ms: 250, free_gib: 8, total_gib: 24 } },
    ] }));
    expect(graphs.runId).toBe("new-run");
    expect(graphs.points.map((point) => point.step)).toEqual([1, 2]);
    expect(graphs.points.every((point) => point.runId === "new-run")).toBe(true);
  });

  test("does not fabricate a trend from empty or one-point evidence", () => {
    expect(buildOperatorSurfaceGraphs(telemetry()).loss.join("\n")).toContain("insufficient real history");
    expect(buildOperatorSurfaceGraphs(telemetry({ recentEvents: [
      { ts: "2026-07-17T17:30:01.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 1, loss: 2, step_ms: 1000, free_gib: 10, total_gib: 24 } },
    ] })).loss.join("\n")).toContain("insufficient real history");
  });

  test("distinguishes idle, stale, and offline using real evidence", () => {
    const now = Date.parse("2026-07-17T17:31:00.000Z");
    expect(getOperatorRunStatus(telemetry(), now)).toBe("IDLE");
    expect(getOperatorRunStatus(telemetry({ recentEvents: [
      { ts: "2026-07-17T17:30:00.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 1, loss: 2 } },
    ] }), now)).toBe("STALE");
    expect(getOperatorRunStatus(telemetry({ channelStatus: "OFFLINE" } as any), now)).toBe("OFFLINE");
  });

  test("does not trust environment source claims without independent binding", () => {
    const snapshot = buildOperatorSurfaceSnapshot({
      telemetry: telemetry(),
      activityLines: [],
      sourceIdentity: { publicCommit: "f".repeat(40), binarySha256: "b".repeat(64) },
    });
    expect(snapshot.source).toBe("SOURCE UNVERIFIED/UNBOUND");
  });

  test("mounted pane exposes the bounded chart rows at the desktop pane width", () => {
    const element = OperatorSurfacePane({
      telemetry: telemetry({
        recentEvents: [
          { ts: "2026-07-17T17:30:01.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 1, loss: 2, step_ms: 1000, free_gib: 10, total_gib: 24 } },
          { ts: "2026-07-17T17:30:02.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 2, loss: 1, step_ms: 500, free_gib: 9, total_gib: 24 } },
          { ts: "2026-07-17T17:30:02.100Z", kind: "checkpoint", source: "journal", payload: { run_id: "run-a", step: 2, checkpoint_manifest_sha256: "a".repeat(64) } },
        ],
        activeRun: { runId: "run-a", step: 2, loss: 1, stepMs: 500, lastTs: "2026-07-17T17:30:02.000Z" },
      }),
      activityLines: [],
      width: 1727,
    });
    const body = (element as any).props.children;
    const rows = (body.props.children as any[]).map((child) => child?.props?.children).filter((value) => typeof value === "string");
    expect(body.props.width).toBe(1727);
    expect(rows).toContain("loss [1.00..2.00]");
    expect(rows).toContain("steps 1 2");
    expect(rows).toContain("checkpoints 2");
    expect(rows).toContain("ACTIVITY/EVENT FEED");
    expect(rows).not.toContain("AGENT STREAM");
  });
  test("renders a titled right-side pane from the snapshot without inventing data", () => {
    const element = OperatorSurfacePane({ telemetry: telemetry(), activityLines: [], sourceIdentity: undefined, width: 48 });
    expect((element as any).props["data-operator-surface"]).toBe("right-pane");
    expect((element as any).props.children.props.borderTitle).toBe("LIVE RUN / ACTIVITY/EVENT FEED");
  });
});
