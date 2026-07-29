// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// OpenAI adapter — translates between Ember message/tool format and OpenAI-compatible
// API format. Activated when EMBER_MODEL_URL points to a non-cloud endpoint.

import { appendFile, mkdir } from "fs/promises";
import { join } from "path";
import type { EmberMessage, EmberContentBlock } from "../types/message-types.ts";
import {
  SAMPLING_PARAM_KEYS,
  type SamplingParams,
} from "./api-model-facing.ts";
export type { EmberMessage, EmberContentBlock } from "../types/message-types.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Default SSE parser initial state. */
export const DEFAULT_THINKING_INITIAL_STATE: SseParserState = "pre";

/** Managed server restart cooldown in ms (AC7). */
export const RESTART_COOLDOWN_MS = 60_000;

/** n_ctx /props probe timeout in ms. */
export const NCTX_PROBE_TIMEOUT_MS = 10_000;

/** Prefill overflow guard threshold (FM_91): fraction of n_ctx. */
export const PREFILL_OVERFLOW_FRACTION = 0.95;

/**
 * Chars-per-token estimate used everywhere a real tokenizer isn't available at
 * this layer (query-engine.ts's per-result truncation + conversation-total
 * budget, session-init.ts's proactive prefill guard). Issue #197: the prior
 * value (3.5) was a guess and measurably too optimistic for the escaped-JSON-
 * heavy tool_result strings ember actually sends -- it undercounted real token
 * usage enough that a payload the estimator judged safe still 400'd against
 * the server. Measured directly against a llama-server /tokenize endpoint
 * serving the checkpoint under test at calibration time -- this adapter
 * serves whatever model the seat-authorized config names (never a
 * hardcoded cockpit-identity claim), so this constant is a calibration
 * snapshot against that one checkpoint, not a guarantee re-verified per
 * served model. Two representative samples from that run: a 6590-char
 * escaped-JSON tool_result (nested object, `\n`/`\"`/`\\` escapes, code lines,
 * file paths) tokenized at 2424 tokens = 2.72 chars/token; an 8023-char
 * JSON-escaped markdown-prose sample tokenized at 1512 tokens = 5.31
 * chars/token. The two diverge because JSON escaping and code/path tokens
 * fragment into more, shorter sub-word tokens than prose. Since the failure
 * mode this constant guards against is UNDERcounting tokens (a payload the
 * estimator judged small enough that overflows for real), the conservative
 * choice is the lower (denser) measurement -- an estimate too pessimistic for
 * prose only costs a little extra truncation/eviction headroom; one too
 * optimistic for JSON is the exact bug being fixed. 2.7 sits just under the
 * measured JSON floor (2.72), so it never reports a smaller token count than
 * the real tokenizer would for the content shape that actually causes
 * overflows. See the PR body for the calibration script and raw output.
 */
export const CHARS_PER_TOKEN_ESTIMATE = 2.7;

// ---------------------------------------------------------------------------
// Tool choice conversion (AC2)
// ---------------------------------------------------------------------------

export type EmberToolChoice =
  | { type: "auto" }
  | { type: "any" }
  | { type: "tool"; name: string };

export type OpenAIToolChoice =
  | "auto"
  | "required"
  | { type: "function"; function: { name: string } };

/**
 * AC2: Converts Ember tool_choice to OpenAI format.
 * - `{type:'auto'}` → `'auto'`
 * - `{type:'any'}` → `'required'`
 * - `{type:'tool', name:N}` → `{type:'function', function:{name:N}}`
 */
export function convertToolChoice(choice: EmberToolChoice): OpenAIToolChoice {
  switch (choice.type) {
    case "auto":
      return "auto";
    case "any":
      return "required";
    case "tool":
      return { type: "function", function: { name: choice.name } };
  }
}

// ---------------------------------------------------------------------------
// Tool definition conversion (Ember → OpenAI)
// ---------------------------------------------------------------------------

export interface EmberTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface OpenAITool {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

/** Converts an Ember tool definition to OpenAI format. */
export function convertToolDefinition(tool: EmberTool): OpenAITool {
  return {
    type: "function",
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.input_schema,
    },
  };
}

// ---------------------------------------------------------------------------
// Message conversion (Ember → OpenAI) (AC1)
// ---------------------------------------------------------------------------
// EmberMessage and EmberContentBlock are imported from ../types/message-types.ts
// (canonical definitions — Wave-1 reconciliation, formerly duplicated here as the remote message type).

export interface OpenAIMessage {
  role: "user" | "assistant" | "tool" | "system";
  content?: string | OpenAIContentPart[] | null;
  tool_calls?: OpenAIToolCall[];
  tool_call_id?: string;
}

export interface OpenAIContentPart {
  type: "text" | "image_url";
  text?: string;
  image_url?: { url: string };
}

export interface OpenAIToolCall {
  id: string;
  type: "function";
  function: {
    name: string;
    arguments: string; // JSON-stringified
  };
}

/**
 * AC1: Converts an array of Ember messages to OpenAI format.
 * - tool_use blocks → tool_calls with JSON-stringified arguments.
 * - tool_result blocks → role:'tool' messages with tool_call_id.
 * - thinking blocks are stripped (unless EMBER_THINKING_REPROMPT is set).
 * - image blocks → image_url content items.
 */
export function convertMessagesToOpenAI(
  messages: EmberMessage[],
): OpenAIMessage[] {
  const useReprompt = !!process.env["EMBER_THINKING_REPROMPT"];
  const result: OpenAIMessage[] = [];

  for (const msg of messages) {
    if (typeof msg.content === "string") {
      result.push({ role: msg.role, content: msg.content });
      continue;
    }

    const blocks = msg.content;
    const toolCalls: OpenAIToolCall[] = [];
    const contentParts: OpenAIContentPart[] = [];
    const toolResults: OpenAIMessage[] = [];

    for (const block of blocks) {
      switch (block.type) {
        case "text":
          contentParts.push({ type: "text", text: block.text });
          break;

        case "thinking":
          if (useReprompt) {
            // Include thinking as a text reprompt injection
            contentParts.push({ type: "text", text: `<thinking>${block.thinking}</thinking>` });
          }
          // else strip
          break;

        case "tool_use":
          toolCalls.push({
            id: block.id,
            type: "function",
            function: {
              name: block.name,
              arguments: JSON.stringify(block.input),
            },
          });
          break;

        case "tool_result": {
          const content =
            typeof block.content === "string"
              ? block.content
              : block.content.map((b) => (b.type === "text" ? b.text : "")).join("");
          toolResults.push({
            role: "tool",
            tool_call_id: block.tool_use_id,
            content,
          });
          break;
        }

        case "image": {
          const src = block.source;
          contentParts.push({
            type: "image_url",
            image_url: {
              url: `data:${src.media_type};base64,${src.data}`,
            },
          });
          break;
        }
      }
    }

    // Emit tool results as separate role:'tool' messages
    result.push(...toolResults);

    if (toolCalls.length > 0 || contentParts.length > 0) {
      const out: OpenAIMessage = { role: msg.role };
      if (contentParts.length > 0) {
        out.content = contentParts.length === 1 && contentParts[0]?.type === "text"
          ? contentParts[0].text
          : contentParts;
      }
      if (toolCalls.length > 0) out.tool_calls = toolCalls;
      result.push(out);
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// finish_reason conversion (AC9)
// ---------------------------------------------------------------------------

/**
 * AC9: Converts OpenAI finish_reason to Ember stop_reason.
 */
export function convertFinishReason(
  finishReason: string | null,
): "end_turn" | "tool_use" | "max_tokens" | "stop_sequence" {
  switch (finishReason) {
    case "tool_calls":
      return "tool_use";
    case "length":
      return "max_tokens";
    case "stop":
    default:
      return "end_turn";
  }
}

// ---------------------------------------------------------------------------
// Prefill overflow guard (FM_91) (AC3, AC4)
// ---------------------------------------------------------------------------

export class PrefillOverflowError extends Error {
  constructor(
    public readonly estimatedPrefill: number,
    public readonly maxTokens: number,
    public readonly nCtx: number,
  ) {
    super(
      `Prefill overflow: estimatedPrefill=${estimatedPrefill} + maxTokens=${maxTokens} > nCtx*0.95=${nCtx * PREFILL_OVERFLOW_FRACTION}`,
    );
    this.name = "PrefillOverflowError";
  }
}

/**
 * Issue #197: buildProductionCallModel threw a bare Error on a non-ok HTTP
 * response, discarding the status code by the time it reached query-engine.ts's
 * retry loop -- which needs the real status to tell a deterministic 4xx (never
 * retry) from a transient 5xx (retry with backoff) per api-backend.ts's
 * shouldRetry contract. Carries the same message text the bare Error used, so
 * anything already surfacing `.message` to the user is unaffected.
 */
export class ModelHttpError extends Error {
  constructor(
    public readonly status: number,
    statusText: string,
    public readonly responseBody = "",
  ) {
    const boundedBody = responseBody.trim().slice(0, 4096);
    super(
      `Model server returned HTTP ${status}: ${statusText}${boundedBody ? `: ${boundedBody}` : ""}`,
    );
    this.name = "ModelHttpError";
  }
}

/**
 * Canonical base for OpenAI-compatible model-server calls.
 *
 * Users commonly configure either `https://host` or `https://host/v1`.
 * Internally Ember appends the endpoint-specific `/v1/...` path, so retaining
 * a terminal `/v1` would produce `/v1/v1/...`. Non-terminal path prefixes are
 * preserved.
 */
export function normalizeModelServerUrl(serverUrl: string): string {
  let normalized = serverUrl.trim().replace(/\/+$/, "");
  normalized = normalized.replace(/\/v1$/i, "");
  if (!normalized || normalized === "/") {
    throw new Error("EMBER_MODEL_URL must contain a non-empty server base URL");
  }
  return normalized;
}

/**
 * AC4: Fetches n_ctx from the server's /props endpoint (or returns override value).
 */
export async function fetchNCtx(serverUrl: string): Promise<number> {
  const override = process.env["EMBER_NCTX_PROBE_OVERRIDE"];
  if (override) {
    const n = parseInt(override, 10);
    if (!isNaN(n)) return n;
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), NCTX_PROBE_TIMEOUT_MS);
  try {
    const normalizedServerUrl = normalizeModelServerUrl(serverUrl);
    const res = await fetch(`${normalizedServerUrl}/props`, { signal: ctrl.signal });
    if (!res.ok) throw new Error(`/props returned HTTP ${res.status}`);
    const data = await res.json() as { n_ctx?: number; default_generation_settings?: { n_ctx?: number } };
    return data.default_generation_settings?.n_ctx ?? data.n_ctx ?? 4096;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * AC3: Checks if the estimated prefill + max_tokens would overflow the context window.
 * Throws PrefillOverflowError if so.
 */
export function checkPrefillOverflow(
  estimatedPrefill: number,
  maxTokens: number,
  nCtx: number,
): void {
  if (estimatedPrefill + maxTokens > nCtx * PREFILL_OVERFLOW_FRACTION) {
    throw new PrefillOverflowError(estimatedPrefill, maxTokens, nCtx);
  }
}

// ---------------------------------------------------------------------------
// SSE parser state machine (AC5)
// ---------------------------------------------------------------------------

export type SseParserState = "pre" | "thinking" | "text";

export interface SseParserOptions {
  initialState?: SseParserState;
  endTag?: string;
  debugPath?: string | null;
  traceEnabled?: boolean;
}

export interface SseParserContext {
  state: SseParserState;
  thinkingBuffer: string;
  textBuffer: string;
  toolCallsByIndex: Map<number, { id: string; name: string; arguments: string }>;
  // issue #197: true only once a chunk carrying a non-null
  // `choices[0].finish_reason` has actually been seen. Before this field
  // existed, session-init.ts's buildProductionCallModel treated ANY stream
  // end (`reader.read()` returning `done: true`) as a successful "end_turn"
  // completion -- with no way to tell "the model genuinely finished" from
  // "the connection died mid-stream and the runtime's fetch() silently
  // reported a clean EOF instead of throwing" (measured directly: a real
  // llama-server killed mid-generation sometimes produces exactly this
  // silent-EOF shape, no error ever thrown). That gap meant a killed/
  // crashed server produced a TRUNCATED response rendered as a normal,
  // complete, successful turn -- worse than a visible error, since nothing
  // ever signaled the user or the retry logic that anything went wrong.
  sawFinishReason: boolean;
  // D2 token-counts fix (issue #581): captured from a chunk's top-level `usage` object
  // (prompt_tokens/completion_tokens) whenever the server sends one -- commonly the final
  // chunk, which often carries empty `choices` alongside it (checked ahead of the
  // choices/delta routing below so an empty-choices usage-only chunk still gets captured).
  // Stays null until a well-formed usage object is actually seen.
  usage: { inputTokens: number; outputTokens: number } | null;
}

/**
 * Creates a fresh SSE parser context.
 * AC5: initial state from EMBER_THINKING_INITIAL_STATE env (default 'pre').
 */
export function createSseParserContext(opts: SseParserOptions = {}): SseParserContext {
  const envInitialState = process.env["EMBER_THINKING_INITIAL_STATE"] as SseParserState | undefined;
  const initialState = opts.initialState ?? envInitialState ?? DEFAULT_THINKING_INITIAL_STATE;
  return {
    state: initialState,
    thinkingBuffer: "",
    textBuffer: "",
    toolCallsByIndex: new Map(),
    sawFinishReason: false,
    usage: null,
  };
}

const DEFAULT_END_TAG = "</thinking>";

/**
 * AC5: Processes a single SSE data line through the state machine.
 * AC6: When EMBER_SSE_DEBUG_PATH is set, appends the raw line to that file.
 */
export async function processSseLine(
  rawLine: string,
  ctx: SseParserContext,
  opts: SseParserOptions = {},
): Promise<void> {
  const debugPath = opts.debugPath ?? process.env["EMBER_SSE_DEBUG_PATH"] ?? null;
  if (debugPath) {
    await appendFile(debugPath, rawLine + "\n", "utf-8").catch(() => {});
  }

  if (!rawLine.startsWith("data:")) return;
  const jsonStr = rawLine.slice(5).trim();
  if (jsonStr === "[DONE]") {
    // issue #197: a genuine [DONE] sentinel is also a valid finish signal,
    // defensive against a server that sends it without a finish_reason on
    // the preceding chunk (the primary signal is checked below).
    ctx.sawFinishReason = true;
    return;
  }

  let data: unknown;
  try {
    data = JSON.parse(jsonStr);
  } catch {
    return;
  }

  const endTag = opts.endTag ?? process.env["EMBER_THINKING_END_TAG"] ?? DEFAULT_END_TAG;

  // Route delta based on state machine
  const choice = (data as Record<string, unknown>)?.["choices"];
  const firstChoice = Array.isArray(choice) ? (choice[0] as Record<string, unknown>) : null;

  // issue #197: record a genuine finish signal BEFORE the `!delta` early
  // return below, since the real final chunk (finish_reason set) commonly
  // carries an empty-but-present delta -- checked on `choice`, not `delta`,
  // so it's captured regardless of that chunk's delta shape.
  if (firstChoice && firstChoice["finish_reason"] != null) {
    ctx.sawFinishReason = true;
  }

  // D2 token-counts fix (issue #581): usage lives at the top level of the chunk, not inside a
  // choice, and the final chunk carrying it often has empty `choices` -- so this is checked
  // ahead of the `!delta` early-return below, and never depends on `firstChoice` at all.
  // Malformed usage objects (missing/non-numeric token fields) are ignored, never thrown.
  const usageObj = (data as Record<string, unknown>)?.["usage"];
  if (usageObj && typeof usageObj === "object") {
    const promptTokens = (usageObj as Record<string, unknown>)["prompt_tokens"];
    const completionTokens = (usageObj as Record<string, unknown>)["completion_tokens"];
    if (typeof promptTokens === "number" && typeof completionTokens === "number") {
      ctx.usage = { inputTokens: promptTokens, outputTokens: completionTokens };
    }
  }

  const delta = firstChoice?.["delta"];
  if (!delta) return;

  const content = (delta as Record<string, unknown>)?.["content"];
  const reasoningContent = (delta as Record<string, unknown>)?.["reasoning_content"];
  const toolCallsDelta = (delta as Record<string, unknown>)?.["tool_calls"];

  // Route reasoning_content to the thinking channel (separate-field path: llama.cpp/turboquant).
  if (typeof reasoningContent === "string") {
    ctx.thinkingBuffer += reasoningContent;
  }

  if (typeof content === "string") {
    switch (ctx.state) {
      case "pre":
        // If this delta contains the inline <thinking> start marker, enter thinking state.
        if (content.includes("<thinking>")) {
          ctx.state = "thinking";
          const afterStart = content.split("<thinking>")[1] ?? "";
          ctx.thinkingBuffer += afterStart;
        } else {
          // Plain content with no thinking tag: treat as text (do not swallow into thinkingBuffer).
          ctx.state = "text";
          ctx.textBuffer += content;
        }
        break;

      case "thinking":
        ctx.thinkingBuffer += content;
        if (ctx.thinkingBuffer.includes(endTag)) {
          const [thinkingDone] = ctx.thinkingBuffer.split(endTag);
          ctx.thinkingBuffer = thinkingDone ?? "";
          ctx.state = "text";
        }
        break;

      case "text":
        ctx.textBuffer += content;
        break;
    }
  }

  // Handle tool call deltas
  if (Array.isArray(toolCallsDelta)) {
    for (const tc of toolCallsDelta) {
      const idx = (tc as Record<string, unknown>)?.["index"] as number;
      const existing = ctx.toolCallsByIndex.get(idx);
      const fn = (tc as Record<string, unknown>)?.["function"] as Record<string, string> | undefined;
      if (existing) {
        existing.arguments += fn?.["arguments"] ?? "";
      } else {
        ctx.toolCallsByIndex.set(idx, {
          id: ((tc as Record<string, unknown>)?.["id"] as string) ?? "",
          name: fn?.["name"] ?? "",
          arguments: fn?.["arguments"] ?? "",
        });
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Managed server restart (AC7)
// ---------------------------------------------------------------------------

interface RestartState {
  lastRestartAt: number | null;
}

const _restartState: RestartState = { lastRestartAt: null };

/**
 * AC7: Returns whether a managed server restart can be triggered now (cooldown elapsed).
 */
export function canRestartManagedServer(): boolean {
  if (_restartState.lastRestartAt === null) return true;
  return Date.now() - _restartState.lastRestartAt >= RESTART_COOLDOWN_MS;
}

/**
 * AC7: Records that a restart was triggered now.
 */
export function recordManagedServerRestart(): void {
  _restartState.lastRestartAt = Date.now();
}

export function _resetRestartStateForTests(): void {
  _restartState.lastRestartAt = null;
}

// ---------------------------------------------------------------------------
// Stall detection (AC8)
// ---------------------------------------------------------------------------

interface StallDetectionState {
  previousTokensPredicted: number | null;
  stalledCount: number;
}

const _stallState: StallDetectionState = {
  previousTokensPredicted: null,
  stalledCount: 0,
};

/**
 * AC8: Records a /metrics poll result. Returns true if stall is detected
 * (2 consecutive polls with same tokens_predicted while state === 'generating').
 */
export function recordMetricsPoll(
  tokensPredicted: number,
  serverState: string,
): boolean {
  if (serverState !== "generating") {
    _stallState.previousTokensPredicted = null;
    _stallState.stalledCount = 0;
    return false;
  }

  if (_stallState.previousTokensPredicted === tokensPredicted) {
    _stallState.stalledCount++;
    if (_stallState.stalledCount >= 2) {
      return true; // stall detected
    }
  } else {
    _stallState.stalledCount = 1;
    _stallState.previousTokensPredicted = tokensPredicted;
  }

  return false;
}

export function _resetStallStateForTests(): void {
  _stallState.previousTokensPredicted = null;
  _stallState.stalledCount = 0;
}

// ---------------------------------------------------------------------------
// Request assembly (AC1: tool_calls conversion)
// ---------------------------------------------------------------------------

export interface OpenAIRequest {
  model: string;
  messages: OpenAIMessage[];
  tools?: OpenAITool[];
  tool_choice?: OpenAIToolChoice;
  stream: boolean;
  max_tokens: number;
  stream_options?: { include_usage: boolean };
  [key: string]: unknown;
}

/**
 * Builds an OpenAI-format request from Ember request components.
 * Applies environment variable overrides per spec.
 */
export function buildOpenAIRequest(opts: {
  model: string;
  messages: EmberMessage[];
  tools?: EmberTool[];
  toolChoice?: EmberToolChoice;
  maxTokens: number;
  samplingParams?: SamplingParams;
}): OpenAIRequest {
  const req: OpenAIRequest = {
    model: opts.model,
    messages: convertMessagesToOpenAI(opts.messages),
    stream: true,
    max_tokens: opts.maxTokens,
  };

  if (opts.samplingParams) {
    for (const key of SAMPLING_PARAM_KEYS) {
      const value = opts.samplingParams[key];
      if (value !== undefined) req[key] = value;
    }
  }

  if (opts.tools && opts.tools.length > 0) {
    req.tools = opts.tools.map(convertToolDefinition);
  }

  if (opts.toolChoice) {
    req.tool_choice = convertToolChoice(opts.toolChoice);
  }

  // EMBER_THINKING_ENABLE_PARAM — parameter name for enabling thinking
  const thinkingParam = process.env["EMBER_THINKING_ENABLE_PARAM"];
  if (thinkingParam) {
    const budget = parseInt(process.env["EMBER_THINKING_BUDGET"] ?? "0", 10);
    req[thinkingParam] = { type: "enabled", budget_tokens: budget };
  }

  // EMBER_THINKING_LOGIT_BIAS
  const logitBias = process.env["EMBER_THINKING_LOGIT_BIAS"];
  if (logitBias) {
    try {
      req["logit_bias"] = JSON.parse(logitBias);
    } catch {
      // ignore invalid JSON
    }
  }

  // EMBER_STREAM_OPTIONS_INCLUDE_USAGE
  if (process.env["EMBER_STREAM_OPTIONS_INCLUDE_USAGE"]) {
    req.stream_options = { include_usage: true };
  }

  return req;
}
