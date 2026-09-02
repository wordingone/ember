// border-rendering.test.ts — B2 (border rendering increment). Written BEFORE any implementation
// change (TDD red-first): a Box{borderStyle} currently renders NOTHING for its border (confirmed
// by team-lead's independent diagnosis: components.ts only drops borderStyle/borderColor into
// data-attrs; nothing downstream reads them). This test mounts real Box/Text elements through the
// FULL live pipeline (reconciler -> layout-engine -> rendering-pipeline), the same path every
// call site in the app uses, so a pass here means every one of the ~29 existing borderStyle call
// sites gets a real border with zero code changes at those sites.

import { describe, test, expect } from "bun:test";
import React from "react";
import { Box, Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";

function mountAndCapture(el: React.ReactElement, cols = 20, rows = 10): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: cols, rows } });
  return buf;
}

describe("Box borderStyle -- real perimeter painted end-to-end", () => {
  test("round border paints the four corner glyphs somewhere in the output", () => {
    const out = mountAndCapture(
      React.createElement(Box, { borderStyle: "round", width: 10, height: 4 },
        React.createElement(Text, null, "hi"),
      ),
    );
    expect(out).toContain("╭");
    expect(out).toContain("╮");
    expect(out).toContain("╰");
    expect(out).toContain("╯");
  });

  test("single border paints straight corners, not round ones", () => {
    const out = mountAndCapture(
      React.createElement(Box, { borderStyle: "single", width: 10, height: 4 },
        React.createElement(Text, null, "hi"),
      ),
    );
    expect(out).toContain("┌");
    expect(out).toContain("┐");
    expect(out).toContain("└");
    expect(out).toContain("┘");
    expect(out).not.toContain("╭");
  });

  test("a Box with no borderStyle paints no border glyphs (regression guard)", () => {
    const out = mountAndCapture(
      React.createElement(Box, { width: 10, height: 4 },
        React.createElement(Text, null, "hi"),
      ),
    );
    expect(out).not.toContain("╭");
    expect(out).not.toContain("┌");
  });

  test("borderColor applies an SGR sequence, not just a bare glyph", () => {
    const out = mountAndCapture(
      React.createElement(Box, { borderStyle: "single", borderColor: "red", width: 10, height: 4 },
        React.createElement(Text, null, "hi"),
      ),
    );
    // Red maps to a named-color SGR code (31) somewhere before the border glyph.
    expect(out).toMatch(/\x1b\[[0-9;]*31[0-9;]*m[^]*┌/);
  });

  test("the top-left corner is painted at the box's own origin, not the terminal origin", () => {
    // A Box nested inside a column Box with a header line above it should have its border
    // start on the SECOND terminal row, not row 1 -- proves position comes from layout, not
    // a hardcoded (0,0).
    const out = mountAndCapture(
      React.createElement(Box, { flexDirection: "column" },
        React.createElement(Text, null, "header"),
        React.createElement(Box, { borderStyle: "single", width: 10, height: 3 },
          React.createElement(Text, null, "hi"),
        ),
      ),
    );
    expect(out).not.toContain("\x1b[1;1H┌");
    expect(out).toContain("\x1b[2;1H┌");
  });

  test("children are inset by exactly 1 cell on each side -- content never overwrites the border column", () => {
    // Fill the box with a single wide char that would collide with the right border column if
    // the layout engine failed to reserve 1 cell per side.
    const out = mountAndCapture(
      React.createElement(Box, { borderStyle: "single", width: 6, height: 3 },
        React.createElement(Text, null, "XXXX"),
      ),
    );
    // Width 6 = 1 border + 4 content + 1 border. The optimizer merges the whole first-paint row
    // into one contiguous run, so assert on the row's literal content rather than a per-char
    // cursor escape: exactly 4 X's must sit between the two vertical border glyphs -- not 3
    // (clipped) and not 5 (border overwritten).
    expect(out).toContain("│XXXX│");
    expect(out).not.toContain("│XXX│");
    expect(out).not.toContain("XXXXX");
  });

  test("EMBER_ASCII=1 degrades every border style to the plain ASCII set", () => {
    const prev = process.env["EMBER_ASCII"];
    process.env["EMBER_ASCII"] = "1";
    try {
      const out = mountAndCapture(
        React.createElement(Box, { borderStyle: "round", width: 10, height: 4 },
          React.createElement(Text, null, "hi"),
        ),
      );
      expect(out).toContain("+");
      expect(out).not.toContain("╭");
      expect(out).not.toContain("┌");
    } finally {
      if (prev === undefined) delete process.env["EMBER_ASCII"];
      else process.env["EMBER_ASCII"] = prev;
    }
  });

  test("double, bold, singleDouble, doubleSingle, and classic all paint distinct corner sets", () => {
    const styles = ["double", "bold", "singleDouble", "doubleSingle", "classic"] as const;
    const corners: Record<string, string> = {};
    for (const s of styles) {
      corners[s] = mountAndCapture(
        React.createElement(Box, { borderStyle: s, width: 8, height: 3 },
          React.createElement(Text, null, "x"),
        ),
      );
    }
    // No two styles should be byte-identical -- each has its own glyph set.
    const seen = new Set<string>();
    for (const s of styles) {
      expect(seen.has(corners[s]!)).toBe(false);
      seen.add(corners[s]!);
    }
    expect(corners["classic"]).toContain("+");
  });
});
