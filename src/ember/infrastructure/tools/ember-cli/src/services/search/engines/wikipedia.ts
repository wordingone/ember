// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Wikipedia search API (JSON, no scraping)

import type { RawResult } from '../merger.ts'
import { httpGet } from './http.ts'
import { stripTags } from './html.ts'

export const name = 'wikipedia'
export const weight = 0.5

export async function search(query: string, _opts: Record<string, unknown> = {}): Promise<RawResult[]> {
  const params = new URLSearchParams({
    action: 'query',
    list: 'search',
    srsearch: query,
    format: 'json',
    utf8: '1',
    srlimit: '5',
  })

  const res = await httpGet(`https://en.wikipedia.org/w/api.php?${params}`, {
    timeout: 8000,
    headers: { Accept: 'application/json' },
  })

  if (res.status !== 200) throw new Error(`Wikipedia HTTP ${res.status}`)

  const data = JSON.parse(res.text) as {
    query?: { search?: { title: string; snippet: string }[] }
  }
  const entries = data?.query?.search
  if (!Array.isArray(entries)) return []

  return entries.map(entry => ({
    url: `https://en.wikipedia.org/wiki/${encodeURIComponent(entry.title.replace(/ /g, '_'))}`,
    title: entry.title,
    content: stripTags(entry.snippet),
  }))
}
