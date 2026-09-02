// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-suggestion-boundary-real-scheduling-maxturns.test.ts — issue #50
// round-3 reviewer repair follow-up (team-lead review of PR952 round-3,
// e6f349f79a1b22c490629b86533b61931938170f): the -success and -error variants
// mount the REAL ReplScreen and drive it through the REAL QueryEngine loop to
// prove the completedTranscript-keyed dispatch (never a same-tick ref read)
// sees the exact transcript for the "success" and "error" ResultEvent
// subtypes. Neither exercises "max_turns": repl.ts's applyResultEvent (see
// repl.ts, the `event.subtype === "max_turns"` branch) replaces the pending
// assistant placeholder with a brand-new `{ type: "error" }` entry -- an
// entirely different id from the placeholder's, exactly like the real error
// path -- so an id-keyed (rather than completedTranscript-state-keyed)
// detection scheme would miss this subtype too, and nothing in the round-3
// suite proved it.
//
// This file drives the loop to a REAL max_turns termination: query-engine.ts
// defaults maxTurns to 100 and increments completeModelTurns on every
// non-streaming model response regardless of stop_reason (query-engine.ts
// ~line 622), so a callModel mock that always answers with `stop_reason:
// "tool_use"` against a tool name no BUILTIN_TOOLS entry matches drives the
// loop through all 100 turns purely in-process (unknown-tool lookups short-
// circuit before any real tool executes -- see query-engine.ts's
// `tools.find(...)` miss path) and lets the real loop's own turn-count
// exhaustion synthesize the "max_turns" ResultEvent, never a mocked one.
//
// Verified: RED against 8edbfa63 (round-2, stale-ref read) if that revision
// is checked out -- messagesRef.current at the same tick would still show
// the open pending placeholder's stop_reason (undefined), not "error".
// GREEN against e6f349f7 (round-3 repair) and this follow-up commit.

import { describe, test, expect, mock, afterEach } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { ReplScreen } from "../screens/repl.ts";

function nextMacrotask(ms = 0): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForCalls(
  calls: unknown[],
  minCount: number,
  maxWaitMs = 8000,
): Promise<void> {
  const start = Date.now();
  while (calls.length < minCount && Date.now() - start < maxWaitMs) {
    await nextMacrotask(10);
  }
}

describe("issue #50 round-3 — suggestion dispatch through the REAL ReplScreen + real QueryEngine + real reconciler (max_turns path)", () => {
  afterEach(() => {
    mock.restore();
  });

  test("max_turns turn (100 tool_use responses against an unknown tool, never a terminating assistant event): the dispatch sees the synthesized max_turns closing message as THIS turn's outcome, never the empty pending placeholder", async () => {
    const suggestionCalls: Array<{ messages: unknown[] }> = [];
    let callCount = 0;

    mock.module("../services/prompt-suggestion.ts", () => ({
      executePromptSuggestion: async (ctx: { messages: unknown[] }) => {
        suggestionCalls.push({ messages: ctx.messages });
      },
      makeSuggestionExecutor: () => async () => ({}),
    }));

    mock.module("../entrypoints/session-init.ts", () => ({
      getLoopDeps: () => ({
        callModel: async () => {
          callCount += 1;
          // Never a real BUILTIN_TOOLS name -- query-engine.ts's `tools.find`
          // misses, so this drives the loop's turn counter without ever
          // invoking a real tool executor.
          return {
            content: [
              {
                type: "tool_use",
                id: `call-${callCount}`,
                name: "__repl_maxturns_test_never_a_real_tool__",
                input: {},
              },
            ],
            stop_reason: "tool_use",
            usage: { input_tokens: 1, output_tokens: 1 },
          };
        },
        microcompact: async (m: unknown[]) => m,
        autocompact: async () => {},
        generateUuid: () => crypto.randomUUID(),
        sleep: async () => {},
      }),
      getToolResultBudget: () => ({ maxChars: 100_000, conversationMaxChars: 500_000 }),
      getCircuitBreakerState: () => null,
    }));

    const stream = { write() {} };
    const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
    const element = React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns: 100, rows: 30 } },
      React.createElement(ReplScreen, {
        config,
        cwd: process.cwd(),
        env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
        onExit: () => {},
      }),
    );
    const handle = mountInk(element, { stream, stdout: { columns: 100, rows: 30 } });

    try {
      for (const ch of "trigger the max turns path") {
        _deliverKeyEvent(ch, {});
      }
      // See the -success variant's header/inline comment: typed-character
      // commits are genuinely deferred by this reconciler's Scheduler past
      // the synchronous continuation that issued them.
      await nextMacrotask(150);
      _deliverKeyEvent("return", {});

      await waitForCalls(suggestionCalls, 1);

      expect(suggestionCalls.length).toBe(1);
      // The loop actually ran to real turn exhaustion, not a short-circuited
      // mock result -- proves this is the real query-engine.ts max_turns
      // branch, not a synthesized event.
      expect(callCount).toBe(100);
      const adapted = suggestionCalls[0]!.messages as Array<Record<string, unknown>>;
      const last = adapted[adapted.length - 1] as Record<string, unknown>;
      // applyResultEvent's max_turns branch (repl.ts) replaces the pending
      // placeholder with a brand-new `{ type: "error" }` entry, identical in
      // shape to the real-error branch; adaptSessionMessagesForSuggestion
      // maps that to role assistant / stop_reason "error" (repl.ts's own
      // contract, unchanged by this repair).
      expect(last["role"]).toBe("assistant");
      expect(last["stop_reason"]).toBe("error");
    } finally {
      handle.unmount();
    }
  }, 15000);
});
