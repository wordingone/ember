// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// bridge-auth.ts — WorkSecret decoding, SDK URL construction, JWT helpers, and token refresh.

// ---- WorkSecret decoding ----

export interface WorkSecretPayload {
  version: number;
  session_ingress_token: string;
  api_base_url: string;
  sources?: unknown[];
  auth?: unknown[];
  [key: string]: unknown;
}

/**
 * Decodes a base64url-encoded WorkSecret and validates its structure.
 * Throws when the version is not 1, or required fields are absent.
 */
export function decodeWorkSecret(secret: string): WorkSecretPayload {
  // Base64url → base64 → JSON
  const b64 = secret.replace(/-/g, '+').replace(/_/g, '/');
  const padded = b64 + '=='.slice(0, (4 - (b64.length % 4)) % 4);

  let obj: Record<string, unknown>;
  try {
    obj = JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    throw new Error('WorkSecret: failed to decode or parse payload');
  }

  if (obj['version'] !== 1) {
    throw new Error(`WorkSecret: unsupported version ${String(obj['version'])}`);
  }

  if (!obj['session_ingress_token']) {
    throw new Error('WorkSecret: missing required field "session_ingress_token"');
  }

  if (!obj['api_base_url']) {
    throw new Error('WorkSecret: missing required field "api_base_url"');
  }

  return obj as WorkSecretPayload;
}

// ---- SDK URL construction ----

/**
 * Builds the WebSocket URL for the session ingress connection.
 *
 * - localhost → ws://
 * - all other hosts → wss:// (regardless of http/https in apiBaseUrl)
 */
export function buildSdkUrl(apiBaseUrl: string, token: string): string {
  const parsed = new URL(apiBaseUrl);
  const isLocal = parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1';
  const wsScheme = isLocal ? 'ws' : 'wss';
  return `${wsScheme}://${parsed.host}/v1/session_ingress/ws/${token}`;
}

/**
 * Builds the CCRv2 HTTP URL for code session access.
 * Format: {apiBaseUrl}/v1/code/sessions/{sessionId}
 */
export function buildCCRv2SdkUrl(apiBaseUrl: string, sessionId: string): string {
  const base = apiBaseUrl.replace(/\/$/, '');
  return `${base}/v1/code/sessions/${sessionId}`;
}

// ---- JWT helpers ----

/**
 * Decodes the payload of a JWT (header.payload.sig format) without verifying the signature.
 * Returns the parsed payload object, or null on malformed input.
 */
export function decodeJwtPayload(jwt: string): Record<string, unknown> | null {
  const parts = jwt.split('.');
  if (parts.length !== 3) return null;
  try {
    const b64 = (parts[1] ?? '').replace(/-/g, '+').replace(/_/g, '/');
    const json = atob(b64 + '=='.slice(0, (4 - (b64.length % 4)) % 4));
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Extracts the `exp` claim (seconds since epoch) from a JWT.
 * Returns null when the claim is absent or the JWT is malformed.
 */
export function decodeJwtExpiry(jwt: string): number | null {
  const payload = decodeJwtPayload(jwt);
  if (!payload) return null;
  const exp = payload['exp'];
  return typeof exp === 'number' ? exp : null;
}

// ---- Token refresh scheduler ----

const MAX_RETRY_ATTEMPTS = 3;

interface RefreshSchedulerOpts {
  getAccessToken: () => Promise<string>;
  onRefresh: (sessionId: string, token: string) => void;
  label: string;
  refreshBufferMs: number;
}

interface RefreshState {
  timer: ReturnType<typeof setTimeout> | null;
  consecutiveFailures: number;
}

interface TokenRefreshScheduler {
  schedule(sessionId: string, jwt: string): void;
  cancel(sessionId: string): void;
  cancelAll(): void;
}

/**
 * Creates a scheduler that fires token refreshes before each JWT's expiry.
 *
 * - Fires at (exp * 1000 - refreshBufferMs)
 * - Stops after MAX_RETRY_ATTEMPTS consecutive failures for a session
 * - cancel(sessionId) prevents pending refreshes from firing
 */
export function createTokenRefreshScheduler(
  opts: RefreshSchedulerOpts,
): TokenRefreshScheduler {
  const sessions = new Map<string, RefreshState>();

  function schedule(sessionId: string, jwt: string): void {
    cancel(sessionId);

    const exp = decodeJwtExpiry(jwt);
    const now = Date.now();
    // When exp is absent or already past, fire after a minimal delay
    const fireAt = exp !== null ? exp * 1000 - opts.refreshBufferMs : now;
    const delay = Math.max(0, fireAt - now);

    const state: RefreshState = { timer: null, consecutiveFailures: 0 };
    sessions.set(sessionId, state);

    state.timer = setTimeout(async () => {
      const s = sessions.get(sessionId);
      if (!s) return;

      if (s.consecutiveFailures >= MAX_RETRY_ATTEMPTS) return;

      try {
        const token = await opts.getAccessToken();
        s.consecutiveFailures = 0;
        opts.onRefresh(sessionId, token);
      } catch {
        s.consecutiveFailures += 1;
      }
    }, delay);
  }

  function cancel(sessionId: string): void {
    const timer = sessions.get(sessionId)?.timer;
    if (timer !== null && timer !== undefined) {
      clearTimeout(timer);
    }
    sessions.delete(sessionId);
  }

  function cancelAll(): void {
    for (const [id] of sessions) cancel(id);
  }

  return { schedule, cancel, cancelAll };
}

// ---- Session ID compatibility shim ----

let _cseShimGate: () => boolean = () => false;

/** Controls whether the cse_ ↔ session_ session ID shim is active. */
export function setCseShimGate(gate: () => boolean): void {
  _cseShimGate = gate;
}

/**
 * Returns true when both IDs refer to the same session.
 * Compares the body after the first underscore; both must have ≥ 4 body characters.
 * Gate must be enabled via setCseShimGate.
 */
export function sameSessionId(id1: string, id2: string): boolean {
  if (!_cseShimGate()) return id1 === id2;

  const body1 = id1.indexOf('_') !== -1 ? id1.slice(id1.indexOf('_') + 1) : id1;
  const body2 = id2.indexOf('_') !== -1 ? id2.slice(id2.indexOf('_') + 1) : id2;

  if (body1.length < 4 || body2.length < 4) return false;
  return body1 === body2;
}

/**
 * Converts a cse_-prefixed session ID to the session_ compat format.
 * No-op when the ID already uses the session_ prefix.
 */
export function toCompatSessionId(id: string): string {
  if (!_cseShimGate()) return id;
  if (id.startsWith('cse_')) return 'session_' + id.slice(4);
  return id;
}

/**
 * Converts a session_-prefixed session ID back to the cse_ infra format.
 * No-op when the ID already uses the cse_ prefix.
 */
export function toInfraSessionId(id: string): string {
  if (id.startsWith('session_')) return 'cse_' + id.slice(8);
  return id;
}

// ---- Trusted device token ----

let _trustedDeviceToken: string | null = null;

/** Clears the cached trusted device token. */
export function clearTrustedDeviceToken(): void {
  _trustedDeviceToken = null;
}

// Suppress unused-variable lint
void _trustedDeviceToken;
