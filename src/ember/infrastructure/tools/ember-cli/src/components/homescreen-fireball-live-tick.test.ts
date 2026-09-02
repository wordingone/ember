// homescreen-fireball-live-tick.test.ts — b14 item 2 reframe (2026-07-03, team-lead gate verdict):
// the welcome-panel fireball was hardcoded to FIREBALL_IDLE_POSE_FRAME "since this welcome-screen
// render never animates" -- a deliberate design choice. The operator's "the animation looks fine
// when the model is generating, but on the welcome screen it's frozen" complaint IS that design's
// defect: a static frame cannot meet the living-flame bar, so the "by design" comment does not
// survive. This mirrors the bottom-chrome fireball (screens/repl.ts), which already ticks fine off
// its own `fireballTick` state/useInterval -- the fix threads that SAME tick down into Homescreen
// instead of freezing it, so both surfaces animate off one clock and stay one art family.
// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, test, expect } from "bun:test";
import React from "react";
import { Homescreen } from "./logo-homescreen.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";

function mountAndCapture(el: React.ReactElement): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  mountInk(el, { stream, stdout: { columns: 120, rows: 30 } });
  return buf;
}

// Fireball glyphs sit at the panel's top-left corner (rows 1-9, cols 1-9 inside the border).
function fireballCells(
  frame: ReturnType<typeof buildFrame>,
  rows: number,
  pool: StylePool,
): string {
  const lines: string[] = [];
  for (let r = 1; r <= 9 && r < rows; r++) {
    lines.push(frame.cells[r].slice(1, 10).map((cell) => JSON.stringify({
      char: cell?.char ?? " ",
      style: pool.lookup(cell?.styleRef ?? 0),
    })).join("|"));
  }
  return lines.join("\n");
}

describe("Homescreen's welcome-panel fireball tracks a live tick (not frozen at FIREBALL_IDLE_POSE_FRAME)", () => {
  test("passing a different fireballTick prop changes the rendered fireball glyphs", () => {
    const state = { version: "0.0.0" };
    const outAt0 = mountAndCapture(
      React.createElement(Homescreen, { state, viewportWidth: 120, fireballTick: 0 }),
    );
    const outAt1 = mountAndCapture(
      React.createElement(Homescreen, { state, viewportWidth: 120, fireballTick: 1 }),
    );
    // FAILS before the fix: both renders are identical because the tick prop is ignored and the
    // fireball is hardcoded to FIREBALL_IDLE_POSE_FRAME regardless of what's passed in.
    expect(outAt0).not.toBe(outAt1);
  });

  test("a genuine in-session update (mount at tick 0, update to tick 1) also animates the fireball's painted cells", () => {
    const state = { version: "0.0.0" };
    const cols = 120, rows = 30;
    // ONE shared frame + style pool across both parses, accumulating writes exactly like a real
    // terminal (an update's ANSI output is a DIFF -- only the cells that changed are repainted;
    // parsing it into a FRESH empty frame would show mostly-blank cells and falsely look "different"
    // regardless of whether the fireball itself changed).
    const frame = buildFrame(cols, rows);
    const pool  = new StylePool();
    let buf = "";
    const stream = { write(s: string) { buf += s; } };
    const handle = mountInk(
      React.createElement(Homescreen, { state, viewportWidth: 120, fireballTick: 0 }),
      { stream, stdout: { columns: cols, rows } },
    );
    parseRenderedIntoFrame(buf, frame, pool);
    const before = fireballCells(frame, rows, pool);
    buf = "";
    handle.update(React.createElement(Homescreen, { state, viewportWidth: 120, fireballTick: 1 }));
    parseRenderedIntoFrame(buf, frame, pool);
    const after = fireballCells(frame, rows, pool);
    expect(before).not.toBe(after);
  });
});
