// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { resetCommandRegistryForTests, setCommandRegistryDeps } from "../../../../../../../tools/ember-cli/src/command-registry.ts";
import { IDENTITY_TAGLINE } from "../components/logo-homescreen.ts";
import type { RegistryCommand } from "../types/command-types.ts";
import { ReplScreen } from "../../../../../../../tools/ember-cli/src/screens/repl.ts";

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
    if (token.startsWith("\x1b[")) {
      const eraseLine = /^\x1b\[([0-2]?)K$/.exec(token);
      if (eraseLine) {
        const mode = eraseLine[1] === "" ? 0 : Number(eraseLine[1]);
        const cells = grid.get(row);
        if (mode === 2) {
          grid.delete(row);
        } else if (cells) {
          for (const column of [...cells.keys()]) {
            if ((mode === 0 && column >= col) || (mode === 1 && column <= col)) cells.delete(column);
          }
          if (cells.size === 0) grid.delete(row);
        }
      }
      continue;
    }
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

function mountRepl(commands?: RegistryCommand[]): {
  chunks: string[];
  unmount: () => void;
} {
  resetCommandRegistryForTests();
  if (commands) setCommandRegistryDeps({ getBuiltinCommands: () => commands });
  const chunks: string[] = [];
  const handle = mountInk(
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
  return {
    chunks,
    unmount: () => {
      handle.unmount();
      resetCommandRegistryForTests();
    },
  };
}

describe("#1369 autocomplete keeps the banner/spine region rendered", () => {
  test("terminal-grid reconstruction applies CSI erase-line updates", () => {
    const rows = reconstructRows("\x1b[1;1HIDENTITY\x1b[1;1H\x1b[2KNEW");
    expect(rows.get(1)).toBe("NEW");
  });

  test("typing '/' leaves both the palette and Homescreen identity in the final grid", async () => {
    const harness = mountRepl();
    try {
      await flush();
      _deliverKeyEvent("/", {});
      await flush();
      const rows = [...reconstructRows(harness.chunks.join("")).values()];
      expect(rows.some((line) => line.includes("/observatory"))).toBe(true);
      expect(rows.some((line) => line.includes(IDENTITY_TAGLINE))).toBe(true);
    } finally {
      harness.unmount();
    }
  });

  test("an exact argument-free registered command dispatches once on the first Enter", async () => {
    const dispatched: string[] = [];
    const harness = mountRepl([
      {
        name: "probeexact",
        description: "first-enter dispatch probe",
        isEnabled: () => true,
        execute: async (args: string) => {
          dispatched.push(args);
          return { type: "message", message: "PROBEEXACT-EXECUTED" };
        },
      },
    ]);
    try {
      await flush();
      for (const character of "/probeexact") _deliverKeyEvent(character, {});
      await flush();
      _deliverKeyEvent("return", {});
      await flush();

      expect(dispatched).toEqual([""]);
      const rows = [...reconstructRows(harness.chunks.join("")).values()];
      expect(rows.some((line) => line.includes("PROBEEXACT-EXECUTED"))).toBe(true);
    } finally {
      harness.unmount();
    }
  });

  test("an exact argument-free command dispatches even when a longer prefix match is selected first", async () => {
    const dispatched: string[] = [];
    const harness = mountRepl([
      {
        name: "probeexact-longer",
        description: "registry-order collision selected ahead of the exact command",
        isEnabled: () => true,
        execute: async (args: string) => {
          dispatched.push(`longer:${args}`);
          return { type: "message", message: "WRONG-COMMAND-EXECUTED" };
        },
      },
      {
        name: "probeexact",
        description: "exact first-enter dispatch probe",
        isEnabled: () => true,
        execute: async (args: string) => {
          dispatched.push(`exact:${args}`);
          return { type: "message", message: "EXACT-COMMAND-EXECUTED" };
        },
      },
    ]);
    try {
      await flush();
      for (const character of "/probeexact") _deliverKeyEvent(character, {});
      await flush();
      _deliverKeyEvent("return", {});
      await flush();

      expect(dispatched).toEqual(["exact:"]);
      const rows = [...reconstructRows(harness.chunks.join("")).values()];
      expect(rows.some((line) => line.includes("EXACT-COMMAND-EXECUTED"))).toBe(true);
      expect(rows.some((line) => line.includes("WRONG-COMMAND-EXECUTED"))).toBe(false);
    } finally {
      harness.unmount();
    }
  });
});
