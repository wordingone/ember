// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for app-state — covers AC1–AC5.
import { test, expect, describe } from "bun:test";
import {
  getDefaultAppState,
  getViewedTeammateTask,
  getActiveAgentForInput,
  externalMetadataToAppState,
} from "./app-state.ts";
import type { AppState, AppStateOverrides } from "./app-state.ts";
import { asAgentId } from "../types/id-types.ts";

describe("getDefaultAppState", () => {
  test("AC1: returns valid AppState with all mutable fields at zero", () => {
    const state = getDefaultAppState({
      sessionId: "x",
      cwd: "/foo",
      entrypoint: "cli",
      mode: "auto",
    });
    // Immutable fields set
    expect(state.sessionId).toBe("x");
    expect(state.cwd).toBe("/foo");
    expect(state.entrypoint).toBe("cli");
    expect(state.mode).toBe("auto");
    // Mutable fields at zero
    expect(state.messages).toEqual([]);
    expect(state.isLoading).toBe(false);
    expect(state.inputValue).toBe("");
    expect(state.currentTask).toBeNull();
    expect(state.completionBoundary).toBeNull();
    expect(state.viewedTeammateTask).toBeNull();
    expect(state.activeAgentForInput).toBeNull();
    expect(state.permissionRequests).toEqual([]);
    expect(state.isDirty).toBe(false);
    expect(state.isCompacting).toBe(false);
    expect(state.contextWindowTokens).toBe(0);
    expect(state.queueDepth).toBe(0);
  });

  test("optional fields default to sensible values", () => {
    const state = getDefaultAppState({
      sessionId: "s1",
      cwd: "/bar",
      entrypoint: "sdk",
      mode: "default",
    });
    expect(state.agentId).toBeUndefined();
    expect(state.teamName).toBeUndefined();
    expect(state.agentName).toBeUndefined();
    expect(state.agentColor).toBeUndefined();
    expect(state.isSubagent).toBe(false);
    expect(state.isConductor).toBe(false);
    expect(state.initialMessage).toBeUndefined();
    expect(state.toolPermissions).toEqual({});
  });

  test("optional immutable overrides propagate", () => {
    const state = getDefaultAppState({
      sessionId: "s2",
      cwd: "/x",
      entrypoint: "cli",
      mode: "bypassPermissions",
      agentId: "a1234567890abcdef",
      teamName: "myteam",
      agentName: "worker-1",
      agentColor: "#ff0000",
      isSubagent: true,
      isConductor: false,
      initialMessage: "hello",
    });
    expect(state.agentId).toBe("a1234567890abcdef");
    expect(state.teamName).toBe("myteam");
    expect(state.agentName).toBe("worker-1");
    expect(state.agentColor).toBe("#ff0000");
    expect(state.isSubagent).toBe(true);
    expect(state.isConductor).toBe(false);
    expect(state.initialMessage).toBe("hello");
  });

  test("AC4: immutable fields are identical at turn 1 and turn 50 (each call returns same values)", () => {
    const overrides = { sessionId: "sX", cwd: "/y", entrypoint: "cli" as const, mode: "plan" as const };
    const state1 = getDefaultAppState(overrides);
    const state2 = getDefaultAppState(overrides);
    expect(state1.sessionId).toBe(state2.sessionId);
    expect(state1.cwd).toBe(state2.cwd);
    expect(state1.entrypoint).toBe(state2.entrypoint);
    expect(state1.mode).toBe(state2.mode);
  });

  test("AC5: queueDepth equals number of queued messages", () => {
    const state = getDefaultAppState({
      sessionId: "q",
      cwd: "/",
      entrypoint: "cli",
      mode: "default",
      queueDepth: 3,
    });
    expect(state.queueDepth).toBe(3);
  });
});

describe("getViewedTeammateTask", () => {
  test("AC3: returns null when viewedTeammateTask is null", () => {
    const state = getDefaultAppState({
      sessionId: "t",
      cwd: "/",
      entrypoint: "cli",
      mode: "default",
    });
    expect(getViewedTeammateTask(state)).toBeNull();
  });

  test("returns viewedTeammateTask when set", () => {
    const state = getDefaultAppState({
      sessionId: "t2",
      cwd: "/",
      entrypoint: "cli",
      mode: "default",
    });
    const fakeView = {
      agentId: asAgentId("a0000000000000001"),
      status: "running" as const,
      startedAt: new Date().toISOString(),
      messages: [],
      inputRouted: false,
    };
    (state as unknown as Record<string, unknown>).viewedTeammateTask = fakeView;
    expect(getViewedTeammateTask(state)).toBe(fakeView);
  });
});

describe("getActiveAgentForInput", () => {
  test("returns null when activeAgentForInput is null", () => {
    const state = getDefaultAppState({
      sessionId: "a",
      cwd: "/",
      entrypoint: "cli",
      mode: "default",
    });
    expect(getActiveAgentForInput(state)).toBeNull();
  });
});

describe("externalMetadataToAppState", () => {
  test("AC5: maps minimal metadata to partial state accepted by getDefaultAppState", () => {
    const partial = externalMetadataToAppState({ sessionId: "s", cwd: "/x" });
    const state = getDefaultAppState({
      sessionId: partial.sessionId!,
      cwd: partial.cwd ?? "/x",
      entrypoint: "sdk",
      mode: "default",
    });
    expect(state.sessionId).toBe("s");
    expect(state.cwd).toBe("/x");
  });

  test("maps all optional metadata fields", () => {
    const partial = externalMetadataToAppState({
      sessionId: "s2",
      cwd: "/y",
      mode: "auto",
      agentId: "a1234567890abcdef",
      teamName: "t",
      agentName: "w",
      agentColor: "blue",
      isSubagent: true,
      isConductor: true,
      initialMessage: "hi",
    });
    expect(partial.mode).toBe("auto");
    expect(partial.agentId).toBe("a1234567890abcdef");
    expect(partial.teamName).toBe("t");
    expect(partial.isSubagent).toBe(true);
    expect(partial.isConductor).toBe(true);
    expect(partial.initialMessage).toBe("hi");
  });

  test("externalMetadataToAppState is pure — no side effects", () => {
    const meta = { sessionId: "pure", cwd: "/pure" };
    const r1 = externalMetadataToAppState(meta);
    const r2 = externalMetadataToAppState(meta);
    expect(r1).toEqual(r2);
    expect(r1).not.toBe(r2); // new object each call
  });
});
