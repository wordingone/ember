// commands/goal.test.ts — bounded goal loop: event->phase derivation, real setLoopPhase
// transitions, module-level status snapshot, and the /goal command's honest-failure paths.

import { describe, it, expect, beforeEach } from "bun:test";
import {
  GOAL_MAX_ITERATIONS,
  deriveLoopPhaseForEvent,
  runGoalLoop,
  getGoalStatus,
  resetGoalStatusForTests,
  createGoalCommand,
  setGoalEngineProvider,
  resetGoalEngineProviderForTests,
  type GoalEngineLike,
} from "./goal.ts";
import type { QueryEvent } from "../core/query-engine.ts";
import { getCognitiveMode, getModeHistory, resetLoopPhaseForTests } from "../state/app-state.ts";

function assistantTextEvent(): QueryEvent {
  return {
    type: "assistant",
    message: { role: "assistant", content: [{ type: "text", text: "thinking" }], stop_reason: null },
  };
}

function assistantToolUseEvent(): QueryEvent {
  return {
    type: "assistant",
    message: {
      role: "assistant",
      content: [{ type: "tool_use", id: "t1", name: "Bash", input: {} }],
      stop_reason: "tool_use",
    },
  };
}

function userToolResultEvent(): QueryEvent {
  return {
    type: "user",
    message: { role: "user", content: [], uuid: "u1", timestamp: new Date().toISOString() },
  };
}

function resultSuccessEvent(): QueryEvent {
  return {
    type: "result",
    subtype: "success",
    durationMs: 1,
    finalMessage: { role: "assistant", content: [], stop_reason: "end_turn" },
  };
}

function resultErrorEvent(): QueryEvent {
  return { type: "result", subtype: "error", durationMs: 1, errorMessage: "boom" };
}

describe("deriveLoopPhaseForEvent", () => {
  it("maps a text-only assistant event to 'streaming_text'", () => {
    expect(deriveLoopPhaseForEvent(assistantTextEvent())).toBe("streaming_text");
  });

  it("maps an assistant event carrying a tool_use block to 'tool_call'", () => {
    expect(deriveLoopPhaseForEvent(assistantToolUseEvent())).toBe("tool_call");
  });

  it("maps a user (tool-result) event to 'tool_result'", () => {
    expect(deriveLoopPhaseForEvent(userToolResultEvent())).toBe("tool_result");
  });

  it("maps a terminal result event to null (not a phase in its own right)", () => {
    expect(deriveLoopPhaseForEvent(resultSuccessEvent())).toBeNull();
  });
});

function makeFakeEngine(eventsPerCall: QueryEvent[]): { engine: GoalEngineLike; calls: string[] } {
  const calls: string[] = [];
  const engine: GoalEngineLike = {
    async *submitMessage(userMessage: string) {
      calls.push(userMessage);
      for (const ev of eventsPerCall) yield ev;
    },
  };
  return { engine, calls };
}

describe("runGoalLoop", () => {
  beforeEach(() => {
    resetGoalStatusForTests();
    resetLoopPhaseForTests();
  });

  it("defaults to GOAL_MAX_ITERATIONS calls to submitMessage when maxIterations is omitted", async () => {
    const { engine, calls } = makeFakeEngine([assistantTextEvent(), resultSuccessEvent()]);
    await runGoalLoop(engine, "reach the summit");
    expect(calls.length).toBe(GOAL_MAX_ITERATIONS);
  });

  it("honors an explicit maxIterations override", async () => {
    const { engine, calls } = makeFakeEngine([assistantTextEvent(), resultSuccessEvent()]);
    await runGoalLoop(engine, "reach the summit", 2);
    expect(calls.length).toBe(2);
  });

  it("returns a completed snapshot with step===maxIterations and phase idle on a clean finish", async () => {
    const { engine } = makeFakeEngine([assistantTextEvent(), resultSuccessEvent()]);
    const final = await runGoalLoop(engine, "reach the summit", 3);
    expect(final.status).toBe("completed");
    expect(final.step).toBe(3);
    expect(final.maxSteps).toBe(3);
    expect(final.phase).toBe("idle");
  });

  it("publishes REAL setLoopPhase transitions -- getModeHistory shows orient then verify per iteration", async () => {
    const { engine } = makeFakeEngine([assistantTextEvent(), userToolResultEvent(), resultSuccessEvent()]);
    await runGoalLoop(engine, "reach the summit", 2);
    const history = getModeHistory();
    // Each iteration: assistant(text)->"orient", user->"verify". 2 iterations = 4 entries,
    // plus the final setLoopPhase("idle") -> "observe" appended at the very end.
    expect(history).toEqual(["orient", "verify", "orient", "verify", "observe"]);
  });

  it("a tool_use assistant event publishes 'act' (the tool_call phase), not 'orient'", async () => {
    const { engine } = makeFakeEngine([assistantToolUseEvent(), resultSuccessEvent()]);
    await runGoalLoop(engine, "reach the summit", 1);
    // The last non-idle mode observed before the terminal "observe" reset.
    const history = getModeHistory();
    expect(history[0]).toBe("act");
  });

  it("getGoalStatus() reflects the live snapshot during and after the run (not fabricated -- driven by the same object runGoalLoop returns)", async () => {
    const { engine } = makeFakeEngine([assistantTextEvent(), resultSuccessEvent()]);
    const final = await runGoalLoop(engine, "reach the summit", 2);
    expect(getGoalStatus()).toEqual(final);
  });

  it("an error result event ends the run early at status:'error', without exhausting maxIterations", async () => {
    const { engine, calls } = makeFakeEngine([assistantTextEvent(), resultErrorEvent()]);
    const final = await runGoalLoop(engine, "reach the summit", 5);
    expect(final.status).toBe("error");
    expect(calls.length).toBe(1); // stopped after the first iteration's error, never reached 5
  });

  it("a thrown exception from the engine also ends the run at status:'error'", async () => {
    const engine: GoalEngineLike = {
      // eslint-disable-next-line require-yield
      async *submitMessage() {
        throw new Error("engine exploded");
      },
    };
    const final = await runGoalLoop(engine, "reach the summit", 5);
    expect(final.status).toBe("error");
  });

  it("the objective and maxSteps are carried through unchanged on the returned snapshot", async () => {
    const { engine } = makeFakeEngine([assistantTextEvent(), resultSuccessEvent()]);
    const final = await runGoalLoop(engine, "ship the R0 ladder", 4);
    expect(final.objective).toBe("ship the R0 ladder");
    expect(final.maxSteps).toBe(4);
  });
});

describe("createGoalCommand — /goal", () => {
  beforeEach(() => {
    resetGoalStatusForTests();
    resetLoopPhaseForTests();
    resetGoalEngineProviderForTests();
  });

  it("returns a usage message when no objective is given", async () => {
    const cmd = createGoalCommand({ getEngine: () => null });
    const result = await cmd.execute("", { sessionId: "s", mode: "default", cwd: "/x" });
    expect(result?.message).toContain("usage");
  });

  it("honestly reports no active engine rather than fabricating a 'started' claim", async () => {
    const cmd = createGoalCommand({ getEngine: () => null });
    const result = await cmd.execute("reach the summit", { sessionId: "s", mode: "default", cwd: "/x" });
    expect(result?.message).toContain("no active session engine");
  });

  it("with a live engine, starts the loop (fire-and-forget) and acks immediately without blocking on completion", async () => {
    let loopStarted = false;
    let loopResolved = false;
    const engine: GoalEngineLike = {
      async *submitMessage() {
        loopStarted = true;
        await new Promise((r) => setTimeout(r, 20));
        loopResolved = true;
        yield resultSuccessEvent();
      },
    };
    const cmd = createGoalCommand({ getEngine: () => engine, maxIterations: 1 });
    const result = await cmd.execute("reach the summit", { sessionId: "s", mode: "default", cwd: "/x" });
    expect(result?.message).toContain("goal loop started");
    expect(result?.message).toContain("reach the summit");
    // execute() resolved before the fake engine's internal 20ms delay completed --
    // proves the command did not await full loop completion.
    expect(loopResolved).toBe(false);
    expect(loopStarted).toBe(true);
    await new Promise((r) => setTimeout(r, 40));
    expect(loopResolved).toBe(true);
  });

  it("setGoalEngineProvider wires the default getEngine() -- the exact hook screens/repl.ts calls after lazy-init", async () => {
    const engine: GoalEngineLike = {
      async *submitMessage() {
        yield resultSuccessEvent();
      },
    };
    setGoalEngineProvider(() => engine);
    const cmd = createGoalCommand({ maxIterations: 1 });
    const result = await cmd.execute("reach the summit", { sessionId: "s", mode: "default", cwd: "/x" });
    expect(result?.message).toContain("goal loop started");
  });

  it("name/description/isEnabled are set for registry integration", () => {
    const cmd = createGoalCommand({ getEngine: () => null });
    expect(cmd.name).toBe("goal");
    expect(cmd.isEnabled()).toBe(true);
    expect(cmd.description.length).toBeGreaterThan(0);
  });
});
