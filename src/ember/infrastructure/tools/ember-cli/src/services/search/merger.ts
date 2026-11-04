// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Result deduplication + inverse-position scoring (SearXNG algorithm)

export interface RawResult {
  url: string
  title: string
  content: string
}

export interface EngineResults {
  engine: string
  weight: number
  results: RawResult[]
  error?: string
}

export interface MergedResult {
  url: string
  title: string
  content: string
  engine: string
  engines: string[]
  positions: number[]
  score: number
  category: string
}

export interface MergeOutput {
  results: MergedResult[]
  unresponsive: [string, string][]
}

function normalizeUrl(raw: string): string {
  try {
    const u = new URL(raw)
    const path = u.pathname.replace(/\/+$/, '') || '/'
    return (u.hostname.toLowerCase().replace(/^www\./, '') + path).toLowerCase()
  } catch {
    return raw.toLowerCase()
  }
}

type InternalEntry = Omit<MergedResult, 'engines'> & { engines: Set<string> }

export function mergeResults(engineResults: EngineResults[]): MergeOutput {
  const byUrl = new Map<string, InternalEntry>()
  const unresponsive: [string, string][] = []

  for (const er of engineResults) {
    if (er.error) {
      unresponsive.push([er.engine, er.error])
      continue
    }
    const weight = er.weight ?? 1.0

    for (let i = 0; i < er.results.length; i++) {
      const r = er.results[i]!
      if (!r.url) continue
      const key = normalizeUrl(r.url)
      const position = i + 1

      const existing = byUrl.get(key)
      if (existing) {
        existing.engines.add(er.engine)
        existing.positions.push(position)
        existing.score += weight / position
        if (r.title && r.title.length > (existing.title?.length ?? 0)) existing.title = r.title
        if (r.content && r.content.length > (existing.content?.length ?? 0))
          existing.content = r.content
        // Prefer HTTPS
        if (r.url.startsWith('https:') && existing.url.startsWith('http:')) existing.url = r.url
      } else {
        byUrl.set(key, {
          url: r.url,
          title: r.title || '',
          content: r.content || '',
          engine: er.engine,
          engines: new Set<string>([er.engine]),
          positions: [position],
          score: weight / position,
          category: 'general',
        } satisfies InternalEntry)
      }
    }
  }

  const results: MergedResult[] = [...byUrl.values()]
    .sort((a, b) => b.score - a.score)
    .map(r => ({ ...r, engines: [...r.engines] as string[] }))

  return { results, unresponsive }
}
