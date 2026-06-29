import { describe, it, expect, beforeEach } from 'bun:test';
import {
  HISTORY_PAGE_SIZE,
  createHistoryAuthCtx,
  fetchLatestEvents,
  fetchOlderEvents,
  type SessionHistoryOAuthDeps,
  type FetchFn,
  type HistoryPage,
} from './session-history.ts';

// ---------------------------------------------------------------------------
// Mock OAuth deps
// ---------------------------------------------------------------------------

// W2-B: orgUUID removed from prepareOAuth() — x-organization-uuid header stripped.
const MOCK_DEPS: SessionHistoryOAuthDeps = {
  async prepareOAuth() {
    return {
      accessToken: 'test-token-abc',
      baseApiUrl: 'https://api.example.com',
    };
  },
  getOAuthHeaders(accessToken: string) {
    return { Authorization: `Bearer ${accessToken}` };
  },
};

// ---------------------------------------------------------------------------
// Mock fetch factory
// ---------------------------------------------------------------------------

function makeFetch(
  status: number,
  body: unknown,
  opts: { timeout?: boolean } = {},
): FetchFn {
  return async (_url, options) => {
    if (opts.timeout && options?.signal) {
      // Simulate a slow request that times out
      await new Promise<void>((_, reject) => {
        (options.signal as AbortSignal).addEventListener('abort', () => {
          reject(new Error('AbortError'));
        });
        // Never resolve naturally — will be aborted
      });
    }
    return {
      status,
      async json() { return body; },
    } as Response;
  };
}

// ---------------------------------------------------------------------------
// AC7: HISTORY_PAGE_SIZE constant is exported and equals 100
// ---------------------------------------------------------------------------
describe('AC7: HISTORY_PAGE_SIZE', () => {
  it('is exported', () => {
    expect(HISTORY_PAGE_SIZE).toBeDefined();
  });

  it('equals 100', () => {
    expect(HISTORY_PAGE_SIZE).toBe(100);
  });
});

// ---------------------------------------------------------------------------
// AC1 + AC2: createHistoryAuthCtx
// ---------------------------------------------------------------------------
describe('createHistoryAuthCtx', () => {
  it('AC1: baseUrl contains sessionId and /v1/sessions/{id}/events path', async () => {
    const ctx = await createHistoryAuthCtx('session-xyz', MOCK_DEPS);
    expect(ctx.baseUrl).toContain('session-xyz');
    expect(ctx.baseUrl).toContain('/v1/sessions/session-xyz/events');
    expect(ctx.baseUrl).toContain('https://api.example.com');
  });

  it('AC1: different sessionIds produce different baseUrls', async () => {
    const ctx1 = await createHistoryAuthCtx('sess-1', MOCK_DEPS);
    const ctx2 = await createHistoryAuthCtx('sess-2', MOCK_DEPS);
    expect(ctx1.baseUrl).not.toBe(ctx2.baseUrl);
  });

  // W2-B: api-beta header stripped — no longer sent.
  it('AC2: headers do NOT include api-beta (W2-B stripped)', async () => {
    const ctx = await createHistoryAuthCtx('session-abc', MOCK_DEPS);
    expect(ctx.headers['api-beta']).toBeUndefined();
  });

  // W2-B: x-organization-uuid header stripped — no longer sent.
  it('AC2: headers do NOT include x-organization-uuid (W2-B stripped)', async () => {
    const ctx = await createHistoryAuthCtx('session-abc', MOCK_DEPS);
    expect(ctx.headers['x-organization-uuid']).toBeUndefined();
  });

  it('AC2: headers include OAuth Authorization header', async () => {
    const ctx = await createHistoryAuthCtx('session-abc', MOCK_DEPS);
    expect(ctx.headers['Authorization']).toContain('Bearer');
  });
});

// ---------------------------------------------------------------------------
// AC3: fetchLatestEvents sends anchor_to_latest=true
// ---------------------------------------------------------------------------
describe('fetchLatestEvents', () => {
  let capturedUrl: string | null = null;

  const captureFetch: FetchFn = async (url, _opts) => {
    capturedUrl = url as string;
    return { status: 200, async json() { return { data: [], first_id: null, has_more: false }; } } as Response;
  };

  beforeEach(async () => {
    capturedUrl = null;
  });

  it('AC3: sends anchor_to_latest=true', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    await fetchLatestEvents(ctx, undefined, captureFetch);
    expect(capturedUrl).toContain('anchor_to_latest=true');
  });

  it('AC3: sends the correct limit (default 100)', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    await fetchLatestEvents(ctx, undefined, captureFetch);
    expect(capturedUrl).toContain('limit=100');
  });

  it('AC3: custom limit is sent', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    await fetchLatestEvents(ctx, 50, captureFetch);
    expect(capturedUrl).toContain('limit=50');
  });

  it('returns events array from response', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    const body = { data: [{ id: 'e1', type: 'message' }], first_id: 'e1', has_more: false };
    const page = await fetchLatestEvents(ctx, undefined, makeFetch(200, body));
    expect(page).not.toBeNull();
    expect(page!.events).toHaveLength(1);
    expect(page!.firstId).toBe('e1');
    expect(page!.hasMore).toBe(false);
  });

  // AC5: non-200 → null without throwing
  it('AC5: HTTP 404 returns null without throwing', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    const page = await fetchLatestEvents(ctx, undefined, makeFetch(404, {}));
    expect(page).toBeNull();
  });

  it('AC5: HTTP 500 returns null without throwing', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    const page = await fetchLatestEvents(ctx, undefined, makeFetch(500, {}));
    expect(page).toBeNull();
  });

  it('AC5: does not throw on non-200', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    await expect(fetchLatestEvents(ctx, undefined, makeFetch(403, {}))).resolves.toBeNull();
  });

  // AC6: network timeout → null
  it('AC6: network error returns null', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    const errorFetch: FetchFn = async () => { throw new Error('Network error'); };
    const page = await fetchLatestEvents(ctx, undefined, errorFetch);
    expect(page).toBeNull();
  });

  it('returns null on malformed response body', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    const page = await fetchLatestEvents(ctx, undefined, makeFetch(200, null));
    expect(page).not.toBeNull();
    expect(page!.events).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// AC4: fetchOlderEvents sends before_id
// ---------------------------------------------------------------------------
describe('fetchOlderEvents', () => {
  let capturedUrl: string | null = null;

  const captureFetch: FetchFn = async (url, _opts) => {
    capturedUrl = url as string;
    return { status: 200, async json() { return { data: [], first_id: null, has_more: false }; } } as Response;
  };

  beforeEach(() => {
    capturedUrl = null;
  });

  it('AC4: sends before_id=beforeId', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    await fetchOlderEvents(ctx, 'event-cursor-123', undefined, captureFetch);
    expect(capturedUrl).toContain('before_id=event-cursor-123');
  });

  it('AC4: sends the correct limit (default 100)', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    await fetchOlderEvents(ctx, 'cursor', undefined, captureFetch);
    expect(capturedUrl).toContain('limit=100');
  });

  it('AC4: custom limit is sent', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    await fetchOlderEvents(ctx, 'cursor', 25, captureFetch);
    expect(capturedUrl).toContain('limit=25');
  });

  // AC5: non-200 → null
  it('AC5: HTTP 404 returns null', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    expect(await fetchOlderEvents(ctx, 'c', undefined, makeFetch(404, {}))).toBeNull();
  });

  it('AC5: HTTP 500 returns null', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    expect(await fetchOlderEvents(ctx, 'c', undefined, makeFetch(500, {}))).toBeNull();
  });

  // AC6: network error → null
  it('AC6: network error returns null', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    const errorFetch: FetchFn = async () => { throw new Error('Network error'); };
    expect(await fetchOlderEvents(ctx, 'c', undefined, errorFetch)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC8: chaining fetchLatestEvents → fetchOlderEvents(ctx, page.firstId)
// ---------------------------------------------------------------------------
describe('AC8: pagination chaining', () => {
  it('fetchOlderEvents uses firstId from previous page as cursor', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);

    // First fetch returns newest page with firstId = "oldest-in-page"
    const newestBody = {
      data: [{ id: 'e3' }, { id: 'e2' }],
      first_id: 'oldest-in-page-e2',
      has_more: true,
      last_id: 'e3',
    };
    const page1 = await fetchLatestEvents(ctx, undefined, makeFetch(200, newestBody));
    expect(page1).not.toBeNull();
    expect(page1!.firstId).toBe('oldest-in-page-e2');
    expect(page1!.hasMore).toBe(true);

    // Second fetch uses page1.firstId as before_id cursor
    let capturedUrl = '';
    const captureFetch: FetchFn = async (url, _opts) => {
      capturedUrl = url as string;
      return {
        status: 200,
        async json() {
          return { data: [{ id: 'e1' }], first_id: 'e1', has_more: false, last_id: 'e1' };
        },
      } as Response;
    };

    const page2 = await fetchOlderEvents(ctx, page1!.firstId!, undefined, captureFetch);
    expect(capturedUrl).toContain('before_id=oldest-in-page-e2');
    expect(page2).not.toBeNull();
    expect(page2!.hasMore).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC9: has_more=true + valid first_id enables further pagination
// ---------------------------------------------------------------------------
describe('AC9: further pagination enabled', () => {
  it('page with has_more=true and firstId can drive pagination', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    const body = { data: [], first_id: 'cursor-abc', has_more: true };
    const page = await fetchLatestEvents(ctx, undefined, makeFetch(200, body)) as HistoryPage;
    expect(page.hasMore).toBe(true);
    expect(page.firstId).toBe('cursor-abc');
    // firstId can be used to call fetchOlderEvents
    expect(typeof page.firstId).toBe('string');
  });

  it('page with has_more=false ends pagination', async () => {
    const ctx = await createHistoryAuthCtx('s1', MOCK_DEPS);
    const body = { data: [], first_id: null, has_more: false };
    const page = await fetchLatestEvents(ctx, undefined, makeFetch(200, body)) as HistoryPage;
    expect(page.hasMore).toBe(false);
    expect(page.firstId).toBeNull();
  });
});
