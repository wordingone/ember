// homescreen-live-resize.test.ts — b14 item 1: real-OS-window resize reflow.
//
// homescreen-border-clip.test.ts proves the panel renders correctly at a GIVEN width on a FRESH
// mount, but every test there does exactly one mount + one capture -- it never exercises an
// UPDATE (a resize arriving to an ALREADY-MOUNTED session), which is what a live terminal
// resize actually is. A real WT-window harness (SetWindowPos + PrintWindow, not the demoted
// pty.resize() synthetic) proved the live b13.exe binary freezes the "ember" panel at its
// FIRST-EVER width after a genuine OS resize, while the status bar/prompt correctly reflow.
//
// Root cause (traced via targeted instrumentation, all reverted): Homescreen's outer `panel` Box
// has no explicit width -- it relies on width:"auto" + row flexDirection to size itself from
// content (leftCol + rightCol, exactly matching viewportWidth by rightColWidth()'s construction).
// On a live UPDATE (not a fresh mount), the panel's own _layout() call correctly recomputes this
// content-sum width -- but its column-direction ANCESTOR's default cross-align "stretch" then
// OVERWRITES that correct value with the ancestor's own crossSpace (ink/layout-engine.ts's
// _crossAlign, `if (child.width === "auto") child.computedWidth = crossSpace;`), and that
// ancestor's crossSpace is stale after an update. A FRESH mount never surfaces this: the
// ancestor's crossSpace is ALSO freshly correct on a first-ever layout pass, so the stretch
// overwrite coincidentally matches the content-sum result -- only a genuine post-mount UPDATE
// diverges the two, exactly the class of defect the demoted pty.resize() harness (single-shot,
// no persisted-session update) could never catch either.
import { describe, test, expect } from "bun:test";
import React from "react";
import { Homescreen } from "./logo-homescreen.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";

function rightEdgeColumn(rendered: string, cols: number, rows: number): number {
  const frame = buildFrame(cols, rows);
  parseRenderedIntoFrame(rendered, frame, new StylePool());
  for (let r = 0; r < rows; r++) {
    const rowStr = frame.cells[r].map((c) => c?.char ?? " ").join("");
    for (const glyph of ["│", "╮", "╯"]) {
      const idx = rowStr.lastIndexOf(glyph);
      if (idx >= 0) return idx;
    }
  }
  return -1;
}

describe("Homescreen panel width on a LIVE resize (mount, then update -- not a fresh mount)", () => {
  test("panel's right border tracks a widened terminal after an in-session update", () => {
    const rows = 30;
    // A mutable stdout object, exactly like the live app's `get columns() { return
    // process.stdout.columns }` -- render() re-reads it fresh on every call, so mutating it
    // between mount and update simulates a genuine OS-level resize of an already-running session.
    const stdout = { columns: 100, rows };
    let buf = "";
    const stream = { write(s: string) { buf += s; } };

    const handle = mountInk(
      React.createElement(Homescreen, { state: { version: "0.0.0" }, viewportWidth: 100 }),
      { stream, stdout },
    );
    const beforeEdge = rightEdgeColumn(buf, 100, rows);
    expect(beforeEdge).toBe(99); // fresh mount: correct, matches the existing border-clip test

    // Simulate the resize: stdout grows, THEN the app re-renders with the new viewportWidth --
    // exactly repl.ts's 250ms poller calling setColumns() then committing with the new value.
    stdout.columns = 170;
    buf = "";
    handle.update(
      React.createElement(Homescreen, { state: { version: "0.0.0" }, viewportWidth: 170 }),
    );
    const afterEdge = rightEdgeColumn(buf, 170, rows);

    // FAILS before the fix: the panel stays frozen at its first-mount width (99), even though
    // the terminal is now 170 cols wide and every OTHER surface (status bar, prompt) reflows.
    expect(afterEdge).toBe(169);
  });

  test("panel's right border tracks a NARROWED terminal after an in-session update", () => {
    const rows = 30;
    const stdout = { columns: 170, rows };
    let buf = "";
    const stream = { write(s: string) { buf += s; } };

    const handle = mountInk(
      React.createElement(Homescreen, { state: { version: "0.0.0" }, viewportWidth: 170 }),
      { stream, stdout },
    );
    rightEdgeColumn(buf, 170, rows); // fresh-mount baseline, not asserted here

    stdout.columns = 110;
    buf = "";
    handle.update(
      React.createElement(Homescreen, { state: { version: "0.0.0" }, viewportWidth: 110 }),
    );
    const afterEdge = rightEdgeColumn(buf, 110, rows);

    expect(afterEdge).toBe(109);
  });
});
