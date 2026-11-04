// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Brave Search HTML scraping

import type { RawResult } from '../merger.ts'
import { httpGet } from './http.ts'
import { stripTags } from './html.ts'

export const name = 'brave'
export const weight = 1.0

export async function search(query: string, _opts: Record<string, unknown> = {}): Promise<RawResult[]> {
  const res = await httpGet(
    `https://search.brave.com/search?q=${encodeURIComponent(query)}&source=web`,
    {
      timeout: 10000,
      cookies: {
        safesearch: 'off',
        country: 'all',
        useLocation: '0',
        ui_lang: 'en-US',
      },
    },
  )

  if (res.status !== 200) throw new Error(`Brave HTTP ${res.status}`)

  const results: RawResult[] = []
  const html = res.text

  const snippetRe =
    /<a[^>]+class="[^"]*result-header[^"]*"[^>]*href="([^"]*)"[^>]*>[\s\S]*?<span[^>]*class="snippet-title"[^>]*>([\s\S]*?)<\/span>[\s\S]*?<(?:p|div)[^>]*class="[^"]*snippet-description[^"]*"[^>]*>([\s\S]*?)<\/(?:p|div)>/g
  let m: RegExpExecArray | null

  while ((m = snippetRe.exec(html)) !== null) {
    const url = m[1]!
    const title = stripTags(m[2]!)
    const content = stripTags(m[3]!)
    if (!url || url.startsWith('/')) continue
    results.push({ url, title, content })
  }

  // Fallback: simpler pattern if the main one didn't match
  if (results.length === 0) {
    const simpleRe = /<a[^>]+href="(https?:\/\/[^"]+)"[^>]*>\s*<span[^>]*>([\s\S]*?)<\/span>/g
    const descRe = /<p[^>]*class="[^"]*snippet-description[^"]*"[^>]*>([\s\S]*?)<\/p>/g
    const urls: { url: string; title: string }[] = []
    while ((m = simpleRe.exec(html)) !== null) {
      urls.push({ url: m[1]!, title: stripTags(m[2]!) })
    }
    const descs: string[] = []
    let dm: RegExpExecArray | null
    while ((dm = descRe.exec(html)) !== null) {
      descs.push(stripTags(dm[1]!))
    }
    for (let i = 0; i < Math.min(urls.length, 10); i++) {
      results.push({ url: urls[i]!.url, title: urls[i]!.title, content: descs[i] || '' })
    }
  }

  return results
}
