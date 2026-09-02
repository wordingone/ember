// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// types/api-protocol.ts
// HTTP request/response envelopes and API error types for Ember's backend services.
// L1 leaf: no intra-ember dependencies. Types only — no runtime implementation.

// ---- Stop reasons ----

/**
 * Reason codes returned by the model when a generation turn ends.
 * The string-intersection arm (`string & {}`) allows forward-compatible extension
 * without requiring exhaustive switch statements throughout the codebase.
 */
export type BetaStopReason =
  | 'end_turn'
  | 'max_tokens'
  | 'stop_sequence'
  | 'tool_use'
  | 'pause_turn'
  | 'timeout'
  | (string & {});

// ---- HTTP envelope types ----

/** Shape of an outgoing API request before serialization. */
export interface ApiRequest {
  method: string;
  url: string;
  headers?: Record<string, string>;
  body?: unknown;
}

/**
 * Shape of an API response after deserialization.
 * `T` is the domain-specific payload type (e.g., a completion object).
 */
export interface ApiResponse<T> {
  status: number;
  statusText: string;
  headers?: Record<string, string>;
  data: T;
}

/** Machine-readable error returned by backend services. */
export interface ApiError {
  /** Short error code for routing and retry logic (e.g., 'auth_error', 'rate_limit'). */
  code: string;
  /** Human-readable description of the error. */
  message: string;
  /** Additional structured context for debugging. */
  details?: unknown;
}

// ---- Client configuration ----

/** Configuration for an API client instance. */
export interface ApiClientConfig {
  /** Base URL to prepend to all request paths. */
  baseUrl?: string;
  /** Request timeout in milliseconds. */
  timeout?: number;
  /** Default headers included with every request. */
  headers?: Record<string, string>;
}
