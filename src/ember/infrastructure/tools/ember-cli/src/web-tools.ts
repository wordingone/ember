// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// web-tools.ts — WebFetch and WebSearch tool implementations.
// Covers AC1–AC8 for WebFetch and AC1–AC5 for WebSearch.

import { z } from 'zod';
import { buildTool } from './core/tool-interface.ts';
import type { ToolUseContext } from './core/tool-interface.ts';
import { isBlockedHost, blockedResolvedAddress, type HostResolver } from './core/private-hosts.ts';

// ---------------------------------------------------------------------------
// Preapproved domains (no secondary-model processing for preapproved URLs)
// ---------------------------------------------------------------------------

const PREAPPROVED_DOMAINS = new Set([
  'docs.python.org',
  'developer.mozilla.org',
  'docs.bun.sh',
  'npmjs.com',
  'jsr.io',
  'docs.deno.com',
  'typescript-eslint.io',
  'typescriptlang.org',
  'zod.dev',
  'react.dev',
  'nodejs.org',
]);

export function isPreapprovedUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    // Strip www. prefix for comparison
    const host = parsed.hostname.replace(/^www\./, '');
    return PREAPPROVED_DOMAINS.has(host);
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Blocked hosts (private / reserved address space)
// ---------------------------------------------------------------------------

// One definition of "private address", shared with the shell tools (core/private-hosts.ts).
export { isBlockedHost };

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

/** Rejects with an AbortError as soon as `signal` aborts, even if `p` never settles (a hung DNS lookup or connect). */
export function abortable<T>(p: Promise<T>, signal: AbortSignal | undefined): Promise<T> {
  if (!signal) return p;
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => { const e = new Error('aborted'); e.name = 'AbortError'; reject(e); };
    if (signal.aborted) { onAbort(); return; }
    signal.addEventListener('abort', onAbort, { once: true });
    p.then(
      (v) => { signal.removeEventListener('abort', onAbort); resolve(v); },
      (e) => { signal.removeEventListener('abort', onAbort); reject(e); },
    );
  });
}

export function upgradeHttpToHttps(url: string): string {
  return url.startsWith('http://') ? url.replace('http://', 'https://') : url;
}

export function isPermittedRedirect(original: string, redirect: string): boolean {
  try {
    const orig = new URL(original);
    const redir = new URL(redirect, original);
    if (orig.protocol !== redir.protocol) return false;
    const origHost = orig.hostname.replace(/^www\./, '');
    const redirHost = redir.hostname.replace(/^www\./, '');
    return origHost === redirHost;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Caches (15-minute TTL)
//
//   pageCache  the fetched page as markdown, keyed by URL (fragment dropped, host lowercased)
//   urlCache   the answer to one question about one page, keyed by URL + prompt
//
// The answer used to be cached by URL alone, so asking a second, different question about the
// same page returned the first question's answer (blind test W17: eight WebFetch calls to compare
// two pages). The page is now cached on its own, so a new question about it is not a new download.
// ---------------------------------------------------------------------------

interface CacheEntry<T> {
  value: T;
  expiresAt: number;
}

class TtlCache<T> {
  map = new Map<string, CacheEntry<T>>();
  private _ttlMs = 15 * 60 * 1000;

  get(key: string): T | undefined {
    const entry = this.map.get(key);
    if (!entry) return undefined;
    if (Date.now() > entry.expiresAt) {
      this.map.delete(key);
      return undefined;
    }
    return entry.value;
  }

  set(key: string, value: T): void {
    this.map.set(key, { value, expiresAt: Date.now() + this._ttlMs });
  }
}

/** A fetched page: its text (capped at MAX_CONTENT_CHARS) and how long the full text was. */
interface PageEntry {
  text: string;
  fullChars: number;
  /** Set when the response is not a text page: the finished result to return as it is. */
  direct?: string;
}

export const urlCache = new TtlCache<string>();
export const pageCache = new TtlCache<PageEntry>();

/** One cache key per page: `https://Host/a#x` and `https://host/a` are the same page. */
export function pageCacheKey(url: string): string {
  try {
    const u = new URL(url);
    u.hash = '';
    return u.toString();
  } catch {
    return url;
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WebFetchInput {
  url: string;
  prompt: string;
  startIndex?: number;
}

export interface WebFetchDeps {
  fetchFn: typeof fetch;
  /** `charsRead` is how much of `content` the model was actually given (it may clip to its context). */
  secondaryModel: (content: string, prompt: string, preapproved: boolean) => Promise<{ text: string; charsRead?: number }>;
  /** `baseUrl` turns the page's relative links into absolute ones (blind test W16). */
  htmlToMarkdown: (html: string, baseUrl?: string) => string;
  persistBinary?: (data: Uint8Array, mimeType: string, url: string) => Promise<string>;
  /** Host name -> addresses, for the private-address check. Default: the system resolver. */
  resolveHost?: HostResolver;
}

const MAX_REDIRECT_HOPS = 5;

const MAX_CONTENT_CHARS = 100_000;

/**
 * The line put in front of a result built from only part of a page. Blind test W12: a 422,279-byte
 * page was cut, the model summarised the cut and reported its size and its last section as the
 * page's own. The size of the whole page and the fact that this is part of it go first, where the
 * model reads them before the content.
 */
export function partialPageNotice(fullChars: number, charsRead: number): string {
  const pct = Math.max(1, Math.min(99, Math.round((charsRead / fullChars) * 100)));
  return `[PARTIAL PAGE (truncated): the page text is ${fullChars.toLocaleString('en-US')} characters; only the first ${charsRead.toLocaleString('en-US')} (${pct}%) were read. ` +
    `Its size, section count, last section and ending, as given below, describe this part only, not the whole page.]`;
}

/** A fetch error in plain words. Bun's own text for a failed DNS lookup is only "Was there a
 * typo in the url or port?" (blind test W13). */
export function describeFetchError(e: unknown, url: string): string {
  const err = e as { message?: string; code?: string; name?: string };
  const code = err.code ?? '';
  if (err.name === 'AbortError' || code === 'ABORT_ERR') return `WebFetch cancelled for ${url}`;
  if (code === 'ConnectionRefused' || /ECONNREFUSED/i.test(code)) return `WebFetch failed for ${url}: could not connect to the server`;
  if (/ENOTFOUND|EAI_|DNS/i.test(code) || /typo in the url/i.test(err.message ?? '')) {
    let host = url;
    try { host = new URL(url).hostname; } catch { /* keep url */ }
    return `WebFetch failed for ${url}: the host name ${host} could not be found (DNS lookup failed). Check the spelling of the domain.`;
  }
  if (/timed? ?out/i.test(code + ' ' + (err.message ?? ''))) return `WebFetch failed for ${url}: the server did not answer in time`;
  return `WebFetch failed for ${url}: ${err.message ?? String(e)}`;
}

/** describeFetchError, plus a DNS lookup when the connection failed: Bun reports a host that does
 * not exist as "ConnectionRefused", which sends the model looking for a server problem. */
async function explainFetchError(e: unknown, url: string): Promise<string> {
  const msg = describeFetchError(e, url);
  if (!msg.endsWith('could not connect to the server')) return msg;
  try {
    const host = new URL(url).hostname;
    await (await import('node:dns')).promises.lookup(host);
  } catch {
    return describeFetchError({ code: 'ENOTFOUND' }, url);
  }
  return msg;
}

// ---------------------------------------------------------------------------
// buildWebFetchTool
// ---------------------------------------------------------------------------

export const WEB_FETCH_DESCRIPTION = [
  'Fetch a URL, convert the page to markdown, and answer a prompt about it using the local model.',
  '- Takes a fully-formed URL and a prompt describing what to extract from the page.',
  '- http:// URLs are upgraded to https://. Private/loopback addresses are refused.',
  '- If the URL redirects to a different host, the redirect URL is returned; call WebFetch again with it.',
  '- Large pages are truncated (100,000 characters) and the result then begins with a PARTIAL PAGE line giving the full size: what follows describes only the part that was read. Pages and answers are cached for 15 minutes.',
  '- If no local model is reachable the truncated page markdown is returned instead of a summary.',
  '- Read-only. For GitHub URLs prefer the gh_* tools.',
].join('\n');

const WebFetchInputSchema = z.object({
  url: z.string().describe('The fully-formed URL to fetch'),
  prompt: z.string().describe('What information to extract from the page'),
}).strict();

export function buildWebFetchTool(deps: WebFetchDeps) {
  return buildTool<WebFetchInput, { result: string }>({
    name: 'WebFetch',
    inputSchema: WebFetchInputSchema,
    description: () => WEB_FETCH_DESCRIPTION,
    prompt: () => WEB_FETCH_DESCRIPTION,
    isReadOnly: () => true,
    isConcurrencySafe: () => true,
    mapToolResultToToolResultBlockParam: (content, id) => ({
      type: 'tool_result' as const,
      tool_use_id: id,
      content: content.result,
    }),
    call: async (args, ctx, _canUse, _parent) => {
      const { url: rawUrl, prompt } = args;
      // Esc must stop a slow download, not wait for it to finish (blind test W21).
      const signal = (ctx as { abortController?: AbortController } | undefined)?.abortController?.signal;

      // AC3: upgrade HTTP to HTTPS
      const url = upgradeHttpToHttps(rawUrl);

      // AC4: block private/reserved hosts
      let hostname = '';
      try {
        const parsed = new URL(url);
        // Only web pages: file://, ftp:// and the like read local files or other services
        // with no approval (blind test W23: file:///C:/Windows/win.ini was read).
        if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
          throw new Error(`blocked: only http and https URLs can be fetched, not ${parsed.protocol}`);
        }
        if (isBlockedHost(parsed.hostname)) {
          throw new Error(`blocked: ${parsed.hostname} is a private/reserved address`);
        }
        hostname = parsed.hostname;
      } catch (e) {
        if ((e as Error).message.includes('blocked')) throw e;
        throw new Error(`blocked: invalid URL`);
      }
      // The name may point at a private address (localtest.me, 127.0.0.1.nip.io; blind test W20).
      const pointsAt = await abortable(blockedResolvedAddress(hostname, deps.resolveHost), signal);
      if (pointsAt !== null) {
        throw new Error(`blocked: ${hostname} resolves to ${pointsAt}, a private/reserved address`);
      }

      // AC5: return the answer to this question about this page, if we already have it
      const pageKey = pageCacheKey(url);
      const answerKey = `${pageKey}\u0000${prompt.trim()}`;
      const cached = urlCache.get(answerKey);
      if (cached !== undefined) {
        return { data: { result: cached } };
      }

      const preapproved = isPreapprovedUrl(url);

      // The page itself: from the cache, or fetched now.
      let page = pageCache.get(pageKey);
      if (page === undefined) {
        const fetched = await abortable(fetchPage(deps, url, signal), signal).catch(async (e) => {
          if ((e as Error).message?.startsWith('blocked')) throw e;
          return { result: await explainFetchError(e, url) };
        });
        if ('result' in fetched) return { data: { result: fetched.result } };
        page = fetched.page;
        if (page.direct === undefined) pageCache.set(pageKey, page);
      }
      if (page.direct !== undefined) {
        urlCache.set(answerKey, page.direct);
        return { data: { result: page.direct } };
      }

      const text = page.text;

      // AC1: preapproved URL with text/markdown — skip model
      // AC2: non-preapproved URL — process through secondary model
      let result: string;
      let charsRead = text.length;
      if (preapproved) {
        result = text;
      } else {
        try {
          const modelResult = await deps.secondaryModel(text, prompt, preapproved);
          result = modelResult.text;
          charsRead = Math.min(text.length, modelResult.charsRead ?? text.length);
        } catch (e) {
          // Never fail the fetch because summarisation failed: hand back the page itself.
          charsRead = Math.min(text.length, 20_000);
          result = `[No model summary (${(e as Error).message}); returning page markdown]\n\n${text.slice(0, charsRead)}`;
        }
      }
      // Cut by the 100,000-character cap, or clipped again to fit the model: say so, with the full size.
      if (page.fullChars > charsRead) {
        result = `${partialPageNotice(page.fullChars, charsRead)}\n\n${result}`;
      }

      urlCache.set(answerKey, result);
      return { data: { result } };
    },
  });
}

/**
 * Downloads `url` and turns it into a PageEntry, or returns the finished result for anything that
 * is not a text page (a failed request, a cross-host redirect, a binary file).
 */
async function fetchPage(
  deps: WebFetchDeps,
  url: string,
  signal: AbortSignal | undefined,
): Promise<{ page: PageEntry } | { result: string }> {
  // Every request carries the turn's abort signal and is cut loose the moment it aborts (W28).
  const fetchFn: typeof fetch = ((u: string | URL | Request, init?: RequestInit) =>
    abortable(deps.fetchFn(u, init), signal)) as typeof fetch;
  // AC6: check for cross-host redirect first
  let headResp: Response;
  try {
    headResp = await fetchFn(url, { redirect: 'manual', signal });
  } catch (e) {
    return { result: await explainFetchError(e, url) };
  }

  // Follow same-host redirects by hand so that every hop is checked (W20): a hop to another host is
  // returned to the model, a hop to a name that points at a private address is refused.
  let resp = headResp;
  let current = url;
  let hops = 0;
  let reprobed = false;
  try {
    for (;;) {
      if (resp.status >= 300 && resp.status < 400) {
        const location = resp.headers.get('location') ?? '';
        if (!isPermittedRedirect(current, location)) return { result: `redirect to ${location}` };
        if (++hops > MAX_REDIRECT_HOPS) return { result: `WebFetch failed for ${url}: too many redirects` };
        const next = new URL(location, current);
        const pointsAt = await abortable(blockedResolvedAddress(next.hostname, deps.resolveHost), signal);
        if (pointsAt !== null) throw new Error(`blocked: redirect to ${next.hostname}, which is ${pointsAt}, a private/reserved address`);
        current = next.toString();
        resp = await fetchFn(current, { redirect: 'manual', signal });
        continue;
      }
      // If the probe response already carries a content-type, reuse it directly (AC5: one round-trip
      // on a cache miss). Without one it is a bare probe stub (e.g. AC7's binary fake): fetch again.
      const ct = resp.headers.get('content-type');
      if (!reprobed && (ct == null || ct === '')) {
        reprobed = true;
        resp = await fetchFn(current, { redirect: 'manual', signal });
        continue;
      }
      break;
    }
  } catch (e) {
    if ((e as Error).message?.startsWith('blocked')) throw e;
    return { result: await explainFetchError(e, url) };
  }
  if (resp.status >= 400) {
    // Errors are not cached: they are often transient.
    return { result: `WebFetch failed for ${url}: HTTP ${resp.status} ${resp.statusText}`.trim() };
  }
  const contentType = resp.headers.get('content-type') ?? '';
  const isBinary = !contentType.startsWith('text/') && !contentType.includes('json') &&
    !contentType.includes('javascript') && !contentType.includes('xml');

  if (isBinary) {
    // AC7: persist binary to disk
    const buffer = new Uint8Array(await abortable(resp.arrayBuffer(), signal));
    if (deps.persistBinary) {
      const path = await deps.persistBinary(buffer, contentType, url);
      return { page: { text: '', fullChars: 0, direct: `Binary content saved to: ${path}` } };
    }
    return { result: `Binary content (${contentType}) — no persistence configured` };
  }

  let text: string;
  try {
    text = await abortable(resp.text(), signal);
  } catch (e) {
    return { result: await explainFetchError(e, url) };
  }

  // Convert HTML to markdown if needed; links become absolute against the final URL (W16).
  if (contentType.includes('text/html')) {
    text = deps.htmlToMarkdown(text, resp.url || current);
  }

  // AC8: truncate long content, remembering how long it really was (W12)
  const fullChars = text.length;
  if (text.length > MAX_CONTENT_CHARS) {
    text = text.slice(0, MAX_CONTENT_CHARS);
  }
  return { page: { text, fullChars } };
}

// ---------------------------------------------------------------------------
// WebSearch types
// ---------------------------------------------------------------------------

export interface WebSearchInput {
  query: string;
  allowed_domains?: string[];
  blocked_domains?: string[];
}

export interface SearchResult {
  url: string;
  title: string;
  description: string;
  score: number;
}

export type WebSearchOutput = {
  query: string;
  results: (string | { content: SearchResult[] })[];
  /** Set when the search could not be performed (e.g. every engine failed). */
  error?: string;
};

export interface SearchDeps {
  /** May return a bare list, or a list plus human-readable notes (e.g. partial engine failures). */
  performSearch: (query: string, opts: unknown) => Promise<SearchResult[] | { results: SearchResult[]; notes?: string[] }>;
}

// ---------------------------------------------------------------------------
// buildWebSearchTool
// ---------------------------------------------------------------------------

export const WEB_SEARCH_DESCRIPTION = [
  'Search the web (keyless meta-search: DuckDuckGo, Brave, Wikipedia) and return ranked results with title, URL and snippet.',
  '- Use for information beyond the model knowledge cutoff or for current events; use the current year in time-sensitive queries.',
  '- Optional allowed_domains OR blocked_domains (mutually exclusive) restrict results by host.',
  '- Snippets are short: follow up with WebFetch on a result URL to read the page.',
  '- If every engine fails the tool returns an error naming each engine failure.',
  '- After answering, cite the URLs you used in a "Sources:" list.',
].join('\n');

const WebSearchInputSchema = z.object({
  query: z.string().min(2).describe('The search query'),
  allowed_domains: z.array(z.string()).optional().describe('Only include results from these domains'),
  blocked_domains: z.array(z.string()).optional().describe('Never include results from these domains'),
}).strict();

export function buildWebSearchTool(deps: SearchDeps) {
  return buildTool<WebSearchInput, WebSearchOutput>({
    name: 'WebSearch',
    inputSchema: WebSearchInputSchema,
    description: () => WEB_SEARCH_DESCRIPTION,
    prompt: () => WEB_SEARCH_DESCRIPTION,
    isReadOnly: () => true,
    isConcurrencySafe: () => true,
    mapToolResultToToolResultBlockParam: (content, id) => ({
      type: 'tool_result' as const,
      tool_use_id: id,
      content: JSON.stringify(content),
    }),
    call: async (args, ctx, _canUse, _parent, onEvent?: (event: unknown) => void) => {
      const signal = (ctx as { abortController?: AbortController } | undefined)?.abortController?.signal;
      const { query, allowed_domains, blocked_domains } = args;

      // AC3: mutual exclusion
      if (allowed_domains && blocked_domains) {
        throw new Error('allowed_domains and blocked_domains are mutually exclusive');
      }

      // AC5: start event
      onEvent?.({ type: 'web_search_start', query });

      let results: SearchResult[];
      let notes: string[] = [];
      try {
        const raw = await abortable(deps.performSearch(query, { allowed_domains, blocked_domains, signal }), signal);
        if (Array.isArray(raw)) results = raw;
        else { results = raw.results; notes = raw.notes ?? []; }
      } catch (e) {
        const error = (e as Error).message || String(e);
        onEvent?.({ type: 'web_search_complete', query, resultCount: 0, error });
        return { data: { query, results: [`WebSearch failed: ${error}`], error } };
      }

      // AC2: filter by allowed_domains
      if (allowed_domains && allowed_domains.length > 0) {
        results = results.filter(r => {
          try {
            const host = new URL(r.url).hostname;
            return allowed_domains.some(d => host === d || host.endsWith(`.${d}`));
          } catch { return false; }
        });
      }

      // Filter by blocked_domains
      if (blocked_domains && blocked_domains.length > 0) {
        results = results.filter(r => {
          try {
            const host = new URL(r.url).hostname;
            return !blocked_domains.some(d => host === d || host.endsWith(`.${d}`));
          } catch { return true; }
        });
      }

      // AC5: complete event
      onEvent?.({ type: 'web_search_complete', query, resultCount: results.length });

      // AC4: sources reminder
      const output: WebSearchOutput = {
        query,
        results: [
          ...(results.length === 0
            ? [notes.length > 0
              ? 'No results found, but a search engine failed (see the notes below), so this may mean the engines did not answer, not that nothing exists.'
              : 'No results found.']
            : []),
          ...notes,
          ...results.map(r => ({ content: [r] })),
          'Sources: Remember to cite the URLs above in your response.',
        ],
      };

      return { data: output };
    },
  });
}
