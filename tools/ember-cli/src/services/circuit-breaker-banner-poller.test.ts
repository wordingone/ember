// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/circuit-breaker-banner-poller.test.ts — issue #239: pins the pure
// projection from the in-process circuit-breaker singleton
// (session-init.ts's getCircuitBreakerState) to status-bar.ts's
// DegradedBannerState. The React hook (useCircuitBreakerBanner) is a thin
// setInterval/useState shell around this; testing the projection directly
// avoids needing a React render cycle or a live server.

import { describe, it, expect, mock, afterEach } from "bun:test";
import { readDegradedBannerState, readRoundtripAgeState } from "./circuit-breaker-banner-poller.ts";
import {
  buildGuardedProductionCallModel,
  _resetInitForTests,
} from "../entrypoints/session-init.ts";

describe("readDegradedBannerState", () => {
  const origFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = origFetch;
    _resetInitForTests();
  });

  it("returns {active:false} when no guarded client has ever been wired", () => {
    _resetInitForTests();
    expect(readDegradedBannerState()).toEqual({ active: false });
  });

  it("returns {active:false} for a freshly wired guarded client (circuit starts closed)", () => {
    buildGuardedProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 4096 });
    expect(readDegradedBannerState()).toEqual({ active: false });
  });

  it("surfaces endpoint/status/attempt-count once the circuit opens", async () => {
    globalThis.fetch = mock(async () =>
      new Response(null, { status: 400, statusText: "Bad Request" }),
    ) as unknown as typeof fetch;

    const guarded = buildGuardedProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 4096 });

    let threw = false;
    try {
      await guarded.callModel({
        messages: [{ role: "user", content: "hi" }],
        systemPrompt: "test",
        tools: [],
        model: "test",
        maxTokens: 100,
      });
    } catch {
      threw = true;
    }
    expect(threw).toBe(true);

    const banner = readDegradedBannerState();
    expect(banner.active).toBe(true);
    expect(banner.endpoint).toBe("http://localhost:1");
    expect(banner.lastStatus).toBe(400);
    expect(banner.attemptCount).toBeGreaterThanOrEqual(1);
  });
});

describe("readRoundtripAgeState — #239 final acceptance clause: last-successful-roundtrip age", () => {
  const origFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = origFetch;
    _resetInitForTests();
  });

  it("returns {lastSuccessAt: null} when no guarded client has ever been wired", () => {
    _resetInitForTests();
    expect(readRoundtripAgeState()).toEqual({ lastSuccessAt: null });
  });

  it("returns {lastSuccessAt: null} for a freshly wired guarded client that has never been called", () => {
    buildGuardedProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 4096 });
    expect(readRoundtripAgeState()).toEqual({ lastSuccessAt: null });
  });

  it("a 4xx fail-fast (no retry, immediate degraded) never fabricates a success timestamp", async () => {
    globalThis.fetch = mock(async () =>
      new Response(null, { status: 400, statusText: "Bad Request" }),
    ) as unknown as typeof fetch;

    const guarded = buildGuardedProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 4096 });

    let threw = false;
    try {
      await guarded.callModel({
        messages: [{ role: "user", content: "hi" }],
        systemPrompt: "test",
        tools: [],
        model: "test",
        maxTokens: 100,
      });
    } catch {
      threw = true;
    }
    expect(threw).toBe(true);
    expect(guarded.getCircuitState().state).toBe("open");

    // The circuit is open (degraded), but since NO call ever succeeded, the
    // roundtrip-age indicator must stay "no roundtrip yet" -- not silently
    // claim a success that never happened.
    expect(readRoundtripAgeState()).toEqual({ lastSuccessAt: null });
  });
});
