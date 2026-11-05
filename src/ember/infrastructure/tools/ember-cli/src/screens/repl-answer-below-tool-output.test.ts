// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2380 S40: the final answer was drawn above the tool output it came from, and in bypass mode the
// tool line did not show the command. Drives a whole turn through the real ReplScreen, the real
// QueryEngine and the real Bash tool, with only the model call scripted (same seam as
// repl-suggestion-boundary-real-scheduling-success.test.ts; one real mount per file).
import { expect, mock, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import type { ModelResponse } from "../query/query-loop-support.ts";
import { ReplScreen } from "../screens/repl.ts";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

test("bypass mode: tool line names the command; the answer sits below the tool output", async () => {
  let call = 0;
  mock.module("../entrypoints/session-init.ts", () => ({
    getLoopDeps: () => ({
      callModel: async (): Promise<ModelResponse> => {
        call += 1;
        if (call === 1) {
          return {
            role: "assistant",
            content: [
              { type: "text", text: "Let me check." },
              { type: "tool_use", id: "t1", name: "Bash", input: { command: "echo s40-tool-output" } },
            ],
            stop_reason: "tool_use",
            usage: { input_tokens: 5, output_tokens: 5 },
          };
        }
        return {
          role: "assistant",
          content: [{ type: "text", text: "s40-final-answer" }],
          stop_reason: "end_turn",
          usage: { input_tokens: 5, output_tokens: 5 },
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

  let raw = "";
  const columns = 100, rows = 40;
  const handle = mountInk(
    React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns, rows } },
      React.createElement(ReplScreen, {
        config: { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" },
        cwd: process.cwd(),
        env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
        onExit: () => {},
      }),
    ),
    { stream: { write(s: string) { raw += s; return true; } }, stdout: { columns, rows } },
  );
  try {
    for (const ch of "run it") _deliverKeyEvent(ch, {});
    await sleep(200);
    _deliverKeyEvent("return", {});
    const start = Date.now();
    let lines: string[] = [];
    while (Date.now() - start < 20_000) {
      await sleep(250);
      const frame = buildFrame(columns, rows);
      parseRenderedIntoFrame(raw, frame, new StylePool());
      lines = frame.cells.map((r) => r.map((c) => c.char).join("").trimEnd());
      if (lines.some((l) => l.includes("s40-final-answer"))) break;
    }
    const at = (needle: string) => lines.findIndex((l) => l.includes(needle));
    const toolLine = lines.findIndex((l) => l.includes("Bash") && l.includes("echo s40-tool-output"));
    const output = lines.findIndex((l, i) => i > toolLine && l.includes("s40-tool-output"));
    const answer = at("s40-final-answer");
    expect(toolLine).toBeGreaterThanOrEqual(0);
    expect(output).toBeGreaterThan(toolLine);
    expect(answer).toBeGreaterThan(output);
    expect(call).toBeGreaterThanOrEqual(2); // a later call is the prompt-suggestion side request
  } finally {
    handle.unmount();
  }
}, 40_000);
