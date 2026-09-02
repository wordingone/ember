// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// highlighted-code-multiline.test.ts — D5 finding: a multi-line code block handed to a SINGLE
// Text (or RawAnsi) node never advances rows on its own embedded "\n" characters --
// renderNodeToOutput's text-walk (ink/rendering-pipeline.ts) computes col/row purely from the
// node's own layout position, character by character, with no special handling for "\n" (it is
// just charWidth(1) like any other character, written literally at the current terminal row/col).
// The result: a multi-line code block collapses onto one terminal row, runs past the viewport
// width, and everything past the cutoff is silently dropped -- not just squished, LOST. Fix:
// HighlightedCode must split on "\n" and render one Text/RawAnsi per line inside a Box{column},
// matching the convention already established for every other multi-line surface in this codebase
// (Fireball, AssistantTextMessage's ANSI-panel routing).
import { describe, test, expect } from "bun:test";
import React from "react";
import { HighlightedCode } from "./markdown-and-code.ts";
import { mountInk } from "../ink/reconciler.ts";

function mountAndCapture(el: React.ReactElement, cols = 80, rows = 12): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  return buf;
}

const MULTI_LINE_CODE = [
  "export async function withRetry(fn, opts) {",
  "  for (let attempt = 0; attempt < opts.maxAttempts; attempt++) {",
  "    try { return await fn(); } catch (err) {",
  "      await sleep(backoffMs(attempt, opts));",
  "    }",
  "  }",
  "}",
].join("\n");

describe("HighlightedCode with EMBER_SYNTAX_HIGHLIGHT unset (plain-text fallback)", () => {
  test("every line of a multi-line code block survives in the render (none silently dropped)", () => {
    const saved = process.env["EMBER_SYNTAX_HIGHLIGHT"];
    delete process.env["EMBER_SYNTAX_HIGHLIGHT"];
    try {
      const out = mountAndCapture(React.createElement(HighlightedCode, { language: "typescript", code: MULTI_LINE_CODE }));
      for (const line of MULTI_LINE_CODE.split("\n")) {
        expect(out).toContain(line.trim() === "" ? line : line);
      }
    } finally {
      if (saved === undefined) delete process.env["EMBER_SYNTAX_HIGHLIGHT"];
      else process.env["EMBER_SYNTAX_HIGHLIGHT"] = saved;
    }
  });

  test("the render contains multiple distinct cursor-position rows (not collapsed onto one row)", () => {
    delete process.env["EMBER_SYNTAX_HIGHLIGHT"];
    const out = mountAndCapture(React.createElement(HighlightedCode, { language: "typescript", code: MULTI_LINE_CODE }));
    const rows = new Set<number>();
    const re = /\x1b\[(\d+);(\d+)H/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(out))) rows.add(Number(m[1]));
    expect(rows.size).toBeGreaterThanOrEqual(MULTI_LINE_CODE.split("\n").length);
  });

  test("the render contains no literal, unhandled newline byte (0x0A) inside a written line", () => {
    delete process.env["EMBER_SYNTAX_HIGHLIGHT"];
    const out = mountAndCapture(React.createElement(HighlightedCode, { language: "typescript", code: MULTI_LINE_CODE }));
    // Strip legitimate escape-sequence bytes first, then confirm no stray \n outside of what the
    // cursor-position addressing itself accounts for (each write chunk should be single-line).
    const chunks = out.split(/\x1b\[\d+;\d+H/);
    for (const chunk of chunks) {
      expect(chunk.includes("\n")).toBe(false);
    }
  });
});
