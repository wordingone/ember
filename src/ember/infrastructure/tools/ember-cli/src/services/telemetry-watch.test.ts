// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { afterEach, describe, expect, test } from "bun:test";
import { appendFile, mkdtemp, open, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import {
  MAX_PARTIAL_LINE_BYTES,
  MAX_READ_BYTES_PER_POLL,
  getDiagnostics,
  getState,
  startTelemetryWatch,
} from "./telemetry-watch.ts";

let scratch: string | undefined;

afterEach(async () => {
  if (scratch) await rm(scratch, { recursive: true, force: true });
  scratch = undefined;
});

describe("training telemetry custody", () => {
  test("retains live VRAM, optimizer progress, verified checkpoint, and model-seat status", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-"));
    const channel = join(scratch, "telemetry.jsonl");
    const now = Date.parse("2026-07-17T05:00:04.000Z");
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
  test("rejects future events before recent or derived state mutation", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-future-"));
    const channel = join(scratch, "telemetry.jsonl");
    const events = [
      { ts: "2026-07-17T05:00:00.000Z", kind: "train_step", source: "journal", payload: { run_id: "current", step: 1, loss: 2, free_gib: 10, total_gib: 24 } },
      { ts: "2026-07-17T05:00:02.000Z", kind: "governor", source: "journal", payload: { run_id: "future", free_gib: 1, total_gib: 24 } },
      { ts: "2026-07-17T05:00:03.000Z", kind: "train_step", source: "journal", payload: { run_id: "future", step: 99, loss: 0.1 } },
      { ts: "2026-07-17T05:00:04.000Z", kind: "checkpoint", source: "journal", payload: { run_id: "future", step: 99, checkpoint_manifest_sha256: "f".repeat(64) } },
      { ts: "2026-07-17T05:00:05.000Z", kind: "run_status", source: "journal", payload: { run_id: "future", phase: "OFFLINE", model_chat: "OFFLINE" } },
    ];
    await writeFile(channel, events.map((event) => JSON.stringify(event)).join("\n") + "\n", "utf8");
    const handle = startTelemetryWatch({ channelPath: channel, now: () => Date.parse("2026-07-17T05:00:01.000Z") });
    try {
      await Bun.sleep(650);
      expect(getState().recentEvents.map((event) => event.payload["run_id"])).toEqual(["current"]);
      expect(getState().activeRun?.runId).toBe("current");
      expect(getState().lastGovernor).toMatchObject({ runId: "current", vramUsedGib: 14 });
      expect(getState().lastCheckpoint).toBeUndefined();
      expect(getState().runStatus).toBeUndefined();
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
  test("keeps a newer FAILED terminal status over an older appended line and accepts a later resume", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-terminal-order-"));
    const channel = join(scratch, "telemetry.jsonl");
    const events = [
      { ts: "2026-07-17T05:00:01.000Z", kind: "train_step", source: "journal", payload: { run_id: "run-a", step: 7, loss: 2 } },
      { ts: "2026-07-17T05:00:03.000Z", kind: "run_status", source: "journal", payload: { run_id: "run-a", phase: "FAILED", model_chat: "OFFLINE", last_completed_step: 7, failure_class: "TRAINER_ERROR" } },
      { ts: "2026-07-17T05:00:02.000Z", kind: "run_status", source: "journal", payload: { run_id: "run-a", phase: "TRAINING", model_chat: "OFFLINE" } },
    ];
    await writeFile(channel, events.map((event) => JSON.stringify(event)).join("\n") + "\n", "utf8");
    const handle = startTelemetryWatch({
      channelPath: channel,
      now: () => Date.parse("2026-07-17T05:00:04.000Z"),
      pollIntervalMs: 20,
    });
    try {
      await Bun.sleep(45);
      expect(getState().runStatus).toMatchObject({
        runId: "run-a",
        phase: "FAILED",
        lastCompletedStep: 7,
        failureClass: "TRAINER_ERROR",
      });
      expect(getState().activeRun).toBeUndefined();

      await appendFile(channel, JSON.stringify({
        ts: "2026-07-17T05:00:04.000Z",
        kind: "run_status",
        source: "journal",
        payload: { run_id: "run-a", phase: "TRAINING", model_chat: "OFFLINE" },
      }) + "\n" + JSON.stringify({
        ts: "2026-07-17T05:00:04.000Z",
        kind: "train_step",
        source: "journal",
        payload: { run_id: "run-a", step: 8, loss: 1.5 },
      }) + "\n", "utf8");
      await Bun.sleep(45);
      expect(getState().runStatus?.phase).toBe("TRAINING");
      expect(getState().activeRun).toMatchObject({ runId: "run-a", step: 8 });
    } finally {
      handle.stop();
    }
  });

  test("retains measured learning, token throughput, and energy without deriving throughput from step time", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-measured-"));
    const channel = join(scratch, "telemetry.jsonl");
    await writeFile(channel, JSON.stringify({
      ts: "2026-07-17T05:00:00.000Z", kind: "train_step", source: "journal",
      payload: { run_id: "run-measured", step: 1, loss: 2, step_ms: 1000,
        tokens_per_second: 321.5, learning_rate: 0.0002, gpu_uuid: "GPU-1",
        gpu_watts: 275.25, board_energy_joules_total: 550.5, energy_status: "MEASURED" },
    }) + "\n", "utf8");
    const handle = startTelemetryWatch({ channelPath: channel, now: () => Date.parse("2026-07-17T05:00:01.000Z") });
    try {
      await Bun.sleep(650);
      expect(getState().activeRun).toMatchObject({
        runId: "run-measured", tokensPerSecond: 321.5, learningRate: 0.0002,
        gpuUuid: "GPU-1", gpuWatts: 275.25, boardEnergyJoulesTotal: 550.5,
        energyStatus: "MEASURED",
      });
    } finally { handle.stop(); }
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
  });

  test("range-reads a growing channel within the per-poll byte ceiling", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-range-"));
    const channel = join(scratch, "telemetry.jsonl");
    const event = JSON.stringify({
      ts: "2026-07-17T05:00:00.000Z",
      kind: "train_step",
      source: "journal",
      payload: { run_id: "bounded", step: 1, loss: 2 },
    }) + "\n";
    const filler = " ".repeat(MAX_READ_BYTES_PER_POLL + 1024) + "\n";
    await writeFile(channel, event + filler, "utf8");

    const handle = startTelemetryWatch({
      channelPath: channel,
      now: () => Date.parse("2026-07-17T05:00:01.000Z"),
      pollIntervalMs: 20,
    });
    try {
      await Bun.sleep(70);
      const diagnostics = getDiagnostics();
      expect(diagnostics.maxSingleReadBytes).toBeLessThanOrEqual(MAX_READ_BYTES_PER_POLL);
      expect(diagnostics.maxPollReadBytes).toBeLessThanOrEqual(MAX_READ_BYTES_PER_POLL);
      expect(getState().activeRun?.runId).toBe("bounded");
    } finally {
      handle.stop();
    }
  });

  test("never overlaps slow telemetry polls", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-single-flight-"));
    const channel = join(scratch, "telemetry.jsonl");
    await writeFile(channel, JSON.stringify({
      ts: "2026-07-17T05:00:00.000Z",
      kind: "train_step",
      source: "journal",
      payload: { run_id: "single-flight", step: 1, loss: 2 },
    }) + "\n", "utf8");
    let concurrentReads = 0;
    let maxConcurrentReads = 0;

    const handle = startTelemetryWatch({
      channelPath: channel,
      now: () => Date.parse("2026-07-17T05:00:01.000Z"),
      pollIntervalMs: 5,
      readRange: async (path, offset, length) => {
        concurrentReads += 1;
        maxConcurrentReads = Math.max(maxConcurrentReads, concurrentReads);
        try {
          await Bun.sleep(30);
          const file = await open(path, "r");
          try {
            const buffer = Buffer.alloc(length);
            const { bytesRead } = await file.read(buffer, 0, length, offset);
            return buffer.subarray(0, bytesRead);
          } finally {
            await file.close();
          }
        } finally {
          concurrentReads -= 1;
        }
      },
    });
    try {
      await Bun.sleep(55);
      expect(maxConcurrentReads).toBe(1);
      expect(getDiagnostics().overlapPollsSkipped).toBeGreaterThan(0);
    } finally {
      handle.stop();
    }
  });

  test("drops an oversized partial line and resumes at the next newline", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-partial-"));
    const channel = join(scratch, "telemetry.jsonl");
    await writeFile(channel, "x".repeat(MAX_PARTIAL_LINE_BYTES + 1), "utf8");
    const handle = startTelemetryWatch({
      channelPath: channel,
      now: () => Date.parse("2026-07-17T05:00:01.000Z"),
      pollIntervalMs: 20,
    });
    try {
      await Bun.sleep(70);
      expect(getDiagnostics().partialLineBytes).toBe(0);
      expect(getDiagnostics().oversizedPartialLinesDropped).toBe(1);
      await appendFile(channel, "\n" + JSON.stringify({
        ts: "2026-07-17T05:00:00.000Z",
        kind: "train_step",
        source: "journal",
        payload: { run_id: "after-oversized", step: 2, loss: 1 },
      }) + "\n", "utf8");
      await Bun.sleep(55);
      expect(getState().activeRun?.runId).toBe("after-oversized");
      expect(getDiagnostics().partialLineBytes).toBe(0);
    } finally {
      handle.stop();
    }
  });
  test("appends to a short channel without replaying its existing prefix", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-append-"));
    const channel = join(scratch, "telemetry.jsonl");
    const first = {
      ts: "2026-07-17T05:00:00.000Z",
      kind: "train_step",
      source: "journal",
      payload: { run_id: "first", step: 1, loss: 2 },
    };
    const second = {
      ts: "2026-07-17T05:00:01.000Z",
      kind: "train_step",
      source: "journal",
      payload: { run_id: "second", step: 2, loss: 1 },
    };
    await writeFile(channel, JSON.stringify(first) + "\n", "utf8");
    const handle = startTelemetryWatch({
      channelPath: channel,
      now: () => Date.parse("2026-07-17T05:00:02.000Z"),
      pollIntervalMs: 20,
    });
    try {
      await Bun.sleep(35);
      await appendFile(channel, JSON.stringify(second) + "\n", "utf8");
      await Bun.sleep(35);
      expect(getState().recentEvents.map((event) => event.payload["run_id"])).toEqual([
        "first",
        "second",
      ]);
    } finally {
      handle.stop();
    }
  });

  test("a replaced watcher cannot publish an obsolete in-flight read", async () => {
    scratch = await mkdtemp(join(tmpdir(), "ember-telemetry-generation-"));
    const oldChannel = join(scratch, "old.jsonl");
    const newChannel = join(scratch, "new.jsonl");
    const line = (runId: string) => JSON.stringify({
      ts: "2026-07-17T05:00:00.000Z",
      kind: "train_step",
      source: "journal",
      payload: { run_id: runId, step: 1, loss: 2 },
    }) + "\n";
    await writeFile(oldChannel, line("obsolete"), "utf8");
    await writeFile(newChannel, line("current"), "utf8");

    const oldHandle = startTelemetryWatch({
      channelPath: oldChannel,
      now: () => Date.parse("2026-07-17T05:00:01.000Z"),
      pollIntervalMs: 5,
      readRange: async (path, offset, length) => {
        await Bun.sleep(40);
        const file = await open(path, "r");
        try {
          const buffer = Buffer.alloc(length);
          const { bytesRead } = await file.read(buffer, 0, length, offset);
          return buffer.subarray(0, bytesRead);
        } finally {
          await file.close();
        }
      },
    });
    await Bun.sleep(12);
    const newHandle = startTelemetryWatch({
      channelPath: newChannel,
      now: () => Date.parse("2026-07-17T05:00:01.000Z"),
      pollIntervalMs: 5,
    });
    try {
      await Bun.sleep(70);
      expect(getState().recentEvents.map((event) => event.payload["run_id"])).toEqual(["current"]);
      expect(getState().activeRun?.runId).toBe("current");
    } finally {
      oldHandle.stop();
      newHandle.stop();
    }
  });
});
