// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Blind test (visible window): /help lines lost their last characters at the column edge. The
// reply wrapped at the full column width and then sat two cells right, after the "● " gutter.
import { test, expect } from "bun:test";
import React from "react";
import { Box } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { AssistantTextMessage, UserCommandMessage } from "./message-renderers.ts";

function renderLines(element: React.ReactElement, columns: number, rows: number): string[] {
  let output = "";
  mountInk(element, { stream: { write(chunk: string) { output += chunk; } }, stdout: { columns, rows } });
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(output, frame, new StylePool());
  return frame.cells.map((row) => row.map((cell) => cell.char).join("").trimEnd());
}

test("a long reply wraps inside the column, every word kept", () => {
  const words = Array.from({ length: 30 }, (_, i) => `word${i}`);
  const lines = renderLines(
    React.createElement(Box, { width: 30, flexDirection: "column", overflow: "hidden" },
      React.createElement(AssistantTextMessage, { text: words.join(" ") })),
    40, 20,
  );
  const shown = lines.join(" ");
  for (const w of words) expect(shown).toContain(w);
  for (const l of lines) expect(l.length).toBeLessThanOrEqual(30);
});

test("a slash command echoes as typed", () => {
  const lines = renderLines(React.createElement(UserCommandMessage, { command: "help" }), 20, 2);
  expect(lines[0]).toBe("/help");
  const again = renderLines(React.createElement(UserCommandMessage, { command: "/help" }), 20, 2);
  expect(again[0]).toBe("/help");
});

test("a line with a `code` span wraps back to the line start, not under the span", () => {
  // Blind test (operator's screenshot): text after an inline-code span wrapped in its own column.
  const lines = renderLines(
    React.createElement(Box, { width: 40, flexDirection: "column", overflow: "hidden" },
      React.createElement(AssistantTextMessage, {
        text: "The command succeeded: the `made-ok` directory was created and the shell printed created.",
      })),
    50, 10,
  );
  const body = lines.filter((l) => l.trim() !== "");
  expect(body.length).toBeGreaterThan(1);
  // continuation rows start right after the 2-cell "● " gutter, not deep under the span
  for (const l of body.slice(1)) expect(l.startsWith("  ") && !l.startsWith("   ")).toBe(true);
  expect(body.join(" ").replace(/\s+/g, " ")).toContain("the made-ok directory was created and the shell printed created.");
});

test("each span keeps its own colour inside the wrapped line", () => {
  let output = "";
  mountInk(React.createElement(Box, { width: 40 }, React.createElement(AssistantTextMessage, { text: "run `ls` now" })),
    { stream: { write(chunk: string) { output += chunk; } }, stdout: { columns: 50, rows: 4 } });
  const frame = buildFrame(50, 4);
  const pool = new StylePool();
  parseRenderedIntoFrame(output, frame, pool);
  const row = frame.cells[0]!;
  const at = (s: string) => row.map((c) => c.char).join("").indexOf(s);
  expect(row[at("ls")]!.styleRef).not.toBe(row[at("run")]!.styleRef);
  expect(row[at("now")]!.styleRef).toBe(row[at("run")]!.styleRef);
});
