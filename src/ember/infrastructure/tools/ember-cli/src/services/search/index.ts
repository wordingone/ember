// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// In-process, keyless meta-search (ported from avir-cli). Takes a query, fans out to
// DuckDuckGo / Brave / Wikipedia in parallel, merges + dedups with inverse-position
// scoring. Every engine failure is caught and reported by name; when ALL engines fail
// the search throws one error that lists each engine's failure (never a silent empty).

import { Cache } from './cache.ts'
import { mergeResults, type EngineResults, type RawResult } from './merger.ts'
import * as duckduckgo from './engines/duckduckgo.ts'
import * as brave from './engines/brave.ts'
import * as wikipedia from './engines/wikipedia.ts'

export interface SearchResult {
  title: string
  url: string
  snippet: string
  score: number
}

export interface SearchEngine {
  name: string
  weight: number
  search: (query: string, opts: Record<string, unknown>) => Promise<RawResult[]>
}

export interface SearchOutcome {
  results: SearchResult[]
  /** One entry per engine that threw or timed out. */
  engineErrors: { engine: string; error: string }[]
  /** Engines that answered without error (possibly with zero results). */
  engineOk: string[]
}

export class AllEnginesFailedError extends Error {
  readonly engineErrors: { engine: string; error: string }[]
  constructor(engineErrors: { engine: string; error: string }[]) {
    super(
      'All search engines failed: ' + engineErrors.map(e => `${e.engine}: ${e.error}`).join('; '),
    )
    this.name = 'AllEnginesFailedError'
    this.engineErrors = engineErrors
  }
}

export const DEFAULT_ENGINES: readonly SearchEngine[] = [duckduckgo, brave, wikipedia]

const ENGINE_TIMEOUT_MS = 10_000
const MIN_FETCH_GAP_MS = 1000

// 15-minute TTL query cache (stores UNFILTERED merged results; domain filters apply after)
const queryCache = new Cache<SearchResult[]>(15 * 60 * 1000)
let lastFetchTime = 0

export function clearSearchCache(): void {
  queryCache.clear()
  lastFetchTime = 0
}

function hostMatches(url: string, domains: string[], onParseError: boolean): boolean {
  try {
    const hostname = new URL(url).hostname
    return domains.some(d => hostname === d || hostname.endsWith('.' + d))
  } catch {
    return onParseError
  }
}

async function runEngine(engine: SearchEngine, query: string, timeoutMs: number): Promise<EngineResults> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    const results = await Promise.race([
      engine.search(query, {}),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`timeout after ${timeoutMs}ms`)), timeoutMs)
      }),
    ])
    return { engine: engine.name, weight: engine.weight, results: results ?? [] }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return { engine: engine.name, weight: engine.weight, results: [], error: msg || 'unknown error' }
  } finally {
    if (timer) clearTimeout(timer)
  }
}

export async function searchWithDiagnostics(
  query: string,
  opts: {
    allowedDomains?: string[]
    blockedDomains?: string[]
    engines?: readonly SearchEngine[]
    engineTimeoutMs?: number
    /** Skip the 1s upstream rate-limit gap (tests). */
    noRateLimit?: boolean
  } = {},
): Promise<SearchOutcome> {
  const engines = opts.engines ?? DEFAULT_ENGINES
  const cacheKey = query.toLowerCase().trim()
  let merged = opts.engines ? undefined : queryCache.get(cacheKey)
  let engineErrors: { engine: string; error: string }[] = []
  let engineOk: string[] = engines.map(e => e.name)

  if (!merged) {
    if (!opts.noRateLimit) {
      const wait = MIN_FETCH_GAP_MS - (Date.now() - lastFetchTime)
      if (wait > 0) await new Promise(r => setTimeout(r, wait))
      lastFetchTime = Date.now()
    }

    const settled = await Promise.all(
      engines.map(e => runEngine(e, query, opts.engineTimeoutMs ?? ENGINE_TIMEOUT_MS)),
    )
    engineErrors = settled.filter(s => s.error).map(s => ({ engine: s.engine, error: s.error! }))
    engineOk = settled.filter(s => !s.error).map(s => s.engine)
    if (engineOk.length === 0) throw new AllEnginesFailedError(engineErrors)

    merged = mergeResults(settled).results.map(r => ({
      title: r.title,
      url: r.url,
      snippet: r.content,
      score: r.score,
    }))
    if (!opts.engines) queryCache.set(cacheKey, merged)
  }

  let filtered = merged
  if (opts.allowedDomains?.length) {
    const allowed = opts.allowedDomains
    filtered = filtered.filter(r => hostMatches(r.url, allowed, false))
  }
  if (opts.blockedDomains?.length) {
    const blocked = opts.blockedDomains
    filtered = filtered.filter(r => !hostMatches(r.url, blocked, true))
  }
  return { results: filtered, engineErrors, engineOk }
}

/** avir-compatible entry: returns results, throws AllEnginesFailedError if every engine failed. */
export async function search(
  query: string,
  opts: { allowedDomains?: string[]; blockedDomains?: string[] } = {},
): Promise<SearchResult[]> {
  return (await searchWithDiagnostics(query, opts)).results
}
