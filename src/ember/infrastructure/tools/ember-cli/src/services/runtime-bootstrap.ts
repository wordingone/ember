// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/runtime-bootstrap.ts — local model server health polling.
//
// Provides:
//   - waitForServerReady: polls /health until the local llama-server reports
//     { status: "ok" }, or throws after a configurable timeout.
//
// L2: depends on utils/env-detection.ts for the ember home path;
//     uses only Node.js built-ins (fetch, setTimeout) otherwise.

import { getEmberConfigHomeDir } from "../utils/env-detection.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Default port the local inference server listens on. */
export const LLAMA_SERVER_DEFAULT_PORT = 8081;

/** How long to wait between health poll attempts (ms). */
export const HEALTH_POLL_INTERVAL_MS = 2000;

/** How long to wait for the server to become ready before giving up (ms). */
export const HEALTH_POLL_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

// ---------------------------------------------------------------------------
// Health poll
// ---------------------------------------------------------------------------

/**
 * Polls the local llama-server /health endpoint until it responds with
 * `{ status: "ok" }`, then resolves.
 *
 * Throws an Error if the server has not become ready within `timeoutMs`.
 *
 * @param port - Port to poll (default: LLAMA_SERVER_DEFAULT_PORT).
 * @param timeoutMs - Maximum wait time in milliseconds (default: 5 minutes).
 */
export async function waitForServerReady(
  port: number = LLAMA_SERVER_DEFAULT_PORT,
  timeoutMs: number = HEALTH_POLL_TIMEOUT_MS,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 2000);
      try {
        const res = await fetch(`http://localhost:${port}/health`, {
          signal: ctrl.signal,
        });
        if (res.ok) {
          const body = (await res.json()) as { status?: string };
          if (body.status === "ok") return;
        }
      } finally {
        clearTimeout(timer);
      }
    } catch {
      // Network error or abort — keep polling
    }

    await new Promise<void>((resolve) => setTimeout(resolve, HEALTH_POLL_INTERVAL_MS));
  }

  throw new Error(`Server did not become ready within ${timeoutMs}ms`);
}

// ---------------------------------------------------------------------------
// Config home helper (re-exported for consumers that bootstrap the server path)
// ---------------------------------------------------------------------------

export { getEmberConfigHomeDir };
