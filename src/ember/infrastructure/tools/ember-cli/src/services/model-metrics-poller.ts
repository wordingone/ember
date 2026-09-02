// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/model-metrics-poller.ts — Polls a local model server for live inference metrics.
// Feeds the ModelMetricsBar in status-bar.ts with context usage, throughput, and VRAM data.
// AC9 spec: parsePrometheusLine, extractMetric, parseMetricsBody, fetchModelMetrics,
// useModelMetricsPoller — all tested without a live server.

import { useState, useEffect } from "react";
import type { ModelMetrics } from "../components/status-bar.ts";

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

/** Default URL for the local model server Prometheus metrics endpoint. */
export const DEFAULT_METRICS_URL = "http://127.0.0.1:53338/metrics";

/** Default polling interval in milliseconds. */
export const DEFAULT_POLL_INTERVAL_MS = 2000;

/** HTTP request timeout in milliseconds — short so unreachable server is fast-fail. */
export const FETCH_TIMEOUT_MS = 1000;

// ---------------------------------------------------------------------------
// Prometheus text parser (llama.cpp /metrics format)
// ---------------------------------------------------------------------------

/**
 * Parses one line of Prometheus text-format exposition into { name, value }.
 * Comment lines (starting with #) and blank lines return null.
 * Label blocks { ... } are stripped before parsing so both
 * `llamacpp:kv_cache_tokens_cell 42` and
 * `llamacpp:kv_cache_tokens_cell{} 42` are accepted.
 */
export function parsePrometheusLine(
  line: string,
): { name: string; value: number } | null {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith("#")) return null;

  // Strip optional label block: `metricname{label="val",...} value [ts]`
  const noLabels = trimmed.replace(/\{[^}]*\}/, "");
  const parts    = noLabels.trim().split(/\s+/);
  if (parts.length < 2) return null;

  const name  = parts[0]!;
  const value = parseFloat(parts[1]!);
  if (!name || isNaN(value)) return null;

  return { name, value };
}

/**
 * Scans a Prometheus text body for the first occurrence of `metricName`
 * and returns its value, or null when absent.
 */
export function extractMetric(body: string, metricName: string): number | null {
  for (const line of body.split("\n")) {
    const parsed = parsePrometheusLine(line);
    if (parsed !== null && parsed.name === metricName) return parsed.value;
  }
  return null;
}

// ---------------------------------------------------------------------------
// ModelMetrics extraction from llama.cpp Prometheus output
// ---------------------------------------------------------------------------

/**
 * Maps a llama.cpp /metrics Prometheus body to a ModelMetrics shape.
 * Absent metrics default to 0 (the status-bar suppresses 0/0 VRAM).
 *
 * Known metric names (llama.cpp ≥b3000):
 *   llamacpp:kv_cache_tokens_cell  — occupied KV-cache slots (≈ context tokens used)
 *   llama_n_ctx                    — configured context window size
 *   llamacpp:n_ctx                 — alternative name in some builds
 *   llamacpp:tokens_per_second     — rolling-mean decode throughput
 *   llamacpp:eval_tokens_seconds   — alternative throughput metric
 *
 * VRAM is not exposed by standard llama.cpp Prometheus output; the two VRAM
 * fields remain 0 and the display layer hides the `0.0/0.0GB` segment.
 */
export function parseMetricsBody(body: string): ModelMetrics {
  const kvUsed = extractMetric(body, "llamacpp:kv_cache_tokens_cell") ?? 0;

  const kvMax  =
    extractMetric(body, "llama_n_ctx")     ??
    extractMetric(body, "llamacpp:n_ctx")  ??
    0;

  const tps =
    extractMetric(body, "llamacpp:tokens_per_second")  ??
    extractMetric(body, "llamacpp:eval_tokens_seconds") ??
    0;

  return {
    contextTokens:    Math.round(kvUsed),
    maxContextTokens: Math.round(kvMax),
    vramUsedGb:       0,
    vramTotalGb:      0,
    tokensPerSec:     tps,
  };
}

// ---------------------------------------------------------------------------
// Network fetcher
// ---------------------------------------------------------------------------

/**
 * Fetches live inference metrics from the model server.
 * Returns null on network failure, timeout, or non-OK HTTP status.
 * Never throws.
 */
export async function fetchModelMetrics(
  url: string = DEFAULT_METRICS_URL,
): Promise<ModelMetrics | null> {
  try {
    const controller = new AbortController();
    const timer      = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    let res: Response;
    try {
      res = await fetch(url, { signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
    if (!res.ok) return null;
    const body = await res.text();
    return parseMetricsBody(body);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// React polling hook
// ---------------------------------------------------------------------------

/**
 * Polls the model server at `intervalMs` cadence.
 * Returns null until the first successful response arrives, and whenever the
 * server is unreachable.  Cleans up the interval on unmount.
 *
 * @param url        Prometheus metrics endpoint (default: DEFAULT_METRICS_URL)
 * @param intervalMs Poll cadence in ms (default: DEFAULT_POLL_INTERVAL_MS)
 */
export function useModelMetricsPoller(
  url:        string = DEFAULT_METRICS_URL,
  intervalMs: number = DEFAULT_POLL_INTERVAL_MS,
): ModelMetrics | null {
  const [metrics, setMetrics] = useState<ModelMetrics | null>(null);

  useEffect(() => {
    let active = true;

    const poll = async (): Promise<void> => {
      const result = await fetchModelMetrics(url);
      if (active) setMetrics(result);
    };

    void poll();                              // immediate first fetch
    const id = setInterval(poll, intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [url, intervalMs]);

  return metrics;
}
