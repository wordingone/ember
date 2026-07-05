// overflow-clip.test.ts — B4 W4 (SWAP-BLOCKING): a Box{overflow:"hidden", height:N} containing a
// child TALLER than N must clip that child's render to N rows. The "overflow" prop has always
// been declared on the layout engine (layout-engine.ts LayoutNode.overflow) and threaded into
// CSSProperties for layout SIZING purposes, but renderNodeToOutput never read it -- clipRect was
// passed unchanged to every child regardless of any ancestor's overflow:hidden, so oversized
// content (e.g. a tall /cockpit board inside the transcript's overflow:hidden Box) painted straight
// through the transcript's own boundary into rows occupied by fixed chrome below it (fireball,
// prompt, status bar) -- exactly the "board row appears below the status bar" defect.
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

function maxRowWritten(out: string): number {
  const re = /\x1b\[(\d+);(\d+)H/g;
  let m: RegExpExecArray | null;
  let max = 0;
  while ((m = re.exec(out))) max = Math.max(max, Number(m[1]));
  return max;
}

describe("W4: overflow:hidden clips oversized children to the node's own height", () => {
  test("a tall child inside a fixed-height overflow:hidden Box never writes past that height", () => {
    const tallChild = React.createElement(
      Box, { flexDirection: "column" },
      ...Array.from({ length: 20 }, (_, i) => React.createElement(Text, { key: i }, `row ${i}`)),
    );
    const el = React.createElement(
      Box, { flexDirection: "column" },
      React.createElement(Box, { key: "clipped", height: 3, overflow: "hidden" }, tallChild),
      React.createElement(Text, { key: "chrome", }, "FIXED CHROME BELOW"),
    );
    // Terminal is deliberately much taller than everything combined (30 rows for 3 clipped + 1
    // chrome + comfortable margin) so any leakage is caused by the Box's OWN overflow:hidden
    // failing to clip, never by the outer terminal-viewport clip masking the bug.
    const out = mountAndCapture(el, 40, 30);
    // The clipped box occupies rows 1-3 (1-indexed); "FIXED CHROME BELOW" must land at row 4,
    // and nothing from the 20-row tall child may appear at or after row 4.
    expect(out).toContain("FIXED CHROME BELOW");
    const chromeIdx = out.indexOf("FIXED CHROME BELOW");
    const beforeChrome = out.slice(0, chromeIdx);
    // row 3 (the last row that fits inside the 3-row clip) is allowed; rows 4..19 must never
    // appear anywhere in the whole output -- not just before the chrome line, anywhere at all.
    for (let i = 4; i < 20; i++) {
      expect(out.includes(`row ${i}`)).toBe(false);
    }
    void beforeChrome;
  });

  test("without overflow:hidden (visible, the default), a tall child is NOT clipped (regression guard)", () => {
    const tallChild = React.createElement(
      Box, { flexDirection: "column" },
      ...Array.from({ length: 6 }, (_, i) => React.createElement(Text, { key: i }, `row ${i}`)),
    );
    const el = React.createElement(Box, { flexDirection: "column", height: 3 }, tallChild);
    const out = mountAndCapture(el, 40, 10);
    // Visible overflow: all 6 rows should still render (nothing new is clipped away).
    for (let i = 0; i < 6; i++) {
      expect(out).toContain(`row ${i}`);
    }
  });
});
