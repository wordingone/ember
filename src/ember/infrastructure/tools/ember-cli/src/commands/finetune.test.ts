// commands/finetune.test.ts — /finetune control command (AC8-AC9)
// Spec: specs/surface2-steerable-watch-control.md

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import { tmpdir } from "os";
import { join } from "path";
import { unlink, readFile } from "fs/promises";
import type { CommandContext } from "../types/command-types.ts";
import { createFinetuneCommand } from "./finetune.ts";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

const tempChannelPath = join(tmpdir(), `test-finetune-cmd-${Date.now()}.jsonl`);

async function cleanupTempFile(): Promise<void> {
  try {
    await unlink(tempChannelPath);
  } catch {
    // file doesn't exist; that's ok
  }
}

function createTestContext(): CommandContext {
  return {
    sessionId: "test-session",
    mode: "auto",
    cwd: "/test",
  };
}

// ---------------------------------------------------------------------------
// AC8: /finetune parses, validates, and emits control commands
// ---------------------------------------------------------------------------

describe("AC8: /finetune command — parse, validate, emit", () => {
  beforeEach(async () => {
    await cleanupTempFile();
  });

  afterEach(async () => {
    await cleanupTempFile();
  });

  it("command name is 'finetune'", () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    expect(cmd.name).toBe("finetune");
  });

  it("command has alias 'ft'", () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    expect(cmd.aliases).toContain("ft");
  });

  it("isEnabled returns true", () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    expect(cmd.isEnabled()).toBe(true);
  });

  it("/finetune start parses and emits 'start' command", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("start", createTestContext());
    expect(result).toBeDefined();
    expect((result as any).message).toContain("start");

    const content = await readFile(tempChannelPath, "utf-8");
    const lines = content.trim().split("\n");
    expect(lines.length).toBe(1);
    const parsed = JSON.parse(lines[0]!);
    expect(parsed.verb).toBe("start");
  });

  it("/finetune stop <runId> parses and emits 'stop' command", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("stop run-abc", createTestContext());
    expect(result).toBeDefined();
    expect((result as any).message).toContain("stop");
    expect((result as any).message).toContain("run-abc");

    const content = await readFile(tempChannelPath, "utf-8");
    const lines = content.trim().split("\n");
    const parsed = JSON.parse(lines[0]!);
    expect(parsed.verb).toBe("stop");
    expect(parsed.runId).toBe("run-abc");
  });

  it("/finetune pause <runId> emits 'pause' command", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("pause run-xyz", createTestContext());
    expect(result).toBeDefined();
    expect((result as any).message).toContain("pause");

    const content = await readFile(tempChannelPath, "utf-8");
    const parsed = JSON.parse(content.trim().split("\n")[0]!);
    expect(parsed.verb).toBe("pause");
    expect(parsed.runId).toBe("run-xyz");
  });

  it("/finetune resume <runId> emits 'resume' command", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("resume run-def", createTestContext());
    expect(result).toBeDefined();
    expect((result as any).message).toContain("resume");

    const content = await readFile(tempChannelPath, "utf-8");
    const parsed = JSON.parse(content.trim().split("\n")[0]!);
    expect(parsed.verb).toBe("resume");
  });

  it("/finetune adjust <runId> <lrScale> emits 'adjust' command", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("adjust run-123 2.5", createTestContext());
    expect(result).toBeDefined();
    expect((result as any).message).toContain("adjust");
    expect((result as any).message).toContain("run-123");
    expect((result as any).message).toContain("2.5");

    const content = await readFile(tempChannelPath, "utf-8");
    const parsed = JSON.parse(content.trim().split("\n")[0]!);
    expect(parsed.verb).toBe("adjust");
    expect(parsed.runId).toBe("run-123");
    expect(parsed.lrScale).toBe(2.5);
  });

  it("invalid args return validator's reason line, no write", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("stop", createTestContext()); // missing runId
    expect(result).toBeDefined();
    const msg = (result as any).message;
    expect(msg).toBeTruthy();
    // Should contain a clear error message
    expect(msg.toLowerCase()).toContain("error");

    let exists = false;
    try {
      await readFile(tempChannelPath);
      exists = true;
    } catch {
      // file doesn't exist; expected
    }
    expect(exists).toBe(false);
  });

  it("stop without runId returns clear error message", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("stop", createTestContext());
    const msg = (result as any).message;
    expect(msg).toContain("stop");
  });
});

// ---------------------------------------------------------------------------
// AC9: /finetune adjust parses lrScale as number with clear error handling
// ---------------------------------------------------------------------------

describe("AC9: /finetune adjust — lrScale number parsing", () => {
  beforeEach(async () => {
    await cleanupTempFile();
  });

  afterEach(async () => {
    await cleanupTempFile();
  });

  it("adjust with numeric lrScale parses correctly", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("adjust run-test 5", createTestContext());
    expect(result).toBeDefined();
    expect((result as any).message).toContain("adjust");

    const content = await readFile(tempChannelPath, "utf-8");
    const parsed = JSON.parse(content.trim().split("\n")[0]!);
    expect(parsed.lrScale).toBe(5);
  });

  it("adjust with float lrScale parses correctly", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("adjust run-test 3.7", createTestContext());
    expect((result as any).message).toContain("adjust");

    const content = await readFile(tempChannelPath, "utf-8");
    const parsed = JSON.parse(content.trim().split("\n")[0]!);
    expect(parsed.lrScale).toBe(3.7);
  });

  it("adjust with non-numeric lrScale returns clear error", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("adjust run-test notanumber", createTestContext());
    const msg = (result as any).message;
    expect(msg).toBeTruthy();
    expect(msg.toLowerCase()).toContain("error");

    let exists = false;
    try {
      await readFile(tempChannelPath);
      exists = true;
    } catch {
      // file doesn't exist; expected
    }
    expect(exists).toBe(false);
  });

  it("adjust with lrScale > 10 returns clear error", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("adjust run-test 11", createTestContext());
    const msg = (result as any).message;
    expect(msg).toBeTruthy();
    expect(msg.toLowerCase()).toContain("error");

    let exists = false;
    try {
      await readFile(tempChannelPath);
      exists = true;
    } catch {
      // file doesn't exist; expected
    }
    expect(exists).toBe(false);
  });

  it("adjust with lrScale=0 returns clear error", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("adjust run-test 0", createTestContext());
    const msg = (result as any).message;
    expect(msg).toBeTruthy();
    expect(msg.toLowerCase()).toContain("error");

    let exists = false;
    try {
      await readFile(tempChannelPath);
      exists = true;
    } catch {
      // file doesn't exist; expected
    }
    expect(exists).toBe(false);
  });

  it("adjust below lower bound (lrScale≤0) returns error", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("adjust run-test 0", createTestContext());
    const msg = (result as any).message;
    expect(msg.toLowerCase()).toContain("error");
  });

  it("adjust at upper bound (lrScale=10) succeeds", async () => {
    const cmd = createFinetuneCommand({ channelPath: tempChannelPath });
    const result = await cmd.execute("adjust run-test 10", createTestContext());
    expect((result as any).message).toContain("adjust");

    const content = await readFile(tempChannelPath, "utf-8");
    const parsed = JSON.parse(content.trim().split("\n")[0]!);
    expect(parsed.lrScale).toBe(10);
  });
});
