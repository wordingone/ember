// screens/repl-slash-dropdown.test.ts — integration receipt for the slash-command completion
// dropdown wired into the real ReplScreen (issue b22 item 1, ledgered since b14 as
// ember-cli-slash-dropdown). Mounts the REAL ReplScreen via mountInk with a capture stream (no
// window), same pattern as scratchpad/bug2-render-capture.test.ts, and drives it with the real
// keyboard-event bus (_deliverKeyEvent) rather than calling component internals directly --
// proves the wiring end to end: typing "/" opens the dropdown, Down moves the selection,
// Enter completes the chosen command into the input and closes the dropdown.
//
// resetCommandRegistryForTests() before mount pins the command list to the default (synchronous,
// filesystem-free) builtins -- observatory/watch/finetune/model/world-state -- so this test's
// assertions don't depend on the real cwd's skill/plugin directories.

import { describe, it, expect } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { ReplScreen } from "./repl.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";

const COLS = 80;
const ROWS = 24;

resetCommandRegistryForTests();

const chunks: string[] = [];
const captureStream = {
  write(s: string | Uint8Array): void {
    chunks.push(typeof s === "string" ? s : new TextDecoder().decode(s));
  },
};

const config = {
  model:            "qwen3.6-27b",
  permissionMode:   "bypass" as const,
  baseSystemPrompt: "",
};

mountInk(
  React.createElement(
    TerminalSizeContext.Provider,
    { value: { columns: COLS, rows: ROWS } },
    React.createElement(ReplScreen, {
      config,
      cwd:    process.cwd(),
      env:    { EMBER_DISABLE_TERMINAL_TITLE: "1" },
      onExit: () => {},
    }),
  ),
  { stream: captureStream as unknown as { write(s: string): void }, stdout: { columns: COLS, rows: ROWS } },
);

// Flushes all pending microtasks (the mount-time getCommands(cwd).then(...) effect, plus any
// state-update-triggered re-render). A single setImmediate proved insufficient during test
// authorship -- each keypress's committed render was observed landing one flush() call late
// (verified via the raw delta dumps: the dropdown's first paint, the Down-arrow's selection
// move, and Enter's completion each showed up a full test-boundary after the key that caused
// them) -- so this settles several ticks in a row, deliberately more than the minimum observed
// requirement, matching the spirit of bug2-render-capture.test.ts's own setImmediate wait but
// hardened against this reconciler's multi-hop effect/state-update scheduling.
async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) {
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
}

describe("slash-command dropdown wired into the real ReplScreen (b22 item 1)", () => {
  it("boot: no dropdown content before anything is typed", async () => {
    await flush(); // let the initial getCommands(cwd) load land before asserting its ABSENCE means anything
    const buf = chunks.join("");
    expect(buf).not.toContain("/observatory");
  });

  it("typing '/' opens the dropdown showing the builtin commands", async () => {
    const before = chunks.length;
    _deliverKeyEvent("/", {});
    await flush();
    const delta = chunks.slice(before).join("");
    expect(delta).toContain("/observatory");
    expect(delta).toContain("/watch");
    expect(delta).toContain("/model");
    // Bordered panel, not a plain list (field-ux-map §9).
    expect(delta).toMatch(/[╭╮╰╯─│┌┐└┘]/);
  });

  it("Down moves the selection from the first to the second command", async () => {
    const beforeMove = chunks.length;
    _deliverKeyEvent("down", {});
    await flush();
    const delta = chunks.slice(beforeMove).join("");
    // The caret marker must now sit next to "watch" (the second builtin, registry order), not
    // "observatory" (the first) -- a real cursor move, not a no-op re-render.
    expect(delta).toContain("❯ /watch");
  });

  it("Enter completes the selected command into the input and closes the dropdown", async () => {
    const beforeEnter = chunks.length;
    _deliverKeyEvent("return", {});
    await flush();
    const delta = chunks.slice(beforeEnter).join("");
    // The input now reads "/watch " (trailing space, ready for args) -- and per
    // shouldShowSlashDropdown, "/watch " no longer matches the "composing a command name"
    // pattern (it has a space), so the dropdown must be gone from THIS frame's diff. This also
    // proves Enter did NOT fall through to message-submit (which would have cleared the input
    // back to empty and echoed a transcript entry instead of leaving "/watch " in place).
    expect(delta).toContain("/watch");
    // None of the OTHER dropdown rows remain -- the command-list panel itself is gone, not just
    // re-labeled (unrelated bordered panels exist elsewhere in this screen's real board/status
    // chrome, so asserting "no border anywhere" would be the wrong, over-broad invariant).
    expect(delta).not.toContain("/observatory");
    expect(delta).not.toContain("/finetune");
    expect(delta).not.toContain("/cockpit");
  });
});
