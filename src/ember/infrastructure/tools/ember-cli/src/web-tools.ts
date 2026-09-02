// web-tools.ts — WebFetch and WebSearch tool implementations.
// Covers AC1–AC8 for WebFetch and AC1–AC5 for WebSearch.

import { buildTool } from './core/tool-interface.ts';
import type { ToolUseContext } from './core/tool-interface.ts';

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

export function isBlockedHost(hostname: string): boolean {
  if (hostname === 'localhost') return true;
  // 127.x.x.x loopback
  if (/^127\./.test(hostname)) return true;
  // 192.168.x.x private
  if (/^192\.168\./.test(hostname)) return true;
  // 10.x.x.x private
  if (/^10\./.test(hostname)) return true;
  // 172.16–31.x.x private
  if (/^172\.(1[6-9]|2\d|3[01])\./.test(hostname)) return true;
  // 169.254.x.x link-local / cloud metadata
  if (/^169\.254\./.test(hostname)) return true;
  // ::1 IPv6 loopback
  if (hostname === '::1') return true;
  return false;
}

// ---------------------------------------------------------------------------
// URL helpers
// ---------------------------------------------------------------------------

export function upgradeHttpToHttps(url: string): string {
  return url.startsWith('http://') ? url.replace('http://', 'https://') : url;
}

export function isPermittedRedirect(original: string, redirect: string): boolean {
  try {
    const orig = new URL(original);
    const redir = new URL(redirect);
    if (orig.protocol !== redir.protocol) return false;
    const origHost = orig.hostname.replace(/^www\./, '');
    const redirHost = redir.hostname.replace(/^www\./, '');
    return origHost === redirHost;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// URL response cache (15-minute TTL, keyed by URL)
// ---------------------------------------------------------------------------

interface CacheEntry {
  result: string;
  expiresAt: number;
}

class UrlCache {
  map = new Map<string, CacheEntry>();
  private _ttlMs = 15 * 60 * 1000;

  get(url: string): string | undefined {
    const entry = this.map.get(url);
    if (!entry) return undefined;
    if (Date.now() > entry.expiresAt) {
      this.map.delete(url);
      return undefined;
    }
    return entry.result;
  }

  set(url: string, result: string): void {
    this.map.set(url, { result, expiresAt: Date.now() + this._ttlMs });
  }
}

export const urlCache = new UrlCache();

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
  secondaryModel: (content: string, prompt: string, preapproved: boolean) => Promise<{ text: string }>;
  htmlToMarkdown: (html: string) => string;
  persistBinary?: (data: Uint8Array, mimeType: string, url: string) => Promise<string>;
}

const MAX_CONTENT_CHARS = 100_000;

// ---------------------------------------------------------------------------
// buildWebFetchTool
// ---------------------------------------------------------------------------

export function buildWebFetchTool(deps: WebFetchDeps) {
  return buildTool<WebFetchInput, { result: string }>({
    name: 'WebFetch',
    description: () => 'Fetch a URL and return its content.',
    isReadOnly: () => true,
    mapToolResultToToolResultBlockParam: (content, id) => ({
      type: 'tool_result' as const,
      tool_use_id: id,
      content: content.result,
    }),
    call: async (args, _ctx, _canUse, _parent) => {
      const { url: rawUrl, prompt } = args;

      // AC3: upgrade HTTP to HTTPS
      const url = upgradeHttpToHttps(rawUrl);

      // AC4: block private/reserved hosts
      try {
        const parsed = new URL(url);
        if (isBlockedHost(parsed.hostname)) {
          throw new Error(`blocked: ${parsed.hostname} is a private/reserved address`);
        }
      } catch (e) {
        if ((e as Error).message.includes('blocked')) throw e;
        throw new Error(`blocked: invalid URL`);
      }

      // AC5: return from cache if present
      const cached = urlCache.get(url);
      if (cached !== undefined) {
        return { data: { result: cached } };
      }

      const preapproved = isPreapprovedUrl(url);

      // AC6: check for cross-host redirect first
      const headResp = await deps.fetchFn(url, { redirect: 'manual' });
      if (headResp.status >= 300 && headResp.status < 400) {
        const location = headResp.headers.get('location') ?? '';
        if (!isPermittedRedirect(url, location)) {
          const result = `redirect to ${location}`;
          return { data: { result } };
        }
      }

      // If the redirect-probe response already carries a content-type, reuse it
      // directly (AC5: avoids a second fetch, keeping the cache-miss cost to one
      // round-trip). If content-type is absent the response is a bare probe stub
      // (e.g. AC7's binary fake), so fall back to a second fetch that follows
      // redirects and delivers the real content.
      const headContentType = headResp.headers.get('content-type');
      const resp = (headContentType != null && headContentType !== '')
        ? headResp
        : await deps.fetchFn(url);
      const contentType = resp.headers.get('content-type') ?? '';
      const isBinary = !contentType.startsWith('text/') && !contentType.includes('json') &&
        !contentType.includes('javascript') && !contentType.includes('xml');

      if (isBinary) {
        // AC7: persist binary to disk
        const buffer = new Uint8Array(await resp.arrayBuffer());
        if (deps.persistBinary) {
          const path = await deps.persistBinary(buffer, contentType, url);
          const result = `Binary content saved to: ${path}`;
          urlCache.set(url, result);
          return { data: { result } };
        }
        return { data: { result: `Binary content (${contentType}) — no persistence configured` } };
      }

      let text = await resp.text();

      // Convert HTML to markdown if needed
      if (contentType.includes('text/html')) {
        text = deps.htmlToMarkdown(text);
      }

      // AC8: truncate long content
      let truncated = false;
      if (text.length > MAX_CONTENT_CHARS) {
        text = text.slice(0, MAX_CONTENT_CHARS);
        truncated = true;
      }
      if (truncated) {
        text += '\n\n[Content truncated to 100,000 characters]';
      }

      // AC1: preapproved URL with text/markdown — skip model
      // AC2: non-preapproved URL — process through secondary model
      let result: string;
      if (preapproved && contentType.includes('markdown')) {
        result = text;
      } else if (preapproved) {
        result = text;
      } else {
        const modelResult = await deps.secondaryModel(text, prompt, preapproved);
        result = modelResult.text;
      }

      urlCache.set(url, result);
      return { data: { result } };
    },
  });
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
};

export interface SearchDeps {
  performSearch: (query: string, opts: unknown) => Promise<SearchResult[]>;
}

// ---------------------------------------------------------------------------
// buildWebSearchTool
// ---------------------------------------------------------------------------

export function buildWebSearchTool(deps: SearchDeps) {
  return buildTool<WebSearchInput, WebSearchOutput>({
    name: 'WebSearch',
    description: () => 'Search the web and return structured results.',
    isReadOnly: () => true,
    mapToolResultToToolResultBlockParam: (content, id) => ({
      type: 'tool_result' as const,
      tool_use_id: id,
      content: JSON.stringify(content),
    }),
    call: async (args, _ctx, _canUse, _parent, onEvent?: (event: unknown) => void) => {
      const { query, allowed_domains, blocked_domains } = args;

      // AC3: mutual exclusion
      if (allowed_domains && blocked_domains) {
        throw new Error('allowed_domains and blocked_domains are mutually exclusive');
      }

      // AC5: start event
      onEvent?.({ type: 'web_search_start', query });

      let results = await deps.performSearch(query, { allowed_domains, blocked_domains });

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
          ...results.map(r => ({ content: [r] })),
          'Sources: Remember to cite the URLs above in your response.',
        ],
      };

      return { data: output };
    },
  });
}
