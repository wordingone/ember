// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// web-http.ts — fetch wrapper for WebFetch: per-request timeout, a short retry on a failed
// DNS lookup or connection (never on a timeout, an abort or an HTTP status), browser-ish User-Agent, and a hard
// body cap (10 MB) so a huge page cannot exhaust memory.

export const MAX_BODY_BYTES = 10 * 1024 * 1024;
export const FETCH_TIMEOUT_MS = 60_000;
const RETRY_DELAYS_MS = [300, 900];
const TRANSIENT_CODES = /ENOTFOUND|EAI_AGAIN|ECONNRESET|ConnectionRefused|ConnectionClosed|FailedToOpenSocket/i;
const TRANSIENT_TEXT = /typo in the url|ENOTFOUND|EAI_AGAIN|ECONNRESET|socket connection was closed|Unable to connect/i;

/** A failure of the lookup or the connection itself (blind test W18), as opposed to a bad answer, a timeout or an abort. */
export function isTransientNetworkError(e: unknown): boolean {
  const err = e as { code?: string; name?: string; message?: string } | null;
  if (!err) return false;
  if (err.name === 'AbortError' || err.name === 'TimeoutError') return false;
  return TRANSIENT_CODES.test(err.code ?? '') || TRANSIENT_TEXT.test(err.message ?? '');
}
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 EmberCLI';

async function capBody(res: Response, maxBytes: number): Promise<Response> {
  const declared = Number(res.headers.get('content-length') ?? '0');
  if (declared > maxBytes) throw new Error(`response too large (${declared} bytes > ${maxBytes})`);
  // 3xx and empty bodies need no buffering.
  if (!res.body || (res.status >= 300 && res.status < 400)) return res;
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel().catch(() => {});
      throw new Error(`response exceeded ${maxBytes} bytes`);
    }
    chunks.push(value);
  }
  const buf = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) { buf.set(c, off); off += c.byteLength; }
  return new Response(buf, { status: res.status, statusText: res.statusText, headers: res.headers });
}

export function makeWebFetch(
  baseFetch: typeof fetch = ((i: string | URL | Request, n?: RequestInit) => globalThis.fetch(i, n)) as typeof fetch,
  opts: { timeoutMs?: number; maxBytes?: number; retryDelaysMs?: number[] } = {},
): typeof fetch {
  const timeoutMs = opts.timeoutMs ?? FETCH_TIMEOUT_MS;
  const maxBytes = opts.maxBytes ?? MAX_BODY_BYTES;
  const delayFor = opts.retryDelaysMs ?? RETRY_DELAYS_MS;
  const attempt = async (input: string | URL | Request, init: RequestInit | undefined, tried: number): Promise<Response> => {
    try {
      const headers = new Headers(init?.headers);
      if (!headers.has('user-agent')) headers.set('user-agent', UA);
      if (!headers.has('accept')) headers.set('accept', 'text/html,application/xhtml+xml,text/markdown,text/plain,application/json;q=0.9,*/*;q=0.5');
      // The caller's signal (Esc) and the timeout both end the request; the timeout used to replace
      // the caller's signal, so Esc did nothing until the timeout fired (blind test W28).
      const signal = init?.signal ? AbortSignal.any([init.signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs);
      const res = await baseFetch(input, { ...init, headers, signal });
      return await capBody(res, maxBytes);
    } catch (e) {
      // One or two quick retries for a lookup/connection failure only; never for an abort, a
      // timeout, an oversized body or an HTTP status.
      if (tried < delayFor.length && !init?.signal?.aborted && isTransientNetworkError(e)) {
        await new Promise((r) => setTimeout(r, delayFor[tried]));
        if (init?.signal?.aborted) throw e;
        return attempt(input, init, tried + 1);
      }
      throw e;
    }
  };
  return ((input: string | URL | Request, init?: RequestInit) => attempt(input, init, 0)) as typeof fetch;
}
