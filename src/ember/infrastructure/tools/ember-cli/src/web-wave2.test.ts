// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Blind tests W20, W28, W18, W06 (issue #2381): a name that points at a local address, Esc on a
// hanging fetch, a flaky first DNS lookup, and a search whose engines failed.
import { test, expect, describe, beforeEach } from 'bun:test';
import { buildWebFetchTool, buildWebSearchTool, urlCache, pageCache } from './web-tools.ts';
import type { WebFetchDeps } from './web-tools.ts';
import { blockedResolvedAddress } from './core/private-hosts.ts';
import { makeWebFetch, isTransientNetworkError } from './services/web-http.ts';
import { formatToolResultForDisplay } from './components/tool-result-renderers.ts';

beforeEach(() => {
  for (const c of [urlCache, pageCache]) (c as unknown as { map: Map<string, unknown> }).map.clear();
});

function ctxWith(ac: AbortController) {
  return { abortController: ac } as unknown as Parameters<ReturnType<typeof buildWebFetchTool>['call']>[1];
}

const text200 = (body = 'hello') =>
  new Response(body, { status: 200, headers: { 'content-type': 'text/plain' } });

function deps(over: Partial<WebFetchDeps>): WebFetchDeps {
  return {
    fetchFn: (async () => text200()) as unknown as typeof fetch,
    secondaryModel: async (c) => ({ text: c }),
    htmlToMarkdown: (h) => h,
    ...over,
  };
}

describe('W20: a name that resolves to a private address is refused', () => {
  const table: Record<string, string[]> = {
    'localtest.me': ['127.0.0.1'],
    '127.0.0.1.nip.io': ['127.0.0.1'],
    'v6.test': ['::1'],
    'mapped.test': ['::ffff:127.0.0.1'],
    'meta.test': ['169.254.169.254'],
    'lan.test': ['192.168.1.5'],
    'zero.test': ['0.0.0.0'],
    'ula.test': ['fd12:3456::1'],
    'mixed.test': ['93.184.216.34', '10.0.0.7'],
    'public.test': ['93.184.216.34', '2606:2800:220:1::1'],
  };
  const resolveHost = async (h: string) => {
    if (h in table) return table[h]!;
    throw Object.assign(new Error('nx'), { code: 'ENOTFOUND' });
  };

  test('blockedResolvedAddress', async () => {
    for (const h of ['localtest.me', '127.0.0.1.nip.io', 'v6.test', 'mapped.test', 'meta.test', 'lan.test', 'zero.test', 'ula.test', 'mixed.test']) {
      expect(await blockedResolvedAddress(h, resolveHost)).not.toBeNull();
    }
    expect(await blockedResolvedAddress('public.test', resolveHost)).toBeNull();
    expect(await blockedResolvedAddress('nx.test', resolveHost)).toBeNull(); // does not resolve: the fetch fails by itself
  });

  test('WebFetch refuses http://localtest.me:8765/ before any request is made', async () => {
    let calls = 0;
    const tool = buildWebFetchTool(deps({ resolveHost, fetchFn: (async () => { calls++; return text200(); }) as unknown as typeof fetch }));
    for (const url of ['http://localtest.me:8765/', 'http://127.0.0.1.nip.io:8765/', 'https://v6.test/']) {
      await expect(tool.call({ url, prompt: 'x' }, ctxWith(new AbortController()), undefined as never, undefined as never))
        .rejects.toThrow(/blocked.*private\/reserved/);
    }
    expect(calls).toBe(0);
  });

  test('a public name still works', async () => {
    const tool = buildWebFetchTool(deps({ resolveHost }));
    const r = await tool.call({ url: 'https://public.test/', prompt: 'x' }, ctxWith(new AbortController()), undefined as never, undefined as never);
    expect((r.data as { result: string }).result).toContain('hello');
  });

  test('each same-host redirect hop is checked: www. alias that points at loopback is refused', async () => {
    const seen: string[] = [];
    // public.test -> www.public.test would be permitted; make the alias the private one
    table['www.public.test'] = ['127.0.0.1'];
    const fetchFn2 = (async (u: string) => {
      seen.push(String(u));
      if (String(u) === 'https://public.test/') {
        return new Response('', { status: 302, headers: { location: 'https://www.public.test/', 'content-type': 'text/plain' } });
      }
      return text200('SECRET');
    }) as unknown as typeof fetch;
    const tool = buildWebFetchTool(deps({ resolveHost, fetchFn: fetchFn2 }));
    await expect(tool.call({ url: 'https://public.test/', prompt: 'x' }, ctxWith(new AbortController()), undefined as never, undefined as never))
      .rejects.toThrow(/blocked: redirect/);
    expect(seen).toEqual(['https://public.test/']);
    delete table['www.public.test'];
  });
});

describe('W28: Esc ends a hanging fetch', () => {
  test('WebFetch returns within a second of abort even if the fetch never settles', async () => {
    const tool = buildWebFetchTool(deps({
      resolveHost: async () => ['93.184.216.34'],
      fetchFn: (() => new Promise(() => {})) as unknown as typeof fetch,
    }));
    const ac = new AbortController();
    setTimeout(() => ac.abort(), 50);
    const t0 = Date.now();
    const r = await tool.call({ url: 'https://example.com:81/', prompt: 'x' }, ctxWith(ac), undefined as never, undefined as never);
    expect(Date.now() - t0).toBeLessThan(1000);
    expect((r.data as { result: string }).result).toContain('cancelled');
  });

  test('WebSearch returns within a second of abort', async () => {
    const tool = buildWebSearchTool({ performSearch: () => new Promise(() => {}) });
    const ac = new AbortController();
    setTimeout(() => ac.abort(), 50);
    const t0 = Date.now();
    const r = await tool.call({ query: 'hang forever' }, ctxWith(ac), undefined as never, undefined as never);
    expect(Date.now() - t0).toBeLessThan(1000);
    expect((r.data as { error?: string }).error).toBeTruthy();
  });

  test('makeWebFetch passes the caller signal on: aborting ends a request that honours its signal', async () => {
    const base = ((_u: unknown, init?: RequestInit) => new Promise((_res, rej) => {
      init?.signal?.addEventListener('abort', () => rej(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    })) as unknown as typeof fetch;
    const ac = new AbortController();
    setTimeout(() => ac.abort(), 50);
    const t0 = Date.now();
    await expect(makeWebFetch(base, { timeoutMs: 30_000 })('https://x.test/', { signal: ac.signal })).rejects.toThrow();
    expect(Date.now() - t0).toBeLessThan(1000);
  });
});

describe('W18: a flaky first lookup is retried, a bad answer is not', () => {
  const dnsErr = () => Object.assign(new Error('getaddrinfo EAI_AGAIN x.test'), { code: 'EAI_AGAIN' });

  test('classification', () => {
    expect(isTransientNetworkError(dnsErr())).toBe(true);
    expect(isTransientNetworkError({ code: 'ENOTFOUND' })).toBe(true);
    expect(isTransientNetworkError({ code: 'ECONNRESET' })).toBe(true);
    expect(isTransientNetworkError({ name: 'TimeoutError', message: 'timed out' })).toBe(false);
    expect(isTransientNetworkError({ name: 'AbortError' })).toBe(false);
    expect(isTransientNetworkError(new Error('response too large'))).toBe(false);
  });

  test('two lookup failures then success: one request resolves', async () => {
    let n = 0;
    const base = (async () => { if (++n < 3) throw dnsErr(); return text200('ok'); }) as unknown as typeof fetch;
    const r = await makeWebFetch(base, { retryDelaysMs: [1, 1] })('https://x.test/');
    expect(n).toBe(3);
    expect(await r.text()).toBe('ok');
  });

  test('HTTP 503/404 are returned as they are, not retried', async () => {
    for (const status of [503, 404, 429]) {
      let n = 0;
      const base = (async () => { n++; return new Response('x', { status }); }) as unknown as typeof fetch;
      expect((await makeWebFetch(base, { retryDelaysMs: [1, 1] })('https://x.test/')).status).toBe(status);
      expect(n).toBe(1);
    }
  });

  test('an aborted request is not retried', async () => {
    let n = 0;
    const ac = new AbortController();
    const base = (async () => { n++; ac.abort(); throw dnsErr(); }) as unknown as typeof fetch;
    await expect(makeWebFetch(base, { retryDelaysMs: [1, 1] })('https://x.test/', { signal: ac.signal })).rejects.toThrow();
    expect(n).toBe(1);
  });
});

describe('W06: a search says which engines failed', () => {
  const failedNote = 'Note: search engine brave failed (HTTP 429).';
  test('the tool result names the failed engine and does not claim nothing exists', async () => {
    const tool = buildWebSearchTool({ performSearch: async () => ({ results: [], notes: [failedNote] }) });
    const r = await tool.call({ query: 'quoted "operator" query' }, ctxWith(new AbortController()), undefined as never, undefined as never);
    const out = JSON.stringify(r.data);
    expect(out).toContain('brave failed (HTTP 429)');
    expect(out).toContain('engines did not answer');
  });

  test('the UI line shows the failed engines, with and without hits', () => {
    const empty = formatToolResultForDisplay(JSON.stringify({ query: 'q', results: ['No results found.', failedNote] }));
    expect(empty).toContain('No results for "q"');
    expect(empty).toContain('search engine brave failed (HTTP 429).');
    const some = formatToolResultForDisplay(JSON.stringify({
      query: 'q',
      results: [failedNote, { content: [{ url: 'https://a.example/', title: 'A' }] }],
    }));
    expect(some).toContain('1 result for "q"');
    expect(some).toContain('search engine brave failed (HTTP 429).');
  });
});

// W03: a long unbroken line (raw JSON in a code fence, a long URL) must stay inside the chat column.
describe('W03: long unbroken lines are hard-wrapped inside the chat column', () => {
  async function panel(text: string, width: number): Promise<string[]> {
    const React = (await import('react')).default;
    const { Box } = await import('./ink/components.ts');
    const { mountInk } = await import('./ink/reconciler.ts');
    const { buildFrame, parseRenderedIntoFrame, StylePool } = await import('./ink/rendering-pipeline.ts');
    const { AssistantTextMessage } = await import('./components/message-renderers.ts');
    const columns = width + 24;
    let output = '';
    mountInk(
      React.createElement(Box, { width: columns, flexDirection: 'row' },
        React.createElement(Box, { width, flexDirection: 'column', overflow: 'hidden' }, React.createElement(AssistantTextMessage, { text, width })),
        React.createElement(Box, { width: 20 }, React.createElement(AssistantTextMessage, { text: 'PANEL', width: 20 }))),
      { stream: { write(c: string) { output += c; } }, stdout: { columns, rows: 30 } },
    );
    const frame = buildFrame(columns, 30);
    parseRenderedIntoFrame(output, frame, new StylePool());
    return frame.cells.map((row) => row.map((c) => c.char).join('').trimEnd());
  }

  for (const [name, text, tail] of [
    ['code fence', '```json\n{"k":"' + 'v'.repeat(150) + 'END"}\n```', 'END"}'],
    ['long URL', 'see https://example.com/' + 'a'.repeat(150) + 'END', 'END'],
    ['long word', 'word ' + 'b'.repeat(150) + 'END', 'END'],
  ] as const) {
    test(name, async () => {
      const lines = await panel(text, 40);
      // the whole line is there (wrapped, not clipped) and nothing crosses into the right panel
      expect(lines.join('').replace(/\s+/g, '')).toContain(tail);
      for (const l of lines) {
        const at = l.indexOf('PANEL');
        if (at >= 0) expect(at).toBeLessThanOrEqual(42);
        expect(l.length).toBeLessThanOrEqual(44 + 20);
      }
      expect(lines.filter((l) => l.includes('PANEL')).length).toBe(1);
    });
  }
});
