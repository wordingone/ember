// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/operator-controls.test.ts — RED-first: OperatorSurfacePane's [START][PAUSE][RESUME]
// [RESTART] controls must drive the REAL control channel, not merely fire a handler.
//
// Two evidence layers, per the operator's bar:
//  (1) unit layer — a mocked emit proves the VERB/runId mapping and the validate-before-write
//      ordering (a rejected verb never reaches emit; for RESTART a rejected "stop" means "start"
//      never runs — no half-restart).
//  (2) real-effect layer — the REAL emitControlCmd against a temp file, read back byte-for-byte,
//      mirroring finetune-control.test.ts's own convention. This is the observable effect a
//      real training-side poller would see; it is the strongest evidence reachable without
//      running a training step (which the pre-training gate forbids).
import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import { tmpdir } from "os";
import { join } from "path";
import { unlink, readFile } from "fs/promises";
import type { FinetuneControlCmd } from "../services/finetune-control.ts";
import { driveOperatorControl } from "./operator-controls.ts";

describe("unit: verb mapping and validate-before-write ordering", () => {
  it("START emits exactly one 'start' command with no runId required", async () => {
    const emitted: Array<{ cmd: FinetuneControlCmd; path?: string }> = [];
    const result = await driveOperatorControl("START", undefined, {
      emit: async (cmd, path) => { emitted.push({ cmd, path }); },
      now: () => Date.parse("2026-07-26T00:00:00.000Z"),
    });
    expect(result.ok).toBe(true);
    expect(emitted.map((e) => e.cmd.verb)).toEqual(["start"]);
    expect(emitted[0]!.cmd.runId).toBeUndefined();
  });

  it("PAUSE emits exactly one 'pause' command scoped to the running run", async () => {
    const emitted: FinetuneControlCmd[] = [];
    const result = await driveOperatorControl("PAUSE", "run-7", {
      emit: async (cmd) => { emitted.push(cmd); },
      now: () => Date.parse("2026-07-26T00:00:00.000Z"),
    });
    expect(result.ok).toBe(true);
    expect(emitted).toEqual([{ verb: "pause", runId: "run-7", ts: "2026-07-26T00:00:00.000Z" }]);
  });

  it("RESUME emits exactly one 'resume' command scoped to the paused run", async () => {
    const emitted: FinetuneControlCmd[] = [];
    const result = await driveOperatorControl("RESUME", "run-7", {
      emit: async (cmd) => { emitted.push(cmd); },
      now: () => Date.parse("2026-07-26T00:00:00.000Z"),
    });
    expect(result.ok).toBe(true);
    expect(emitted).toEqual([{ verb: "resume", runId: "run-7", ts: "2026-07-26T00:00:00.000Z" }]);
  });

  it("RESTART emits 'stop' THEN 'start', sequentially, both scoped/timestamped correctly", async () => {
    const emitted: FinetuneControlCmd[] = [];
    const result = await driveOperatorControl("RESTART", "run-7", {
      emit: async (cmd) => { emitted.push(cmd); },
      now: () => Date.parse("2026-07-26T00:00:00.000Z"),
    });
    expect(result.ok).toBe(true);
    expect(emitted).toEqual([
      { verb: "stop", runId: "run-7", ts: "2026-07-26T00:00:00.000Z" },
      { verb: "start", ts: "2026-07-26T00:00:00.000Z" },
    ]);
  });

  it("PAUSE with no runId is rejected BEFORE any write (fail-closed, not a silent no-op)", async () => {
    const emitted: FinetuneControlCmd[] = [];
    const result = await driveOperatorControl("PAUSE", undefined, {
      emit: async (cmd) => { emitted.push(cmd); },
      now: () => Date.parse("2026-07-26T00:00:00.000Z"),
    });
    expect(result.ok).toBe(false);
    expect(emitted).toEqual([]);
    expect(result.error).toContain("PAUSE");
  });

  it("RESTART with no runId rejects the 'stop' leg and never attempts 'start' (no half-restart)", async () => {
    const emitted: FinetuneControlCmd[] = [];
    const result = await driveOperatorControl("RESTART", undefined, {
      emit: async (cmd) => { emitted.push(cmd); },
      now: () => Date.parse("2026-07-26T00:00:00.000Z"),
    });
    expect(result.ok).toBe(false);
    expect(emitted).toEqual([]);
  });
});

describe("real-effect: driveOperatorControl writes the actual control-channel bytes", () => {
  const tempPath = join(tmpdir(), `test-operator-controls-${Date.now()}-${Math.random()}.jsonl`);

  afterEach(async () => {
    try { await unlink(tempPath); } catch { /* file may not exist */ }
  });

  it("PAUSE appends one real, validated JSONL line a training-side poller could read", async () => {
    const result = await driveOperatorControl("PAUSE", "run-real", {
      channelPath: tempPath,
      now: () => Date.parse("2026-07-26T00:00:00.000Z"),
    });
    expect(result.ok).toBe(true);
    const raw = await readFile(tempPath, "utf-8");
    const lines = raw.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
    expect(lines).toEqual([{ verb: "pause", runId: "run-real", ts: "2026-07-26T00:00:00.000Z" }]);
  });

  it("RESTART appends two real lines, stop then start, in file order", async () => {
    const result = await driveOperatorControl("RESTART", "run-real", {
      channelPath: tempPath,
      now: () => Date.parse("2026-07-26T00:00:00.000Z"),
    });
    expect(result.ok).toBe(true);
    const raw = await readFile(tempPath, "utf-8");
    const lines = raw.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
    expect(lines.map((line) => line.verb)).toEqual(["stop", "start"]);
  });
});
