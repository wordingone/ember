// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2380 S26: a turn whose reply is only hidden reasoning ended on a frozen, empty screen. It now ends
// with a notice saying so. Pure seam (applyResultEvent) plus one real turn through ReplScreen.
import { expect, mock, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import type { ModelResponse } from "../query/query-loop-support.ts";
import { applyResultEvent, ReplScreen } from "../screens/repl.ts";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const NOTICE = "The model finished without writing an answer";

const reasoningOnly = {
  role: "assistant",
  content: [{ type: "thinking", thinking: "hmm, let me think about this for a long time" }],
  stop_reason: "end_turn",
  usage: { input_tokens: 1, output_tokens: 1 },
} as unknown as ModelResponse;

test("applyResultEvent: an empty answer with only reasoning behind it becomes a visible notice", () => {
  const out = applyResultEvent(
    { type: "result", subtype: "success", durationMs: 1, finalMessage: reasoningOnly } as any,
    [{ id: "u", type: "user", content: "hi" }, { id: "p", type: "assistant", content: "" }] as any,
    "p",
  );
  expect(out.some((m) => m.id === "p")).toBe(false);
  const last = out[out.length - 1]!;
  expect(last.type).toBe("error");
  expect(String(last["content"])).toContain(NOTICE);
});

test("applyResultEvent: a real answer is left alone", () => {
  const withText = { ...reasoningOnly, content: [{ type: "text", text: "done" }] } as unknown as ModelResponse;
  const out = applyResultEvent(
    { type: "result", subtype: "success", durationMs: 1, finalMessage: withText } as any,
    [{ id: "p", type: "assistant", content: "done" }] as any,
    "p",
  );
  expect(out.length).toBe(1);
  expect(out[0]!["content"]).toBe("done");
  expect(out[0]!["stop_reason"]).toBe("end_turn");
});

test("a reasoning-only turn through the real REPL ends with the notice on screen", async () => {
  mock.module("../entrypoints/session-init.ts", () => ({
    getLoopDeps: () => ({
      callModel: async (): Promise<ModelResponse> => reasoningOnly,
      microcompact: async (m: unknown[]) => m,
      autocompact: async () => {},
      generateUuid: () => crypto.randomUUID(),
      sleep: async () => {},
    }),
    getToolResultBudget: () => ({ maxChars: 100_000, conversationMaxChars: 500_000 }),
    getCircuitBreakerState: () => null,
  }));
  let raw = "";
  const columns = 100, rows = 30;
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
    for (const ch of "think hard") _deliverKeyEvent(ch, {});
    await sleep(200);
    _deliverKeyEvent("return", {});
    const start = Date.now();
    let text = "";
    while (Date.now() - start < 15_000) {
      await sleep(250);
      const frame = buildFrame(columns, rows);
      parseRenderedIntoFrame(raw, frame, new StylePool());
      text = frame.cells.map((r) => r.map((c) => c.char).join("").trimEnd()).join("\n");
      if (text.includes(NOTICE)) break;
    }
    expect(text).toContain(NOTICE);
  } finally {
    handle.unmount();
  }
}, 30_000);
