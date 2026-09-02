// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// screens/width-sweep-probe.test.ts — issue #1370 acceptance #6, executed rather than asserted:
// every command in the LIVE registry is reachable BY MOUSE at every terminal size the cockpit is
// used at.
//
// The first cut of #1370 passed every unit test and still failed this: at 80x24 seven of the
// fourteen builtins had no button, and the `+N more` marker they collapsed into carried no click
// handler, so half the registry was mouse-unreachable. Nothing short of driving the real screen
// through real clicks at real sizes catches that — a layout test asserts what the packer decided,
// not what a pointer can actually get to. So this walks the bar the way an operator does: mount
// the real ReplScreen, click the pager with real SGR bytes, and count which commands were ever
// reachable. A command that only "remains reachable by typing /" is a FAILURE here, because that
// keyboard-only state is precisely what the issue was filed to end.

import { describe, expect, test } from "bun:test";
import { EventEmitter } from "node:events";
import readline from "node:readline";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { startStdinBridge } from "../ink/stdin-bridge.ts";
import { getCommands, resetCommandRegistryForTests } from "../../../../../../../tools/ember-cli/src/command-registry.ts";
import { startTelemetryWatch } from "../../../../../../../tools/ember-cli/src/services/telemetry-watch.ts";
import { ReplScreen } from "../../../../../../../tools/ember-cli/src/screens/repl.ts";

class FakeStdin extends EventEmitter {
  isTTY = true;
  setRawMode(): void {}
  resume(): void {}
  pause(): void {}
}

/** One SGR left-button-press sequence for a zero-based (col, row) terminal cell. */
function sgrLeftClick(col: number, row: number): string {
  return `\x1b[<0;${col + 1};${row + 1}M`;
}

/** The sizes the cockpit is actually used at, from the narrowest usable pane to a full screen. */
const SIZES = [[40, 24], [60, 20], [80, 24], [100, 30], [140, 40]] as const;

interface SweepRow {
  size: string;
  registered: number;
  onFirstPage: number;
  reached: number;
  pagerClicks: number;
  missing: string[];
}

describe("command-bar width sweep (issue #1370 acceptance #6)", () => {
  test("every registered command is click-reachable at every cockpit size", async () => {
    resetCommandRegistryForTests();
    const registry = await getCommands(process.cwd());
    const names = registry.map((command) => command.name);
    expect(names.length).toBeGreaterThan(0);

    const sweep: SweepRow[] = [];
    for (const [columns, rows] of SIZES) {
      let raw = "";
      const element = React.createElement(
        TerminalSizeContext.Provider,
        { value: { columns, rows } },
        React.createElement(ReplScreen, {
          config: { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" },
          cwd: process.cwd(),
          env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
          onExit: () => {},
        }),
      );
      const handle = mountInk(element, {
        stream: { write(chunk: string) { raw += chunk; } },
        stdout: { columns, rows },
      });
      const stdin = new FakeStdin();
      const stopBridge = startStdinBridge({
        stdin: stdin as never,
        emitKeypressEvents: (stream) => readline.emitKeypressEvents(stream),
      });
      const lines = (): string[] => {
        const frame = buildFrame(columns, rows);
        parseRenderedIntoFrame(raw, frame, new StylePool());
        return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
      };
      const settle = async (): Promise<void> => {
        for (let flush = 0; flush < 6; flush++) {
          await new Promise<void>((resolve) => setTimeout(resolve, 40));
          await new Promise<void>((resolve) => setImmediate(resolve));
        }
      };

      try {
        await settle();
        const firstPage = new Set<string>();
        const reached = new Set<string>();
        let pagerClicks = 0;
        // Bounded by the registry size: one button per page is the worst case, so a pager that
        // silently stops advancing runs out of hops and FAILS rather than looping forever.
        for (let hop = 0; hop < names.length + 2; hop++) {
          const current = lines();
          const joined = current.join("\n");
          for (const name of names) {
            if (!joined.includes(`[${name}]`)) continue;
            reached.add(name);
            if (hop === 0) firstPage.add(name);
          }
          if (reached.size === names.length) break;
          // The pager is matched by its OWN shape rather than by proximity to a button label:
          // "+N more", or the "›" glyph it degrades to when the pane cannot afford the caption.
          // Since #1399 the bar shares the live-run pane with the telemetry cards, whose
          // "… N more charts" caption a naive search for "more" hits first and clicks instead —
          // that caption has no "+", so the pattern below cannot match it.
          let at: { col: number; row: number } | undefined;
          for (let row = current.length - 1; row >= 0 && !at; row--) {
            const line = current[row]!;
            const plus = /\+\d+ more/.exec(line);
            if (plus && plus.index >= 0) { at = { col: plus.index, row }; break; }
            const glyph = line.indexOf("›");
            if (glyph >= 0) { at = { col: glyph, row }; break; }
          }
          if (!at) break;
          stdin.emit("data", Buffer.from(sgrLeftClick(at.col + 1, at.row)));
          pagerClicks++;
          await settle();
        }
        sweep.push({
          size: `${columns}x${rows}`,
          registered: names.length,
          onFirstPage: firstPage.size,
          reached: reached.size,
          pagerClicks,
          missing: names.filter((name) => !reached.has(name)),
        });
      } finally {
        stopBridge();
        handle.unmount();
      }
    }

    // Printed so a CI run carries the sweep as evidence, not just a pass/fail bit.
    console.log("| size | registered | buttons on page 1 | reached by clicking | pager clicks |");
    console.log("|---|---|---|---|---|");
    for (const row of sweep) {
      console.log(
        `| ${row.size} | ${row.registered} | ${row.onFirstPage} | ${row.reached} | ${row.pagerClicks} |`,
      );
    }

    for (const row of sweep) {
      expect({ size: row.size, missing: row.missing }).toEqual({ size: row.size, missing: [] });
    }
    // The sweep must actually EXERCISE paging somewhere, or it is proving nothing: a run where
    // every size happened to fit the whole registry would pass while the pager is dead again.
    expect(sweep.some((row) => row.pagerClicks > 0)).toBe(true);

    resetCommandRegistryForTests();
    startTelemetryWatch().stop();
  }, 120000);
});
