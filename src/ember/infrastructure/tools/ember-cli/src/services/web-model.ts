// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// web-model.ts — WebFetch "secondary model": summarise fetched markdown against the
// caller's prompt with the ACTIVE local model (OpenAI-compatible, EMBER_MODEL_URL).
// If no model endpoint is reachable, returns the truncated markdown instead of failing.

import { fetchNCtx, normalizeModelServerUrl } from './api-openai-adapter.ts';

export const FALLBACK_CHARS = 20_000;
const DEFAULT_MODEL_CHARS = 12_000;
const CHARS_PER_TOKEN = 2.7;

/** Added to every summary prompt: what the model must not claim, and what it must keep. */
const FIDELITY_GUIDELINES = [
  ' - If the content above ends with a note that it was truncated, you were given only the start of the page: say so, and do not describe its size, its last section or its ending as the whole page\'s.',
  ' - Where the content has links ([text](url)) that bear on the question, give their URLs exactly as written.',
];

export function makeSecondaryModelPrompt(content: string, prompt: string, preapproved: boolean): string {
  const guidelines = preapproved
    ? ['Provide a concise response based on the content above. Include relevant details, code examples, and documentation excerpts as needed. In your response:', ...FIDELITY_GUIDELINES].join('\n')
    : [
        'Provide a concise response based only on the content above. In your response:',
        ' - Enforce a strict 125-character maximum for quotes from any source document.',
        ' - Use quotation marks for exact language from articles; any language outside of the quotation should never be word-for-word the same.',
        ' - Never produce or reproduce exact song lyrics.',
        ...FIDELITY_GUIDELINES,
      ].join('\n');
  return `Web page content:\n---\n${content}\n---\n\n${prompt}\n\n${guidelines}\n`;
}

export function truncatedFallback(content: string, reason: string): string {
  const body = content.length > FALLBACK_CHARS
    ? content.slice(0, FALLBACK_CHARS) + `\n\n[Truncated to ${FALLBACK_CHARS} characters]`
    : content;
  return `[No model summary (${reason}); returning page markdown]\n\n${body}`;
}

export function stripThinking(text: string): string {
  return text.replace(/<think>[\s\S]*?<\/think>/gi, '').replace(/^[\s\S]*?<\/think>/i, '').trim();
}

/** How much of `content` a failed summary hands back as the page text. */
function fallbackChars(content: string): number {
  return Math.min(content.length, FALLBACK_CHARS);
}

/**
 * `charsRead` is how much of `content` the answer rests on: the part the model was given, or the
 * part returned in place of a summary. WebFetch compares it with the page's full length and says
 * so up front when the answer covers only part of the page (blind test W12).
 */
export async function summariseWithLocalModel(
  content: string,
  prompt: string,
  preapproved: boolean,
  env: Record<string, string | undefined> = process.env,
  fetchFn: typeof fetch = globalThis.fetch,
): Promise<{ text: string; charsRead: number }> {
  const url = env['EMBER_MODEL_URL'];
  const fallback = (reason: string) => ({ text: truncatedFallback(content, reason), charsRead: fallbackChars(content) });
  if (!url) return fallback('EMBER_MODEL_URL not set');
  try {
    const base = normalizeModelServerUrl(url);
    let maxChars = DEFAULT_MODEL_CHARS;
    try {
      const nCtx = await fetchNCtx(base);
      // use at most half the context for page content
      maxChars = Math.max(4000, Math.min(60_000, Math.floor(nCtx * 0.5 * CHARS_PER_TOKEN)));
    } catch { /* keep default */ }
    const clipped = content.length > maxChars
      ? content.slice(0, maxChars) + '\n\n[Content truncated for the model]'
      : content;
    const res = await fetchFn(`${base}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        model: env['EMBER_MODEL_NAME'] ?? 'local',
        messages: [{ role: 'user', content: makeSecondaryModelPrompt(clipped, prompt, preapproved) }],
        max_tokens: 1536,
        temperature: 0.2,
        stream: false,
        // A reasoning model spent the whole budget thinking and returned no summary, so every
        // fetch fell back to raw, cut-off page text (blind test W06). A summary needs no thinking.
        chat_template_kwargs: { enable_thinking: false },
      }),
      signal: AbortSignal.timeout(180_000),
    });
    if (!res.ok) return fallback(`model HTTP ${res.status}`);
    const j = (await res.json()) as { choices?: Array<{ message?: { content?: string } }> };
    const text = stripThinking(j.choices?.[0]?.message?.content ?? '');
    if (!text) return fallback('model returned empty text');
    return { text, charsRead: Math.min(content.length, maxChars) };
  } catch (e) {
    return fallback(`model unavailable: ${(e as Error).message}`);
  }
}
