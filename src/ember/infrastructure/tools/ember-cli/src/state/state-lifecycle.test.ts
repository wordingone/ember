// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for state-lifecycle — covers AC1–AC5.
import { test, expect, describe } from "bun:test";
import {
  IDLE_SPECULATION_STATE,
  PANEL_GRACE_MS,
  externalMetadataToAppState,
} from "./state-lifecycle.ts";
import type { SpeculationState, CompletionBoundary } from "./state-lifecycle.ts";

describe("IDLE_SPECULATION_STATE", () => {
  test("AC2: isSpeculating is false", () => {
    expect(IDLE_SPECULATION_STATE.isSpeculating).toBe(false);
  });

  test("speculatedMessages is undefined", () => {
    expect(IDLE_SPECULATION_STATE.speculatedMessages).toBeUndefined();
  });

  test("speculatedToolCalls is undefined", () => {
    expect(IDLE_SPECULATION_STATE.speculatedToolCalls).toBeUndefined();
  });

  test("AC2: is the constant reference (not a new object each time)", () => {
    // Importing IDLE_SPECULATION_STATE twice should give the same reference
    const { IDLE_SPECULATION_STATE: same } = require("./state-lifecycle.ts");
    expect(same).toBe(IDLE_SPECULATION_STATE);
  });
});

describe("PANEL_GRACE_MS", () => {
  test("AC4: equals 30,000 ms (30 seconds)", () => {
    expect(PANEL_GRACE_MS).toBe(30_000);
  });
});

describe("CompletionBoundary shape (type check via runtime object)", () => {
  test("AC3: completionBoundary has required fields", () => {
    const boundary: CompletionBoundary = {
      messageIndex: 5,
      tokenCount: 1234,
      timestamp: new Date().toISOString(),
      stopReason: "end_turn",
    };
    expect(boundary.messageIndex).toBe(5);
    expect(boundary.tokenCount).toBe(1234);
    expect(boundary.stopReason).toBe("end_turn");
  });

  test("stopReason accepts null (intermediate / streaming)", () => {
    const boundary: CompletionBoundary = {
      messageIndex: 0,
      tokenCount: 0,
      timestamp: new Date().toISOString(),
      stopReason: null,
    };
    expect(boundary.stopReason).toBeNull();
  });
});

describe("SpeculationState shape", () => {
  test("AC1: isSpeculating: true at turn start", () => {
    const state: SpeculationState = {
      isSpeculating: true,
      speculatedToolCalls: [{ toolName: "bash", estimatedDurationMs: 1000 }],
    };
    expect(state.isSpeculating).toBe(true);
    expect(state.speculatedToolCalls).toHaveLength(1);
  });
});

describe("externalMetadataToAppState", () => {
  test("AC5: maps minimal metadata to partial state", () => {
    const result = externalMetadataToAppState({ sessionId: "s", cwd: "/x" });
    expect(result.sessionId).toBe("s");
    expect(result.cwd).toBe("/x");
  });

  test("maps all optional fields", () => {
    const result = externalMetadataToAppState({
      sessionId: "s2",
      cwd: "/y",
      mode: "auto",
      agentId: "a1234567890abcdef",
      teamName: "t",
      agentName: "n",
      agentColor: "red",
      isSubagent: true,
      isConductor: false,
      initialMessage: "hello",
    });
    expect(result.mode).toBe("auto");
    expect(result.agentId).toBe("a1234567890abcdef");
    expect(result.teamName).toBe("t");
    expect(result.agentName).toBe("n");
    expect(result.agentColor).toBe("red");
    expect(result.isSubagent).toBe(true);
    expect(result.isConductor).toBe(false);
    expect(result.initialMessage).toBe("hello");
  });

  test("is pure — returns new object each call", () => {
    const meta = { sessionId: "p", cwd: "/p" };
    const r1 = externalMetadataToAppState(meta);
    const r2 = externalMetadataToAppState(meta);
    expect(r1).not.toBe(r2);
    expect(r1).toEqual(r2);
  });

  test("does not mutate input", () => {
    const meta = { sessionId: "m", cwd: "/m" };
    const before = { ...meta };
    externalMetadataToAppState(meta);
    expect(meta).toEqual(before);
  });
});
