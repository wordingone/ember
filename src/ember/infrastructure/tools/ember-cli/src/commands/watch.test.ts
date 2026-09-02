// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/watch.test.ts — /watch command (AC1-AC4)
// Spec: specs/surface2-steerable-watch-control.md

import { describe, it, expect, beforeEach } from "bun:test";
import type { CommandContext } from "../types/command-types.ts";
import { createWatchCommand } from "./watch.ts";
import type { TelemetryState } from "../services/telemetry-watch.ts";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function createTestContext(): CommandContext {
  return {
    sessionId: "test-session",
    mode: "auto",
    cwd: "/test",
  };
}

// Mock TelemetryWatch deps
interface MockWatchDeps {
  startCalls: Array<{ deps?: any }>;
  stopCalls: number;
  currentState: TelemetryState;
  fileExists: (path: string) => boolean;
}

let mockDeps: MockWatchDeps = {
  startCalls: [],
  stopCalls: 0,
  currentState: { recentEvents: [] },
  fileExists: () => true,
};

function mockStartTelemetryWatch(deps?: any) {
  mockDeps.startCalls.push({ deps });
  return {
    stop: () => {
      mockDeps.stopCalls++;
    },
  };
}

function mockGetState() {
  return mockDeps.currentState;
}

function resetMocks(): void {
  mockDeps = {
    startCalls: [],
    stopCalls: 0,
    currentState: { recentEvents: [] },
    fileExists: () => true,
  };
}

// ---------------------------------------------------------------------------
// AC1: registered in command-registry as 'watch'
// ---------------------------------------------------------------------------

describe("AC1: /watch command registration", () => {
  it("command name is 'watch'", () => {
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => true,
    });
    expect(cmd.name).toBe("watch");
  });

  it("isEnabled returns true", () => {
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => true,
    });
    expect(cmd.isEnabled()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC2: /watch toggles the telemetry view on/off; idempotent
// ---------------------------------------------------------------------------

describe("AC2: /watch toggles on/off — idempotent", () => {
  beforeEach(() => {
    resetMocks();
  });

  it("first /watch turns watching on", async () => {
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => true,
    });
    const result = await cmd.execute("", createTestContext());
    expect(result).toBeDefined();
    const msg = (result as any).message;
    expect(msg).toContain("watching");
  });

  it("second /watch (double-on) stays on, idempotent", async () => {
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => true,
    });

    const result1 = await cmd.execute("", createTestContext());
    const msg1 = (result1 as any).message;
    expect(msg1).toContain("watching");

    const result2 = await cmd.execute("", createTestContext());
    const msg2 = (result2 as any).message;
    expect(msg2).toContain("watching");
    // Both should indicate watching is on
  });

  it("returns 'watching' status on successful activation", async () => {
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => true,
    });

    const result = await cmd.execute("", createTestContext());
    const msg = (result as any).message;
    expect(msg).toBeTruthy();
    expect(msg.length).toBeGreaterThan(0);
  });

  it("returns a one-line status message", async () => {
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => true,
    });
    const result = await cmd.execute("", createTestContext());
    const msg = (result as any).message;
    // One-line: no newlines
    expect(msg.split("\n").length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// AC3: /watch <path> overrides channel path; non-existent path returns clear error
// ---------------------------------------------------------------------------

describe("AC3: /watch <path> — custom channel path", () => {
  beforeEach(() => {
    resetMocks();
  });

  it("/watch /custom/path starts watching at custom path", async () => {
    const customPath = "/custom/telemetry.jsonl";
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: (path: string) => path === customPath,
    });

    const result = await cmd.execute(customPath, createTestContext());
    const msg = (result as any).message;
    expect(msg).toContain("watching");
    expect(msg).toContain(customPath);
  });

  it("non-existent path returns 'channel not found' error, never crashes", async () => {
    const badPath = "/nonexistent/path.jsonl";
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: (path: string) => path !== badPath,
    });

    const result = await cmd.execute(badPath, createTestContext());
    const msg = (result as any).message;
    expect(msg).toBeDefined();
    expect(msg.toLowerCase()).toContain("not found");
  });

  it("returns a one-line error message for missing path", async () => {
    const badPath = "/nonexistent/path.jsonl";
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => false,
    });

    const result = await cmd.execute(badPath, createTestContext());
    const msg = (result as any).message;
    // One-line
    expect(msg.split("\n").length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// AC4: uses EXISTING startTelemetryWatch/getState API, calls stop()
// ---------------------------------------------------------------------------

describe("AC4: /watch uses startTelemetryWatch/getState API", () => {
  beforeEach(() => {
    resetMocks();
  });

  it("calls startTelemetryWatch with channelPath override", async () => {
    const customPath = "/custom/telemetry.jsonl";
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => true,
    });

    await cmd.execute(customPath, createTestContext());

    expect(mockDeps.startCalls.length).toBeGreaterThanOrEqual(1);
    // The first call should have channelPath
    const firstCall = mockDeps.startCalls[0]!;
    expect(firstCall.deps).toBeDefined();
    expect((firstCall.deps as any)?.channelPath).toBe(customPath);
  });

  it("calling /watch with different path stops the previous handle", async () => {
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => true,
    });

    // First /watch with default path
    await cmd.execute("", createTestContext());
    expect(mockDeps.startCalls.length).toBe(1);

    // Second /watch with different path
    await cmd.execute("/custom/path", createTestContext());
    // The previous stop should have been called when starting the new watcher
    expect(mockDeps.stopCalls).toBeGreaterThanOrEqual(1);
  });

  it("startTelemetryWatch is called with the correct channel path", async () => {
    const customPath = "/test/channel.jsonl";
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => true,
    });

    await cmd.execute(customPath, createTestContext());
    expect(mockDeps.startCalls.length).toBeGreaterThanOrEqual(1);
    const firstCall = mockDeps.startCalls[0]!;
    expect((firstCall.deps as any)?.channelPath).toBe(customPath);
  });

  it("does not re-implement polling — uses the returned handle", async () => {
    const cmd = createWatchCommand({
      startTelemetryWatch: mockStartTelemetryWatch,
      getState: mockGetState,
      fileExists: () => true,
    });

    await cmd.execute("", createTestContext());

    // Verify startTelemetryWatch was called (polling delegated to it)
    expect(mockDeps.startCalls.length).toBeGreaterThanOrEqual(1);
  });
});
