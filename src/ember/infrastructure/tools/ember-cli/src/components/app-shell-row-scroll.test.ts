// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { clampRowOffset, scrollMessagesByRows, type SessionMessage } from "./app-shell.ts";

const msg = (id: string, content: string) => ({ id, type: "assistant", content }) as unknown as SessionMessage;

describe("row scrolling", () => {
  const lines = Array.from({ length: 30 }, (_, i) => `line ${i + 1}`).join("\n");
  const list = [msg("a", "first"), msg("b", lines)];

  it("trims the newest message's tail by the offset", () => {
    const out = scrollMessagesByRows(list, 10, 200);
    expect(out.length).toBe(2);
    expect(String((out[1] as Record<string, unknown>)["content"]).split("\n").pop()).toBe("line 20");
  });

  it("drops whole messages the offset covers and never empties the list", () => {
    expect(scrollMessagesByRows(list, 31, 200).map((m) => m.id)).toEqual(["a"]);
    expect(scrollMessagesByRows(list, 999, 200).length).toBe(1);
  });

  it("clamps to what the transcript can reveal", () => {
    expect(clampRowOffset(-5, list, 10, 200)).toBe(0);
    expect(clampRowOffset(999, list, 10, 200)).toBeLessThanOrEqual(33);
  });
});

// #2381 U-PageUp: PageUp past the oldest message used to leave the oldest message alone at the
// bottom of an otherwise empty screen. The top of the transcript now sits at the top.
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { Text } from "../ink/components.ts";
import { totalMessageRows, VirtualMessageList } from "./app-shell.ts";

function renderList(messages: SessionMessage[], rowOffset: number, viewportRows: number, width: number): string[] {
  let output = "";
  const element = React.createElement(VirtualMessageList, {
    messages,
    viewportRows,
    rowOffset,
    width,
    renderMessage: (m: SessionMessage) => React.createElement(Text, { key: m.id }, String((m as Record<string, unknown>)["content"] ?? "")),
  });
  mountInk(element, { stream: { write(c: string) { output += c; } }, stdout: { columns: width, rows: viewportRows } });
  const frame = buildFrame(width, viewportRows);
  parseRenderedIntoFrame(output, frame, new StylePool());
  return frame.cells.map((row) => row.map((c) => c.char).join("").trimEnd());
}

describe("PageUp reaches the top of the transcript (U-PageUp)", () => {
  const many = Array.from({ length: 12 }, (_, i) => msg(`m${i}`, `message ${i} a\nmessage ${i} b\nmessage ${i} c`));
  const viewport = 10;
  const width = 60;

  it("the clamp stops one screenful before the end of the estimated transcript, not at its end", () => {
    const total = totalMessageRows(many, width);
    expect(clampRowOffset(99_999, many, viewport, width)).toBe(total - viewport);
    expect(clampRowOffset(0, many, viewport, width)).toBe(0);
    // a transcript shorter than the screen cannot scroll at all
    expect(clampRowOffset(50, many.slice(0, 1), viewport, width)).toBe(0);
  });

  it("at the clamp limit the oldest message follows the 'top' line and the screen is full", () => {
    const lines = renderList(many, clampRowOffset(99_999, many, viewport, width), viewport, width);
    expect(lines[0]).toContain("top of the conversation");
    expect(lines[1]).toBe("message 0 a");
    expect(lines[2]).toBe("message 0 b");
    // the whole viewport shows transcript, no empty band
    expect(lines.filter((l) => l.trim() === "").length).toBe(0);
  });

  it("a request far past the clamp, even one a few rows off the estimate, still shows the top", () => {
    const lines = renderList(many, 99_999, viewport, width);
    expect(lines[1]).toBe("message 0 a");
  });

  it("half way up: bottom-anchored as before, older lines above, newest hidden", () => {
    const lines = renderList(many, 12, viewport, width);
    const text = lines.join("\n");
    expect(text).not.toContain("message 11 a");
    expect(text).toContain("scrolled up 12 rows");
    expect(lines[0]!.trim()).not.toBe("");
  });
});
