// services/model-circuit-breaker.ts — issue #239: cross-call retry circuit
// breaker for the model-client request path.
//
// The existing per-turn retry (api-backend.ts's shouldRetry/computeRetryDelay,
// wired into query-engine.ts's callModelWithRetry for issue #197) bounds
// retries WITHIN a single turn: a deterministic 4xx throws immediately, a
// transient 5xx/429/network failure gets a handful of backed-off attempts,
// then the turn ends with a terminal error. What it does NOT do is remember
// that failure across turns -- the next user message, or the next
// goal-continuation re-invocation (issue #211), starts a fresh attempt count
// and retries the SAME broken endpoint from scratch. Repeated indefinitely
// (operator session, 2026-07-05T19:00 -> 07-06T15:00, ~20h against a leftover
// #195/#196 fixture server returning HTTP 400) that is an unbounded loop in
// every way that matters to the operator, even though no single turn ever
// retried "forever."
//
// This module is the missing cross-call memory: a small state machine that
// tracks consecutive endpoint failures and, once tripped, refuses to even
// attempt a network call (fail fast, zero additional load on the broken
// endpoint) until a single half-open probe is due. Pure functions operating
// on an explicit, immutable state value -- no module-level singletons, no
// timers -- so every transition is independently testable (see
// model-circuit-breaker.test.ts) and the caller controls persistence scope
// (session-init.ts holds one instance for the life of the process).

// ---------------------------------------------------------------------------
// Constants (mission-frozen: dispatch-spec-239-196-circuit-breaker.md)
// ---------------------------------------------------------------------------

/** Base delay for the first bounded-backoff retry. */
export const CIRCUIT_BASE_DELAY_MS = 1_000;
/** Backoff never waits longer than this between attempts. */
export const CIRCUIT_BACKOFF_CAP_MS = 30_000;
/** Total attempts (including the first) before a retryable failure opens the circuit. */
export const CIRCUIT_MAX_ATTEMPTS = 6;
/** Once open, at most one half-open probe attempt per this many ms. */
export const CIRCUIT_PROBE_INTERVAL_MS = 60_000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CircuitState = "closed" | "open" | "half-open";

export interface CircuitBreakerState {
  state: CircuitState;
  /** Consecutive failures observed since the last full reset (recordSuccess). */
  consecutiveFailures: number;
  /** Epoch ms the circuit first opened, or null if it has never opened (or was reset). */
  openedAt: number | null;
  /** Epoch ms the most recent probe attempt started, or null if none yet. */
  lastProbeAt: number | null;
  /** HTTP status of the failure that most recently changed circuit state, if any. */
  lastStatus: number | null;
  /** Human-readable cause of the most recent failure, e.g. "HTTP 400" or "connection error". */
  lastReason: string | null;
  /** The endpoint URL this breaker is tracking. */
  endpoint: string | null;
}

/** Everything the degraded-state banner (status-bar.ts) needs to render. */
export interface DegradedBannerInfo {
  active: true;
  endpoint: string | null;
  lastStatus: number | null;
  lastReason: string | null;
  attemptCount: number;
  /** Epoch ms the next half-open probe becomes eligible. */
  nextProbeAt: number;
  /** True while a half-open probe attempt is in flight. */
  probing: boolean;
}

/** Info about a single failed attempt, used to decide the next transition. */
export interface FailureInfo {
  status: number | null;
  isNetworkError: boolean;
  endpoint: string;
  reason: string;
  now: number;
}

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------

export function createCircuitBreakerState(): CircuitBreakerState {
  return {
    state: "closed",
    consecutiveFailures: 0,
    openedAt: null,
    lastProbeAt: null,
    lastStatus: null,
    lastReason: null,
    endpoint: null,
  };
}

// ---------------------------------------------------------------------------
// Classification
// ---------------------------------------------------------------------------

/**
 * True for a deterministic client error that retrying can never fix: any 4xx
 * except 408 (server-chosen timeout) and 429 (rate limit) -- both of those
 * mirror a transient condition and get bounded backoff instead, matching
 * api-backend.ts's existing shouldRetry contract (issue #197).
 */
export function isNonRetryableClientError(status: number | null): boolean {
  if (status === null) return false;
  if (status === 408 || status === 429) return false;
  return status >= 400 && status < 500;
}

// ---------------------------------------------------------------------------
// Backoff timing
// ---------------------------------------------------------------------------

/**
 * Exponential backoff delay for retry attempt N (0-indexed), base 1s capped
 * at 30s, with up to 20% jitter -- same shape as api-backend.ts's
 * computeRetryDelay, distinct constants (this breaker's mission-frozen
 * schedule is tighter: 6 attempts max vs. the per-turn retry's 10).
 */
export function computeCircuitBackoffDelay(attempt: number): number {
  const base = CIRCUIT_BASE_DELAY_MS * Math.pow(2, attempt);
  const capped = Math.min(base, CIRCUIT_BACKOFF_CAP_MS);
  const jitter = capped * 0.2 * Math.random();
  return Math.round(capped + jitter);
}

// ---------------------------------------------------------------------------
// State transitions
// ---------------------------------------------------------------------------

/** Returns whether (and how) the caller may attempt a call right now. */
export function canAttempt(
  state: CircuitBreakerState,
  now: number,
): { allowed: boolean; isProbe: boolean } {
  if (state.state === "closed") return { allowed: true, isProbe: false };
  if (state.state === "half-open") return { allowed: false, isProbe: false }; // a probe is already in flight
  // open
  const last = state.lastProbeAt ?? state.openedAt ?? now;
  if (now - last >= CIRCUIT_PROBE_INTERVAL_MS) return { allowed: true, isProbe: true };
  return { allowed: false, isProbe: false };
}

/**
 * Records a single failed attempt and returns the resulting state.
 * - A non-retryable 4xx opens the circuit immediately (fail fast, mission 1).
 * - A retryable failure (429/5xx/network) accumulates; the circuit opens once
 *   consecutiveFailures reaches CIRCUIT_MAX_ATTEMPTS.
 * - A failed half-open probe returns to "open" and resets the probe clock,
 *   WITHOUT restarting a fresh 6-attempt accumulation (the probe is a single
 *   shot, not a new bounded-backoff cycle).
 */
export function recordFailure(
  state: CircuitBreakerState,
  info: FailureInfo,
): CircuitBreakerState {
  const nonRetryable = isNonRetryableClientError(info.status);

  if (state.state === "half-open") {
    return {
      state: "open",
      consecutiveFailures: Math.max(state.consecutiveFailures, CIRCUIT_MAX_ATTEMPTS),
      openedAt: state.openedAt ?? info.now,
      lastProbeAt: info.now,
      lastStatus: info.status,
      lastReason: info.reason,
      endpoint: info.endpoint,
    };
  }

  const consecutiveFailures = state.consecutiveFailures + 1;
  const shouldOpen = nonRetryable || consecutiveFailures >= CIRCUIT_MAX_ATTEMPTS;

  return {
    state: shouldOpen ? "open" : "closed",
    consecutiveFailures,
    openedAt: shouldOpen ? (state.openedAt ?? info.now) : state.openedAt,
    lastProbeAt: state.lastProbeAt,
    lastStatus: info.status,
    lastReason: info.reason,
    endpoint: info.endpoint,
  };
}

/** A successful call always fully resets the breaker, from any state. */
export function recordSuccess(_state: CircuitBreakerState): CircuitBreakerState {
  return createCircuitBreakerState();
}

/** Marks the start of a half-open probe attempt (open -> half-open). */
export function markProbeStart(state: CircuitBreakerState, now: number): CircuitBreakerState {
  return { ...state, state: "half-open", lastProbeAt: now };
}

// ---------------------------------------------------------------------------
// UI projection
// ---------------------------------------------------------------------------

/** Projects breaker state into what the degraded-state banner needs, or null when healthy. */
export function describeDegradedBanner(
  state: CircuitBreakerState,
  now: number,
): DegradedBannerInfo | null {
  if (state.state === "closed") return null;
  const last = state.lastProbeAt ?? state.openedAt ?? now;
  return {
    active: true,
    endpoint: state.endpoint,
    lastStatus: state.lastStatus,
    lastReason: state.lastReason,
    attemptCount: state.consecutiveFailures,
    nextProbeAt: last + CIRCUIT_PROBE_INTERVAL_MS,
    probing: state.state === "half-open",
  };
}
