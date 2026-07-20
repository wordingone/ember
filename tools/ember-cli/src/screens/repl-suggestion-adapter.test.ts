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
} from "./repl.ts";
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
});
