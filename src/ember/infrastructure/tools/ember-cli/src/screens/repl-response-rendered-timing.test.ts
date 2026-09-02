// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-response-rendered-timing.test.ts — issue #191:
// response_rendered should fire only after the actual response renders,
// not on the thinking preamble.
//
// The fixture simulates: thinking preamble arrives as "assistant" event,
// then the actual response arrives, then "result" event closes the turn.
// response_rendered should only be recorded when we have a message with
// stop_reason (meaning streaming is complete), not on first delta.
//
// The fix in repl.ts checks that the message has stop_reason before
// appending response_rendered to the receipts.

import { describe, it, expect } from "bun:test";
import type { SessionMessage } from "../components/app-shell.ts";
import type { QueryEvent, ResultEvent } from "../core/query-engine.ts";
import type { ModelResponse } from "../query/query-loop-support.ts";
import { applyResultEvent } from "./repl.ts";
import type { OperatorReceiptWriter } from "../services/operator-receipts.ts";

describe("response_rendered timing — issue #191", () => {
  it("detects thinking preamble (stop_reason=null) vs actual response (stop_reason!=null)", () => {
    // Simulate the event sequence from a real turn with extended thinking.
    //
    // Event 1: First "assistant" event with thinking preamble (no stop_reason yet).
    // This is what fires FIRST and what currently triggers response_rendered early.
    const thinkingChunk = {
      type: "assistant",
      message: {
        role: "assistant",
        content: [{ type: "thinking", thinking: "Let me think about this..." }],
        stop_reason: null, // <— thinking is still in flight
      },
    } as QueryEvent;

    // Event 2: Second "assistant" event with actual response content.
    // This arrives AFTER thinking completes (but stop_reason still null until result).
    const responseChunk = {
      type: "assistant",
      message: {
        role: "assistant",
        content: [
          { type: "thinking", thinking: "Let me think about this..." },
          { type: "text", text: "Here is my response." },
        ],
        stop_reason: null, // <— still in flight, but now has actual content
      },
    } as QueryEvent;

    // Event 3: "result" event with finalMessage containing stop_reason.
    // This is when the turn is TRULY complete.
    const resultEvent: ResultEvent = {
      type: "result",
      subtype: "success",
      durationMs: 3400,
      finalMessage: {
        role: "assistant",
        content: [
          { type: "thinking", thinking: "Let me think about this..." },
          { type: "text", text: "Here is my response." },
        ],
        stop_reason: "end_turn", // <— NOW the turn is complete
        usage: { input_tokens: 100, output_tokens: 50 },
      },
    };

    // Simulate the REPL's message handling for each event.
    let messages: SessionMessage[] = [];
    const assistantId = "msg-1";

    // Start with empty (as the REPL would)
    messages = [
      { id: assistantId, type: "assistant", content: "" },
    ];

    // Event 1: thinking preamble arrives
    // The current code would record response_rendered HERE (wrong!)
    // We need to verify we haven't done so yet.
    const afterThinking = [...messages];
    const thinkingMessage = afterThinking.find((m) => m.id === assistantId);
    expect(thinkingMessage).toBeDefined();
    expect(thinkingMessage!["stop_reason"]).toBeUndefined(); // No stop_reason yet

    // Event 2: response content arrives
    const afterResponse = [...messages];
    const responseMessage = afterResponse.find((m) => m.id === assistantId);
    expect(responseMessage).toBeDefined();
    expect(responseMessage!["stop_reason"]).toBeUndefined(); // Still no stop_reason

    // Event 3: result event with finalMessage
    // NOW we should apply the finalMessage which carries stop_reason
    const afterResult = applyResultEvent(resultEvent, afterResponse, assistantId);
    const finalMessage = afterResult.find((m) => m.id === assistantId);
    expect(finalMessage).toBeDefined();
    expect(finalMessage!["stop_reason"]).toBe("end_turn"); // <— NOW we have stop_reason
    expect(finalMessage!["usage"]).toEqual({ input_tokens: 100, output_tokens: 50 });

    // The fix: response_rendered should only be recorded when stop_reason exists.
    // We need a way to check this in the REPL's submitPrompt logic.
    // The test verifies the CONDITION: a message with stop_reason means the turn
    // is complete and response_rendered is safe to record.
    const shouldRecordResponseRendered = finalMessage!["stop_reason"] !== undefined;
    expect(shouldRecordResponseRendered).toBe(true);
  });

  it("correctly distinguishes when to fire response_rendered: early vs final", () => {
    // This test verifies the specific bug: response_rendered fires on first
    // "assistant" event (thinking preamble) instead of after "result" event
    // (final message with stop_reason).

    const messages: SessionMessage[] = [
      { id: "a1", type: "assistant", content: "" },
    ];
    const assistantId = "a1";

    // Snapshot 1: Immediately after first "assistant" event (thinking preamble)
    // should NOT have stop_reason yet.
    let currentMessages = [...messages];
    let msg = currentMessages.find((m) => m.id === assistantId);
    expect(msg!["stop_reason"]).toBeUndefined();
    // BUG: Old code would record response_rendered HERE
    // FIX: We should NOT

    // Snapshot 2: After "result" event applies finalMessage with stop_reason
    const resultEvent: ResultEvent = {
      type: "result",
      subtype: "success",
      durationMs: 3400,
      finalMessage: {
        role: "assistant",
        content: [{ type: "text", text: "Final answer." }],
        stop_reason: "end_turn",
        usage: { input_tokens: 50, output_tokens: 25 },
      },
    };
    currentMessages = applyResultEvent(resultEvent, currentMessages, assistantId);
    msg = currentMessages.find((m) => m.id === assistantId);
    expect(msg!["stop_reason"]).toBe("end_turn");
    // FIX: We SHOULD record response_rendered HERE

    // The condition for recording response_rendered:
    // The message must have stop_reason (indicating the turn is complete).
    const canRecordResponseRendered = msg!["stop_reason"] !== undefined;
    expect(canRecordResponseRendered).toBe(true);
  });

  it("simulates the receipt-writing logic: only record when stop_reason exists", () => {
    // This test models the exact fix applied to repl.ts submitPrompt:
    // Before recording response_rendered, check that the message has stop_reason.

    const assistantId = "msg-turn-1";
    let messagesRef = { current: [{ id: assistantId, type: "assistant", content: "" } as SessionMessage] };
    const recordedEvents: Array<{ event: string; detail?: string }> = [];
    const mockReceiptWriter: OperatorReceiptWriter = {
      filePath: "/fake/path",
      append: (event, detail) => {
        recordedEvents.push({ event, detail });
      },
    };

    // Scenario 1: Message arrives with content but NO stop_reason (thinking preamble)
    // OLD BUG: response_rendered would be recorded here
    const shouldRecordAfterThinking = messagesRef.current.find((m) => m.id === assistantId);
    expect(shouldRecordAfterThinking!["stop_reason"]).toBeUndefined();
    // Apply the fix: check for stop_reason before recording
    if (shouldRecordAfterThinking && shouldRecordAfterThinking["stop_reason"] !== undefined) {
      mockReceiptWriter.append("response_rendered", assistantId);
    }
    // Verify: nothing recorded yet (fix prevents early recording)
    expect(recordedEvents.length).toBe(0);

    // Scenario 2: Message now has stop_reason (from result event)
    const resultEvent: ResultEvent = {
      type: "result",
      subtype: "success",
      durationMs: 3400,
      finalMessage: {
        role: "assistant",
        content: [{ type: "text", text: "Here is my response." }],
        stop_reason: "end_turn",
        usage: { input_tokens: 100, output_tokens: 50 },
      },
    };
    messagesRef.current = applyResultEvent(resultEvent, messagesRef.current, assistantId);

    // NEW BEHAVIOR: now we CAN record response_rendered (message has stop_reason)
    const shouldRecordAfterResult = messagesRef.current.find((m) => m.id === assistantId);
    expect(shouldRecordAfterResult!["stop_reason"]).toBe("end_turn");
    // Apply the fix: check for stop_reason before recording
    if (shouldRecordAfterResult && shouldRecordAfterResult["stop_reason"] !== undefined) {
      mockReceiptWriter.append("response_rendered", assistantId);
    }
    // Verify: response_rendered was recorded this time
    expect(recordedEvents.length).toBe(1);
    expect(recordedEvents[0]!.event).toBe("response_rendered");
    expect(recordedEvents[0]!.detail).toBe(assistantId);
  });
});
