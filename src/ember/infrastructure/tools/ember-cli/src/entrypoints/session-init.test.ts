// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// entrypoints/session-init.test.ts — issue #157 Leg 2: buildProductionCallModel must
// proactively refuse an oversized request BEFORE it ever reaches the network, rather than
// sending it and risking the server silently wedging (receipt: receipts/operator-sessions/
// session-20260705T234943Z.jsonl -- a 46,634-byte tool result vs an 8192-token n_ctx slot,
// GPU idle, spinner alive >4min with no error ever surfacing). checkPrefillOverflow/fetchNCtx
// (FM_91, AC3/AC4) already existed for exactly this but were never wired to the production
// call path -- these tests pin the wiring, not the guard's own math (that's api-openai-
// adapter.test.ts's job).

import { describe, it, expect, mock, afterEach } from "bun:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  buildProductionCallModel,
  buildGuardedProductionCallModel,
  getResolvedNCtx,
  getToolResultBudget,
  getCircuitBreakerState,
  resolveInitServerUrl,
} from "./session-init.ts";
import { ModelHttpError } from "../services/api-openai-adapter.ts";
import { CircuitOpenError } from "../services/model-circuit-breaker-client.ts";

// issue #197: buildProductionCallModel now throws (rather than fabricating a
// success) when the stream ends without ever seeing a genuine finish_reason
// -- see api-openai-adapter.ts's SseParserContext.sawFinishReason. A mock
// reader that goes straight to `done: true` with no data no longer models a
// real (if minimal) completed SSE response; this helper emits one proper
// finish_reason chunk first, matching what a real server actually sends.
function makeSingleChunkReader() {
  const encoder = new TextEncoder();
  const chunk = encoder.encode(
    'data: {"choices":[{"finish_reason":"stop","index":0,"delta":{}}]}\n\n',
  );
  let sent = false;
  return {
    read: async () => {
      if (!sent) {
        sent = true;
        return { done: false, value: chunk };
      }
      return { done: true, value: undefined };
    },
    releaseLock: () => {},
  };
}

describe("buildProductionCallModel — proactive prefill overflow guard (issue #157)", () => {
  const origFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = origFetch;
    delete process.env["EMBER_MODEL_HTTP_CAPTURE_PATH"];
  });

  it("throws PrefillOverflowError and never calls fetch when the estimated prefill overflows n_ctx", async () => {
    let fetchCalled = false;
    globalThis.fetch = mock(async () => {
      fetchCalled = true;
      throw new Error("fetch should never be reached");
    }) as unknown as typeof fetch;

    const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 8192 });

    const hugeMessage = {
      role: "user" as const,
      content: "X".repeat(60_000), // ~17k tokens at 3.5 chars/token -- overflows an 8192 n_ctx slot
    };

    let thrown: unknown = null;
    try {
      await callModel({
        messages: [hugeMessage],
        systemPrompt: "test",
        tools: [],
        model: "test-model",
        maxTokens: 4096,
      });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).not.toBeNull();
    expect(String((thrown as Error).message)).toContain("Prefill overflow");
    expect(fetchCalled).toBe(false);
  });

  it("does not false-positive on a trivial prompt even when maxTokens carries query-engine.ts's uncapped default of 8192 (live repro: this exact combination tripped the guard against a real ctx-size-8192 server before the reserve-floor fix)", async () => {
    let fetchCalled = false;
    globalThis.fetch = mock(async () => {
      fetchCalled = true;
      return {
        ok: true,
        body: {
          getReader: () => makeSingleChunkReader(),
        },
      } as unknown as Response;
    }) as unknown as typeof fetch;

    const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 8192 });

    let thrown: unknown = null;
    try {
      await callModel({
        messages: [{ role: "user" as const, content: "Read docs/domains/governance/authority/GOAL.md and summarize its first section" }],
        systemPrompt: "test",
        tools: [],
        model: "test-model",
        maxTokens: 8192, // query-engine.ts's default when no maxOutputTokensOverride is set
      });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeNull();
    expect(fetchCalled).toBe(true);
  });

  it("proceeds to fetch when the estimated prefill fits comfortably within n_ctx", async () => {
    let fetchCalled = false;
    globalThis.fetch = mock(async () => {
      fetchCalled = true;
      return {
        ok: true,
        body: {
          getReader: () => makeSingleChunkReader(),
        },
      } as unknown as Response;
    }) as unknown as typeof fetch;

    const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 8192 });

    await callModel({
      messages: [{ role: "user" as const, content: "hello" }],
      systemPrompt: "test",
      tools: [],
      model: "test-model",
      maxTokens: 256,
    });

    expect(fetchCalled).toBe(true);
  });

  // issue #197 Leg 3: query-engine.ts's retry loop classifies on `.status` --
  // a bare Error carries no status and would be misread as a network error
  // (see query-engine.retry.test.ts's regression guard), so a non-ok HTTP
  // response must throw the TYPED ModelHttpError, not a plain Error.
  it("throws a ModelHttpError carrying the real HTTP status on a non-ok response (issue #197)", async () => {
    globalThis.fetch = mock(async () => {
      return { ok: false, status: 400, statusText: "Bad Request" } as unknown as Response;
    }) as unknown as typeof fetch;

    const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 8192 });

    let thrown: unknown = null;
    try {
      await callModel({
        messages: [{ role: "user" as const, content: "hello" }],
        systemPrompt: "test",
        tools: [],
        model: "test-model",
        maxTokens: 256,
      });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeInstanceOf(ModelHttpError);
    expect((thrown as ModelHttpError).status).toBe(400);
  });


  it("captures the exact live request bytes and HTTP error body only when an explicit absolute capture path is set", async () => {
    const captureDir = await mkdtemp(join(tmpdir(), "ember-model-http-capture-"));
    const capturePath = join(captureDir, "capture.json");
    process.env["EMBER_MODEL_HTTP_CAPTURE_PATH"] = capturePath;
    let transmittedBody = "";
    globalThis.fetch = mock(async (_url, init) => {
      transmittedBody = String(init?.body ?? "");
      return {
        ok: false,
        status: 400,
        statusText: "Bad Request",
        text: async () => '{"error":{"message":"captured-live-contract-rejection"}}',
      } as unknown as Response;
    }) as unknown as typeof fetch;

    const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 8192 });
    let thrown: unknown = null;
    try {
      await callModel({
        messages: [{ role: "user" as const, content: "capture this exact request" }],
        systemPrompt: "capture-test",
        tools: [],
        model: "owned-test-model",
        maxTokens: 8096,
      });
    } catch (err) {
      thrown = err;
    }

    try {
      expect(thrown).toBeInstanceOf(ModelHttpError);
      expect((thrown as Error).message).toContain("captured-live-contract-rejection");
      const capture = JSON.parse(await readFile(capturePath, "utf8")) as Record<string, unknown>;
      expect(capture["schema_version"]).toBe("ember-model-http-error-capture-v1");
      expect(capture["request_body_utf8"]).toBe(transmittedBody);
      expect(capture["response_status"]).toBe(400);
      expect(capture["response_body_utf8"]).toBe('{"error":{"message":"captured-live-contract-rejection"}}');
      expect(capture).not.toHaveProperty("request_headers");
    } finally {
      await rm(captureDir, { recursive: true, force: true });
    }
  });
  it("ModelHttpError.status reflects a 5xx just as faithfully as a 4xx", async () => {
    globalThis.fetch = mock(async () => {
      return { ok: false, status: 503, statusText: "Service Unavailable" } as unknown as Response;
    }) as unknown as typeof fetch;

    const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 8192 });

    let thrown: unknown = null;
    try {
      await callModel({
        messages: [{ role: "user" as const, content: "hello" }],
        systemPrompt: "test",
        tools: [],
        model: "test-model",
        maxTokens: 256,
      });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeInstanceOf(ModelHttpError);
    expect((thrown as ModelHttpError).status).toBe(503);
  });

  it("issue #197: a stream that ends (done=true) without ever seeing a finish_reason throws a retryable transport error, not a fabricated success", async () => {
    // Regression guard for the exact defect acceptance leg C exposed: a real
    // server killed mid-generation can make fetch() report a silent,
    // non-throwing EOF (measured directly against llama-server). Before this
    // check, that silently produced a fabricated "end_turn" ModelResponse
    // from whatever partial content had streamed -- a truncated answer
    // rendered as a normal, complete, successful turn, with no error and no
    // retry. This mock reader emits real partial content, THEN done:true,
    // with NO finish_reason chunk ever sent -- exactly that failure shape.
    const encoder = new TextEncoder();
    let sent = false;
    globalThis.fetch = mock(async () => {
      return {
        ok: true,
        body: {
          getReader: () => ({
            read: async () => {
              if (!sent) {
                sent = true;
                return {
                  done: false,
                  value: encoder.encode(
                    'data: {"choices":[{"finish_reason":null,"index":0,"delta":{"content":"partial"}}]}\n\n',
                  ),
                };
              }
              return { done: true, value: undefined }; // connection died -- no finish_reason ever arrived
            },
            releaseLock: () => {},
          }),
        },
      } as unknown as Response;
    }) as unknown as typeof fetch;

    const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 8192 });

    let thrown: unknown = null;
    try {
      await callModel({
        messages: [{ role: "user" as const, content: "hello" }],
        systemPrompt: "test",
        tools: [],
        model: "test-model",
        maxTokens: 256,
      });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).not.toBeNull();
    expect(thrown).toBeInstanceOf(Error);
    expect((thrown as { code?: string }).code).toBe("ECONNRESET");
  });

  it("issue #197: a stream that DOES see a genuine finish_reason completes normally, even with zero content", async () => {
    // Sibling guard: the check above must not become a false-positive trap
    // for a legitimately empty-but-complete response.
    globalThis.fetch = mock(async () => ({
      ok: true,
      body: { getReader: () => makeSingleChunkReader() },
    }) as unknown as Response) as unknown as typeof fetch;

    const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 8192 });

    const result = await callModel({
      messages: [{ role: "user" as const, content: "hello" }],
      systemPrompt: "test",
      tools: [],
      model: "test-model",
      maxTokens: 256,
    });

    expect(result.stop_reason).toBe("end_turn");
  });
});

describe("buildProductionCallModel — issue #267 external endpoint policy reaches the wire", () => {
  const origFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = origFetch;
    delete process.env["EMBER_SAMPLING_PARAMS"];
  });

  it("normalizes a terminal /v1 and transmits max_tokens plus configured sampling", async () => {
    let capturedUrl = "";
    let capturedBody: Record<string, unknown> = {};
    globalThis.fetch = mock(async (url, init) => {
      capturedUrl = String(url);
      capturedBody = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      return {
        ok: true,
        body: { getReader: () => makeSingleChunkReader() },
      } as unknown as Response;
    }) as unknown as typeof fetch;
    process.env["EMBER_SAMPLING_PARAMS"] = JSON.stringify({
      temperature: 0.55,
      top_p: 0.9,
      seed: 123,
    });

    const callModel = buildProductionCallModel({
      serverUrl: "https://external.example/custom/v1/",
      nCtx: 8192,
    });
    await callModel({
      messages: [{ role: "user" as const, content: "hello" }],
      systemPrompt: "test",
      tools: [],
      model: "external-model",
      maxTokens: 777,
    });

    expect(capturedUrl).toBe("https://external.example/custom/v1/chat/completions");
    expect(capturedBody["max_tokens"]).toBe(777);
    expect(capturedBody["temperature"]).toBe(0.55);
    expect(capturedBody["top_p"]).toBe(0.9);
    expect(capturedBody["seed"]).toBe(123);
  });
});

// PR948 round-8 (P2): modelSupportsStructuredOutputs (model-config.ts) existed
// but was never actually consumed anywhere in the real request construction
// path -- buildProductionCallModel set `response_format` unconditionally the
// instant a caller passed `jsonSchema`, regardless of whether the served
// model's bound capability declaration actually granted structured outputs.
// These tests pin the fix: jsonSchema construction is now GATED on
// modelSupportsStructuredOutputs, fed by an explicit capability declaration +
// the served model's exact modelConfigSha256 (never inferred, never assumed
// true by default).
describe("buildProductionCallModel — structured-outputs capability gate (issue #51 P2)", () => {
  const origFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = origFetch;
  });

  it("throws and never calls fetch when jsonSchema is requested but no capability declaration is bound at all", async () => {
    let fetchCalled = false;
    globalThis.fetch = mock(async () => {
      fetchCalled = true;
      throw new Error("fetch should never be reached");
    }) as unknown as typeof fetch;

    const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 8192 });

    let thrown: unknown = null;
    try {
      await callModel({
        messages: [{ role: "user" as const, content: "hello" }],
        systemPrompt: "test",
        tools: [],
        model: "test-model",
        maxTokens: 256,
        jsonSchema: { type: "object" },
      });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).not.toBeNull();
    expect(String((thrown as Error).message)).toContain("structured outputs");
    expect(fetchCalled).toBe(false);
  });

  it("throws and never calls fetch when the bound declaration's modelConfigSha256 does not match the served model's exact hash", async () => {
    let fetchCalled = false;
    globalThis.fetch = mock(async () => {
      fetchCalled = true;
      throw new Error("fetch should never be reached");
    }) as unknown as typeof fetch;

    const callModel = buildProductionCallModel({
      serverUrl: "http://localhost:1",
      nCtx: 8192,
      modelCapabilities: { modelConfigSha256: "a".repeat(64), structuredOutputs: true },
      servedModelConfigSha256: "b".repeat(64),
    });

    let thrown: unknown = null;
    try {
      await callModel({
        messages: [{ role: "user" as const, content: "hello" }],
        systemPrompt: "test",
        tools: [],
        model: "test-model",
        maxTokens: 256,
        jsonSchema: { type: "object" },
      });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).not.toBeNull();
    expect(fetchCalled).toBe(false);
  });

  it("sends response_format only when the declaration's modelConfigSha256 matches the served model's exact hash", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    globalThis.fetch = mock(async (_url: string, init?: RequestInit) => {
      capturedBody = JSON.parse(String(init?.body));
      return {
        ok: true,
        body: { getReader: () => makeSingleChunkReader() },
      } as unknown as Response;
    }) as unknown as typeof fetch;

    const sha = "c".repeat(64);
    const callModel = buildProductionCallModel({
      serverUrl: "http://localhost:1",
      nCtx: 8192,
      modelCapabilities: { modelConfigSha256: sha, structuredOutputs: true },
      servedModelConfigSha256: sha,
    });

    await callModel({
      messages: [{ role: "user" as const, content: "hello" }],
      systemPrompt: "test",
      tools: [],
      model: "test-model",
      maxTokens: 256,
      jsonSchema: { type: "object" },
    });

    expect(capturedBody).not.toBeNull();
    expect((capturedBody as Record<string, unknown>)["response_format"]).toBeDefined();
  });

  it("never sends response_format when jsonSchema is absent, regardless of capability", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    globalThis.fetch = mock(async (_url: string, init?: RequestInit) => {
      capturedBody = JSON.parse(String(init?.body));
      return {
        ok: true,
        body: { getReader: () => makeSingleChunkReader() },
      } as unknown as Response;
    }) as unknown as typeof fetch;

    const sha = "d".repeat(64);
    const callModel = buildProductionCallModel({
      serverUrl: "http://localhost:1",
      nCtx: 8192,
      modelCapabilities: { modelConfigSha256: sha, structuredOutputs: true },
      servedModelConfigSha256: sha,
    });

    await callModel({
      messages: [{ role: "user" as const, content: "hello" }],
      systemPrompt: "test",
      tools: [],
      model: "test-model",
      maxTokens: 256,
    });

    expect(capturedBody).not.toBeNull();
    expect((capturedBody as Record<string, unknown>)["response_format"]).toBeUndefined();
  });
});

describe("getResolvedNCtx / getToolResultBudget — issue #157 n_ctx-derived budget", () => {
  it("getToolResultBudget derives a positive char budget even before init() has resolved n_ctx", () => {
    // init() may not have run in this test process; the getter must still return something
    // sane (its own documented 4096 fallback) rather than throwing or returning 0/NaN.
    const budget = getToolResultBudget();
    expect(budget.maxChars).toBeGreaterThan(0);
    expect(Number.isFinite(budget.maxChars)).toBe(true);
  });

  it("getResolvedNCtx returns null or a positive number, never NaN/undefined-as-number", () => {
    const n = getResolvedNCtx();
    expect(n === null || (typeof n === "number" && n > 0)).toBe(true);
  });

  // issue #197 Leg 1: query-engine.ts's conversation-total eviction reads
  // ToolUseContext.toolResultBudget.conversationMaxChars -- if this getter
  // ever stopped populating it (or returned 0/NaN), eviction would silently
  // no-op (evictOldestToolResults treats maxChars<=0 as "no budget, skip").
  it("getToolResultBudget derives a positive conversationMaxChars, strictly larger than a single-result maxChars", () => {
    const budget = getToolResultBudget();
    expect(budget.conversationMaxChars).toBeGreaterThan(0);
    expect(Number.isFinite(budget.conversationMaxChars)).toBe(true);
    // The whole-conversation ceiling must be larger than the per-result one --
    // otherwise a single result could never fit its own conversation.
    expect(budget.conversationMaxChars).toBeGreaterThan(budget.maxChars);
  });
});

describe("buildGuardedProductionCallModel — issue #239 circuit breaker on the real model client", () => {
  const origFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = origFetch;
  });

  it("wraps buildProductionCallModel: a 400 opens the circuit after exactly one fetch call", async () => {
    let fetchCalls = 0;
    globalThis.fetch = mock(async () => {
      fetchCalls += 1;
      return new Response(null, { status: 400, statusText: "Bad Request" });
    }) as unknown as typeof fetch;

    const states: Array<{ state: string }> = [];
    const guarded = buildGuardedProductionCallModel(
      { serverUrl: "http://localhost:1", nCtx: 4096 },
      (s) => states.push(s),
    );

    let thrown: unknown = null;
    try {
      await guarded.callModel({
        messages: [{ role: "user", content: "hi" }],
        systemPrompt: "test",
        tools: [],
        model: "test",
        maxTokens: 100,
      });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeInstanceOf(CircuitOpenError);
    expect(fetchCalls).toBe(1);
    expect(guarded.getCircuitState().state).toBe("open");
    expect(states.length).toBeGreaterThan(0);
    expect(states[states.length - 1]!.state).toBe("open");
  });

  it("getCircuitBreakerState() returns null before any guarded client has been wired", () => {
    // A fresh module (no init() call, no buildGuardedProductionCallModel wiring
    // into the module-level singleton in this test's isolated assertion) must
    // never throw -- absence of a circuit is reported as null, matching
    // getResolvedNCtx()'s pre-init contract above.
    const state = getCircuitBreakerState();
    expect(state === null || typeof state.state === "string").toBe(true);
  });
});

// ---------------------------------------------------------------------------
// issue #602: resolveInitServerUrl -- _runInit's GPU-free null signal must never
// collapse into the same fallback chain as "not provided" (undefined). Even after
// process-entry.ts's own precedence fix, this SECOND unguarded `?? env ?? default`
// chain (right here in _runInit) silently resurrected a "real" serverUrl from a
// stray EMBER_MODEL_URL or the hardcoded "http://localhost:8081" default whenever
// main() passed serverUrl: null -- defeating the `!serverUrl` offline-stub check
// a few lines below it and reaching a real (or fake) model server in GPU-free mode.
// ---------------------------------------------------------------------------

describe("session-init — resolveInitServerUrl: EMBER_GPU_FREE null signal must not collapse into env/default fallback (issue #602)", () => {
  it("returns null when opts.serverUrl is explicitly null and EMBER_MODEL_URL is unset (issue #602 regression -- the reachable case: no .bat launcher can produce an empty-string env var, only unset)", () => {
    expect(resolveInitServerUrl(null, undefined)).toBeNull();
  });

  it("returns null when opts.serverUrl is explicitly null, even if a stray EMBER_MODEL_URL is set in the environment", () => {
    expect(resolveInitServerUrl(null, "http://localhost:9999")).toBeNull();
  });

  it("falls back to EMBER_MODEL_URL when opts.serverUrl is undefined (not provided at all -- distinct from explicit null)", () => {
    expect(resolveInitServerUrl(undefined, "http://localhost:9999")).toBe("http://localhost:9999");
  });

  it("fails closed to offline when both opts.serverUrl and EMBER_MODEL_URL are unset", () => {
    expect(resolveInitServerUrl(undefined, undefined)).toBeNull();
  });

  it("an explicit opts.serverUrl string wins over EMBER_MODEL_URL", () => {
    expect(resolveInitServerUrl("http://localhost:1111", "http://localhost:9999")).toBe("http://localhost:1111");
  });
});
