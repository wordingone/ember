// services/model-circuit-breaker.test.ts — issue #239: pure state-machine unit
// for the cross-call retry circuit breaker. The existing per-turn retry
// (api-backend.ts's shouldRetry/computeRetryDelay, wired in query-engine.ts
// for issue #197) bounds retries WITHIN a single turn, but a new turn (or a
// goal-continuation re-invocation, issue #211) starts a fresh attempt count
// and will happily retry a persistently broken endpoint forever across turns
// -- the actual shape of the 20h wedge incident (issue #239). This module
// tracks failure state ACROSS calls so the client can fail fast, locally,
// with zero network hits, once it knows the endpoint is broken.
//
// Pure logic only -- no network, no timers (tests inject `now`).

import { describe, it, expect } from "bun:test";
import {
  CIRCUIT_BASE_DELAY_MS,
  CIRCUIT_BACKOFF_CAP_MS,
  CIRCUIT_MAX_ATTEMPTS,
  CIRCUIT_PROBE_INTERVAL_MS,
  createCircuitBreakerState,
  isNonRetryableClientError,
  computeCircuitBackoffDelay,
  canAttempt,
  recordFailure,
  recordSuccess,
  markProbeStart,
  describeDegradedBanner,
} from "./model-circuit-breaker.ts";

describe("createCircuitBreakerState", () => {
  it("starts closed with zero failures", () => {
    const s = createCircuitBreakerState();
    expect(s.state).toBe("closed");
    expect(s.consecutiveFailures).toBe(0);
    expect(s.openedAt).toBeNull();
    expect(s.lastProbeAt).toBeNull();
  });
});

describe("isNonRetryableClientError — 4xx except 408/429", () => {
  it("400/401/403/404/451 are non-retryable", () => {
    for (const status of [400, 401, 403, 404, 451, 499]) {
      expect(isNonRetryableClientError(status)).toBe(true);
    }
  });

  it("408 and 429 are NOT classified as non-retryable (they get bounded backoff)", () => {
    expect(isNonRetryableClientError(408)).toBe(false);
    expect(isNonRetryableClientError(429)).toBe(false);
  });

  it("5xx, null, and non-4xx are not non-retryable-client-errors", () => {
    expect(isNonRetryableClientError(500)).toBe(false);
    expect(isNonRetryableClientError(503)).toBe(false);
    expect(isNonRetryableClientError(null)).toBe(false);
    expect(isNonRetryableClientError(200)).toBe(false);
  });
});

describe("computeCircuitBackoffDelay — base 1s, cap 30s", () => {
  it("attempt 0 is close to the 1000ms base (plus up to 20% jitter)", () => {
    const d = computeCircuitBackoffDelay(0);
    expect(d).toBeGreaterThanOrEqual(CIRCUIT_BASE_DELAY_MS);
    expect(d).toBeLessThanOrEqual(CIRCUIT_BASE_DELAY_MS * 1.2 + 1);
  });

  it("grows exponentially and never exceeds the 30s cap (+ jitter)", () => {
    for (let attempt = 0; attempt < 10; attempt++) {
      const d = computeCircuitBackoffDelay(attempt);
      expect(d).toBeLessThanOrEqual(CIRCUIT_BACKOFF_CAP_MS * 1.2 + 1);
    }
  });

  it("attempt 5 is capped at 30s (2^5 * 1000 = 32000 > cap)", () => {
    const d = computeCircuitBackoffDelay(5);
    expect(d).toBeGreaterThanOrEqual(CIRCUIT_BACKOFF_CAP_MS);
    expect(d).toBeLessThanOrEqual(CIRCUIT_BACKOFF_CAP_MS * 1.2 + 1);
  });
});

describe("recordFailure — non-retryable 4xx opens the circuit immediately", () => {
  it("a single 400 opens the circuit from closed, no bounded backoff needed", () => {
    const s0 = createCircuitBreakerState();
    const s1 = recordFailure(s0, {
      status: 400,
      isNetworkError: false,
      endpoint: "http://localhost:9999",
      reason: "HTTP 400",
      now: 1000,
    });
    expect(s1.state).toBe("open");
    expect(s1.openedAt).toBe(1000);
    expect(s1.lastStatus).toBe(400);
    expect(s1.endpoint).toBe("http://localhost:9999");
    expect(s1.consecutiveFailures).toBeGreaterThanOrEqual(1);
  });
});

describe("recordFailure — retryable errors accumulate toward CIRCUIT_MAX_ATTEMPTS then open", () => {
  it("stays closed while under the max-attempts ceiling", () => {
    let s = createCircuitBreakerState();
    for (let i = 0; i < CIRCUIT_MAX_ATTEMPTS - 1; i++) {
      s = recordFailure(s, {
        status: 503,
        isNetworkError: false,
        endpoint: "http://localhost:9999",
        reason: "HTTP 503",
        now: 1000 + i,
      });
      expect(s.state).toBe("closed");
    }
    expect(s.consecutiveFailures).toBe(CIRCUIT_MAX_ATTEMPTS - 1);
  });

  it("opens once consecutive failures reach CIRCUIT_MAX_ATTEMPTS", () => {
    let s = createCircuitBreakerState();
    for (let i = 0; i < CIRCUIT_MAX_ATTEMPTS; i++) {
      s = recordFailure(s, {
        status: 503,
        isNetworkError: false,
        endpoint: "http://localhost:9999",
        reason: "HTTP 503",
        now: 1000 + i,
      });
    }
    expect(s.state).toBe("open");
    expect(s.consecutiveFailures).toBe(CIRCUIT_MAX_ATTEMPTS);
  });

  it("network errors (status null) accumulate the same way as 5xx", () => {
    let s = createCircuitBreakerState();
    for (let i = 0; i < CIRCUIT_MAX_ATTEMPTS; i++) {
      s = recordFailure(s, {
        status: null,
        isNetworkError: true,
        endpoint: "http://localhost:9999",
        reason: "connection error",
        now: 1000 + i,
      });
    }
    expect(s.state).toBe("open");
  });

  it("429 is retryable (accumulates, does not open on a single failure)", () => {
    const s = recordFailure(createCircuitBreakerState(), {
      status: 429,
      isNetworkError: false,
      endpoint: "http://localhost:9999",
      reason: "HTTP 429",
      now: 1000,
    });
    expect(s.state).toBe("closed");
    expect(s.consecutiveFailures).toBe(1);
  });
});

describe("canAttempt — gates calls once the circuit is open", () => {
  it("closed: always allowed, never a probe", () => {
    const s = createCircuitBreakerState();
    expect(canAttempt(s, 1000)).toEqual({ allowed: true, isProbe: false });
  });

  it("open, before the 60s probe interval elapses: blocked", () => {
    const s = recordFailure(createCircuitBreakerState(), {
      status: 400,
      isNetworkError: false,
      endpoint: "e",
      reason: "HTTP 400",
      now: 0,
    });
    const result = canAttempt(s, CIRCUIT_PROBE_INTERVAL_MS - 1);
    expect(result.allowed).toBe(false);
  });

  it("open, at/after the 60s probe interval: exactly one probe allowed", () => {
    const s = recordFailure(createCircuitBreakerState(), {
      status: 400,
      isNetworkError: false,
      endpoint: "e",
      reason: "HTTP 400",
      now: 0,
    });
    const result = canAttempt(s, CIRCUIT_PROBE_INTERVAL_MS);
    expect(result).toEqual({ allowed: true, isProbe: true });
  });
});

describe("markProbeStart / half-open lifecycle", () => {
  it("transitions open -> half-open and records the probe timestamp", () => {
    const opened = recordFailure(createCircuitBreakerState(), {
      status: 400,
      isNetworkError: false,
      endpoint: "e",
      reason: "HTTP 400",
      now: 0,
    });
    const probing = markProbeStart(opened, CIRCUIT_PROBE_INTERVAL_MS);
    expect(probing.state).toBe("half-open");
    expect(probing.lastProbeAt).toBe(CIRCUIT_PROBE_INTERVAL_MS);
  });

  it("a failed probe returns to open and resets the probe clock (not a fresh 6-attempt cycle)", () => {
    const opened = recordFailure(createCircuitBreakerState(), {
      status: 400,
      isNetworkError: false,
      endpoint: "e",
      reason: "HTTP 400",
      now: 0,
    });
    const probing = markProbeStart(opened, CIRCUIT_PROBE_INTERVAL_MS);
    const failedAgain = recordFailure(probing, {
      status: 400,
      isNetworkError: false,
      endpoint: "e",
      reason: "HTTP 400",
      now: CIRCUIT_PROBE_INTERVAL_MS + 5,
    });
    expect(failedAgain.state).toBe("open");
    expect(failedAgain.lastProbeAt).toBe(CIRCUIT_PROBE_INTERVAL_MS + 5);
    // Not eligible for another probe until another full interval passes
    expect(canAttempt(failedAgain, CIRCUIT_PROBE_INTERVAL_MS + 6).allowed).toBe(false);
  });

  it("a successful probe fully resets the circuit to closed", () => {
    const opened = recordFailure(createCircuitBreakerState(), {
      status: 400,
      isNetworkError: false,
      endpoint: "e",
      reason: "HTTP 400",
      now: 0,
    });
    const probing = markProbeStart(opened, CIRCUIT_PROBE_INTERVAL_MS);
    const closed = recordSuccess(probing);
    expect(closed.state).toBe("closed");
    expect(closed.consecutiveFailures).toBe(0);
    expect(canAttempt(closed, CIRCUIT_PROBE_INTERVAL_MS + 1)).toEqual({ allowed: true, isProbe: false });
  });
});

describe("recordSuccess — resets from any state", () => {
  it("closed-with-partial-failures -> closed, zeroed", () => {
    let s = createCircuitBreakerState();
    s = recordFailure(s, { status: 503, isNetworkError: false, endpoint: "e", reason: "HTTP 503", now: 1 });
    s = recordSuccess(s);
    expect(s).toEqual(createCircuitBreakerState());
  });
});

describe("describeDegradedBanner — UI-facing projection", () => {
  it("returns null when the circuit is closed", () => {
    expect(describeDegradedBanner(createCircuitBreakerState(), 0)).toBeNull();
  });

  it("surfaces endpoint, last status, attempt count, and next-probe time when open", () => {
    const s = recordFailure(createCircuitBreakerState(), {
      status: 400,
      isNetworkError: false,
      endpoint: "http://localhost:8081",
      reason: "HTTP 400",
      now: 5000,
    });
    const banner = describeDegradedBanner(s, 5000);
    expect(banner).not.toBeNull();
    expect(banner!.active).toBe(true);
    expect(banner!.endpoint).toBe("http://localhost:8081");
    expect(banner!.lastStatus).toBe(400);
    expect(banner!.lastReason).toBe("HTTP 400");
    expect(banner!.attemptCount).toBeGreaterThanOrEqual(1);
    expect(banner!.nextProbeAt).toBe(5000 + CIRCUIT_PROBE_INTERVAL_MS);
    expect(banner!.probing).toBe(false);
  });

  it("flags probing:true while half-open", () => {
    const opened = recordFailure(createCircuitBreakerState(), {
      status: 400,
      isNetworkError: false,
      endpoint: "e",
      reason: "HTTP 400",
      now: 0,
    });
    const probing = markProbeStart(opened, CIRCUIT_PROBE_INTERVAL_MS);
    const banner = describeDegradedBanner(probing, CIRCUIT_PROBE_INTERVAL_MS);
    expect(banner!.probing).toBe(true);
  });
});
