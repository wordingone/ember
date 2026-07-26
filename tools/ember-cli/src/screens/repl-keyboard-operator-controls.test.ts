// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// screens/repl-keyboard-operator-controls.test.ts — R2b: the keyboard half of the operator
// controls. #1102 (50498b7) wired the mouse-click path end to end (real SGR bytes -> decoder ->
// hit-test -> Box.onClick -> onControl -> driveOperatorControl -> a real JSONL append); this file
// proves the keyboard path exists too, entering at the SAME kind of real boundary the click test
// used: real key bytes on a fake stdin, read back from the real control-channel file, never the
// handler call.
//
// A note on the acceptance map's row 1 ("Tab from the pane, four times -> focus visits all four
// controls in visual order"), read against isOperatorControlEnabled: START/PAUSE/RESTART gate on
// a single-valued `status` (IDLE/RUNNING/STALE/OFFLINE) that is mutually exclusive by
// construction, and RESUME gates independently on runStatus.phase. No real telemetry state can
// therefore make all four enabled at once (at most one of START/PAUSE/RESTART, plus optionally
// RESUME) -- so "all four reachable" cannot be exercised through the full integration harness
// without contradicting the Build section's own "a control that is not currently valid ... is
// skipped by traversal." Row 1 is instead verified against `nextOperatorFocusIndex`, the exact
// pure traversal-step function the production keyboard handler in repl.ts calls on every
// Tab/Arrow press -- so this is still a real-production-code test, just entered one level below
// the full key-byte boundary, on the one row whose own premise is unreachable at that boundary.
// Every other row (2 through S3) drives real key bytes into a real mounted ReplScreen exactly as
// the click test does.
import { describe, expect, test } from "bun:test";
import { EventEmitter } from "node:events";
import React from "react";
import { tmpdir } from "os";
import { join } from "path";
import { writeFile, readFile, unlink } from "fs/promises";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { startStdinBridge } from "../ink/stdin-bridge.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { startTelemetryWatch } from "../services/telemetry-watch.ts";
import { ReplScreen } from "./repl.ts";
import {
  OperatorSurfacePane,
  nextOperatorFocusIndex,
  operatorControlDisabledReason,
} from "../components/operator-surface-pane.ts";

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

// Raw byte sequences for the keys this build reads. Delivered through the SAME real
// readline-keypress pipeline (stdin-bridge.ts -> node's readline.emitKeypressEvents) the click
// test's mouse bytes went through -- not a synthetic _deliverKeyEvent shortcut.
const KEY = {
  TAB: "\t",
  RIGHT: "\x1b[C",
  LEFT: "\x1b[D",
  ENTER: "\r",
  SPACE: " ",
  ESCAPE: "\x1b",
};

async function readControlLines(controlPath: string): Promise<Array<Record<string, unknown>>> {
  try {
    const raw = await readFile(controlPath, "utf-8");
    return raw.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
  } catch {
    return [];
  }
}

interface Mounted {
  handle: ReturnType<typeof mountInk>;
  stdin: FakeStdin;
  stopBridge: () => void;
  telemetryPath: string;
  controlPath: string;
  columns: number;
  rows: number;
  getRaw: () => string;
}

/** Mounts a real ReplScreen with a seeded telemetry file and a temp control-channel path, wires
 *  a FakeStdin through the real stdin-bridge (exactly as the click test does), and returns
 *  handles for driving keys and reading back state. Seed lines are appended to the telemetry
 *  file before mount so the pane observes them on its first poll. */
async function mountForKeyboard(
  seedLines: Array<Record<string, unknown>>,
  options: { columns?: number; rows?: number } = {},
): Promise<Mounted> {
  resetCommandRegistryForTests();
  const telemetryPath = join(tmpdir(), `test-kbd-telemetry-${Date.now()}-${Math.random()}.jsonl`);
  const controlPath = join(tmpdir(), `test-kbd-control-${Date.now()}-${Math.random()}.jsonl`);
  await writeFile(telemetryPath, seedLines.map((line) => JSON.stringify(line)).join("\n") + (seedLines.length > 0 ? "\n" : ""));
  const previousTelemetryEnv = process.env["EMBER_TELEMETRY_PATH"];
  process.env["EMBER_TELEMETRY_PATH"] = telemetryPath;

  const columns = options.columns ?? 100;
  const rows = options.rows ?? 30;
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
  // NOTE: unlike the mouse-click test, this file drives KEYBOARD input, which is decoded by
  // node's real `readline.emitKeypressEvents` (stdin-bridge's default) rather than the SGR mouse
  // decoder -- so, unlike the click test, this must NOT stub emitKeypressEvents to a no-op.
  const stopBridge = startStdinBridge({ stdin: stdin as never });

  (handle as unknown as { _previousTelemetryEnv?: string | undefined })._previousTelemetryEnv = previousTelemetryEnv;

  return { handle, stdin, stopBridge, telemetryPath, controlPath, columns, rows, getRaw: () => raw };
}

async function teardown(m: Mounted, previousTelemetryEnv: string | undefined): Promise<void> {
  m.stopBridge();
  m.handle.unmount();
  if (previousTelemetryEnv === undefined) delete process.env["EMBER_TELEMETRY_PATH"];
  else process.env["EMBER_TELEMETRY_PATH"] = previousTelemetryEnv;
  // telemetry-watch's state is a module-level singleton (see repl-operator-control-wiring.test.ts's
  // identical note) -- stop it and wipe both temp files so a later test never observes this one's
  // leftovers.
  startTelemetryWatch().stop();
  await Promise.all([
    unlink(m.telemetryPath).catch(() => {}),
    unlink(m.controlPath).catch(() => {}),
  ]);
}

function send(stdin: FakeStdin, bytes: string): void {
  stdin.emit("data", Buffer.from(bytes));
}

async function waitFor(predicate: () => boolean, attempts: number = 30): Promise<boolean> {
  for (let attempt = 0; attempt < attempts && !predicate(); attempt++) {
    await new Promise<void>((resolve) => setTimeout(resolve, 100));
    await flushRepl();
  }
  return predicate();
}

const RUN_ID = "run-kbd";

function trainEvent(runId: string, ts: string, step: number = 1): Record<string, unknown> {
  return { ts, kind: "train_step", source: "journal", payload: { run_id: runId, step, loss: 1.5 } };
}

function runStatusEvent(runId: string, ts: string, phase: string): Record<string, unknown> {
  return { ts, kind: "run_status", source: "journal", payload: { run_id: runId, phase, model_chat: "chat" } };
}

describe("repl keyboard operator controls (R2b)", () => {
  // -----------------------------------------------------------------------
  // Row 1 -- traversal order + "leaves the set" (see module doc for why this is a direct test of
  // the pure step function rather than the full key-byte boundary).
  // -----------------------------------------------------------------------
  test("row1: Tab-equivalent traversal visits every control in visual order, then leaves the set", () => {
    const allEnabled = [true, true, true, true];
    let index: number | null = nextOperatorFocusIndex(-1, 1, allEnabled); // entry
    expect(index).toBe(0);
    index = nextOperatorFocusIndex(index!, 1, allEnabled);
    expect(index).toBe(1);
    index = nextOperatorFocusIndex(index!, 1, allEnabled);
    expect(index).toBe(2);
    index = nextOperatorFocusIndex(index!, 1, allEnabled);
    expect(index).toBe(3);
    index = nextOperatorFocusIndex(index!, 1, allEnabled);
    expect(index).toBeNull(); // leaves the set
  });

  // -----------------------------------------------------------------------
  // Row 2 -- Enter on a focused control reaches the control stream with the right run id.
  // -----------------------------------------------------------------------
  test("row2: Enter on the focused control appends the real command to the control channel", async () => {
    const now = new Date().toISOString();
    const m = await mountForKeyboard([trainEvent(RUN_ID, now)]);
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const running = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("RUNNING")));
      expect(running).toBe(true);

      send(m.stdin, KEY.TAB); // enter the pane -- lands on PAUSE, the only enabled control while RUNNING
      await flushRepl();
      send(m.stdin, KEY.ENTER);
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const lines = await readControlLines(m.controlPath);
      expect(lines).toEqual([{ verb: "pause", runId: RUN_ID, ts: expect.any(String) }]);
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // Row 3 -- Space is identical to Enter.
  // -----------------------------------------------------------------------
  test("row3: Space on the focused control behaves identically to Enter", async () => {
    const now = new Date().toISOString();
    const m = await mountForKeyboard([trainEvent(RUN_ID, now)]);
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const running = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("RUNNING")));
      expect(running).toBe(true);

      send(m.stdin, KEY.TAB);
      await flushRepl();
      send(m.stdin, KEY.SPACE);
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const lines = await readControlLines(m.controlPath);
      expect(lines).toEqual([{ verb: "pause", runId: RUN_ID, ts: expect.any(String) }]);
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // Row 4 -- each accelerator key, pane focused, reaches the stream; focus is unchanged.
  // -----------------------------------------------------------------------
  test("row4: an accelerator reaches the stream for its OWN control without moving focus off the currently-focused one", async () => {
    const t1 = new Date(Date.now() - 2000).toISOString();
    const t2 = new Date(Date.now() - 1000).toISOString(); // after t1 -- run_status is the newer, live signal
    const m = await mountForKeyboard([trainEvent(RUN_ID, t1), runStatusEvent(RUN_ID, t2, "PAUSED")]);
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      // Both PAUSE (status RUNNING via the train_step) and RESUME (runStatus.phase PAUSED,
      // gated independently) are enabled simultaneously here.
      // The four control labels always render regardless of status (only their color/enablement
      // changes), so waiting on the label text is not a wait on the RIGHT condition -- wait for
      // the actual rendered status word instead, exactly as the click test does.
      const running = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("RUNNING")));
      expect(running).toBe(true);

      send(m.stdin, KEY.TAB); // entry lands on the first enabled control in canonical order: PAUSE
      await flushRepl();
      let lines = renderedLines(m.getRaw(), m.columns, m.rows);
      expect(lines.some((l) => l.includes("▸ [(P)AUSE]"))).toBe(true); // focus marker on PAUSE

      send(m.stdin, "u"); // RESUME's accelerator -- focus is still on PAUSE
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([{ verb: "resume", runId: RUN_ID, ts: expect.any(String) }]);

      lines = renderedLines(m.getRaw(), m.columns, m.rows);
      expect(lines.some((l) => l.includes("▸ [(P)AUSE]"))).toBe(true); // still on PAUSE
      expect(lines.some((l) => l.includes("▸ [RES(U)ME]"))).toBe(false); // never moved to RESUME
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // Row 5 -- an accelerator while a text input has focus just types the character.
  // -----------------------------------------------------------------------
  test("row5: an accelerator typed while the prompt (not the pane) has focus is inserted as text, no verb emitted", async () => {
    const m = await mountForKeyboard([]);
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      await flushRepl();
      // Never Tab into the pane -- the prompt has focus by default.
      send(m.stdin, "p"); // PAUSE's accelerator, typed as an ordinary character instead
      await flushRepl();

      const lines = renderedLines(m.getRaw(), m.columns, m.rows);
      const promptRow = lines.find((l) => l.includes("❯")); // the prompt's ❯ glyph
      expect(promptRow).toBeDefined();
      expect(promptRow).toContain("p");

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]);
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // Row 6 -- traversal skips a disabled control; the others remain reachable.
  // -----------------------------------------------------------------------
  test("row6: traversal steps over a disabled control instead of landing on it", async () => {
    const now = new Date().toISOString();
    const m = await mountForKeyboard([trainEvent(RUN_ID, now)]); // status RUNNING: only PAUSE enabled
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const running = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("RUNNING")));
      expect(running).toBe(true);

      send(m.stdin, KEY.TAB); // entry lands on PAUSE (index 1) -- the only enabled control
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸ [(P)AUSE]"))).toBe(true);

      // Backward from PAUSE: START (index 0) is disabled and must be SKIPPED -- there is nothing
      // else below it, so traversal leaves the set rather than landing on the disabled control.
      send(m.stdin, KEY.LEFT);
      await flushRepl();
      const lines = renderedLines(m.getRaw(), m.columns, m.rows);
      expect(lines.some((l) => l.includes("▸ [(S)TART]"))).toBe(false); // never focused START
      expect(lines.some((l) => l.includes("▸"))).toBe(false); // no marker anywhere -- left the set
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // Row 7 -- accelerator for a disabled control: no verb, no error, reason surfaced.
  // -----------------------------------------------------------------------
  test("row7: an accelerator for a disabled control emits nothing and surfaces the reason", async () => {
    const now = new Date().toISOString();
    const m = await mountForKeyboard([trainEvent(RUN_ID, now)]); // status RUNNING: START is disabled
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const running = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("RUNNING")));
      expect(running).toBe(true);

      send(m.stdin, KEY.TAB);
      await flushRepl();
      send(m.stdin, "s"); // START's accelerator -- disabled while RUNNING
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]); // no verb

      const lines = renderedLines(m.getRaw(), m.columns, m.rows);
      expect(lines.some((l) => l.includes(operatorControlDisabledReason("START")))).toBe(true); // reason surfaced
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // C1 -- narrowest supported width, all four controls: reachable regardless of wrapped rows.
  // -----------------------------------------------------------------------
  test("C1: at a narrow pane width the controls reflow across rows but activation still works", async () => {
    const now = new Date().toISOString();
    // 60 real terminal columns pushes the operator pane itself well under the ~49-column budget
    // the four decorated labels need on one row, forcing layoutControlRows to wrap -- proving the
    // premise (reflow is actually happening here, not just assumed).
    const m = await mountForKeyboard([trainEvent(RUN_ID, now)], { columns: 60, rows: 24 });
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const running = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("RUNNING")));
      expect(running).toBe(true);

      send(m.stdin, KEY.TAB);
      await flushRepl();
      send(m.stdin, KEY.ENTER);
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([{ verb: "pause", runId: RUN_ID, ts: expect.any(String) }]);
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // C2 -- a live run and RESTART: stop leg then start leg, both observable, in order.
  // -----------------------------------------------------------------------
  test("C2: RESTART on an OFFLINE run emits stop then start, in order", async () => {
    const t1 = new Date(Date.now() - 2000).toISOString();
    const t2 = new Date(Date.now() - 1000).toISOString();
    // train_step resolves a run; a NEWER run_status with phase OFFLINE flips channelIsOffline,
    // which is what getOperatorRunStatus reads as status "OFFLINE" -- the only state that enables
    // RESTART.
    const m = await mountForKeyboard([trainEvent(RUN_ID, t1), runStatusEvent(RUN_ID, t2, "OFFLINE")]);
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const offline = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("OFFLINE")));
      expect(offline).toBe(true);

      send(m.stdin, KEY.TAB); // entry lands on RESTART, the only enabled control while OFFLINE
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸ [RES(T)ART]"))).toBe(true);

      send(m.stdin, KEY.ENTER);
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([
        { verb: "stop", runId: RUN_ID, ts: expect.any(String) },
        { verb: "start", ts: expect.any(String) },
      ]);
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // C3 -- disabled control AND accelerator AND text input focused: the input wins.
  // -----------------------------------------------------------------------
  test("C3: a disabled control's accelerator, typed while the prompt has focus, types the character and shows no reason banner", async () => {
    const m = await mountForKeyboard([]); // no run at all -- RESTART is disabled
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      await flushRepl();
      send(m.stdin, "t"); // RESTART's accelerator, but the prompt (not the pane) has focus
      await flushRepl();

      const lines = renderedLines(m.getRaw(), m.columns, m.rows);
      const promptRow = lines.find((l) => l.includes("❯"));
      expect(promptRow).toBeDefined();
      expect(promptRow).toContain("t");
      expect(lines.some((l) => l.includes(operatorControlDisabledReason("RESTART")))).toBe(false); // input wins, no banner

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]);
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // C4 -- rapid repeat of one accelerator: one verb per keypress, no coalescing.
  // -----------------------------------------------------------------------
  test("C4: three rapid presses of the same accelerator emit three separate commands", async () => {
    const now = new Date().toISOString();
    const m = await mountForKeyboard([trainEvent(RUN_ID, now)]);
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const running = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("RUNNING")));
      expect(running).toBe(true);

      send(m.stdin, KEY.TAB);
      await flushRepl();
      send(m.stdin, "p");
      send(m.stdin, "p");
      send(m.stdin, "p");
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toHaveLength(3);
      expect(controlLines.every((line) => line["verb"] === "pause" && line["runId"] === RUN_ID)).toBe(true);
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // S1 -- disabled-state check bypassed when no run exists at all: no crash, everything inert.
  // -----------------------------------------------------------------------
  test("S1: with no run at all, traversal and a disabled accelerator both stay inert without crashing", async () => {
    const m = await mountForKeyboard([]); // fully empty telemetry -- only START is enabled (IDLE)
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      await flushRepl();

      send(m.stdin, KEY.TAB); // entry -- lands on START (only enabled control)
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸ [(S)TART]"))).toBe(true);

      // Forward from START: PAUSE, RESUME, RESTART are all disabled -- skip clean off the end
      // rather than throwing or landing on a dead control.
      send(m.stdin, KEY.RIGHT);
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸"))).toBe(false);

      // Re-enter and try a disabled accelerator directly.
      send(m.stdin, KEY.TAB);
      await flushRepl();
      send(m.stdin, "u"); // RESUME -- disabled, no paused run
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]); // never crashed, never emitted
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes(operatorControlDisabledReason("RESUME")))).toBe(true);
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // S2 -- focus containment bypassed when the pane is not mounted (via ReplScreen's keyboard
  // wiring): accelerators emit nothing, because nothing exists to dispatch them.
  // -----------------------------------------------------------------------
  test("S2: mounting the pane WITHOUT ReplScreen means accelerator keys reach no keyboard handler at all", async () => {
    resetCommandRegistryForTests();
    const calls: Array<{ action: string; runId?: string }> = [];
    let raw = "";
    const columns = 80;
    const rows = 24;
    const element = React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns, rows } },
      React.createElement(OperatorSurfacePane, {
        telemetry: { recentEvents: [] } as never,
        activityLines: [],
        width: 33,
        height: 24,
        onControl: (action, runId) => calls.push({ action, runId }),
      }),
    );
    const handle = mountInk(element, { stream: { write(s: string) { raw += s; } }, stdout: { columns, rows } });
    const stdin = new FakeStdin();
    // NOTE: unlike the mouse-click test, this file drives KEYBOARD input, which is decoded by
  // node's real `readline.emitKeypressEvents` (stdin-bridge's default) rather than the SGR mouse
  // decoder -- so, unlike the click test, this must NOT stub emitKeypressEvents to a no-op.
  const stopBridge = startStdinBridge({ stdin: stdin as never });
    try {
      await flushRepl();
      send(stdin, "s");
      send(stdin, "p");
      send(stdin, "u");
      send(stdin, "t");
      send(stdin, KEY.TAB);
      send(stdin, KEY.ENTER);
      await flushRepl();
      expect(calls).toEqual([]); // no ReplScreen keyboard handler is mounted to interpret these
    } finally {
      stopBridge();
      handle.unmount();
    }
  });

  // -----------------------------------------------------------------------
  // S3 -- run-id resolution bypassed when the run id is null: no verb, rather than a verb with a
  // null id.
  // -----------------------------------------------------------------------
  test("S3: RESUME enabled with no resolvable run id emits no verb instead of one with a null runId", async () => {
    const now = new Date().toISOString();
    // A run_status PAUSED event with NO train_step event at all: RESUME's own enablement check
    // (runStatus.phase === "PAUSED") is independent of the derived `status`/runId, so RESUME can
    // read as enabled while selectedRunEvidence -- and therefore runId -- resolves to undefined.
    const m = await mountForKeyboard([runStatusEvent(RUN_ID, now, "PAUSED")]);
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const ready = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("[RES(U)ME]") || l.includes("(U)ME")));
      expect(ready).toBe(true);

      send(m.stdin, KEY.TAB); // entry lands on START (IDLE, since no train_step -> no resolved runId)
      await flushRepl();
      send(m.stdin, "u"); // RESUME's accelerator, reachable via row4's focus-independent dispatch
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]); // driveOperatorControl's validateControlCmd rejects a
      // runId-less resume BEFORE any emit -- the fail-closed floor holds even when the pane's own
      // enablement check let the accelerator through.
    } finally {
      await teardown(m, previous);
    }
  }, 15000);
});
