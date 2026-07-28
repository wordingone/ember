// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import React from "react";

import { renderFireballLines } from "../components/fireball.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { ReplScreen } from "./repl.ts";

let mounted: ReturnType<typeof mountInk> | undefined;
const originalAnimationEnv = {
  EMBER_REDUCED_MOTION: process.env["EMBER_REDUCED_MOTION"],
  EMBER_ASCII: process.env["EMBER_ASCII"],
  NO_COLOR: process.env["NO_COLOR"],
};

beforeEach(() => {
  delete process.env["EMBER_REDUCED_MOTION"];
  delete process.env["EMBER_ASCII"];
  delete process.env["NO_COLOR"];
});

afterEach(() => {
  mounted?.unmount();
  mounted = undefined;
  for (const [name, value] of Object.entries(originalAnimationEnv)) {
    if (value === undefined) {
      delete process.env[name];
    } else {
      process.env[name] = value;
    }
  }
});

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

function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*m/g, "");
}

const idleRasters = [0, 1, 2].map((tick) =>
  renderFireballLines("panel", "idle", tick, { ascii: false, color: true }).map(stripAnsi)
);

function detectedIdleRaster(lines: string[]): number | undefined {
  for (let tick = 0; tick < idleRasters.length; tick++) {
    const raster = idleRasters[tick]!;
    for (let row = 0; row <= lines.length - raster.length; row++) {
      if (raster.every((rasterLine, offset) => lines[row + offset]!.includes(rasterLine))) {
        return tick;
      }
    }
  }
  return undefined;
}

describe("issue #46 production homescreen fireball binding", () => {
  test("the real idle ReplScreen advances through at least two welcome-fireball rasters", async () => {
    const columns = 120;
    const rows = 36;
    let raw = "";
    const element = React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns, rows } },
      React.createElement(ReplScreen, {
        config: { model: "ember", permissionMode: "bypass", baseSystemPrompt: "" },
        cwd: process.cwd(),
        env: {
          EMBER_DISABLE_TERMINAL_TITLE: "1",
          EMBER_DISABLE_VIRTUAL_SCROLL: "1",
        },
        onExit: () => {},
      }),
    );
    mounted = mountInk(element, {
      stream: { write(chunk: string) { raw += chunk; } },
      stdout: { columns, rows },
    });

    // Let async command discovery and the first telemetry/activity pickup settle. The next
    // liveness/telemetry cadence is 500-1000 ms away; only the 140 ms welcome fireball should
    // change across the bounded samples below.
    await Bun.sleep(700);
    await flushRepl();
    const observed = new Set<number>();
    for (let sample = 0; sample < 4; sample++) {
      const raster = detectedIdleRaster(renderedLines(raw, columns, rows));
      expect(raster).toBeDefined();
      observed.add(raster!);
      await Bun.sleep(150);
      await flushRepl();
    }

    expect(observed.size).toBeGreaterThanOrEqual(2);
  });

  test("the welcome fireball stops repainting after a real command leaves the empty idle state", async () => {
    const columns = 120;
    const rows = 36;
    let raw = "";
    const element = React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns, rows } },
      React.createElement(ReplScreen, {
        config: { model: "ember", permissionMode: "bypass", baseSystemPrompt: "" },
        cwd: process.cwd(),
        env: {
          EMBER_DISABLE_TERMINAL_TITLE: "1",
          EMBER_DISABLE_VIRTUAL_SCROLL: "1",
        },
        onExit: () => {},
      }),
    );
    mounted = mountInk(element, {
      stream: { write(chunk: string) { raw += chunk; } },
      stdout: { columns, rows },
    });

    await Bun.sleep(300);
    await flushRepl();
    for (const character of "/help") {
      _deliverKeyEvent(character, {});
    }
    _deliverKeyEvent("return", {});
    await Bun.sleep(500);
    await flushRepl();

    const observed = new Set<number>();
    for (let sample = 0; sample < 4; sample++) {
      const raster = detectedIdleRaster(renderedLines(raw, columns, rows));
      expect(raster).toBeDefined();
      observed.add(raster!);
      await Bun.sleep(150);
      await flushRepl();
    }

    expect(observed.size).toBe(1);
  });
});
