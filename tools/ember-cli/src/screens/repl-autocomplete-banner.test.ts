// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { IDENTITY_TAGLINE } from "../components/logo-homescreen.ts";
import { ReplScreen } from "./repl.ts";

const COLS = 100;
const ROWS = 40;

function reconstructRows(out: string): Map<number, string> {
  const grid = new Map<number, Map<number, string>>();
  const tokenPattern = /\x1b\[(\d+);(\d+)H|\x1b\[[0-9;]*[A-Za-z]|[^\x1b]+/g;
  let row = 1;
  let col = 1;
  let match: RegExpExecArray | null;
  while ((match = tokenPattern.exec(out))) {
    const token = match[0];
    if (token.startsWith("\x1b[") && /H$/.test(token) && match[1] !== undefined) {
      row = Number(match[1]);
      col = Number(match[2]);
      continue;
    }
    if (token.startsWith("\x1b[")) continue;
    let cells = grid.get(row);
    if (!cells) {
      cells = new Map();
      grid.set(row, cells);
    }
    for (const character of token) {
      cells.set(col, character);
      col += 1;
    }
  }
  const rows = new Map<number, string>();
  for (const [rowNumber, cells] of grid) {
    const lastColumn = Math.max(...cells.keys());
    let line = "";
    for (let column = 1; column <= lastColumn; column += 1) line += cells.get(column) ?? " ";
    rows.set(rowNumber, line);
  }
  return rows;
}

async function flush(): Promise<void> {
  for (let index = 0; index < 5; index += 1) {
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
}

const chunks: string[] = [];
let handle: ReturnType<typeof mountInk> | null = null;

beforeAll(() => {
  resetCommandRegistryForTests();
  handle = mountInk(
    React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns: COLS, rows: ROWS } },
      React.createElement(ReplScreen, {
        config: { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" },
        cwd: process.cwd(),
        env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
        onExit: () => {},
      }),
    ),
    {
      stream: { write(chunk: string | Uint8Array) { chunks.push(typeof chunk === "string" ? chunk : new TextDecoder().decode(chunk)); } },
      stdout: { columns: COLS, rows: ROWS },
    },
  );
});

afterAll(() => handle?.unmount());

describe("#1369 autocomplete keeps the banner/spine region rendered", () => {
  test("typing '/' leaves both the palette and Homescreen identity in the final grid", async () => {
    await flush();
    _deliverKeyEvent("/", {});
    await flush();
    const rows = [...reconstructRows(chunks.join("")).values()];
    expect(rows.some((line) => line.includes("/observatory"))).toBe(true);
    expect(rows.some((line) => line.includes(IDENTITY_TAGLINE))).toBe(true);
  });
});
