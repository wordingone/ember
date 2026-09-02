// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// cockpit-ansi-passthrough-check.test.ts — verifies (empirically, not by assumption) whether
// renderMonitorPanel()'s ANSI-colored output survives the /cockpit message display path intact.
// AssistantTextMessage's default case routes text through Markdown -> renderInline -> a plain
// Text leaf, which paints its content CHARACTER BY CHARACTER (ink/rendering-pipeline.ts's text
// branch), treating each byte of an embedded \x1b[... escape sequence as its own 1-cell-wide
// printable character. HighlightedCode already hit this exact problem for ANSI-highlighted code
// and works around it by routing through RawAnsi (markdown-and-code.ts:52-54) -- this test checks
// whether AssistantTextMessage needs the same treatment before wiring a colored panel into it.
import { describe, test, expect } from "bun:test";
import React from "react";
import { AssistantTextMessage } from "./message-renderers.ts";
import { mountInk } from "../ink/reconciler.ts";

function mountAndCapture(el: React.ReactElement, cols = 100, rows = 12): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  return buf;
}

describe("AssistantTextMessage vs embedded ANSI content", () => {
  test("a message containing an embedded truecolor escape code renders WITHOUT the raw escape digits leaking as literal text", () => {
    // Mirrors exactly what renderMonitorPanel() would emit: a real SGR truecolor sequence
    // followed by a border glyph.
    const coloredLine = "\x1b[38;2;100;150;200m╭─────╮\x1b[0m";
    const out = mountAndCapture(React.createElement(AssistantTextMessage, { text: coloredLine }));
    // The escape sequence must survive INTACT (ESC byte still attached to its digits) --
    // proof it was written as one opaque block, not walked character-by-character and
    // reinterpreted into orphaned, garbled digit text. (The pipeline re-parses/re-emits SGR
    // resets in its own canonical short form \x1b[m, so check the color-setting half verbatim.)
    expect(out).toContain("\x1b[38;2;100;150;200m╭─────╮");
    // A garbled render would show the ESC byte consumed/dropped by something upstream while its
    // printable digits leak out on their own -- that orphaned form must never appear.
    expect(out).not.toMatch(/[^\x1b]\[38;2;100;150;200m/);
  });

  test("a plain multi-line message with no ANSI content still renders normally (regression guard)", () => {
    const out = mountAndCapture(React.createElement(AssistantTextMessage, { text: "hello\nworld" }));
    expect(out).toContain("hello");
    expect(out).toContain("world");
  });
});
