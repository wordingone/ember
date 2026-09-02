// query/query-loop-support.ts — loop dependency injection and feature flag support.
//
// Provides:
//   - LoopDeps: injectable dependencies for the agent query loop (callModel, uuid, compaction).
//   - LoopConfig: frozen runtime configuration for a loop run (feature flags, user type).
//   - createLoopDeps: factory with sensible defaults, overridable in tests.
//   - buildLoopConfig: reads env + feature flag registry at call time.
//
// L2 leaf: no intra-ember dependencies beyond the crypto global.

// ---------------------------------------------------------------------------
// Feature flag registry (module-scoped Map — write via setFeatureFlag in tests)
// ---------------------------------------------------------------------------

const _featureFlags = new Map<string, boolean>();

/**
 * Returns the current value of a named feature flag.
 * Defaults to false when the flag has not been set.
 */
export function isFeatureFlagEnabled(flag: string): boolean {
  return _featureFlags.get(flag) ?? false;
}

/**
 * Sets a feature flag value. Intended for tests and early boot setup.
 */
export function setFeatureFlag(flag: string, value: boolean): void {
  _featureFlags.set(flag, value);
}

// ---------------------------------------------------------------------------
// LoopConfig — frozen snapshot of runtime configuration
// ---------------------------------------------------------------------------

export interface LoopConfig {
  /** When true, tool execution streams results as they arrive. */
  streamingToolExecution: boolean;
  /** When true, a compact summary of each tool use is emitted as a user message. */
  emitToolUseSummaries: boolean;
  /** When true, the running user has a non-empty USER_TYPE (privileged/operator tier). */
  isPrivilegedUser: boolean;
  /** When true, fast-mode heuristics (speculative tool reuse) are enabled. */
  fastModeEnabled: boolean;
}

/**
 * Returns true when the USER_TYPE env value is a non-empty string.
 * Empty string and undefined both map to "unprivileged".
 */
export function _isPrivilegedUserType(userType: string | undefined): boolean {
  return userType !== undefined && userType !== "";
}

/**
 * Builds a frozen LoopConfig snapshot from the current environment and
 * feature flag registry. Called once per query invocation.
 */
export function buildLoopConfig(): Readonly<LoopConfig> {
  return Object.freeze({
    streamingToolExecution: isFeatureFlagEnabled("streaming-tool-execution"),
    emitToolUseSummaries: !!process.env["EMBER_EMIT_TOOL_USE_SUMMARIES"],
    isPrivilegedUser: _isPrivilegedUserType(process.env["USER_TYPE"]),
    fastModeEnabled: !process.env["EMBER_DISABLE_FAST_MODE"],
  });
}

// ---------------------------------------------------------------------------
// LoopDeps — injectable model + compaction dependencies
// ---------------------------------------------------------------------------

/** Parameters passed to callModel each turn. */
export interface CallModelParams {
  messages: unknown[];
  systemPrompt: string;
  tools: Array<{ name: string; description: string; input_schema: Record<string, unknown> }>;
  model: string;
  maxTokens: number;
  skipCacheWrite?: boolean;
  // Optional: callers may invoke callModel without a cancellation signal
  // (e.g. one-shot headless requests); the loop guards its absence.
  abortSignal?: AbortSignal;
  jsonSchema?: unknown;
}

/** Shape of the model response returned by callModel. */
export interface ModelResponse {
  role: "assistant";
  content: unknown[];
  stop_reason: "end_turn" | "stop_sequence" | "tool_use" | "max_tokens" | null;
  usage?: {
    input_tokens: number;
    output_tokens: number;
    cache_read_input_tokens?: number;
    cache_creation_input_tokens?: number;
  };
}

/**
 * Injectable dependencies for the agent query loop.
 * Provide overrides in tests to avoid hitting a real model server.
 */
export interface LoopDeps {
  /**
   * Sends a model request and returns the parsed response.
   * In production, wired to the local llama-server or remote API.
   */
  callModel: (params: CallModelParams) => Promise<ModelResponse>;
  /**
   * Micro-compaction: trims the message list minimally when close to context limit.
   * Default: identity (returns the list unchanged).
   */
  microcompact: (messages: unknown[]) => Promise<unknown[]>;
  /**
   * Full autocompaction: rebuilds the conversation from a condensed summary.
   * Default: no-op.
   */
  autocompact: () => Promise<void>;
  /**
   * Generates a random UUID (v4 or equivalent) for message correlation.
   * Default: crypto.randomUUID().
   */
  generateUuid: () => string;
  /**
   * Waits `ms` milliseconds, resolving early if `signal` aborts (issue #197:
   * the retry backoff wait must stay responsive to a user-initiated Ctrl+C
   * mid-backoff rather than blocking the full delay). Default: a real timer.
   * Tests override this to make backoff waits instant.
   */
  sleep: (ms: number, signal?: AbortSignal) => Promise<void>;
}

/** Partial override type for createLoopDeps (all keys optional). */
export type LoopDepsOverrides = Partial<LoopDeps>;

function _defaultSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) { resolve(); return; }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });
}

/**
 * Creates a LoopDeps object with production defaults, overridden by any provided values.
 * In production: callModel must be supplied by session-init; the others are safe no-ops.
 * In tests: override any or all fields to inject controlled behavior.
 */
export function createLoopDeps(overrides: LoopDepsOverrides = {}): LoopDeps {
  return {
    callModel:
      overrides.callModel ??
      (async () => {
        throw new Error("No model sampling function provided to loop deps");
      }),
    microcompact: overrides.microcompact ?? (async (msgs) => msgs),
    autocompact: overrides.autocompact ?? (async () => {}),
    generateUuid: overrides.generateUuid ?? (() => crypto.randomUUID()),
    sleep: overrides.sleep ?? _defaultSleep,
  };
}
