// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2380 S24 (approval case): while the "Allow Bash: ..." box waits for the user, the spinner said
// "Thinking... 4m 45s". It must say the turn is waiting for approval, with its own wait time.
// One real turn through ReplScreen in regular permission mode; only the model call is scripted.
// The screen is tall because the worktree-root warning banners fill the prompt box in this checkout.
import { expect, mock, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import type { ModelResponse } from "../query/query-loop-support.ts";
import { ReplScreen } from "../screens/repl.ts";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

test("regular mode: a pending approval is named by the spinner, never 'Thinking'", async () => {
  let call = 0;
  mock.module("../entrypoints/session-init.ts", () => ({
    getLoopDeps: () => ({
      callModel: async (): Promise<ModelResponse> => {
        call += 1;
        if (call === 1) {
          return {
            role: "assistant",
            content: [{ type: "tool_use", id: "t1", name: "Bash", input: { command: "echo approval-probe" } }],
            stop_reason: "tool_use",
            usage: { input_tokens: 1, output_tokens: 1 },
          };
        }
        return { role: "assistant", content: [{ type: "text", text: "ok" }], stop_reason: "end_turn", usage: { input_tokens: 1, output_tokens: 1 } };
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
  const columns = 100, rows = 70;
  const handle = mountInk(
    React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns, rows } },
      React.createElement(ReplScreen, {
        config: { model: "ember", permissionMode: "regular" as const, baseSystemPrompt: "" },
        cwd: process.cwd(),
        env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
        onExit: () => {},
      }),
    ),
    { stream: { write(s: string) { raw += s; return true; } }, stdout: { columns, rows } },
  );
  const screen = (): string[] => {
    const frame = buildFrame(columns, rows);
    parseRenderedIntoFrame(raw, frame, new StylePool());
    return frame.cells.map((r) => r.map((c) => c.char).join("").trimEnd());
  };
  try {
    for (const ch of "do it") _deliverKeyEvent(ch, {});
    await sleep(200);
    _deliverKeyEvent("return", {});
    const start = Date.now();
    let lines: string[] = [];
    while (Date.now() - start < 15_000) {
      await sleep(250);
      lines = screen();
      if (lines.some((l) => l.includes("Allow Bash"))) break;
    }
    expect(lines.some((l) => l.includes("Allow Bash") && l.includes("echo approval-probe"))).toBe(true);
    // let the spinner tick at least once so the label is what it settles on, not a first frame
    await sleep(1300);
    lines = screen();

    const spinnerRow = lines.find((l) => l.includes("Waiting for your approval"));
    expect(spinnerRow).toBeDefined();
    // the row keeps its own wait time and the interrupt hint on the same line (the command itself
    // is in the box directly above, so a narrow column may cut it from the label)
    expect(spinnerRow).toMatch(/\d+s · Esc to interrupt/);
    expect(lines.join("\n")).not.toContain("Thinking");
    // answering ends the wait: the spinner stops naming an approval
    _deliverKeyEvent("n", {});
    await sleep(800);
    expect(screen().join("\n")).not.toContain("Waiting for your approval");
  } finally {
    handle.unmount();
  }
}, 40_000);
