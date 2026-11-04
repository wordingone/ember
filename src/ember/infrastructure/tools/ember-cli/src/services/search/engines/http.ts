// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// fetch() wrapper with UA rotation, timeouts, retries (zero dependencies)

const USER_AGENTS = [
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
]

let uaIndex = 0
function nextUA(): string {
  return USER_AGENTS[uaIndex++ % USER_AGENTS.length]!
}

export interface HttpOpts {
  timeout?: number
  retry?: number
  fetchMode?: string
  fetchSite?: string
  fetchDest?: string
  headers?: Record<string, string>
  cookies?: Record<string, string>
  contentType?: string
}

export interface HttpResponse {
  status: number
  text: string
  headers: Headers
}

function buildHeaders(opts: HttpOpts = {}): Record<string, string> {
  const h: Record<string, string> = {
    'User-Agent': nextUA(),
    Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Sec-Fetch-Mode': opts.fetchMode ?? 'navigate',
    'Sec-Fetch-Site': opts.fetchSite ?? 'none',
    'Sec-Fetch-Dest': opts.fetchDest ?? 'document',
    ...opts.headers,
  }
  if (opts.cookies) {
    h['Cookie'] = Object.entries(opts.cookies)
      .map(([k, v]) => `${k}=${v}`)
      .join('; ')
  }
  return h
}

const TRANSIENT_STATUS = new Set([429, 500, 502, 503, 504])

/**
 * One fetch attempt plus up to `retry` retries. Transient = network error,
 * timeout, or HTTP 429/5xx. A non-transient HTTP status (e.g. 403) is returned
 * to the caller untouched so the engine can name it in its own error.
 */
async function doFetch(
  url: string,
  fetchOpts: RequestInit,
  timeout: number,
  retry: number,
): Promise<HttpResponse> {
  try {
    const res = await globalThis.fetch(url, { ...fetchOpts, signal: AbortSignal.timeout(timeout) })
    if (retry > 0 && TRANSIENT_STATUS.has(res.status)) {
      return doFetch(url, fetchOpts, timeout, retry - 1)
    }
    return { status: res.status, text: await res.text(), headers: res.headers }
  } catch (err) {
    if (retry > 0) return doFetch(url, fetchOpts, timeout, retry - 1)
    throw err
  }
}

export async function httpGet(url: string, opts: HttpOpts = {}): Promise<HttpResponse> {
  const timeout = opts.timeout ?? 10000
  return doFetch(
    url,
    {
      method: 'GET',
      headers: buildHeaders(opts),
      redirect: 'follow',
    },
    timeout,
    opts.retry ?? 1,
  )
}

export async function httpPost(
  url: string,
  body: string,
  opts: HttpOpts = {},
): Promise<HttpResponse> {
  const timeout = opts.timeout ?? 10000
  const headers = buildHeaders(opts)
  if (typeof body === 'string') {
    headers['Content-Type'] = opts.contentType ?? 'application/x-www-form-urlencoded'
  }
  return doFetch(
    url,
    {
      method: 'POST',
      headers,
      body,
      redirect: 'follow',
    },
    timeout,
    opts.retry ?? 1,
  )
}
