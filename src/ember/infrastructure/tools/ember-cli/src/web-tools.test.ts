// Tests for web-tools.ts
// WebFetch: AC1-AC8; WebSearch: AC1-AC5.
// Never makes real network calls — injects fake fetch via `as unknown as typeof fetch`.

import { test, expect, describe, beforeEach } from 'bun:test';
import {
  buildWebFetchTool,
  buildWebSearchTool,
  isPreapprovedUrl,
  isBlockedHost,
  upgradeHttpToHttps,
  isPermittedRedirect,
  urlCache,
} from './web-tools.ts';
import type { WebFetchDeps, SearchDeps, WebFetchInput, WebSearchInput, WebSearchOutput } from './web-tools.ts';

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeCtx(): Parameters<ReturnType<typeof buildWebFetchTool>['call']>[1] {
  return {
    options: {},
    abortController: new AbortController(),
    getAppState: () => ({}),
    setAppState: async () => {},
    setAppStateForTasks: () => {},
    readFileState: new Map(),
    messages: [],
    appendSystemMessage: () => {},
    nestedMemoryAttachmentTriggers: new Set(),
    loadedNestedMemoryPaths: new Set(),
    dynamicSkillDirTriggers: new Set(),
    discoveredSkillNames: new Set(),
    fileReadingLimits: { maxTokens: 100_000, maxSizeBytes: 10_000_000 },
    globLimits: { maxResults: 1000 },
    toolUseId: 'test-web-id',
  } as unknown as Parameters<ReturnType<typeof buildWebFetchTool>['call']>[1];
}

/**
 * Create a fake fetch function that returns the given response.
 * Cast via `as unknown as typeof fetch` per spec requirements.
 */
function makeFakeFetch(
  statusCode: number,
  contentType: string,
  body: string,
  headers: Record<string, string> = {},
): typeof fetch {
  return (async (_url: string | URL | Request, _init?: RequestInit) => {
    return new Response(body, {
      status: statusCode,
      statusText: 'OK',
      headers: {
        'content-type': contentType,
        ...headers,
      },
    });
  }) as unknown as typeof fetch;
}

function makeMarkdownFetch(body: string): typeof fetch {
  return makeFakeFetch(200, 'text/markdown', body);
}

function makeHtmlFetch(body: string): typeof fetch {
  return makeFakeFetch(200, 'text/html', body);
}

function makeRedirectFetch(location: string, status = 301): typeof fetch {
  return (async (_url: string | URL | Request, init?: RequestInit) => {
    if ((init as RequestInit & { redirect?: string })?.redirect === 'manual') {
      return new Response('', {
        status,
        statusText: 'Moved Permanently',
        headers: { location, 'content-type': 'text/plain' },
      });
    }
    // Follow mode
    return new Response('final content', {
      status: 200,
      statusText: 'OK',
      headers: { 'content-type': 'text/plain' },
    });
  }) as unknown as typeof fetch;
}

const nopModel: WebFetchDeps['secondaryModel'] = async (content, _prompt, _preapproved) => ({
  text: `MODEL_PROCESSED: ${content.slice(0, 50)}`,
});

const identityHtml: WebFetchDeps['htmlToMarkdown'] = (html: string) => html;

function makeFetchDeps(overrides: Partial<WebFetchDeps> = {}): WebFetchDeps {
  return {
    fetchFn: makeFakeFetch(200, 'text/plain', 'plain text content'),
    secondaryModel: nopModel,
    htmlToMarkdown: identityHtml,
    ...overrides,
  };
}

// Clear url cache before each test
beforeEach(() => {
  // Access internal cache and clear it
  const cache = urlCache as unknown as { map: Map<string, unknown> };
  if (cache && cache.map instanceof Map) {
    cache.map.clear();
  }
});

// ---------------------------------------------------------------------------
// Unit helpers
// ---------------------------------------------------------------------------

describe('isPreapprovedUrl', () => {
  test('known cloud domain is no longer preapproved', () => {
    expect(isPreapprovedUrl('https://docs.example.com/en/api')).toBe(false);
  });
  test('www. prefix stripped correctly', () => {
    expect(isPreapprovedUrl('https://www.npmjs.com/package/zod')).toBe(true);
  });
  test('unknown domain is not preapproved', () => {
    expect(isPreapprovedUrl('https://example.com/page')).toBe(false);
  });
  test('github.com/wordingone path is no longer preapproved', () => {
    expect(isPreapprovedUrl('https://github.com/vendor-org/vendor-sdk-python')).toBe(false);
  });
  test('github.com/other path is not preapproved', () => {
    expect(isPreapprovedUrl('https://github.com/expressjs/express')).toBe(false);
  });
});

describe('isBlockedHost', () => {
  test('localhost is blocked', () => {
    expect(isBlockedHost('localhost')).toBe(true);
  });
  test('127.0.0.1 is blocked', () => {
    expect(isBlockedHost('127.0.0.1')).toBe(true);
  });
  test('192.168.1.1 is blocked', () => {
    expect(isBlockedHost('192.168.1.1')).toBe(true);
  });
  test('cloud metadata is blocked', () => {
    expect(isBlockedHost('169.254.169.254')).toBe(true);
  });
  test('public IP is not blocked', () => {
    expect(isBlockedHost('8.8.8.8')).toBe(false);
  });
});

describe('upgradeHttpToHttps', () => {
  test('upgrades http:// to https://', () => {
    expect(upgradeHttpToHttps('http://example.com/page')).toBe('https://example.com/page');
  });
  test('leaves https:// unchanged', () => {
    expect(upgradeHttpToHttps('https://example.com/page')).toBe('https://example.com/page');
  });
});

describe('isPermittedRedirect', () => {
  test('www to non-www is permitted', () => {
    expect(isPermittedRedirect('https://www.example.com/', 'https://example.com/')).toBe(true);
  });
  test('non-www to www is permitted', () => {
    expect(isPermittedRedirect('https://example.com/', 'https://www.example.com/')).toBe(true);
  });
  test('cross-host redirect is not permitted', () => {
    expect(isPermittedRedirect('https://example.com/', 'https://other.com/')).toBe(false);
  });
  test('http to https same host', () => {
    // protocol must match (after HTTP upgrade already done)
    expect(isPermittedRedirect('https://example.com/', 'http://example.com/')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// WebFetch ACs
// ---------------------------------------------------------------------------

describe('WebFetch', () => {
  test('AC1: preapproved URL with text/markdown returns raw without model processing', async () => {
    let modelCalled = false;
    const deps = makeFetchDeps({
      fetchFn: makeMarkdownFetch('# Python Docs\nContent here.'),
      secondaryModel: async (content, prompt, _approved) => {
        modelCalled = true;
        return { text: 'model output' };
      },
    });
    const tool = buildWebFetchTool(deps);
    const result = await tool.call(
      { url: 'https://docs.python.org/en/intro', prompt: 'What is this?' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(modelCalled).toBe(false);
    const data = result.data as { result: string };
    expect(data.result).toContain('Python Docs');
  });

  test('AC2: non-preapproved URL processes through secondary model', async () => {
    let modelCalled = false;
    const deps = makeFetchDeps({
      fetchFn: makeHtmlFetch('<html><body>Content</body></html>'),
      secondaryModel: async (_content, _prompt, _approved) => {
        modelCalled = true;
        return { text: 'model processed output' };
      },
    });
    const tool = buildWebFetchTool(deps);
    const result = await tool.call(
      { url: 'https://example.com/page', prompt: 'Summarize' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(modelCalled).toBe(true);
    const data = result.data as { result: string };
    expect(data.result).toBe('model processed output');
  });

  test('AC3: HTTP URL is upgraded to HTTPS before fetching', async () => {
    const fetchedUrls: string[] = [];
    const fakeFetch = (async (url: string | URL | Request, _init?: RequestInit) => {
      fetchedUrls.push(String(url));
      return new Response('content', { status: 200, headers: { 'content-type': 'text/plain' } });
    }) as unknown as typeof fetch;
    const deps = makeFetchDeps({ fetchFn: fakeFetch });
    const tool = buildWebFetchTool(deps);
    await tool.call(
      { url: 'http://docs.ember.ai/page', prompt: 'read' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(fetchedUrls.some((u) => u.startsWith('https://'))).toBe(true);
    expect(fetchedUrls.some((u) => u.startsWith('http://'))).toBe(false);
  });

  test('AC4: private/reserved addresses are blocked', async () => {
    const deps = makeFetchDeps();
    const tool = buildWebFetchTool(deps);
    await expect(
      tool.call(
        { url: 'https://127.0.0.1/admin', prompt: 'read' },
        makeCtx(),
        async () => true,
        undefined,
      ),
    ).rejects.toThrow('blocked');
  });

  test('AC5: cached URL returns immediately without re-fetching', async () => {
    let fetchCount = 0;
    const fakeFetch = (async (_url: string | URL | Request, _init?: RequestInit) => {
      fetchCount++;
      return new Response('content', {
        status: 200,
        headers: { 'content-type': 'text/plain' },
      });
    }) as unknown as typeof fetch;
    const deps = makeFetchDeps({ fetchFn: fakeFetch });
    const tool = buildWebFetchTool(deps);
    // First call
    await tool.call(
      { url: 'https://docs.python.org/cached', prompt: 'read' },
      makeCtx(),
      async () => true,
      undefined,
    );
    // Second call — should hit cache
    await tool.call(
      { url: 'https://docs.python.org/cached', prompt: 'read' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(fetchCount).toBe(1);
  });

  test('AC6: cross-host redirect returns redirect info instead of following', async () => {
    const deps = makeFetchDeps({
      fetchFn: makeRedirectFetch('https://other-host.com/new-page'),
    });
    const tool = buildWebFetchTool(deps);
    const result = await tool.call(
      { url: 'https://example.com/moved', prompt: 'read' },
      makeCtx(),
      async () => true,
      undefined,
    );
    const data = result.data as { result: string };
    expect(data.result).toContain('other-host.com');
    expect(data.result).toContain('redirect');
  });

  test('AC7: binary content is persisted to disk', async () => {
    const pngData = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
    const fakeFetch = (async (_url: string | URL | Request, init?: RequestInit) => {
      if ((init as RequestInit & { redirect?: string })?.redirect === 'manual') {
        // Not a redirect
        return new Response('', { status: 200, headers: { location: '' } });
      }
      return new Response(pngData, {
        status: 200,
        headers: { 'content-type': 'image/png' },
      });
    }) as unknown as typeof fetch;
    let persistCalled = false;
    const deps = makeFetchDeps({
      fetchFn: fakeFetch,
      persistBinary: async (_data, _mimeType, _url) => {
        persistCalled = true;
        return '/tmp/binary-blob.png';
      },
    });
    const tool = buildWebFetchTool(deps);
    const result = await tool.call(
      { url: 'https://example.com/image.png', prompt: 'read' },
      makeCtx(),
      async () => true,
      undefined,
    );
    expect(persistCalled).toBe(true);
    const data = result.data as { result: string };
    expect(data.result).toContain('/tmp/binary-blob.png');
  });

  test('AC8: content longer than 100000 chars is truncated with notice', async () => {
    const longContent = 'x'.repeat(110_000);
    const deps = makeFetchDeps({
      fetchFn: makeMarkdownFetch(longContent),
    });
    const tool = buildWebFetchTool(deps);
    const result = await tool.call(
      { url: 'https://docs.python.org/long', prompt: 'read' },
      makeCtx(),
      async () => true,
      undefined,
    );
    const data = result.data as { result: string };
    expect(data.result.length).toBeLessThanOrEqual(100_200); // 100k + short notice
    expect(data.result).toContain('truncated');
  });
});

// ---------------------------------------------------------------------------
// WebSearch ACs
// ---------------------------------------------------------------------------

describe('WebSearch', () => {
  function makeSearchDeps(results = [{
    url: 'https://example.com',
    title: 'Example',
    description: 'An example site',
    score: 1.0,
  }]): SearchDeps {
    return {
      async performSearch(_query: string, _opts: unknown) {
        return results;
      },
    };
  }

  test('AC1: valid query returns structured results and reminder', async () => {
    const deps = makeSearchDeps();
    const tool = buildWebSearchTool(deps);
    const result = await tool.call(
      { query: 'hello world' },
      makeCtx(),
      async () => true,
      undefined,
    );
    const data = result.data as WebSearchOutput;
    expect(data.query).toBe('hello world');
    expect(Array.isArray(data.results)).toBe(true);
    // AC4: sources reminder appended
    const hasReminder = data.results.some(
      (r) => typeof r === 'string' && r.includes('Sources'),
    );
    expect(hasReminder).toBe(true);
  });

  test('AC2: allowed_domains filters results', async () => {
    const deps: SearchDeps = {
      async performSearch(_query, _opts) {
        return [
          { url: 'https://docs.python.org/page', title: 'Python', description: '', score: 1 },
          { url: 'https://other.com/page', title: 'Other', description: '', score: 0.5 },
        ];
      },
    };
    const tool = buildWebSearchTool(deps);
    const result = await tool.call(
      { query: 'python docs', allowed_domains: ['docs.python.org'] },
      makeCtx(),
      async () => true,
      undefined,
    );
    const entries = (result.data as WebSearchOutput).results.filter(
      (r) => typeof r === 'object' && r !== null && 'content' in r,
    ) as Array<{ content: Array<{ url: string }> }>;
    const urls = entries.flatMap((e) => e.content.map((c) => c.url));
    expect(urls.every((u) => u.includes('docs.python.org'))).toBe(true);
    expect(urls.some((u) => u.includes('other.com'))).toBe(false);
  });

  test('AC3: specifying both allowed_domains and blocked_domains throws validation error', async () => {
    const deps = makeSearchDeps();
    const tool = buildWebSearchTool(deps);
    await expect(
      tool.call(
        { query: 'test', allowed_domains: ['a.com'], blocked_domains: ['b.com'] },
        makeCtx(),
        async () => true,
        undefined,
      ),
    ).rejects.toThrow('mutually exclusive');
  });

  test('AC4: result always includes sources reminder message', async () => {
    const deps = makeSearchDeps();
    const tool = buildWebSearchTool(deps);
    const result = await tool.call(
      { query: 'search term' },
      makeCtx(),
      async () => true,
      undefined,
    );
    const hasReminder = (result.data as WebSearchOutput).results.some(
      (r) => typeof r === 'string' && r.includes('Sources'),
    );
    expect(hasReminder).toBe(true);
  });

  test('AC5: two progress events emitted (start + complete)', async () => {
    const deps = makeSearchDeps();
    const tool = buildWebSearchTool(deps);
    const events: unknown[] = [];
    await tool.call(
      { query: 'progress test' },
      makeCtx(),
      async () => true,
      undefined,
      (event) => events.push(event),
    );
    const types = events.map((e) => (e as { type: string }).type);
    expect(types).toContain('web_search_start');
    expect(types).toContain('web_search_complete');
  });
});
