// services/model-circuit-breaker-client.ts — issue #239: wraps the
// model-client request function (session-init.ts's buildProductionCallModel
// output, i.e. LoopDeps.callModel) with the pure circuit-breaker state
// machine from model-circuit-breaker.ts.
//
// This is the seam that actually decides whether a network call happens at
// all. Once canAttempt() says no, wrappedCallModel throws CircuitOpenError
// synchronously -- the underlying callModel is never invoked -- so a caller
// that keeps calling in a loop (a fresh user turn, or a goal-continuation
// re-invocation, issue #211) can knock on the wrapper as many times as it
// likes without ever generating more than CIRCUIT_MAX_ATTEMPTS real requests
// against a broken endpoint. That is the actual fix for the 20h wedge: not a
// tighter single-turn retry cap (issue #197 already has one), but a memory
// of the failure that survives across turns.
//
// A thrown CircuitOpenError is deliberately NOT classified as retryable by
// api-backend.ts's shouldRetry (status stays null, and it carries none of
// RETRYABLE_TRANSPORT_ERROR_CODES) -- so query-engine.ts's existing
// callModelWithRetry (issue #197), which wraps this as LoopDeps.callModel,
// treats it as an immediate terminal error and does not layer a second
// round of retries on top. The two mechanisms compose without doubling
// delay: #197's loop handles same-turn transient hiccups against a healthy
// endpoint; this breaker handles a persistently broken one across turns.

import { ModelHttpError } from "./api-openai-adapter.ts";
import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";
import {
  CIRCUIT_MAX_ATTEMPTS,
  type CircuitBreakerState,
  createCircuitBreakerState,
  isNonRetryableClientError,
  computeCircuitBackoffDelay,
  canAttempt,
  recordFailure,
  recordSuccess,
  markProbeStart,
} from "./model-circuit-breaker.ts";

// ---------------------------------------------------------------------------
// Transport-error classification
// ---------------------------------------------------------------------------

/**
 * Node/Bun connection-failure error codes a killed/unreachable model server
 * actually throws. Mirrors query-engine.ts's RETRYABLE_TRANSPORT_ERROR_CODES
 * (issue #197 Leg 3/4 -- measured directly against the real llama-server
 * binary: Bun's fetch() throws a plain Error carrying `.code`, not a
 * TypeError, for both a from-scratch refused connection and a mid-stream
 * kill). Duplicated here rather than imported so this module has zero
 * coupling to query-engine.ts's internals; keep the two lists in sync if the
 * transport classification ever changes.
 */
const RETRYABLE_TRANSPORT_ERROR_CODES = new Set([
  "ConnectionRefused",
  "ECONNRESET",
  "ECONNREFUSED",
  "ETIMEDOUT",
  "EPIPE",
  "EHOSTUNREACH",
  "EAI_AGAIN",
]);

function isRetryableTransportError(err: unknown): boolean {
  if (err instanceof TypeError) return true;
  if (err instanceof Error && err.name === "AbortError") return true;
  if (err instanceof Error) {
    const code = (err as { code?: unknown }).code;
    if (typeof code === "string" && RETRYABLE_TRANSPORT_ERROR_CODES.has(code)) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// CircuitOpenError
// ---------------------------------------------------------------------------

/**
 * Thrown whenever the circuit breaker refuses (or gives up on) a call. Not
 * a ModelHttpError and carries no retryable transport code, so the existing
 * per-turn retry (api-backend.ts's shouldRetry) always treats it as terminal.
 */
export class CircuitOpenError extends Error {
  constructor(
    public readonly endpoint: string,
    public readonly circuitState: CircuitBreakerState,
    public readonly cause?: unknown,
  ) {
    super(
      `Model endpoint degraded: circuit open for ${endpoint}` +
        (circuitState.lastReason ? ` (last failure: ${circuitState.lastReason}` +
          (circuitState.lastStatus != null ? ` ${circuitState.lastStatus}` : "") + ")" : ""),
    );
    this.name = "CircuitOpenError";
  }
}

// ---------------------------------------------------------------------------
// Wrapper
// ---------------------------------------------------------------------------

export interface WrapCircuitBreakerOptions {
  /** Endpoint URL this breaker instance tracks (surfaced on the banner and in errors). */
  endpoint: string;
  /** Overridable for tests; defaults to a real setTimeout-based sleep. */
  sleep?: (ms: number, signal?: AbortSignal) => Promise<void>;
  /** Overridable clock for tests; defaults to Date.now. */
  now?: () => number;
  /** Notified after every state transition (wire into the TUI degraded banner). */
  onStateChange?: (state: CircuitBreakerState) => void;
  /** Resume from a prior state instead of starting closed. */
  initialState?: CircuitBreakerState;
}

export interface CircuitBreakerClientHandle {
  callModel: (params: CallModelParams) => Promise<ModelResponse>;
  getState: () => CircuitBreakerState;
}

function defaultSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) { resolve(); return; }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });
}

/**
 * Wraps a raw callModel function with circuit-breaker behavior:
 * - non-retryable 4xx: fail fast, open immediately, zero backoff wait.
 * - 429/5xx/network: bounded exponential backoff (1s base / 30s cap),
 *   CIRCUIT_MAX_ATTEMPTS total attempts, then open.
 * - once open: every call is rejected locally (no network) until a single
 *   half-open probe becomes due (at most once per CIRCUIT_PROBE_INTERVAL_MS);
 *   a failed probe re-arms the same window, a successful one fully resets.
 * - errors unrelated to endpoint health (a synchronous client-side guard
 *   like the prefill-overflow check, or a user-initiated abort) pass through
 *   untouched and never move circuit state.
 */
export function wrapModelClientWithCircuitBreaker(
  callModel: (params: CallModelParams) => Promise<ModelResponse>,
  opts: WrapCircuitBreakerOptions,
): CircuitBreakerClientHandle {
  let state = opts.initialState ?? createCircuitBreakerState();
  const sleep = opts.sleep ?? defaultSleep;
  const now = opts.now ?? (() => Date.now());
  const notify = () => opts.onStateChange?.(state);

  async function wrappedCallModel(params: CallModelParams): Promise<ModelResponse> {
    const gate = canAttempt(state, now());
    if (!gate.allowed) {
      throw new CircuitOpenError(opts.endpoint, state);
    }
    if (gate.isProbe) {
      state = markProbeStart(state, now());
      notify();
    }

    let attempt = 0;
    while (true) {
      try {
        const response = await callModel(params);
        state = recordSuccess(state);
        notify();
        return response;
      } catch (err) {
        if (params.abortSignal?.aborted) throw err;

        const status = err instanceof ModelHttpError ? err.status : null;
        const isNetworkError = status === null && isRetryableTransportError(err);
        const nonRetryable4xx = isNonRetryableClientError(status);
        const circuitRelevant =
          nonRetryable4xx ||
          status === 429 ||
          (status !== null && status >= 500 && status < 600) ||
          isNetworkError;

        if (!circuitRelevant) throw err;

        const reason = status !== null ? `HTTP ${status}` : "connection error";
        state = recordFailure(state, {
          status,
          isNetworkError,
          endpoint: opts.endpoint,
          reason,
          now: now(),
        });
        notify();

        if (state.state !== "closed") {
          // Opened just now (fail-fast 4xx, or exhausted the bounded backoff
          // budget), or a half-open probe bounced straight back to open.
          throw new CircuitOpenError(opts.endpoint, state, err);
        }

        const delayMs = computeCircuitBackoffDelay(attempt);
        attempt += 1;
        await sleep(delayMs, params.abortSignal);
      }
    }
  }

  return { callModel: wrappedCallModel, getState: () => state };
}

export { CIRCUIT_MAX_ATTEMPTS };
