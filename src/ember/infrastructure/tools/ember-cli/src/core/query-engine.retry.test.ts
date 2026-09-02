// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// core/query-engine.retry.test.ts — issue #197 Legs 3/4: the production
// callModel made exactly one attempt per turn -- a deterministic 400 as much
// as a transient connection drop terminated the turn immediately, and the
// REPL's "Retrying..." UI text was shown on EVERY terminal error regardless
// of whether any retry ever actually happened (repl.ts's renderMsgDispatch
// hardcoded a retryCount default of 4; see repl.dispatch.test.ts for that
// half). This file pins query()'s retry loop: a deterministic 4xx (except
// 429/408) throws straight through with zero retries; a transient 5xx/
// timeout/connection failure gets bounded attempts with backoff, each one
// reported via the onRetryAttempt callback BEFORE its wait begins, and a
// terminal result event when the retry budget is exhausted.

import { describe, it, expect } from "bun:test";
import { query, type QueryEvent, type RetryAttemptInfo } from "./query-engine.ts";
import { type LoopDepsOverrides, type ModelResponse } from "../query/query-loop-support.ts";
import { ModelHttpError } from "../services/api-openai-adapter.ts";
import { MAX_RETRY_ATTEMPTS } from "../api-backend.ts";
import type { ToolUseContext } from "./tool-interface.ts";

function makeToolUseContext(overrides: Partial<ToolUseContext> = {}): ToolUseContext {
  return {
    options: { tools: [], mainLoopModel: "test" },
    abortController: new AbortController(),
    getAppState: () => ({}),
    setAppState: () => {},
    setAppStateForTasks: () => {},
    readFileState: new Map(),
    messages: [],
    appendSystemMessage: () => {},
    nestedMemoryAttachmentTriggers: new Set(),
    loadedNestedMemoryPaths: new Set(),
    dynamicSkillDirTriggers: new Set(),
    discoveredSkillNames: new Set(),
    fileReadingLimits: { maxTokens: 10000, maxSizeBytes: 1024 * 1024 },
    globLimits: { maxResults: 100 },
    toolUseId: "test_tool_use",
    setSDKStatus: undefined,
    ...overrides,
  } as ToolUseContext;
}

const finalResponse: ModelResponse = {
  role: "assistant",
  content: [{ type: "text", text: "done" }],
  stop_reason: "end_turn",
};

describe("query loop — retry policy (issue #197 Legs 3/4)", () => {
  it("a deterministic 400 is never retried: one callModel invocation, immediate terminal error", async () => {
    let callCount = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        callCount += 1;
        throw new ModelHttpError(400, "Bad Request");
      },
      generateUuid: () => "u",
      sleep: async () => {
        throw new Error("sleep must never be called for a non-retried 400");
      },
    };
    const toolUseContext = makeToolUseContext();

    const events: QueryEvent[] = [];
    for await (const event of query(
      { messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }], systemPrompt: "test", toolUseContext },
      testDeps,
    )) {
      events.push(event);
    }

    expect(callCount).toBe(1);
    const result = events.find((e) => e.type === "result");
    expect(result).toBeDefined();
    expect((result as { subtype: string }).subtype).toBe("error");
  });

  it("a 503 retries with bounded backoff and yields a terminal error once the retry budget is exhausted", async () => {
    let callCount = 0;
    const sleepCalls: number[] = [];
    const retryAttempts: RetryAttemptInfo[] = [];
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        callCount += 1;
        throw new ModelHttpError(503, "Service Unavailable");
      },
      generateUuid: () => "u",
      sleep: async (ms: number) => {
        sleepCalls.push(ms);
        // instant resolve -- no real timers in a unit test
      },
    };
    const toolUseContext = makeToolUseContext();

    const events: QueryEvent[] = [];
    for await (const event of query(
      { messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }], systemPrompt: "test", toolUseContext },
      testDeps,
      { onRetryAttempt: (info) => retryAttempts.push(info) },
    )) {
      events.push(event);
    }

    // MAX_RETRY_ATTEMPTS retries after the original attempt, then give up.
    expect(callCount).toBe(MAX_RETRY_ATTEMPTS + 1);
    expect(sleepCalls.length).toBe(MAX_RETRY_ATTEMPTS);
    expect(retryAttempts.length).toBe(MAX_RETRY_ATTEMPTS);

    // Each reported attempt is visible BEFORE its wait -- attempt numbers count
    // up 1..MAX_RETRY_ATTEMPTS, all bounded by the same ceiling, all naming HTTP 503.
    retryAttempts.forEach((info, i) => {
      expect(info.attempt).toBe(i + 1);
      expect(info.maxAttempts).toBe(MAX_RETRY_ATTEMPTS);
      expect(info.status).toBe(503);
      expect(info.reason).toBe("HTTP 503");
      expect(info.delayMs).toBeGreaterThan(0);
    });

    const result = events.find((e) => e.type === "result");
    expect(result).toBeDefined();
    expect((result as { subtype: string }).subtype).toBe("error");
  });

  it("a connection-level failure (TypeError, e.g. fetch's own ECONNREFUSED wrapper) is retried", async () => {
    let callCount = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        callCount += 1;
        if (callCount < 3) throw new TypeError("fetch failed");
        return finalResponse;
      },
      generateUuid: () => "u",
      sleep: async () => {},
    };
    const toolUseContext = makeToolUseContext();

    const events: QueryEvent[] = [];
    for await (const event of query(
      { messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }], systemPrompt: "test", toolUseContext },
      testDeps,
    )) {
      events.push(event);
    }

    expect(callCount).toBe(3); // 2 failures + 1 success
    const result = events.find((e) => e.type === "result");
    expect((result as { subtype: string }).subtype).toBe("success");
  });

  it("a Bun-real connection-refused Error (plain Error, code='ConnectionRefused', NOT a TypeError) is retried", async () => {
    // Measured directly against Bun's fetch(): a from-scratch refused
    // connection throws `Error("Unable to connect...")` with
    // `code: "ConnectionRefused"` -- NOT a TypeError. The synthetic
    // `new TypeError(...)` test above does not exercise this real shape;
    // this is the exact classification gap acceptance leg C exposed (kill
    // the model server -> zero retries -> immediate terminal error).
    let callCount = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        callCount += 1;
        if (callCount < 3) {
          const err = new Error("Unable to connect. Is the computer able to access the url?");
          (err as { code?: string }).code = "ConnectionRefused";
          throw err;
        }
        return finalResponse;
      },
      generateUuid: () => "u",
      sleep: async () => {},
    };
    const toolUseContext = makeToolUseContext();

    const events: QueryEvent[] = [];
    for await (const event of query(
      { messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }], systemPrompt: "test", toolUseContext },
      testDeps,
    )) {
      events.push(event);
    }

    expect(callCount).toBe(3);
    const result = events.find((e) => e.type === "result");
    expect((result as { subtype: string }).subtype).toBe("success");
  });

  it("a Bun-real mid-stream ECONNRESET Error (plain Error, code='ECONNRESET') is retried", async () => {
    // Measured directly against Bun's fetch() reading an active SSE stream
    // whose server process was killed mid-response: throws
    // `Error("The socket connection was closed unexpectedly...")` with
    // `code: "ECONNRESET"` -- same non-TypeError shape as above.
    let callCount = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        callCount += 1;
        if (callCount < 2) {
          const err = new Error(
            "The socket connection was closed unexpectedly. For more information, pass `verbose: true` in the second argument to fetch()",
          );
          (err as { code?: string }).code = "ECONNRESET";
          throw err;
        }
        return finalResponse;
      },
      generateUuid: () => "u",
      sleep: async () => {},
    };
    const toolUseContext = makeToolUseContext();

    const events: QueryEvent[] = [];
    for await (const event of query(
      { messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }], systemPrompt: "test", toolUseContext },
      testDeps,
    )) {
      events.push(event);
    }

    expect(callCount).toBe(2);
    const result = events.find((e) => e.type === "result");
    expect((result as { subtype: string }).subtype).toBe("success");
  });

  it("a plain Error (not TypeError, not ModelHttpError, not AbortError) is never retried", async () => {
    // Regression guard for the exact bug this suite caught: classifying
    // "not a ModelHttpError" as "is a network error" retried this case into a
    // 5s timeout (query-engine.error-event.test.ts). A generic Error is an
    // unrecognized condition, not a confirmed transport failure -- terminate
    // immediately, same as before retry logic existed.
    let callCount = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        callCount += 1;
        throw new Error("something unexpected");
      },
      generateUuid: () => "u",
      sleep: async () => {
        throw new Error("sleep must never be called for an unrecognized plain Error");
      },
    };
    const toolUseContext = makeToolUseContext();

    const events: QueryEvent[] = [];
    for await (const event of query(
      { messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }], systemPrompt: "test", toolUseContext },
      testDeps,
    )) {
      events.push(event);
    }

    expect(callCount).toBe(1);
    const result = events.find((e) => e.type === "result");
    expect((result as { subtype: string }).subtype).toBe("error");
  });

  it("a raw non-Error throw is never retried and still surfaces as a usable error message", async () => {
    let callCount = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        callCount += 1;
        // eslint-disable-next-line @typescript-eslint/no-throw-literal
        throw "raw string rejection";
      },
      generateUuid: () => "u",
      sleep: async () => {
        throw new Error("sleep must never be called for a non-Error throw");
      },
    };
    const toolUseContext = makeToolUseContext();

    const events: QueryEvent[] = [];
    for await (const event of query(
      { messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }], systemPrompt: "test", toolUseContext },
      testDeps,
    )) {
      events.push(event);
    }

    expect(callCount).toBe(1);
    const result = events.find((e) => e.type === "result") as { subtype: string; errorMessage?: string };
    expect(result.subtype).toBe("error");
    expect(result.errorMessage).toBe("raw string rejection");
  });

  it("a user-initiated abort mid-backoff terminates as an abort result, not a further retry", async () => {
    const abortController = new AbortController();
    let callCount = 0;
    const testDeps: LoopDepsOverrides = {
      callModel: async () => {
        callCount += 1;
        throw new ModelHttpError(503, "Service Unavailable");
      },
      generateUuid: () => "u",
      sleep: async (_ms: number, signal?: AbortSignal) => {
        // Simulate the user hitting Ctrl+C while a retry backoff is in flight.
        abortController.abort();
        if (signal?.aborted) return; // real _defaultSleep resolves early on abort
      },
    };
    const toolUseContext = makeToolUseContext({ abortController });

    const events: QueryEvent[] = [];
    for await (const event of query(
      { messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }], systemPrompt: "test", toolUseContext },
      testDeps,
    )) {
      events.push(event);
    }

    // Aborted after the first retry's backoff -- exactly 2 attempts (original + 1 retry).
    expect(callCount).toBe(2);
    const result = events.find((e) => e.type === "result");
    expect((result as { subtype: string }).subtype).toBe("abort");
  });
});
