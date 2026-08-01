// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// bottom-anchor.test.ts — B7 item 2 ("kill the void"): the transcript region must anchor its
// content toward the prompt (bottom of the viewport) instead of the top, so a sparse/fresh
// session doesn't leave a huge black field below its content. Mechanism: justifyContent:"flexEnd"
// on the transcript's outer Box (already wired end-to-end -- reconciler.ts copies it, layout-engine
// applies it via `startOffset = relFree` in the flexEnd case) combined with the existing
// overflow:"hidden" clip (B4 W4) for the case where content is now TALLER than the viewport and
// must clip from the TOP (keep the newest/bottom rows, drop the oldest) instead of the reverse.
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

function rowsForText(out: string, needle: string): number[] {
  const re = /\x1b\[(\d+);(\d+)H([^\x1b]*)/g;
  let m: RegExpExecArray | null;
  const found: number[] = [];
  while ((m = re.exec(out))) {
    if (m[3].includes(needle)) found.push(Number(m[1]));
  }
  return found;
}

describe("B7 item 2: transcript region anchors content toward the bottom (prompt side)", () => {
  test("column-reverse places the first child at the bottom and keeps source-order siblings above it", () => {
    const el = React.createElement(
      Box, { flexDirection: "column-reverse", height: 6, overflow: "hidden" },
      React.createElement(Text, { key: "newest" }, "newest"),
      React.createElement(Text, { key: "older" }, "older"),
    );
    const out = mountAndCapture(el, 40, 6);
    const newestRows = rowsForText(out, "newest");
    const olderRows = rowsForText(out, "older");
    expect(newestRows.at(-1)).toBe(6);
    expect(olderRows.at(-1)).toBe(5);
  });
  test("short content sits flush against the bottom of a tall, fixed-height container", () => {
    const totalRows = 20;
    const el = React.createElement(
      Box, { flexDirection: "column", height: totalRows, overflow: "hidden", justifyContent: "flex-end" },
      React.createElement(Text, { key: "a" }, "line-a"),
      React.createElement(Text, { key: "b" }, "line-b"),
      React.createElement(Text, { key: "c" }, "line-c"),
    );
    const out = mountAndCapture(el, 40, totalRows);
    const aRows = rowsForText(out, "line-a");
    const cRows = rowsForText(out, "line-c");
    expect(aRows.length).toBeGreaterThan(0);
    expect(cRows.length).toBeGreaterThan(0);
    // 3 lines anchored to the bottom of a 20-row box: rows 18, 19, 20 (1-indexed).
    expect(aRows[aRows.length - 1]).toBe(totalRows - 2);
    expect(cRows[cRows.length - 1]).toBe(totalRows);
  });

  test("oversized content: flex-end anchoring doesn't break the existing overflow clip (regression guard)", () => {
    // NOTE on scope: this deliberately does NOT assert "the newest rows are what's kept". This
    // engine's shrink pass is single-pass (no re-layout of an already-positioned child after its
    // reported size changes -- see layout-engine.ts's shrink comment), so an oversized child's
    // OWN internal children keep the positions they were given in the first layout pass
    // regardless of justifyContent on the ancestor; which end of an overflowing list survives
    // clipping is governed by render/message order, not by this prop, both before and after this
    // change. That's pre-existing behavior (confirmed identical with flex-start), not a
    // regression this fix introduces, and reopening it is a separate, larger change (either a
    // multi-pass layout re-flow or VirtualMessageList-level data windowing) outside item 2's scope
    // ("kill the void" -- the empty/sparse case covered by the test above). What THIS test
    // guards: adding flex-end must not newly break the clip boundary itself (nothing paints past
    // the container height, and clipping still happens) versus the flex-start baseline.
    //
    // ACCEPTANCE REQUIREMENT for whichever future change closes this gap (team-lead, 2026-07-03):
    // BOTTOM-SURVIVES. In a chat transcript the newest rows are the ones the user is reading right
    // now -- clipping MUST drop the OLDEST rows first and keep the newest ones visible. The b10
    // cockpit frame team-lead captured does the opposite: it keeps the TOP of an oversized
    // transcript and drops the newest content off the bottom, which is backwards for a
    // conversation surface (right for a fixed dashboard/log-head view, wrong here). Whoever lands
    // the multi-pass re-flow or VirtualMessageList windowing must make bottom-survives part of
    // its own acceptance test, not just "clipping still happens somewhere."
    const totalRows = 10;
    const lines = Array.from({ length: 25 }, (_, i) => `row-${i}`);
    const inner = React.createElement(
      Box, { key: "inner", flexDirection: "column" },
      ...lines.map((t, i) => React.createElement(Text, { key: i }, t)),
    );
    const el = React.createElement(
      Box, { flexDirection: "column", height: totalRows, overflow: "hidden", justifyContent: "flex-end" },
      inner,
    );
    const out = mountAndCapture(el, 40, totalRows);
    const re = /\x1b\[(\d+);(\d+)H/g;
    let m: RegExpExecArray | null;
    let maxRow = 0;
    let rowsWritten = 0;
    while ((m = re.exec(out))) { maxRow = Math.max(maxRow, Number(m[1])); rowsWritten++; }
    expect(maxRow).toBeLessThanOrEqual(totalRows);
    expect(rowsWritten).toBe(totalRows); // exactly 10 of the 25 rows survive the clip
  });

  // B7 item 2 re-verification (operator regrade 2026-07-03): the two tests above mounted the
  // transcript Box as a container with an EXPLICIT height, in isolation. The REAL repl.ts always
  // nests it alongside flexShrink:0 siblings (input-wrap, status-wrap) with NO explicit height of
  // its own -- it gets its size from flexGrow:1 + the outer column's shrink pass, exactly like
  // this test's shape. That's a materially different code path (layout-engine.ts's "auto"-height
  // branch: `selfH = this.height === "auto" ? availH : ...`), and it was NOT covered by the tests
  // above -- this test closes that gap.
  test("flex-end still anchors correctly when the container's own height comes from flexGrow/shrink (not an explicit height), alongside real flexShrink:0 siblings", () => {
    const totalRows = 50;
    const child = React.createElement(Text, { key: "child" }, "child-content");
    const el = React.createElement(
      Box, { flexDirection: "column", height: totalRows },
      React.createElement(
        Box, { key: "transcript", flexDirection: "column", flexGrow: 1, overflow: "hidden", justifyContent: "flex-end" },
        React.createElement(Box, { key: "inner", flexDirection: "column", height: 11 }, child),
      ),
      React.createElement(Box, { key: "input-wrap", flexShrink: 0, height: 3 },
        React.createElement(Text, null, "input")),
      React.createElement(Box, { key: "status-wrap", flexShrink: 0, height: 1 },
        React.createElement(Text, null, "status")),
    );
    const out = mountAndCapture(el, 40, totalRows);
    const rows = rowsForText(out, "child-content");
    expect(rows.length).toBeGreaterThan(0);
    // transcript's TRUE available height is totalRows - input-wrap(3) - status-wrap(1) = 46.
    // flex-end anchors an 11-row child to the bottom of THAT 46, so its top row is 46-11+1 = 36
    // (1-indexed) within the transcript, landing at absolute row 36 (transcript starts at row 1).
    expect(rows[0]).toBe(36);
  });
});
