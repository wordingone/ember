// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// api-backend.ts — HTTP retry logic, error classification, and request-level utilities.
// W2-B: local-only adapter. Cloud-specific concepts (privileged user, overage credit)
// are stripped. shouldUseOpenAIAdapter always returns true; isPrivilegedUser always false.

import { join } from 'path';
import { getEmberConfigHomeDir } from './utils/env-detection.ts';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const BASE_DELAY_MS = 500;
export const BACKOFF_CAP_MS = 8_000;
export const MAX_RETRY_ATTEMPTS = 10;
export const MAX_529_RETRIES_FOREGROUND = 3;
export const FILE_DOWNLOAD_SIZE_CAP_BYTES = 500 * 1024 * 1024;

// ---------------------------------------------------------------------------
// Error classification
// ---------------------------------------------------------------------------

export type ApiErrorCategory =
  | 'auth'
  | 'ratelimit'
  | 'overloaded'
  | 'aborted'
  | 'connection'
  | 'prompt_too_long'
  | 'other';

export interface ClassifiedApiError {
  category: ApiErrorCategory;
  status: number | null;
}

type BodyWithError = { error?: { type?: string } } | null | undefined;

/**
 * Classifies an API error into a semantic category.
 * Precedence: aborted → connection → status-based → other.
 */
export function classifyApiError(
  status: number | null,
  body: unknown,
  isAborted: boolean,
  isConnectionError: boolean,
): ClassifiedApiError {
  if (isAborted) return { category: 'aborted', status: null };
  if (isConnectionError) return { category: 'connection', status: null };

  if (status === 401) return { category: 'auth', status };
  if (status === 429) return { category: 'ratelimit', status };
  if (status === 529) return { category: 'overloaded', status };

  if (status === 400) {
    const b = body as BodyWithError;
    if (b?.error?.type === 'prompt_too_long') {
      return { category: 'prompt_too_long', status };
    }
  }

  return { category: 'other', status };
}

// ---------------------------------------------------------------------------
// Retry logic
// ---------------------------------------------------------------------------

/**
 * Determines whether a failed request should be retried.
 * Network errors use a slightly lower retry cap than HTTP errors.
 */
export function shouldRetry(
  status: number | null,
  isNetworkError: boolean,
  retryCount: number,
  count529: number,
  isBackground: boolean,
): boolean {
  // Network-level errors: cap at MAX_RETRY_ATTEMPTS - 1
  if (isNetworkError && status === null) {
    return retryCount < MAX_RETRY_ATTEMPTS - 1;
  }

  // Global hard cap for HTTP errors
  if (retryCount >= MAX_RETRY_ATTEMPTS) return false;

  // 529 overloaded: background → bail immediately; foreground → limited retries
  if (status === 529) {
    if (isBackground) return false;
    return count529 < MAX_529_RETRIES_FOREGROUND;
  }

  // 429 rate-limited: retry (respects global cap above)
  if (status === 429) return true;

  // 408 request timeout: the server gave up waiting, not a permanent client
  // error -- retry like 429 (issue #197's fix contract: "4xx except 429/408
  // is deterministic"). Distinct from a *connection*-level timeout (handled
  // above via isNetworkError), this is a real HTTP response the server chose
  // to send.
  if (status === 408) return true;

  // Other 4xx: deterministic client errors (bad request, oversized payload,
  // auth, not found, ...) -- retrying can never succeed, do not retry.
  if (status !== null && status >= 400 && status < 500) return false;

  // 5xx server errors: retry
  if (status !== null && status >= 500 && status < 600) return true;

  return false;
}

/**
 * Computes exponential-backoff delay for a retry attempt.
 * Applies up to 20% jitter and caps at BACKOFF_CAP_MS.
 */
export function computeRetryDelay(attempt: number): number {
  const base = BASE_DELAY_MS * Math.pow(2, attempt);
  const capped = Math.min(base, BACKOFF_CAP_MS);
  const jitter = capped * 0.2 * Math.random();
  return Math.round(capped + jitter);
}

// ---------------------------------------------------------------------------
// Request headers
// ---------------------------------------------------------------------------

/**
 * Builds the standard set of HTTP headers for model API requests.
 * Generates a fresh UUID request-id per call.
 */
export function buildStandardHeaders(
  sessionId: string,
  authorization: string,
  userAgent: string,
): Record<string, string> {
  return {
    'x-client-request-id': crypto.randomUUID(),
    'User-Agent': userAgent,
    'X-Ember-Session-Id': sessionId,
    'Authorization': authorization,
  };
}

// ---------------------------------------------------------------------------
// Session log conflict handling
// ---------------------------------------------------------------------------

export interface ServerConflictState {
  lastKnownServerUuid: string | null;
}

/**
 * On a 409 conflict, adopts the server's last known UUID to resync the log.
 */
export function adoptServerStateOnConflict(
  serverUuid: string | null,
): ServerConflictState {
  return { lastKnownServerUuid: serverUuid };
}

// ---------------------------------------------------------------------------
// Model URL detection
// ---------------------------------------------------------------------------

/**
 * Always returns true in local-only mode. Cloud routing was removed in W2-B.
 */
export function shouldUseOpenAIAdapter(): boolean {
  return true;
}

// ---------------------------------------------------------------------------
// Prompt dump path
// ---------------------------------------------------------------------------

/**
 * Returns the path where prompt debug dumps are written for a given session.
 */
export function getPromptDumpPath(sessionId: string): string {
  return join(getEmberConfigHomeDir(), 'dump-prompts', `${sessionId}.jsonl`);
}

// ---------------------------------------------------------------------------
// Privileged user gate (W2-B: always false — cloud billing stripped)
// ---------------------------------------------------------------------------

/**
 * Always returns false in local-only mode.
 */
export function isPrivilegedUser(): boolean {
  return false;
}
