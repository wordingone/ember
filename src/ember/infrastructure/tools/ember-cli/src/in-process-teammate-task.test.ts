// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for in-process-teammate-task — covers spec ACs 1–5.
import { test, expect, describe, mock } from "bun:test";
import {
  createInProcessTeammateTaskWithDelivery,
  markTeammateStarted,
  markTeammateTurnStart,
  markTeammateTurnEnd,
} from "./in-process-teammate-task.ts";
import type { TeammateMessage } from "./in-process-teammate-task.ts";
import { stopTask } from "./task-infrastructure.ts";
import { asAgentId } from "../types/id-types.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const AGENT_ID = asAgentId("a1234567890abcdef");

function makeTask(opts: { stopFn?: () => Promise<void> } = {}) {
  return createInProcessTeammateTaskWithDelivery({
    agentId: AGENT_ID,
    teamName: "ember",
    agentName: "alice",
    identity: "alice",
    cwd: "/projects/ember",
    sessionId: "sess-alice-001",
    ...opts,
  });
}

function fakeMsg(content: string, role: "assistant" | "user" = "assistant"): TeammateMessage {
  return {
    role,
    content,
    uuid: crypto.randomUUID(),
    timestamp: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// AC1: teammate started with identity 'alice' loads Alice's EMBER.md
// (Shape/behavioral check — actual loading is deferred TeammateRuntime dep)
// ---------------------------------------------------------------------------

describe("AC1 — identity field", () => {
  test("AC1: identity field is stored on the task", () => {
    const { task } = makeTask();
    expect(task.identity).toBe("alice");
  });

  test("AC1: agentName matches the provided name", () => {
    const { task } = makeTask();
    expect(task.agentName).toBe("alice");
  });

  test("AC1: teamName is stored", () => {
    const { task } = makeTask();
    expect(task.teamName).toBe("ember");
  });
});

// ---------------------------------------------------------------------------
// AC2: teammate's JSONL entries have their own sessionId distinct from coordinator's
// ---------------------------------------------------------------------------

describe("AC2 — own sessionId", () => {
  test("AC2: sessionId matches the provided session ID", () => {
    const { task } = makeTask();
    expect(task.sessionId).toBe("sess-alice-001");
  });

  test("AC2: different tasks get different sessionIds", () => {
    const { task: t1 } = createInProcessTeammateTaskWithDelivery({
      agentId: AGENT_ID,
      teamName: "t",
      agentName: "a",
      identity: "bob",
      cwd: "/",
      sessionId: "sess-bob-001",
    });
    const { task: t2 } = createInProcessTeammateTaskWithDelivery({
      agentId: AGENT_ID,
      teamName: "t",
      agentName: "b",
      identity: "alice",
      cwd: "/",
      sessionId: "sess-alice-002",
    });
    expect(t1.sessionId).not.toBe(t2.sessionId);
  });
});

// ---------------------------------------------------------------------------
// AC3: sendMessage enqueues; message appears in JSONL after next turn
// (We test the enqueue behavior; actual JSONL write is deferred dep)
// ---------------------------------------------------------------------------

describe("AC3 — sendMessage enqueues non-blocking", () => {
  test("AC3: sendMessage does not throw", async () => {
    const { task } = makeTask();
    await expect(task.sendMessage("hello")).resolves.toBeUndefined();
  });

  test("AC3: getMessages returns empty initially", () => {
    const { task } = makeTask();
    expect(task.getMessages()).toHaveLength(0);
  });

  test("AC3: delivered messages appear in getMessages", () => {
    const { task, delivery } = makeTask();
    delivery.deliver(fakeMsg("First response"));
    expect(task.getMessages()).toHaveLength(1);
    expect(task.getMessages()[0]?.content).toBe("First response");
  });

  test("AC3: multiple deliveries accumulate in order", () => {
    const { task, delivery } = makeTask();
    delivery.deliver(fakeMsg("msg 1"));
    delivery.deliver(fakeMsg("msg 2"));
    delivery.deliver(fakeMsg("msg 3"));
    const msgs = task.getMessages();
    expect(msgs).toHaveLength(3);
    expect(msgs[0]?.content).toBe("msg 1");
    expect(msgs[2]?.content).toBe("msg 3");
  });
});

// ---------------------------------------------------------------------------
// AC4: stop() allows current turn to complete before task reaches 'stopped'
// ---------------------------------------------------------------------------

describe("AC4 — stop() behavior", () => {
  test("AC4: stop() transitions task to 'stopped'", async () => {
    const { task } = makeTask();
    markTeammateStarted(task);
    await task.stop();
    expect(task.status).toBe("stopped");
  });

  test("AC4: stopTask dispatches to stop()", async () => {
    const { task } = makeTask();
    markTeammateStarted(task);
    await stopTask(task);
    expect(task.status).toBe("stopped");
  });

  test("AC4: stop() calls provided stopFn", async () => {
    const stopFn = mock(async () => {});
    const { task } = makeTask({ stopFn });
    markTeammateStarted(task);
    await task.stop();
    expect(stopFn).toHaveBeenCalledTimes(1);
  });

  test("AC4: stop() on already-stopped task is no-op", async () => {
    const stopFn = mock(async () => {});
    const { task } = makeTask({ stopFn });
    markTeammateStarted(task);
    await task.stop(); // first stop
    await task.stop(); // second stop — no-op
    expect(stopFn).toHaveBeenCalledTimes(1);
    expect(task.status).toBe("stopped");
  });

  test("AC4: completedAt set when stopped", async () => {
    const { task } = makeTask();
    markTeammateStarted(task);
    await task.stop();
    expect(task.completedAt).toBeDefined();
    expect(new Date(task.completedAt!).getTime()).not.toBeNaN();
  });

  test("AC4: isRunning is false after stop()", async () => {
    const { task } = makeTask();
    markTeammateStarted(task);
    markTeammateTurnStart(task);
    expect(task.isRunning).toBe(true);
    await task.stop();
    expect(task.isRunning).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC5: onMessage callbacks fire for every new message
// ---------------------------------------------------------------------------

describe("AC5 — onMessage subscription", () => {
  test("AC5: onMessage callback fires when a message is delivered", () => {
    const { task, delivery } = makeTask();
    const received: TeammateMessage[] = [];
    task.onMessage((msg) => received.push(msg));

    delivery.deliver(fakeMsg("hello from teammate"));
    expect(received).toHaveLength(1);
    expect(received[0]?.content).toBe("hello from teammate");
  });

  test("AC5: multiple subscribers each receive the message", () => {
    const { task, delivery } = makeTask();
    const a: TeammateMessage[] = [];
    const b: TeammateMessage[] = [];
    task.onMessage((msg) => a.push(msg));
    task.onMessage((msg) => b.push(msg));

    delivery.deliver(fakeMsg("broadcast"));
    expect(a).toHaveLength(1);
    expect(b).toHaveLength(1);
  });

  test("AC5: unsubscribe function stops future deliveries", () => {
    const { task, delivery } = makeTask();
    const received: TeammateMessage[] = [];
    const unsubscribe = task.onMessage((msg) => received.push(msg));

    delivery.deliver(fakeMsg("before unsubscribe"));
    unsubscribe();
    delivery.deliver(fakeMsg("after unsubscribe"));

    expect(received).toHaveLength(1);
    expect(received[0]?.content).toBe("before unsubscribe");
  });

  test("AC5: delivery fires all callbacks, errors in one don't break others", () => {
    const { task, delivery } = makeTask();
    const good: TeammateMessage[] = [];
    task.onMessage(() => { throw new Error("bad subscriber"); });
    task.onMessage((msg) => good.push(msg));

    // Should not throw despite bad subscriber
    expect(() => delivery.deliver(fakeMsg("resilient"))).not.toThrow();
    expect(good).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Construction (AC5 — base fields present at construction)
// ---------------------------------------------------------------------------

describe("createInProcessTeammateTaskWithDelivery — base fields (AC5)", () => {
  test("AC5: id is set at construction with 't' prefix", () => {
    const { task } = makeTask();
    expect(task.id).toBeDefined();
    expect(task.id[0]).toBe("t"); // 'in_process_teammate' prefix
  });

  test("AC5: type is 'in_process_teammate'", () => {
    const { task } = makeTask();
    expect(task.type).toBe("in_process_teammate");
  });

  test("AC5: status starts as 'pending'", () => {
    const { task } = makeTask();
    expect(task.status).toBe("pending");
  });

  test("AC5: createdAt is valid ISO timestamp", () => {
    const { task } = makeTask();
    expect(new Date(task.createdAt).getTime()).not.toBeNaN();
  });
});

// ---------------------------------------------------------------------------
// Lifecycle state transitions
// ---------------------------------------------------------------------------

describe("lifecycle transitions", () => {
  test("markTeammateStarted transitions to 'running'", () => {
    const { task } = makeTask();
    markTeammateStarted(task);
    expect(task.status).toBe("running");
  });

  test("markTeammateTurnStart sets isRunning: true", () => {
    const { task } = makeTask();
    markTeammateTurnStart(task);
    expect(task.isRunning).toBe(true);
  });

  test("markTeammateTurnEnd sets isRunning: false", () => {
    const { task } = makeTask();
    markTeammateTurnStart(task);
    markTeammateTurnEnd(task);
    expect(task.isRunning).toBe(false);
  });
});
