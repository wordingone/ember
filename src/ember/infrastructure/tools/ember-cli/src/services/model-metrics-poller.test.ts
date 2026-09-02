// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/model-metrics-poller.test.ts — AC9 tests for the model-metrics poller.
//
// AC9a: parsePrometheusLine — comment lines, blank lines, metric+value, label stripping
// AC9b: extractMetric — finds named metric in multi-line body; returns null when absent
// AC9c: parseMetricsBody — maps llama.cpp Prometheus body to ModelMetrics
// AC9d: fetchModelMetrics — success path (mocked fetch), network error, non-200, timeout

import { describe, it, expect, mock, beforeEach, afterEach } from "bun:test";
import {
  parsePrometheusLine,
  extractMetric,
  parseMetricsBody,
  fetchModelMetrics,
  DEFAULT_METRICS_URL,
  FETCH_TIMEOUT_MS,
} from "./model-metrics-poller.ts";

// ---------------------------------------------------------------------------
// AC9a — parsePrometheusLine
// ---------------------------------------------------------------------------

describe("AC9a: parsePrometheusLine", () => {
  it("returns null for blank line", () => {
    expect(parsePrometheusLine("")).toBeNull();
    expect(parsePrometheusLine("   ")).toBeNull();
  });

  it("returns null for comment lines", () => {
    expect(parsePrometheusLine("# HELP llamacpp:tokens_per_second")).toBeNull();
    expect(parsePrometheusLine("# TYPE llamacpp:tokens_per_second gauge")).toBeNull();
  });

  it("parses a plain metric line", () => {
    const result = parsePrometheusLine("llamacpp:kv_cache_tokens_cell 42");
    expect(result).not.toBeNull();
    expect(result!.name).toBe("llamacpp:kv_cache_tokens_cell");
    expect(result!.value).toBe(42);
  });

  it("parses a metric line with a float value", () => {
    const result = parsePrometheusLine("llamacpp:tokens_per_second 28.35");
    expect(result).not.toBeNull();
    expect(result!.value).toBeCloseTo(28.35, 2);
  });

  it("strips label blocks before parsing", () => {
    const result = parsePrometheusLine('llamacpp:kv_cache_tokens_cell{slot="0"} 100');
    expect(result).not.toBeNull();
    expect(result!.name).toBe("llamacpp:kv_cache_tokens_cell");
    expect(result!.value).toBe(100);
  });

  it("strips empty label blocks", () => {
    const result = parsePrometheusLine("llama_n_ctx{} 32768");
    expect(result).not.toBeNull();
    expect(result!.name).toBe("llama_n_ctx");
    expect(result!.value).toBe(32768);
  });

  it("handles leading/trailing whitespace", () => {
    const result = parsePrometheusLine("  llamacpp:tokens_per_second 5.0  ");
    expect(result).not.toBeNull();
    expect(result!.name).toBe("llamacpp:tokens_per_second");
  });

  it("returns null when value is not a number", () => {
    expect(parsePrometheusLine("some_metric not_a_number")).toBeNull();
  });

  it("returns null for a line with only one token", () => {
    expect(parsePrometheusLine("only_metric_no_value")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC9b — extractMetric
// ---------------------------------------------------------------------------

const SAMPLE_BODY = `
# HELP llamacpp:kv_cache_tokens_cell Number of used KV cache cells
# TYPE llamacpp:kv_cache_tokens_cell gauge
llamacpp:kv_cache_tokens_cell{} 512
# HELP llamacpp:tokens_per_second Decode throughput
# TYPE llamacpp:tokens_per_second gauge
llamacpp:tokens_per_second 27.4
# HELP llama_n_ctx Context window size
llama_n_ctx 32768
`.trim();

describe("AC9b: extractMetric", () => {
  it("finds an existing metric by name", () => {
    expect(extractMetric(SAMPLE_BODY, "llamacpp:kv_cache_tokens_cell")).toBe(512);
  });

  it("finds throughput metric", () => {
    const tps = extractMetric(SAMPLE_BODY, "llamacpp:tokens_per_second");
    expect(tps).toBeCloseTo(27.4, 1);
  });

  it("finds context-window metric", () => {
    expect(extractMetric(SAMPLE_BODY, "llama_n_ctx")).toBe(32768);
  });

  it("returns null for an absent metric", () => {
    expect(extractMetric(SAMPLE_BODY, "nonexistent_metric")).toBeNull();
  });

  it("returns null on empty body", () => {
    expect(extractMetric("", "llamacpp:kv_cache_tokens_cell")).toBeNull();
  });

  it("returns the first occurrence when a name appears multiple times", () => {
    const body = "my_metric 10\nmy_metric 20";
    expect(extractMetric(body, "my_metric")).toBe(10);
  });
});

// ---------------------------------------------------------------------------
// AC9c — parseMetricsBody
// ---------------------------------------------------------------------------

describe("AC9c: parseMetricsBody", () => {
  it("extracts contextTokens from kv_cache_tokens_cell", () => {
    const m = parseMetricsBody(SAMPLE_BODY);
    expect(m.contextTokens).toBe(512);
  });

  it("extracts maxContextTokens from llama_n_ctx", () => {
    const m = parseMetricsBody(SAMPLE_BODY);
    expect(m.maxContextTokens).toBe(32768);
  });

  it("extracts tokensPerSec from tokens_per_second", () => {
    const m = parseMetricsBody(SAMPLE_BODY);
    expect(m.tokensPerSec).toBeCloseTo(27.4, 1);
  });

  it("VRAM fields default to 0 (not exposed by standard llama.cpp)", () => {
    const m = parseMetricsBody(SAMPLE_BODY);
    expect(m.vramUsedGb).toBe(0);
    expect(m.vramTotalGb).toBe(0);
  });

  it("all fields default to 0 on empty body", () => {
    const m = parseMetricsBody("");
    expect(m.contextTokens).toBe(0);
    expect(m.maxContextTokens).toBe(0);
    expect(m.tokensPerSec).toBe(0);
    expect(m.vramUsedGb).toBe(0);
    expect(m.vramTotalGb).toBe(0);
  });

  it("contextTokens is rounded to an integer", () => {
    const body = "llamacpp:kv_cache_tokens_cell 100.7";
    const m = parseMetricsBody(body);
    expect(Number.isInteger(m.contextTokens)).toBe(true);
    expect(m.contextTokens).toBe(101);
  });

  it("prefers llamacpp:n_ctx when llama_n_ctx is absent", () => {
    const body = "llamacpp:n_ctx 16384";
    const m = parseMetricsBody(body);
    expect(m.maxContextTokens).toBe(16384);
  });

  it("prefers llamacpp:eval_tokens_seconds when tokens_per_second is absent", () => {
    const body = "llamacpp:eval_tokens_seconds 15.0";
    const m = parseMetricsBody(body);
    expect(m.tokensPerSec).toBeCloseTo(15.0, 1);
  });
});

// ---------------------------------------------------------------------------
// AC9d — fetchModelMetrics (mocked fetch)
// ---------------------------------------------------------------------------

describe("AC9d: fetchModelMetrics", () => {
  // Save and restore global fetch between tests.
  const origFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = origFetch; });

  it("returns parsed ModelMetrics on 200 response", async () => {
    globalThis.fetch = mock(async (_url: string) => ({
      ok:   true,
      text: async () => "llamacpp:kv_cache_tokens_cell 64\nllama_n_ctx 8192\nllamacpp:tokens_per_second 30.0",
    })) as unknown as typeof fetch;

    const result = await fetchModelMetrics();
    expect(result).not.toBeNull();
    expect(result!.contextTokens).toBe(64);
    expect(result!.maxContextTokens).toBe(8192);
    expect(result!.tokensPerSec).toBeCloseTo(30.0, 1);
  });

  it("returns null on non-OK HTTP status", async () => {
    globalThis.fetch = mock(async () => ({
      ok:   false,
      text: async () => "",
    })) as unknown as typeof fetch;

    expect(await fetchModelMetrics()).toBeNull();
  });

  it("returns null on network error (fetch rejects)", async () => {
    globalThis.fetch = mock(async () => { throw new Error("ECONNREFUSED"); }) as unknown as typeof fetch;
    expect(await fetchModelMetrics()).toBeNull();
  });

  it("returns null on AbortError (timeout)", async () => {
    globalThis.fetch = mock(async (_url: string, opts: RequestInit) => {
      // Simulate abort: call the signal's abort handler path
      opts.signal?.addEventListener("abort", () => {});
      throw new DOMException("The operation was aborted.", "AbortError");
    }) as unknown as typeof fetch;

    expect(await fetchModelMetrics()).toBeNull();
  });

  it("passes the supplied URL to fetch", async () => {
    let capturedUrl = "";
    globalThis.fetch = mock(async (url: string) => {
      capturedUrl = url;
      return { ok: true, text: async () => "" };
    }) as unknown as typeof fetch;

    await fetchModelMetrics("http://127.0.0.1:9999/custom");
    expect(capturedUrl).toBe("http://127.0.0.1:9999/custom");
  });

  it("uses DEFAULT_METRICS_URL when no URL is supplied", async () => {
    let capturedUrl = "";
    globalThis.fetch = mock(async (url: string) => {
      capturedUrl = url;
      return { ok: true, text: async () => "" };
    }) as unknown as typeof fetch;

    await fetchModelMetrics();
    expect(capturedUrl).toBe(DEFAULT_METRICS_URL);
  });

  it("FETCH_TIMEOUT_MS is exported and positive", () => {
    expect(FETCH_TIMEOUT_MS).toBeGreaterThan(0);
  });
});
