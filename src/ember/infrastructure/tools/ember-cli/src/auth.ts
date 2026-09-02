// auth.ts — token source detection, API key resolution, and OAuth session management.

// ---- AuthError ----

/** Thrown when no valid credentials are available or a refresh fails. */
export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AuthError';
  }
}

// ---- OAuthSession ----

export interface OAuthSession {
  accessToken: string;
  refreshToken: string;
  expiresAt: number; // Unix epoch ms
  scopes: string[];
}

// ---- In-memory OAuth session store ----

let _oauthSession: OAuthSession | null = null;

/** Stores the OAuth session in memory (replaces any existing session). */
export async function storeOAuthSession(session: OAuthSession): Promise<void> {
  _oauthSession = session;
}

/** Clears the in-memory OAuth session. */
export async function clearOAuthSession(): Promise<void> {
  _oauthSession = null;
}

// ---- Token source detection ----

export type AuthTokenSource = 'bedrock' | 'vertex' | 'local';

/**
 * Determines the token source based on the current environment variables.
 * Priority: bedrock > vertex > local.
 */
export function getAuthTokenSource(): AuthTokenSource {
  // Bedrock: AWS credentials
  if (process.env['AWS_ACCESS_KEY_ID'] || process.env['AWS_BEDROCK_BASE_URL']) {
    return 'bedrock';
  }

  // Vertex: Google credentials
  if (
    process.env['GOOGLE_APPLICATION_CREDENTIALS'] ||
    process.env['GOOGLE_CLOUD_PROJECT'] ||
    process.env['CLOUDSDK_CORE_PROJECT']
  ) {
    return 'vertex';
  }

  return 'local';
}

// ---- API key resolution ----

/**
 * Returns the API key for direct API calls.
 *
 * - Reads EMBER_API_KEY (trimmed) when set; EMBER_API_KEY_HELPER is bypassed
 * - Throws AuthError when no credentials are available
 */
export async function getApiKey(): Promise<string> {
  const directKey = process.env['EMBER_API_KEY']?.trim();
  if (directKey) return directKey;

  // No direct key; throw — callers must handle the OAuth path separately
  throw new AuthError('No API key available. Set EMBER_API_KEY or authenticate via OAuth.');
}

// ---- OAuth token refresh ----

const REFRESH_THRESHOLD_MS = 5 * 60 * 1000; // refresh when < 5 minutes remaining
const OAUTH_TOKEN_ENDPOINT = 'https://api.ember.ai/v1/oauth/token';

export interface GetOrRefreshOAuthTokenOpts {
  fetchFn?: typeof fetch;
}

/**
 * Returns the current access token, refreshing it proactively when it expires
 * within the next 5 minutes.
 *
 * Throws AuthError when:
 * - no session exists
 * - the token needs refresh but the refresh call fails
 */
export async function getOrRefreshOAuthToken(
  opts?: GetOrRefreshOAuthTokenOpts,
): Promise<string> {
  const session = _oauthSession;
  if (!session) {
    throw new AuthError('No OAuth session. Please authenticate first.');
  }

  const now = Date.now();
  const timeRemaining = session.expiresAt - now;

  if (timeRemaining > REFRESH_THRESHOLD_MS) {
    // Token is fresh; return it directly
    return session.accessToken;
  }

  // Token is near expiry; attempt refresh
  const fetchFn = opts?.fetchFn ?? fetch;

  let resp: Response;
  try {
    resp = await fetchFn(OAUTH_TOKEN_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        grant_type: 'refresh_token',
        refresh_token: session.refreshToken,
      }),
    });
  } catch (err) {
    throw new AuthError(`Token refresh request failed: ${String(err)}`);
  }

  if (!resp.ok) {
    throw new AuthError(`Token refresh failed with status ${resp.status}`);
  }

  const data = (await resp.json()) as Record<string, unknown>;
  const newToken = data['access_token'] as string | undefined;
  if (!newToken) {
    throw new AuthError('Token refresh response did not include an access_token');
  }

  const expiresIn = (data['expires_in'] as number | undefined) ?? 3600;
  const newSession: OAuthSession = {
    accessToken: newToken,
    refreshToken: session.refreshToken,
    expiresAt: Date.now() + expiresIn * 1000,
    scopes: session.scopes,
  };
  _oauthSession = newSession;

  return newToken;
}

// ---- Subscription type ----

export type SubscriptionType = 'free' | 'pro' | 'max' | 'team_premium' | 'enterprise';

const KNOWN_TIERS = new Set<string>(['pro', 'max', 'team_premium', 'enterprise']);

/**
 * Resolves a raw subscription tier string to a typed SubscriptionType.
 * Unknown or absent tiers resolve to 'free'. Comparison is case-insensitive.
 */
export function resolveSubscriptionType(tier?: string): SubscriptionType {
  if (!tier) return 'free';
  const lower = tier.toLowerCase();
  if (KNOWN_TIERS.has(lower)) return lower as SubscriptionType;
  return 'free';
}
