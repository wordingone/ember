// services/prompt-suggestion.ts — prediction of next user input.
// Enables type-ahead and pipeline optimization by generating candidate inputs
// before the user types them.

import type { EmberMessage } from "../types/message-types.ts";
import type { AppState } from "../state/app-state.ts";
import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PromptVariant = "user_intent" | "stated_intent";

/**
 * Configuration passed to the forked-agent executor on every generation call.
 * The executor is expected to honour skipTranscript and skipCacheWrite to avoid
 * contaminating the real conversation history or the prompt-cache budget.
 */
export interface ForkedAgentConfig {
  /** Full parent-context parameters (system prompt + messages + tools). */
  cacheSafeParams: object;
  /** Abort signal forwarded from the outer AbortController. */
  signal?: AbortSignal;
  /** When true, the forked agent's turn must NOT be appended to the transcript. */
  skipTranscript?: boolean;
  /** When true, the forked agent's response must NOT be written into the cache. */
  skipCacheWrite?: boolean;
}

/**
 * Injectable forked-agent executor interface.
 *
 * The real executor (not yet present in the ember-cli tree) runs a lightweight
 * forked agent whose tool callbacks unconditionally deny all tools.  It accepts
 * the suggestion prompt string and the generation config, then returns the raw
 * response messages produced by the model.
 *
 * Passing `undefined` (the default) causes generateSuggestion to short-circuit
 * and return { suggestion: null, generationRequestId: null }, preserving the
 * prior stub behaviour while the real executor is wired up.
 */
export type ForkedAgentExecutor = (
  prompt: string,
  config: ForkedAgentConfig,
) => Promise<EmberMessage[]>;

export interface REPLHookContext {
  messages: EmberMessage[];
  getAppState: () => AppState;
  setAppState: AppStateSetter;
  cacheSafeParams?: object;
  source?: string;
  /**
   * Optional injectable executor for prompt-suggestion generation.
   * When omitted the REPL hook is a no-op (no suggestion generated).
   * Provide a mock here in tests; provide the real forked-agent executor
   * when the executor seam lands in the ember-cli tree.
   */
  forkedAgentExecutor?: ForkedAgentExecutor;
}

export type AppStateSetter = (updater: (s: AppState) => AppState) => void;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_PARENT_UNCACHED_TOKENS = 10_000;

let currentAbortController: AbortController | null = null;

export const SUGGESTION_PROMPTS: Record<PromptVariant, string> = {
  user_intent:
    "Predict the user's natural next input. Output ONLY the predicted text, nothing else.",
  stated_intent:
    "Predict the user's next stated intent. Output ONLY the predicted text, nothing else.",
};

const SHORT_ALLOWLIST = new Set([
  "yes",
  "ok",
  "no",
  "push",
  "commit",
  "run",
  "done",
  "go",
  "stop",
]);

const META_TEXT_RE =
  /^(nothing found|silence|no input|no response|no suggestion|no next|not applicable|n\/a)$/i;

const EVALUATIVE_TERMS = [
  "great",
  "thanks",
  "thank",
  "nice",
  "perfect",
  "excellent",
  "awesome",
  "good job",
  "well done",
  "wonderful",
];

const VOICE_PREFIXES = [
  "let me",
  "i'll",
  "here's",
  "sure",
  "of course",
  "i can",
  "i will",
  "i'd",
  "i would",
  "i'm going",
];

// ---------------------------------------------------------------------------
// Debug logging (#190)
// ---------------------------------------------------------------------------

/**
 * Internal diagnostics for the suggestion engine. Ink owns the terminal frame
 * during interactive use, so a raw console write from here lands as literal
 * text on the live status line (e.g. "[suggestion] tryGenerate: too_few_turns
 * { count: 0 }"). Silent by default; set EMBER_SUGGESTION_DEBUG=1 to opt in
 * when debugging outside the TUI (headless run, piped stdout).
 */
function debugLog(...args: unknown[]): void {
  if (process.env["EMBER_SUGGESTION_DEBUG"] === "1") {
    console.debug(...args);
  }
}

// ---------------------------------------------------------------------------
// Module-level configuration (evaluated once at load time)
// ---------------------------------------------------------------------------

export const globalConfig = {
  tengu_chomp_inflection:
    process.env["FEATURE_TENGU_CHOMP_INFLECTION"] === "true",
  speculationEnabled:
    process.env["FEATURE_SPECULATION_ENABLED"] !== "false",
};

const userConfig = {
  get promptSuggestionEnabled(): boolean {
    const v = process.env["PROMPT_SUGGESTION_ENABLED"];
    if (v !== undefined) return v !== "false" && v !== "0";
    return true; // default enabled
  },
};

// ---------------------------------------------------------------------------
// Feature gate
// ---------------------------------------------------------------------------

/**
 * Returns the active prompt variant.
 * Hardcoded to user_intent; variant selection logic is out of scope here.
 */
export function getPromptVariant(): PromptVariant {
  return "user_intent";
}

/**
 * Returns true when prompt suggestions are enabled for the current session.
 * Checks five conditions in priority order.
 */
export function shouldEnablePromptSuggestion(): boolean {
  // 1. Explicit environment override beats everything
  const envOverride = process.env["PROMPT_SUGGESTION_ENABLED"];
  if (envOverride !== undefined) {
    const enabled = envOverride !== "false" && envOverride !== "0";
    debugLog("[suggestion] env override:", enabled);
    return enabled;
  }

  // 2. Feature flag: tengu_chomp_inflection disables the feature when set
  if (globalConfig.tengu_chomp_inflection) {
    debugLog("[suggestion] disabled by feature flag tengu_chomp_inflection");
    return false;
  }

  // 3. Session type: interactive mode — enabled by default
  debugLog("[suggestion] session type check: interactive");

  // 4. Team context: single-instance — always enabled
  debugLog("[suggestion] team context: single-instance");

  // 5. User settings
  const enabled = userConfig.promptSuggestionEnabled;
  debugLog("[suggestion] user settings enabled:", enabled);
  return enabled;
}

// ---------------------------------------------------------------------------
// Abort control
// ---------------------------------------------------------------------------

/**
 * Aborts any in-flight suggestion generation and clears the controller.
 */
export function abortPromptSuggestion(): void {
  if (currentAbortController !== null) {
    currentAbortController.abort();
    currentAbortController = null;
  }
}

// ---------------------------------------------------------------------------
// Suppress-reason helpers
// ---------------------------------------------------------------------------

type MessageUsage =
  | {
      input_tokens?: number;
      cache_creation_input_tokens?: number;
      cache_read_input_tokens?: number;
      output_tokens?: number;
    }
  | undefined;

/**
 * Returns "cache_cold" if the last assistant message has too many uncached
 * tokens; null otherwise.
 * Uncached token count = input_tokens + cache_creation_input_tokens + output_tokens.
 */
export function getParentCacheSuppressReason(
  lastAssistantMessage: EmberMessage,
): string | null {
  const usage = lastAssistantMessage["usage"] as MessageUsage;
  const total =
    (usage?.input_tokens ?? 0) +
    (usage?.cache_creation_input_tokens ?? 0) +
    (usage?.output_tokens ?? 0);
  if (total > MAX_PARENT_UNCACHED_TOKENS) {
    return "cache_cold";
  }
  return null;
}

/**
 * Returns the first reason to suppress suggestion generation, or null if
 * suggestions are permitted for the current app state.
 */
export function getSuggestionSuppressReason(appState: AppState): string | null {
  // 1. Feature gate
  if (!shouldEnablePromptSuggestion()) {
    debugLog("[suggestion] suppress: disabled");
    return "disabled";
  }

  // 2. Pending permission — no permission system present; always clear

  // 3. Elicitation active — not applicable; always clear

  // 4. Plan mode suppresses suggestions
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  if ((appState as any).mode === "plan") {
    debugLog("[suggestion] suppress: plan_mode");
    return "plan_mode";
  }

  // 5. Rate limit suppresses for non-internal users
  if (
    process.env["USER_TYPE"] !== "ant" &&
    process.env["RATE_LIMIT_STATUS"] === "blocked"
  ) {
    debugLog("[suggestion] suppress: rate_limit");
    return "rate_limit";
  }

  return null;
}

// ---------------------------------------------------------------------------
// Suggestion filter
// ---------------------------------------------------------------------------

/**
 * Returns true when the suggestion should be discarded.
 * Applies 12 ordered checks; logs the first matched filter.
 */
export function shouldFilterSuggestion(
  suggestion: string | null,
  promptId: PromptVariant,
  source?: string,
): boolean {
  if (suggestion === null) {
    debugLog("[suggestion] filter: null");
    return true;
  }

  const lower = suggestion.toLowerCase();

  // 1. Exact match on "done"
  if (lower === "done") {
    debugLog("[suggestion] filter: done", { promptId, source });
    return true;
  }

  // 2. Meta-commentary text
  if (META_TEXT_RE.test(suggestion)) {
    debugLog("[suggestion] filter: meta_text", { promptId, source });
    return true;
  }

  // 3. Parenthetical or bracketed thought
  if (
    (suggestion.startsWith("(") && suggestion.endsWith(")")) ||
    (suggestion.startsWith("[") && suggestion.endsWith("]"))
  ) {
    debugLog("[suggestion] filter: meta_wrapped", { promptId, source });
    return true;
  }

  // 4. Error response
  if (
    /^\{.*"error"/.test(suggestion) ||
    /^Error:/.test(suggestion) ||
    /^API Error/.test(suggestion)
  ) {
    debugLog("[suggestion] filter: error_message", { promptId, source });
    return true;
  }

  // 5. Label-prefixed output ("Label: text")
  if (/^[A-Za-z]+:\s/.test(suggestion)) {
    debugLog("[suggestion] filter: prefixed_label", { promptId, source });
    return true;
  }

  // 6. Too few words (< 2), unless in the short-command allowlist
  const words = suggestion
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0);
  if (words.length < 2 && !SHORT_ALLOWLIST.has(lower.trim())) {
    debugLog("[suggestion] filter: too_few_words", { promptId, source });
    return true;
  }

  // 7. Too many words (> 12)
  if (words.length > 12) {
    debugLog("[suggestion] filter: too_many_words", { promptId, source });
    return true;
  }

  // 8. Too long (>= 100 characters)
  if (suggestion.length >= 100) {
    debugLog("[suggestion] filter: too_long", { promptId, source });
    return true;
  }

  // 9. Multiple sentences (punctuation + space + uppercase)
  if (/[.!?]\s[A-Z]/.test(suggestion)) {
    debugLog("[suggestion] filter: multiple_sentences", { promptId, source });
    return true;
  }

  // 10. Formatting characters present
  if (
    suggestion.includes("\n") ||
    suggestion.includes("*") ||
    suggestion.includes(" ** ")
  ) {
    debugLog("[suggestion] filter: has_formatting", { promptId, source });
    return true;
  }

  // 11. Evaluative language
  for (const term of EVALUATIVE_TERMS) {
    if (lower.includes(term)) {
      debugLog("[suggestion] filter: evaluative", { term, promptId, source });
      return true;
    }
  }

  // 12. First-person assistant voice prefixes
  for (const prefix of VOICE_PREFIXES) {
    if (lower.startsWith(prefix)) {
      debugLog("[suggestion] filter: assistant_voice", { prefix, promptId, source });
      return true;
    }
  }

  return false;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Scans ALL messages returned by the forked agent and returns the first
 * non-empty text block found, or null if none.
 *
 * Handles both plain-string message content and structured EmberContentBlock
 * arrays, mirroring the behavioral-map description:
 *   "scans ALL messages for text block".
 */
function extractFirstTextBlock(messages: EmberMessage[]): string | null {
  for (const message of messages) {
    const { content } = message;
    if (typeof content === "string") {
      const trimmed = content.trim();
      if (trimmed.length > 0) return trimmed;
    } else if (Array.isArray(content)) {
      for (const block of content) {
        if (
          block.type === "text" &&
          "text" in block &&
          typeof block.text === "string"
        ) {
          const trimmed = block.text.trim();
          if (trimmed.length > 0) return trimmed;
        }
      }
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Real executor factory
// ---------------------------------------------------------------------------

/**
 * Creates a ForkedAgentExecutor backed by the provided callModel function.
 *
 * The returned executor, given a ForkedAgentConfig:
 *  - Builds a CallModelParams using the prompt string (already resolved to the
 *    SUGGESTION_PROMPTS variant text by generateSuggestion) as systemPrompt.
 *  - Extracts conversation messages from cacheSafeParams["messages"] so the
 *    model has parent-conversation context to predict from.
 *  - Sets tools to an EMPTY array — deny-all tool use for the forked agent.
 *  - Sets skipCacheWrite=true so the suggestion run never pollutes the cache.
 *  - Forwards the AbortSignal so in-flight requests cancel cleanly.
 *  - Wraps the single ModelResponse as an EmberMessage[] for extractFirstTextBlock.
 *
 * Do NOT construct callModel inside this function — it requires a serverUrl
 * this module should not know about.  The REPL or app shell supplies the
 * callModel produced by buildProductionCallModel (from session-init.ts).
 */
export function makeSuggestionExecutor(
  callModel: (params: CallModelParams) => Promise<ModelResponse>,
): ForkedAgentExecutor {
  return async function suggestionExecutor(
    prompt: string,
    config: ForkedAgentConfig,
  ): Promise<EmberMessage[]> {
    // Extract conversation messages from the parent context parameters.
    // cacheSafeParams is typed as `object`; at runtime it typically carries
    // a `messages` array matching the shape of CallModelParams.messages.
    const parentMessages =
      (
        (config.cacheSafeParams as Record<string, unknown>)["messages"] as
          | unknown[]
          | undefined
      ) ?? [];

    const callParams: CallModelParams = {
      // The resolved suggestion-prompt string is the full system instruction.
      systemPrompt: prompt,
      // Pass the parent conversation so the model has context to predict from.
      messages: parentMessages,
      // Empty tools array: deny-all tool use for the forked agent.
      tools: [],
      // Model identifier — inherit from env; llama-server loads one model and
      // typically ignores this field, so any non-empty value or empty string works.
      model: process.env["EMBER_MODEL"] ?? "",
      // 64 tokens is generous for a short user-input suggestion (≤12 words).
      maxTokens: 64,
      // Never write suggestion responses into the prompt-cache budget.
      skipCacheWrite: true,
      // Forward the abort signal so cancellation propagates to the fetch.
      abortSignal: config.signal,
    };

    const response = await callModel(callParams);

    // Wrap ModelResponse as a single-element EmberMessage[] so that
    // extractFirstTextBlock can scan the content array with its existing logic.
    // The cast is safe: at runtime, response.content items are
    // { type: "text", text: string } objects — EmberContentBlock-shaped.
    return [response as unknown as EmberMessage];
  };
}

// ---------------------------------------------------------------------------
// Generation
// ---------------------------------------------------------------------------

/**
 * Generates a prompt suggestion via the injectable forked-agent executor.
 *
 * Contract:
 *  - Returns immediately with { suggestion: null, generationRequestId: null }
 *    when (a) the signal is already aborted or (b) no executor is provided.
 *  - Resolves the prompt template from SUGGESTION_PROMPTS[promptId].
 *  - Passes cacheSafeParams + abort signal + skipTranscript + skipCacheWrite
 *    to the executor config.
 *  - Scans ALL returned messages for the first non-empty text block.
 *  - Re-checks the abort signal after generation completes; returns null on abort.
 *  - Returns a traceable generationRequestId (format: "psg-<ts>-<random>") only
 *    when a non-null suggestion was extracted.
 *
 * The 12-filter quality pipeline (shouldFilterSuggestion) is applied by the
 * caller (tryGenerateSuggestion), not here.
 *
 * When forkedAgentExecutor is undefined the function is a safe no-op,
 * preserving backward-compatible behaviour until the real executor seam lands.
 */
export async function generateSuggestion(
  abortController: AbortController,
  promptId: PromptVariant,
  cacheSafeParams: object,
  forkedAgentExecutor?: ForkedAgentExecutor,
): Promise<{ suggestion: string | null; generationRequestId: string | null }> {
  // Guard: already aborted before we start (belt-and-suspenders; the outer
  // tryGenerateSuggestion guard at L377 also catches this for the normal path).
  if (abortController.signal.aborted) {
    return { suggestion: null, generationRequestId: null };
  }

  // No executor provided — cannot generate; return null (no-op fallback).
  if (!forkedAgentExecutor) {
    return { suggestion: null, generationRequestId: null };
  }

  // Traceable identifier for this generation attempt.
  const generationRequestId = `psg-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 9)}`;

  // Retrieve the prompt template for the requested variant.
  const prompt = SUGGESTION_PROMPTS[promptId];

  // Run the forked agent.  Tool callbacks inside the executor should deny all;
  // skipTranscript and skipCacheWrite keep the run invisible to the session.
  const messages = await forkedAgentExecutor(prompt, {
    cacheSafeParams,
    signal: abortController.signal,
    skipTranscript: true,
    skipCacheWrite: true,
  });

  // Post-generation abort check (mirrors L420-421 of the guard chain).
  if (abortController.signal.aborted) {
    return { suggestion: null, generationRequestId: null };
  }

  // Extract first non-null text block from ALL returned messages.
  const suggestion = extractFirstTextBlock(messages);

  return {
    suggestion,
    generationRequestId: suggestion !== null ? generationRequestId : null,
  };
}

// ---------------------------------------------------------------------------
// Try-generate (guard chain)
// ---------------------------------------------------------------------------

/**
 * Attempts to generate a suggestion, applying the full guard sequence.
 * Returns null on any guard failure, abort, or filter rejection.
 * Re-throws unexpected errors.
 *
 * forkedAgentExecutor is threaded through to generateSuggestion so tests can
 * inject a deterministic mock without touching the module-level state.
 */
export async function tryGenerateSuggestion(
  abortController: AbortController,
  messages: EmberMessage[],
  getAppState: () => AppState,
  cacheSafeParams: object,
  source?: string,
  forkedAgentExecutor?: ForkedAgentExecutor,
): Promise<{
  suggestion: string;
  promptId: PromptVariant;
  generationRequestId: string;
} | null> {
  try {
    // Guard 1: already aborted
    if (abortController.signal.aborted) {
      debugLog("[suggestion] tryGenerate: pre-aborted");
      return null;
    }

    // Guard 2 & 3: need at least 2 assistant messages
    const assistantMessages = messages.filter((m) => m.role === "assistant");
    if (assistantMessages.length < 2) {
      debugLog("[suggestion] tryGenerate: too_few_turns", {
        count: assistantMessages.length,
      });
      return null;
    }

    // Guard 3: last assistant message must not carry an error stop reason
    const lastAssistant = assistantMessages[assistantMessages.length - 1]!;
    if (lastAssistant.stop_reason === "error") {
      debugLog("[suggestion] tryGenerate: last message is error");
      return null;
    }

    // Guard 4: parent cache budget
    const cacheReason = getParentCacheSuppressReason(lastAssistant);
    if (cacheReason !== null) {
      debugLog("[suggestion] tryGenerate: cache suppress", cacheReason);
      return null;
    }

    // Guard 5: feature gate + app-state conditions
    const suppressReason = getSuggestionSuppressReason(getAppState());
    if (suppressReason !== null) {
      debugLog("[suggestion] tryGenerate: suppressed", suppressReason);
      return null;
    }

    const promptId = getPromptVariant();
    const result = await generateSuggestion(
      abortController,
      promptId,
      cacheSafeParams,
      forkedAgentExecutor,
    );

    // Post-generation abort check
    if (abortController.signal.aborted) {
      return null;
    }

    // Filter check
    if (shouldFilterSuggestion(result.suggestion, promptId, source)) {
      return null;
    }

    return {
      suggestion: result.suggestion!,
      promptId,
      generationRequestId: result.generationRequestId!,
    };
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      return null;
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// REPL hook entry point
// ---------------------------------------------------------------------------

/**
 * Fire-and-forget suggestion generation hook.
 * Aborts any in-flight request before starting a new one.
 */
export function executePromptSuggestion(context: REPLHookContext): Promise<void> {
  abortPromptSuggestion();
  const controller = new AbortController();
  currentAbortController = controller;

  return (async () => {
    try {
      const result = await tryGenerateSuggestion(
        controller,
        context.messages,
        context.getAppState,
        context.cacheSafeParams ?? {},
        context.source,
        context.forkedAgentExecutor,
      );
      if (result !== null) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        context.setAppState((s) => ({ ...s, currentSuggestion: result.suggestion } as any));
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        return;
      }
      debugLog("[suggestion] executePromptSuggestion error:", err);
    }
  })();
}

// ---------------------------------------------------------------------------
// Outcome logging
// ---------------------------------------------------------------------------

/**
 * Logs the outcome of a displayed suggestion (accepted or ignored).
 */
export function logSuggestionOutcome(
  suggestion: string,
  userInput: string,
  emittedAt: number,
  promptId: PromptVariant,
  generationRequestId: string,
): void {
  const accepted =
    userInput === suggestion || userInput.startsWith(suggestion);
  const elapsed = Date.now() - emittedAt;
  debugLog("[suggestion] outcome", {
    outcome: accepted ? "accepted" : "ignored",
    promptId,
    generationRequestId,
    suggestionLength: suggestion.length,
    ...(accepted
      ? { timeToAcceptMs: elapsed }
      : { timeToIgnoreMs: elapsed }),
    similarity: accepted ? 1 : 0,
  });
}

/**
 * Logs when a suggestion was suppressed before display.
 */
export function logSuggestionSuppressed(
  reason: string,
  suggestion?: string,
  promptId?: PromptVariant,
  source?: string,
): void {
  debugLog("[suggestion] suppressed", {
    outcome: "suppressed",
    reason,
    promptId,
    source,
    suggestionLength: suggestion?.length,
  });
}
