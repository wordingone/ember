// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-result-event.test.ts — issue #49: a transport-level generate failure must
// surface as ONE styled error message in the transcript, never a dangling empty assistant
// bubble and never a second "new" message alongside it.
//
// applyResultEvent is the extracted, pure decision function the REPL's submit loop calls when
// its for-await over QueryEvents ends on a "result" event. Non-error subtypes are untouched
// (success/abort already have their content, or intentionally have none) -- this function's only
// job is the error path: drop the still-empty placeholder bubble and append exactly one styled
// error entry, so the transcript never carries a silent, contentless "assistant" turn.

import { describe, it, expect } from "bun:test";
import { applyResultEvent } from "./repl.ts";
import type { SessionMessage } from "../components/app-shell.ts";
import type { ResultEvent } from "../core/query-engine.ts";
import type { ModelResponse } from "../query/query-loop-support.ts";

describe("applyResultEvent — issue #49 error-surface regression", () => {
  it("drops the empty placeholder and appends exactly one styled error message on subtype 'error'", () => {
    const messages: SessionMessage[] = [
      { id: "u1", type: "user", content: "hello" },
      { id: "a1", type: "assistant", content: "" }, // pending placeholder, never got real content
    ];
    const event: ResultEvent = {
      type: "result",
      subtype: "error",
      durationMs: 12,
      errorMessage: "fetch failed: connect ECONNREFUSED 127.0.0.1:1",
    };

    const next = applyResultEvent(event, messages, "a1");

    // Renders the styled error and NOTHING else new: exactly the prior user turn plus one
    // new error entry -- no leftover empty assistant bubble, no second placeholder.
    expect(next).toHaveLength(2);
    expect(next[0]!.id).toBe("u1");
    expect(next[1]!.type).toBe("error");
    expect(String(next[1]!["content"])).toContain("ECONNREFUSED");
    expect(next.some((m) => m.type === "assistant")).toBe(false);
  });

  it("falls back to a generic message when the event carries no errorMessage text", () => {
    const messages: SessionMessage[] = [{ id: "a1", type: "assistant", content: "" }];
    const event: ResultEvent = { type: "result", subtype: "error", durationMs: 1, errorMessage: "" };
    const next = applyResultEvent(event, messages, "a1");
    expect(next).toHaveLength(1);
    expect(next[0]!.type).toBe("error");
    expect(String(next[0]!["content"]).length).toBeGreaterThan(0);
  });

  // issue #52: "success" is no longer a pure no-op. Content already arrived via the preceding
  // "assistant" event (untouched here), but stop_reason/usage from the engine's ModelResponse
  // had nowhere to land -- guards 3/4 in prompt-suggestion.ts read exactly those two fields off
  // the last assistant message and, until this fix, always saw them undefined. This is the
  // #49 applyResultEvent seam extended to thread that metadata through, same shape as the
  // errorMessage threading the "error" subtype already does below.
  it("threads stop_reason/usage from finalMessage onto the matching assistant message on subtype 'success'", () => {
    const messages: SessionMessage[] = [
      { id: "u1", type: "user", content: "hello" },
      { id: "a1", type: "assistant", content: "a real reply" },
    ];
    const finalMessage: ModelResponse = {
      role: "assistant",
      content: [],
      stop_reason: "end_turn",
      usage: { input_tokens: 120, output_tokens: 40 },
    };
    const event: ResultEvent = {
      type: "result",
      subtype: "success",
      durationMs: 5,
      usage: finalMessage.usage,
      finalMessage,
    };
    const next = applyResultEvent(event, messages, "a1");
    const assistant = next.find((m) => m.id === "a1")!;
    // Content is untouched -- this seam enriches with metadata, it never rewrites what the
    // streaming "assistant" event already put there.
    expect(assistant["content"]).toBe("a real reply");
    expect(assistant["stop_reason"]).toBe("end_turn");
    expect(assistant["usage"]).toEqual({ input_tokens: 120, output_tokens: 40 });
    // The other transcript entries are untouched.
    expect(next.find((m) => m.id === "u1")).toEqual(messages[0]);
  });

  it("threads stop_reason/usage onto the matching assistant message on subtype 'error_max_tokens' too", () => {
    const messages: SessionMessage[] = [{ id: "a1", type: "assistant", content: "ran out of room" }];
    const finalMessage: ModelResponse = {
      role: "assistant",
      content: [],
      stop_reason: "max_tokens",
      usage: { input_tokens: 500, output_tokens: 4096 },
    };
    const event: ResultEvent = {
      type: "result",
      subtype: "error_max_tokens",
      durationMs: 5,
      finalMessage,
    };
    const next = applyResultEvent(event, messages, "a1");
    const assistant = next.find((m) => m.id === "a1")!;
    expect(assistant["stop_reason"]).toBe("max_tokens");
    expect(assistant["usage"]).toEqual({ input_tokens: 500, output_tokens: 4096 });
  });

  it("threading a 'success' event never touches a message with a different id (only the pending turn is enriched)", () => {
    const messages: SessionMessage[] = [
      { id: "a0", type: "assistant", content: "earlier reply", stop_reason: "end_turn" },
      { id: "a1", type: "assistant", content: "current reply" },
    ];
    const finalMessage: ModelResponse = {
      role: "assistant",
      content: [],
      stop_reason: "end_turn",
      usage: { input_tokens: 10, output_tokens: 5 },
    };
    const event: ResultEvent = {
      type: "result",
      subtype: "success",
      durationMs: 5,
      finalMessage,
    };
    const next = applyResultEvent(event, messages, "a1");
    const earlier = next.find((m) => m.id === "a0")!;
    expect(earlier["usage"]).toBeUndefined(); // untouched -- was never the pending turn
    const current = next.find((m) => m.id === "a1")!;
    expect(current["usage"]).toEqual({ input_tokens: 10, output_tokens: 5 });
  });

  it("leaves messages untouched on subtype 'abort' (no error surface for a user-initiated cancel)", () => {
    const messages: SessionMessage[] = [{ id: "a1", type: "assistant", content: "" }];
    const event: ResultEvent = { type: "result", subtype: "abort", durationMs: 3 };
    const next = applyResultEvent(event, messages, "a1");
    expect(next).toBe(messages);
  });

  it("never introduces a duplicate welcome/homescreen entry -- only ever appends the one error message", () => {
    const messages: SessionMessage[] = [
      { id: "w1", type: "welcome", content: "" },
      { id: "a1", type: "assistant", content: "" },
    ];
    const event: ResultEvent = {
      type: "result",
      subtype: "error",
      durationMs: 1,
      errorMessage: "connect ECONNREFUSED",
    };
    const next = applyResultEvent(event, messages, "a1");
    const welcomeCount = next.filter((m) => m.type === "welcome").length;
    expect(welcomeCount).toBe(1);
    expect(next).toHaveLength(2);
  });
});
