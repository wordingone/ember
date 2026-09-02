// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/model-circuit-breaker.wrap.test.ts — issue #239: wraps a
// callModel-shaped function (the model-client request path, e.g.
// session-init.ts's buildProductionCallModel output) with the circuit
// breaker from model-circuit-breaker.ts. This is the layer that actually
// decides whether to hit the network at all -- the "never loop" acceptance
// criterion lives here: once the circuit is open, wrappedCallModel must
// return WITHOUT invoking the underlying callModel, no matter how many times
// (or how long) the caller keeps calling it.

import { describe, it, expect } from "bun:test";
import {
  wrapModelClientWithCircuitBreaker,
  CircuitOpenError,
} from "./model-circuit-breaker-client.ts";
import { CIRCUIT_MAX_ATTEMPTS, CIRCUIT_PROBE_INTERVAL_MS, describeRoundtripAge } from "./model-circuit-breaker.ts";
import { ModelHttpError } from "./api-openai-adapter.ts";
import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";

const okParams: CallModelParams = {
  messages: [],
  systemPrompt: "test",
  tools: [],
  model: "test",
  maxTokens: 100,
};

const okResponse: ModelResponse = {
  role: "assistant",
  content: [{ type: "text", text: "hi" }],
  stop_reason: "end_turn",
};

function makeClock(start = 0) {
  let now = start;
  return { now: () => now, advance: (ms: number) => { now += ms; } };
}

describe("wrapModelClientWithCircuitBreaker — fail-fast on non-retryable 4xx", () => {
  it("a single 400 makes exactly ONE underlying call, then throws CircuitOpenError", async () => {
    let calls = 0;
    const clock = makeClock();
    const sleeps: number[] = [];
    const handle = wrapModelClientWithCircuitBreaker(
      async () => { calls += 1; throw new ModelHttpError(400, "Bad Request"); },
      { endpoint: "http://localhost:9999", now: clock.now, sleep: async (ms) => { sleeps.push(ms); } },
    );

    await expect(handle.callModel(okParams)).rejects.toBeInstanceOf(CircuitOpenError);
    expect(calls).toBe(1);
    expect(sleeps).toEqual([]); // fail-fast: no backoff wait at all
    expect(handle.getState().state).toBe("open");
  });
});

describe("wrapModelClientWithCircuitBreaker — bounded backoff on retryable errors", () => {
  it("succeeds on the 3rd attempt: 2 backoff sleeps, circuit stays closed", async () => {
    let calls = 0;
    const clock = makeClock();
    const sleeps: number[] = [];
    const handle = wrapModelClientWithCircuitBreaker(
      async () => {
        calls += 1;
        if (calls < 3) throw new ModelHttpError(503, "Service Unavailable");
        return okResponse;
      },
      { endpoint: "e", now: clock.now, sleep: async (ms) => { sleeps.push(ms); } },
    );

    const result = await handle.callModel(okParams);
    expect(result).toEqual(okResponse);
    expect(calls).toBe(3);
    expect(sleeps.length).toBe(2);
    expect(handle.getState().state).toBe("closed");
    expect(handle.getState().consecutiveFailures).toBe(0);
    // #239 final acceptance clause: the eventual success stamps lastSuccessAt
    // with the wrapper's injected clock, not a real Date.now() the test can't control.
    expect(handle.getState().lastSuccessAt).toBe(clock.now());
  });

  it("exhausting all 6 attempts opens the circuit -- exactly 6 underlying calls, never more", async () => {
    let calls = 0;
    const clock = makeClock();
    const handle = wrapModelClientWithCircuitBreaker(
      async () => { calls += 1; throw new ModelHttpError(503, "Service Unavailable"); },
      { endpoint: "http://localhost:9999", now: clock.now, sleep: async () => {} },
    );

    await expect(handle.callModel(okParams)).rejects.toBeInstanceOf(CircuitOpenError);
    expect(calls).toBe(CIRCUIT_MAX_ATTEMPTS);
    expect(handle.getState().state).toBe("open");
  });
});

describe("wrapModelClientWithCircuitBreaker — once OPEN, blocks further calls with zero network hits", () => {
  it("simulated wedge: invoking the wrapper 'forever' against a 400-forever mock never grows past the bound", async () => {
    // This is the dispatch spec's simulated-wedge acceptance test: a mock
    // endpoint that always returns 400 (the actual #239 incident shape), and
    // a caller that keeps invoking the client over and over (standing in for
    // repeated turns / goal-continuation re-invocations across the 20h
    // incident window). The fix's whole point is that the attempt counter
    // must NOT grow unboundedly with the number of caller invocations.
    let networkCalls = 0;
    const clock = makeClock();
    const handle = wrapModelClientWithCircuitBreaker(
      async () => { networkCalls += 1; throw new ModelHttpError(400, "Bad Request"); },
      { endpoint: "http://localhost:9999", now: clock.now, sleep: async () => {} },
    );

    const rejections: unknown[] = [];
    for (let i = 0; i < 50; i++) {
      try {
        await handle.callModel(okParams);
      } catch (err) {
        rejections.push(err);
      }
    }

    expect(rejections.length).toBe(50);
    expect(rejections.every((e) => e instanceof CircuitOpenError)).toBe(true);
    // The 400 is non-retryable: only the FIRST of the 50 invocations ever
    // reached the network. The other 49 were rejected locally.
    expect(networkCalls).toBe(1);
    expect(networkCalls).toBeLessThanOrEqual(CIRCUIT_MAX_ATTEMPTS);
    expect(handle.getState().state).toBe("open");
  });

  it("blocks calls before the 60s probe window, with zero additional network hits", async () => {
    let calls = 0;
    const clock = makeClock();
    const handle = wrapModelClientWithCircuitBreaker(
      async () => { calls += 1; throw new ModelHttpError(400, "Bad Request"); },
      { endpoint: "e", now: clock.now, sleep: async () => {} },
    );

    await expect(handle.callModel(okParams)).rejects.toBeInstanceOf(CircuitOpenError);
    expect(calls).toBe(1);

    clock.advance(CIRCUIT_PROBE_INTERVAL_MS - 1);
    await expect(handle.callModel(okParams)).rejects.toBeInstanceOf(CircuitOpenError);
    expect(calls).toBe(1); // still no new network hit
  });

  it("allows exactly one probe attempt after 60s; a failed probe re-arms the 60s window", async () => {
    let calls = 0;
    const clock = makeClock();
    const handle = wrapModelClientWithCircuitBreaker(
      async () => { calls += 1; throw new ModelHttpError(400, "Bad Request"); },
      { endpoint: "e", now: clock.now, sleep: async () => {} },
    );

    await expect(handle.callModel(okParams)).rejects.toBeInstanceOf(CircuitOpenError);
    expect(calls).toBe(1);

    clock.advance(CIRCUIT_PROBE_INTERVAL_MS);
    await expect(handle.callModel(okParams)).rejects.toBeInstanceOf(CircuitOpenError);
    expect(calls).toBe(2); // exactly one probe hit the network

    // Immediately after the failed probe, still blocked (probe clock reset)
    await expect(handle.callModel(okParams)).rejects.toBeInstanceOf(CircuitOpenError);
    expect(calls).toBe(2);
  });

  it("a successful probe closes the circuit", async () => {
    let calls = 0;
    const clock = makeClock();
    const handle = wrapModelClientWithCircuitBreaker(
      async () => {
        calls += 1;
        if (calls === 1) throw new ModelHttpError(400, "Bad Request");
        return okResponse;
      },
      { endpoint: "e", now: clock.now, sleep: async () => {} },
    );

    await expect(handle.callModel(okParams)).rejects.toBeInstanceOf(CircuitOpenError);
    clock.advance(CIRCUIT_PROBE_INTERVAL_MS);
    const result = await handle.callModel(okParams);
    expect(result).toEqual(okResponse);
    expect(handle.getState().state).toBe("closed");
  });
});

describe("wrapModelClientWithCircuitBreaker — non-endpoint errors pass through untouched", () => {
  it("a plain (non-HTTP, non-network) error never affects circuit state", async () => {
    const clock = makeClock();
    const handle = wrapModelClientWithCircuitBreaker(
      async () => { throw new Error("Model server response has no body"); },
      { endpoint: "e", now: clock.now, sleep: async () => { throw new Error("must not sleep"); } },
    );

    await expect(handle.callModel(okParams)).rejects.toThrow("Model server response has no body");
    expect(handle.getState().state).toBe("closed");
  });

  it("a user-initiated abort passes through immediately, circuit unaffected", async () => {
    const clock = makeClock();
    const ctrl = new AbortController();
    ctrl.abort();
    const handle = wrapModelClientWithCircuitBreaker(
      async () => {
        const err = new Error("aborted");
        err.name = "AbortError";
        throw err;
      },
      { endpoint: "e", now: clock.now, sleep: async () => { throw new Error("must not sleep"); } },
    );

    await expect(
      handle.callModel({ ...okParams, abortSignal: ctrl.signal }),
    ).rejects.toThrow("aborted");
    expect(handle.getState().state).toBe("closed");
  });
});

describe("wrapModelClientWithCircuitBreaker — #239 final acceptance clause: last-successful-roundtrip age", () => {
  it("never having succeeded: describeRoundtripAge reports null/null", () => {
    const clock = makeClock();
    const handle = wrapModelClientWithCircuitBreaker(
      async () => okResponse,
      { endpoint: "e", now: clock.now, sleep: async () => {} },
    );
    expect(describeRoundtripAge(handle.getState(), clock.now())).toEqual({
      lastSuccessAt: null,
      ageMs: null,
    });
  });

  it("a real successful roundtrip stamps a timestamp the status line can age against", async () => {
    const clock = makeClock(1_000);
    const handle = wrapModelClientWithCircuitBreaker(
      async () => okResponse,
      { endpoint: "e", now: clock.now, sleep: async () => {} },
    );

    await handle.callModel(okParams);
    clock.advance(4_500);
    const age = describeRoundtripAge(handle.getState(), clock.now());
    expect(age.lastSuccessAt).toBe(1_000);
    expect(age.ageMs).toBe(4_500);
  });

  it("a subsequent fail-fast 4xx opens the circuit but PRESERVES the prior success's age -- the operator can still see when the endpoint last actually worked, even while wedged", async () => {
    const clock = makeClock(1_000);
    let mode: "ok" | "fail" = "ok";
    const handle = wrapModelClientWithCircuitBreaker(
      async () => {
        if (mode === "fail") throw new ModelHttpError(400, "Bad Request");
        return okResponse;
      },
      { endpoint: "e", now: clock.now, sleep: async () => { throw new Error("must not sleep on 4xx"); } },
    );

    await handle.callModel(okParams); // succeeds at t=1000
    clock.advance(19_000); // t=20000
    mode = "fail";
    await expect(handle.callModel(okParams)).rejects.toBeInstanceOf(CircuitOpenError);

    expect(handle.getState().state).toBe("open");
    const age = describeRoundtripAge(handle.getState(), clock.now());
    expect(age.lastSuccessAt).toBe(1_000);
    expect(age.ageMs).toBe(19_000); // visibly stale, not silently reset to "just now"
  });
});
