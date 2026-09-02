// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// screens/repl-command-button-wiring.test.ts — end-to-end proof that a real mouse click on a
// command button drives the real command (#1370).
//
// The chain exercised is the production one, start to finish:
//   raw SGR mouse bytes on stdin -> createSgrMouseDecoder -> hit-test -> Box.onClick
//   -> CommandBarPane's onActivate -> ReplScreen's handleCommandButton -> OperatorInjector
//   -> submitPrompt -> tryDispatchSlashCommand -> the registered command's own execute().
//
// Assertions target EFFECTS — did the registered command actually run, did the composer actually
// receive the prefix, did typed text survive — never "did a handler fire". A handler that fires
// and changes nothing is precisely the defect this wiring exists to remove, and is invisible to
// anything short of an effect-level assertion.

import { describe, expect, test } from "bun:test";
import { EventEmitter } from "node:events";
import readline from "node:readline";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { startStdinBridge } from "../ink/stdin-bridge.ts";
import { resetCommandRegistryForTests, setCommandRegistryDeps } from "../command-registry.ts";
import { startTelemetryWatch } from "../services/telemetry-watch.ts";
import { ReplScreen } from "../screens/repl.ts";
import type { RegistryCommand } from "../types/command-types.ts";

class FakeStdin extends EventEmitter {
  isTTY = true;
  setRawMode(): void {}
  resume(): void {}
  pause(): void {}
}

async function flushRepl(times: number = 5): Promise<void> {
  for (let index = 0; index < times; index++) {
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
}

function renderedLines(raw: string, columns: number, rows: number): string[] {
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
}

function findGlyph(lines: string[], needle: string): { col: number; row: number } | undefined {
  for (let row = 0; row < lines.length; row++) {
    const col = lines[row]!.indexOf(needle);
    if (col >= 0) return { col, row };
  }
  return undefined;
}

/** The command bar's pager as it currently renders: the "+N more" caption, or the compact glyph
 *  it degrades to at narrow widths. Returned as the exact on-screen text so the click lands on the
 *  pager and not on the telemetry pane's own "... N more charts" caption, which shares the pane
 *  with the bar since #1399. */
function pagerNeedle(lines: string[]): string | undefined {
  for (const line of lines) {
    const match = /\+\d+ more/.exec(line);
    if (match) return match[0];
  }
  return lines.some((line) => line.includes("›")) ? "›" : undefined;
}

/** Clicks whatever the pager reads as RIGHT NOW. Re-located on every hop on purpose: the caption
 *  carries the count it is hiding, so it is "+9 more" on one page and "+11 more" on the next — a
 *  needle captured once goes stale the moment the first click lands. */
async function clickPager(harness: Harness): Promise<boolean> {
  const needle = pagerNeedle(harness.lines());
  return needle === undefined ? false : harness.click(needle);
}

/** One SGR left-button-press sequence for a zero-based (col, row) terminal cell. */
function sgrLeftClick(col: number, row: number): string {
  return `\x1b[<0;${col + 1};${row + 1}M`;
}

const COLUMNS = 100;
const ROWS = 30;

interface Harness {
  stdin: FakeStdin;
  lines: () => string[];
  waitFor: (predicate: (lines: string[]) => boolean, attempts?: number) => Promise<boolean>;
  click: (needle: string) => Promise<boolean>;
  stop: () => void;
}

function mountRepl(columns: number = COLUMNS, rows: number = ROWS): Harness {
  let raw = "";
  const element = React.createElement(
    TerminalSizeContext.Provider,
    { value: { columns, rows } },
    React.createElement(ReplScreen, {
      config: { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" },
      cwd: process.cwd(),
      env: {
        EMBER_DISABLE_TERMINAL_TITLE: "1",
        EMBER_DISABLE_VIRTUAL_SCROLL: "1",
      },
      onExit: () => {},
    }),
  );
  const handle = mountInk(element, {
    stream: { write(chunk: string) { raw += chunk; } },
    stdout: { columns, rows },
  });
  const stdin = new FakeStdin();
  // The REAL readline keypress emitter, not a stub: the focus-preservation test below has to
  // deliver actual typing through the same bridge the click travels on, and a stubbed emitter
  // silently swallows every keystroke.
  const stopBridge = startStdinBridge({
    stdin: stdin as never,
    emitKeypressEvents: (stream) => readline.emitKeypressEvents(stream),
  });
  const lines = () => renderedLines(raw, columns, rows);
  const waitFor = async (predicate: (l: string[]) => boolean, attempts = 40): Promise<boolean> => {
    for (let attempt = 0; attempt < attempts; attempt++) {
      await new Promise<void>((resolve) => setTimeout(resolve, 50));
      await flushRepl();
      if (predicate(lines())) return true;
    }
    return false;
  };
  return {
    stdin,
    lines,
    waitFor,
    click: async (needle: string) => {
      const found = await waitFor((l) => findGlyph(l, needle) !== undefined);
      if (!found) return false;
      const at = findGlyph(lines(), needle)!;
      // Click the middle of the label rather than its first cell, so the assertion cannot pass
      // on a one-column-off hit box.
      stdin.emit("data", Buffer.from(sgrLeftClick(at.col + Math.floor(needle.length / 2), at.row)));
      await flushRepl();
      return true;
    },
    stop: () => { stopBridge(); handle.unmount(); },
  };
}

function registerCommands(commands: RegistryCommand[]): void {
  resetCommandRegistryForTests();
  setCommandRegistryDeps({ getBuiltinCommands: () => commands });
}

describe("command-button click drives the real registered command", () => {
  test("clicking an argument-free command's button runs that command and renders its result", async () => {
    const ran: string[] = [];
    registerCommands([
      {
        name: "probeone",
        description: "test probe command",
        isEnabled: () => true,
        execute: async (args: string) => {
          ran.push(args);
          return { type: "message" as const, message: "PROBEONE-EXECUTED" };
        },
      },
    ]);
    startTelemetryWatch().stop();
    const harness = mountRepl();
    try {
      expect(await harness.click("[probeone]")).toBe(true);
      const rendered = await harness.waitFor((l) => l.some((line) => line.includes("PROBEONE-EXECUTED")));
      expect(rendered).toBe(true);
      // The command really ran, once, with empty arguments — not a handler that fired into a void.
      expect(ran).toEqual([""]);
    } finally {
      harness.stop();
      startTelemetryWatch().stop();
      resetCommandRegistryForTests();
    }
  }, 20000);

  test("clicking a command that requires arguments composes it and dispatches nothing", async () => {
    const ran: string[] = [];
    registerCommands([
      {
        name: "needsargs",
        description: "test command with required arguments",
        argumentHint: "--target <path>",
        isEnabled: () => true,
        execute: async (args: string) => {
          ran.push(args);
          return { type: "message" as const, message: "NEEDSARGS-EXECUTED" };
        },
      },
    ]);
    startTelemetryWatch().stop();
    const harness = mountRepl();
    try {
      expect(await harness.click("[needsargs]")).toBe(true);
      // The composer receives the prefix and the usage line is surfaced. The match deliberately
      // EXCLUDES the button's own "[needsargs]" label, which would otherwise satisfy a naive
      // substring search whether or not the composer was ever touched.
      // The slash spelling now appears ONLY in the composer and the usage line — the button's own
      // label lost it in #1399 — so a bare "/needsargs" match can no longer be satisfied by the
      // button itself. The label exclusion is kept anyway: it costs nothing and states the intent.
      const composed = await harness.waitFor((l) =>
        l.some((line) => line.includes("/needsargs") && !line.includes("[needsargs]")),
      );
      expect(composed).toBe(true);
      const usageShown = await harness.waitFor((l) =>
        l.some((line) => line.includes("--target <path>")),
      );
      expect(usageShown).toBe(true);
      // ... and NOTHING was dispatched: a blind invocation that could only be a usage error.
      expect(ran).toEqual([]);
      expect(harness.lines().some((line) => line.includes("NEEDSARGS-EXECUTED"))).toBe(false);
    } finally {
      harness.stop();
      startTelemetryWatch().stop();
      resetCommandRegistryForTests();
    }
  }, 20000);

  test("clicking a disabled command surfaces its reason and runs nothing", async () => {
    const ran: string[] = [];
    registerCommands([
      {
        name: "offlinecmd",
        description: "test command that is unavailable",
        isEnabled: () => false,
        execute: async (args: string) => {
          ran.push(args);
          return { type: "message" as const, message: "OFFLINECMD-EXECUTED" };
        },
      },
      {
        name: "probeone",
        description: "test probe command",
        isEnabled: () => true,
        execute: async () => ({ type: "message" as const, message: "PROBEONE-EXECUTED" }),
      },
    ]);
    startTelemetryWatch().stop();
    const harness = mountRepl();
    try {
      expect(await harness.click("[offlinecmd]")).toBe(true);
      const reasonShown = await harness.waitFor((l) =>
        l.some((line) => line.includes("/offlinecmd is not available")),
      );
      expect(reasonShown).toBe(true);
      expect(ran).toEqual([]);
    } finally {
      harness.stop();
      startTelemetryWatch().stop();
      resetCommandRegistryForTests();
    }
  }, 20000);

  test("a click never steals typing focus: text typed before the click survives it", async () => {
    const ran: string[] = [];
    registerCommands([
      {
        name: "probeone",
        description: "test probe command",
        isEnabled: () => true,
        execute: async (args: string) => {
          ran.push(args);
          return { type: "message" as const, message: "PROBEONE-EXECUTED" };
        },
      },
    ]);
    startTelemetryWatch().stop();
    const harness = mountRepl();
    try {
      // Type into the composer first, then click a button.
      await harness.waitFor((l) => findGlyph(l, "[probeone]") !== undefined);
      harness.stdin.emit("data", Buffer.from("halftyped"));
      const typed = await harness.waitFor((l) => l.some((line) => line.includes("halftyped")));
      expect(typed).toBe(true);

      expect(await harness.click("[probeone]")).toBe(true);
      await flushRepl(20);
      await new Promise<void>((resolve) => setTimeout(resolve, 200));

      // The half-typed text is still in the composer — the click was queued behind it rather
      // than injected over it, and the keyboard still owns the composer.
      expect(harness.lines().some((line) => line.includes("halftyped"))).toBe(true);

      // Typing continues to land in the composer after the click.
      harness.stdin.emit("data", Buffer.from("XZ"));
      const stillTyping = await harness.waitFor((l) =>
        l.some((line) => line.includes("halftypedXZ")),
      );
      expect(stillTyping).toBe(true);
    } finally {
      harness.stop();
      startTelemetryWatch().stop();
      resetCommandRegistryForTests();
    }
  }, 20000);
});

describe("paging reaches the commands the bar has no room to show", () => {
  /** A registry deliberately larger than an 80-column bar can hold in its row budget. */
  function crowdedRegistry(): RegistryCommand[] {
    return ["alphacmd", "bravocmd", "charliecmd", "deltacmd", "echocmd", "foxtrotcmd",
      "golfcmd", "hotelcmd", "indiacmd", "juliettcmd", "kilocmd", "limacmd"].map((name) => ({
      name,
      description: `${name} description`,
      isEnabled: () => true,
      execute: async () => ({ type: "message" as const, message: `${name.toUpperCase()}-EXECUTED` }),
    }));
  }

  test("at 80x24 a command with no button on the first page is reached by clicking the pager", async () => {
    const registry = crowdedRegistry();
    registerCommands(registry);
    startTelemetryWatch().stop();
    const harness = mountRepl(80, 24);
    try {
      // Find a command the first page genuinely cannot show — the review's exact failure mode.
      await harness.waitFor((l) => findGlyph(l, "[alphacmd]") !== undefined);
      const firstPage = harness.lines().join("\n");
      const hidden = registry.map((c) => c.name).filter((name) => !firstPage.includes(`[${name}]`));
      expect(hidden.length).toBeGreaterThan(0);

      // The pager is on screen, and it is a real click target rather than a caption. Matched by
      // its own "+N more" shape: since #1399 the bar shares the live-run pane with the charts'
      // "... N more charts" caption, and a bare " more" search hits that caption instead.
      expect(pagerNeedle(harness.lines())).toBeDefined();
      expect(await clickPager(harness)).toBe(true);

      // Page forward until the hidden command has a button, then click THAT button and prove the
      // command really ran. Bounded by the registry size: paging that never arrives is a failure.
      let reached = false;
      for (let hop = 0; hop < registry.length && !reached; hop++) {
        if (await harness.waitFor((l) => findGlyph(l, `[${hidden[0]}]`) !== undefined, 4)) {
          reached = true;
          break;
        }
        await clickPager(harness);
      }
      expect(reached).toBe(true);
      expect(await harness.click(`[${hidden[0]}]`)).toBe(true);
      const ran = await harness.waitFor((l) =>
        l.some((line) => line.includes(`${hidden[0]!.toUpperCase()}-EXECUTED`)),
      );
      expect(ran).toBe(true);
    } finally {
      harness.stop();
      startTelemetryWatch().stop();
      resetCommandRegistryForTests();
    }
  }, 40000);

  test("at 40x24 — the narrowest cockpit — every command is still reachable by paging", async () => {
    const registry = crowdedRegistry();
    registerCommands(registry);
    startTelemetryWatch().stop();
    const harness = mountRepl(40, 24);
    try {
      await harness.waitFor((l) => findGlyph(l, "[alphacmd]") !== undefined);
      const seen = new Set<string>();
      expect(pagerNeedle(harness.lines())).toBeDefined();
      // One full cycle of the pager must expose the whole registry; the loop is bounded so a
      // pager that silently stops advancing fails rather than hangs.
      for (let hop = 0; hop < registry.length * 2 && seen.size < registry.length; hop++) {
        for (const command of registry) {
          if (findGlyph(harness.lines(), `[${command.name}]`)) seen.add(command.name);
        }
        await clickPager(harness);
        await harness.waitFor(() => true, 2);
      }
      expect([...seen].sort()).toEqual(registry.map((c) => c.name).sort());
    } finally {
      harness.stop();
      startTelemetryWatch().stop();
      resetCommandRegistryForTests();
    }
  }, 40000);
});

describe("the notice row clears instead of going stale", () => {
  test("a rejected command's reason disappears as soon as the operator types", async () => {
    registerCommands([
      {
        name: "offlinecmd",
        description: "test command that is unavailable",
        isEnabled: () => false,
        execute: async () => ({ type: "message" as const, message: "OFFLINECMD-EXECUTED" }),
      },
    ]);
    startTelemetryWatch().stop();
    const harness = mountRepl();
    try {
      expect(await harness.click("[offlinecmd]")).toBe(true);
      expect(await harness.waitFor((l) => l.some((line) => line.includes("is not available")))).toBe(true);

      // A single ordinary keystroke — no slash, so the palette never opens and cannot be what
      // removes the row.
      harness.stdin.emit("data", Buffer.from("z"));
      const cleared = await harness.waitFor((l) => !l.some((line) => line.includes("is not available")));
      expect(cleared).toBe(true);
      // ...and the keystroke landed in the composer: the clear costs no typing.
      expect(harness.lines().some((line) => line.includes("z"))).toBe(true);
    } finally {
      harness.stop();
      startTelemetryWatch().stop();
      resetCommandRegistryForTests();
    }
  }, 20000);

  test("a usage line does not survive the submit it was describing", async () => {
    registerCommands([
      {
        name: "needsargs",
        description: "test command with required arguments",
        argumentHint: "--target <path>",
        isEnabled: () => true,
        execute: async () => ({ type: "message" as const, message: "NEEDSARGS-EXECUTED" }),
      },
    ]);
    startTelemetryWatch().stop();
    const harness = mountRepl();
    try {
      expect(await harness.click("[needsargs]")).toBe(true);
      expect(await harness.waitFor((l) => l.some((line) => line.includes("--target <path>")))).toBe(true);

      // Submit the prefilled composer. Its trailing space closes the palette, so Enter really is
      // a submit and not a palette completion.
      harness.stdin.emit("data", Buffer.from("\r"));
      const cleared = await harness.waitFor((l) => !l.some((line) => line.includes("--target <path>")));
      expect(cleared).toBe(true);
    } finally {
      harness.stop();
      startTelemetryWatch().stop();
      resetCommandRegistryForTests();
    }
  }, 20000);
});
