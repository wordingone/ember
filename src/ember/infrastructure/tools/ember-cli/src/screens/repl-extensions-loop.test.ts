// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-extensions-loop.test.ts — issue #2376 through the REAL ReplScreen, QueryEngine and
// keyboard path (only callModel is scripted): `/loop 5s <prompt>` runs the prompt now, runs it
// again one interval later while the TUI is idle (real wall-clock ticker), and Esc stops it.

import { describe, test, expect, mock, afterEach } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import type { ModelResponse } from "../query/query-loop-support.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { _resetSchedulerForTests, hasActiveLoops } from "../extensions/scheduler.ts";
import { ReplScreen } from "../screens/repl.ts";

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

async function until(pred: () => boolean, maxMs: number): Promise<void> {
  const start = Date.now();
  while (!pred() && Date.now() - start < maxMs) await wait(25);
}

function renderedText(raw: string, columns: number, rows: number): string {
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join("")).join("\n");
}

describe("issue #2376 — /loop through the real REPL", () => {
  afterEach(() => {
    mock.restore();
    _resetSchedulerForTests();
    resetCommandRegistryForTests();
  });

  test("/loop 5s runs twice, then Esc stops it", async () => {
    mock.module("../services/prompt-suggestion.ts", () => ({
      executePromptSuggestion: async () => {},
      makeSuggestionExecutor: () => async () => ({}),
    }));
    const asked: string[] = [];
    mock.module("../entrypoints/session-init.ts", () => ({
      getLoopDeps: () => ({
        callModel: async (p: { messages: Array<{ role: string; content: unknown }> }): Promise<ModelResponse> => {
          const last = p.messages[p.messages.length - 1]!;
          const blocks = Array.isArray(last.content) ? (last.content as Array<Record<string, unknown>>) : [];
          asked.push(blocks.map((b) => String(b["text"] ?? "")).join(""));
          return { role: "assistant", content: [{ type: "text", text: `checked ${asked.length}` }], stop_reason: "end_turn" };
        },
        microcompact: async (m: unknown[]) => m,
        autocompact: async () => {},
        generateUuid: () => crypto.randomUUID(),
        sleep: async () => {},
      }),
      getToolResultBudget: () => ({ maxChars: 100_000, conversationMaxChars: 500_000 }),
      getCircuitBreakerState: () => null,
    }));

    let raw = "";
    const columns = 120, rows = 40;
    const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
    const handle = mountInk(
      React.createElement(
        TerminalSizeContext.Provider,
        { value: { columns, rows } },
        React.createElement(ReplScreen, { config, cwd: process.cwd(), env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" }, onExit: () => {} }),
      ),
      { stream: { write(s: string) { raw += s; } }, stdout: { columns, rows } },
    );

    try {
      await wait(300);
      for (const ch of "/loop 5s check the build") _deliverKeyEvent(ch, {});
      await wait(250);
      const t0 = Date.now();
      _deliverKeyEvent("return", {});

      await until(() => asked.length >= 1, 5000);
      expect(asked).toEqual(["check the build"]); // run 1: immediately
      expect(hasActiveLoops()).toBe(true);

      await until(() => asked.length >= 2, 15_000);
      expect(asked).toEqual(["check the build", "check the build"]); // run 2: one interval later
      expect(Date.now() - t0).toBeGreaterThanOrEqual(4800);

      _deliverKeyEvent("escape", {});
      await wait(300);
      expect(hasActiveLoops()).toBe(false);
      expect(renderedText(raw, columns, rows)).toContain("Stopped 1 loop.");

      await wait(7000); // longer than an interval: nothing more may fire
      expect(asked.length).toBe(2);
    } finally {
      handle.unmount();
    }
  }, 60_000);
});
