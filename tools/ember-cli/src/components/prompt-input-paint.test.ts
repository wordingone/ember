// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import React from "react";
import { Terminal } from "@xterm/headless";
import { Text } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import {
  PromptInput,
  promptInputViewportWidth,
  type PromptInputState,
} from "./prompt-input.ts";

const ROWS = 8;

function state(): PromptInputState {
  return {
    text: "operator input",
    cursor: 14,
    mode: "prompt",
    isStashed: false,
    permissionMode: "bypass",
    pastedContents: null,
    stashNotice: "",
  };
}

function element(width: number): React.ReactElement {
  return React.createElement(PromptInput, {
    state: state(),
    statusLine: React.createElement(Text, null, "STATUS"),
    showStatusLine: false,
    width,
  });
}

function lines(terminal: Terminal): string[] {
  const start = terminal.buffer.active.viewportY;
  return Array.from({ length: terminal.rows }, (_, row) =>
    terminal.buffer.active.getLine(start + row)?.translateToString(false) ?? "",
  );
}

function assertClosedPromptRegion(frame: string[], width: number): void {
  const top = frame.findIndex((line) => line.startsWith("╭") && line.includes("╮"));
  const bottom = frame.findIndex((line) => line.startsWith("╰") && line.includes("╯"));
  expect(top).toBeGreaterThanOrEqual(0);
  expect(bottom).toBeGreaterThan(top);

  const right = frame[top]!.indexOf("╮");
  expect(right).toBe(width - 1);
  expect(frame[bottom]!.indexOf("╯")).toBe(right);

  const prompt = frame.find((line) => line.includes("❯"));
  const status = frame.find((line) => line.includes("STATUS"));
  expect(prompt).toBeDefined();
  expect(status).toBeDefined();
  for (const row of [prompt!, status!]) {
    expect(row[0]).toBe("│");
    expect(row[right]).toBe("│");
  }
}

describe("PromptInput real terminal paint", () => {
  test("keeps a closed rounded region through a live 80 to 40 to 80 resize", async () => {
    const stdout = { columns: 80, rows: ROWS };
    const terminal = new Terminal({ cols: 80, rows: ROWS, allowProposedApi: true });
    let writes = Promise.resolve();
    const stream = {
      write(data: string) {
        writes = writes.then(() => new Promise<void>((resolve) => terminal.write(data, resolve)));
      },
    };

    const handle = mountInk(element(80), { stream, stdout });
    await writes;
    assertClosedPromptRegion(lines(terminal), 80);

    for (const width of [40, 80]) {
      terminal.resize(width, ROWS);
      stdout.columns = width;
      handle.container.stdout.columns = width;
      handle.container.rootNode.layout.width = width;
      handle.update(element(width));
      await writes;
      assertClosedPromptRegion(lines(terminal), width);
    }

    expect(promptInputViewportWidth(40)).toBeGreaterThan(0);
    handle.unmount();
    terminal.dispose();
  });
});
