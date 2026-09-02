// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-suggestion-boundary-real-scheduling-success.test.ts — issue #50
// round-3 reviewer repair (reject on 8edbfa63d7366cbe29a31fc7868ae4a01ffe9e50):
// repl-suggestion-boundary-timing.test.ts calls applyResultEvent directly
// against hand-built SessionMessage[] arrays -- it proves the CURED VALUE is
// correct once you already have it, but never exercises the real seam the
// reviewer flagged: `completedTranscript` was assigned from inside
// setMessages's own updater callback and read back on the very next line,
// synchronously, with nothing in the language or in React's documented
// contract guaranteeing that updater has actually run by then.
//
// This file mounts the REAL ReplScreen (the actual component with the actual
// bug/fix, not a hand-rolled mirror) via the real ink reconciler, drives a
// full user turn through the REAL keyboard path (_deliverKeyEvent -- the same
// stdin-bridge entry point a live terminal uses) and the REAL QueryEngine
// loop (core/query-engine.ts, unmodified), with only the network-facing
// callModel swapped for a scripted stub via session-init's real
// dependency-injection seam (getLoopDeps) -- the exact same seam
// core/query-engine.test.ts and friends already use for control, not a
// bypass invented for this file. prompt-suggestion.ts's executePromptSuggestion
// is replaced with a recorder so the test can observe exactly what transcript
// repl.ts's real submitPrompt handed it, with no other change to repl.ts's
// own code path.
//
// The repair under test (screens/repl.ts): `completedTranscript` is now a
// dedicated useState slot written from inside the "result" event's
// setMessages updater and consumed by a SEPARATE useEffect keyed to that
// state -- so the suggestion dispatch only ever fires once React has
// actually committed the value, never on a same-tick read racing the
// updater's own invocation.
//
// Split into its own file (paired with the -error variant) rather than two
// tests in one describe block: each test mounts a full ReplScreen with its
// own live intervals (activity feed, spinner, heartbeat writer); running two
// such mounts back-to-back in one process/file -- even with unmount() called
// -- was observed to crash the Bun test runner itself (internal assertion
// failure, not a repl.ts or test-logic failure) via leftover timer/fiber
// interaction. One real-mount scenario per file/process sidesteps that
// entirely; each variant still independently exercises the real scheduling
// seam end to end.

import { describe, test, expect, mock, afterEach } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import type { ModelResponse } from "../query/query-loop-support.ts";
import { ReplScreen } from "../screens/repl.ts";

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

describe("issue #50 round-3 — suggestion dispatch through the REAL ReplScreen + real QueryEngine + real reconciler", () => {
  afterEach(() => {
    mock.restore();
  });

  test("success turn: the real submitPrompt hands the suggestion dispatch the CURRENT turn's stop_reason/usage, mounted+scheduled for real", async () => {
    const suggestionCalls: Array<{ messages: unknown[] }> = [];

    mock.module("../services/prompt-suggestion.ts", () => ({
      executePromptSuggestion: async (ctx: { messages: unknown[] }) => {
        suggestionCalls.push({ messages: ctx.messages });
      },
      makeSuggestionExecutor: () => async () => ({}),
    }));

    const fakeResponse: ModelResponse = {
      role: "assistant",
      content: [{ type: "text", text: "real-scheduling success reply" }],
      stop_reason: "end_turn",
      usage: { input_tokens: 11, output_tokens: 4 },
    };

    mock.module("../entrypoints/session-init.ts", () => ({
      getLoopDeps: () => ({
        callModel: async () => fakeResponse,
        microcompact: async (m: unknown[]) => m,
        autocompact: async () => {},
        generateUuid: () => crypto.randomUUID(),
        sleep: async () => {},
      }),
      getToolResultBudget: () => ({ maxChars: 100_000, conversationMaxChars: 500_000 }),
      // repl.ts's useCircuitBreakerBanner (static import, services/circuit-breaker-banner-poller.ts)
      // reads this directly -- null means "no guarded client wired", its own
      // documented no-client contract.
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
      for (const ch of "hello there") {
        _deliverKeyEvent(ch, {});
      }
      // Typed characters land via setState calls made outside any
      // React-recognized synchronous event (this test drives the stdin bridge
      // directly, not through a native event) -- this reconciler's Scheduler
      // genuinely defers flushing those to a later macrotask (confirmed by
      // instrumentation: reading the input state back inside the SAME
      // synchronous continuation right after calling insertText still shows
      // the pre-keystroke value). A real terminal session has this same gap
      // between keystroke and commit; give it real wall-clock time rather
      // than a single microtask tick.
      await nextMacrotask(150);
      _deliverKeyEvent("return", {});

      await waitForCalls(suggestionCalls, 1);

      expect(suggestionCalls.length).toBe(1);
      const adapted = suggestionCalls[0]!.messages as Array<Record<string, unknown>>;
      const last = adapted[adapted.length - 1] as Record<string, unknown>;
      // This is exactly the metadata applyResultEvent threads onto the
      // pending message -- present here only if the dispatch read the
      // transcript AFTER it actually included this turn's result, never the
      // still-open placeholder or a prior turn's leftovers.
      expect(last["role"]).toBe("assistant");
      expect(last["stop_reason"]).toBe("end_turn");
      expect(last["content"]).toBe("real-scheduling success reply");
      expect(last["usage"]).toEqual({ input_tokens: 11, output_tokens: 4 });
    } finally {
      handle.unmount();
    }
  }, 10000);
});
