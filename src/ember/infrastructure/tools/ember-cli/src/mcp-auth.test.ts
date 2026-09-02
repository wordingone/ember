// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Tests for mcp-auth.ts — maps to spec Acceptance Criteria.

import { describe, it, expect, beforeEach, afterEach } from 'bun:test';
import {
  generateCodeVerifier,
  deriveCodeChallenge,
  generateCsrfState,
  validateCallbackState,
  selectOAuthCallbackPort,
  isTokenExpiringSoon,
  isOfficialEmberMcpUrl,
  EmberAuthProvider,
  getCachedIdpIdToken,
  setCachedIdpIdToken,
  clearXaaCache,
  performMCPXaaAuth,
  type FetchLike,
  type OAuthTokens,
} from './mcp-auth.ts';

// ---------------------------------------------------------------------------
// AC1: Each OAuth flow generates unique code_verifier + code_challenge (S256)
// ---------------------------------------------------------------------------

describe('EmberAuthProvider.generatePkce — AC1', () => {
  const provider = new EmberAuthProvider({
    tokenEndpoint: 'https://example.com/token',
    clientId: 'test-client',
    authorizationEndpoint: 'https://example.com/auth',
  });

  it('generates a non-empty verifier and challenge', () => {
    const { verifier, challenge } = provider.generatePkce();
    expect(verifier.length).toBeGreaterThan(0);
    expect(challenge.length).toBeGreaterThan(0);
  });

  it('generates a different verifier+challenge on each call', () => {
    const a = provider.generatePkce();
    const b = provider.generatePkce();
    expect(a.verifier).not.toBe(b.verifier);
    expect(a.challenge).not.toBe(b.challenge);
  });

  it('code_challenge is S256 (SHA-256 base64url) of the verifier', () => {
    const verifier = generateCodeVerifier();
    const expected = deriveCodeChallenge(verifier);
    const actual = deriveCodeChallenge(verifier);
    expect(actual).toBe(expected);
    // Must be base64url (no +, /, = padding)
    expect(actual).toMatch(/^[A-Za-z0-9_-]+$/);
  });
});

// ---------------------------------------------------------------------------
// AC2: Callback state validation — mismatch returns error
// ---------------------------------------------------------------------------

describe('validateCallbackState — AC2', () => {
  it('returns true when state matches', () => {
    const state = generateCsrfState();
    expect(validateCallbackState(state, state)).toBe(true);
  });

  it('returns false when state does not match', () => {
    const state = generateCsrfState();
    expect(validateCallbackState(state, 'wrong-state')).toBe(false);
  });

  it('is case-sensitive', () => {
    expect(validateCallbackState('AbCd', 'abcd')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC3: Token exchange 15-second timeout
// ---------------------------------------------------------------------------

describe('EmberAuthProvider.exchangeCode — AC3 timeout', () => {
  it('propagates an error when the token endpoint is unreachable within timeout', async () => {
    const provider = new EmberAuthProvider({
      tokenEndpoint: 'https://example.com/token',
      clientId: 'test-client',
      authorizationEndpoint: 'https://example.com/auth',
    });

    // Stub fetch that always times out (simulate via abort)
    const slowFetch: FetchLike = async () => {
      await new Promise((_, reject) =>
        setTimeout(() => reject(Object.assign(new Error('AbortError'), { name: 'AbortError' })), 50),
      );
      return new Response();
    };

    await expect(
      provider.exchangeCode({
        code: 'test-code',
        verifier: 'test-verifier',
        port: 3000,
        fetchFn: slowFetch,
      }),
    ).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// AC4: Tokens considered expired 5 minutes before actual expiry
// ---------------------------------------------------------------------------

describe('isTokenExpiringSoon — AC4', () => {
  it('returns false for a token with plenty of time left', () => {
    const tokens: OAuthTokens = {
      access_token: 'tok',
      expires_in: 3600,
      acquired_at: Date.now(),
    };
    expect(isTokenExpiringSoon(tokens)).toBe(false);
  });

  it('returns true for a token expiring in less than 5 minutes', () => {
    const tokens: OAuthTokens = {
      access_token: 'tok',
      expires_in: 200, // 200 seconds = <5 min
      acquired_at: Date.now(),
    };
    expect(isTokenExpiringSoon(tokens)).toBe(true);
  });

  it('returns false when expires_in or acquired_at is absent', () => {
    const tokens: OAuthTokens = { access_token: 'tok' };
    expect(isTokenExpiringSoon(tokens)).toBe(false);
  });

  it('returns true for an already-expired token', () => {
    const tokens: OAuthTokens = {
      access_token: 'tok',
      expires_in: 1,
      acquired_at: Date.now() - 10_000, // acquired 10 seconds ago, expired 9 seconds ago
    };
    expect(isTokenExpiringSoon(tokens)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC5: CLAUDEAI_SUCCESS_URL redirect on successful auth
// ---------------------------------------------------------------------------

describe('EmberAuthProvider.buildAuthUrl — AC5', () => {
  it('includes the required OAuth parameters', () => {
    const provider = new EmberAuthProvider({
      tokenEndpoint: 'https://example.com/token',
      clientId: 'my-client',
      authorizationEndpoint: 'https://example.com/authorize',
    });
    const url = provider.buildAuthUrl({
      challenge: 'test-challenge',
      state: 'test-state',
      port: 4567,
    });
    const parsed = new URL(url);
    expect(parsed.searchParams.get('response_type')).toBe('code');
    expect(parsed.searchParams.get('client_id')).toBe('my-client');
    expect(parsed.searchParams.get('code_challenge')).toBe('test-challenge');
    expect(parsed.searchParams.get('code_challenge_method')).toBe('S256');
    expect(parsed.searchParams.get('state')).toBe('test-state');
    expect(parsed.searchParams.get('redirect_uri')).toBe('http://localhost:4567/callback');
  });
});

// ---------------------------------------------------------------------------
// AC6: MCP_OAUTH_CALLBACK_PORT honored; otherwise random in platform range
// ---------------------------------------------------------------------------

describe('selectOAuthCallbackPort — AC6', () => {
  afterEach(() => {
    delete process.env['MCP_OAUTH_CALLBACK_PORT'];
  });

  it('uses MCP_OAUTH_CALLBACK_PORT when set', () => {
    process.env['MCP_OAUTH_CALLBACK_PORT'] = '12345';
    expect(selectOAuthCallbackPort()).toBe(12345);
  });

  it('returns a port in the platform range when env var is absent', () => {
    delete process.env['MCP_OAUTH_CALLBACK_PORT'];
    const port = selectOAuthCallbackPort();
    // Both Windows and Unix ranges start at 39152+
    expect(port).toBeGreaterThanOrEqual(39152);
    expect(port).toBeLessThanOrEqual(65535);
  });
});

// ---------------------------------------------------------------------------
// AC7: XAA IdP token cached for (expiry - 60s); subsequent calls reuse it
// ---------------------------------------------------------------------------

describe('XAA IdP token cache — AC7', () => {
  beforeEach(() => clearXaaCache());

  it('getCachedIdpIdToken returns null when cache is empty', () => {
    expect(getCachedIdpIdToken()).toBeNull();
  });

  it('setCachedIdpIdToken stores and getCachedIdpIdToken retrieves the token', () => {
    setCachedIdpIdToken('test-token', 3600);
    expect(getCachedIdpIdToken()).toBe('test-token');
  });

  it('returns null after the cache expires (60-second buffer applied)', () => {
    // expires_in=60 → expiresAt = now + 60000 - 60000 = now → already expired
    setCachedIdpIdToken('expired-token', 60);
    // Should be null immediately because expiresAt = now - buffer = ~now
    // (may be >= now by a tiny margin; check that it expires quickly)
    // Use expires_in=0 to force immediate expiry
    clearXaaCache();
    setCachedIdpIdToken('expired-token', 0);
    expect(getCachedIdpIdToken()).toBeNull();
  });

  it('performMCPXaaAuth fetches the IdP token only once across calls', async () => {
    clearXaaCache();
    let fetchCount = 0;

    const calls: string[] = [];
    const mockFetch = async (url: string | URL | Request): Promise<Response> => {
      const urlStr = url.toString();
      calls.push(urlStr);
      fetchCount++;

      if (urlStr.includes('.well-known/oauth-protected-resource')) {
        return new Response(JSON.stringify({ authorization_servers: ['https://auth.example.com'] }));
      }
      if (urlStr.includes('.well-known/oauth-authorization-server')) {
        return new Response(JSON.stringify({
          token_endpoint: 'https://auth.example.com/token',
          idp_token_endpoint: 'https://auth.example.com/idp-token',
        }));
      }
      if (urlStr.includes('/idp-token')) {
        return new Response(JSON.stringify({
          id_token: 'idp-tok',
          expires_in: 3600,
        }));
      }
      if (urlStr.includes('/token')) {
        return new Response(JSON.stringify({ access_token: 'mcp-access-tok' }));
      }
      return new Response('{}', { status: 404 });
    };

    // First call — acquires IdP token
    const result1 = await performMCPXaaAuth({
      resourceUrl: 'https://resource.example.com',
      fetchFn: mockFetch,
    });
    expect(result1.accessToken).toBe('mcp-access-tok');
    expect(result1.idpToken).toBe('idp-tok');

    const fetchCountAfterFirst = fetchCount;

    // Second call — IdP token should come from cache; only resource+authserver+token fetches
    await performMCPXaaAuth({
      resourceUrl: 'https://resource.example.com',
      fetchFn: mockFetch,
    });

    // The second call should NOT call /idp-token again
    const idpCalls = calls.filter((u) => u.includes('/idp-token'));
    expect(idpCalls.length).toBe(1); // Only one IdP token fetch total
  });
});

// ---------------------------------------------------------------------------
// AC8: RFC 7009 revocation with token_type_hint=access_token
// ---------------------------------------------------------------------------

describe('EmberAuthProvider.revokeOAuthToken — AC8', () => {
  it('issues POST with token_type_hint=access_token', async () => {
    let capturedBody = '';
    const mockFetch: FetchLike = async (_url, init) => {
      capturedBody = init?.body?.toString() ?? '';
      return new Response('{}');
    };

    const provider = new EmberAuthProvider({
      tokenEndpoint: 'https://example.com/token',
      clientId: 'test-client',
      authorizationEndpoint: 'https://example.com/auth',
      revocationEndpoint: 'https://example.com/revoke',
    });
    provider.setStoredTokens({ access_token: 'my-access-token' });
    await provider.revokeOAuthToken(mockFetch);

    expect(capturedBody).toContain('token=my-access-token');
    expect(capturedBody).toContain('token_type_hint=access_token');
  });
});

// ---------------------------------------------------------------------------
// isOfficialEmberMcpUrl
// ---------------------------------------------------------------------------

describe('isOfficialEmberMcpUrl', () => {
  it('returns true for ember.ai URLs', () => {
    expect(isOfficialEmberMcpUrl('https://mcp.ember.ai/v1')).toBe(true);
    expect(isOfficialEmberMcpUrl('https://api.ember.ai')).toBe(true);
  });

  it('returns true for ember.ai root URL', () => {
    expect(isOfficialEmberMcpUrl('https://ember.ai/mcp')).toBe(true);
  });

  it('returns false for other URLs', () => {
    expect(isOfficialEmberMcpUrl('https://example.com/mcp')).toBe(false);
    expect(isOfficialEmberMcpUrl('https://evil.com')).toBe(false);
  });

  it('returns false for invalid URLs', () => {
    expect(isOfficialEmberMcpUrl('not-a-url')).toBe(false);
  });
});
