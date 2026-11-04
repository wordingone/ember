// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2381 U-50x16: at 50x16 the live-run pane took half the window and left the conversation 25
// cells. Below OPERATOR_SURFACE_MIN_COLUMNS the pane is not drawn and the conversation gets the
// whole width; at normal widths the layout is unchanged.
import { afterEach, describe, expect, test } from "bun:test";
import React from "react";
import { mountInk, type MountHandle } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { OPERATOR_SURFACE_MIN_COLUMNS, operatorSurfaceWidth, ReplScreen } from "../screens/repl.ts";

let handle: MountHandle | undefined;
afterEach(() => { handle?.unmount(); handle = undefined; });
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const noMods = { ctrl: false, alt: false, shift: false, meta: false };

async function mountAt(columns: number, rows: number): Promise<() => string[]> {
  resetCommandRegistryForTests();
  let raw = "";
  handle = mountInk(
    React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns, rows } },
      React.createElement(ReplScreen, {
        config: { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" },
        cwd: process.cwd(),
        env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
        onExit: () => {},
      }),
    ),
    { stream: { write(s: string) { raw += s; return true; } }, stdout: { columns, rows } },
  );
  await sleep(300);
  return () => {
    const frame = buildFrame(columns, rows);
    parseRenderedIntoFrame(raw, frame, new StylePool());
    return frame.cells.map((row) => row.map((c) => c.char).join("").trimEnd());
  };
}

describe("operatorSurfaceWidth at narrow sizes", () => {
  test("hidden below the minimum, bounded above it, unchanged at the sizes already pinned", () => {
    expect(operatorSurfaceWidth(50)).toBe(0);
    expect(operatorSurfaceWidth(OPERATOR_SURFACE_MIN_COLUMNS - 1)).toBe(0);
    expect(operatorSurfaceWidth(OPERATOR_SURFACE_MIN_COLUMNS)).toBeGreaterThan(0);
    // the conversation keeps a usable column wherever the pane is drawn
    for (let c = OPERATOR_SURFACE_MIN_COLUMNS; c <= 300; c++) {
      expect(c - operatorSurfaceWidth(c)).toBeGreaterThanOrEqual(32);
    }
    expect(operatorSurfaceWidth(80)).toBe(33);
    expect(operatorSurfaceWidth(120)).toBe(50);
    expect(operatorSurfaceWidth(240)).toBe(100);
  });
});

describe("REPL layout at 50x16 (#2381 U-50x16)", () => {
  test("no live-run pane; the conversation and the prompt span the whole width", async () => {
    const read = await mountAt(50, 16);
    const lines = read();
    expect(lines.join("\n")).not.toContain("LIVE RUN");
    expect(lines.join("\n")).not.toContain("SELECT PROCESS");
    // the welcome card and the prompt box both end on the last column
    const tops = lines.filter((l) => l.startsWith("╭"));
    expect(tops.length).toBe(2);
    for (const t of tops) expect(t.indexOf("╮")).toBe(49);
    for (const l of lines) expect(l.length).toBeLessThanOrEqual(50);
  });

  test("Tab does not move focus into a pane that is not there: the next key still types", async () => {
    const read = await mountAt(50, 16);
    _deliverKeyEvent("tab", noMods);
    await sleep(50);
    _deliverKeyEvent("h", noMods);
    _deliverKeyEvent("i", noMods);
    await sleep(100);
    expect(read().some((l) => l.startsWith("│ ❯ hi"))).toBe(true);
  });

  test("at 80x24 the pane is still there", async () => {
    const read = await mountAt(80, 24);
    expect(read().join("\n")).toContain("LIVE RUN");
  });
});
