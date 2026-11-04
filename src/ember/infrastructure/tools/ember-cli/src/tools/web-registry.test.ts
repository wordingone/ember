// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// web-registry.test.ts — WebFetch/WebSearch are registered with schemas and prompts, and
// the keyless wiring degrades (never crashes) when engines or the model are unavailable.

import { test, expect, describe, afterEach } from 'bun:test';
import { BUILTIN_TOOLS } from './builtin-tools.ts';
import { WebFetchTool, WebSearchTool, performKeylessSearch } from './web-registry.ts';
import { clearSearchCache } from '../services/search/index.ts';
import { urlCache } from '../web-tools.ts';

const realFetch = globalThis.fetch;
const realUrl = process.env['EMBER_MODEL_URL'];
afterEach(() => {
  globalThis.fetch = realFetch;
  if (realUrl === undefined) delete process.env['EMBER_MODEL_URL']; else process.env['EMBER_MODEL_URL'] = realUrl;
  clearSearchCache();
  urlCache.map.clear();
});

const ctx = {} as never;

describe('registry', () => {
  test('WebFetch and WebSearch are registered exactly once in BUILTIN_TOOLS', () => {
    const names = BUILTIN_TOOLS.map((t) => t.name);
    expect(names.filter((n) => n === 'WebFetch').length).toBe(1);
    expect(names.filter((n) => n === 'WebSearch').length).toBe(1);
  });
  test('tools expose schemas, descriptions and read-only/concurrency flags', () => {
    for (const t of [WebFetchTool, WebSearchTool]) {
      expect(t.isReadOnly()).toBe(true);
      expect(t.isConcurrencySafe()).toBe(true);
      expect(t.description().length).toBeGreaterThan(80);
      expect(t.inputSchema).toBeDefined();
    }
    expect(WebFetchTool.inputSchema!.safeParse({ url: 'https://a.b', prompt: 'x' }).success).toBe(true);
    expect(WebFetchTool.inputSchema!.safeParse({ url: 'https://a.b' }).success).toBe(false);
    expect(WebSearchTool.inputSchema!.safeParse({ query: 'llama' }).success).toBe(true);
    expect(WebSearchTool.inputSchema!.safeParse({}).success).toBe(false);
  });
});

describe('WebSearch wiring', () => {
  test('all engines failing returns an error result naming each engine (no throw)', async () => {
    globalThis.fetch = (async () => { throw new TypeError('offline'); }) as unknown as typeof fetch;
    const { data } = await WebSearchTool.call({ query: 'all fail query' }, ctx);
    expect(data.error).toMatch(/duckduckgo/);
    expect(data.error).toMatch(/brave/);
    expect(data.error).toMatch(/wikipedia/);
    expect(JSON.stringify(data.results)).toContain('WebSearch failed');
  });
  test('partial failure yields results plus a note about the failed engines', async () => {
    globalThis.fetch = (async (u: string) => String(u).includes('wikipedia.org')
      ? new Response(JSON.stringify({ query: { search: [{ title: 'Foo', snippet: 'bar' }] } }), { status: 200 })
      : new Response('blocked', { status: 403 })) as unknown as typeof fetch;
    const out = await performKeylessSearch('partial note query', {});
    expect(out.results[0]!.url).toBe('https://en.wikipedia.org/wiki/Foo');
    expect(out.notes.join(' ')).toMatch(/duckduckgo failed/);
    expect(out.notes.join(' ')).toMatch(/brave failed/);
  });
  test('allowed_domains and blocked_domains together are rejected', async () => {
    await expect(WebSearchTool.call({ query: 'q', allowed_domains: ['a.com'], blocked_domains: ['b.com'] }, ctx)).rejects.toThrow(/mutually exclusive/);
  });
});

describe('WebFetch wiring', () => {
  test('no model: returns page markdown, not a failure', async () => {
    delete process.env['EMBER_MODEL_URL'];
    globalThis.fetch = (async () => new Response('<html><head><title>Hello</title></head><body><p>World text</p></body></html>', {
      status: 200, headers: { 'content-type': 'text/html; charset=utf-8' },
    })) as unknown as typeof fetch;
    const { data } = await WebFetchTool.call({ url: 'https://fetch-nomodel.example/', prompt: 'summarise' }, ctx);
    expect(data.result).toContain('World text');
    expect(data.result).toContain('# Hello');
    expect(data.result).toContain('No model summary');
  });
  test('network failure is reported as a result string, not thrown', async () => {
    globalThis.fetch = (async () => { throw new TypeError('connection refused'); }) as unknown as typeof fetch;
    const { data } = await WebFetchTool.call({ url: 'https://fetch-down.example/', prompt: 'x' }, ctx);
    expect(data.result).toContain('WebFetch failed');
    expect(data.result).toContain('connection refused');
  });
  test('HTTP 404 is reported with its status and is not cached', async () => {
    let n = 0;
    globalThis.fetch = (async () => { n++; return new Response('nope', { status: 404, statusText: 'Not Found', headers: { 'content-type': 'text/html' } }); }) as unknown as typeof fetch;
    const a = await WebFetchTool.call({ url: 'https://fetch-404.example/', prompt: 'x' }, ctx);
    expect(a.data.result).toContain('HTTP 404');
    await WebFetchTool.call({ url: 'https://fetch-404.example/', prompt: 'x' }, ctx);
    expect(n).toBe(2);
  });
  test('private hosts are refused', async () => {
    await expect(WebFetchTool.call({ url: 'http://127.0.0.1:8080/x', prompt: 'x' }, ctx)).rejects.toThrow(/blocked/);
  });
  test('cross-host redirect is surfaced, same-host redirect is followed', async () => {
    globalThis.fetch = (async () => new Response(null, { status: 301, headers: { location: 'https://other.example/z' } })) as unknown as typeof fetch;
    const cross = await WebFetchTool.call({ url: 'https://redir-a.example/x', prompt: 'x' }, ctx);
    expect(cross.data.result).toBe('redirect to https://other.example/z');

    let calls = 0;
    globalThis.fetch = (async (u: unknown, _init?: RequestInit) => {
      calls++;
      if (String(u).endsWith('/x')) {
        return new Response(null, { status: 301, headers: { location: '/y', 'content-type': 'text/html' } });
      }
      return new Response('<body><p>followed</p></body>', { status: 200, headers: { 'content-type': 'text/html' } });
    }) as unknown as typeof fetch;
    delete process.env['EMBER_MODEL_URL'];
    const same = await WebFetchTool.call({ url: 'https://redir-b.example/x', prompt: 'x' }, ctx);
    expect(same.data.result).toContain('followed');
    expect(calls).toBe(2);
  });
});
