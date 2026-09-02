// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-suggestion-adapter.test.ts — issue #50: the shape mismatch between the
// transcript's SessionMessage[] (`{id, type, ...}` -- app-shell.ts) and prompt-suggestion's
// EmberMessage[] guard input (`role`/`stop_reason`/`usage`) meant Guard 2
// (`messages.filter(m => m.role === "assistant")`) always saw zero matches: the call site's
// `messages as any` cast papered over messages that never carried a `role` field, so the
// feature could never generate a suggestion in production.
//
// These tests feed REAL production-shaped SessionMessage objects -- the exact fields
// applyResultEvent (screens/repl.ts) attaches at the pending-message seam -- through the
// adapter and, for the reachability test, through the real guard chain. No `.role` is ever
// hand-added to the input; only the adapter may introduce it.

import { describe, it, expect } from "bun:test";
import {
  adaptSessionMessagesForSuggestion,
  applyResultEvent,
} from "../screens/repl.ts";
import type { SessionMessage } from "../components/app-shell.ts";
import { tryGenerateSuggestion } from "../services/prompt-suggestion.ts";
import type { ForkedAgentExecutor } from "../services/prompt-suggestion.ts";
import type { AppState } from "../state/app-state.ts";

describe("adaptSessionMessagesForSuggestion — issue #50 boundary adapter", () => {
  it("maps a real applyResultEvent-produced assistant SessionMessage to the guard input shape", () => {
    // Build the pending message exactly as the submit loop does, then thread
    // stop_reason/usage through applyResultEvent's success path -- no hand-added .role.
    const pending: SessionMessage = { id: "a1", type: "assistant", content: "sure thing" };
    const messages: SessionMessage[] = [
      { id: "u1", type: "user", content: "hello" },
      pending,
    ];
    const next = applyResultEvent(
      {
        type: "result",
        subtype: "success",
        durationMs: 5,
        finalMessage: {
          role: "assistant",
          content: [{ type: "text", text: "sure thing" }],
          stop_reason: "end_turn",
          usage: { input_tokens: 10, output_tokens: 5 },
        } as any,
      } as any,
      messages,
      "a1",
    );

    const adapted = adaptSessionMessagesForSuggestion(next);

    expect(adapted).toHaveLength(2);
    expect(adapted[0]).toMatchObject({ role: "user", content: "hello" });
    expect(adapted[1]).toMatchObject({
      role: "assistant",
      content: "sure thing",
      stop_reason: "end_turn",
    });
    expect((adapted[1] as any).usage).toEqual({ input_tokens: 10, output_tokens: 5 });
  });

  it("guard-2 reachability: adapted assistant messages actually reach the forked-agent executor", async () => {
    // Two full turns as the transcript would really hold them post applyResultEvent.
    const messages: SessionMessage[] = [
      { id: "u1", type: "user", content: "first" },
      {
        id: "a1",
        type: "assistant",
        content: "first reply",
        stop_reason: "end_turn",
        usage: { input_tokens: 100, output_tokens: 20 },
      },
      { id: "u2", type: "user", content: "second" },
      {
        id: "a2",
        type: "assistant",
        content: "second reply",
        stop_reason: "end_turn",
        usage: { input_tokens: 100, output_tokens: 20 },
      },
    ];
    const adapted = adaptSessionMessagesForSuggestion(messages);

    let executorInvoked = false;
    const spyExecutor: ForkedAgentExecutor = async () => {
      executorInvoked = true;
      return [{ role: "assistant", content: "predicted next input" }];
    };

    const getAppState = () => ({}) as AppState;
    const result = await tryGenerateSuggestion(
      new AbortController(),
      adapted,
      getAppState,
      {},
      undefined,
      spyExecutor,
    );

    // If guards 2/3/4 didn't see the assistant turns, the executor is never called and
    // tryGenerateSuggestion returns null on "too_few_turns" before reaching generation.
    expect(executorInvoked).toBe(true);
    expect(result).not.toBeNull();
  });

  it("named negative: a type:'error' entry maps to role assistant with stop_reason 'error' (Guard 3 suppresses)", () => {
    const messages: SessionMessage[] = [
      { id: "u1", type: "user", content: "hello" },
      { id: "e1", type: "error", content: "An error occurred while processing your request." },
    ];
    const adapted = adaptSessionMessagesForSuggestion(messages);

    expect(adapted).toHaveLength(2);
    expect(adapted[1]).toMatchObject({ role: "assistant", stop_reason: "error" });
  });

  it("named negative: malformed/non-conversational entries are dropped, not crashed", () => {
    const messages: SessionMessage[] = [
      { id: "w1", type: "welcome", content: "banner text" },
      { id: "c1", type: "compaction", isComplete: true, elapsedSecs: 3 } as unknown as SessionMessage,
      { id: "tr1", type: "tool_result", content: "output", tool_use_id: "t1" },
      // @ts-expect-error -- deliberately malformed: type missing
      { id: "bad1", content: "no type field" },
      null as unknown as SessionMessage,
      { id: "u1", type: "user", content: "actual user turn" },
    ];

    expect(() => adaptSessionMessagesForSuggestion(messages)).not.toThrow();
    const adapted = adaptSessionMessagesForSuggestion(messages);
    expect(adapted).toHaveLength(1);
    expect(adapted[0]).toMatchObject({ role: "user", content: "actual user turn" });
  });

  // issue #52 reviewer spec: the two negative tests above stop at the adapter's output
  // shape. Neither drives the adapted array through tryGenerateSuggestion, so neither
  // proves the guard the shape is supposed to trip actually fires on production-shaped
  // input. These two close that gap: real applyResultEvent output (the same machinery
  // repl-result-event.test.ts exercises), through the real adapter, through the real
  // guard chain -- no hand-built EmberMessage or usage object anywhere in the chain.

  it("guard-3 end-to-end: a real applyResultEvent error turn suppresses tryGenerateSuggestion (no manually constructed EmberMessage)", async () => {
    // Turn 1: completes successfully. Content arrives via the streaming "assistant"
    // event (already on the SessionMessage, per the repl-result-event.test.ts pattern);
    // applyResultEvent's success path only threads stop_reason/usage onto it.
    const afterTurn1 = applyResultEvent(
      {
        type: "result",
        subtype: "success",
        durationMs: 5,
        finalMessage: {
          role: "assistant",
          content: [],
          stop_reason: "end_turn",
          usage: { input_tokens: 50, output_tokens: 20 },
        },
      } as any,
      [
        { id: "u1", type: "user", content: "first question" },
        { id: "a1", type: "assistant", content: "first reply" },
      ],
      "a1",
    );

    // Turn 2: the submit loop appends a user entry and an empty pending placeholder,
    // then the engine's for-await ends on a transport-level "result" event of
    // subtype "error" -- applyResultEvent drops the placeholder and appends the one
    // styled error entry (the exact #49 path repl-result-event.test.ts covers).
    const withPendingTurn2: SessionMessage[] = [
      ...afterTurn1,
      { id: "u2", type: "user", content: "second question" },
      { id: "a2", type: "assistant", content: "" },
    ];
    const afterTurn2 = applyResultEvent(
      {
        type: "result",
        subtype: "error",
        durationMs: 12,
        errorMessage: "fetch failed: connect ECONNREFUSED 127.0.0.1:1",
      },
      withPendingTurn2,
      "a2",
    );

    const adapted = adaptSessionMessagesForSuggestion(afterTurn2);
    // Sanity: the adapter really produced 2 assistant-role entries, the second
    // carrying stop_reason "error" -- otherwise this test would pass for the
    // wrong reason (guard 2's too-few-turns, not guard 3).
    const assistantEntries = adapted.filter((m) => m.role === "assistant");
    expect(assistantEntries).toHaveLength(2);
    expect(assistantEntries[1]).toMatchObject({ stop_reason: "error" });

    let executorInvoked = false;
    const spyExecutor: ForkedAgentExecutor = async () => {
      executorInvoked = true;
      return [{ role: "assistant", content: "predicted next input" }];
    };

    const result = await tryGenerateSuggestion(
      new AbortController(),
      adapted,
      () => ({}) as AppState,
      {},
      undefined,
      spyExecutor,
    );

    // Guard 3 must suppress before generation is ever attempted.
    expect(result).toBeNull();
    expect(executorInvoked).toBe(false);
  });

  it("guard-4 end-to-end: real applyResultEvent-threaded usage over the cache budget suppresses tryGenerateSuggestion (no hand-built usage object)", async () => {
    // Turn 1: completes successfully, well within the cache budget.
    const afterTurn1 = applyResultEvent(
      {
        type: "result",
        subtype: "success",
        durationMs: 5,
        finalMessage: {
          role: "assistant",
          content: [],
          stop_reason: "end_turn",
          usage: { input_tokens: 100, output_tokens: 20 },
        },
      } as any,
      [
        { id: "u1", type: "user", content: "first question" },
        { id: "a1", type: "assistant", content: "first reply" },
      ],
      "a1",
    );

    // Turn 2: also completes successfully, but the engine's finalMessage.usage
    // for this turn sums past MAX_PARENT_UNCACHED_TOKENS (10_000) -- the exact
    // field getParentCacheSuppressReason reads off the last assistant message.
    const withPendingTurn2: SessionMessage[] = [
      ...afterTurn1,
      { id: "u2", type: "user", content: "second question" },
      { id: "a2", type: "assistant", content: "second reply" },
    ];
    const afterTurn2 = applyResultEvent(
      {
        type: "result",
        subtype: "success",
        durationMs: 5,
        finalMessage: {
          role: "assistant",
          content: [],
          stop_reason: "end_turn",
          usage: {
            input_tokens: 9000,
            cache_creation_input_tokens: 2000,
            output_tokens: 500,
          }, // sum = 11 500 > 10 000
        },
      } as any,
      withPendingTurn2,
      "a2",
    );

    const adapted = adaptSessionMessagesForSuggestion(afterTurn2);
    const assistantEntries = adapted.filter((m) => m.role === "assistant");
    // Sanity: the real usage landed on the adapted last-assistant entry unmodified --
    // otherwise this would pass on guard 2 or 3, not guard 4.
    expect(assistantEntries).toHaveLength(2);
    expect(assistantEntries[1]).toMatchObject({ stop_reason: "end_turn" });
    expect((assistantEntries[1] as any).usage).toEqual({
      input_tokens: 9000,
      cache_creation_input_tokens: 2000,
      output_tokens: 500,
    });

    let executorInvoked = false;
    const spyExecutor: ForkedAgentExecutor = async () => {
      executorInvoked = true;
      return [{ role: "assistant", content: "predicted next input" }];
    };

    const result = await tryGenerateSuggestion(
      new AbortController(),
      adapted,
      () => ({}) as AppState,
      {},
      undefined,
      spyExecutor,
    );

    // Guard 4 must suppress before generation is ever attempted.
    expect(result).toBeNull();
    expect(executorInvoked).toBe(false);
  });
});
