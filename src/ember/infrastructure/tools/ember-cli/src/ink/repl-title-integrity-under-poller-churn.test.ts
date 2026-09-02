// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// #1698 acceptance criterion 3: a full-repaint invariant (or equivalent) guarantees no torn
// label survives the next frame. checkFrameGeometry (frame-geometry.ts) is the existing,
// reusable structural checker for exactly this shape of defect: it discovers every bordered
// box from its own corner glyphs and asserts corner-closure/column-purity/no-content-in-
// border-row -- the class of violation a torn title (e.g. the issue's own "HOST MEMORYBGIB",
// "TENERGYE" examples) produces.
//
// Scope note: this test proves Ink's OWN successive rendered frames stay structurally intact
// and title text stays byte-exact across repeated poller-driven re-renders. It cannot, by
// construction, reproduce the terminal-level interleaving the issue describes -- that
// corruption came from a SECOND writer (console.warn) hitting the real process stdout
// alongside Ink's controlled stream, and mountInk's injected stream only ever captures Ink's
// own writes, never a stray console call reaching the real terminal. That exact channel is
// proven RED (pre-fix) and GREEN (post-fix) by
// screens/repl-offline-stdout-bleed.test.ts instead, via a console spy. This test is the
// structural safety net: once that second writer is gone (the fix under test), the only
// remaining writer is Ink itself, and this asserts ITS frames never tear a title across churn.
import { afterEach, describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "./reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "./components.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { ReplScreen } from "../screens/repl.ts";
import { checkFrameGeometry } from "./frame-geometry.ts";

function renderedLines(raw: string, columns: number, rows: number): string[] {
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
}

async function wait(ms: number): Promise<void> {
  await new Promise<void>((resolve) => setTimeout(resolve, ms));
}

describe("panel titles render byte-exact across poller churn (#1698 acceptance 3)", () => {
  let mounted: ReturnType<typeof mountInk> | null = null;

  afterEach(() => {
    mounted?.unmount();
    mounted = null;
  });

  test("frame stays structurally intact and known labels render whole after sustained watcher-poller churn", async () => {
    resetCommandRegistryForTests();
    let raw = "";
    const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
    const columns = 120, rows = 44;
    const element = React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns, rows } },
      React.createElement(ReplScreen, {
        config,
        cwd: process.cwd(),
        env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
        onExit: () => {},
      }),
    );
    mounted = mountInk(element, {
      stream: { write(s: string) { raw += s; } },
      stdout: { columns, rows },
    });

    const before = renderedLines(raw, columns, rows);
    const beforeResult = checkFrameGeometry(before);
    expect(beforeResult.violations).toEqual([]);
    expect(beforeResult.boxes.length).toBeGreaterThan(0);

    // memory-footprint polls at 1s cadence, serving-topology at 5s; this window carries the
    // render through several ticks of the faster poller and at least one of the slower one --
    // the activity feed legitimately grows during this window (poll failures now route there,
    // see repl-offline-stdout-bleed.test.ts), which can reflow panel row positions. Comparing
    // exact box coordinates before/after would therefore false-positive on that legitimate
    // reflow; checking structural well-formedness plus label wholeness at the AFTER snapshot,
    // taken once churn has already happened, avoids that confound while still directly testing
    // "no torn label" during churn.
    await wait(2500);

    const after = renderedLines(raw, columns, rows);
    const afterResult = checkFrameGeometry(after);
    expect(afterResult.violations).toEqual([]);
    expect(afterResult.boxes.length).toBeGreaterThan(0);

    // Known host-telemetry panel titles must render whole, not torn -- exactly the issue's own
    // "HOST MEMORYBGIB", "TENERGYE" examples of what a torn version of these same labels
    // looks like.
    const afterText = after.join("\n");
    expect(afterText).toContain("HOST VRAM GIB");
    expect(afterText).toContain("HOST GPU %");
    expect(afterText).not.toContain("GIBGIB");
    expect(afterText).not.toContain("BGIB");
  });
});
