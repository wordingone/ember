// entrypoints/session-init.test.ts — issue #157 Leg 2: buildProductionCallModel must
// proactively refuse an oversized request BEFORE it ever reaches the network, rather than
// sending it and risking the server silently wedging (receipt: receipts/operator-sessions/
// session-20260705T234943Z.jsonl -- a 46,634-byte tool result vs an 8192-token n_ctx slot,
// GPU idle, spinner alive >4min with no error ever surfacing). checkPrefillOverflow/fetchNCtx
// (FM_91, AC3/AC4) already existed for exactly this but were never wired to the production
// call path -- these tests pin the wiring, not the guard's own math (that's api-openai-
// adapter.test.ts's job).

import { describe, it, expect, mock, afterEach } from "bun:test";
import { buildProductionCallModel, getResolvedNCtx, getToolResultBudget } from "./session-init.ts";
import { ModelHttpError } from "../services/api-openai-adapter.ts";

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
        messages: [{ role: "user" as const, content: "Read GOAL.md and summarize its first section" }],
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
