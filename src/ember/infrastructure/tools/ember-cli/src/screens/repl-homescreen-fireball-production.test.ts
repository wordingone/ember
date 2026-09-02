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
  EMBER_DIAGNOSTIC_DISABLE_ACTIVITY_FEED: process.env["EMBER_DIAGNOSTIC_DISABLE_ACTIVITY_FEED"],
};

beforeEach(() => {
  delete process.env["EMBER_REDUCED_MOTION"];
  delete process.env["EMBER_ASCII"];
  delete process.env["NO_COLOR"];
  // Keep this production-path clock test in the empty-idle state it names. Ambient shared-repo
  // activity receipts can otherwise append a transcript line before the one-second boundary,
  // intentionally disabling the fireball gate and selecting the fixed idle pose.
  process.env["EMBER_DIAGNOSTIC_DISABLE_ACTIVITY_FEED"] = "1";
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

function renderedFrame(raw: string, columns: number, rows: number) {
  const frame = buildFrame(columns, rows);
  const pool = new StylePool();
  parseRenderedIntoFrame(raw, frame, pool);
  return { frame, pool };
}

function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*m/g, "");
}

const idleRaster = renderFireballLines(
  "panel",
  "idle",
  0,
  { ascii: false, color: true },
).map(stripAnsi);

function detectedIdleStyleSignature(raw: string, columns: number, rows: number): string | undefined {
  const { frame, pool } = renderedFrame(raw, columns, rows);
  const lines = frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
  for (let row = 0; row <= lines.length - idleRaster.length; row++) {
    for (let col = 0; col <= columns - 9; col++) {
      if (idleRaster.every((rasterLine, offset) =>
        lines[row + offset]!.slice(col, col + rasterLine.length) === rasterLine
      )) {
        return JSON.stringify(frame.cells.slice(row, row + idleRaster.length).map((line) =>
          line.slice(col, col + 9).map((cell) => ({
            char: cell?.char ?? " ",
            style: pool.lookup(cell?.styleRef ?? 0),
          }))
        ));
      }
    }
  }
  return undefined;
}

describe("issue #46 production homescreen fireball binding", () => {
  test("the real idle ReplScreen advances the fireball on the existing one-second liveness cadence", async () => {
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

    // The fireball must not own a sub-second repaint clock. During the first 400 ms after mount,
    // the mandatory one-second liveness heartbeat has not fired, so every observed raster must
    // remain identical even if unrelated async setup commits settle around it.
    await flushRepl();
    const subsecond = new Set<string>();
    for (let sample = 0; sample < 5; sample++) {
      const signature = detectedIdleStyleSignature(raw, columns, rows);
      expect(signature).toBeDefined();
      subsecond.add(signature!);
      if (sample < 4) await Bun.sleep(100);
      await flushRepl();
    }
    expect(subsecond.size).toBe(1);

    // Cross the first liveness boundary. Reusing that existing clock must still produce real
    // animation, just without animation-only commits between heartbeat frames.
    const beforeLiveness = [...subsecond][0]!;
    // Leave scheduler headroom after the interval's effect-registration point; the assertion is
    // about crossing at least one one-second liveness boundary, not about a 150 ms deadline.
    await Bun.sleep(1250);
    await flushRepl();
    const afterLiveness = detectedIdleStyleSignature(raw, columns, rows);
    expect(afterLiveness).toBeDefined();
    expect(afterLiveness).not.toBe(beforeLiveness);
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

    const observed = new Set<string>();
    for (let sample = 0; sample < 4; sample++) {
      const signature = detectedIdleStyleSignature(raw, columns, rows);
      expect(signature).toBeDefined();
      observed.add(signature!);
      await Bun.sleep(150);
      await flushRepl();
    }

    expect(observed.size).toBe(1);
  });
});
