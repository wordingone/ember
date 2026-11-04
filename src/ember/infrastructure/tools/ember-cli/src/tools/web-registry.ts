// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/web-registry.ts — wires the WebFetch / WebSearch builders (web-tools.ts) to the
// real keyless services: in-process meta-search, HTML->markdown, local-model summary.

import { buildWebFetchTool, buildWebSearchTool } from "../web-tools.ts";
import type { SearchResult as ToolSearchResult } from "../web-tools.ts";
import { searchWithDiagnostics } from "../services/search/index.ts";
import { htmlToMarkdown } from "../services/web-markdown.ts";
import { makeWebFetch } from "../services/web-http.ts";
import { summariseWithLocalModel } from "../services/web-model.ts";

export async function performKeylessSearch(
  query: string,
  opts: unknown,
): Promise<{ results: ToolSearchResult[]; notes: string[] }> {
  const o = (opts ?? {}) as { allowed_domains?: string[]; blocked_domains?: string[] };
  const out = await searchWithDiagnostics(query, {
    allowedDomains: o.allowed_domains,
    blockedDomains: o.blocked_domains,
  });
  const notes = out.engineErrors.map((e) => `Note: search engine ${e.engine} failed (${e.error}).`);
  return {
    results: out.results.slice(0, 15).map((r) => ({ url: r.url, title: r.title, description: r.snippet, score: r.score })),
    notes,
  };
}

export const WebFetchTool = buildWebFetchTool({
  fetchFn: makeWebFetch(),
  secondaryModel: (content, prompt, preapproved) => summariseWithLocalModel(content, prompt, preapproved),
  htmlToMarkdown: (html, baseUrl) => htmlToMarkdown(html, baseUrl),
});

export const WebSearchTool = buildWebSearchTool({ performSearch: performKeylessSearch });

export const WEB_TOOLS = [WebFetchTool, WebSearchTool];
