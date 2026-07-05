// components/slash-dropdown.test.ts — render tests for the slash-command completion dropdown
// (issue b22 item 1). Mounts the real component via mountInk with a capture stream (the same
// pattern as fireball.test.ts's renderFireballLines tests and scratchpad/bug2-render-capture.test.ts),
// asserting on the actual emitted ANSI text rather than component internals.

import { describe, test, expect } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { SlashDropdown } from "./slash-dropdown.ts";
import type { RegistryCommand } from "../types/command-types.ts";

function cmd(name: string, description: string): RegistryCommand {
  return {
    name,
    description,
    isEnabled: () => true,
    execute: async () => ({ type: "message", message: "" }),
  };
}

function renderToText(el: React.ReactElement): string {
  const chunks: string[] = [];
  const stream = { write(s: string): void { chunks.push(s); } };
  mountInk(el, { stream, stdout: { columns: 80, rows: 24 } });
  return chunks.join("");
}

describe("SlashDropdown", () => {
  test("renders every visible command's name and description", () => {
    const out = renderToText(
      React.createElement(SlashDropdown, {
        commands: [cmd("help", "show available commands"), cmd("model", "switch model")],
        selectedIndex: 0,
        overflowCount: 0,
        width: 80,
      }),
    );
    expect(out).toContain("/help");
    expect(out).toContain("show available commands");
    expect(out).toContain("/model");
    expect(out).toContain("switch model");
  });

  test("the selected row carries the caret marker; other rows do not", () => {
    const out = renderToText(
      React.createElement(SlashDropdown, {
        commands: [cmd("help", "d1"), cmd("model", "d2"), cmd("clear", "d3")],
        selectedIndex: 1,
        overflowCount: 0,
        width: 80,
      }),
    );
    // "❯ /model" -- the selected row's own marker+name pair, contiguous (no unrelated escape
    // codes splitting them, matching how the rest of the chrome writes marker+text runs).
    expect(out).toContain("❯ /model");
    // Neither non-selected row's rendered line contains the caret.
    const lines = out.split("\x1b[");
    const helpLine = lines.find((l) => l.includes("/help"));
    const clearLine = lines.find((l) => l.includes("/clear"));
    expect(helpLine).toBeDefined();
    expect(clearLine).toBeDefined();
    expect(helpLine).not.toContain("❯");
    expect(clearLine).not.toContain("❯");
  });

  test("the selected row's name is rendered in the cyan interaction accent (field-ux-map §9: one accent color, paired with a marker, never color alone)", () => {
    const out = renderToText(
      React.createElement(SlashDropdown, {
        commands: [cmd("help", "d1")],
        selectedIndex: 0,
        overflowCount: 0,
        width: 80,
      }),
    );
    // "cyan" resolves through resolveColor to a truecolor/ANSI escape containing this pattern --
    // assert the escape sequence for cyan is present somewhere before the command name.
    expect(out).toMatch(/\x1b\[[\d;]*36[\d;]*m.*\/help/s);
  });

  test("an overflow count > 0 renders a '+N more' line; zero overflow renders no such line", () => {
    const withOverflow = renderToText(
      React.createElement(SlashDropdown, {
        commands: [cmd("help", "d1")],
        selectedIndex: 0,
        overflowCount: 5,
        width: 80,
      }),
    );
    expect(withOverflow).toContain("+5 more");

    const withoutOverflow = renderToText(
      React.createElement(SlashDropdown, {
        commands: [cmd("help", "d1")],
        selectedIndex: 0,
        overflowCount: 0,
        width: 80,
      }),
    );
    expect(withoutOverflow).not.toContain("more");
  });

  test("renders a thin box-drawing border (round corners, field-ux-map §9: thin borders + negative space, never a heavy frame)", () => {
    const out = renderToText(
      React.createElement(SlashDropdown, {
        commands: [cmd("help", "d1")],
        selectedIndex: 0,
        overflowCount: 0,
        width: 80,
      }),
    );
    // Round-corner box-drawing glyphs (╭ ╮ ╰ ╯) or their straight-edge siblings (─ │) -- whichever
    // the layout engine emits for PANEL_BORDER_STYLE -- must appear; this is a border, not a
    // borderless plain-text list.
    expect(out).toMatch(/[╭╮╰╯─│┌┐└┘]/);
  });

  test("an empty command list renders without throwing (still a valid, bordered, empty panel)", () => {
    expect(() =>
      renderToText(React.createElement(SlashDropdown, { commands: [], selectedIndex: 0, overflowCount: 0, width: 80 })),
    ).not.toThrow();
  });

  // b23: banked wince from the b22 gate -- a description that overflows the available row width
  // must truncate with an ellipsis instead of being hard-clipped by the terminal buffer with no
  // signal anything was cut. /cockpit's real description is the live repro at default width.
  test("a description that overflows the panel width truncates with an ellipsis", () => {
    const longDesc =
      "C-OBS observatory: MONITOR/UNDERSTAND/INTERACT over the real GOAL/ledger/receipts world-state adapter, with click-to-evidence and a confirm-only encounter membrane";
    const out = renderToText(
      React.createElement(SlashDropdown, {
        commands: [cmd("cockpit", longDesc)],
        selectedIndex: 0,
        overflowCount: 0,
        width: 80,
      }),
    );
    expect(out).toContain("…");
    // The full, untruncated description must NOT appear anywhere in the output -- proving this
    // is a real truncation, not an ellipsis appended after rendering the whole string anyway.
    expect(out).not.toContain(longDesc);
  });

  test("a description that comfortably fits the panel width gets NO ellipsis", () => {
    const out = renderToText(
      React.createElement(SlashDropdown, {
        commands: [cmd("help", "short description")],
        selectedIndex: 0,
        overflowCount: 0,
        width: 80,
      }),
    );
    expect(out).toContain("short description");
    expect(out).not.toContain("…");
  });

  test("narrowing the panel width (b14 resize/reflow) truncates a description that fit at a wider width", () => {
    const desc = "a description that fits nicely at eighty";
    const wide = renderToText(
      React.createElement(SlashDropdown, {
        commands: [cmd("help", desc)],
        selectedIndex: 0,
        overflowCount: 0,
        width: 80,
      }),
    );
    const narrow = renderToText(
      React.createElement(SlashDropdown, {
        commands: [cmd("help", desc)],
        selectedIndex: 0,
        overflowCount: 0,
        width: 40,
      }),
    );
    expect(wide).toContain(desc);
    expect(wide).not.toContain("…");
    expect(narrow).toContain("…");
    expect(narrow).not.toContain(desc);
  });
});
