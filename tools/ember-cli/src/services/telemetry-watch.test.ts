// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { afterEach, describe, expect, test } from "bun:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { getState, startTelemetryWatch } from "./telemetry-watch.ts";

let scratch: string | undefined;

afterEach(async () => {
  if (scratch) await rm(scratch, { recursive: true, force: true });
  scratch = undefined;
});

describe("training telemetry custody", () => {
  test("retains live VRAM, optimizer progress, verified checkpoint, and model-seat status", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-"));
    const channel = join(scratch, "telemetry.jsonl");
    const now = Date.parse("2026-07-17T05:00:00.000Z");
    const events = [
      { ts: "2026-07-17T05:00:00.000Z", kind: "run_status", source: "ember-restart-3b", payload: { run_id: "vision-v4", phase: "TRAINING", model_chat: "OFFLINE", restore_not_before: "2026-07-18T11:00:00-07:00" } },
      { ts: "2026-07-17T05:00:01.000Z", kind: "governor", source: "ember-restart-3b", payload: { free_gib: 3.5, total_gib: 24, vram_fraction_applied: 0.95 } },
      { ts: "2026-07-17T05:00:02.000Z", kind: "train_step", source: "ember-restart-3b", payload: { run_id: "vision-v4", step: 8192, total_steps: 65538, loss: 4.125, step_ms: 1250 } },
      { ts: "2026-07-17T05:00:03.000Z", kind: "checkpoint", source: "ember-restart-3b", payload: { run_id: "vision-v4", step: 8192, checkpoint_manifest_sha256: "a".repeat(64) } },
    ];
    await writeFile(channel, events.map((event) => JSON.stringify(event)).join("\n") + "\n", "utf8");
    const handle = startTelemetryWatch({ channelPath: channel, now: () => now });
    try {
      await Bun.sleep(650);
      const state = getState();
      expect(state.lastGovernor).toEqual({ vramUsedGib: 20.5, vramTotalGib: 24, fractionApplied: 0.95 });
      expect(state.activeRun).toMatchObject({ runId: "vision-v4", step: 8192, totalSteps: 65538, loss: 4.125, stepMs: 1250 });
      expect(state.lastCheckpoint).toEqual({ runId: "vision-v4", step: 8192, checkpointManifestSha256: "a".repeat(64), lastTs: "2026-07-17T05:00:03.000Z" });
      expect(state.runStatus).toEqual({ runId: "vision-v4", phase: "TRAINING", modelChat: "OFFLINE", restoreNotBefore: "2026-07-18T11:00:00-07:00", lastTs: "2026-07-17T05:00:00.000Z" });
    } finally {
      handle.stop();
    }
  });
  test("never stores invalid VRAM governor or train-step measurements", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-vram-"));
    const channel = join(scratch, "telemetry.jsonl");
    const events = [
      { ts: "2026-07-17T05:00:00.000Z", kind: "governor", source: "journal", payload: { free_gib: 25, total_gib: 24, run_id: "bad" } },
      { ts: "2026-07-17T05:00:01.000Z", kind: "governor", source: "journal", payload: { free_gib: -1, total_gib: 24, run_id: "bad" } },
      { ts: "2026-07-17T05:00:02.000Z", kind: "governor", source: "journal", payload: { total_gib: 24, run_id: "bad" } },
      { ts: "2026-07-17T05:00:03.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 1, loss: 2, free_gib: 30, total_gib: 24 } },
    ];
    await writeFile(channel, events.map((event) => JSON.stringify(event)).join("\n") + "\n", "utf8");
    const handle = startTelemetryWatch({ channelPath: channel, now: () => Date.parse("2026-07-17T05:00:04.000Z") });
    try {
      await Bun.sleep(650);
      expect(getState().lastGovernor).toBeUndefined();
      expect(getState().recentEvents).toHaveLength(4);
    } finally {
      handle.stop();
    }
  });
  test("marks a disappeared live channel OFFLINE and clears any running claim", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-offline-"));
    const channel = join(scratch, "telemetry.jsonl");
    await writeFile(channel, JSON.stringify({ ts: "2026-07-17T05:00:00.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 1, loss: 2 } }) + "\n", "utf8");
    const handle = startTelemetryWatch({ channelPath: channel, now: () => Date.parse("2026-07-17T05:00:01.000Z") });
    try {
      await Bun.sleep(650);
      expect(getState().channelStatus).toBe("ONLINE");
      await rm(channel, { force: true });
      await Bun.sleep(650);
      expect(getState().channelStatus).toBe("OFFLINE");
      expect(getState().activeRun).toBeUndefined();
    } finally {
      handle.stop();
    }
  });

  test("resets offset and evidence on channel rotation without mixing runs", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-rotate-"));
    const channel = join(scratch, "telemetry.jsonl");
    const oldEvent = { ts: "2026-07-17T05:00:00.000Z", kind: "train_step", source: "journal", payload: { run_id: "old-run", step: 1, loss: 2 } };
    const newEvent = { ts: "2026-07-17T05:00:02.000Z", kind: "train_step", source: "journal", payload: { run_id: "new-run", step: 7, loss: 1 } };
    await writeFile(channel, JSON.stringify(oldEvent) + "\n", "utf8");
    const handle = startTelemetryWatch({ channelPath: channel, now: () => Date.parse("2026-07-17T05:00:03.000Z") });
    try {
      await Bun.sleep(650);
      await rm(channel, { force: true });
      await writeFile(channel, JSON.stringify(newEvent) + "\n", "utf8");
      await Bun.sleep(650);
      expect(getState().channelStatus).toBe("ONLINE");
      expect(getState().recentEvents.map((event) => event.payload["run_id"])).toEqual(["new-run"]);
      expect(getState().activeRun?.runId).toBe("new-run");
    } finally {
      handle.stop();
    }
  });

  test("resets evidence when an equal-length channel is rewritten in place", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-rewrite-"));
    const channel = join(scratch, "telemetry.jsonl");
    const oldEvent = { ts: "2026-07-17T05:00:00.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 1, loss: 2 } };
    const newEvent = { ts: "2026-07-17T05:00:00.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-b", step: 1, loss: 1 } };
    const oldLine = JSON.stringify(oldEvent) + "\n";
    const newLine = JSON.stringify(newEvent) + "\n";
    expect(newLine.length).toBe(oldLine.length);
    await writeFile(channel, oldLine, "utf8");
    const handle = startTelemetryWatch({ channelPath: channel, now: () => Date.parse("2026-07-17T05:00:01.000Z") });
    try {
      await Bun.sleep(650);
      expect(getState().recentEvents.map((event) => event.payload["run_id"])).toEqual(["run-a"]);
      await writeFile(channel, newLine, "utf8");
      await Bun.sleep(650);
      expect(getState().channelStatus).toBe("ONLINE");
      expect(getState().recentEvents.map((event) => event.payload["run_id"])).toEqual(["run-b"]);
      expect(getState().activeRun?.runId).toBe("run-b");
    } finally {
      handle.stop();
    }
  });

  test("keeps an unchanged channel ONLINE while ordinary run evidence expires to stale", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-stale-"));
    const channel = join(scratch, "telemetry.jsonl");
    await writeFile(channel, JSON.stringify({ ts: "2026-07-17T05:00:00.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 1, loss: 2 } }) + "\n", "utf8");
    const handle = startTelemetryWatch({ channelPath: channel, now: () => Date.parse("2026-07-17T06:00:00.000Z") });
    try {
      await Bun.sleep(650);
      expect(getState().channelStatus).toBe("ONLINE");
      expect(getState().activeRun).toBeUndefined();
      expect(getState().recentEvents).toHaveLength(1);
    } finally {
      handle.stop();
    }
  });
  test("rejects missing or invalid timestamps instead of fabricating evidence time", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-missing-ts-"));
    const channel = join(scratch, "telemetry.jsonl");
    await writeFile(channel, JSON.stringify({ kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 1, loss: 2 } }) + "\n" + JSON.stringify({ ts: "not-a-time", kind: "train_step", source: "journal", payload: { run_id: "run-b", step: 2, loss: 1 } }) + "\n", "utf8");
    const handle = startTelemetryWatch({ channelPath: channel, now: () => Date.parse("2026-07-17T05:00:01.000Z") });
    try {
      await Bun.sleep(650);
      expect(getState().recentEvents).toHaveLength(0);
      expect(getState().activeRun).toBeUndefined();
    } finally {
      handle.stop();
    }
  });});
