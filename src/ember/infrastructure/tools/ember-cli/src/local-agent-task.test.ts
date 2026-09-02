// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for local-agent-task — covers spec ACs 1–5.
import { test, expect, describe } from "bun:test";
import {
  createLocalAgentTask,
  normalizeAgentModel,
  markAgentStarted,
  markAgentComplete,
  markAgentError,
  accumulateAgentTokenUsage,
} from "./local-agent-task.ts";
import { stopTask } from "./task-infrastructure.ts";
import { asAgentId } from "../types/id-types.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const FAKE_AGENT_ID = asAgentId("a1234567890abcdef");
const FAKE_PARENT_ID = asAgentId("aparent1234567890");

function makeRunningAgent() {
  const task = createLocalAgentTask({
    agentId: FAKE_AGENT_ID,
    parentAgentId: FAKE_PARENT_ID,
    prompt: "Do some work",
  });
  markAgentStarted(task);
  return task;
}

// ---------------------------------------------------------------------------
// AC1: model normalization — LARGE_MODELS is empty in local-only mode (one model).
// Cloud-tier model names pass through unchanged; callers use DEFAULT_SUBAGENT_MODEL.
// ---------------------------------------------------------------------------

describe("AC1 — model normalization", () => {
  test("AC1: model 'opus' passes through by default (LARGE_MODELS empty in local mode)", () => {
    expect(normalizeAgentModel("opus", false)).toBe("opus");
  });

  test("AC1: model 'fable' passes through by default", () => {
    expect(normalizeAgentModel("fable", false)).toBe("fable");
  });

  test("AC1: model 'qwen-3.6' passes through by default", () => {
    expect(normalizeAgentModel("qwen-3.6", false)).toBe("qwen-3.6");
  });

  test("AC1: model 'local' is allowed without opt-in", () => {
    expect(normalizeAgentModel("local", false)).toBe("local");
  });

  test("AC1: model 'sonnet' is allowed without opt-in", () => {
    expect(normalizeAgentModel("sonnet", false)).toBe("sonnet");
  });

  test("AC1: model 'opus' is allowed WITH explicit opt-in", () => {
    expect(normalizeAgentModel("opus", true)).toBe("opus");
  });

  test("AC1: undefined model defaults to 'local'", () => {
    expect(normalizeAgentModel(undefined, false)).toBe("local");
  });

  test("AC1: createLocalAgentTask with model 'opus' stores 'opus' (LARGE_MODELS empty in local mode)", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
      model: "opus",
    });
    expect(task.model).toBe("opus");
  });

  test("AC1: createLocalAgentTask with opt-in stores 'opus'", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
      model: "opus",
      allowLargeModels: true,
    });
    expect(task.model).toBe("opus");
  });
});

// ---------------------------------------------------------------------------
// AC2: JSONL entries have isSidechain: true and matching agentId (shape check)
// ---------------------------------------------------------------------------

describe("AC2 — sidechain shape", () => {
  test("AC2: isSubagent is true on LocalAgentTask", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
    });
    expect(task.isSubagent).toBe(true);
  });

  test("AC2: isConductor is false on LocalAgentTask", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
    });
    expect(task.isConductor).toBe(false);
  });

  test("AC2: agentId matches the provided agent ID", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
    });
    expect(task.agentId).toBe(FAKE_AGENT_ID);
  });
});

// ---------------------------------------------------------------------------
// AC3: stopTask fires AbortSignal within one event loop tick
// ---------------------------------------------------------------------------

describe("AC3 — abort signal fires on stopTask", () => {
  test("AC3: signal is not aborted initially", () => {
    const task = makeRunningAgent();
    expect(task.signal.aborted).toBe(false);
  });

  test("AC3: stopTask aborts the signal synchronously (within one tick)", () => {
    const task = makeRunningAgent();
    stopTask(task);
    // The abort is synchronous — no await needed per spec "within one event loop tick"
    expect(task.signal.aborted).toBe(true);
  });

  test("AC3: task transitions to 'stopped' after stopTask", () => {
    const task = makeRunningAgent();
    stopTask(task);
    expect(task.status).toBe("stopped");
  });

  test("AC3: stopTask on completed agent is no-op (signal stays unaborted if already complete)", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
    });
    markAgentStarted(task);
    markAgentComplete(task, "done");
    // Now terminal — stopTask should be no-op
    stopTask(task);
    expect(task.status).toBe("complete");
  });
});

// ---------------------------------------------------------------------------
// AC4: Token usage accumulated in LocalAgentTask.tokenUsage, not host StatsContext
// ---------------------------------------------------------------------------

describe("AC4 — token usage accumulation", () => {
  test("AC4: tokenUsage starts undefined", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
    });
    expect(task.tokenUsage).toBeUndefined();
  });

  test("AC4: accumulateAgentTokenUsage initializes and adds token counts", () => {
    const task = makeRunningAgent();
    accumulateAgentTokenUsage(task, { input: 100, output: 50, cacheRead: 20 });
    expect(task.tokenUsage).toBeDefined();
    expect(task.tokenUsage!.input).toBe(100);
    expect(task.tokenUsage!.output).toBe(50);
    expect(task.tokenUsage!.cacheRead).toBe(20);
  });

  test("AC4: multiple accumulations sum correctly", () => {
    const task = makeRunningAgent();
    accumulateAgentTokenUsage(task, { input: 100, output: 50, cacheRead: 10 });
    accumulateAgentTokenUsage(task, { input: 200, output: 75, cacheRead: 5 });
    expect(task.tokenUsage!.input).toBe(300);
    expect(task.tokenUsage!.output).toBe(125);
    expect(task.tokenUsage!.cacheRead).toBe(15);
  });
});

// ---------------------------------------------------------------------------
// AC5: LocalAgentTask.result contains final text after 'complete'
// ---------------------------------------------------------------------------

describe("AC5 — result after complete", () => {
  test("AC5: result is undefined before completion", () => {
    const task = makeRunningAgent();
    expect(task.result).toBeUndefined();
  });

  test("AC5: markAgentComplete sets result", () => {
    const task = makeRunningAgent();
    markAgentComplete(task, "The final answer is 42.");
    expect(task.result).toBe("The final answer is 42.");
  });

  test("AC5: status is 'complete' after markAgentComplete", () => {
    const task = makeRunningAgent();
    markAgentComplete(task, "done");
    expect(task.status).toBe("complete");
  });

  test("AC5: durationMs is set when startTimeMs is provided", () => {
    const task = makeRunningAgent();
    const start = Date.now() - 1000;
    markAgentComplete(task, "done", start);
    expect(task.durationMs).toBeGreaterThan(0);
  });

  test("AC5: markAgentError sets errorOutput", () => {
    const task = makeRunningAgent();
    markAgentError(task, "Something went wrong");
    expect(task.errorOutput).toBe("Something went wrong");
    expect(task.status).toBe("error");
  });
});

// ---------------------------------------------------------------------------
// Construction (AC5 — base fields)
// ---------------------------------------------------------------------------

describe("createLocalAgentTask — base fields (AC5)", () => {
  test("AC5: id is set at construction with 'a' prefix", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
    });
    expect(task.id).toBeDefined();
    expect(task.id[0]).toBe("a"); // 'local_agent' prefix
  });

  test("AC5: type is 'local_agent'", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
    });
    expect(task.type).toBe("local_agent");
  });

  test("AC5: status is 'pending' at construction", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
    });
    expect(task.status).toBe("pending");
  });

  test("AC5: createdAt is a valid ISO timestamp", () => {
    const task = createLocalAgentTask({
      agentId: FAKE_AGENT_ID,
      parentAgentId: FAKE_PARENT_ID,
      prompt: "test",
    });
    expect(new Date(task.createdAt).getTime()).not.toBeNaN();
  });
});
