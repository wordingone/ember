// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// search.test.ts — keyless meta-search: parsers, merger, failure paths, retry.
// No real network: globalThis.fetch is replaced per test.

import { test, expect, describe, afterEach } from 'bun:test';
import { mergeResults } from './merger.ts';
import { stripTags, decodeEntities } from './engines/html.ts';
import * as ddg from './engines/duckduckgo.ts';
import * as brave from './engines/brave.ts';
import * as wiki from './engines/wikipedia.ts';
import { httpGet } from './engines/http.ts';
import {
  searchWithDiagnostics,
  search,
  AllEnginesFailedError,
  clearSearchCache,
  type SearchEngine,
} from './index.ts';

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
  clearSearchCache();
});

function mockFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>): { calls: string[] } {
  const calls: string[] = [];
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    calls.push(url);
    return handler(url, init);
  }) as unknown as typeof fetch;
  return { calls };
}

const html = (body: string, status = 200): Response =>
  new Response(body, { status, headers: { 'content-type': 'text/html' } });

describe('html helpers', () => {
  test('stripTags removes tags and decodes entities', () => {
    expect(stripTags('<b>A &amp; B</b><br>&#65;&#x42;')).toBe('A & B AB');
  });
  test('decodeEntities leaves unknown entities', () => {
    expect(decodeEntities('&bogus; &lt;')).toBe('&bogus; <');
  });
});

describe('mergeResults', () => {
  test('dedups by normalised url, sums inverse-position scores, prefers https', () => {
    const out = mergeResults([
      { engine: 'a', weight: 1, results: [{ url: 'http://x.com/p/', title: 'X', content: 'short' }] },
      { engine: 'b', weight: 1, results: [
        { url: 'https://y.com/', title: 'Y', content: '' },
        { url: 'https://x.com/p', title: 'X longer', content: 'a much longer snippet' },
      ] },
    ]);
    expect(out.results.length).toBe(2);
    const x = out.results.find((r) => r.url.includes('x.com'))!;
    expect(x.url.startsWith('https:')).toBe(true);
    expect(x.score).toBeCloseTo(1 + 0.5);
    expect(x.engines.sort()).toEqual(['a', 'b']);
    expect(x.title).toBe('X longer');
    expect(out.results[0]!.url).toContain('x.com');
  });
  test('errored engines are reported as unresponsive, not merged', () => {
    const out = mergeResults([
      { engine: 'bad', weight: 1, results: [], error: 'boom' },
      { engine: 'ok', weight: 1, results: [{ url: 'https://a.com', title: 'A', content: '' }] },
    ]);
    expect(out.unresponsive).toEqual([['bad', 'boom']]);
    expect(out.results.length).toBe(1);
  });
  test('weight scales score', () => {
    const out = mergeResults([{ engine: 'w', weight: 0.5, results: [{ url: 'https://a.com', title: 'A', content: '' }] }]);
    expect(out.results[0]!.score).toBe(0.5);
  });
});

describe('engine parsers', () => {
  test('duckduckgo decodes uddg redirects and skips ads', async () => {
    const page = `
      <a class="result__a" href="//duckduckgo.com/l/?uddg=${encodeURIComponent('https://example.org/a?x=1')}&rut=z">Title <b>A</b></a>
      <a class="result__snippet" href="#">Snippet &amp; more</a>
      <a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Ad</a>
      <a class="result__snippet" href="#">ad snippet</a>`;
    mockFetch((url) => (url.includes('html.duckduckgo.com') ? html(page) : html('no vqd')));
    const r = await ddg.search('q');
    expect(r).toEqual([{ url: 'https://example.org/a?x=1', title: 'Title A', content: 'Snippet & more' }]);
  });

  test('duckduckgo bot-challenge page throws instead of returning empty', async () => {
    mockFetch(() => html('<html>Unfortunately, bots use DuckDuckGo too. anomaly challenge</html>'));
    await expect(ddg.search('q')).rejects.toThrow(/bot challenge/);
  });

  test('duckduckgo non-200 throws with status', async () => {
    mockFetch(() => html('x', 403));
    await expect(ddg.search('q')).rejects.toThrow(/DDG HTTP 403/);
  });

  test('brave parses result blocks', async () => {
    const page = `<a class="result-header" href="https://b.example/1"><span class="snippet-title">Brave &lt;1&gt;</span></a>
      <p class="snippet-description">Desc one</p>`;
    mockFetch(() => html(page));
    const r = await brave.search('q');
    expect(r[0]).toEqual({ url: 'https://b.example/1', title: 'Brave <1>', content: 'Desc one' });
  });

  test('wikipedia parses JSON and builds article urls', async () => {
    mockFetch(() => new Response(JSON.stringify({ query: { search: [{ title: 'Llama cpp', snippet: 'a <span>b</span>' }] } }), { status: 200 }));
    const r = await wiki.search('llama');
    expect(r).toEqual([{ url: 'https://en.wikipedia.org/wiki/Llama_cpp', title: 'Llama cpp', content: 'a b' }]);
  });

  test('wikipedia malformed JSON throws', async () => {
    mockFetch(() => new Response('not json', { status: 200 }));
    await expect(wiki.search('q')).rejects.toThrow();
  });
});

describe('httpGet retry', () => {
  test('retries once on a network error then succeeds', async () => {
    let n = 0;
    const { calls } = mockFetch(() => {
      n++;
      if (n === 1) throw new TypeError('socket closed');
      return html('ok');
    });
    const res = await httpGet('https://x.test/');
    expect(res.text).toBe('ok');
    expect(calls.length).toBe(2);
  });
  test('retries once on 503 then returns the final response', async () => {
    const { calls } = mockFetch(() => html('down', 503));
    const res = await httpGet('https://x.test/');
    expect(res.status).toBe(503);
    expect(calls.length).toBe(2);
  });
  test('does not retry a 403', async () => {
    const { calls } = mockFetch(() => html('no', 403));
    const res = await httpGet('https://x.test/');
    expect(res.status).toBe(403);
    expect(calls.length).toBe(1);
  });
  test('gives up after one retry on persistent network error', async () => {
    const { calls } = mockFetch(() => { throw new TypeError('dns'); });
    await expect(httpGet('https://x.test/')).rejects.toThrow('dns');
    expect(calls.length).toBe(2);
  });
});

function engine(name: string, impl: () => Promise<{ url: string; title: string; content: string }[]>, weight = 1): SearchEngine {
  return { name, weight, search: impl };
}

describe('searchWithDiagnostics', () => {
  const opts = { noRateLimit: true };

  test('all engines failing throws an error naming each engine', async () => {
    const engines = [
      engine('alpha', async () => { throw new Error('HTTP 403'); }),
      engine('beta', async () => { throw new Error('dns failure'); }),
    ];
    let err: unknown;
    try { await searchWithDiagnostics('q', { ...opts, engines }); } catch (e) { err = e; }
    expect(err).toBeInstanceOf(AllEnginesFailedError);
    const msg = (err as Error).message;
    expect(msg).toContain('alpha: HTTP 403');
    expect(msg).toContain('beta: dns failure');
  });

  test('partial failure still returns results and lists the failed engine', async () => {
    const engines = [
      engine('good', async () => [{ url: 'https://a.com/1', title: 'A', content: 's' }]),
      engine('bad', async () => { throw new Error('boom'); }),
    ];
    const out = await searchWithDiagnostics('q', { ...opts, engines });
    expect(out.results.map((r) => r.url)).toEqual(['https://a.com/1']);
    expect(out.engineErrors).toEqual([{ engine: 'bad', error: 'boom' }]);
    expect(out.engineOk).toEqual(['good']);
  });

  test('an engine that hangs is timed out and reported', async () => {
    const engines = [
      engine('slow', () => new Promise(() => {})),
      engine('fast', async () => [{ url: 'https://a.com', title: 'A', content: '' }]),
    ];
    const out = await searchWithDiagnostics('q', { ...opts, engines, engineTimeoutMs: 30 });
    expect(out.engineErrors[0]!.engine).toBe('slow');
    expect(out.engineErrors[0]!.error).toMatch(/timeout/);
    expect(out.results.length).toBe(1);
  });

  test('zero results with no engine error is an honest empty, not a failure', async () => {
    const out = await searchWithDiagnostics('q', { ...opts, engines: [engine('quiet', async () => [])] });
    expect(out.results).toEqual([]);
    expect(out.engineErrors).toEqual([]);
  });

  test('allowed and blocked domains filter by host suffix', async () => {
    const engines = [engine('e', async () => [
      { url: 'https://github.com/a', title: 'gh', content: '' },
      { url: 'https://docs.github.com/b', title: 'docs', content: '' },
      { url: 'https://other.org/c', title: 'o', content: '' },
    ])];
    const allowed = await searchWithDiagnostics('q', { ...opts, engines, allowedDomains: ['github.com'] });
    expect(allowed.results.map((r) => r.title)).toEqual(['gh', 'docs']);
    const blocked = await searchWithDiagnostics('q', { ...opts, engines, blockedDomains: ['github.com'] });
    expect(blocked.results.map((r) => r.title)).toEqual(['o']);
  });

  test('default engines path: all three real engines failing via fetch yields AllEnginesFailedError', async () => {
    mockFetch(() => { throw new TypeError('offline'); });
    await expect(search('offline query')).rejects.toThrow(/duckduckgo: .*brave: .*wikipedia: /);
  });

  test('default engines path: one engine answering is enough', async () => {
    mockFetch((url) => url.includes('wikipedia.org')
      ? new Response(JSON.stringify({ query: { search: [{ title: 'T', snippet: 's' }] } }), { status: 200 })
      : html('nope', 403));
    const r = await search('partial query');
    expect(r.map((x) => x.url)).toEqual(['https://en.wikipedia.org/wiki/T']);
  });
});
