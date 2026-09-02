// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// github-app-auth.test.ts — tests for the GitHub App JWT mint + installation
// token exchange (ember issue #507).

import { describe, test, expect, beforeEach, afterEach, mock } from "bun:test";
import crypto from "node:crypto";
import { decodeJwtPayload } from "./bridge-auth.ts";
import {
  signAppJwt,
  resolveCredentials,
  getInstallationToken,
  checkRateLimit,
  SETUP_POINTER,
  setGithubAppAuthDeps,
  _resetGithubAppAuthDepsForTests,
  _clearTokenCacheForTests,
  type GithubAppCredentialsRaw,
} from "./github-app-auth.ts";

let testKeyPair: { publicKey: string; privateKey: string };

beforeEach(() => {
  testKeyPair = crypto.generateKeyPairSync("rsa", {
    modulusLength: 2048,
    publicKeyEncoding: { type: "spki", format: "pem" },
    privateKeyEncoding: { type: "pkcs8", format: "pem" },
  });
});

afterEach(() => {
  _resetGithubAppAuthDepsForTests();
  _clearTokenCacheForTests();
});

describe("signAppJwt", () => {
  test("produces a JWT whose signature verifies against the public key", () => {
    const jwt = signAppJwt("12345", testKeyPair.privateKey, Date.parse("2026-07-08T12:00:00.000Z"));
    const parts = jwt.split(".");
    expect(parts.length).toBe(3);

    const signingInput = `${parts[0]}.${parts[1]}`;
    const signature = Buffer.from(parts[2]!, "base64url");
    const verified = crypto.verify(
      "RSA-SHA256",
      Buffer.from(signingInput),
      testKeyPair.publicKey,
      signature,
    );
    expect(verified).toBe(true);
  });

  test("payload carries iss=appId, iat backdated 60s, exp within GitHub's 10-min ceiling", () => {
    const nowMs = Date.parse("2026-07-08T12:00:00.000Z");
    const jwt = signAppJwt("999", testKeyPair.privateKey, nowMs);
    const payload = decodeJwtPayload(jwt) as { iss: string; iat: number; exp: number };

    const nowSec = Math.floor(nowMs / 1000);
    expect(payload.iss).toBe("999");
    expect(payload.iat).toBe(nowSec - 60);
    expect(payload.exp).toBeLessThanOrEqual(nowSec + 10 * 60);
    expect(payload.exp).toBeGreaterThan(payload.iat);
  });
});

describe("resolveCredentials", () => {
  test("returns ok:false listing every missing env var when none are set", () => {
    setGithubAppAuthDeps({
      readEnv: (): GithubAppCredentialsRaw => ({ appId: undefined, installationId: undefined, privateKeyPath: undefined }),
    });
    const result = resolveCredentials();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.missing).toEqual(["EMBER_GH_APP_ID", "EMBER_GH_INSTALLATION_ID", "EMBER_GH_PRIVATE_KEY_PATH"]);
      expect(result.detail).toBe(SETUP_POINTER);
    }
  });

  test("returns ok:false listing only the missing subset", () => {
    setGithubAppAuthDeps({
      readEnv: (): GithubAppCredentialsRaw => ({ appId: "1", installationId: undefined, privateKeyPath: "/key.pem" }),
    });
    const result = resolveCredentials();
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.missing).toEqual(["EMBER_GH_INSTALLATION_ID"]);
  });

  test("returns ok:false when the key file can't be read, even with all env vars present", () => {
    setGithubAppAuthDeps({
      readEnv: (): GithubAppCredentialsRaw => ({ appId: "1", installationId: "2", privateKeyPath: "/nope.pem" }),
      readPrivateKeyFile: () => {
        throw new Error("ENOENT: no such file");
      },
    });
    const result = resolveCredentials();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.missing).toEqual(["EMBER_GH_PRIVATE_KEY_PATH"]);
      expect(result.detail).toContain("ENOENT");
    }
  });

  test("returns ok:true with resolved creds when everything is present and readable", () => {
    setGithubAppAuthDeps({
      readEnv: (): GithubAppCredentialsRaw => ({ appId: "1", installationId: "2", privateKeyPath: "/key.pem" }),
      readPrivateKeyFile: () => testKeyPair.privateKey,
    });
    const result = resolveCredentials();
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.creds).toEqual({ appId: "1", installationId: "2", privateKeyPem: testKeyPair.privateKey });
    }
  });
});

describe("getInstallationToken", () => {
  function configureDeps(overrides: Parameters<typeof setGithubAppAuthDeps>[0] = {}) {
    setGithubAppAuthDeps({
      readEnv: (): GithubAppCredentialsRaw => ({ appId: "1", installationId: "2", privateKeyPath: "/key.pem" }),
      readPrivateKeyFile: () => testKeyPair.privateKey,
      now: () => Date.parse("2026-07-08T12:00:00.000Z"),
      ...overrides,
    });
  }

  test("NOT_CONFIGURED when credentials are missing", async () => {
    setGithubAppAuthDeps({ readEnv: (): GithubAppCredentialsRaw => ({ appId: undefined, installationId: undefined, privateKeyPath: undefined }) });
    const result = await getInstallationToken();
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.state).toBe("NOT_CONFIGURED");
  });

  test("JWT_MINT_FAILED when signing throws", async () => {
    configureDeps({
      signJwt: () => {
        throw new Error("bad key");
      },
    });
    const result = await getInstallationToken();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.state).toBe("JWT_MINT_FAILED");
      expect(result.detail).toContain("bad key");
    }
  });

  test("EXCHANGE_FAILED when the token exchange rejects", async () => {
    configureDeps({
      fetchInstallationToken: async () => {
        throw new Error("installation not found");
      },
    });
    const result = await getInstallationToken();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.state).toBe("EXCHANGE_FAILED");
      expect(result.detail).toContain("installation not found");
    }
  });

  test("INSTALLATION_TOKEN_OK on a successful exchange, uncached on first call", async () => {
    const fetchMock = mock(async () => ({ token: "ghs_abc", expiresAt: "2026-07-08T12:10:00.000Z" }));
    configureDeps({ fetchInstallationToken: fetchMock });

    const result = await getInstallationToken();
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.state).toBe("INSTALLATION_TOKEN_OK");
      expect(result.token).toBe("ghs_abc");
      expect(result.cached).toBe(false);
    }
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("caches the token across calls within its validity window", async () => {
    const fetchMock = mock(async () => ({ token: "ghs_abc", expiresAt: "2026-07-08T12:10:00.000Z" }));
    configureDeps({ fetchInstallationToken: fetchMock });

    await getInstallationToken();
    const second = await getInstallationToken();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(second.ok).toBe(true);
    if (second.ok) expect(second.cached).toBe(true);
  });

  test("refreshes once the cached token is within the refresh buffer of expiry", async () => {
    let call = 0;
    const fetchMock = mock(async () => {
      call += 1;
      return { token: `ghs_${call}`, expiresAt: "2026-07-08T12:10:00.000Z" };
    });
    let nowMs = Date.parse("2026-07-08T12:00:00.000Z");
    configureDeps({ fetchInstallationToken: fetchMock, now: () => nowMs });

    await getInstallationToken();
    // Advance past expiresAt - REFRESH_BUFFER_MS (12:10:00 - 60s = 12:09:00).
    nowMs = Date.parse("2026-07-08T12:09:30.000Z");
    const second = await getInstallationToken();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(second.ok).toBe(true);
    if (second.ok) {
      expect(second.token).toBe("ghs_2");
      expect(second.cached).toBe(false);
    }
  });
});

describe("checkRateLimit", () => {
  test("passes the token through to the fetchRateLimit dep and returns its result", async () => {
    const fetchMock = mock(async (token: string) => (token === "tok" ? 4999 : null));
    setGithubAppAuthDeps({ fetchRateLimit: fetchMock });

    expect(await checkRateLimit("tok")).toBe(4999);
    expect(fetchMock).toHaveBeenCalledWith("tok");
  });
});
