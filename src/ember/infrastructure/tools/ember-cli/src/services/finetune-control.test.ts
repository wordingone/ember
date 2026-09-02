// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/finetune-control.test.ts — control channel for finetune governance
// Spec: specs/surface2-steerable-watch-control.md (AC5-AC7)

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import { tmpdir } from "os";
import { join } from "path";
import { unlink, readFile } from "fs/promises";
import type { FinetuneControlCmd } from "./finetune-control.ts";
import {
  validateControlCmd,
  emitControlCmd,
  CONTROL_CHANNEL_PATH,
} from "./finetune-control.ts";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

const tempPath = join(tmpdir(), `test-finetune-control-${Date.now()}.jsonl`);

async function cleanupTempFile(): Promise<void> {
  try {
    await unlink(tempPath);
  } catch {
    // file doesn't exist; that's ok
  }
}

// ---------------------------------------------------------------------------
// AC5: validateControlCmd — validation rules
// ---------------------------------------------------------------------------

describe("AC5: validateControlCmd — pure validation", () => {
  it("accepts 'start' verb with no runId", () => {
    const cmd: FinetuneControlCmd = {
      verb: "start",
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(true);
  });

  it("rejects 'stop' without runId", () => {
    const cmd: FinetuneControlCmd = {
      verb: "stop",
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(false);
    expect(result.reason).toBeDefined();
  });

  it("rejects 'pause' without runId", () => {
    const cmd: FinetuneControlCmd = {
      verb: "pause",
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(false);
  });

  it("rejects 'resume' without runId", () => {
    const cmd: FinetuneControlCmd = {
      verb: "resume",
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(false);
  });

  it("accepts 'stop' with runId", () => {
    const cmd: FinetuneControlCmd = {
      verb: "stop",
      runId: "run-123",
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(true);
  });

  it("accepts 'pause' with runId", () => {
    const cmd: FinetuneControlCmd = {
      verb: "pause",
      runId: "run-123",
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(true);
  });

  it("accepts 'resume' with runId", () => {
    const cmd: FinetuneControlCmd = {
      verb: "resume",
      runId: "run-123",
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(true);
  });

  it("rejects 'adjust' without lrScale", () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-123",
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(false);
  });

  it("rejects 'adjust' with lrScale=0", () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-123",
      lrScale: 0,
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(false);
  });

  it("rejects 'adjust' with lrScale > 10", () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-123",
      lrScale: 10.1,
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(false);
  });

  it("accepts 'adjust' with lrScale=1 (at lower bound)", () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-123",
      lrScale: 1,
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(true);
  });

  it("accepts 'adjust' with lrScale=10 (at upper bound)", () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-123",
      lrScale: 10,
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(true);
  });

  it("accepts 'adjust' with lrScale=5.5 (in range)", () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-123",
      lrScale: 5.5,
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(true);
  });

  it("rejects 'adjust' without runId", () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      lrScale: 5,
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(false);
  });

  it("rejects unknown verb", () => {
    const cmd = {
      verb: "unknown",
      ts: "2026-06-29T00:00:00Z",
    } as any;
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(false);
  });

  it("returns reason string for all failures", () => {
    const cmd: FinetuneControlCmd = {
      verb: "stop",
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(false);
    expect(typeof result.reason).toBe("string");
    expect((result.reason ?? "").length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// AC6: emitControlCmd — append-only JSONL, reject invalid
// ---------------------------------------------------------------------------

describe("AC6: emitControlCmd — append-only write", () => {
  beforeEach(async () => {
    await cleanupTempFile();
  });

  afterEach(async () => {
    await cleanupTempFile();
  });

  it("appends a valid 'start' command as one JSONL line", async () => {
    const cmd: FinetuneControlCmd = {
      verb: "start",
      ts: "2026-06-29T00:00:00Z",
    };
    await emitControlCmd(cmd, tempPath);

    const content = await readFile(tempPath, "utf-8");
    const lines = content.trim().split("\n");
    expect(lines.length).toBe(1);

    const parsed = JSON.parse(lines[0]!);
    expect(parsed.verb).toBe("start");
    expect(parsed.ts).toBe("2026-06-29T00:00:00Z");
  });

  it("appends a valid 'adjust' command", async () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-456",
      lrScale: 2,
      ts: "2026-06-29T00:00:00Z",
    };
    await emitControlCmd(cmd, tempPath);

    const content = await readFile(tempPath, "utf-8");
    const lines = content.trim().split("\n");
    const parsed = JSON.parse(lines[0]!);
    expect(parsed.verb).toBe("adjust");
    expect(parsed.runId).toBe("run-456");
    expect(parsed.lrScale).toBe(2);
  });

  it("throws (never writes) for invalid command", async () => {
    const cmd: FinetuneControlCmd = {
      verb: "stop",
      ts: "2026-06-29T00:00:00Z",
      // missing runId
    };

    let threw = false;
    try {
      await emitControlCmd(cmd, tempPath);
    } catch {
      threw = true;
    }

    expect(threw).toBe(true);

    // Verify file was not created
    let exists = false;
    try {
      await readFile(tempPath);
      exists = true;
    } catch {
      // file doesn't exist; expected
    }
    expect(exists).toBe(false);
  });

  it("appends to existing channel (not truncates)", async () => {
    // Write first command
    const cmd1: FinetuneControlCmd = {
      verb: "start",
      ts: "2026-06-29T00:00:00Z",
    };
    await emitControlCmd(cmd1, tempPath);

    // Write second command
    const cmd2: FinetuneControlCmd = {
      verb: "pause",
      runId: "run-789",
      ts: "2026-06-29T00:01:00Z",
    };
    await emitControlCmd(cmd2, tempPath);

    const content = await readFile(tempPath, "utf-8");
    const lines = content.trim().split("\n");
    expect(lines.length).toBe(2);
    expect(JSON.parse(lines[0]!).verb).toBe("start");
    expect(JSON.parse(lines[1]!).verb).toBe("pause");
  });

  it("does not write on validation failure", async () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-123",
      lrScale: 11, // > 10
      ts: "2026-06-29T00:00:00Z",
    };

    let threw = false;
    try {
      await emitControlCmd(cmd, tempPath);
    } catch {
      threw = true;
    }

    expect(threw).toBe(true);

    let exists = false;
    try {
      await readFile(tempPath);
      exists = true;
    } catch {
      // file doesn't exist; expected
    }
    expect(exists).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC7: governed-by-default — lrScale cap at 10
// ---------------------------------------------------------------------------

describe("AC7: governed-by-default — CLI-side lrScale bounds", () => {
  it("CONTROL_CHANNEL_PATH is defined", () => {
    expect(CONTROL_CHANNEL_PATH).toBeDefined();
    expect(typeof CONTROL_CHANNEL_PATH).toBe("string");
    expect(CONTROL_CHANNEL_PATH.length).toBeGreaterThan(0);
  });

  it("validateControlCmd enforces lrScale ≤ 10 (governor cap)", () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-123",
      lrScale: 10,
      ts: "2026-06-29T00:00:00Z",
    };
    expect(validateControlCmd(cmd).ok).toBe(true);

    const cmd2: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-123",
      lrScale: 10.0001,
      ts: "2026-06-29T00:00:00Z",
    };
    expect(validateControlCmd(cmd2).ok).toBe(false);
  });

  it("rejects lrScale > 10 with clear reason", () => {
    const cmd: FinetuneControlCmd = {
      verb: "adjust",
      runId: "run-123",
      lrScale: 15,
      ts: "2026-06-29T00:00:00Z",
    };
    const result = validateControlCmd(cmd);
    expect(result.ok).toBe(false);
    expect(result.reason).toBeDefined();
  });
});
