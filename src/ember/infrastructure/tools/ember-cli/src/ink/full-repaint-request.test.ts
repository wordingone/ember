// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2380 S41: after /clear and a turn the screen kept stale cells; there was no way to force a
// clean repaint. requestFullRepaint() makes the renderer clear the screen and write every cell
// again; Ctrl+L calls it from the REPL, and /clear arms it for the next frame.
import { afterEach, describe, expect, test } from "bun:test";
import React from "react";
import { Text, TerminalSizeContext } from "./components.ts";
import { _deliverKeyEvent, requestFullRepaint } from "./hooks.ts";
import { mountInk, type MountHandle } from "./reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "./rendering-pipeline.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { ReplScreen } from "../screens/repl.ts";

const CLEAR_SCREEN = "\x1b[2J";
let handle: MountHandle | undefined;
afterEach(() => { handle?.unmount(); handle = undefined; });
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const noMods = { ctrl: false, alt: false, shift: false, meta: false };

function mount(element: React.ReactElement, columns = 40, rows = 8) {
  const chunks: string[] = [];
  handle = mountInk(element, { stream: { write(s: string) { chunks.push(s); return true; } }, stdout: { columns, rows } });
  return {
    chunks,
    /** everything written since the last call */
    take(): string { const s = chunks.join(""); chunks.length = 0; return s; },
  };
}
function lines(raw: string, columns: number, rows: number): string[] {
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((row) => row.map((c) => c.char).join("").trimEnd());
}

describe("requestFullRepaint", () => {
  test("nothing mounted: reports false and does nothing", () => {
    expect(requestFullRepaint()).toBe(false);
  });

  test("immediate: clears the screen and writes the whole frame again, unchanged content included", () => {
    const out = mount(React.createElement(Text, null, "stable text"));
    out.take();
    // an ordinary re-render of the same tree writes nothing it does not need to
    expect(requestFullRepaint(false)).toBe(true);
    expect(out.take()).toBe("");

    expect(requestFullRepaint()).toBe(true);
    const repaint = out.take();
    expect(repaint).toContain(CLEAR_SCREEN);
    expect(lines(repaint, 40, 8)[0]).toBe("stable text");
  });

  test("the repaint happens once: the next ordinary commit is a diff again", () => {
    const out = mount(React.createElement(Text, null, "one"));
    out.take();
    requestFullRepaint();
    expect(out.take()).toContain(CLEAR_SCREEN);
    handle!.update(React.createElement(Text, null, "two"));
    const next = out.take();
    expect(next).not.toContain(CLEAR_SCREEN);
    expect(next).toContain("two");
  });

  test("deferred (immediate = false): the next commit carries the full repaint", () => {
    const out = mount(React.createElement(Text, null, "before"));
    out.take();
    requestFullRepaint(false);
    expect(out.take()).toBe("");
    handle!.update(React.createElement(Text, null, "after"));
    const frame = out.take();
    expect(frame).toContain(CLEAR_SCREEN);
    expect(lines(frame, 40, 8)[0]).toBe("after");
  });

  test("after unmount the request is dropped", () => {
    mount(React.createElement(Text, null, "x"));
    handle!.unmount();
    handle = undefined;
    expect(requestFullRepaint()).toBe(false);
  });
});

describe("Ctrl+L in the REPL", () => {
  test("clears the screen and repaints the whole chat; plain 'l' does not", async () => {
    resetCommandRegistryForTests();
    const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
    const out = mount(
      React.createElement(
        TerminalSizeContext.Provider,
        { value: { columns: 100, rows: 30 } },
        React.createElement(ReplScreen, {
          config,
          cwd: process.cwd(),
          env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
          onExit: () => {},
        }),
      ),
      100, 30,
    );
    await sleep(300);
    out.take();

    _deliverKeyEvent("l", noMods);
    await sleep(50);
    expect(out.take()).not.toContain(CLEAR_SCREEN);

    _deliverKeyEvent("l", { ...noMods, ctrl: true });
    await sleep(50);
    const repaint = out.take();
    expect(repaint).toContain(CLEAR_SCREEN);
    // a whole screen, not a patch: the prompt row and the welcome card are both in it
    const text = lines(repaint, 100, 30).join("\n");
    expect(text).toContain("ember");
    expect(text.split("\n").filter((l) => l.trim() !== "").length).toBeGreaterThan(5);
  }, 15_000);
});
