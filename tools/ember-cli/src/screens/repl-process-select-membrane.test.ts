// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// screens/repl-process-select-membrane.test.ts — #1475's two heaviest acceptance rows, driven
// through the REAL production click path (raw SGR mouse bytes -> stdin bridge -> decoder ->
// hit-test -> Box.onClick -> ReplScreen wiring -> OperatorInjector -> submitPrompt -> the slash
// dispatcher):
//
//  1. Single execution spine: START on a selected process invokes the SAME registered command
//     handler a typed `/name` invokes — asserted on the handler's own call record, not on a
//     transcript lookalike.
//  2. Membrane preservation: START on train runs the real preflight path, mints the real OFFER
//     (visible), flips the button to [CONFIRM START], and the second click dispatches the exact
//     `/train confirm <id>` the membrane minted — the consumer runs once with the offer's own
//     artifact paths, the preflight is never re-run on confirm, and the offer text stays
//     visible. The runners are injected through createTrainCommand's own test seam so NO real
//     subprocess ever runs; everything else is production code.
import { describe, expect, test } from "bun:test";
import { EventEmitter } from "node:events";
import React from "react";
import { tmpdir } from "os";
import { join } from "path";
import { access, mkdtemp, rm, unlink, writeFile } from "fs/promises";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { startStdinBridge } from "../ink/stdin-bridge.ts";
import { resetCommandRegistryForTests, setCommandRegistryDeps } from "../command-registry.ts";
import { startTelemetryWatch } from "../services/telemetry-watch.ts";
import { createTrainCommand } from "../commands/train.ts";
import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
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

function findGlyph(lines: string[], needle: string): { col: number; row: number } | undefined {
  for (let row = 0; row < lines.length; row++) {
    const col = lines[row]!.indexOf(needle);
    if (col >= 0) return { col, row };
  }
  return undefined;
}

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

function sgrLeftClick(col: number, row: number): string {
  return `\x1b[<0;${col + 1};${row + 1}M`;
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
  previousTelemetryEnv: string | undefined;
}

/** Mounts a real ReplScreen against a stubbed registry (set by the caller BEFORE this runs) with
 *  a seeded-empty telemetry file, wiring a FakeStdin through the real stdin bridge with BOTH the
 *  SGR mouse decoder and real keypress decoding live — this file drives mouse and keyboard. */
async function mountRepl(columns: number, rows: number): Promise<Mounted> {
  const telemetryPath = join(tmpdir(), `test-psm-telemetry-${Date.now()}-${Math.random()}.jsonl`);
  const controlPath = join(tmpdir(), `test-psm-control-${Date.now()}-${Math.random()}.jsonl`);
  await writeFile(telemetryPath, "");
  const previousTelemetryEnv = process.env["EMBER_TELEMETRY_PATH"];
  process.env["EMBER_TELEMETRY_PATH"] = telemetryPath;

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
  const stopBridge = startStdinBridge({ stdin: stdin as never });
  return { handle, stdin, stopBridge, telemetryPath, controlPath, columns, rows, getRaw: () => raw, previousTelemetryEnv };
}

async function teardown(m: Mounted): Promise<void> {
  m.stopBridge();
  m.handle.unmount();
  if (m.previousTelemetryEnv === undefined) delete process.env["EMBER_TELEMETRY_PATH"];
  else process.env["EMBER_TELEMETRY_PATH"] = m.previousTelemetryEnv;
  resetCommandRegistryForTests();
  startTelemetryWatch().stop();
  await Promise.all([
    unlink(m.telemetryPath).catch(() => {}),
    unlink(m.controlPath).catch(() => {}),
  ]);
}

function click(m: Mounted, at: { col: number; row: number }): void {
  m.stdin.emit("data", Buffer.from(sgrLeftClick(at.col + 1, at.row)));
}

async function waitLines(
  m: Mounted,
  predicate: (lines: string[]) => boolean,
  attempts: number = 40,
): Promise<string[]> {
  let lines: string[] = [];
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await new Promise<void>((resolve) => setTimeout(resolve, 50));
    await flushRepl();
    lines = renderedLines(m.getRaw(), m.columns, m.rows);
    if (predicate(lines)) return lines;
  }
  return lines;
}

/** Drives the shared opening of both tests: toggle -> pick `name` -> return the armed frame. */
async function selectProcessByClicks(m: Mounted, name: string): Promise<string[]> {
  let lines = await waitLines(m, (l) => l.some((line) => line.includes("[SELECT PROCESS")));
  const toggleAt = findGlyph(lines, "[SELECT PROCESS");
  expect(toggleAt).toBeDefined();
  click(m, { col: toggleAt!.col + 1, row: toggleAt!.row });
  lines = await waitLines(m, (l) =>
    findGlyphFrom(l, name, toggleAt!.row + 1, Math.max(0, toggleAt!.col - 2)) !== undefined);
  const optionAt = findGlyphFrom(lines, name, toggleAt!.row + 1, Math.max(0, toggleAt!.col - 2));
  expect(optionAt).toBeDefined();
  click(m, { col: optionAt!.col + 1, row: optionAt!.row });
  return waitLines(m, (l) => l.some((line) => line.includes(`[PROCESS: ${name}`)));
}

describe("#1475 START dispatch rides the single execution spine", () => {
  test("click-START and typed /name invoke the SAME registered handler, same session", async () => {
    resetCommandRegistryForTests();
    startTelemetryWatch().stop();
    const calls: Array<{ args: string; sessionId: string }> = [];
    const probe: RegistryCommand = {
      name: "smoketest",
      description: "dispatch-equality probe process",
      isEnabled: () => true,
      execute: async (args: string, ctx: CommandContext) => {
        calls.push({ args, sessionId: ctx.sessionId });
        return { type: "message" as const, message: `PROBE-RAN-${calls.length}` };
      },
    };
    setCommandRegistryDeps({ getBuiltinCommands: () => [probe] });
    const m = await mountRepl(100, 40);
    try {
      let lines = await selectProcessByClicks(m, "smoketest");
      const startAt = findGlyph(lines, "[START]");
      expect(startAt).toBeDefined();

      click(m, { col: startAt!.col + 1, row: startAt!.row });
      lines = await waitLines(m, (l) => l.some((line) => line.includes("PROBE-RAN-1")));
      expect(lines.some((line) => line.includes("PROBE-RAN-1"))).toBe(true);
      expect(calls).toHaveLength(1);

      // The typed path, through the same mounted session: identical handler, identical session.
      m.stdin.emit("data", Buffer.from("/smoketest "));
      await flushRepl();
      m.stdin.emit("data", Buffer.from("\r"));
      lines = await waitLines(m, (l) => l.some((line) => line.includes("PROBE-RAN-2")));
      expect(lines.some((line) => line.includes("PROBE-RAN-2"))).toBe(true);

      expect(calls).toHaveLength(2);
      expect(calls[1]!.sessionId).toBe(calls[0]!.sessionId);
      expect(calls[1]!.args).toBe(calls[0]!.args);
    } finally {
      await teardown(m);
    }
  }, 25000);
});

describe("#1475 the /train confirm-only membrane is preserved through START", () => {
  test("START mints the real OFFER; [CONFIRM START] spends it through /train confirm <id>", async () => {
    resetCommandRegistryForTests();
    startTelemetryWatch().stop();

    const artifactDir = await mkdtemp(join(tmpdir(), "psm-train-authority-"));
    const certificatePath = join(artifactDir, "certificate.json");
    const ledgerPath = join(artifactDir, "declaration-ledger.jsonl");
    const runSpecPath = join(artifactDir, "run-spec.json");
    await Promise.all([
      writeFile(certificatePath, `${JSON.stringify({ kind: "certificate" })}\n`),
      writeFile(ledgerPath, `${JSON.stringify({ kind: "declaration" })}\n`),
      writeFile(runSpecPath, `${JSON.stringify({ kind: "run-spec" })}\n`),
    ]);

    const preflightCalls: string[][] = [];
    const consumerCalls: string[][] = [];
    const trainCmd = createTrainCommand({
      runLaunchPacket: (_executable, args) => {
        preflightCalls.push(args);
        return {
          status: 0,
          stdout: `${JSON.stringify({
            record: "launch-packet-summary",
            overall_ready: true,
            named_ember02_command: { command: "python run_vertical_slice.py --config c.json" },
          })}\n`,
        };
      },
      runCertifiedLaunch: (_executable, args) => {
        consumerCalls.push(args);
        return {
          status: 0,
          stdout: `${JSON.stringify({ execution_receipt: "receipt-psm-1", artifact_root: "artifacts/psm-run" })}\n`,
        };
      },
      repoRoot: artifactDir,
      pythonBin: "python-never-spawned",
      certificatePath,
      declarationLedgerPath: ledgerPath,
      runSpecPath,
    });
    setCommandRegistryDeps({ getBuiltinCommands: () => [trainCmd] });

    const m = await mountRepl(100, 40);
    try {
      let lines = await selectProcessByClicks(m, "train");
      const startAt = findGlyph(lines, "[START]");
      expect(startAt).toBeDefined();

      // First START: the command's own preflight runs, the membrane mints a single-use OFFER,
      // and the offer text (with its typed-confirm spelling) is visible in the transcript.
      click(m, { col: startAt!.col + 1, row: startAt!.row });
      lines = await waitLines(m, (l) => l.some((line) => line.includes("[CONFIRM START]")));
      expect(preflightCalls).toHaveLength(1);
      expect(consumerCalls).toHaveLength(0);
      expect(lines.some((line) => line.includes("OFFER train-"))).toBe(true);
      expect(lines.some((line) => line.includes("/train confirm"))).toBe(true);
      const confirmAt = findGlyph(lines, "[CONFIRM START]");
      expect(confirmAt).toBeDefined();

      // Second START — the explicit confirm act: the consumer runs exactly once, with the
      // offer's own resolved artifact paths, and the preflight is NEVER re-run on confirm.
      click(m, { col: confirmAt!.col + 1, row: confirmAt!.row });
      lines = await waitLines(m, (l) =>
        l.some((line) => line.includes("certified bounded canary process completed.")));
      expect(lines.some((line) => line.includes("certified bounded canary process completed."))).toBe(true);
      expect(consumerCalls).toHaveLength(1);
      expect(consumerCalls[0]!.slice(1)).toEqual([
        "--root", artifactDir,
        "--certificate", certificatePath,
        "--declaration-ledger", ledgerPath,
        "--run-spec", runSpecPath,
      ]);
      expect(preflightCalls).toHaveLength(1);

      // The offer/refusal text remains visible after the confirm, and the spent offer disarms
      // the confirm stage — START is back to its armed label, never a stale confirm button.
      expect(lines.some((line) => line.includes("OFFER train-"))).toBe(true);
      expect(lines.some((line) => line.includes("[CONFIRM START]"))).toBe(false);
      expect(lines.some((line) => line.includes("[START]"))).toBe(true);

      // The legacy control channel was never touched by any leg of this flow.
      await expect(access(m.controlPath)).rejects.toThrow();
    } finally {
      await teardown(m);
      await rm(artifactDir, { recursive: true, force: true }).catch(() => {});
    }
  }, 25000);
});
