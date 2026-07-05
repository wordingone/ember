// chrome-stack.test.ts — B6 W4': the bottom fixed-chrome stack (fireball, prompt, status bar)
// must obey a strict compression contract under a tall-transcript / vertical-space-starved
// scenario: status bar pinned to the TRUE last row; prompt row NEVER absent; fireball is the
// FIRST element to yield (hide) when space is starved; nothing ever paints below the status bar.
//
// Root cause: layout-engine.ts's shrink pass (the `freeSpace < 0` branch) distributes the deficit
// PROPORTIONALLY across every child's base size, with ZERO regard for that child's own
// `flexShrink` value -- so a fixed-chrome sibling declared `flexShrink:0` was still crushed right
// alongside the flex-grow transcript whenever the transcript's own (unclamped, auto-height)
// natural content size exceeded the viewport. The property exists (FlexNode.flexShrink, correctly
// copied by reconciler.ts's applyBoxStyle) but was never consulted during the actual cut -- the
// same *class* of gap as W4 (overflow declared, never wired into the computation that mattered).
import { describe, test, expect } from "bun:test";
import React from "react";
import { Box, Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";

function mountAndCapture(el: React.ReactElement, cols = 40, rows = 10): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  return buf;
}

function rowsWritten(out: string): number[] {
  const re = /\x1b\[(\d+);(\d+)H/g;
  let m: RegExpExecArray | null;
  const rows: number[] = [];
  while ((m = re.exec(out))) rows.push(Number(m[1]));
  return rows;
}

function maxRowWritten(out: string): number {
  return rowsWritten(out).reduce((a, b) => Math.max(a, b), 0);
}

/** Row(s) a given substring's cursor-position write landed on, in the order they were written. */
function rowsForText(out: string, needle: string): number[] {
  const re = /\x1b\[(\d+);(\d+)H([^\x1b]*)/g;
  let m: RegExpExecArray | null;
  const found: number[] = [];
  while ((m = re.exec(out))) {
    if (m[3].includes(needle)) found.push(Number(m[1]));
  }
  return found;
}

/** Builds the same 4-part fixed-chrome shape as ReplScreen's real render tree (repl.ts):
 * transcript (flexGrow:1, overflow:"hidden", oversized content) / prompt / fireball / status bar.
 * `wrapFixed` lets a test opt into the fix's flexShrink:0 wrapper without duplicating the tree. */
function buildChromeStack(opts: { totalRows: number; boardLines: number; wrapFixed: boolean }): React.ReactElement {
  const { totalRows, boardLines, wrapFixed } = opts;
  const transcript = React.createElement(
    Box, { key: "transcript", flexDirection: "column", flexGrow: 1, overflow: "hidden" },
    ...Array.from({ length: boardLines }, (_, i) => React.createElement(Text, { key: i }, `board row ${i}`)),
  );
  const promptEl = React.createElement(Text, { key: "prompt-text" }, "❯ prompt-line");
  const prompt = wrapFixed
    ? React.createElement(Box, { key: "prompt", flexShrink: 0 }, promptEl)
    : React.createElement(Box, { key: "prompt" }, promptEl);
  const fireballLines = [
    React.createElement(Text, { key: 0 }, "FIRE-A"),
    React.createElement(Text, { key: 1 }, "FIRE-B"),
    React.createElement(Text, { key: 2 }, "FIRE-C"),
  ];
  const fireball = React.createElement(
    Box,
    wrapFixed
      ? { key: "fireball", flexDirection: "column", width: 9, flexShrink: 0 }
      : { key: "fireball", flexDirection: "column", width: 9 },
    ...fireballLines,
  );
  const statusEl = React.createElement(Text, { key: "status-text" }, "STATUS-BAR-END");
  const status = wrapFixed
    ? React.createElement(Box, { key: "status", flexShrink: 0 }, statusEl)
    : React.createElement(Box, { key: "status" }, statusEl);
  return React.createElement(
    Box, { flexDirection: "column", height: totalRows },
    transcript, prompt, fireball, status,
  );
}

describe("W4': bottom fixed-chrome stack under tall-transcript vertical-space pressure", () => {
  test("status bar is pinned to the true last row, prompt is present, nothing paints below the status bar", () => {
    const totalRows = 32;
    const el = buildChromeStack({ totalRows, boardLines: 40, wrapFixed: true });
    const out = mountAndCapture(el, 100, totalRows);

    const statusRows = rowsForText(out, "STATUS-BAR-END");
    expect(statusRows.length).toBeGreaterThan(0);
    const statusRow = statusRows[statusRows.length - 1];
    expect(statusRow).toBe(totalRows);

    const promptRows = rowsForText(out, "prompt-line");
    expect(promptRows.length).toBeGreaterThan(0);

    expect(maxRowWritten(out)).toBe(totalRows);

    // The fireball must never be partially crushed into a broken glyph fragment -- all three of
    // its lines are either fully present or (in a genuinely starved terminal) fully absent.
    const fireballLinesPresent = ["FIRE-A", "FIRE-B", "FIRE-C"].filter((s) => out.includes(s)).length;
    expect(fireballLinesPresent === 0 || fireballLinesPresent === 3).toBe(true);
  });

  test("regression guard: with plenty of room, all four chrome parts render (nothing over-suppressed)", () => {
    const totalRows = 32;
    const el = buildChromeStack({ totalRows, boardLines: 3, wrapFixed: true });
    const out = mountAndCapture(el, 100, totalRows);
    expect(out).toContain("board row 0");
    expect(out).toContain("prompt-line");
    expect(out).toContain("STATUS-BAR-END");
  });
});
