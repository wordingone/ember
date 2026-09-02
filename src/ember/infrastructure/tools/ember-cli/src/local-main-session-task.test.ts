// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for local-main-session-task — covers spec ACs 1–5.
import { test, expect, describe, beforeEach, afterEach } from "bun:test";
import {
  createLocalMainSessionTask,
  syncMainSessionStatus,
  markMainSessionComplete,
  markMainSessionStopped,
  addActiveSubtask,
  removeActiveSubtask,
  hasMainSessionTask,
  unregisterMainSessionTask,
} from "./local-main-session-task.ts";
import type { LocalMainSessionTask } from "./local-main-session-task.ts";
import { asAgentId } from "../types/id-types.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const AGENT_ID = asAgentId("amain1234567890ab");

let sessionCounter = 0;
function uniqueSessionId(): string {
  return `test-session-${++sessionCounter}`;
}

function makeTask(sessionId?: string): LocalMainSessionTask {
  const sid = sessionId ?? uniqueSessionId();
  return createLocalMainSessionTask({
    sessionId: sid,
    agentId: AGENT_ID,
    cwd: "/projects/ember",
    model: "haiku",
  });
}

// Clean up any tasks created in tests
afterEach(() => {
  // Clear any lingering test sessions
  for (let i = 1; i <= sessionCounter; i++) {
    unregisterMainSessionTask(`test-session-${i}`);
  }
});

// ---------------------------------------------------------------------------
// AC1: LocalMainSessionTask.sessionId equals AppState.sessionId
// ---------------------------------------------------------------------------

describe("AC1 — sessionId matches AppState.sessionId", () => {
  test("AC1: sessionId stored matches the provided value", () => {
    const sid = uniqueSessionId();
    const task = makeTask(sid);
    expect(task.sessionId).toBe(sid);
  });

  test("AC1: different sessions have different sessionIds", () => {
    const sid1 = uniqueSessionId();
    const sid2 = uniqueSessionId();
    const t1 = makeTask(sid1);
    const t2 = makeTask(sid2);
    expect(t1.sessionId).not.toBe(t2.sessionId);
  });
});

// ---------------------------------------------------------------------------
// AC2: status 'running' when AppState.isLoading is true
// ---------------------------------------------------------------------------

describe("AC2 — status syncs with AppState.isLoading", () => {
  test("AC2: syncMainSessionStatus(true) → 'running'", () => {
    const task = makeTask();
    syncMainSessionStatus(task, true);
    expect(task.status).toBe("running");
  });

  test("AC2: syncMainSessionStatus(false) → 'pending'", () => {
    const task = makeTask();
    syncMainSessionStatus(task, true); // first set running
    syncMainSessionStatus(task, false); // then back to pending
    expect(task.status).toBe("pending");
  });

  test("AC2: initial status is 'pending' (idle, waiting for input)", () => {
    const task = makeTask();
    expect(task.status).toBe("pending");
  });

  test("AC2: syncMainSessionStatus is no-op on terminal task", () => {
    const task = makeTask();
    markMainSessionComplete(task);
    syncMainSessionStatus(task, true);
    expect(task.status).toBe("complete");
  });
});

// ---------------------------------------------------------------------------
// AC3: activeSubtaskIds contains IDs of all currently-running subtasks
// ---------------------------------------------------------------------------

describe("AC3 — activeSubtaskIds tracking", () => {
  test("AC3: activeSubtaskIds is empty initially", () => {
    const task = makeTask();
    expect(task.activeSubtaskIds).toHaveLength(0);
  });

  test("AC3: addActiveSubtask adds the ID", () => {
    const task = makeTask();
    addActiveSubtask(task, "a-subagent-id");
    expect(task.activeSubtaskIds).toContain("a-subagent-id");
  });

  test("AC3: addActiveSubtask does not add duplicates", () => {
    const task = makeTask();
    addActiveSubtask(task, "a-id");
    addActiveSubtask(task, "a-id");
    expect(task.activeSubtaskIds.filter((id) => id === "a-id")).toHaveLength(1);
  });

  test("AC3: removeActiveSubtask removes the ID", () => {
    const task = makeTask();
    addActiveSubtask(task, "b-subagent");
    removeActiveSubtask(task, "b-subagent");
    expect(task.activeSubtaskIds).not.toContain("b-subagent");
  });

  test("AC3: multiple subtasks tracked independently", () => {
    const task = makeTask();
    addActiveSubtask(task, "agent-1");
    addActiveSubtask(task, "shell-1");
    addActiveSubtask(task, "remote-1");
    expect(task.activeSubtaskIds).toHaveLength(3);

    removeActiveSubtask(task, "shell-1");
    expect(task.activeSubtaskIds).toHaveLength(2);
    expect(task.activeSubtaskIds).toContain("agent-1");
    expect(task.activeSubtaskIds).toContain("remote-1");
  });
});

// ---------------------------------------------------------------------------
// AC4: isConductor: true when the session has spawned any InProcessTeammateTask
// ---------------------------------------------------------------------------

describe("AC4 — isConductor when teammate task spawned", () => {
  test("AC4: isConductor starts as false", () => {
    const task = makeTask();
    expect(task.isConductor).toBe(false);
  });

  test("AC4: addActiveSubtask with isTeammateTask: true sets isConductor: true", () => {
    const task = makeTask();
    addActiveSubtask(task, "t-teammate-id", true);
    expect(task.isConductor).toBe(true);
  });

  test("AC4: addActiveSubtask without isTeammateTask does not set isConductor", () => {
    const task = makeTask();
    addActiveSubtask(task, "a-subagent-id", false);
    expect(task.isConductor).toBe(false);
  });

  test("AC4: isConductor stays true even after removing the teammate task", () => {
    const task = makeTask();
    addActiveSubtask(task, "t-teammate", true);
    removeActiveSubtask(task, "t-teammate");
    // Once conductor, stays coordinator for the session lifetime
    expect(task.isConductor).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC5: There is never more than one LocalMainSessionTask per session
// ---------------------------------------------------------------------------

describe("AC5 — singleton per session", () => {
  test("AC5: creating a second task for the same sessionId throws", () => {
    const sid = uniqueSessionId();
    makeTask(sid); // first — fine
    expect(() => makeTask(sid)).toThrow();
  });

  test("AC5: after unregister, a new task can be created for the same sessionId", () => {
    const sid = uniqueSessionId();
    makeTask(sid);
    unregisterMainSessionTask(sid);
    expect(() => makeTask(sid)).not.toThrow();
  });

  test("AC5: hasMainSessionTask is true after creation", () => {
    const sid = uniqueSessionId();
    makeTask(sid);
    expect(hasMainSessionTask(sid)).toBe(true);
  });

  test("AC5: hasMainSessionTask is false after markMainSessionComplete", () => {
    const sid = uniqueSessionId();
    const task = makeTask(sid);
    markMainSessionComplete(task);
    expect(hasMainSessionTask(sid)).toBe(false);
  });

  test("AC5: hasMainSessionTask is false after markMainSessionStopped", () => {
    const sid = uniqueSessionId();
    const task = makeTask(sid);
    markMainSessionStopped(task);
    expect(hasMainSessionTask(sid)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Construction (AC5 — base fields)
// ---------------------------------------------------------------------------

describe("createLocalMainSessionTask — base fields (AC5)", () => {
  test("AC5: id is set at construction", () => {
    const task = makeTask();
    expect(task.id).toBeDefined();
    expect(task.id.length).toBeGreaterThan(0);
  });

  test("AC5: type is 'local_main_session'", () => {
    const task = makeTask();
    expect(task.type).toBe("local_main_session");
  });

  test("AC5: status is 'pending' at construction", () => {
    const task = makeTask();
    expect(task.status).toBe("pending");
  });

  test("AC5: createdAt is a valid ISO timestamp", () => {
    const task = makeTask();
    expect(new Date(task.createdAt).getTime()).not.toBeNaN();
  });
});

// ---------------------------------------------------------------------------
// Terminal state transitions
// ---------------------------------------------------------------------------

describe("terminal state transitions", () => {
  test("markMainSessionComplete sets status to 'complete'", () => {
    const task = makeTask();
    markMainSessionComplete(task);
    expect(task.status).toBe("complete");
  });

  test("markMainSessionStopped sets status to 'stopped'", () => {
    const task = makeTask();
    markMainSessionStopped(task);
    expect(task.status).toBe("stopped");
  });

  test("completedAt is set on complete", () => {
    const task = makeTask();
    markMainSessionComplete(task);
    expect(task.completedAt).toBeDefined();
    expect(new Date(task.completedAt!).getTime()).not.toBeNaN();
  });

  test("markMainSessionComplete is no-op on already-terminal task", () => {
    const task = makeTask();
    markMainSessionStopped(task);
    markMainSessionComplete(task); // no-op
    expect(task.status).toBe("stopped");
  });
});
