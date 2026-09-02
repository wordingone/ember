// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for bridge-auth.ts — AC1 through AC12

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import {
  decodeWorkSecret,
  buildSdkUrl,
  buildCCRv2SdkUrl,
  decodeJwtPayload,
  decodeJwtExpiry,
  createTokenRefreshScheduler,
  toCompatSessionId,
  toInfraSessionId,
  sameSessionId,
  setCseShimGate,
  clearTrustedDeviceToken,
} from "./bridge-auth.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Base64url-encode a JSON object for WorkSecret tests. */
function encodeWorkSecret(obj: unknown): string {
  const json = JSON.stringify(obj);
  const b64 = btoa(json);
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

/** Build a minimal valid WorkSecret payload. */
function validPayload(overrides: Record<string, unknown> = {}) {
  return {
    version: 1,
    session_ingress_token: "tok-abc",
    api_base_url: "https://api.ember.ai",
    sources: [],
    auth: [],
    ...overrides,
  };
}

/** Build a JWT with a given payload (not signed — header.payload.sig). */
function makeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
  return `${header}.${body}.fakesig`;
}

// ---------------------------------------------------------------------------
// decodeWorkSecret — AC1, AC2, AC3
// ---------------------------------------------------------------------------

describe("decodeWorkSecret", () => {
  it("AC1: decodes a valid v1 payload and returns the typed object", () => {
    const secret = encodeWorkSecret(validPayload());
    const result = decodeWorkSecret(secret);
    expect(result.version).toBe(1);
    expect(result.session_ingress_token).toBe("tok-abc");
    expect(result.api_base_url).toBe("https://api.ember.ai");
  });

  it("AC2: throws when version is 2", () => {
    const secret = encodeWorkSecret(validPayload({ version: 2 }));
    expect(() => decodeWorkSecret(secret)).toThrow();
  });

  it("AC3: throws when session_ingress_token is missing", () => {
    const secret = encodeWorkSecret({
      version: 1,
      api_base_url: "https://api.ember.ai",
      sources: [],
      auth: [],
    });
    expect(() => decodeWorkSecret(secret)).toThrow();
  });

  it("throws when api_base_url is missing", () => {
    const secret = encodeWorkSecret({
      version: 1,
      session_ingress_token: "tok",
      sources: [],
      auth: [],
    });
    expect(() => decodeWorkSecret(secret)).toThrow();
  });
});

// ---------------------------------------------------------------------------
// buildSdkUrl — AC4, AC5
// ---------------------------------------------------------------------------

describe("buildSdkUrl", () => {
  it("AC4: uses ws:// for localhost", () => {
    expect(buildSdkUrl("http://localhost:1234", "abc")).toBe(
      "ws://localhost:1234/v1/session_ingress/ws/abc",
    );
  });

  it("AC5: uses wss:// for production https", () => {
    expect(buildSdkUrl("https://api.example.com", "abc")).toBe(
      "wss://api.example.com/v1/session_ingress/ws/abc",
    );
  });

  it("uses wss:// for production http (non-localhost)", () => {
    expect(buildSdkUrl("http://api.example.com", "abc")).toBe(
      "wss://api.example.com/v1/session_ingress/ws/abc",
    );
  });
});

// ---------------------------------------------------------------------------
// buildCCRv2SdkUrl
// ---------------------------------------------------------------------------

describe("buildCCRv2SdkUrl", () => {
  it("returns the v2 HTTP URL with sessionId", () => {
    expect(buildCCRv2SdkUrl("https://api.example.com", "sess-1")).toBe(
      "https://api.example.com/v1/code/sessions/sess-1",
    );
  });
});

// ---------------------------------------------------------------------------
// decodeJwtPayload / decodeJwtExpiry
// ---------------------------------------------------------------------------

describe("decodeJwtPayload", () => {
  it("returns payload object from standard JWT", () => {
    const jwt = makeJwt({ sub: "user-1", exp: 9999999999 });
    const payload = decodeJwtPayload(jwt) as Record<string, unknown>;
    expect(payload["sub"]).toBe("user-1");
  });

  it("returns null on malformed input", () => {
    expect(decodeJwtPayload("not-a-jwt")).toBeNull();
  });
});

describe("decodeJwtExpiry", () => {
  it("extracts exp claim from JWT", () => {
    const expiry = 9999999999;
    const jwt = makeJwt({ exp: expiry });
    expect(decodeJwtExpiry(jwt)).toBe(expiry);
  });

  it("returns null when no exp", () => {
    const jwt = makeJwt({ sub: "user" });
    expect(decodeJwtExpiry(jwt)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Token refresh scheduler — AC6, AC7, AC8
// ---------------------------------------------------------------------------

describe("createTokenRefreshScheduler", () => {
  it("AC6: calls onRefresh before exp timestamp (at exp - refreshBufferMs)", async () => {
    const refreshed: string[] = [];
    const nowSec = Math.floor(Date.now() / 1000);
    const expSec = nowSec + 1; // 1 second from now
    const refreshBufferMs = 800; // fire at 200ms from now

    const jwt = makeJwt({ exp: expSec });

    const scheduler = createTokenRefreshScheduler({
      getAccessToken: async () => "new-token",
      onRefresh: (_sid, tok) => { refreshed.push(tok); },
      label: "test",
      refreshBufferMs,
    });

    scheduler.schedule("sess-1", jwt);

    // Wait long enough for the refresh to fire
    await new Promise<void>((resolve) => setTimeout(resolve, 600));
    scheduler.cancelAll();

    expect(refreshed.length).toBeGreaterThan(0);
    expect(refreshed[0]).toBe("new-token");
  });

  it("AC7: stops after 3 consecutive failures for a session", async () => {
    let attemptCount = 0;

    const scheduler = createTokenRefreshScheduler({
      getAccessToken: async () => {
        attemptCount++;
        throw new Error("token fetch failed");
      },
      onRefresh: () => {},
      label: "test",
      refreshBufferMs: 0,
    });

    // Schedule with no exp — uses fallback but with 0 delay for testing
    const jwt = makeJwt({ exp: Math.floor(Date.now() / 1000) }); // expired immediately
    scheduler.schedule("sess-1", jwt);

    // Wait for all retries
    await new Promise<void>((resolve) => setTimeout(resolve, 200));
    scheduler.cancelAll();

    // Should have stopped at MAX_RETRY_ATTEMPTS (3)
    expect(attemptCount).toBeLessThanOrEqual(3);
  });

  it("AC8: cancel prevents onRefresh from firing", async () => {
    const refreshed: string[] = [];
    const nowSec = Math.floor(Date.now() / 1000);
    const expSec = nowSec + 1;
    const jwt = makeJwt({ exp: expSec });

    const scheduler = createTokenRefreshScheduler({
      getAccessToken: async () => "new-token",
      onRefresh: (_sid, tok) => { refreshed.push(tok); },
      label: "test",
      refreshBufferMs: 800,
    });

    scheduler.schedule("sess-1", jwt);
    // Cancel immediately before the timer fires
    scheduler.cancel("sess-1");

    await new Promise<void>((resolve) => setTimeout(resolve, 400));
    expect(refreshed).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Session ID compatibility shim — AC9, AC10, AC11, AC12
// ---------------------------------------------------------------------------

describe("session ID compat shim", () => {
  // Enable the gate for these tests
  beforeEach(() => {
    setCseShimGate(() => true);
  });

  afterEach(() => {
    setCseShimGate(() => false);
  });

  it("AC9: sameSessionId returns true when both IDs have the same body (≥ 4 chars)", () => {
    // body 'wxyz' = 4 chars, meets the minimum
    expect(sameSessionId("cse_abc_wxyz", "session_abc_wxyz")).toBe(true);
  });

  it("AC10: sameSessionId returns false when body < 4 chars", () => {
    // 'ab' has 2 chars < 4
    expect(sameSessionId("cse_ab", "session_ab")).toBe(false);
  });

  it("AC11: toCompatSessionId('cse_abc') returns 'session_abc' when gate enabled", () => {
    expect(toCompatSessionId("cse_abc")).toBe("session_abc");
  });

  it("AC12: toCompatSessionId('session_abc') is a no-op", () => {
    expect(toCompatSessionId("session_abc")).toBe("session_abc");
  });

  it("toInfraSessionId converts session_* to cse_*", () => {
    expect(toInfraSessionId("session_abc")).toBe("cse_abc");
  });

  it("sameSessionId returns false when one ID has no underscore", () => {
    expect(sameSessionId("nounderscore", "session_abc")).toBe(false);
  });
});
