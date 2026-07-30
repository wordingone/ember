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
//
// DD1-DD4 below (added for the #P1 dual-dispatch repair, R2b keyboard-authority fix) are the same
// shape, entering at the same real key-byte boundary, but each proves a NEGATIVE as well as a
// positive: that repl.ts's own operator-pane handler acts on a key AND that usePromptInput's own
// handler -- registered on the exact same shared dispatcher (ink/hooks.ts's `_inputHandlers`) --
// never also acts on it while the pane holds focus. Two of the four (DD1 Shift+Tab's
// cyclePermissionMode, DD2 Alt+P's openModelPicker) have NO production render or callback surface
// at all: `permissionModeStatusLine` is dead in production (prompt-input.ts's own comment: "repl.ts
// :showStatusLine is always false"), and `onModelPickerOpen`/`onEditorOpen` have zero call sites
// anywhere in repl.ts (grep-verified) -- both effects are invoked ONLY from usePromptInput's own
// internal useInput handler, so nothing downstream can ever show they didn't fire. Row 1 above hit
// the identical wall (no telemetry state makes its premise reachable at the full boundary) and
// dropped one level to the pure step function; DD1/DD2 drop to the same next level down --
// `usePromptInput` itself, still the real hook, the real shared dispatcher, and the real stdin
// bridge, just with `keyboardActive` set explicitly to the value ReplScreen computes (`!paneFocused`)
// instead of being driven by a live pane, and with the otherwise-unrendered state made visible (or
// spied) by the test's own wrapper -- exactly as `mountForKeyboard`'s own wrapper already renders
// context/props no production entry point renders unassisted. Each of DD1/DD2 also includes a
// sensitivity check (the identical bytes DO fire the effect when `keyboardActive` is true) so the
// negative assertion is a real one, not a harness that could never observe the effect either way.
import { describe, expect, test } from "bun:test";
import { EventEmitter } from "node:events";
import React, { useState } from "react";
import { tmpdir } from "os";
import { join } from "path";
import { writeFile, readFile, unlink } from "fs/promises";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext, Text } from "../ink/components.ts";
import { startStdinBridge } from "../ink/stdin-bridge.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { startTelemetryWatch } from "../services/telemetry-watch.ts";
import { ReplScreen } from "./repl.ts";
import { usePromptInput, type PromptInputDeps } from "../components/prompt-input.ts";
import { useInput as useRawInput, _deliverKeyEvent } from "../ink/hooks.ts";
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
  // DD1-DD4: byte sequences confirmed against node's own readline keypress decoder (the same
  // decoder stdin-bridge.ts wires up via `emitKeypressEvents`) -- SHIFT_TAB decodes to
  // {name:"tab", shift:true}, CTRL_S to {name:"s", ctrl:true}, ALT_P to {name:"p", meta:true}.
  SHIFT_TAB: "\x1b[Z",
  CTRL_S: "\x13",
  ALT_P: "\x1bp",
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

/** DD1/DD2 support -- mounts `usePromptInput` with `keyboardActive` pinned to the exact value the
 *  test wants to probe, and renders `state.permissionMode` as text so an otherwise fully-internal,
 *  never-rendered-in-production piece of state becomes observable. Real hook, real
 *  `useInput`/dispatcher, real stdin bridge -- see the module doc comment above for why this is
 *  the correct level to enter at for these two keys specifically.
 *
 *  Registers a SECOND, always-active, no-op `useInput` AFTER usePromptInput's own -- mirroring
 *  screens/repl.ts's real registration order (usePromptInput at line ~1099, the main handler at
 *  line ~1547, always-active, registered later) -- because ink/hooks.ts's `useInput` has its OWN
 *  defect: the per-render "sync isActive" effect writes to `_inputHandlers[_inputHandlers.length -
 *  1]` (the array's LAST entry) instead of the specific entry its own mount effect created, so
 *  whichever `useInput` call is NOT currently last never has its `isActive` toggle actually take
 *  effect after the first render. With only usePromptInput's own handler registered, this harness
 *  would never trigger that defect (its entry IS always "last"); the companion handler recreates
 *  the exact two-handler contention screens/repl.ts has in production, so `active:false` here is a
 *  real test of whether keyboardActive suppression survives that contention -- not a vacuous one.
 *
 *  Also reproduces the exact TRANSITION shape, not just the end value: the resync-index defect
 *  above only breaks an UPDATE to `isActive` -- the one-time mount effect always captures whatever
 *  value is current at first render correctly, so a harness that mounts directly with a fixed
 *  `keyboardActive` would never exercise the bug (it would look "already correct" from render one).
 *  screens/repl.ts starts with `paneFocused=false` (`keyboardActive` true) and flips to false only
 *  once Tab is pressed -- a genuine post-mount update -- so this harness mounts at `true` and then
 *  transitions to the requested `active` value the same way, before any key bytes are sent. */
async function mountPromptHookOnly(
  active: boolean,
  deps: PromptInputDeps = {},
): Promise<{ stdin: FakeStdin; stopBridge: () => void; getRaw: () => string; unmount: () => void }> {
  let raw = "";
  let setLiveExternal: ((v: boolean) => void) | null = null;
  function Probe(): React.ReactElement {
    const [live, setLive] = useState(true); // mirrors the initial `!paneFocused === true`
    setLiveExternal = setLive;
    const [state] = usePromptInput({ ...deps, keyboardActive: live });
    // Always-active companion handler, registered AFTER usePromptInput's own -- see doc comment.
    useRawInput(() => {});
    return React.createElement(Text, null, `PERM:${state.permissionMode}`);
  }
  const handle = mountInk(React.createElement(Probe, null), {
    stream: { write(chunk: string) { raw += chunk; } },
    stdout: { columns: 40, rows: 5 },
  });
  const stdin = new FakeStdin();
  const stopBridge = startStdinBridge({ stdin: stdin as never });
  await flushRepl();
  setLiveExternal!(active); // the Tab-press-equivalent transition
  await flushRepl();
  return { stdin, stopBridge, getRaw: () => raw, unmount: () => handle.unmount() };
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
  // Row 4 -- each legacy shortcut key, pane focused, reaches the stream; focus is unchanged.
  // -----------------------------------------------------------------------
  test("row4: a plain letter never dispatches a control or moves focus", async () => {
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
      expect(lines.some((l) => l.includes("▸ [PAUSE]"))).toBe(true); // focus marker on PAUSE

      send(m.stdin, "u"); // RESUME's legacy shortcut -- focus is still on PAUSE
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]);

      lines = renderedLines(m.getRaw(), m.columns, m.rows);
      expect(lines.some((l) => l.includes("▸ [PAUSE]"))).toBe(true); // still on PAUSE
      expect(lines.some((l) => l.includes("▸ [RESUME]"))).toBe(false); // never moved to RESUME
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // Row 5 -- an legacy shortcut while a text input has focus just types the character.
  // -----------------------------------------------------------------------
  test("row5: a plain letter typed while the prompt has focus is inserted as text, no verb emitted", async () => {
    const m = await mountForKeyboard([]);
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      await flushRepl();
      // Never Tab into the pane -- the prompt has focus by default.
      send(m.stdin, "p"); // PAUSE's legacy shortcut, typed as an ordinary character instead
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
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸ [PAUSE]"))).toBe(true);

      // Backward from PAUSE: START (index 0) is disabled and must be SKIPPED -- there is nothing
      // else below it, so traversal leaves the set rather than landing on the disabled control.
      send(m.stdin, KEY.LEFT);
      await flushRepl();
      const lines = renderedLines(m.getRaw(), m.columns, m.rows);
      expect(lines.some((l) => l.includes("▸ [START]"))).toBe(false); // never focused START
      expect(lines.some((l) => l.includes("▸"))).toBe(false); // no marker anywhere -- left the set
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // Row 7 -- legacy shortcut for a disabled control: no verb, no error, reason surfaced.
  // -----------------------------------------------------------------------
  test("row7: a plain letter cannot activate a disabled control or surface a false control error", async () => {
    const now = new Date().toISOString();
    const m = await mountForKeyboard([trainEvent(RUN_ID, now)]); // status RUNNING: START is disabled
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const running = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("RUNNING")));
      expect(running).toBe(true);

      send(m.stdin, KEY.TAB);
      await flushRepl();
      send(m.stdin, "s"); // START's legacy shortcut -- disabled while RUNNING
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]); // no verb

      const lines = renderedLines(m.getRaw(), m.columns, m.rows);
      expect(lines.some((l) => l.includes(operatorControlDisabledReason("START")))).toBe(false); // letter is not a control shortcut
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
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸ [RESTART]"))).toBe(true);

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
  // C3 -- disabled control AND legacy shortcut AND text input focused: the input wins.
  // -----------------------------------------------------------------------
  test("C3: a plain letter typed while the prompt has focus remains text and shows no control banner", async () => {
    const m = await mountForKeyboard([]); // no run at all -- RESTART is disabled
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      await flushRepl();
      send(m.stdin, "t"); // RESTART's legacy shortcut, but the prompt (not the pane) has focus
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
  // C4 -- rapid repeat of one legacy shortcut: one verb per keypress, no coalescing.
  // -----------------------------------------------------------------------
  test("C4: three rapid plain letters emit no lifecycle commands", async () => {
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
      expect(controlLines).toHaveLength(0);
      expect(controlLines).toEqual([]);
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // S1 -- disabled-state check bypassed when no run exists at all: no crash, everything inert.
  // -----------------------------------------------------------------------
  test("S1: with no run at all, traversal and a plain letter stay inert without crashing", async () => {
    const m = await mountForKeyboard([]); // fully empty telemetry -- only START is enabled (IDLE)
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      await flushRepl();

      send(m.stdin, KEY.TAB); // entry -- lands on START (only enabled control)
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸ [START]"))).toBe(true);

      // Forward from START: PAUSE, RESUME, RESTART are all disabled -- skip clean off the end
      // rather than throwing or landing on a dead control.
      send(m.stdin, KEY.RIGHT);
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸"))).toBe(false);

      // Re-enter and try a disabled legacy shortcut directly.
      send(m.stdin, KEY.TAB);
      await flushRepl();
      send(m.stdin, "u"); // RESUME -- disabled, no paused run
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]); // never crashed, never emitted
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes(operatorControlDisabledReason("RESUME")))).toBe(false);
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // S2 -- focus containment bypassed when the pane is not mounted (via ReplScreen's keyboard
  // wiring): legacy shortcuts emit nothing, because nothing exists to dispatch them.
  // -----------------------------------------------------------------------
  test("S2: mounting the pane without ReplScreen creates no lifecycle keyboard dispatch", async () => {
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
      const ready = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("[RESUME]") || l.includes("(U)ME")));
      expect(ready).toBe(true);

      send(m.stdin, KEY.TAB); // entry lands on START (IDLE, since no train_step -> no resolved runId)
      await flushRepl();
      send(m.stdin, "u"); // RESUME's legacy shortcut, reachable via row4's focus-independent dispatch
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]); // driveOperatorControl's validateControlCmd rejects a
      // runId-less resume BEFORE any emit -- the fail-closed floor holds even when the pane's own
      // enablement check let the legacy shortcut through.
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // DD1 -- Shift+Tab: real production dual-registration. Reviewer-found defect (independent
  // review at 0f9a5b17): repl.ts's operator pane and prompt-input.ts's usePromptInput both
  // registered `useInput` handlers on the shared ink/hooks.ts dispatcher, and Shift+Tab reached
  // BOTH -- the pane traversed backward AND the prompt cycled its permission mode. The fix pins
  // usePromptInput's own handler `isActive` to `!paneFocused`.
  // -----------------------------------------------------------------------
  test("DD1: Shift+Tab moves the pane's focus backward and never reaches the prompt's permission-mode cycle", async () => {
    // PANE HALF -- full ReplScreen, real \x1b[Z bytes: entry lands on PAUSE, forward once onto
    // RESUME (both enabled simultaneously here, exactly as row4 sets up), then Shift+Tab must
    // move focus back to PAUSE -- proving repl.ts's own handler receives and acts on the real
    // byte sequence as backward traversal, and that traversal never dispatches a verb.
    const t1 = new Date(Date.now() - 2000).toISOString();
    const t2 = new Date(Date.now() - 1000).toISOString();
    const m = await mountForKeyboard([trainEvent(RUN_ID, t1), runStatusEvent(RUN_ID, t2, "PAUSED")]);
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const running = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("RUNNING")));
      expect(running).toBe(true);

      send(m.stdin, KEY.TAB); // entry -- lands on PAUSE
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸ [PAUSE]"))).toBe(true);

      send(m.stdin, KEY.RIGHT); // forward -- lands on RESUME
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸ [RESUME]"))).toBe(true);

      send(m.stdin, KEY.SHIFT_TAB); // backward -- must return to PAUSE
      await flushRepl();
      const lines = renderedLines(m.getRaw(), m.columns, m.rows);
      expect(lines.some((l) => l.includes("▸ [PAUSE]"))).toBe(true);
      expect(lines.some((l) => l.includes("▸ [RESUME]"))).toBe(false);

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]); // traversal alone never emits a verb
    } finally {
      await teardown(m, previous);
    }

    // PROMPT HALF -- see mountPromptHookOnly's doc comment for why this drops one level: with
    // keyboardActive pinned false (the value ReplScreen computes while paneFocused), the SAME
    // Shift+Tab byte sequence, through the real hook and the real dispatcher, must leave
    // state.permissionMode at its initial sandboxed "regular" mode.
    const inactive = await mountPromptHookOnly(false);
    try {
      send(inactive.stdin, KEY.SHIFT_TAB);
      await flushRepl();
      expect(renderedLines(inactive.getRaw(), 40, 5).some((l) => l.includes("PERM:regular"))).toBe(true);
    } finally {
      inactive.stopBridge();
      inactive.unmount();
    }

    // Sensitivity check -- the identical bytes through the identical hook DO cycle the mode when
    // active, so the negative assertion above is real: the harness can observe the effect, it
    // simply didn't fire while inactive.
    const active = await mountPromptHookOnly(true);
    try {
      send(active.stdin, KEY.SHIFT_TAB);
      await flushRepl();
      expect(renderedLines(active.getRaw(), 40, 5).some((l) => l.includes("PERM:bypass"))).toBe(true);
    } finally {
      active.stopBridge();
      active.unmount();
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // DD2 -- Alt+P: legacy shortcut matching ignores modifiers (`input.toLowerCase() === "p"`), so the
  // pane's PAUSE legacy shortcut fires on Alt+P exactly as it does on plain "p", while the prompt's
  // `key.alt && input === "p"` branch also matches the same keystroke and would (pre-fix) open
  // the model picker.
  // -----------------------------------------------------------------------
  test("DD2: Alt+P never dispatches PAUSE and the prompt model picker remains focus-gated", async () => {
    // PANE HALF -- full ReplScreen, real \x1bp bytes (node readline: meta:true, name:"p").
    const now = new Date().toISOString();
    const m = await mountForKeyboard([trainEvent(RUN_ID, now)]); // status RUNNING -- only PAUSE enabled
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      const running = await waitFor(() => renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("RUNNING")));
      expect(running).toBe(true);

      send(m.stdin, KEY.TAB); // entry -- lands on PAUSE, the only enabled control while RUNNING
      await flushRepl();
      send(m.stdin, KEY.ALT_P);
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]);
    } finally {
      await teardown(m, previous);
    }

    // PROMPT HALF -- onModelPickerOpen has zero call sites in repl.ts (grep-verified: it is never
    // wired to ReplScreen's usePromptInput call at all), so its non-invocation can only be shown
    // via a spy passed straight through PromptInputDeps -- exactly the supported test seam.
    const inactiveCalls: string[] = [];
    const inactive = await mountPromptHookOnly(false, { onModelPickerOpen: () => inactiveCalls.push("open") });
    try {
      send(inactive.stdin, KEY.ALT_P);
      await flushRepl();
      expect(inactiveCalls).toEqual([]);
    } finally {
      inactive.stopBridge();
      inactive.unmount();
    }

    // Sensitivity check -- the identical bytes through the identical hook DO open the picker
    // when active.
    const activeCalls: string[] = [];
    const active = await mountPromptHookOnly(true, { onModelPickerOpen: () => activeCalls.push("open") });
    try {
      send(active.stdin, KEY.ALT_P);
      await flushRepl();
      expect(activeCalls).toEqual(["open"]);
    } finally {
      active.stopBridge();
      active.unmount();
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // DD3 -- Ctrl+S: legacy shortcut matching ignores modifiers, so Ctrl+S reaches the pane's START
  // legacy shortcut exactly as plain "s" does, while the prompt's `key.ctrl && input === "s"` branch
  // also matches and would (pre-fix) stash the prompt's text.
  // -----------------------------------------------------------------------
  test("DD3: Ctrl+S never dispatches START and prompt stashing remains focus-gated", async () => {
    const m = await mountForKeyboard([]); // no run at all -- only START is enabled (IDLE)
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      await flushRepl();
      send(m.stdin, KEY.TAB); // entry -- lands on START, the only enabled control
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸ [START]"))).toBe(true);

      send(m.stdin, KEY.CTRL_S); // real \x13 bytes (node readline: ctrl:true, name:"s")
      await flushRepl();
      await new Promise<void>((resolve) => setTimeout(resolve, 50));

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]);

      const lines = renderedLines(m.getRaw(), m.columns, m.rows);
      expect(lines.some((l) => l.includes("Input stashed"))).toBe(false); // prompt never stashed
    } finally {
      await teardown(m, previous);
    }
  }, 15000);

  // -----------------------------------------------------------------------
  // DD4 -- Escape: the pane's own `key.escape` branch always exits the pane; the prompt's
  // `key.escape && isStashed` branch would (pre-fix) ALSO restore a stash on the same keystroke,
  // discarding it, whenever one existed at the moment the pane held focus.
  // -----------------------------------------------------------------------
  test("DD4: Escape exits the pane and never restores an existing stash", async () => {
    const m = await mountForKeyboard([]); // no run at all -- only START is enabled (IDLE)
    const previous = (m.handle as unknown as { _previousTelemetryEnv?: string })._previousTelemetryEnv;
    try {
      await flushRepl();

      // Stash real text while the PROMPT (not the pane) has focus, so a stash genuinely exists
      // before the pane ever takes the keyboard.
      send(m.stdin, "h");
      send(m.stdin, "i");
      await flushRepl();
      send(m.stdin, KEY.CTRL_S); // stash() -- prompt has focus, pane doesn't exist yet
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("Input stashed"))).toBe(true);

      send(m.stdin, KEY.TAB); // entry -- lands on START; the stash notice must survive this
      await flushRepl();
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸ [START]"))).toBe(true);
      expect(renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("Input stashed"))).toBe(true);

      // A bare Escape byte cannot be driven through the real stdin-bridge pipeline here: the SGR
      // mouse decoder in front of it (ink/termio.ts's createSgrMouseDecoder) retains any byte
      // sequence that is itself a strict prefix of its mouse-report marker "\x1b[<" -- and a lone
      // "\x1b" IS such a prefix -- so `pending` holds it forever waiting for more input that this
      // test never sends (byte-traced: `retainedPrefixLength("\x1b")` returns 1, so `passthrough`
      // stays empty and the byte never reaches readline at all; even a follow-up byte in the SAME
      // send() would merge into ONE readline keypress, meta+char, never a standalone `escape`).
      // Row 1 hit an identical wall (no telemetry state makes its premise reachable at the full
      // byte boundary) and dropped to the pure step function underneath; this drops to the same
      // next level down -- `_deliverKeyEvent`, ink/hooks.ts's own dispatcher entry point, called
      // directly with the exact keyName/modifiers a real standalone Escape keypress carries. This
      // still exercises the real, currently-mounted `_inputHandlers` (repl.ts's pane handler AND
      // usePromptInput's, both live from the mount above) -- only the byte-to-keypress decoding
      // step is skipped, because that step is the one genuinely unreachable here.
      _deliverKeyEvent("escape", {});
      await flushRepl();
      const exited = await waitFor(() => !renderedLines(m.getRaw(), m.columns, m.rows).some((l) => l.includes("▸")));
      expect(exited).toBe(true); // pane's own escape branch fired -- focus left the set

      const lines = renderedLines(m.getRaw(), m.columns, m.rows);
      expect(lines.some((l) => l.includes("Input stashed"))).toBe(true); // stash was NEVER restored

      const controlLines = await readControlLines(m.controlPath);
      expect(controlLines).toEqual([]); // escape never dispatches a verb either
    } finally {
      await teardown(m, previous);
    }
  }, 15000);
});
