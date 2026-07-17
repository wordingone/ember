// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { buildOperatorSurfaceSnapshot, OperatorSurfacePane } from "./operator-surface-pane.ts";
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
    expect(snapshot.source).toBe(`source ${"f".repeat(12)}${ellipsis} binary ${"b".repeat(12)}${ellipsis}`);
    expect(snapshot.agentLines[0]).toContain("[receipt] checkpoint receipt landed [receipts/run/checkpoint.json]");
  });

  test("fails closed with explicit idle/source-unbound state when evidence is absent", () => {
    const snapshot = buildOperatorSurfaceSnapshot({ telemetry: telemetry(), activityLines: [] });
    expect(snapshot.status).toBe("IDLE_OR_STALE");
    expect(snapshot.metrics).toEqual([]);
    expect(snapshot.source).toBe("SOURCE UNBOUND");
    expect(snapshot.agentLines).toEqual(["activity: none observed yet"]);
  });

  test("renders a titled right-side pane from the snapshot without inventing data", () => {
    const element = OperatorSurfacePane({ telemetry: telemetry(), activityLines: [], sourceIdentity: undefined, width: 48 });
    expect((element as any).props["data-operator-surface"]).toBe("right-pane");
    expect((element as any).props.children.props.borderTitle).toBe("LIVE RUN / AGENT STREAM");
  });
});