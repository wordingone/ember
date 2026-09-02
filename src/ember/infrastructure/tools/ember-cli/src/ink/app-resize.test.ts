// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// app-resize.test.ts — B7 item 3 investigation (team-lead's resize-reflow hypothesis, 2026-07-03).
// Operator resized his live window after launch; team-lead's capture shows the welcome panel's
// border sitting at ~63% of the window width, consistent with the tree having rendered at
// LAUNCH-time dimensions and never reflowing. This tests App's actual resize mechanism end to end:
// does a real 'resize' event (or, since Bun-compiled binaries under ConPTY don't reliably emit
// it, the 250ms poller fallback -- see components.ts's App comment) actually reach a re-render
// that a CONSUMER of TerminalSizeContext sees, or does the state update happen but never commit?
//
// Written as a real .test.ts file under src/ (not a scratchpad script) specifically because src/
// has its own nested node_modules/react, separate from the repo root -- a scratchpad script
// importing "react" directly resolves a DIFFERENT React instance than components.ts's internal
// hooks use, which throws "invalid hook call" the moment a hook-using consumer is rendered. Inside
// src/, module resolution is consistent and this actually works.
//
// VERIFICATION METHOD NOTE: reads back the accumulated raw ANSI output through the PRODUCTION
// frame parser (buildFrame/parseRenderedIntoFrame), not a raw-byte regex. A first draft of this
// test used `/SIZE=\d+x\d+/g` directly against the accumulated write buffer and got a FALSE
// NEGATIVE: the diff-based repaint pipeline only re-emits the CHANGED cells on a re-render (a
// cursor-jump + the new digits), not the whole "SIZE=..." string every frame, so the literal
// substring "SIZE=170x71" never appears contiguously in the raw byte stream even though the
// terminal's true final state is correct. Same class of self-inflicted false lead as the earlier
// item-3 layout investigation this session -- the frame parser is the only trustworthy readback.
import { describe, test, expect, afterEach } from "bun:test";
import React from "react";
import { App, Text, TerminalSizeContext } from "./components.ts";
import { mountInk } from "./reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "./rendering-pipeline.ts";

function Reporter(): React.ReactElement {
  const { columns, rows } = React.useContext(TerminalSizeContext);
  return React.createElement(Text, null, `SIZE=${columns}x${rows}`);
}

function readLine0(raw: string, cols: number, rows: number): string {
  const frame = buildFrame(cols, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells[0]!.map((c) => c?.char ?? " ").join("").replace(/\s+$/, "");
}

const origColumns = process.stdout.columns;
const origRows    = process.stdout.rows;

afterEach(() => {
  // Restore -- these tests mutate the GLOBAL process.stdout dimensions (App reads them directly,
  // not whatever stream/stdout object was passed to mountInk), so leaking a mutated value would
  // affect any later test in the same process that also reads process.stdout.columns/rows.
  Object.defineProperty(process.stdout, "columns", { value: origColumns, configurable: true });
  Object.defineProperty(process.stdout, "rows",    { value: origRows,    configurable: true });
});

describe("App — terminal resize reflow (B7 item 3 investigation)", () => {
  test("a real 'resize' event on process.stdout updates TerminalSizeContext and a consumer re-renders with the new size", async () => {
    Object.defineProperty(process.stdout, "columns", { value: 80, configurable: true });
    Object.defineProperty(process.stdout, "rows",    { value: 24, configurable: true });

    let raw = "";
    const stream = { write(s: string) { raw += s; } };
    const el = React.createElement(App, null, React.createElement(Reporter));
    mountInk(el, { stream, stdout: { columns: 80, rows: 24 } });

    expect(readLine0(raw, 80, 24)).toBe("SIZE=80x24");

    Object.defineProperty(process.stdout, "columns", { value: 170, configurable: true });
    Object.defineProperty(process.stdout, "rows",    { value: 71,  configurable: true });
    process.stdout.emit("resize");

    // Give the reconciler's scheduler a couple of turns to flush the resulting setState -- this
    // custom host config schedules via setTimeout/queueMicrotask (reconciler.ts), which needs a
    // real event-loop turn, not just a synchronous return.
    await new Promise((r) => setTimeout(r, 20));

    expect(readLine0(raw, 170, 71)).toBe("SIZE=170x71");
  });

  test("when 'resize' does NOT fire (the ConPTY/compiled-binary failure mode this poller exists for), the 250ms poller fallback still picks up the new size", async () => {
    Object.defineProperty(process.stdout, "columns", { value: 100, configurable: true });
    Object.defineProperty(process.stdout, "rows",    { value: 32,  configurable: true });

    let raw = "";
    const stream = { write(s: string) { raw += s; } };
    const el = React.createElement(App, null, React.createElement(Reporter));
    mountInk(el, { stream, stdout: { columns: 100, rows: 32 } });

    expect(readLine0(raw, 100, 32)).toBe("SIZE=100x32");

    // Change the dimensions WITHOUT emitting 'resize' -- simulates the documented ConPTY gap.
    Object.defineProperty(process.stdout, "columns", { value: 130, configurable: true });
    Object.defineProperty(process.stdout, "rows",    { value: 45,  configurable: true });

    // Poller fires every 250ms (components.ts's App); wait past one full interval.
    await new Promise((r) => setTimeout(r, 300));

    expect(readLine0(raw, 130, 45)).toBe("SIZE=130x45");
  });

  test("#159 resize storm reaches the final tiny viewport without throwing or freezing stale dimensions", async () => {
    Object.defineProperty(process.stdout, "columns", { value: 80, configurable: true });
    Object.defineProperty(process.stdout, "rows", { value: 24, configurable: true });

    let raw = "";
    const stream = { write(s: string) { raw += s; } };
    const handle = mountInk(
      React.createElement(App, null, React.createElement(Reporter)),
      { stream, stdout: { columns: 80, rows: 24 } },
    );

    try {
      for (let index = 0; index < 100; index += 1) {
        const columns = 8 + (index % 73);
        const rows = 4 + (index % 29);
        Object.defineProperty(process.stdout, "columns", {
          value: columns,
          configurable: true,
        });
        Object.defineProperty(process.stdout, "rows", { value: rows, configurable: true });
        process.stdout.emit("resize");
      }
      await new Promise((resolvePromise) => setTimeout(resolvePromise, 30));
      expect(readLine0(raw, 34, 16)).toBe("SIZE=34x16");
    } finally {
      handle.unmount();
    }
  });
});
