// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// github-app-auth.ts — GitHub App identity: JWT mint + installation token
// exchange, cached with expiry and auto-refresh (ember issue #507).
//
// Credential source is env-only (never a personal PAT, never committed):
//   EMBER_GH_APP_ID            — the GitHub App's numeric ID
//   EMBER_GH_INSTALLATION_ID   — the installation ID on the target repo
//   EMBER_GH_PRIVATE_KEY_PATH  — path to the App's PEM private key (the key
//                                file itself lives outside the repo)
//
// The App installation is provisioned on a separate leg (#507 "out of
// scope") -- this module must be safe to import and call before that leg
// lands: every credential-absent or credential-bad path degrades to a typed
// failure result, never a thrown exception and never a retry storm.

import fs from "node:fs";
import crypto from "node:crypto";

export const GITHUB_API_BASE = "https://api.github.com";

export const SETUP_POINTER =
  "GitHub App identity is NOT_CONFIGURED -- set EMBER_GH_APP_ID, " +
  "EMBER_GH_INSTALLATION_ID, and EMBER_GH_PRIVATE_KEY_PATH (path to the App's " +
  "PEM private key, kept outside the repo) to enable ember's native GitHub " +
  "capability. See ember issue #507.";

// ---------------------------------------------------------------------------
// Credentials
// ---------------------------------------------------------------------------

export interface GithubAppCredentialsRaw {
  appId: string | undefined;
  installationId: string | undefined;
  privateKeyPath: string | undefined;
}

export interface GithubAppCredentials {
  appId: string;
  installationId: string;
  privateKeyPem: string;
}

export type CredentialsResult =
  | { ok: true; creds: GithubAppCredentials }
  | { ok: false; missing: string[]; detail: string };

// ---------------------------------------------------------------------------
// Deps (DI) -- same shape as install-github-app.ts / config-tool.ts
// ---------------------------------------------------------------------------

export interface GithubAppAuthDeps {
  readEnv: () => GithubAppCredentialsRaw;
  readPrivateKeyFile: (path: string) => string;
  now: () => number;
  signJwt: (appId: string, privateKeyPem: string, nowMs: number) => string;
  fetchInstallationToken: (
    installationId: string,
    jwt: string,
  ) => Promise<{ token: string; expiresAt: string }>;
  fetchRateLimit: (token: string) => Promise<number | null>;
}

function defaultReadEnv(): GithubAppCredentialsRaw {
  return {
    appId: process.env["EMBER_GH_APP_ID"],
    installationId: process.env["EMBER_GH_INSTALLATION_ID"],
    privateKeyPath: process.env["EMBER_GH_PRIVATE_KEY_PATH"],
  };
}

function defaultReadPrivateKeyFile(p: string): string {
  return fs.readFileSync(p, "utf8");
}

/** Signs a GitHub App JWT (RS256; iat/exp/iss per GitHub's App-auth contract).
 *  iat is backdated 60s for clock drift; exp is capped at 9 minutes, safely
 *  under GitHub's 10-minute ceiling for App JWTs. */
export function signAppJwt(appId: string, privateKeyPem: string, nowMs: number): string {
  const nowSec = Math.floor(nowMs / 1000);
  const header = { alg: "RS256", typ: "JWT" };
  const payload = { iat: nowSec - 60, exp: nowSec + 9 * 60, iss: appId };

  const b64url = (obj: unknown): string => Buffer.from(JSON.stringify(obj)).toString("base64url");
  const signingInput = `${b64url(header)}.${b64url(payload)}`;
  const signature = crypto.sign("RSA-SHA256", Buffer.from(signingInput), { key: privateKeyPem });
  return `${signingInput}.${signature.toString("base64url")}`;
}

async function defaultFetchInstallationToken(
  installationId: string,
  jwt: string,
): Promise<{ token: string; expiresAt: string }> {
  const res = await fetch(`${GITHUB_API_BASE}/app/installations/${installationId}/access_tokens`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${jwt}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`installation token exchange returned ${res.status}: ${body}`);
  }
  const data = (await res.json()) as { token?: string; expires_at?: string };
  if (!data.token || !data.expires_at) {
    throw new Error("installation token response missing token/expires_at");
  }
  return { token: data.token, expiresAt: data.expires_at };
}

async function defaultFetchRateLimit(token: string): Promise<number | null> {
  try {
    const res = await fetch(`${GITHUB_API_BASE}/rate_limit`, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { resources?: { core?: { remaining?: number } } };
    return data.resources?.core?.remaining ?? null;
  } catch {
    return null;
  }
}

const DEFAULT_DEPS: GithubAppAuthDeps = {
  readEnv: defaultReadEnv,
  readPrivateKeyFile: defaultReadPrivateKeyFile,
  now: () => Date.now(),
  signJwt: signAppJwt,
  fetchInstallationToken: defaultFetchInstallationToken,
  fetchRateLimit: defaultFetchRateLimit,
};

let deps: GithubAppAuthDeps = { ...DEFAULT_DEPS };

export function setGithubAppAuthDeps(overrides: Partial<GithubAppAuthDeps>): void {
  deps = { ...deps, ...overrides };
}

export function _resetGithubAppAuthDepsForTests(): void {
  deps = { ...DEFAULT_DEPS };
  cachedToken = null;
}

// ---------------------------------------------------------------------------
// Credential resolution
// ---------------------------------------------------------------------------

export function resolveCredentials(): CredentialsResult {
  const raw = deps.readEnv();
  const missing: string[] = [];
  if (!raw.appId) missing.push("EMBER_GH_APP_ID");
  if (!raw.installationId) missing.push("EMBER_GH_INSTALLATION_ID");
  if (!raw.privateKeyPath) missing.push("EMBER_GH_PRIVATE_KEY_PATH");

  if (missing.length > 0) {
    return { ok: false, missing, detail: SETUP_POINTER };
  }

  let privateKeyPem: string;
  try {
    privateKeyPem = deps.readPrivateKeyFile(raw.privateKeyPath!);
  } catch (err) {
    return {
      ok: false,
      missing: ["EMBER_GH_PRIVATE_KEY_PATH"],
      detail: `${SETUP_POINTER} (could not read key file: ${err instanceof Error ? err.message : String(err)})`,
    };
  }

  return { ok: true, creds: { appId: raw.appId!, installationId: raw.installationId!, privateKeyPem } };
}

// ---------------------------------------------------------------------------
// Stage primitives -- exported individually so the doctor can walk the ladder
// and report exactly how far it got, instead of collapsing every failure
// into one opaque state.
// ---------------------------------------------------------------------------

export function mintJwt(
  creds: GithubAppCredentials,
  nowMs: number,
): { ok: true; jwt: string } | { ok: false; detail: string } {
  try {
    return { ok: true, jwt: deps.signJwt(creds.appId, creds.privateKeyPem, nowMs) };
  } catch (err) {
    return { ok: false, detail: `JWT signing failed: ${err instanceof Error ? err.message : String(err)}` };
  }
}

export async function exchangeInstallationToken(
  installationId: string,
  jwt: string,
): Promise<{ ok: true; token: string; expiresAt: string } | { ok: false; detail: string }> {
  try {
    const { token, expiresAt } = await deps.fetchInstallationToken(installationId, jwt);
    return { ok: true, token, expiresAt };
  } catch (err) {
    return {
      ok: false,
      detail: `installation token exchange failed: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

export function checkRateLimit(token: string): Promise<number | null> {
  return deps.fetchRateLimit(token);
}

// ---------------------------------------------------------------------------
// Installation token cache (module-level, single installation)
// ---------------------------------------------------------------------------

interface CachedToken {
  token: string;
  expiresAtMs: number;
}

let cachedToken: CachedToken | null = null;
const REFRESH_BUFFER_MS = 60_000;

export type CapabilityState = "NOT_CONFIGURED" | "JWT_MINT_FAILED" | "EXCHANGE_FAILED" | "INSTALLATION_TOKEN_OK";

export type TokenResult =
  | { ok: true; state: "INSTALLATION_TOKEN_OK"; token: string; expiresAt: string; cached: boolean }
  | { ok: false; state: Exclude<CapabilityState, "INSTALLATION_TOKEN_OK">; detail: string };

/** Returns a valid installation access token, minting/exchanging/refreshing
 *  as needed. Never throws -- every failure degrades to a typed result the
 *  caller (tool surface, doctor) can render without crashing. */
export async function getInstallationToken(): Promise<TokenResult> {
  const resolved = resolveCredentials();
  if (!resolved.ok) {
    return { ok: false, state: "NOT_CONFIGURED", detail: resolved.detail };
  }

  const nowMs = deps.now();
  if (cachedToken && cachedToken.expiresAtMs - REFRESH_BUFFER_MS > nowMs) {
    return {
      ok: true,
      state: "INSTALLATION_TOKEN_OK",
      token: cachedToken.token,
      expiresAt: new Date(cachedToken.expiresAtMs).toISOString(),
      cached: true,
    };
  }

  const jwtResult = mintJwt(resolved.creds, nowMs);
  if (!jwtResult.ok) {
    return { ok: false, state: "JWT_MINT_FAILED", detail: jwtResult.detail };
  }

  const exchangeResult = await exchangeInstallationToken(resolved.creds.installationId, jwtResult.jwt);
  if (!exchangeResult.ok) {
    return { ok: false, state: "EXCHANGE_FAILED", detail: exchangeResult.detail };
  }

  cachedToken = { token: exchangeResult.token, expiresAtMs: Date.parse(exchangeResult.expiresAt) };
  return {
    ok: true,
    state: "INSTALLATION_TOKEN_OK",
    token: exchangeResult.token,
    expiresAt: exchangeResult.expiresAt,
    cached: false,
  };
}

/** Test-only escape hatch -- also useful for a forced re-check. */
export function _clearTokenCacheForTests(): void {
  cachedToken = null;
}
