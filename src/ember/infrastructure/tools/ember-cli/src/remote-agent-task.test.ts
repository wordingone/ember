// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for remote-agent-task — covers spec ACs 1–5.
import { test, expect, describe, mock } from "bun:test";
import {
  createRemoteAgentTask,
  mapRemoteStatus,
  applyRemotePollResult,
  markRemoteAgentStarted,
  REMOTE_AGENT_DEFAULT_POLL_INTERVAL_MS,
  REMOTE_AGENT_DEFAULT_MAX_POLL_ATTEMPTS,
} from "./remote-agent-task.ts";
import type { RemoteAgentTask } from "./remote-agent-task.ts";
import { stopTask } from "./task-infrastructure.ts";
import type { KillableTask } from "./task-infrastructure.ts";
import { asAgentId } from "../types/id-types.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const AGENT_ID = asAgentId("a1234567890abcdef");
const REMOTE_SID = "remote-session-abc123";

function makeTask(opts: {
  maxPollAttempts?: number;
  cancelFn?: (sid: string) => Promise<void>;
} = {}): RemoteAgentTask & KillableTask {
  return createRemoteAgentTask({
    agentId: AGENT_ID,
    remoteSessionId: REMOTE_SID,
    prompt: "Do some research",
    model: "haiku",
    ...opts,
  });
}

// ---------------------------------------------------------------------------
// mapRemoteStatus — status mapping table
// ---------------------------------------------------------------------------

describe("mapRemoteStatus — remote API status → local TaskState", () => {
  test("'pending' remote → 'running' local", () => {
    expect(mapRemoteStatus("pending")).toBe("running");
  });

  test("'running' remote → 'running' local", () => {
    expect(mapRemoteStatus("running")).toBe("running");
  });

  test("'completed' remote → 'complete' local", () => {
    expect(mapRemoteStatus("completed")).toBe("complete");
  });

  test("'failed' remote → 'error' local", () => {
    expect(mapRemoteStatus("failed")).toBe("error");
  });

  test("'cancelled' remote → 'stopped' local", () => {
    expect(mapRemoteStatus("cancelled")).toBe("stopped");
  });
});

// ---------------------------------------------------------------------------
// AC1: remote agent with remoteStatus 'completed' → 'complete' + result populated
// ---------------------------------------------------------------------------

describe("AC1 — remoteStatus 'completed' → 'complete' with result", () => {
  test("AC1: applyRemotePollResult with status 'completed' sets task to 'complete'", () => {
    const task = makeTask();
    markRemoteAgentStarted(task);
    applyRemotePollResult(task, {
      status: "completed",
      result: "The answer is 42",
    });
    expect(task.status).toBe("complete");
  });

  test("AC1: result is populated on 'completed'", () => {
    const task = makeTask();
    markRemoteAgentStarted(task);
    applyRemotePollResult(task, {
      status: "completed",
      result: "Final response text",
    });
    expect(task.result).toBe("Final response text");
  });

  test("AC1: completedAt is set on 'completed'", () => {
    const task = makeTask();
    markRemoteAgentStarted(task);
    applyRemotePollResult(task, { status: "completed" });
    expect(task.completedAt).toBeDefined();
    expect(new Date(task.completedAt!).getTime()).not.toBeNaN();
  });

  test("AC1: 'failed' remote → 'error' with errorOutput", () => {
    const task = makeTask();
    markRemoteAgentStarted(task);
    applyRemotePollResult(task, {
      status: "failed",
      errorOutput: "OOM on remote backend",
    });
    expect(task.status).toBe("error");
    expect(task.errorOutput).toBe("OOM on remote backend");
  });
});

// ---------------------------------------------------------------------------
// AC2: exceeding maxPollAttempts transitions to 'error'
// ---------------------------------------------------------------------------

describe("AC2 — maxPollAttempts exceeded → 'error'", () => {
  test("AC2: exactly maxPollAttempts 'running' polls → 'error'", () => {
    const task = makeTask({ maxPollAttempts: 3 });
    markRemoteAgentStarted(task);

    applyRemotePollResult(task, { status: "running" }); // attempt 1
    expect(task.status).toBe("running");

    applyRemotePollResult(task, { status: "running" }); // attempt 2
    expect(task.status).toBe("running");

    applyRemotePollResult(task, { status: "running" }); // attempt 3 = maxPollAttempts
    expect(task.status).toBe("error");
  });

  test("AC2: error message mentions poll attempts on timeout", () => {
    const task = makeTask({ maxPollAttempts: 2 });
    markRemoteAgentStarted(task);
    applyRemotePollResult(task, { status: "running" });
    applyRemotePollResult(task, { status: "running" });
    expect(task.error).toContain("2");
  });

  test("AC2: pollCount increments on each poll", () => {
    const task = makeTask({ maxPollAttempts: 10 });
    markRemoteAgentStarted(task);
    applyRemotePollResult(task, { status: "running" });
    applyRemotePollResult(task, { status: "running" });
    expect(task.pollCount).toBe(2);
  });

  test("AC2: poll after terminal state is no-op (pollCount unchanged)", () => {
    const task = makeTask({ maxPollAttempts: 1 });
    markRemoteAgentStarted(task);
    applyRemotePollResult(task, { status: "running" }); // maxed out → error
    const countAfterError = task.pollCount;
    applyRemotePollResult(task, { status: "running" }); // should be no-op
    expect(task.pollCount).toBe(countAfterError);
  });
});

// ---------------------------------------------------------------------------
// AC3: stopTask sends cancellation and immediately transitions to 'stopped'
// ---------------------------------------------------------------------------

describe("AC3 — stopTask cancels immediately without waiting", () => {
  test("AC3: stopTask transitions to 'stopped' synchronously", async () => {
    const task = makeTask();
    markRemoteAgentStarted(task);
    await stopTask(task);
    expect(task.status).toBe("stopped");
  });

  test("AC3: stopTask fires cancelFn (best-effort)", async () => {
    const cancelFn = mock(async (_sid: string) => {});
    const task = makeTask({ cancelFn });
    markRemoteAgentStarted(task);
    await stopTask(task);
    // Give the best-effort fire a tick to run
    await new Promise((r) => setTimeout(r, 10));
    expect(cancelFn).toHaveBeenCalledWith(REMOTE_SID);
  });

  test("AC3: completedAt is set immediately on stopTask", async () => {
    const task = makeTask();
    markRemoteAgentStarted(task);
    await stopTask(task);
    expect(task.completedAt).toBeDefined();
    expect(new Date(task.completedAt!).getTime()).not.toBeNaN();
  });

  test("AC3: stopTask on already-stopped task is no-op", async () => {
    const cancelFn = mock(async (_sid: string) => {});
    const task = makeTask({ cancelFn });
    markRemoteAgentStarted(task);
    await stopTask(task); // first
    await stopTask(task); // second — no-op
    await new Promise((r) => setTimeout(r, 10));
    expect(cancelFn).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// AC4: pollIntervalMs: 5000 means at most one poll per 5 seconds
// (Behavioral constraint — verified via defaults; actual interval enforcement
// is in the polling loop, a deferred dep)
// ---------------------------------------------------------------------------

describe("AC4 — pollIntervalMs defaults", () => {
  test("AC4: default pollIntervalMs is 5000", () => {
    const task = makeTask();
    expect(task.pollIntervalMs).toBe(REMOTE_AGENT_DEFAULT_POLL_INTERVAL_MS);
    expect(task.pollIntervalMs).toBe(5000);
  });

  test("AC4: custom pollIntervalMs is stored", () => {
    const task = createRemoteAgentTask({
      agentId: AGENT_ID,
      remoteSessionId: REMOTE_SID,
      prompt: "test",
      model: "haiku",
      pollIntervalMs: 10_000,
    });
    expect(task.pollIntervalMs).toBe(10_000);
  });

  test("AC4: default maxPollAttempts is 720", () => {
    const task = makeTask();
    expect(task.maxPollAttempts).toBe(REMOTE_AGENT_DEFAULT_MAX_POLL_ATTEMPTS);
    expect(task.maxPollAttempts).toBe(720);
  });
});

// ---------------------------------------------------------------------------
// AC5: Token usage from remote agent in session telemetry
// (Shape check — actual telemetry emit is deferred dep)
// ---------------------------------------------------------------------------

describe("AC5 — remote agent in session telemetry (shape only)", () => {
  test("AC5: remoteStatus is tracked on the task for telemetry consumers", () => {
    const task = makeTask();
    markRemoteAgentStarted(task);
    applyRemotePollResult(task, { status: "running" });
    expect(task.remoteStatus).toBe("running");
  });

  test("AC5: agentId is set for analytics routing", () => {
    const task = makeTask();
    expect(task.agentId).toBe(AGENT_ID);
  });
});

// ---------------------------------------------------------------------------
// Construction (AC5 — base fields)
// ---------------------------------------------------------------------------

describe("createRemoteAgentTask — base fields (AC5)", () => {
  test("AC5: id starts with 'r' prefix (remote_agent type)", () => {
    const task = makeTask();
    expect(task.id[0]).toBe("r");
  });

  test("AC5: type is 'remote_agent'", () => {
    const task = makeTask();
    expect(task.type).toBe("remote_agent");
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
// remoteStatus tracking
// ---------------------------------------------------------------------------

describe("remoteStatus field", () => {
  test("remoteStatus is undefined before first poll", () => {
    const task = makeTask();
    expect(task.remoteStatus).toBeUndefined();
  });

  test("remoteStatus is updated on each poll", () => {
    const task = makeTask({ maxPollAttempts: 10 });
    markRemoteAgentStarted(task);
    applyRemotePollResult(task, { status: "pending" });
    expect(task.remoteStatus).toBe("pending");
    applyRemotePollResult(task, { status: "running" });
    expect(task.remoteStatus).toBe("running");
  });
});
