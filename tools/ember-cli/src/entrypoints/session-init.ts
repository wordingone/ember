// entrypoints/session-init.ts — session bootstrap and dependency wiring.
// Initialises config, TLS, analytics, IDE detection, shell setup, and the
// production LoopDeps (callModel / microcompact / autocompact).
// Bundle: entrypoints/session-init.ts (line 289018)

import {
  createLoopDeps,
  type LoopDeps,
  type CallModelParams,
  type ModelResponse,
} from "../query/query-loop-support.ts";
import { assembleModelRequest } from "../services/api-model-facing.ts";
import {
  buildOpenAIRequest,
  createSseParserContext,
  processSseLine,
  fetchNCtx,
  checkPrefillOverflow,
  PREFILL_OVERFLOW_FRACTION,
  CHARS_PER_TOKEN_ESTIMATE,
  ModelHttpError,
} from "../services/api-openai-adapter.ts";
import { createMicrocompact } from "../services/compaction.ts";
import { wrapModelClientWithCircuitBreaker } from "../services/model-circuit-breaker-client.ts";
import type { CircuitBreakerState } from "../services/model-circuit-breaker.ts";

// ---------------------------------------------------------------------------
// Module-level state (singletons)
// ---------------------------------------------------------------------------

let _initialized        = false;
let _initPromise:        Promise<void> | null = null;
let _loopDeps:           LoopDeps | null      = null;
let _telemetryInitialized = false;
let _cleanupHandlers:   Array<() => unknown>  = [];
/** The server's actual n_ctx once probed (issue #157); null before init() completes. */
let _resolvedNCtx:       number | null        = null;
/** issue #239: the live circuit breaker guarding the production model client; null before init(). */
let _circuitBreakerHandle: GuardedProductionCallModel | null = null;

// ---------------------------------------------------------------------------
// n_ctx-derived tool-result budget (issue #157; conversation-total extension #197)
// ---------------------------------------------------------------------------

/** Fraction of n_ctx reserved for a single tool result, leaving headroom for
 *  the system prompt, conversation history, tool schemas, and generation. */
const TOOL_RESULT_BUDGET_FRACTION = 0.25;

/**
 * Minimum generation headroom (tokens) the overflow guard reserves below
 * (issue #157 Leg 2). query-engine.ts's default request is an UNCAPPED
 * maxTokens=8192 ("no explicit limit set" -- not "we expect 8192 tokens of
 * output"); llama-server treats max_tokens as a ceiling, not a reservation,
 * and simply stops generation early when less room remains. Reserving the
 * FULL requested maxTokens here would false-positive on every short exchange
 * once nCtx <= ~8192 (verified live: a trivial one-line prompt tripped
 * "estimatedPrefill=22 + maxTokens=8192 > nCtx*0.95=7782.4" against the
 * throwaway CPU test server at ctx-size 8192, the exact live-cockpit config).
 * The real danger this guard exists for is the PROMPT ALONE not fitting
 * (that's what silently wedges the server) -- so cap the reserved amount at
 * this floor, never the raw request, and let an explicit smaller override
 * still be honored if the caller asked for less than the floor.
 */
const MIN_GENERATION_RESERVE_TOKENS = 512;

/** Returns the server's actual n_ctx as resolved by init()'s /props probe, or
 *  null if init() has not completed (or the probe failed and no fallback ran yet). */
export function getResolvedNCtx(): number | null {
  return _resolvedNCtx;
}

/**
 * Derives the per-tool-result char budget AND the conversation-total char
 * budget from the resolved n_ctx. Falls back to a conservative 4096
 * assumption when init() has not run yet.
 *
 * `maxChars` (issue #157 Leg 1) bounds a single tool_result string.
 *
 * `conversationMaxChars` (issue #197) bounds the WHOLE assembled conversation
 * (system prompt + full history) query-engine.ts sends per model call. Per-
 * result truncation alone is necessary but not sufficient: five individually-
 * small (already-truncated) tool results can still sum past n_ctx (receipt:
 * operator session #5, five tool calls in one turn against an 8192-ctx
 * server -- each result fit its own 25%-of-n_ctx budget, the SUM didn't fit).
 * Deliberately reuses the exact threshold formula checkPrefillOverflow (the
 * backstop below) enforces -- estimatedPrefill + reservedGeneration >
 * nCtx*PREFILL_OVERFLOW_FRACTION -- so query-engine.ts's proactive eviction
 * targets fitting under the SAME ceiling the backstop guards, and the
 * backstop should only ever fire on what eviction's cruder (raw
 * JSON.stringify, no tool-schema accounting) estimate under-counts.
 */
export function getToolResultBudget(): { maxChars: number; conversationMaxChars: number } {
  const nCtx = _resolvedNCtx ?? 4096;
  const conversationBudgetTokens = Math.max(
    nCtx * PREFILL_OVERFLOW_FRACTION - MIN_GENERATION_RESERVE_TOKENS,
    0,
  );
  return {
    maxChars: Math.floor(nCtx * TOOL_RESULT_BUDGET_FRACTION * CHARS_PER_TOKEN_ESTIMATE),
    conversationMaxChars: Math.floor(conversationBudgetTokens * CHARS_PER_TOKEN_ESTIMATE),
  };
}

// ---------------------------------------------------------------------------
// Cleanup registry
// ---------------------------------------------------------------------------

/** Registers a function to run on graceful shutdown (LIFO order). */
export function registerCleanupHandler(fn: () => unknown): void {
  _cleanupHandlers.push(fn);
}

async function _runCleanup(): Promise<void> {
  for (const fn of [..._cleanupHandlers].reverse()) {
    try {
      await fn();
    } catch {
      // individual cleanup failures are suppressed
    }
  }
}

// ---------------------------------------------------------------------------
// Combined abort signal helper
// ---------------------------------------------------------------------------

function createCombinedSignal(a: AbortSignal, b: AbortSignal): AbortSignal {
  const ctrl = new AbortController();
  const abort = () => ctrl.abort();
  a.addEventListener("abort", abort, { once: true });
  b.addEventListener("abort", abort, { once: true });
  return ctrl.signal;
}

// ---------------------------------------------------------------------------
// buildProductionCallModel — wires the local model server to LoopDeps.callModel
// ---------------------------------------------------------------------------

export interface ProductionCallModelOpts {
  serverUrl:  string;
  nCtx?:      number;
  timeoutMs?: number;
}

export function buildProductionCallModel(
  opts: ProductionCallModelOpts,
): (params: CallModelParams) => Promise<ModelResponse> {
  const serverUrl  = opts.serverUrl;
  const timeoutMs  = opts.timeoutMs ?? 30 * 60 * 1000;
  const nCtx       = opts.nCtx ?? 4096;

  return async function callModel(params: CallModelParams): Promise<ModelResponse> {
    const {
      messages,
      systemPrompt,
      tools,
      model,
      maxTokens,
      skipCacheWrite,
      abortSignal,
      jsonSchema,
    } = params;

    const assembled = assembleModelRequest({
      isToolUseTurn: tools.length > 0,
      model,
      messages,
      maxTokens,
      system: systemPrompt,
      tools:  tools as Parameters<typeof assembleModelRequest>[0]["tools"],
    });

    // as any: assembled is Record<string,unknown>; interop with OpenAI adapter types
    const openAiReq = buildOpenAIRequest({
      model:     assembled["model"]     as string,
      messages:  assembled["messages"]  as any[],   // interop: Record<string,unknown>→EmberMessage[]
      tools:     (assembled["tools"]    as any[] | undefined) ?? undefined,
      maxTokens: assembled["max_tokens"] as number,
    });

    // issue #157 Leg 2 (backstop): query-engine.ts's tool-result truncation
    // (Leg 1) is the primary cure for oversized prefill, but cumulative
    // multi-turn history or a tool exempted from truncation can still
    // overflow. Rather than send an oversized request and risk the server
    // silently wedging (receipt: receipts/operator-sessions/
    // session-20260705T234943Z.jsonl -- GPU idle, spinner alive >4min after a
    // 46,634-byte tool result vs n_ctx 8192), refuse it here, synchronously,
    // before any network call. This throw propagates out of callModel and is
    // already caught by query-engine.ts's try/catch around deps.callModel(),
    // which synthesizes a proper result/error event -- never a hang.
    // checkPrefillOverflow/fetchNCtx were built for this (FM_91, AC3/AC4) but
    // were never actually wired to the production request path until now.
    const estimatedPrefill = Math.ceil(
      (JSON.stringify(openAiReq.messages).length + systemPrompt.length) / CHARS_PER_TOKEN_ESTIMATE,
    );
    const reservedGenerationTokens = Math.min(maxTokens, MIN_GENERATION_RESERVE_TOKENS);
    checkPrefillOverflow(estimatedPrefill, reservedGenerationTokens, nCtx);

    const reqBody: Record<string, unknown> = { ...openAiReq };
    reqBody["cache_prompt"] = false;

    if (jsonSchema) {
      reqBody["response_format"] = {
        type:        "json_schema",
        json_schema: { name: "output", schema: jsonSchema },
      };
    }

    // issue #197: an explicit `Connection: keep-alive` header here was
    // silently DEFEATING the retry mechanism -- measured directly (two live
    // kill-mid-stream probes against the real llama-server binary, one with
    // this header, one without): with it set, Bun's fetch() pools the
    // request onto its keep-alive connection machinery and treats a server
    // process killed mid-SSE-stream as a normal, silent end-of-stream
    // (`done: true`, zero error) instead of throwing -- so a crashed/killed
    // server produced a SILENTLY TRUNCATED response with no error, no
    // retry, and no user-visible signal anything went wrong. Without the
    // header, the identical kill throws a real `Error` (`code: "ECONNRESET"`)
    // that reaches callModelWithRetry's classifier correctly. Modern fetch
    // clients manage connection reuse themselves; this header was
    // boilerplate from the CLI's initial publish, never load-bearing for
    // anything else, and actively harmful here.
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    if (skipCacheWrite) {
      headers["X-Skip-Cache-Write"] = "1";
    }

    const ctrl      = new AbortController();
    const timeoutId = setTimeout(() => ctrl.abort(), timeoutMs);
    const combinedSignal = abortSignal
      ? createCombinedSignal(ctrl.signal, abortSignal)
      : ctrl.signal;

    let response: Response;
    try {
      response = await fetch(`${serverUrl}/v1/chat/completions`, {
        method:  "POST",
        headers,
        body:    JSON.stringify(reqBody),
        signal:  combinedSignal,
      });
    } catch (err) {
      clearTimeout(timeoutId);
      throw err;
    }

    if (!response.ok) {
      clearTimeout(timeoutId);
      // issue #197: a typed error carrying the real status, not a bare Error --
      // query-engine.ts's retry loop classifies on `.status` to tell a
      // deterministic 4xx (never retry) from a transient 5xx (retry+backoff).
      throw new ModelHttpError(response.status, response.statusText);
    }

    const ctx    = createSseParserContext();
    const reader = response.body?.getReader();
    if (!reader) {
      clearTimeout(timeoutId);
      throw new Error("Model server response has no body");
    }

    const decoder = new TextDecoder();
    let lineBuffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        lineBuffer += decoder.decode(value, { stream: true });
        const lines = lineBuffer.split("\n");
        lineBuffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed) {
            await processSseLine(trimmed, ctx);
          }
        }
      }
      if (lineBuffer.trim()) {
        await processSseLine(lineBuffer.trim(), ctx);
      }
    } finally {
      clearTimeout(timeoutId);
      reader.releaseLock();
    }

    // issue #197: `reader.read()` returning `done: true` is a TRANSPORT-level
    // signal (the underlying stream ended), not proof the model actually
    // finished. Measured directly against the real llama-server binary: a
    // server killed mid-generation sometimes makes Bun's fetch() report a
    // silent, non-throwing EOF here -- with no finish_reason chunk and no
    // [DONE] sentinel ever seen. Before this check, that silently produced a
    // fabricated "end_turn" response built from whatever partial content had
    // streamed so far -- a TRUNCATED answer rendered as a normal, complete,
    // successful turn, with no error, no retry, and no signal to the user
    // that anything went wrong (worse than a visible error). A stream that
    // ends without ever having seen a genuine finish signal is a transport
    // failure, classified the same way an ECONNRESET is (see
    // query-engine.ts's isRetryableTransportError) so it gets a real,
    // bounded, visible retry instead of a silently-corrupted success.
    if (!ctx.sawFinishReason) {
      const err = new Error(
        "Model server connection ended before a finish signal was received (stream truncated).",
      );
      (err as { code?: string }).code = "ECONNRESET";
      throw err;
    }

    // Merge thinking prefix into text when still in 'pre' state
    if (ctx.state === "pre" && ctx.thinkingBuffer) {
      ctx.textBuffer    = ctx.thinkingBuffer + ctx.textBuffer;
      ctx.thinkingBuffer = "";
    }

    const content: unknown[] = [];

    if (ctx.thinkingBuffer) {
      content.push({ type: "thinking", thinking: ctx.thinkingBuffer });
    }
    if (ctx.textBuffer) {
      content.push({ type: "text", text: ctx.textBuffer });
    }
    for (const [, tc] of ctx.toolCallsByIndex) {
      let input: unknown;
      try {
        input = JSON.parse(tc.arguments);
      } catch {
        input = {};
      }
      content.push({
        type:  "tool_use",
        id:    tc.id || `tool_${crypto.randomUUID()}`,
        name:  tc.name,
        input,
      });
    }

    const stopReason = content.some((b) => (b as { type?: string }).type === "tool_use")
      ? "tool_use"
      : "end_turn";

    const emberMessage: ModelResponse = {
      role:          "assistant",
      content,
      stop_reason:   stopReason as ModelResponse["stop_reason"],
      usage: {
        input_tokens:                0,
        output_tokens:               0,
        cache_read_input_tokens:     0,
        cache_creation_input_tokens: 0,
      },
    };

    return emberMessage;
  };
}

// ---------------------------------------------------------------------------
// Circuit breaker wiring (issue #239) — the model-client request path
// ---------------------------------------------------------------------------

export interface GuardedProductionCallModel {
  callModel: (params: CallModelParams) => Promise<ModelResponse>;
  getCircuitState: () => CircuitBreakerState;
}

/**
 * Wraps buildProductionCallModel's raw HTTP client with the cross-call
 * circuit breaker (services/model-circuit-breaker-client.ts): a deterministic
 * 4xx fails fast to a degraded state instead of retrying, 429/5xx/network
 * failures get bounded backoff before the same degraded state, and once open
 * every further call is rejected locally (no network) until a single
 * half-open probe is due. This is the actual cure for the 20h wedge (issue
 * #239): the existing per-turn retry (issue #197) has no memory across
 * turns, so a broken endpoint got retried from a clean slate on every new
 * turn or goal-continuation re-invocation, forever. Exported standalone (not
 * just inlined into _runInit) so it is testable against a mocked fetch
 * without driving the whole init() singleton lifecycle.
 *
 * Always self-registers into the module-level _circuitBreakerHandle
 * singleton before returning, regardless of what the caller does with the
 * returned handle -- getCircuitBreakerState() (polled by the TUI's degraded
 * banner) must reflect ANY guarded client this function ever builds, not
 * only one a caller happened to also assign manually. A caller that builds
 * its own throwaway guarded client (a unit test, say) still moves the
 * singleton; _resetInitForTests() exists precisely to undo that between tests.
 */
export function buildGuardedProductionCallModel(
  opts: ProductionCallModelOpts,
  onStateChange?: (state: CircuitBreakerState) => void,
): GuardedProductionCallModel {
  const raw = buildProductionCallModel(opts);
  const handle = wrapModelClientWithCircuitBreaker(raw, {
    endpoint: opts.serverUrl,
    onStateChange,
  });
  const guarded: GuardedProductionCallModel = { callModel: handle.callModel, getCircuitState: handle.getState };
  _circuitBreakerHandle = guarded;
  return guarded;
}

/**
 * GPU-free mode stub: returns an OFFLINE error instead of calling a model.
 * The UI surfaces this state honestly (no fake tokens; board/receipt surfaces remain live).
 */
function buildOfflineCallModel(): GuardedProductionCallModel {
  const callModel = async (_params: CallModelParams): Promise<ModelResponse> => {
    // Return an error response that the UI can render as "OFFLINE (GPU leased to training)"
    const err = new ModelHttpError(
      "model_offline",
      "Model server is offline (GPU leased to training). Board and activity display remain available.",
      503,
    );
    throw err;
  };
  const handle = wrapModelClientWithCircuitBreaker(callModel, {
    endpoint: "(offline)",
    onStateChange: undefined,
  });
  const guarded: GuardedProductionCallModel = { callModel: handle.callModel, getCircuitState: handle.getState };
  return guarded;
}

/**
 * Returns the live circuit-breaker state for the production model client, or
 * null before init() has wired one up. Polled by the TUI's degraded-state
 * banner (status-bar.ts's DegradedBanner via repl.ts).
 */
export function getCircuitBreakerState(): CircuitBreakerState | null {
  return _circuitBreakerHandle?.getCircuitState() ?? null;
}

// ---------------------------------------------------------------------------
// Compaction wiring
// ---------------------------------------------------------------------------

// Micro-compaction is store-agnostic (a pure messages→messages transform), so it
// is built here and carried on LoopDeps. Auto-compaction is conversation-store-
// specific (it rewrites the persisted log), so it is built by QueryEngine against
// its own message store — not here.
function buildProductionMicrocompact(): (messages: unknown[]) => Promise<unknown[]> {
  return createMicrocompact();
}

// ---------------------------------------------------------------------------
// Internal init helpers (stubs — behaviour lives in production services)
// ---------------------------------------------------------------------------

async function _loadConfig(): Promise<void> {}
function  _applyTlsCerts(): void {}

function _registerGracefulShutdown(): void {
  process.once("exit", () => { _runCleanup(); });
  process.once("SIGINT",  () => { _runCleanup().then(() => process.exit(0)); });
  process.once("SIGTERM", () => { _runCleanup().then(() => process.exit(0)); });
}

async function _startAnalytics():    Promise<void> {}
async function _detectIde():         Promise<void> {}
async function _loadOAuthAccount():  Promise<void> {}
async function _detectGit():         Promise<void> {}
async function _loadRemoteSettings():Promise<void> {}
async function _loadPolicyLimits():  Promise<void> {}
function       _configureMtls():     void {}
function       _configureProxyAgents(): void {}
async function _preconnectApi(_serverUrl: string): Promise<void> {}
async function _initUpstreamProxy(): Promise<void> {
  // CCR (remote session) path — no-op for local sessions
  const isCcr = process.env["EMBER_REMOTE_SESSION_ID"] !== undefined;
  if (!isCcr) return;
}

function _setupWindowsShell(): void {
  if (!process.env["SHELL"]) {
    const comspec = process.env["COMSPEC"] ?? "C:\\Windows\\System32\\cmd.exe";
    process.env["SHELL"] = comspec;
  }
}

function  _shutdownLsp():        void {}
async function _cleanupTeams(): Promise<void> {}

async function _ensureScratchpad(): Promise<void> {
  if (!process.env["EMBER_SCRATCHPAD_DIR"]) return;
  const { mkdir } = await import("fs/promises");
  await mkdir(process.env["EMBER_SCRATCHPAD_DIR"], { recursive: true }).catch(() => {});
}

async function _lazyLoadOtel(): Promise<void> {}

// ---------------------------------------------------------------------------
// init — session bootstrap entry point (idempotent)
// ---------------------------------------------------------------------------

export interface InitOpts {
  serverUrl?:      string;
  nCtx?:           number;
  nonInteractive?: boolean;
}

export async function init(opts: InitOpts = {}): Promise<void> {
  if (_initialized)  return;
  if (_initPromise)  return _initPromise;
  _initPromise = _runInit(opts);
  return _initPromise;
}

async function _runInit(opts: InitOpts): Promise<void> {
  const serverUrl = opts.serverUrl
    ?? process.env["EMBER_MODEL_URL"]
    ?? "http://localhost:8081";
  const nCtxFallback = opts.nCtx ?? 4096;

  await _loadConfig();
  _applyTlsCerts();
  _registerGracefulShutdown();

  const analyticsP = _startAnalytics().catch(() => {});
  const ideP       = _detectIde().catch(() => {});

  _loadOAuthAccount().catch(() => {});
  _detectGit().catch(() => {});
  _loadRemoteSettings().catch(() => {});
  _loadPolicyLimits().catch(() => {});

  process.env["EMBER_FIRST_START_TIME"] ??= String(Date.now());

  _configureMtls();
  _configureProxyAgents();
  _preconnectApi(serverUrl).catch(() => {});
  _initUpstreamProxy().catch(() => {});
  _setupWindowsShell();

  registerCleanupHandler(() => _shutdownLsp());
  registerCleanupHandler(async () => { await _cleanupTeams(); });

  await _ensureScratchpad().catch(() => {});
  Promise.all([analyticsP, ideP]);

  // issue #157: resolve the server's ACTUAL n_ctx so the proactive overflow
  // guard and the tool-result truncation budget are sized against the real
  // running server, not a guessed default. process-entry.ts's -p/TUI path
  // already probes this itself (detectNCtx) and passes it in via opts.nCtx --
  // trust that rather than re-probing (avoids a redundant /props round trip).
  // Callers that DON'T pre-detect (e.g. mcp-server-entry.ts calls init() with
  // no options at all) get it here instead, via FM_91's fetchNCtx -- built for
  // exactly this, previously never called from anywhere. Best-effort: falls
  // back to the default when the probe fails (server not up yet, offline test
  // run, etc) -- never blocks init on a broken probe.
  let nCtx = nCtxFallback;
  if (opts.nCtx === undefined) {
    try {
      nCtx = await fetchNCtx(serverUrl);
    } catch {
      nCtx = nCtxFallback;
    }
  }
  _resolvedNCtx = nCtx;

  // issue #239: every production call goes through the circuit breaker, not
  // just buildProductionCallModel's raw fetch -- see buildGuardedProductionCallModel's
  // docstring for why this replaces the bare productionCallModel wiring.
  // GPU-free mode: serverUrl is null, so use the offline stub instead.
  _circuitBreakerHandle = !serverUrl
    ? buildOfflineCallModel()
    : buildGuardedProductionCallModel({ serverUrl, nCtx });
  const productionMicrocompact = buildProductionMicrocompact();

  _loopDeps = createLoopDeps({
    callModel:    _circuitBreakerHandle.callModel,
    microcompact: productionMicrocompact,
    // autocompact is engine-store-bound (it rewrites the persisted conversation),
    // so QueryEngine builds it against its own message log; the LoopDeps default
    // (no-op) applies here and is unused.
  });

  if (opts.nonInteractive) {
    await initializeTelemetryAfterTrust().catch(() => {});
  }

  _initialized = true;
}

// ---------------------------------------------------------------------------
// getLoopDeps — returns the wired LoopDeps; throws if init() not completed
// ---------------------------------------------------------------------------

export function getLoopDeps(): LoopDeps {
  if (!_loopDeps) {
    throw new Error("session-init: getLoopDeps() called before init() completed");
  }
  return _loopDeps;
}

// ---------------------------------------------------------------------------
// initializeTelemetryAfterTrust — called after trust dialog acceptance
// ---------------------------------------------------------------------------

export async function initializeTelemetryAfterTrust(): Promise<void> {
  if (_telemetryInitialized) return;
  _telemetryInitialized = true;
  await _lazyLoadOtel().catch(() => {});
  const cur = parseInt(process.env["EMBER_SESSION_COUNT"] ?? "0", 10);
  process.env["EMBER_SESSION_COUNT"] = String((isNaN(cur) ? 0 : cur) + 1);
}

// ---------------------------------------------------------------------------
// Test helpers (reset module state between test runs)
// ---------------------------------------------------------------------------

export function _resetInitForTests(): void {
  _initialized          = false;
  _initPromise          = null;
  _loopDeps             = null;
  _telemetryInitialized = false;
  _cleanupHandlers.length = 0;
  _resolvedNCtx          = null;
  _circuitBreakerHandle  = null;
}

export function _getLoopDepsForTests(): LoopDeps | null {
  return _loopDeps;
}
