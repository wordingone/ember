// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-operator-control-wiring.test.ts — RED-first end-to-end proof that a real mouse
// click on the operator-surface controls drives a real effect on the run, not just
// a handler firing. Before this wiring, ReplScreen never passed `onControl` to
// OperatorSurfacePane, so every click called `undefined?.(...)` -- a no-op indistinguishable
// from a working control by anything short of an effect-level assertion.
//
// The chain exercised here is the REAL production click path, start to finish:
//   raw SGR mouse bytes on stdin -> createSgrMouseDecoder -> hit-test -> Box.onClick
//   -> OperatorSurfacePane's onControl(action, runId) -> ReplScreen's handleOperatorControl.
// START then enters the governed /train dispatcher and must render its result; runtime actions enter
// driveOperatorControl -> emitControlCmd -> a real JSONL append. Assertions target those effects,
// not whether a handler ran (per the operator's bar:
// "did the test apparatus produce the condition it is measuring?" -- driving state directly and
// observing that same state proves nothing; this drives the click and observes the channel).
import { describe, expect, test } from "bun:test";
import { EventEmitter } from "node:events";
import React from "react";
import { tmpdir } from "os";
import { join } from "path";
import { access, writeFile, readFile, unlink } from "fs/promises";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { startStdinBridge } from "../ink/stdin-bridge.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { startTelemetryWatch } from "../services/telemetry-watch.ts";
import { ReplScreen } from "./repl.ts";

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

/** Finds the zero-based (col, row) of the first character of `needle` in the rendered frame. */
function findGlyph(lines: string[], needle: string): { col: number; row: number } | undefined {
  for (let row = 0; row < lines.length; row++) {
    const col = lines[row]!.indexOf(needle);
    if (col >= 0) return { col, row };
  }
  return undefined;
}

/** Builds one SGR left-button-press sequence for a zero-based (col, row) terminal cell. */
function sgrLeftClick(col: number, row: number): string {
  return `\x1b[<0;${col + 1};${row + 1}M`;
}

/** Like findGlyph, but scanning only rows at/after `fromRow` and columns at/after `fromCol` —
 *  used to locate SELECT PROCESS dropdown rows inside the operator pane's column range without
 *  matching the same word rendered by the homescreen/transcript on the left. */
function findGlyphFrom(
  lines: string[],
  needle: string,
  fromRow: number,
  fromCol: number,
): { col: number; row: number } | undefined {
  for (let row = fromRow; row < lines.length; row++) {
    const col = lines[row]!.indexOf(needle, fromCol);
    if (col >= 0) return { col, row };
  }
  return undefined;
}

describe("operator-surface pane control click drives a real effect on the run", () => {
  test("#1475 click-first path: SELECT PROCESS -> train -> START enters the real /train flow and surfaces its refusal", async () => {
    resetCommandRegistryForTests();
    startTelemetryWatch().stop();
    const telemetryPath = join(tmpdir(), `test-repl-start-telemetry-${Date.now()}-${Math.random()}.jsonl`);
    const controlPath = join(tmpdir(), `test-repl-start-control-${Date.now()}-${Math.random()}.jsonl`);
    await writeFile(telemetryPath, "");
    const previousTelemetryEnv = process.env["EMBER_TELEMETRY_PATH"];
    const previousPythonEnv = process.env["EMBER_PYTHON_BIN"];
    process.env["EMBER_TELEMETRY_PATH"] = telemetryPath;
    process.env["EMBER_PYTHON_BIN"] = join(tmpdir(), "ember-test-python-that-does-not-exist");

    const columns = 100;
    const rows = 30;
    let raw = "";
    const element = React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns, rows } },
      React.createElement(ReplScreen, {
        config: { model: "ember", permissionMode: "regular" as const, baseSystemPrompt: "" },
        cwd: process.cwd(),
        env: {
          EMBER_DISABLE_TERMINAL_TITLE: "1",
          EMBER_DISABLE_VIRTUAL_SCROLL: "1",
          EMBER_FINETUNE_CONTROL_PATH: controlPath,
        },
        onExit: () => {},
      }),
    );
    const handle = mountInk(element, {
      stream: { write(chunk: string) { raw += chunk; } },
      stdout: { columns, rows },
    });
    const stdin = new FakeStdin();
    const stopBridge = startStdinBridge({ stdin: stdin as never, emitKeypressEvents: () => {} });

    try {
      // (1) The reorganized pane: [SELECT PROCESS ▾] sits under the state line where the gray
      // "run control" caption used to be, and the launch cluster is out of the command bar —
      // [train] has no bar button, the dropdown is its one home.
      let lines: string[] = [];
      let toggleAt: { col: number; row: number } | undefined;
      for (let attempt = 0; attempt < 30 && !toggleAt; attempt += 1) {
        await new Promise<void>((resolve) => setTimeout(resolve, 50));
        await flushRepl();
        lines = renderedLines(raw, columns, rows);
        if (lines.some((line) => line.includes("IDLE"))) toggleAt = findGlyph(lines, "[SELECT PROCESS");
      }
      expect(toggleAt).toBeDefined();
      expect(lines.some((line) => line.includes("run control"))).toBe(false);
      expect(lines.some((line) => line.includes("[train]"))).toBe(false);

      // (2) Click the toggle: the dropdown dialog opens where the button is, listing train.
      stdin.emit("data", Buffer.from(sgrLeftClick(toggleAt!.col + 1, toggleAt!.row)));
      let trainAt: { col: number; row: number } | undefined;
      for (let attempt = 0; attempt < 30 && !trainAt; attempt += 1) {
        await new Promise<void>((resolve) => setTimeout(resolve, 50));
        await flushRepl();
        lines = renderedLines(raw, columns, rows);
        trainAt = findGlyphFrom(lines, "train", toggleAt!.row + 1, Math.max(0, toggleAt!.col - 2));
      }
      expect(trainAt).toBeDefined();

      // (3) Click train: the menu closes, the toggle re-labels with the selection, and START is
      // armed (present and clickable).
      stdin.emit("data", Buffer.from(sgrLeftClick(trainAt!.col + 1, trainAt!.row)));
      let startAt: { col: number; row: number } | undefined;
      for (let attempt = 0; attempt < 30 && !startAt; attempt += 1) {
        await new Promise<void>((resolve) => setTimeout(resolve, 50));
        await flushRepl();
        lines = renderedLines(raw, columns, rows);
        if (lines.some((line) => line.includes("[PROCESS: train"))) startAt = findGlyph(lines, "[START]");
      }
      expect(startAt).toBeDefined();

      // (4) Click START: enters the REAL /train dispatcher — the nonexistent python fails the
      // preflight closed and the refusal renders; nothing ever touches the legacy control
      // channel (no dead start row).
      stdin.emit("data", Buffer.from(sgrLeftClick(startAt!.col + 1, startAt!.row)));
      let refusalVisible = false;
      for (let attempt = 0; attempt < 40 && !refusalVisible; attempt += 1) {
        await new Promise<void>((resolve) => setTimeout(resolve, 50));
        await flushRepl();
        lines = renderedLines(raw, columns, rows);
        refusalVisible = lines.some((line) => line.includes("BLOCKED"));
      }

      expect(refusalVisible).toBe(true);
      await expect(access(controlPath)).rejects.toThrow();
    } finally {
      stopBridge();
      handle.unmount();
      startTelemetryWatch().stop();
      if (previousTelemetryEnv === undefined) delete process.env["EMBER_TELEMETRY_PATH"];
      else process.env["EMBER_TELEMETRY_PATH"] = previousTelemetryEnv;
      if (previousPythonEnv === undefined) delete process.env["EMBER_PYTHON_BIN"];
      else process.env["EMBER_PYTHON_BIN"] = previousPythonEnv;
      await Promise.all([
        unlink(telemetryPath).catch(() => {}),
        unlink(controlPath).catch(() => {}),
      ]);
    }
  }, 20000);

  test("clicking [PAUSE] via the real mouse-click path appends a real pause command to the control channel", async () => {
    resetCommandRegistryForTests();
    const telemetryPath = join(tmpdir(), `test-repl-telemetry-${Date.now()}-${Math.random()}.jsonl`);
    const controlPath = join(tmpdir(), `test-repl-control-${Date.now()}-${Math.random()}.jsonl`);
    const runId = "run-wiring-e2e";
    await writeFile(
      telemetryPath,
      `${JSON.stringify({
        ts: new Date().toISOString(),
        kind: "train_step",
        source: "journal",
        payload: { run_id: runId, step: 1, loss: 1.5 },
      })}\n`,
    );
    const previousTelemetryEnv = process.env["EMBER_TELEMETRY_PATH"];
    process.env["EMBER_TELEMETRY_PATH"] = telemetryPath;

    const columns = 100;
    const rows = 30;
    let raw = "";
    const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
    const element = React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns, rows } },
      React.createElement(ReplScreen, {
        config,
        cwd: process.cwd(),
        env: {
          EMBER_DISABLE_TERMINAL_TITLE: "1",
          EMBER_DISABLE_VIRTUAL_SCROLL: "1",
          EMBER_FINETUNE_CONTROL_PATH: controlPath,
        },
        onExit: () => {},
      }),
    );
    const handle = mountInk(element, {
      stream: { write(chunk: string) { raw += chunk; } },
      stdout: { columns, rows },
    });
    const stdin = new FakeStdin();
    const stopBridge = startStdinBridge({ stdin: stdin as never, emitKeypressEvents: () => {} });

    try {
      // Real telemetry poll runs every 500ms (services/telemetry-watch.ts POLL_INTERVAL_MS);
      // wait for the pane to actually observe the RUNNING event before clicking, rather than a
      // fixed sleep guessed to be "long enough".
      // The PAUSE control renders in EVERY status (disabled-but-visible when not RUNNING), so
      // the loop must wait for RUNNING itself, not merely for the glyph to appear. R2b decorates
      // the plain label ("[PAUSE]", see operatorControlLabel) plus a two-column
      // focus-marker slot in front of it -- the click still targets the same Box, just at the
      // new label text.
      let lines: string[] = [];
      let running = false;
      for (let attempt = 0; attempt < 30 && !running; attempt++) {
        await new Promise<void>((resolve) => setTimeout(resolve, 100));
        await flushRepl();
        lines = renderedLines(raw, columns, rows);
        running = lines.some((line) => line.includes("RUNNING"));
      }
      expect(running).toBe(true);
      const pauseAt = findGlyph(lines, "[PAUSE]");
      expect(pauseAt).toBeDefined();

      stdin.emit("data", Buffer.from(sgrLeftClick(pauseAt!.col + 1, pauseAt!.row)));
      await flushRepl();
      // The control channel write is async (fs append); give the microtask/IO queue a moment.
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlRaw = await readFile(controlPath, "utf-8");
      const controlLines = controlRaw.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
      expect(controlLines).toEqual([{ verb: "pause", runId, ts: expect.any(String) }]);
    } finally {
      stopBridge();
      handle.unmount();
      if (previousTelemetryEnv === undefined) delete process.env["EMBER_TELEMETRY_PATH"];
      else process.env["EMBER_TELEMETRY_PATH"] = previousTelemetryEnv;
      // telemetry-watch's state is a module-level singleton, not scoped to this mount: unmount
      // only stops OUR interval, it does not reset `_state` back to empty. Without this, the
      // NEXT test file's ReplScreen reads this test's leftover RUNNING state as its very first
      // synchronous getState() (before its own startTelemetryWatch effect has fired), which is
      // exactly the cross-test pollution this caused before the fix: a later, unrelated repl
      // layout test observed "RUNNING" where it expected a clean "IDLE".
      startTelemetryWatch().stop();
      await Promise.all([
        unlink(telemetryPath).catch(() => {}),
        unlink(controlPath).catch(() => {}),
      ]);
    }
  }, 15000);
});
