// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/api-openai-adapter.test.ts — token-usage plumbing fix (the D2 "token counts > 0"
// receipt requirement, autonomy-relinquishment ladder R0). No test file existed for this module
// before this change; scope here is the usage-capture addition plus a routing-safety check that
// the new code (inserted ahead of the existing delta early-return) does not disturb the existing
// content/tool-call routing.

import { describe, it, expect } from "bun:test";
import {
  buildOpenAIRequest,
  createSseParserContext,
  normalizeModelServerUrl,
  processSseLine,
} from "./api-openai-adapter.ts";

const USER_MESSAGE = [{ role: "user" as const, content: "hello" }];

function sseLine(obj: unknown): string {
  return `data: ${JSON.stringify(obj)}`;
}

describe("processSseLine — usage capture (D2 token-counts fix)", () => {
  it("captures usage from a final chunk carrying empty choices", async () => {
    const ctx = createSseParserContext();
    await processSseLine(
      sseLine({ choices: [], usage: { prompt_tokens: 42, completion_tokens: 17 } }),
      ctx,
    );
    expect(ctx.usage).toEqual({ inputTokens: 42, outputTokens: 17 });
  });

  it("leaves ctx.usage null when no usage chunk is ever seen", async () => {
    const ctx = createSseParserContext();
    await processSseLine(
      sseLine({ choices: [{ delta: { content: "hello" } }] }),
      ctx,
    );
    expect(ctx.usage).toBeNull();
  });

  it("ignores a malformed usage object (missing token fields), never throws, stays null", async () => {
    const ctx = createSseParserContext();
    await processSseLine(sseLine({ choices: [], usage: { prompt_tokens: "not-a-number" } }), ctx);
    expect(ctx.usage).toBeNull();
  });

  it("a usage chunk that ALSO carries content updates both usage and textBuffer", async () => {
    const ctx = createSseParserContext({ initialState: "text" });
    await processSseLine(
      sseLine({
        choices: [{ delta: { content: "done" } }],
        usage: { prompt_tokens: 5, completion_tokens: 3 },
      }),
      ctx,
    );
    expect(ctx.usage).toEqual({ inputTokens: 5, outputTokens: 3 });
    expect(ctx.textBuffer).toBe("done");
  });

  it("the [DONE] sentinel line never sets usage and never throws", async () => {
    const ctx = createSseParserContext();
    await processSseLine("data: [DONE]", ctx);
    expect(ctx.usage).toBeNull();
  });
});

describe("processSseLine — content/tool-call routing unaffected by the usage-capture insertion", () => {
  it("plain text content in 'pre' state still routes to textBuffer", async () => {
    const ctx = createSseParserContext({ initialState: "pre" });
    await processSseLine(sseLine({ choices: [{ delta: { content: "hi there" } }] }), ctx);
    expect(ctx.textBuffer).toBe("hi there");
    expect(ctx.state).toBe("text");
  });

  it("tool_calls deltas still accumulate into toolCallsByIndex", async () => {
    const ctx = createSseParserContext();
    await processSseLine(
      sseLine({
        choices: [{ delta: { tool_calls: [{ index: 0, id: "call_1", function: { name: "foo", arguments: "{\"a\":" } }] } }],
      }),
      ctx,
    );
    await processSseLine(
      sseLine({ choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: "1}" } }] } }] }),
      ctx,
    );
    const tc = ctx.toolCallsByIndex.get(0);
    expect(tc?.name).toBe("foo");
    expect(tc?.arguments).toBe('{"a":1}');
  });
});

describe("issue #267 external OpenAI-compatible request policy", () => {
  it("preserves validated per-model sampling fields in the transmitted request shape", () => {
    const req = buildOpenAIRequest({
      model: "external-model",
      messages: USER_MESSAGE,
      maxTokens: 321,
      samplingParams: {
        temperature: 0.63,
        top_p: 0.92,
        top_k: 24,
        seed: 88,
      },
    });
    expect(req.max_tokens).toBe(321);
    expect(req.temperature).toBe(0.63);
    expect(req.top_p).toBe(0.92);
    expect(req.top_k).toBe(24);
    expect(req.seed).toBe(88);
  });

  it("normalizes only a terminal /v1 segment and trailing slashes", () => {
    expect(normalizeModelServerUrl(" https://host.example/v1/ ")).toBe("https://host.example");
    expect(normalizeModelServerUrl("https://host.example/prefix/v1")).toBe("https://host.example/prefix");
    expect(normalizeModelServerUrl("https://host.example/prefix")).toBe("https://host.example/prefix");
    expect(normalizeModelServerUrl("https://host.example/api/v10")).toBe("https://host.example/api/v10");
  });

  it("rejects an empty model server URL", () => {
    expect(() => normalizeModelServerUrl(" /v1/ ")).toThrow();
  });
});
