// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2380 S41: /clear shrinks the transcript to the welcome card; the next frame must be a full
// clear-and-repaint so nothing of the old transcript survives on the terminal.
import { expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { ReplScreen } from "../screens/repl.ts";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

test("/clear arms a full repaint: the frame after it clears the screen first", async () => {
  const chunks: string[] = [];
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
    { stream: { write(s: string) { chunks.push(s); return true; } }, stdout: { columns, rows } },
  );
  try {
    await sleep(300);
    chunks.length = 0;
    for (const ch of "/clear") _deliverKeyEvent(ch, {});
    await sleep(200);
    // the slash palette is open on a bare "/clear": the first Enter may only complete it
    _deliverKeyEvent("return", {});
    await sleep(600);
    const afterClear = chunks.join("");
    expect(afterClear).toContain("\x1b[2J");
  } finally {
    handle.unmount();
  }
}, 20_000);
