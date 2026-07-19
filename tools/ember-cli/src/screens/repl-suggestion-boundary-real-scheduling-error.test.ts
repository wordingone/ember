// screens/repl-suggestion-boundary-real-scheduling-error.test.ts — issue #50
// round-3 reviewer repair (reject on 8edbfa63d7366cbe29a31fc7868ae4a01ffe9e50).
// Paired with the -success variant (see that file's header for the full
// rationale/seam description and why this is a separate file/process rather
// than a second test in the same describe block). This variant proves the
// repaired dispatch surfaces an ERROR result correctly through the real
// ReplScreen + real QueryEngine + real reconciler: applyResultEvent REPLACES
// the pending assistant-placeholder id with a brand-new error-message id for
// this subtype, so any id-keyed detection scheme would miss it -- this test
// guards against exactly that regression class, not just the success path.

import { describe, test, expect, mock, afterEach } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { ReplScreen } from "./repl.ts";

function nextMacrotask(ms = 0): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForCalls(
  calls: unknown[],
  minCount: number,
  maxWaitMs = 4000,
): Promise<void> {
  const start = Date.now();
  while (calls.length < minCount && Date.now() - start < maxWaitMs) {
    await nextMacrotask(10);
  }
}

describe("issue #50 round-3 — suggestion dispatch through the REAL ReplScreen + real QueryEngine + real reconciler (error path)", () => {
  afterEach(() => {
    mock.restore();
  });

  test("error turn (non-retryable HTTP 400, no assistant event ever precedes it): the dispatch sees the error as THIS turn's outcome, never the empty pending placeholder", async () => {
    const suggestionCalls: Array<{ messages: unknown[] }> = [];

    mock.module("../services/prompt-suggestion.ts", () => ({
      executePromptSuggestion: async (ctx: { messages: unknown[] }) => {
        suggestionCalls.push({ messages: ctx.messages });
      },
      makeSuggestionExecutor: () => async () => ({}),
    }));

    mock.module("../entrypoints/session-init.ts", () => ({
      getLoopDeps: () => ({
        callModel: async () => {
          const { ModelHttpError } = await import("../services/api-openai-adapter.ts");
          throw new ModelHttpError(400, "Bad Request");
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
      for (const ch of "trigger the error path") {
        _deliverKeyEvent(ch, {});
      }
      // See the -success variant's header/inline comment: typed-character
      // commits are genuinely deferred by this reconciler's Scheduler past
      // the synchronous continuation that issued them.
      await nextMacrotask(150);
      _deliverKeyEvent("return", {});

      await waitForCalls(suggestionCalls, 1);

      expect(suggestionCalls.length).toBe(1);
      const adapted = suggestionCalls[0]!.messages as Array<Record<string, unknown>>;
      const last = adapted[adapted.length - 1] as Record<string, unknown>;
      // adaptSessionMessagesForSuggestion maps an error-type message to role
      // assistant / stop_reason "error" (repl.ts's own contract, unchanged
      // by this repair) -- the defective (pre-#50) read would instead have
      // shown the still-open, contentless pending placeholder here.
      expect(last["role"]).toBe("assistant");
      expect(last["stop_reason"]).toBe("error");
    } finally {
      handle.unmount();
    }
  }, 10000);
});
