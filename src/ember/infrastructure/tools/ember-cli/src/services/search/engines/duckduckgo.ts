// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// DuckDuckGo HTML endpoint scraping

import type { RawResult } from '../merger.ts'
import { Cache } from '../cache.ts'
import { httpGet, httpPost } from './http.ts'
import { stripTags } from './html.ts'

export const name = 'duckduckgo'
export const weight = 1.0

const vqdCache = new Cache<string>(3600000) // 1 hour TTL for VQD tokens

async function getVqd(query: string): Promise<string | null> {
  const cached = vqdCache.get(query)
  if (cached) return cached

  try {
    const res = await httpGet(`https://duckduckgo.com/?q=${encodeURIComponent(query)}`, {
      timeout: 8000,
      fetchSite: 'none',
    })
    const match = res.text.match(/vqd="([^"]+)"/)
    if (match) {
      vqdCache.set(query, match[1]!)
      return match[1]!
    }
  } catch {
    /* fall through — VQD is optional */
  }
  return null
}

export async function search(query: string, _opts: Record<string, unknown> = {}): Promise<RawResult[]> {
  const vqd = await getVqd(query)

  const body = new URLSearchParams({ q: query })
  if (vqd) body.set('vqd', vqd)

  const res = await httpPost('https://html.duckduckgo.com/html/', body.toString(), {
    timeout: 10000,
    fetchMode: 'navigate',
    fetchSite: 'same-origin',
    fetchDest: 'document',
    headers: { 'Sec-Fetch-User': '?1', Referer: 'https://html.duckduckgo.com/' },
  })

  if (res.status !== 200) throw new Error(`DDG HTTP ${res.status}`)

  const results: RawResult[] = []
  // Match result blocks: link + snippet
  const blockRe =
    /<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>[\s\S]*?<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g
  let m: RegExpExecArray | null

  while ((m = blockRe.exec(res.text)) !== null) {
    let rawUrl = m[1]!
    const title = stripTags(m[2]!)
    const content = stripTags(m[3]!)

    // Decode DDG redirect: //duckduckgo.com/l/?uddg=ENCODED_URL
    const uddgMatch = rawUrl.match(/[?&]uddg=([^&]+)/)
    if (uddgMatch) {
      rawUrl = decodeURIComponent(uddgMatch[1]!)
    } else if (rawUrl.startsWith('//')) {
      rawUrl = 'https:' + rawUrl
    }

    if (!rawUrl || rawUrl.includes('duckduckgo.com/y.js')) continue
    results.push({ url: rawUrl, title, content })
  }

  if (results.length === 0 && /anomaly|captcha|unusual traffic|challenge/i.test(res.text)) {
    throw new Error('DDG served a bot challenge page (no results parsed)')
  }

  return results
}
