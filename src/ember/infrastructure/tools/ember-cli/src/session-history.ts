// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// session-history.ts — OAuth-authenticated session event history fetcher (W2-B).

export const HISTORY_PAGE_SIZE = 100;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SessionHistoryOAuthDeps {
  prepareOAuth(): Promise<{ accessToken: string; baseApiUrl: string }>;
  getOAuthHeaders(accessToken: string): Record<string, string>;
}

export type FetchFn = (url: string | URL, options?: RequestInit) => Promise<Response>;

export interface HistoryPage {
  events: unknown[];
  firstId: string | null;
  hasMore: boolean;
}

interface HistoryAuthCtx {
  baseUrl: string;
  headers: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Auth context builder (W2-B: no api-beta, no x-organization-uuid)
// ---------------------------------------------------------------------------

export async function createHistoryAuthCtx(
  sessionId: string,
  deps: SessionHistoryOAuthDeps,
): Promise<HistoryAuthCtx> {
  const { accessToken, baseApiUrl } = await deps.prepareOAuth();
  const oauthHeaders = deps.getOAuthHeaders(accessToken);
  // W2-B: strip any beta / org headers — only the OAuth Authorization header is sent.
  const headers: Record<string, string> = { ...oauthHeaders };
  delete headers['api-beta'];
  delete headers['x-organization-uuid'];
  return {
    baseUrl: `${baseApiUrl}/v1/sessions/${sessionId}/events`,
    headers,
  };
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

function parsePage(body: unknown): HistoryPage {
  if (!body || typeof body !== 'object') {
    return { events: [], firstId: null, hasMore: false };
  }
  const b = body as Record<string, unknown>;
  return {
    events: Array.isArray(b['data']) ? b['data'] : [],
    firstId: typeof b['first_id'] === 'string' ? b['first_id'] : null,
    hasMore: b['has_more'] === true,
  };
}

async function safeFetch(
  url: string,
  ctx: HistoryAuthCtx,
  fetchFn: FetchFn,
): Promise<HistoryPage | null> {
  try {
    const res = await fetchFn(url, { headers: ctx.headers });
    if (res.status !== 200) return null;
    const body: unknown = await res.json();
    return parsePage(body);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Public fetch API
// ---------------------------------------------------------------------------

export async function fetchLatestEvents(
  ctx: HistoryAuthCtx,
  limit?: number,
  fetchFn: FetchFn = fetch,
): Promise<HistoryPage | null> {
  const n = limit ?? HISTORY_PAGE_SIZE;
  const url = `${ctx.baseUrl}?anchor_to_latest=true&limit=${n}`;
  return safeFetch(url, ctx, fetchFn);
}

export async function fetchOlderEvents(
  ctx: HistoryAuthCtx,
  beforeId: string,
  limit?: number,
  fetchFn: FetchFn = fetch,
): Promise<HistoryPage | null> {
  const n = limit ?? HISTORY_PAGE_SIZE;
  const url = `${ctx.baseUrl}?before_id=${encodeURIComponent(beforeId)}&limit=${n}`;
  return safeFetch(url, ctx, fetchFn);
}
