// Tests for api-backend service (ACs from spec).
// W2-B: cloud cache / privileged-user imports removed; local-only adapter assertions updated.

import { describe, test, expect } from "bun:test";
import {
  classifyApiError,
  computeRetryDelay,
  shouldRetry,
  buildStandardHeaders,
  adoptServerStateOnConflict,
  shouldUseOpenAIAdapter,
  getPromptDumpPath,
  isPrivilegedUser,
  BASE_DELAY_MS,
  BACKOFF_CAP_MS,
  MAX_RETRY_ATTEMPTS,
  MAX_529_RETRIES_FOREGROUND,
  FILE_DOWNLOAD_SIZE_CAP_BYTES,
} from "./api-backend.ts";

describe("constants", () => {
  test("BASE_DELAY_MS is 500", () => expect(BASE_DELAY_MS).toBe(500));
  test("BACKOFF_CAP_MS is 8000", () => expect(BACKOFF_CAP_MS).toBe(8_000));
  test("MAX_RETRY_ATTEMPTS is 10", () => expect(MAX_RETRY_ATTEMPTS).toBe(10));
  test("MAX_529_RETRIES_FOREGROUND is 3", () => expect(MAX_529_RETRIES_FOREGROUND).toBe(3));
  test("FILE_DOWNLOAD_SIZE_CAP_BYTES is 500 MB", () =>
    expect(FILE_DOWNLOAD_SIZE_CAP_BYTES).toBe(500 * 1024 * 1024));
});

describe("error classification", () => {
  test("AC7: 401 → auth", () => {
    const e = classifyApiError(401, null, false, false);
    expect(e.category).toBe("auth");
    expect(e.status).toBe(401);
  });

  test("AC7: 429 → ratelimit", () => {
    const e = classifyApiError(429, null, false, false);
    expect(e.category).toBe("ratelimit");
    expect(e.status).toBe(429);
  });

  test("AC7: 529 → overloaded", () => {
    const e = classifyApiError(529, null, false, false);
    expect(e.category).toBe("overloaded");
    expect(e.status).toBe(529);
  });

  test("AC7: aborted → aborted", () => {
    const e = classifyApiError(null, null, true, false);
    expect(e.category).toBe("aborted");
  });

  test("AC7: connection error → connection", () => {
    const e = classifyApiError(null, null, false, true);
    expect(e.category).toBe("connection");
  });

  test("AC7: prompt_too_long error type → prompt_too_long", () => {
    const e = classifyApiError(400, { error: { type: "prompt_too_long" } }, false, false);
    expect(e.category).toBe("prompt_too_long");
  });

  test("AC7: unknown status → other", () => {
    const e = classifyApiError(418, null, false, false);
    expect(e.category).toBe("other");
  });
});

describe("retry logic", () => {
  test("AC4: should not retry when MAX_RETRY_ATTEMPTS reached", () => {
    expect(shouldRetry(500, false, MAX_RETRY_ATTEMPTS, 0, false)).toBe(false);
  });

  test("AC4: 5xx is retried", () => {
    expect(shouldRetry(503, false, 1, 0, false)).toBe(true);
  });

  test("AC4: 4xx (except 429, 529) is NOT retried", () => {
    expect(shouldRetry(400, false, 0, 0, false)).toBe(false);
    expect(shouldRetry(403, false, 0, 0, false)).toBe(false);
    expect(shouldRetry(404, false, 0, 0, false)).toBe(false);
  });

  test("AC3: 529 in foreground retried up to 3 times", () => {
    expect(shouldRetry(529, false, 0, 0, false)).toBe(true);  // 0 retries so far
    expect(shouldRetry(529, false, 0, 2, false)).toBe(true);  // 2 retries so far
    expect(shouldRetry(529, false, 0, 3, false)).toBe(false); // at cap
  });

  test("AC3: 529 in background → immediate bail", () => {
    expect(shouldRetry(529, false, 0, 0, true)).toBe(false);
  });

  test("AC4: network errors are retried", () => {
    expect(shouldRetry(null, true, 0, 0, false)).toBe(true);
    expect(shouldRetry(null, true, MAX_RETRY_ATTEMPTS - 1, 0, false)).toBe(false);
  });

  test("AC4: retry delay starts at BASE_DELAY_MS and caps at BACKOFF_CAP_MS", () => {
    // attempt 0 → ~500ms
    const d0 = computeRetryDelay(0);
    expect(d0).toBeGreaterThanOrEqual(0);
    expect(d0).toBeLessThanOrEqual(BACKOFF_CAP_MS * 1.3);

    // high attempt number → capped
    const dHigh = computeRetryDelay(100);
    // With 20% jitter: at most BACKOFF_CAP_MS * 1.2
    expect(dHigh).toBeLessThanOrEqual(BACKOFF_CAP_MS * 1.3);
  });
});

describe("request headers", () => {
  test("AC2: returns all required headers", () => {
    const headers = buildStandardHeaders("session-123", "Bearer tok", "ember-cli/1.0");
    expect(headers["x-client-request-id"]).toBeDefined();
    expect(headers["x-client-request-id"]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
    );
    expect(headers["User-Agent"]).toBe("ember-cli/1.0");
    expect(headers["X-Ember-Session-Id"]).toBe("session-123");
    expect(headers["Authorization"]).toBe("Bearer tok");
  });

  test("AC2: generates a different request-id each time", () => {
    const h1 = buildStandardHeaders("s", "a", "u");
    const h2 = buildStandardHeaders("s", "a", "u");
    expect(h1["x-client-request-id"]).not.toBe(h2["x-client-request-id"]);
  });
});

describe("session log conflict handling", () => {
  test("AC5: 409 adopts server's last UUID", () => {
    const state = adoptServerStateOnConflict("server-uuid-42");
    expect(state.lastKnownServerUuid).toBe("server-uuid-42");
  });

  test("AC5: null server UUID when server log is empty", () => {
    const state = adoptServerStateOnConflict(null);
    expect(state.lastKnownServerUuid).toBeNull();
  });
});

describe("model URL detection", () => {
  // W2-B: shouldUseOpenAIAdapter always returns true in local-only mode.
  test("AC1: always uses OpenAI adapter (local-only mode)", () => {
    const orig = process.env["EMBER_MODEL_URL"];
    process.env["EMBER_MODEL_URL"] = "http://localhost:8081";
    expect(shouldUseOpenAIAdapter()).toBe(true);
    if (orig === undefined) delete process.env["EMBER_MODEL_URL"];
    else process.env["EMBER_MODEL_URL"] = orig;
  });

  test("AC1: no EMBER_MODEL_URL → still uses OpenAI adapter (local-only)", () => {
    const orig = process.env["EMBER_MODEL_URL"];
    delete process.env["EMBER_MODEL_URL"];
    expect(shouldUseOpenAIAdapter()).toBe(true);
    if (orig !== undefined) process.env["EMBER_MODEL_URL"] = orig;
  });

  test("AC1: any URL → uses OpenAI adapter (cloud backend stripped)", () => {
    const orig = process.env["EMBER_MODEL_URL"];
    process.env["EMBER_MODEL_URL"] = "http://localhost:11434/v1";
    expect(shouldUseOpenAIAdapter()).toBe(true);
    if (orig === undefined) delete process.env["EMBER_MODEL_URL"];
    else process.env["EMBER_MODEL_URL"] = orig;
  });
});

describe("privileged user", () => {
  test("AC8: prompt dump path includes sessionId", () => {
    const path = getPromptDumpPath("my-session-id");
    expect(path).toContain("my-session-id.jsonl");
    expect(path).toContain("dump-prompts");
  });

  // W2-B: isPrivilegedUser always returns false in local-only mode.
  test("isPrivilegedUser always returns false (cloud billing concept stripped)", () => {
    expect(isPrivilegedUser()).toBe(false);
  });
});

// W2-B: passes-eligibility and overage-credit cache tests removed.
// Those were cloud billing (ember.ai subscription) concepts with no local equivalent.

// ---------------------------------------------------------------------------
// FINDING: api-backend.ts exposes only PURE retry-logic helpers (shouldRetry,
// computeRetryDelay). There is NO fetch-execution loop or injectable HTTP seam
// in this module. The retry execution loop lives in a consumer module
// (e.g. services/api-model-facing.ts). An end-to-end "inject a failing fetch N
// times then succeed" test is NOT POSSIBLE against api-backend.ts without either
// editing production code (forbidden) or duplicating retry-loop logic in the test.
//
// The tests below verify the retry POLICY through the pure-helper interface by
// simulating the call pattern an executor loop would follow, and tighten the
// computeRetryDelay lower-bound assertion that was previously `>= 0` (trivially
// true, permits a delay of 0 which violates the exponential backoff contract).
// ---------------------------------------------------------------------------

describe("retry policy simulation — transient-then-success loop shape", () => {
  test("5xx retries: shouldRetry permits exactly N failures before the caller's success branch", () => {
    // Simulates: 3 × 503 failures, then the caller's fetch succeeds.
    // The caller loop checks shouldRetry after each failure; on success it stops without
    // calling shouldRetry again. Verifies that shouldRetry returns true for all 3 failures
    // and that the attempt counter is exactly TRANSIENT_COUNT at the success point.
    const TRANSIENT_COUNT = 3;
    let attempt = 0;
    while (attempt < TRANSIENT_COUNT) {
      const willRetry = shouldRetry(503, false, attempt, 0, false);
      expect(willRetry).toBe(true); // must still be retriable at each transient failure
      attempt++;
    }
    // The next call would succeed; the loop exits without calling shouldRetry.
    // Attempt count is exactly TRANSIENT_COUNT — the retry floor is intact.
    expect(attempt).toBe(TRANSIENT_COUNT);
  });

  test("always-failing 503: loop stops at exactly MAX_RETRY_ATTEMPTS (hard ceiling not exceeded)", () => {
    // Simulates a permanently-overloaded server (503 on every attempt).
    // The caller loop increments attempt after each "failure" and calls shouldRetry again;
    // when shouldRetry returns false the loop stops.
    // Verifies: (a) the loop runs some iterations (floor > 0), (b) it stops at exactly
    // MAX_RETRY_ATTEMPTS (ceiling not exceeded or undercut).
    let attempt = 0;
    while (shouldRetry(503, false, attempt, 0, false)) {
      attempt++;
      // Safety valve: if shouldRetry never returns false the test would hang
      if (attempt > MAX_RETRY_ATTEMPTS + 5) {
        throw new Error(`shouldRetry(503) never returned false after ${attempt} iterations`);
      }
    }
    // Must stop at exactly the cap: not 1 fewer (too eager) nor 1 more (ceiling violated).
    expect(attempt).toBe(MAX_RETRY_ATTEMPTS);
  });

  test("permanent failure (401 auth): shouldRetry returns false at attempt 0 — never retried", () => {
    // 401 is an auth error; it is permanent by definition. The caller loop calls
    // shouldRetry(401, ..., 0) on the first failure and must get false immediately,
    // meaning at most 1 total attempt is made (the original call, not a retry).
    expect(shouldRetry(401, false, 0, 0, false)).toBe(false);
    // Verify the auth-never-retry invariant holds at every attempt count too:
    // even if the caller mistakenly called shouldRetry again it must still return false.
    for (let i = 1; i < MAX_RETRY_ATTEMPTS; i++) {
      expect(shouldRetry(401, false, i, 0, false)).toBe(false);
    }
  });
});

describe("computeRetryDelay — tightened lower-bound (prior test allowed delay = 0)", () => {
  test("attempt 0 delay is ≥ BASE_DELAY_MS, not merely ≥ 0 (exponential backoff floor)", () => {
    // The prior test checked `>= 0` which is trivially true (permits no delay at all).
    // The correct floor: BASE_DELAY_MS * 2^0 = BASE_DELAY_MS = 500 ms (before jitter).
    // Jitter is additive (capped * 0.2 * Math.random()), so the minimum is BASE_DELAY_MS.
    const d0 = computeRetryDelay(0);
    expect(d0).toBeGreaterThanOrEqual(BASE_DELAY_MS);
    // Upper bound: 500 + (500 * 0.2 * 1) = 600; allow +1 for Math.round rounding.
    expect(d0).toBeLessThanOrEqual(Math.ceil(BASE_DELAY_MS * 1.2) + 1);
  });

  test("attempt 1 delay is ≥ 2 × BASE_DELAY_MS (exponential growth through at least attempt 1)", () => {
    // BASE_DELAY_MS * 2^1 = 1000 ms base; jitter is additive.
    const d1 = computeRetryDelay(1);
    expect(d1).toBeGreaterThanOrEqual(BASE_DELAY_MS * 2);
    expect(d1).toBeLessThanOrEqual(Math.ceil(BASE_DELAY_MS * 2 * 1.2) + 1);
  });

  test("high-attempt delay is ≥ BACKOFF_CAP_MS and ≤ BACKOFF_CAP_MS * 1.2 (cap enforced)", () => {
    // At attempt 100 the base overflows the cap; the result must be in [cap, cap*1.2].
    const dHigh = computeRetryDelay(100);
    expect(dHigh).toBeGreaterThanOrEqual(BACKOFF_CAP_MS);
    expect(dHigh).toBeLessThanOrEqual(Math.ceil(BACKOFF_CAP_MS * 1.2) + 1);
  });
});
