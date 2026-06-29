import { describe, expect, test, beforeEach, afterEach } from 'bun:test';
import {
  getAuthTokenSource,
  getApiKey,
  getOrRefreshOAuthToken,
  storeOAuthSession,
  clearOAuthSession,
  resolveSubscriptionType,
  AuthError,
  type OAuthSession,
} from './auth';

// ---------------------------------------------------------------------------
// getAuthTokenSource
// ---------------------------------------------------------------------------

describe('getAuthTokenSource', () => {
  afterEach(() => {
    delete process.env['AWS_ACCESS_KEY_ID'];
    delete process.env['GOOGLE_APPLICATION_CREDENTIALS'];
    delete process.env['AWS_BEDROCK_BASE_URL'];
  });

  test('AC1: AWS_ACCESS_KEY_ID set → bedrock', () => {
    process.env['AWS_ACCESS_KEY_ID'] = 'AKIAIOSFODNN7EXAMPLE';
    expect(getAuthTokenSource()).toBe('bedrock');
  });

  test('AWS_BEDROCK_BASE_URL set → bedrock', () => {
    process.env['AWS_BEDROCK_BASE_URL'] = 'https://bedrock.example.com';
    expect(getAuthTokenSource()).toBe('bedrock');
  });

  test('GOOGLE_APPLICATION_CREDENTIALS set → vertex', () => {
    process.env['GOOGLE_APPLICATION_CREDENTIALS'] = '/path/to/creds.json';
    expect(getAuthTokenSource()).toBe('vertex');
  });

  test('AC6: no auth env vars → local', () => {
    delete process.env['AWS_ACCESS_KEY_ID'];
    delete process.env['AWS_BEDROCK_BASE_URL'];
    delete process.env['GOOGLE_APPLICATION_CREDENTIALS'];
    delete process.env['GOOGLE_CLOUD_PROJECT'];
    delete process.env['CLOUDSDK_CORE_PROJECT'];
    expect(getAuthTokenSource()).toBe('local');
  });

  test('Bedrock has higher priority than Vertex', () => {
    process.env['AWS_ACCESS_KEY_ID'] = 'key';
    process.env['GOOGLE_APPLICATION_CREDENTIALS'] = '/creds.json';
    expect(getAuthTokenSource()).toBe('bedrock');
  });
});

// ---------------------------------------------------------------------------
// getApiKey
// ---------------------------------------------------------------------------

describe('getApiKey', () => {
  afterEach(() => {
    delete process.env['EMBER_API_KEY'];
    delete process.env['EMBER_API_KEY_HELPER'];
  });

  test('AC2: EMBER_API_KEY set → returns it without invoking helper', async () => {
    process.env['EMBER_API_KEY'] = 'sk-direct-key';
    const key = await getApiKey();
    expect(key).toBe('sk-direct-key');
  });

  test('trims whitespace from EMBER_API_KEY', async () => {
    process.env['EMBER_API_KEY'] = '  sk-trimmed  ';
    const key = await getApiKey();
    expect(key).toBe('sk-trimmed');
  });

  test('throws AuthError when no credentials available', async () => {
    delete process.env['EMBER_API_KEY'];
    delete process.env['EMBER_API_KEY_HELPER'];
    // Ensure no OAuth session
    await clearOAuthSession();
    await expect(getApiKey()).rejects.toBeInstanceOf(AuthError);
  });
});

// ---------------------------------------------------------------------------
// OAuth token refresh
// ---------------------------------------------------------------------------

describe('getOrRefreshOAuthToken', () => {
  afterEach(async () => {
    await clearOAuthSession();
  });

  test('returns current token when not near expiry', async () => {
    const session: OAuthSession = {
      accessToken: 'tok-valid',
      refreshToken: 'refresh-valid',
      expiresAt: Date.now() + 60 * 60 * 1000, // 1 hour from now
      scopes: ['read'],
    };
    await storeOAuthSession(session);

    const token = await getOrRefreshOAuthToken();
    expect(token).toBe('tok-valid');
  });

  test('AC4: token expiring in 2 min triggers refresh', async () => {
    const session: OAuthSession = {
      accessToken: 'tok-old',
      refreshToken: 'refresh-ok',
      expiresAt: Date.now() + 2 * 60 * 1000, // 2 minutes — within 5 min window
      scopes: ['read'],
    };
    await storeOAuthSession(session);

    // Mock fetch that returns a new token
    // Cast: mock lacks the 'preconnect' property required by Bun's typeof fetch
    const mockFetch = (async (_url: unknown, _opts?: unknown) => {
      return new Response(
        JSON.stringify({ access_token: 'tok-new', expires_in: 3600 }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    }) as unknown as typeof fetch;

    const token = await getOrRefreshOAuthToken({ fetchFn: mockFetch });
    expect(token).toBe('tok-new');
  });

  test('AC5: refresh failure throws AuthError (does not return expired token)', async () => {
    const session: OAuthSession = {
      accessToken: 'tok-expired',
      refreshToken: 'bad-refresh',
      expiresAt: Date.now() + 60 * 1000, // 1 min — within window
      scopes: ['read'],
    };
    await storeOAuthSession(session);

    // Cast: mock lacks 'preconnect' required by Bun's typeof fetch
    const failingFetch = (async () => {
      return new Response('Unauthorized', { status: 401 });
    }) as unknown as typeof fetch;

    await expect(
      getOrRefreshOAuthToken({ fetchFn: failingFetch }),
    ).rejects.toBeInstanceOf(AuthError);
  });

  test('throws when no session exists', async () => {
    await clearOAuthSession();
    await expect(getOrRefreshOAuthToken()).rejects.toBeInstanceOf(AuthError);
  });
});

// ---------------------------------------------------------------------------
// resolveSubscriptionType
// ---------------------------------------------------------------------------

describe('resolveSubscriptionType', () => {
  test('no hint → free', () => {
    expect(resolveSubscriptionType()).toBe('free');
  });

  test('known tiers map correctly', () => {
    expect(resolveSubscriptionType('pro')).toBe('pro');
    expect(resolveSubscriptionType('max')).toBe('max');
    expect(resolveSubscriptionType('team_premium')).toBe('team_premium');
    expect(resolveSubscriptionType('enterprise')).toBe('enterprise');
  });

  test('unknown tier → free', () => {
    expect(resolveSubscriptionType('unknown-tier')).toBe('free');
  });

  test('case-insensitive', () => {
    expect(resolveSubscriptionType('PRO')).toBe('pro');
    expect(resolveSubscriptionType('Max')).toBe('max');
  });
});
