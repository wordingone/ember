// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// mcp-auth.ts — MCP OAuth PKCE flow, token management, and XAA (cross-account auth).

import { createHash, randomBytes } from 'crypto';

// ---- Types ----

export type FetchLike = (url: string | URL | Request, init?: RequestInit) => Promise<Response>;

export interface OAuthTokens {
  access_token: string;
  expires_in?: number;
  acquired_at?: number;
}

// ---- PKCE helpers ----

/**
 * Generates a cryptographically random code verifier (base64url, 32 bytes).
 */
export function generateCodeVerifier(): string {
  return randomBytes(32).toString('base64url');
}

/**
 * Derives the PKCE S256 code challenge from a verifier.
 * Returns a base64url-encoded SHA-256 hash with no padding characters.
 */
export function deriveCodeChallenge(verifier: string): string {
  return createHash('sha256').update(verifier).digest('base64url');
}

// ---- CSRF state ----

/** Generates a random CSRF state token. */
export function generateCsrfState(): string {
  return randomBytes(16).toString('hex');
}

/** Returns true when `received` exactly matches the expected `state` (case-sensitive). */
export function validateCallbackState(state: string, received: string): boolean {
  return state === received;
}

// ---- Callback port selection ----

const PORT_MIN = 39152;
const PORT_MAX = 65535;

/**
 * Returns the OAuth callback port.
 * Reads MCP_OAUTH_CALLBACK_PORT when set; otherwise chooses a random port in [39152, 65535].
 */
export function selectOAuthCallbackPort(): number {
  const envPort = process.env['MCP_OAUTH_CALLBACK_PORT'];
  if (envPort) {
    const parsed = parseInt(envPort, 10);
    if (!isNaN(parsed)) return parsed;
  }
  return PORT_MIN + Math.floor(Math.random() * (PORT_MAX - PORT_MIN + 1));
}

// ---- Token expiry ----

const TOKEN_EXPIRY_BUFFER_SECS = 300; // 5 minutes

/**
 * Returns true when the token will expire within the next 5 minutes.
 * Returns false when expires_in or acquired_at are absent.
 */
export function isTokenExpiringSoon(tokens: OAuthTokens): boolean {
  if (tokens.expires_in === undefined || tokens.acquired_at === undefined) return false;
  const expiresAt = tokens.acquired_at + tokens.expires_in * 1000;
  return expiresAt - Date.now() < TOKEN_EXPIRY_BUFFER_SECS * 1000;
}

// ---- Official URL check ----

/**
 * Returns true when `url` is an official Ember MCP endpoint (*.ember.ai or ember.ai).
 */
export function isOfficialEmberMcpUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname;
    return host === 'ember.ai' || host.endsWith('.ember.ai');
  } catch {
    return false;
  }
}

// ---- EmberAuthProvider ----

interface EmberAuthProviderOpts {
  tokenEndpoint: string;
  clientId: string;
  authorizationEndpoint: string;
  revocationEndpoint?: string;
}

interface PkceResult {
  verifier: string;
  challenge: string;
}

interface ExchangeCodeOpts {
  code: string;
  verifier: string;
  port: number;
  fetchFn?: FetchLike;
}

interface BuildAuthUrlOpts {
  challenge: string;
  state: string;
  port: number;
}

/**
 * Handles the OAuth 2.0 + PKCE flow for MCP authentication.
 */
export class EmberAuthProvider {
  private readonly opts: EmberAuthProviderOpts;
  private _storedTokens: OAuthTokens | null = null;

  constructor(opts: EmberAuthProviderOpts) {
    this.opts = opts;
  }

  /** Generates a PKCE verifier + S256 challenge pair. */
  generatePkce(): PkceResult {
    const verifier = generateCodeVerifier();
    const challenge = deriveCodeChallenge(verifier);
    return { verifier, challenge };
  }

  /**
   * Exchanges an authorization code for tokens.
   * The 15-second timeout is enforced via AbortController.
   */
  async exchangeCode(opts: ExchangeCodeOpts): Promise<OAuthTokens> {
    const fetchFn = (opts.fetchFn ?? fetch) as typeof fetch;
    const redirectUri = `http://localhost:${opts.port}/callback`;

    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code: opts.code,
      code_verifier: opts.verifier,
      redirect_uri: redirectUri,
      client_id: this.opts.clientId,
    });

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);

    try {
      const resp = await fetchFn(this.opts.tokenEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
        signal: controller.signal,
      });
      if (!resp.ok) throw new Error(`Token exchange failed: ${resp.status}`);
      const tokens = (await resp.json()) as OAuthTokens;
      tokens.acquired_at = Date.now();
      this._storedTokens = tokens;
      return tokens;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Builds the OAuth authorization URL with required PKCE + CSRF parameters.
   * Includes: response_type, client_id, code_challenge, code_challenge_method=S256,
   * state, redirect_uri.
   */
  buildAuthUrl(opts: BuildAuthUrlOpts): string {
    const redirectUri = `http://localhost:${opts.port}/callback`;
    const url = new URL(this.opts.authorizationEndpoint);
    url.searchParams.set('response_type', 'code');
    url.searchParams.set('client_id', this.opts.clientId);
    url.searchParams.set('code_challenge', opts.challenge);
    url.searchParams.set('code_challenge_method', 'S256');
    url.searchParams.set('state', opts.state);
    url.searchParams.set('redirect_uri', redirectUri);
    return url.toString();
  }

  /**
   * Revokes the stored access token via RFC 7009.
   * POST body: token=..., token_type_hint=access_token.
   */
  async revokeOAuthToken(fetchFn?: FetchLike): Promise<void> {
    const endpoint = this.opts.revocationEndpoint;
    if (!endpoint || !this._storedTokens) return;

    const doFetch = (fetchFn ?? fetch) as typeof fetch;
    const body = new URLSearchParams({
      token: this._storedTokens.access_token,
      token_type_hint: 'access_token',
    });

    await doFetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });
  }

  /** Stores tokens without an exchange (e.g., in tests). */
  setStoredTokens(tokens: OAuthTokens): void {
    this._storedTokens = tokens;
  }
}

// ---- XAA IdP token cache ----

interface CachedIdpToken {
  token: string;
  expiresAt: number; // epoch ms
}

let _xaaCache: CachedIdpToken | null = null;
const IDP_TOKEN_BUFFER_SECS = 60;

/** Returns the cached IdP token, or null when absent or expired. */
export function getCachedIdpIdToken(): string | null {
  if (!_xaaCache) return null;
  if (Date.now() >= _xaaCache.expiresAt) return null;
  return _xaaCache.token;
}

/**
 * Caches an IdP token with a 60-second expiry buffer.
 * A token with expires_in=0 is immediately considered expired.
 */
export function setCachedIdpIdToken(token: string, expiresIn: number): void {
  const expiresAt = Date.now() + (expiresIn - IDP_TOKEN_BUFFER_SECS) * 1000;
  _xaaCache = { token, expiresAt };
}

/** Clears the XAA cache (IdP token). */
export function clearXaaCache(): void {
  _xaaCache = null;
}

// ---- MCP XAA auth flow ----

interface MXaaAuthOpts {
  resourceUrl: string;
  fetchFn?: FetchLike;
}

interface MXaaAuthResult {
  accessToken: string;
  idpToken: string;
}

/**
 * Performs the full MCP cross-account auth (XAA) flow.
 *
 * Steps:
 * 1. Fetch {resourceUrl}/.well-known/oauth-protected-resource → authorization_servers[0]
 * 2. Fetch {authServer}/.well-known/oauth-authorization-server → idp_token_endpoint + token_endpoint
 * 3. Fetch IdP token (skipped when cached)
 * 4. Exchange IdP token for resource access token
 *
 * Caches the IdP token for (expires_in - 60s) seconds.
 */
export async function performMCPXaaAuth(opts: MXaaAuthOpts): Promise<MXaaAuthResult> {
  const fetchFn = opts.fetchFn ?? fetch;

  // Step 1: discover authorization server
  const resourceUrl = opts.resourceUrl.replace(/\/$/, '');
  const protectedResourceResp = await fetchFn(
    `${resourceUrl}/.well-known/oauth-protected-resource`,
  );
  const protectedResource = (await protectedResourceResp.json()) as Record<string, unknown>;
  const authServers = protectedResource['authorization_servers'] as string[];
  const authServer = (authServers[0] ?? '').replace(/\/$/, '');

  // Step 2: discover endpoints
  const asMetaResp = await fetchFn(
    `${authServer}/.well-known/oauth-authorization-server`,
  );
  const asMeta = (await asMetaResp.json()) as Record<string, unknown>;
  const tokenEndpoint = asMeta['token_endpoint'] as string;
  const idpTokenEndpoint = asMeta['idp_token_endpoint'] as string;

  // Step 3: acquire IdP token (use cache when available)
  let idpToken = getCachedIdpIdToken();

  if (!idpToken) {
    const idpResp = await fetchFn(idpTokenEndpoint);
    const idpData = (await idpResp.json()) as Record<string, unknown>;
    idpToken = idpData['id_token'] as string;
    const expiresIn = (idpData['expires_in'] as number | undefined) ?? 3600;
    setCachedIdpIdToken(idpToken, expiresIn);
  }

  // Step 4: exchange IdP token for resource access token
  const tokenResp = await fetchFn(tokenEndpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id_token: idpToken }),
  });
  const tokenData = (await tokenResp.json()) as Record<string, unknown>;
  const accessToken = tokenData['access_token'] as string;

  return { accessToken, idpToken };
}
