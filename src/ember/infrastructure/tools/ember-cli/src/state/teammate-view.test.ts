// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for teammate-view — covers AC1–AC5.
import { test, expect, describe, mock } from "bun:test";
import {
  enterTeammateView,
  exitTeammateView,
  stopOrDismissAgent,
} from "./teammate-view.ts";
import { createStore } from "./state-store.ts";
import { getDefaultAppState } from "./app-state.ts";
import type { AppState } from "./app-state.ts";
import type { AgentId } from "../types/id-types.ts";

function makeStore(): ReturnType<typeof createStore<AppState>> {
  return createStore(
    getDefaultAppState({ sessionId: "test", cwd: "/", entrypoint: "cli", mode: "default" })
  );
}

const AGENT_A = "a0000000000000001" as AgentId;
const AGENT_B = "a0000000000000002" as AgentId;

describe("enterTeammateView", () => {
  test("AC1 (first half): sets viewedTeammateTask", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, {});
    expect(store.getState().viewedTeammateTask).not.toBeNull();
    expect(store.getState().viewedTeammateTask?.agentId).toBe(AGENT_A);
  });

  test("sets activeAgentForInput when routeInput: true", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, { routeInput: true });
    expect(store.getState().activeAgentForInput).toBe(AGENT_A);
  });

  test("does NOT set activeAgentForInput when routeInput omitted", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, {});
    expect(store.getState().activeAgentForInput).toBeNull();
  });

  test("returns a teardown function", () => {
    const store = makeStore();
    const teardown = enterTeammateView(store, AGENT_A, {});
    expect(typeof teardown).toBe("function");
  });

  test("teardown function calls exitTeammateView", () => {
    const store = makeStore();
    const teardown = enterTeammateView(store, AGENT_A, { routeInput: true });
    teardown();
    expect(store.getState().viewedTeammateTask).toBeNull();
    expect(store.getState().activeAgentForInput).toBeNull();
  });

  test("AC1: entering B while A is shown first exits A, then shows B", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, {});
    expect(store.getState().viewedTeammateTask?.agentId).toBe(AGENT_A);

    enterTeammateView(store, AGENT_B, {});
    expect(store.getState().viewedTeammateTask?.agentId).toBe(AGENT_B);
  });

  test("initial panel status is 'running'", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, {});
    expect(store.getState().viewedTeammateTask?.status).toBe("running");
  });

  test("panel startedAt is an ISO timestamp", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, {});
    const ts = store.getState().viewedTeammateTask?.startedAt;
    expect(ts).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});

describe("exitTeammateView", () => {
  test("clears viewedTeammateTask to null", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, {});
    exitTeammateView(store);
    expect(store.getState().viewedTeammateTask).toBeNull();
  });

  test("clears activeAgentForInput to null", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, { routeInput: true });
    exitTeammateView(store);
    expect(store.getState().activeAgentForInput).toBeNull();
  });

  test("calling exitTeammateView when no panel is open is a no-op", () => {
    const store = makeStore();
    expect(() => exitTeammateView(store)).not.toThrow();
    expect(store.getState().viewedTeammateTask).toBeNull();
  });
});

describe("stopOrDismissAgent", () => {
  test("AC4: calling stopOrDismissAgent twice on the same running agent — dismissed panel status set", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, {});
    stopOrDismissAgent(store, AGENT_A);
    expect(store.getState().viewedTeammateTask?.status).toBe("dismissed");
    // Second call should not throw and panel should remain dismissed
    stopOrDismissAgent(store, AGENT_A);
    expect(store.getState().viewedTeammateTask?.status).toBe("dismissed");
  });

  test("AC5: a panel in 'dismissed' status does not transition further", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, {});
    stopOrDismissAgent(store, AGENT_A);
    // Simulate agent completing after dismissed — panel must not change to 'complete'
    const panel = store.getState().viewedTeammateTask;
    expect(panel?.status).toBe("dismissed");
  });

  test("is idempotent", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, {});
    stopOrDismissAgent(store, AGENT_A);
    stopOrDismissAgent(store, AGENT_A);
    stopOrDismissAgent(store, AGENT_A);
    expect(store.getState().viewedTeammateTask?.status).toBe("dismissed");
  });
});

describe("TeammateTaskView shape", () => {
  test("has all required fields after enterTeammateView", () => {
    const store = makeStore();
    enterTeammateView(store, AGENT_A, {
      taskId: "task-1",
      agentName: "worker",
      agentColor: "#00ff00",
      teamName: "my-team",
    });
    const panel = store.getState().viewedTeammateTask;
    expect(panel?.agentId).toBe(AGENT_A);
    expect(panel?.taskId).toBe("task-1");
    expect(panel?.agentName).toBe("worker");
    expect(panel?.agentColor).toBe("#00ff00");
    expect(panel?.teamName).toBe("my-team");
    expect(panel?.messages).toEqual([]);
    expect(panel?.inputRouted).toBe(false);
  });
});
