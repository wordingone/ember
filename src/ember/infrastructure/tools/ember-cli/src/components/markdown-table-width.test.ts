// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2380 S39: a markdown table wider than the chat column was squeezed (last column cut to two
// characters) or clipped. It is now laid out as one `Header: value` list per row when it does not
// fit, and stays a grid when it does.
// #2381 U-indent: every wrapped line of a reply hangs under the text, not under the "● " gutter.
import { expect, test } from "bun:test";
import React from "react";
import { Box } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { Markdown, tableNaturalWidth } from "./markdown-and-code.ts";
import { AssistantTextMessage } from "./message-renderers.ts";

function renderLines(element: React.ReactElement, columns: number, rows: number): string[] {
  let output = "";
  mountInk(element, { stream: { write(chunk: string) { output += chunk; } }, stdout: { columns, rows } });
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(output, frame, new StylePool());
  return frame.cells.map((row) => row.map((cell) => cell.char).join("").trimEnd());
}
function reply(text: string, width: number, rows = 24): string[] {
  return renderLines(
    React.createElement(Box, { width, flexDirection: "column", overflow: "hidden" },
      React.createElement(AssistantTextMessage, { text, width })),
    width + 4, rows,
  );
}

const TABLE = [
  "| Command | What it does | Example usage |",
  "|---|---|---|",
  "| ember --resume | Continue the most recent session in this folder | ember --resume |",
  "| ember --model | Pick a model for this session instead of the default | ember --model qwen3 |",
].join("\n");

test("natural width counts each column plus its gap", () => {
  expect(tableNaturalWidth([3, 5])).toBe(10);
  expect(tableNaturalWidth([])).toBe(0);
});

test("a table that fits stays a grid, columns aligned", () => {
  const lines = reply("| a | bb |\n|---|---|\n| ccc | d |", 40, 6);
  expect(lines[0]).toContain("● ");
  expect(lines.join("\n")).toContain("a   bb");
  expect(lines.join("\n")).toContain("ccc d");
});

test("a table wider than the column becomes Header: value records, nothing cut", () => {
  const lines = reply(TABLE, 40);
  const text = lines.join("\n");
  // the first and last column of the wide rows survive whole
  expect(text).toContain("Command");
  expect(text).toContain("Example usage");
  // every cell's words are present somewhere (wrapped, not clipped)
  const flat = text.replace(/\s+/g, " ");
  for (const word of ["ember --resume", "Continue the most recent session in this folder", "ember --model qwen3"]) {
    expect(flat).toContain(word);
  }
  // no row of the output is wider than the column
  for (const l of lines) expect(l.length).toBeLessThanOrEqual(40);
  // never a two-character sliver of a column: no line is a lone 1-2 char fragment next to a label
  expect(lines.some((l) => /Example usage:\s+\S{1,2}$/.test(l))).toBe(false);
});

test("a wide table is a record per row, separated by a blank line", () => {
  const lines = reply(TABLE, 40);
  const labelRows = lines.filter((l) => l.includes("Command:"));
  expect(labelRows.length).toBe(2);
});

test("the same table in a wide column is still a grid", () => {
  const lines = reply(TABLE, 120, 8);
  expect(lines.some((l) => l.includes("Command") && l.includes("What it does") && l.includes("Example usage"))).toBe(true);
});

test("Markdown without a width keeps the old grid whatever the size", () => {
  const lines = renderLines(React.createElement(Box, { width: 200 }, React.createElement(Markdown, { content: TABLE })), 200, 6);
  expect(lines.some((l) => l.includes("Command") && l.includes("Example usage"))).toBe(true);
});

test("U-indent: a long paragraph's continuation lines start under the text, after the gutter", () => {
  const lines = reply("alpha ".repeat(30).trim(), 30, 10).filter((l) => l.trim() !== "");
  expect(lines.length).toBeGreaterThan(2);
  expect(lines[0]!.startsWith("● ")).toBe(true);
  for (const l of lines.slice(1)) expect(l.startsWith("  ") && !l.startsWith("   ")).toBe(true);
});

test("U-indent: a long bullet's continuation lines hang under the item text", () => {
  const lines = reply("- " + "beta ".repeat(20).trim(), 30, 10).filter((l) => l.trim() !== "");
  expect(lines.length).toBeGreaterThan(2);
  expect(lines[0]!.startsWith("● • ")).toBe(true);
  for (const l of lines.slice(1)) expect(l.startsWith("    ") && !l.startsWith("     ")).toBe(true);
});
