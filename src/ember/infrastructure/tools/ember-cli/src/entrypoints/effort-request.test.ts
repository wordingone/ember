// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// entrypoints/effort-request.test.ts -- issue #2370: the thinking level must reach the
// body that is handed to fetch, on every main-loop request. Pins session-init's wiring of
// chat_template_kwargs and the max-effort output cap.

import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test";
import { buildProductionCallModel } from "./session-init.ts";
import { buildOpenAIRequest } from "../services/api-openai-adapter.ts";
import { EFFORT_LEVELS, _resetEffortLevelForTests, type EffortLevel } from "../services/effort-level.ts";

function makeSingleChunkReader() {
  const chunk = new TextEncoder().encode(
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

describe("buildOpenAIRequest -- chat_template_kwargs", () => {
  const messages = [{ role: "user" as const, content: "hi" }];

  it("carries chat_template_kwargs when given", () => {
    const req = buildOpenAIRequest({
      model: "m",
      messages,
      maxTokens: 100,
      chatTemplateKwargs: { enable_thinking: true, reasoning_effort: "low" },
    });
    expect(req["chat_template_kwargs"]).toEqual({ enable_thinking: true, reasoning_effort: "low" });
  });

  it("omits the field when not given", () => {
    const req = buildOpenAIRequest({ model: "m", messages, maxTokens: 100 });
    expect("chat_template_kwargs" in req).toBe(false);
  });
});

describe("buildProductionCallModel -- thinking level reaches the request body", () => {
  const origFetch = globalThis.fetch;
  let bodies: Record<string, unknown>[];

  beforeEach(() => {
    bodies = [];
    globalThis.fetch = mock(async (_url: unknown, init?: { body?: string }) => {
      bodies.push(JSON.parse(String(init?.body)));
      return { ok: true, body: { getReader: () => makeSingleChunkReader() } } as unknown as Response;
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = origFetch;
    _resetEffortLevelForTests();
  });

  async function sendAt(level: EffortLevel): Promise<Record<string, unknown>> {
    _resetEffortLevelForTests(level);
    const callModel = buildProductionCallModel({ serverUrl: "http://localhost:1", nCtx: 65536 });
    await callModel({
      messages: [{ role: "user" as const, content: "hello" }],
      systemPrompt: "test",
      tools: [],
      model: "test-model",
      maxTokens: 8192,
    });
    expect(bodies).toHaveLength(1);
    return bodies[0]!;
  }

  const expected: Record<EffortLevel, Record<string, unknown>> = {
    off: { enable_thinking: false },
    low: { enable_thinking: true, reasoning_effort: "low" },
    medium: { enable_thinking: true, reasoning_effort: "medium" },
    high: { enable_thinking: true, reasoning_effort: "xhigh" },
    max: { enable_thinking: true, reasoning_effort: "xhigh" },
  };

  for (const level of EFFORT_LEVELS) {
    it(`level ${level} sends ${JSON.stringify(expected[level])}`, async () => {
      const body = await sendAt(level);
      expect(body["chat_template_kwargs"]).toEqual(expected[level]);
    });
  }

  it("max raises max_tokens to at least 32768; the other levels leave the cap alone", async () => {
    const max = await sendAt("max");
    expect(max["max_tokens"] as number).toBeGreaterThanOrEqual(32768);
    bodies = [];
    const high = await sendAt("high");
    expect(high["max_tokens"] as number).toBeLessThan(32768);
  });
});
