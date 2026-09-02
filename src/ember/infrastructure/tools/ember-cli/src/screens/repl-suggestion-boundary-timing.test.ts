// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-suggestion-boundary-timing.test.ts — issue #50 reviewer
// sequencing defect: the submit loop scheduled applyResultEvent's new
// transcript into React state via setMessages, broke, then immediately
// adapted messagesRef.current for the suggestion dispatch -- but the ref
// only syncs from a LATER React effect (`useEffect(() => { messagesRef.current
// = messages; }, [messages])`), so reading it in the SAME tick as the result
// event can still observe the PRE-result transcript: missing this turn's
// final stop_reason/usage on success, or hiding an error/max_turns outcome
// behind the still-open pending placeholder as if the preceding assistant
// turn were the last completed one.
//
// The cure (repl.ts submitPrompt): capture the exact array applyResultEvent
// produces -- via setMessages's own `prev`, never the ref -- into one local
// `completedTranscript`, and adapt THAT SAME value for the suggestion
// dispatch. These tests model the two candidate call-site behaviors
// (stale-ref vs completedTranscript) against the real applyResultEvent and
// adaptSessionMessagesForSuggestion functions and assert only the cured
// behavior reflects the current turn's outcome.

import { describe, it, expect } from "bun:test";
import {
  adaptSessionMessagesForSuggestion,
  applyResultEvent,
} from "../../../../../../../tools/ember-cli/src/screens/repl.ts";
import type { SessionMessage } from "../components/app-shell.ts";
import type { ResultEvent } from "../core/query-engine.ts";

describe("suggestion-dispatch sequencing — issue #50 reviewer defect", () => {
  it("positive: success result arriving same tick -- completedTranscript carries the CURRENT turn's stop_reason/usage; the stale ref does not", () => {
    const pendingId = "a2";
    // messagesRef.current as it stands BEFORE this turn's result event lands
    // (this is what the ref would still read if sampled in the same tick --
    // the effect that syncs it fires on a LATER render).
    const staleRef: SessionMessage[] = [
      { id: "u1", type: "user", content: "first" },
      { id: "a1", type: "assistant", content: "first reply", stop_reason: "end_turn", usage: { input_tokens: 10, output_tokens: 5 } },
      { id: "u2", type: "user", content: "second" },
      { id: pendingId, type: "assistant", content: "second reply" }, // still no stop_reason/usage
    ];

    // React's own queued `prev` at the moment the result event's setMessages
    // updater runs -- identical content to staleRef here (nothing else wrote
    // to state in between), which is exactly why using it is safe: it is the
    // authoritative queued value, not a lagging side-channel snapshot.
    const prevAtResultTime = staleRef;

    const resultEvent: ResultEvent = {
      type: "result",
      subtype: "success",
      durationMs: 12,
      finalMessage: {
        role: "assistant",
        content: [{ type: "text", text: "second reply" }],
        stop_reason: "end_turn",
        usage: { input_tokens: 20, output_tokens: 8 },
      },
    };

    const completedTranscript = applyResultEvent(resultEvent, prevAtResultTime, pendingId);

    // CURED path: adapt the captured snapshot.
    const curedInput = adaptSessionMessagesForSuggestion(completedTranscript);
    const curedCurrentTurn = curedInput[curedInput.length - 1];
    expect(curedCurrentTurn).toMatchObject({
      role: "assistant",
      content: "second reply",
      stop_reason: "end_turn",
    });
    expect((curedCurrentTurn as any).usage).toEqual({ input_tokens: 20, output_tokens: 8 });

    // DEFECTIVE path (what the reviewer flagged): adapt the stale ref instead.
    const staleInput = adaptSessionMessagesForSuggestion(staleRef);
    const staleCurrentTurn = staleInput[staleInput.length - 1];
    // The stale read is missing exactly the metadata applyResultEvent attaches.
    expect(staleCurrentTurn!["stop_reason"]).toBeUndefined();
    expect((staleCurrentTurn as any).usage).toBeUndefined();

    // The two inputs must diverge -- proving the ref read was genuinely stale,
    // not an equivalent alternate path.
    expect(curedCurrentTurn).not.toEqual(staleCurrentTurn);
  });

  it("negative: error result -- completedTranscript reflects the error as the CURRENT turn's outcome; the stale ref still shows the empty pending placeholder", () => {
    const pendingId = "a1";
    const staleRef: SessionMessage[] = [
      { id: "u1", type: "user", content: "hello" },
      { id: pendingId, type: "assistant", content: "" }, // pre-result: still the empty placeholder
    ];
    const prevAtResultTime = staleRef;

    const resultEvent: ResultEvent = {
      type: "result",
      subtype: "error",
      durationMs: 8,
      errorMessage: "transport failed",
    } as ResultEvent;

    const completedTranscript = applyResultEvent(resultEvent, prevAtResultTime, pendingId);

    const curedInput = adaptSessionMessagesForSuggestion(completedTranscript);
    const curedLast = curedInput[curedInput.length - 1];
    // The error IS this turn's outcome -- mapped to role assistant with the
    // literal stop_reason "error" Guard 3 checks for.
    expect(curedLast).toMatchObject({ role: "assistant", stop_reason: "error" });

    const staleInput = adaptSessionMessagesForSuggestion(staleRef);
    const staleLast = staleInput[staleInput.length - 1];
    // Defective read: the pending placeholder (empty content, no stop_reason)
    // is what would have been sent -- the current turn's error never appears.
    expect(staleLast!["stop_reason"]).toBeUndefined();
    expect(staleLast).not.toMatchObject({ stop_reason: "error" });
  });

  it("negative: max_turns result -- completedTranscript reflects the max_turns outcome as the CURRENT turn, never as a completed prior assistant turn", () => {
    const pendingId = "a1";
    const staleRef: SessionMessage[] = [
      { id: "u1", type: "user", content: "hello" },
      // A genuinely completed PRIOR turn -- present so the defective read has
      // something that LOOKS like a valid last assistant turn to fall back on.
      { id: "a0", type: "assistant", content: "earlier answer", stop_reason: "end_turn", usage: { input_tokens: 5, output_tokens: 3 } },
      { id: "u2", type: "user", content: "go further" },
      { id: pendingId, type: "assistant", content: "" }, // this turn's still-open placeholder
    ];
    const prevAtResultTime = staleRef;

    const resultEvent: ResultEvent = {
      type: "result",
      subtype: "max_turns",
      durationMs: 30,
      finalMessage: {
        role: "assistant",
        content: [{ type: "text", text: "Ran out of turns before finishing." }],
      } as any,
    } as ResultEvent;

    const completedTranscript = applyResultEvent(resultEvent, prevAtResultTime, pendingId);

    const curedInput = adaptSessionMessagesForSuggestion(completedTranscript);
    const curedLast = curedInput[curedInput.length - 1];
    expect(curedLast).toMatchObject({ role: "assistant", stop_reason: "error" });
    expect(curedLast!.content).toContain("Ran out of turns");

    const staleInput = adaptSessionMessagesForSuggestion(staleRef);
    const staleLast = staleInput[staleInput.length - 1];
    // Defective read: the stale ref's last entry is still the empty pending
    // placeholder for THIS turn -- it does not surface the max_turns outcome
    // at all, let alone show it as belonging to a completed prior turn.
    expect(staleLast!["content"]).toBe("");
    expect(staleLast).not.toMatchObject({ stop_reason: "error" });
  });
});
