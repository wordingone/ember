// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// web-fetch-stack.test.ts — html->markdown, fetch wrapper (timeout/retry/cap), local-model summary.

import { test, expect, describe } from 'bun:test';
import { htmlToMarkdown } from './web-markdown.ts';
import { makeWebFetch } from './web-http.ts';
import { summariseWithLocalModel, truncatedFallback, stripThinking, FALLBACK_CHARS } from './web-model.ts';

describe('htmlToMarkdown', () => {
  test('headings, paragraphs, emphasis, inline code', () => {
    const md = htmlToMarkdown('<html><head><title>T</title></head><body><h1>Hi</h1><p>a <b>bold</b> and <em>it</em> <code>x()</code></p></body></html>');
    expect(md).toBe('# Hi\n\na **bold** and *it* `x()`');
  });
  test('adds <title> as heading when body lacks it', () => {
    expect(htmlToMarkdown('<head><title>Example Domain</title></head><body><p>text</p></body>')).toBe('# Example Domain\n\ntext');
  });
  test('links are absolutised against baseUrl; javascript: links dropped to text', () => {
    const md = htmlToMarkdown('<p><a href="/docs">Docs</a> <a href="javascript:void(0)">x</a></p>', 'https://ex.com/a/b');
    expect(md).toBe('[Docs](https://ex.com/docs) x');
  });
  test('lists, ordered and unordered', () => {
    const md = htmlToMarkdown('<ul><li>a</li><li>b</li></ul><ol><li>one</li><li>two</li></ol>');
    expect(md).toContain('- a\n- b');
    expect(md).toContain('1. one\n2. two');
  });
  test('pre blocks keep whitespace, fenced', () => {
    const md = htmlToMarkdown('<pre><code>line1\n  line2</code></pre>');
    expect(md).toBe('```\nline1\n  line2\n```');
  });
  test('drops script/style/comments, decodes entities', () => {
    const md = htmlToMarkdown('<body><script>alert(1)</script><style>p{}</style><!-- c --><p>a &amp; b &lt;c&gt;</p></body>');
    expect(md).toBe('a & b <c>');
  });
  test('tables render as pipe rows', () => {
    const md = htmlToMarkdown('<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>');
    expect(md).toContain('| A | B |');
    expect(md).toContain('| 1 | 2 |');
  });
  test('blockquote and malformed markup do not throw', () => {
    expect(htmlToMarkdown('<blockquote>q</blockquote>')).toBe('> q');
    expect(() => htmlToMarkdown('<p>unclosed <b>bold <i>x</p></u> < 3 <')).not.toThrow();
    expect(htmlToMarkdown('')).toBe('');
  });
});

describe('makeWebFetch', () => {
  test('retries a failed lookup/connection but not a 503; sets a user-agent', async () => {
    let n = 0;
    const seen: string[] = [];
    const base = (async (_u: unknown, init?: RequestInit) => {
      n++;
      seen.push(new Headers(init?.headers).get('user-agent') ?? '');
      if (n === 1) throw Object.assign(new TypeError('reset'), { code: 'ECONNRESET' });
      if (n === 2) return new Response('x', { status: 503 });
      return new Response('fine', { status: 200, headers: { 'content-type': 'text/plain' } });
    }) as unknown as typeof fetch;
    const f = makeWebFetch(base, { retryDelaysMs: [1] });
    // attempt 1 resets -> retry (attempt 2 returns 503, an HTTP status is never retried) -> 503 returned
    const r = await f('https://x.test/');
    expect(n).toBe(2);
    expect(r.status).toBe(503);
    expect(seen[0]).toContain('Mozilla');
  });
  test('rejects a declared oversized body', async () => {
    const base = (async () => new Response('x', { status: 200, headers: { 'content-length': '999999' } })) as unknown as typeof fetch;
    await expect(makeWebFetch(base, { maxBytes: 1000 })('https://x.test/')).rejects.toThrow(/too large/);
  });
  test('rejects a streamed body that exceeds the cap', async () => {
    const big = 'a'.repeat(5000);
    const base = (async () => new Response(big, { status: 200 })) as unknown as typeof fetch;
    await expect(makeWebFetch(base, { maxBytes: 1000 })('https://x.test/')).rejects.toThrow(/exceeded/);
  });
  test('passes small bodies and 3xx untouched', async () => {
    const base = (async () => new Response('hello', { status: 200, headers: { 'content-type': 'text/plain' } })) as unknown as typeof fetch;
    const r = await makeWebFetch(base)('https://x.test/');
    expect(await r.text()).toBe('hello');
    const redirect = (async () => new Response(null, { status: 301, headers: { location: 'https://y.test/' } })) as unknown as typeof fetch;
    expect((await makeWebFetch(redirect)('https://x.test/', { redirect: 'manual' })).status).toBe(301);
  });
});

describe('summariseWithLocalModel', () => {
  test('no EMBER_MODEL_URL returns the markdown (truncated) instead of failing', async () => {
    const r = await summariseWithLocalModel('c'.repeat(FALLBACK_CHARS + 50), 'p', false, {});
    expect(r.text).toContain('EMBER_MODEL_URL not set');
    expect(r.text).toContain(`Truncated to ${FALLBACK_CHARS}`);
  });
  test('uses the OpenAI-compatible endpoint and strips <think>', async () => {
    let body: any; let url = '';
    const fetchFn = (async (u: string, init?: RequestInit) => {
      url = u; body = JSON.parse(String(init?.body));
      return new Response(JSON.stringify({ choices: [{ message: { content: '<think>hmm</think>The answer.' } }] }), { status: 200 });
    }) as unknown as typeof fetch;
    const r = await summariseWithLocalModel('PAGE', 'what?', false, { EMBER_MODEL_URL: 'http://127.0.0.1:9/v1', EMBER_NCTX_PROBE_OVERRIDE: '8192' }, fetchFn);
    expect(url).toBe('http://127.0.0.1:9/v1/chat/completions');
    expect(body.messages[0].content).toContain('PAGE');
    expect(body.messages[0].content).toContain('what?');
    expect(body.stream).toBe(false);
    expect(r.text).toBe('The answer.');
  });
  test('model HTTP error, empty text and network failure all fall back to markdown', async () => {
    const env = { EMBER_MODEL_URL: 'http://127.0.0.1:9', EMBER_NCTX_PROBE_OVERRIDE: '4096' };
    const err500 = (async () => new Response('x', { status: 500 })) as unknown as typeof fetch;
    expect((await summariseWithLocalModel('PAGE', 'p', false, env, err500)).text).toContain('model HTTP 500');
    const empty = (async () => new Response(JSON.stringify({ choices: [{ message: { content: '' } }] }), { status: 200 })) as unknown as typeof fetch;
    expect((await summariseWithLocalModel('PAGE', 'p', false, env, empty)).text).toContain('empty');
    const down = (async () => { throw new TypeError('ECONNREFUSED'); }) as unknown as typeof fetch;
    const r = await summariseWithLocalModel('PAGE', 'p', false, env, down);
    expect(r.text).toContain('ECONNREFUSED');
    expect(r.text).toContain('PAGE');
  });
  test('helpers', () => {
    expect(stripThinking('<think>a</think> b')).toBe('b');
    expect(truncatedFallback('x', 'why')).toContain('why');
  });
});
