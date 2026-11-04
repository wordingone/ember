// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tab-control-char-repaint.test.ts — #2379 FO-49 live check (2026-11-04): Read tool-result rows
// were drawn with leftover text from earlier rows ("1txt:4Theckubrown fox ...") until Ctrl+L.
// Read's content is `<padded line number>\t<line>`. The pipeline measured "\t" as one cell and
// wrote it into a cell as-is; a real terminal moves the cursor to the next tab stop WITHOUT
// overwriting the cells it skips, so the cursor and the renderer's frame disagree and old cells
// stay on screen. These tests feed the renderer's real bytes into a terminal emulator.

import { describe, expect, test } from "bun:test";
import React from "react";
import { Terminal } from "@xterm/headless";
import { Box, Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";
import { expandTerminalText } from "./rendering-pipeline.ts";

const COLS = 60;
const ROWS = 6;

function screen(terminal: Terminal): string[] {
  const start = terminal.buffer.active.viewportY;
  return Array.from({ length: terminal.rows }, (_, row) =>
    terminal.buffer.active.getLine(start + row)?.translateToString(true).trimEnd() ?? "",
  );
}

function column(lines: string[]): React.ReactElement {
  return React.createElement(Box, { flexDirection: "column" },
    ...lines.map((l, i) => React.createElement(Text, { key: String(i) }, l)));
}

async function paint(frames: React.ReactElement[]): Promise<string[]> {
  const terminal = new Terminal({ cols: COLS, rows: ROWS, allowProposedApi: true });
  let pending = Promise.resolve();
  const stream = {
    write(s: string) {
      pending = pending.then(() => new Promise<void>((resolve) => terminal.write(s, resolve)));
    },
  };
  const handle = mountInk(frames[0]!, { stream, stdout: { columns: COLS, rows: ROWS } });
  for (const f of frames.slice(1)) handle.update(f);
  await pending;
  const out = screen(terminal);
  handle.unmount();
  terminal.dispose();
  return out;
}

describe("tabs and control characters in Text never leave stale cells (#2379 FO-49)", () => {
  test("a Read-style row painted over an earlier Grep-style row shows only the new text", async () => {
    const before = column([
      "notes.txt:4:Line four mentions the moon.",
      "notes.txt:5:The the the.",
    ]);
    const after = column([
      "     1\tThe quick brown fox jumps over the lazy dog.",
      "     2\tThe the the.",
    ]);
    const rows = await paint([before, after]);
    expect(rows[0]).toBe("     1  The quick brown fox jumps over the lazy dog.");
    expect(rows[1]).toBe("     2  The the the.");
  });

  test("two Read results in a row (the live repro) both paint cleanly", async () => {
    const first = column(["     1\talpha", "     2\tbeta beta beta beta"]);
    const second = column(["     1\tx", "     2\ty"]);
    const rows = await paint([first, second]);
    expect(rows[0]).toBe("     1  x");
    expect(rows[1]).toBe("     2  y");
  });

  test("tab stops are every 8 columns from the start of the line", () => {
    expect(expandTerminalText("a\tb").text).toBe("a       b");
    expect(expandTerminalText("abcdefgh\tc").text).toBe("abcdefgh        c");
    expect(expandTerminalText("x\ny\tz").text).toBe("x\ny       z");
  });

  test("carriage returns and other C0 controls are dropped, newlines kept", () => {
    expect(expandTerminalText("a\r\nb").text).toBe("a\nb");
    expect(expandTerminalText("a\x07b\x08c\x1bd").text).toBe("abcd");
    expect(expandTerminalText("plain text").text).toBe("plain text");
  });

  test("styled runs follow the expansion so colors stay on the right cells", () => {
    const red = { fg: { type: "named" as const, index: 1 } };
    const out = expandTerminalText("1\tok", [{ len: 2, style: red }, { len: 2, style: {} }]);
    expect(out.text).toBe("1       ok");
    expect(out.runs).toEqual([{ len: 8, style: red }, { len: 2, style: {} }]);
  });

  test("a carriage return mid-line cannot rewind the cursor over earlier cells", async () => {
    const rows = await paint([column(["0123456789"]), column(["abc\rXY"])]);
    expect(rows[0]).toBe("abcXY");
  });
});
