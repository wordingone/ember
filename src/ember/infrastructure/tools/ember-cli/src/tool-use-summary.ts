// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tool-use-summary.ts — generates concise past-tense summaries of tool-use sequences.

// ---- Constants ----

/** Maximum JSON characters before truncation (excluding the trailing '...'). */
export const TRUNCATE_MAX_LENGTH = 300;

/** Maximum characters in the final summary string. */
export const MAX_SUMMARY_LENGTH = 30;

/**
 * Model used to generate tool-use summaries.
 * Must be a fast, cost-efficient model since it runs after every tool-use batch.
 */
export const SUMMARY_MODEL = 'haiku-4-5';

// ---- Types ----

export interface SummarizedToolCall {
  name: string;
  input: unknown;
  output: unknown;
}

export interface ModelCallOptions {
  model: string;
  enablePromptCaching: boolean;
  messages: Array<{ content: string }>;
}

// ---- JSON truncation ----

/**
 * Serialises `obj` to JSON and truncates to `maxLength` characters, appending
 * '...' when truncation occurs. Returns the full JSON when it fits.
 */
export function truncateJson(obj: unknown, maxLength: number = TRUNCATE_MAX_LENGTH): string {
  const json = JSON.stringify(obj);
  if (json.length <= maxLength) return json;
  return json.slice(0, maxLength) + '...';
}

// ---- Summary generator ----

/**
 * Generates a concise past-tense summary of the provided tool calls.
 *
 * - Truncates each input/output to TRUNCATE_MAX_LENGTH chars before sending to the model
 * - Uses SUMMARY_MODEL with prompt caching enabled
 * - Trims the model response to MAX_SUMMARY_LENGTH characters
 * - Returns a fallback string (first tool name, lowercased) on model error
 */
export async function generateToolUseSummary(
  tools: SummarizedToolCall[],
  modelCallFn: (opts: ModelCallOptions) => Promise<string>,
): Promise<string> {
  const fallback =
    tools.length > 0 ? tools[0]!.name.toLowerCase() : 'tool use';

  try {
    const toolDescriptions = tools
      .map((t) => {
        const inputStr = truncateJson(t.input, TRUNCATE_MAX_LENGTH);
        const outputStr = truncateJson(t.output, TRUNCATE_MAX_LENGTH);
        return `Tool: ${t.name}\nInput: ${inputStr}\nOutput: ${outputStr}`;
      })
      .join('\n\n');

    const prompt = [
      'Summarise the following tool calls in past-tense verb + noun style.',
      `Keep the summary to ${MAX_SUMMARY_LENGTH} characters or fewer.`,
      'Examples: "Read config.ts", "Wrote 3 files", "Ran tests".',
      '',
      toolDescriptions,
    ].join('\n');

    const response = await modelCallFn({
      model: SUMMARY_MODEL,
      enablePromptCaching: true,
      messages: [{ content: prompt }],
    });

    return response.trim().slice(0, MAX_SUMMARY_LENGTH);
  } catch {
    return fallback;
  }
}
