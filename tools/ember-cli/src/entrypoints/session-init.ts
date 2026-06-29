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
} from "../services/api-openai-adapter.ts";
import { createMicrocompact } from "../services/compaction.ts";

// ---------------------------------------------------------------------------
// Module-level state (singletons)
// ---------------------------------------------------------------------------

let _initialized        = false;
let _initPromise:        Promise<void> | null = null;
let _loopDeps:           LoopDeps | null      = null;
let _telemetryInitialized = false;
let _cleanupHandlers:   Array<() => unknown>  = [];

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

    const reqBody: Record<string, unknown> = { ...openAiReq };
    reqBody["cache_prompt"] = false;

    if (jsonSchema) {
      reqBody["response_format"] = {
        type:        "json_schema",
        json_schema: { name: "output", schema: jsonSchema },
      };
    }

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Connection:     "keep-alive",
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
      throw new Error(
        `Model server returned HTTP ${response.status}: ${response.statusText}`,
      );
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
  const nCtx = opts.nCtx ?? 4096;

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

  const productionCallModel    = buildProductionCallModel({ serverUrl, nCtx });
  const productionMicrocompact = buildProductionMicrocompact();

  _loopDeps = createLoopDeps({
    callModel:    productionCallModel,
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
}

export function _getLoopDepsForTests(): LoopDeps | null {
  return _loopDeps;
}
