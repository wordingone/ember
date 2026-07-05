// border-title.test.ts — D4 (mock1 parity): the outer homescreen panel is titled "╭─ ember ─...─╮",
// something no existing Box/border primitive supports (paintBorder only paints a uniform
// perimeter). This adds an optional `borderTitle` prop, embedded in the TOP border edge, so
// Homescreen can compose a titled panel declaratively (Box + borderStyle + borderColor +
// borderTitle) instead of hand-building a raw ANSI string block that duplicates FeedComponent's
// logic.
import { describe, test, expect } from "bun:test";
import React from "react";
import { Box, Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";

function mountAndCapture(el: React.ReactElement, cols = 30, rows = 6): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  return buf;
}

function stripAnsi(s: string): string {
  return s.replace(/\x1b\[[0-9;]*m/g, "");
}

describe("Box borderTitle", () => {
  test("embeds the title text in the top border edge", () => {
    const out = mountAndCapture(
      React.createElement(Box, { borderStyle: "round", borderColor: "red", borderTitle: "ember", width: 20, height: 4 },
        React.createElement(Text, null, "hi"),
      ),
    );
    const plain = stripAnsi(out);
    expect(plain).toContain("ember");
  });

  test("all four corners still paint when a title is present", () => {
    const out = mountAndCapture(
      React.createElement(Box, { borderStyle: "round", borderColor: "red", borderTitle: "ember", width: 20, height: 4 },
        React.createElement(Text, null, "hi"),
      ),
    );
    const plain = stripAnsi(out);
    expect(plain).toContain("╭");
    expect(plain).toContain("╮");
    expect(plain).toContain("╰");
    expect(plain).toContain("╯");
  });

  test("a title longer than the available width does not throw and still paints corners", () => {
    const out = mountAndCapture(
      React.createElement(Box, { borderStyle: "round", borderColor: "red", borderTitle: "a much too long title for this box", width: 10, height: 4 },
        React.createElement(Text, null, "hi"),
      ),
    );
    const plain = stripAnsi(out);
    expect(plain).toContain("╭");
    expect(plain).toContain("╮");
  });

  test("no borderTitle prop -> top edge is a uniform line, unaffected (no regression)", () => {
    const out = mountAndCapture(
      React.createElement(Box, { borderStyle: "round", borderColor: "red", width: 20, height: 4 },
        React.createElement(Text, null, "hi"),
      ),
    );
    const plain = stripAnsi(out);
    expect(plain).toContain("╭");
    expect(plain).toContain("╮");
  });
});
