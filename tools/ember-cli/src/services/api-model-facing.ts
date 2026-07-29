// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// API model-facing surface — assembles the exact request the model sees each turn.
// W2-B: local-only mode. No remote-API version/beta header injection here;
// betaHeaders is advisory metadata only — for a local llama-server it will be empty
// (ACTIVE_BETA_FLAGS cleared in agent-identity.ts). Exported signatures preserved.
// Covers: T=0 sampling, message normalization, tool schema conversion,
// system prompt assembly, effort/thinking resolution, beta header merging,
// and extra body params injection.

// ---------------------------------------------------------------------------
// Constants (AC1, AC2)
// ---------------------------------------------------------------------------

/** Sampling params used for tool-use-primary (deterministic) turns. */
export const T0_SAMPLING_PARAMS = {
  temperature: 0.0,
  top_k: 1,
  seed: 42,
} as const;

/** Sampling fields accepted from a model's `samplingParams` configuration. */
export const SAMPLING_PARAM_KEYS = [
  "temperature",
  "top_p",
  "top_k",
  "min_p",
  "typical_p",
  "seed",
  "repeat_penalty",
  "frequency_penalty",
  "presence_penalty",
] as const;

export type SamplingParamKey = typeof SAMPLING_PARAM_KEYS[number];
export type SamplingParams = Partial<Record<SamplingParamKey, number>>;

const SAMPLING_PARAM_KEY_SET = new Set<string>(SAMPLING_PARAM_KEYS);
const INTEGER_SAMPLING_PARAMS = new Set<SamplingParamKey>(["top_k", "seed"]);

function validateSamplingParam(key: SamplingParamKey, value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`EMBER_SAMPLING_PARAMS.${key} must be a finite number`);
  }
  if (INTEGER_SAMPLING_PARAMS.has(key) && !Number.isInteger(value)) {
    throw new Error(`EMBER_SAMPLING_PARAMS.${key} must be an integer`);
  }
  return value;
}

/**
 * Parse the per-model sampling policy installed by process-entry.ts.
 *
 * This is deliberately closed: a models.json entry cannot smuggle arbitrary
 * request-body fields through `samplingParams`, and malformed policy never
 * silently falls back to server defaults.
 */
export function getConfiguredSamplingParams(
  raw: string | undefined = process.env["EMBER_SAMPLING_PARAMS"],
): SamplingParams {
  if (raw === undefined) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("EMBER_SAMPLING_PARAMS must be valid JSON");
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("EMBER_SAMPLING_PARAMS must be a JSON object");
  }

  const result: SamplingParams = {};
  for (const [key, value] of Object.entries(parsed)) {
    if (!SAMPLING_PARAM_KEY_SET.has(key)) {
      throw new Error(`EMBER_SAMPLING_PARAMS contains unsupported field: ${key}`);
    }
    const samplingKey = key as SamplingParamKey;
    result[samplingKey] = validateSamplingParam(samplingKey, value);
  }
  return result;
}

/** Extract and revalidate sampling fields from a fully assembled request. */
export function extractSamplingParams(
  request: Readonly<Record<string, unknown>>,
): SamplingParams {
  const result: SamplingParams = {};
  for (const key of SAMPLING_PARAM_KEYS) {
    if (request[key] !== undefined) {
      result[key] = validateSamplingParam(key, request[key]);
    }
  }
  return result;
}

/**
 * Minimum uncached token count that constitutes a "significant cache miss."
 * Downstream services read this to decide whether to suppress speculation.
 */
export const MIN_CACHE_MISS_TOKENS = 2000;

/**
 * Maximum `max_tokens` value — a fixed ceiling applied when the model default
 * would otherwise exceed it.
 */
export const CAPPED_DEFAULT_MAX_TOKENS = 8096;

// ---------------------------------------------------------------------------
// Thinking configuration modes
// ---------------------------------------------------------------------------

export type ThinkingMode = "adaptive" | "enabled" | "disabled";

export interface ThinkingConfigDisabled {
  type: "disabled";
}

export interface ThinkingConfigEnabled {
  type: "enabled";
  budget_tokens: number;
}

export type ThinkingConfig = ThinkingConfigDisabled | ThinkingConfigEnabled;

// ---------------------------------------------------------------------------
// Effort resolution (AC7)
// ---------------------------------------------------------------------------

/**
 * Resolves the thinking mode for a request.
 * Priority: env override → explicit request option → model default.
 * AC7: never left unresolved — always returns one of the three modes.
 */
export function resolveEffort(
  explicitOption: ThinkingMode | undefined,
  modelDefault: ThinkingMode,
): ThinkingMode {
  // Env override (EMBER_THINKING_BUDGET set to 0 → disabled; set → enabled)
  const budgetEnv = process.env["EMBER_THINKING_BUDGET"];
  if (budgetEnv !== undefined) {
    const budget = parseInt(budgetEnv, 10);
    if (!isNaN(budget)) {
      return budget === 0 ? "disabled" : "enabled";
    }
  }

  // Explicit request option
  if (explicitOption !== undefined) {
    return explicitOption;
  }

  // Model default
  return modelDefault;
}

/**
 * Converts a resolved ThinkingMode to the API ThinkingConfig shape.
 */
export function buildThinkingConfig(mode: ThinkingMode): ThinkingConfig {
  if (mode === "disabled") {
    return { type: "disabled" };
  }
  const budgetEnv = process.env["EMBER_THINKING_BUDGET"];
  const budget = budgetEnv !== undefined ? parseInt(budgetEnv, 10) : 8192;
  if (mode === "enabled" || mode === "adaptive") {
    return { type: "enabled", budget_tokens: isNaN(budget) ? 8192 : Math.max(budget, 1) };
  }
  return { type: "disabled" };
}

// ---------------------------------------------------------------------------
// Prompt state snapshot (AC2)
// ---------------------------------------------------------------------------

export interface PromptStateSnapshot {
  cachedTokens: number;
  uncachedTokens: number;
  isSignificantCacheMiss: boolean;
}

/**
 * AC2: Records a snapshot of the current prompt token counts.
 * Sets `isSignificantCacheMiss = true` when uncachedTokens > MIN_CACHE_MISS_TOKENS.
 */
export function buildPromptStateSnapshot(
  cachedTokens: number,
  uncachedTokens: number,
): PromptStateSnapshot {
  return {
    cachedTokens,
    uncachedTokens,
    isSignificantCacheMiss: uncachedTokens > MIN_CACHE_MISS_TOKENS,
  };
}

// ---------------------------------------------------------------------------
// Tool schema conversion (AC3)
// ---------------------------------------------------------------------------

export interface EmberToolDefinition {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema?: Record<string, unknown>; // not sent to model
}

export interface ApiToolDefinition {
  name: string;
  description: string;
  input_schema: {
    type: "object";
    properties: Record<string, unknown>;
    required?: string[];
  };
}

/**
 * AC3: Converts a registered tool definition to the API JSON schema format.
 * The output_schema (if any) is NOT included — it is only used for local validation.
 */
export function convertToolToApiSchema(tool: EmberToolDefinition): ApiToolDefinition {
  const inputSchema = tool.input_schema as {
    type?: string;
    properties?: Record<string, unknown>;
    required?: string[];
  };
  return {
    name: tool.name,
    description: tool.description,
    input_schema: {
      type: "object",
      properties: inputSchema.properties ?? {},
      ...(inputSchema.required !== undefined ? { required: inputSchema.required } : {}),
    },
  };
}

/**
 * Converts all tools in a registry to API schema format.
 */
export function convertToolsToApiSchemas(tools: EmberToolDefinition[]): ApiToolDefinition[] {
  return tools.map(convertToolToApiSchema);
}

// ---------------------------------------------------------------------------
// System prompt assembly (AC4)
// ---------------------------------------------------------------------------

export interface SystemPromptParts {
  cliPrefix: string;
  projectInstructions: string | null;
  userInstructions: string | null;
  injectedContext: string | null;
}

/**
 * AC4: Assembles the system prompt from ordered components.
 * Order: CLI prefix → project instructions → user instructions → injected context.
 * Null/empty parts are omitted from the assembled string.
 */
export function assembleSystemPrompt(parts: SystemPromptParts): string {
  const segments: string[] = [parts.cliPrefix];
  if (parts.projectInstructions) segments.push(parts.projectInstructions);
  if (parts.userInstructions) segments.push(parts.userInstructions);
  if (parts.injectedContext) segments.push(parts.injectedContext);
  return segments.join("\n\n");
}

// ---------------------------------------------------------------------------
// Beta header merging (AC6)
// ---------------------------------------------------------------------------

/**
 * AC6: Merges model-level and request-level beta headers.
 * Deduplicates — preserves insertion order of first occurrence.
 */
export function mergeBetaHeaders(
  modelBetas: string[],
  requestBetas: string[],
): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const b of [...modelBetas, ...requestBetas]) {
    if (!seen.has(b)) {
      seen.add(b);
      result.push(b);
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Extra body params injection (AC5)
// ---------------------------------------------------------------------------

/**
 * AC5: Parses EMBER_EXTRA_BODY and returns its fields if it is a valid JSON object.
 * Returns null if not set or not an object.
 */
export function getExtraBodyParams(): Record<string, unknown> | null {
  const raw = process.env["EMBER_EXTRA_BODY"];
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Merges extra body params (from EMBER_EXTRA_BODY) into the provided request body.
 * Extra body fields overwrite colliding built-in fields.
 */
export function mergeExtraBodyParams(
  body: Record<string, unknown>,
): Record<string, unknown> {
  const extra = getExtraBodyParams();
  if (!extra) return body;
  return { ...body, ...extra };
}

// ---------------------------------------------------------------------------
// Request assembly helpers
// ---------------------------------------------------------------------------

export interface ModelRequestOptions {
  isToolUseTurn: boolean;
  model: string;
  messages: unknown[];
  maxTokens: number;
  system?: string;
  tools?: EmberToolDefinition[];
  thinkingMode?: ThinkingMode;
  modelDefaultThinkingMode?: ThinkingMode;
  modelBetas?: string[];
  requestBetas?: string[];
}

export interface AssembledModelRequest {
  model: string;
  messages: unknown[];
  max_tokens: number;
  system?: string;
  tools?: ApiToolDefinition[];
  thinking?: ThinkingConfig;
  /** merged, deduplicated beta header values */
  betaHeaders: string[];
  /** sampling params (T=0 for tool-use turns, undefined otherwise) */
  samplingParams?: typeof T0_SAMPLING_PARAMS;
}

/**
 * Assembles the full model request object from the provided options.
 * AC1: Tool-use-primary turns get T=0 sampling params.
 * AC5: Extra body params are merged.
 * AC6: Beta headers are deduplicated.
 * AC7: Effort is resolved from env → explicit → model default.
 */
export function assembleModelRequest(opts: ModelRequestOptions): Record<string, unknown> {
  const resolvedMode = resolveEffort(opts.thinkingMode, opts.modelDefaultThinkingMode ?? "adaptive");
  const thinkingCfg = buildThinkingConfig(resolvedMode);
  const betaHeaders = mergeBetaHeaders(opts.modelBetas ?? [], opts.requestBetas ?? []);
  const convertedTools = opts.tools ? convertToolsToApiSchemas(opts.tools) : undefined;
  const configuredSampling = getConfiguredSamplingParams();

  const body: Record<string, unknown> = {
    model: opts.model,
    messages: opts.messages,
    max_tokens: Math.min(opts.maxTokens, CAPPED_DEFAULT_MAX_TOKENS),
    ...(opts.system ? { system: opts.system } : {}),
    ...(convertedTools && convertedTools.length > 0 ? { tools: convertedTools } : {}),
    ...(thinkingCfg.type !== "disabled" ? { thinking: thinkingCfg } : {}),
    ...configuredSampling,
    ...(opts.isToolUseTurn ? T0_SAMPLING_PARAMS : {}),
  };

  // Attach beta headers as metadata (consumer picks them up)
  body["_betaHeaders"] = betaHeaders;

  return mergeExtraBodyParams(body);
}
