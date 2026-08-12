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
import { createHash } from "node:crypto";
import React from "react";
import { tmpdir } from "os";
import { join } from "path";
import { access, mkdir, mkdtemp, rm, unlink, writeFile } from "fs/promises";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { startStdinBridge } from "../ink/stdin-bridge.ts";
import { resetCommandRegistryForTests, setCommandRegistryDeps } from "../command-registry.ts";
import { startTelemetryWatch } from "../services/telemetry-watch.ts";
import { createTrainCommand, outstandingTrainOfferForSession } from "../commands/train.ts";
import { buildProcessOptions, startActivation } from "../services/process-select.ts";
import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import { ReplScreen } from "./repl.ts";

const AUTHORITY_BINDING_KEYS = [
  "benchmark_registry_sha256", "board_receipt_sha256", "checkout_sha256",
  "cli_binary_sha256", "config_sha256", "failure_class_ledger_sha256",
  "input_authority_sha256", "launch_packet_sha256", "root_summary_sha256",
  "seat_sha256", "subject_manifest_sha256", "tokenizer_sha256",
] as const;

async function writeExternalAuthority(
  custodyRoot: string,
  runId: string,
  runSpec: Record<string, unknown>,
): Promise<{ certificatePath: string; ledgerPath: string; runSpecPath: string }> {
  const leaf = join(custodyRoot, runId, "launch-authority");
  await mkdir(leaf, { recursive: true });
  const certificate = {
    kind: "certificate",
    ...Object.fromEntries(
      AUTHORITY_BINDING_KEYS.map((key, index) => [key, index.toString(16).padStart(64, "0")]),
    ),
  };
  const files = {
    "certificate.json": `${JSON.stringify(certificate)}\n`,
    "declaration-ledger.jsonl": `${JSON.stringify({ kind: "declaration" })}\n`,
    "run-spec.json": `${JSON.stringify(runSpec)}\n`,
    "sha-binding-map.json": `${JSON.stringify(Object.fromEntries(
      AUTHORITY_BINDING_KEYS.map((key) => [
        key,
        `sha256:${certificate[key]};path:governed-source:${key}`,
      ]),
    ))}\n`,
  };
  await Promise.all(Object.entries(files).map(([name, bytes]) => writeFile(join(leaf, name), bytes)));
  const hashes = Object.fromEntries(Object.entries(files).map(([name, bytes]) => [
    name,
    createHash("sha256").update(bytes).digest("hex"),
  ]));
  await writeFile(join(leaf, "launch-authority-custody.json"), `${JSON.stringify({
    custody_kind: "external-run-scoped",
    files: hashes,
    run_id: runId,
    schema_version: "ember-launch-authority-external-custody-v1",
    training_executed: false,
  })}\n`);
  return {
    certificatePath: join(leaf, "certificate.json"),
    ledgerPath: join(leaf, "declaration-ledger.jsonl"),
    runSpecPath: join(leaf, "run-spec.json"),
  };
}

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
  runSpecPath: string;
  columns: number;
  rows: number;
  getRaw: () => string;
  previousTelemetryEnv: string | undefined;
}

/** Mounts a real ReplScreen against a stubbed registry (set by the caller BEFORE this runs) with
 *  a seeded-empty telemetry file, wiring a FakeStdin through the real stdin bridge with BOTH the
 *  SGR mouse decoder and real keypress decoding live — this file drives mouse and keyboard. */
async function mountRepl(
  columns: number,
  rows: number,
  operatorReceiptEvents?: Array<{ event: string; detail?: string }>,
  authorityMode: "external" | "standalone-leaf" = "external",
): Promise<Mounted> {
  const telemetryPath = join(tmpdir(), `test-psm-telemetry-${Date.now()}-${Math.random()}.jsonl`);
  const controlPath = join(tmpdir(), `test-psm-control-${Date.now()}-${Math.random()}.jsonl`);
  const authorityRoot = join(tmpdir(), `test-psm-authority-${Date.now()}-${Math.random()}`);
  const authorityRunId = "process-review-run";
  const runSpecPath = join(authorityRoot, authorityRunId, "launch-authority", "run-spec.json");
  await mkdir(join(authorityRoot, authorityRunId, "launch-authority"), { recursive: true });
  await writeFile(telemetryPath, "");
  await writeFile(runSpecPath, JSON.stringify({
    schema_version: "ember-certified-train-run-v1",
    run_id: "process-review-run",
    seed: 83,
    requested_scope: { optimizer_steps: 2, write_budget_bytes: 4096 },
  }));
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
        ...(authorityMode === "external" ? {
          EMBER_LAUNCH_AUTHORITY_CUSTODY_ROOT: authorityRoot,
          EMBER_LAUNCH_AUTHORITY_RUN_ID: authorityRunId,
        } : {
          EMBER_RUN_SPEC_PATH: runSpecPath,
        }),
      },
      ...(operatorReceiptEvents ? {
        operatorReceiptWriter: {
          filePath: join(tmpdir(), "test-psm-operator-receipts.jsonl"),
          append(event: string, detail?: string) {
            operatorReceiptEvents.push({ event, detail });
          },
        },
      } : {}),
      onExit: () => {},
    }),
  );
  const handle = mountInk(element, {
    stream: { write(chunk: string) { raw += chunk; } },
    stdout: { columns, rows },
  });
  const stdin = new FakeStdin();
  const stopBridge = startStdinBridge({ stdin: stdin as never });
  return { handle, stdin, stopBridge, telemetryPath, controlPath, runSpecPath, columns, rows, getRaw: () => raw, previousTelemetryEnv };
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
    unlink(m.runSpecPath).catch(() => {}),
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
    const alternateCalls: string[] = [];
    const probe: RegistryCommand = {
      name: "smoketest",
      description: "dispatch-equality probe process",
      isEnabled: () => true,
      execute: async (args: string, ctx: CommandContext) => {
        calls.push({ args, sessionId: ctx.sessionId });
        return { type: "message" as const, message: `PROBE-RAN-${calls.length}` };
      },
    };
    const alternate: RegistryCommand = {
      name: "alternate",
      description: "selection-drift adversary",
      isEnabled: () => true,
      execute: async () => {
        alternateCalls.push("ran");
        return { type: "message" as const, message: "ALTERNATE-RAN" };
      },
    };
    setCommandRegistryDeps({ getBuiltinCommands: () => [probe, alternate] });
    const m = await mountRepl(100, 40);
    try {
      let lines = await selectProcessByClicks(m, "smoketest");
      const startAt = findGlyph(lines, "[START]");
      expect(startAt).toBeDefined();

      click(m, { col: startAt!.col + 1, row: startAt!.row });
      lines = await waitLines(m, (l) => l.some((line) => line.includes("START PARAMETERS")));
      const titleAt = findGlyph(lines, "START PARAMETERS");
      expect(titleAt).toBeDefined();
      // Change the live selection after review opened. Confirmation must still dispatch the
      // captured smoketest activation, never recompute from this new selection.
      const selectedAt = findGlyph(lines, "[PROCESS: smoketest");
      expect(selectedAt).toBeDefined();
      click(m, { col: selectedAt!.col + 1, row: selectedAt!.row });
      lines = await waitLines(m, (l) => findGlyphFrom(l, "alternate", selectedAt!.row + 1, 0) !== undefined);
      const alternateAt = findGlyphFrom(lines, "alternate", selectedAt!.row + 1, 0);
      expect(alternateAt).toBeDefined();
      click(m, { col: alternateAt!.col + 1, row: alternateAt!.row });
      lines = await waitLines(m, (l) => l.some((line) => line.includes("[PROCESS: alternate")));
      const refreshedTitleAt = findGlyph(lines, "START PARAMETERS");
      expect(refreshedTitleAt).toBeDefined();
      const confirmAt = findGlyphFrom(lines, "CONFIRM START", refreshedTitleAt!.row + 1, 0);
      expect(confirmAt).toBeDefined();
      click(m, { col: confirmAt!.col + 1, row: confirmAt!.row });
      lines = await waitLines(m, (l) => l.some((line) => line.includes("PROBE-RAN-1")));
      expect(lines.some((line) => line.includes("PROBE-RAN-1"))).toBe(true);
      expect(calls).toHaveLength(1);
      expect(alternateCalls).toHaveLength(0);

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

describe("#1488 the /train confirm-only membrane is preserved through START", () => {
  test("standalone or tracked run-spec authority is refused at mounted CONFIRM START", async () => {
    resetCommandRegistryForTests();
    startTelemetryWatch().stop();
    const repoRoot = await mkdtemp(join(tmpdir(), "psm-1506-refusal-repo-"));
    const custodyRoot = await mkdtemp(join(tmpdir(), "psm-1506-refusal-custody-"));
    const authorityRunId = "train-refusal-run";
    await writeExternalAuthority(custodyRoot, authorityRunId, {
      schema_version: "ember-certified-train-run-v1",
      run_id: authorityRunId,
      seed: 83,
      requested_scope: { optimizer_steps: 2, write_budget_bytes: 4096 },
    });
    let consumerCalls = 0;
    const trainCmd = createTrainCommand({
      repoRoot,
      launchAuthorityCustodyRoot: custodyRoot,
      launchAuthorityRunId: authorityRunId,
      runLaunchPacket: () => ({
        status: 0,
        stdout: `${JSON.stringify({
          record: "launch-packet-summary",
          overall_ready: true,
          named_ember02_command: { command: "never-executed" },
        })}\n`,
      }),
      runCertifiedLaunch: () => {
        consumerCalls += 1;
        return { status: 0, stdout: "{}" };
      },
    });
    setCommandRegistryDeps({ getBuiltinCommands: () => [trainCmd] });
    const receiptEvents: Array<{ event: string; detail?: string }> = [];
    const m = await mountRepl(100, 40, receiptEvents, "standalone-leaf");
    try {
      let lines = await selectProcessByClicks(m, "train");
      const startAt = findGlyph(lines, "[START]");
      expect(startAt).toBeDefined();
      click(m, { col: startAt!.col + 1, row: startAt!.row });
      lines = await waitLines(m, (rows) => rows.some((line) => line.includes("[CONFIRM START]")));
      const confirmAt = findGlyph(lines, "[CONFIRM START]");
      expect(confirmAt).toBeDefined();
      click(m, { col: confirmAt!.col + 1, row: confirmAt!.row });
      lines = await waitLines(m, (rows) => rows.some((line) =>
        line.includes("external run-scoped launch-authority custody root and run id are required")));

      expect(lines.some((line) => line.includes("START PARAMETERS"))).toBe(false);
      expect(consumerCalls).toBe(0);
      expect(receiptEvents.some((row) =>
        row.event === "control_refused" && row.detail?.includes("external run-scoped"))).toBe(true);
    } finally {
      await teardown(m);
      await rm(repoRoot, { recursive: true, force: true }).catch(() => {});
      await rm(custodyRoot, { recursive: true, force: true }).catch(() => {});
    }
  }, 25000);

  test("click-only SELECT -> START -> CONFIRM spends the exact single-use offer", async () => {
    resetCommandRegistryForTests();
    startTelemetryWatch().stop();

    const artifactDir = await mkdtemp(join(tmpdir(), "psm-train-repo-"));
    const custodyRoot = await mkdtemp(join(tmpdir(), "psm-train-authority-"));
    const authorityRunId = "train-membrane-run";
    const { certificatePath, ledgerPath, runSpecPath } = await writeExternalAuthority(
      custodyRoot,
      authorityRunId,
      {
        schema_version: "ember-certified-train-run-v1",
        run_id: authorityRunId,
        seed: 83,
        requested_scope: { optimizer_steps: 2, write_budget_bytes: 4096 },
      },
    );

    const preflightCalls: string[][] = [];
    const consumerCalls: string[][] = [];
    const operatorReceiptEvents: Array<{ event: string; detail?: string }> = [];
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
      launchAuthorityCustodyRoot: custodyRoot,
      launchAuthorityRunId: authorityRunId,
    });
    setCommandRegistryDeps({ getBuiltinCommands: () => [trainCmd] });

    const m = await mountRepl(100, 40, operatorReceiptEvents);
    try {
      // Unarmed START is clickable only to surface its named refusal.
      let lines = await waitLines(m, (l) => l.some((line) => line.includes("[START]")));
      const unarmedAt = findGlyph(lines, "[START]");
      expect(unarmedAt).toBeDefined();
      click(m, { col: unarmedAt!.col + 1, row: unarmedAt!.row });
      lines = await waitLines(m, (l) => l.some((line) => line.includes("select a process first")));
      expect(lines.some((line) => line.includes("START PARAMETERS"))).toBe(false);
      expect(preflightCalls).toHaveLength(0);
      expect(consumerCalls).toHaveLength(0);
      expect(operatorReceiptEvents.filter((row) => row.event === "start_parameters_confirmed")).toHaveLength(0);

      lines = await selectProcessByClicks(m, "train");
      const startAt = findGlyph(lines, "[START]");
      expect(startAt).toBeDefined();

      // First START: the command's own preflight runs, the membrane mints a single-use OFFER,
      // and the offer text (with its typed-confirm spelling) is visible in the transcript.
      click(m, { col: startAt!.col + 1, row: startAt!.row });
      lines = await waitLines(m, (l) => l.some((line) => line.includes("[CONFIRM START]")));
      expect(preflightCalls).toHaveLength(1);
      expect(consumerCalls).toHaveLength(0);
      expect(lines.some((line) => line.includes("START PARAMETERS"))).toBe(false);
      expect(lines.some((line) => line.includes("OFFER train-"))).toBe(true);
      expect(lines.some((line) => line.includes("/train confirm"))).toBe(true);
      const confirmAt = findGlyph(lines, "[CONFIRM START]");
      expect(confirmAt).toBeDefined();

      // Second START — the explicit confirm act: the consumer runs exactly once, with the
      // offer's own resolved artifact paths, and the preflight is NEVER re-run on confirm.
      click(m, { col: confirmAt!.col + 1, row: confirmAt!.row });
      lines = await waitLines(m, (l) => l.some((line) => line.includes("START PARAMETERS")));
      const dialogTitleAt = findGlyph(lines, "START PARAMETERS");
      expect(dialogTitleAt).toBeDefined();
      const dialogConfirmAt = findGlyphFrom(lines, "CONFIRM START", dialogTitleAt!.row + 1, 0);
      expect(dialogConfirmAt).toBeDefined();
      click(m, { col: dialogConfirmAt!.col + 1, row: dialogConfirmAt!.row });
      lines = await waitLines(m, (l) =>
        l.some((line) => line.includes("certified bounded canary process completed.")));
      expect(lines.some((line) => line.includes("certified bounded canary process completed."))).toBe(true);
      expect(lines.some((line) => line.includes("START PARAMETERS"))).toBe(false);
      expect(consumerCalls).toHaveLength(1);
      expect(consumerCalls[0]![1]).toBe("--root");
      expect(consumerCalls[0]![2]).toBe(artifactDir);
      expect(consumerCalls[0]![3]).toBe("--certificate");
      expect(consumerCalls[0]![5]).toBe("--declaration-ledger");
      expect(consumerCalls[0]![7]).toBe("--run-spec");
      const consumerLeaf = join(consumerCalls[0]![4]!, "..");
      expect(consumerCalls[0]![4]).toEndWith("certificate.json");
      expect(consumerCalls[0]![6]).toBe(join(consumerLeaf, "declaration-ledger.jsonl"));
      expect(consumerCalls[0]![8]).toBe(join(consumerLeaf, "run-spec.json"));
      expect(consumerCalls[0]![4]).toBe(certificatePath);
      expect(preflightCalls).toHaveLength(1);
      expect(operatorReceiptEvents.filter((row) => row.event === "control_confirmed")).toHaveLength(1);

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
      await rm(custodyRoot, { recursive: true, force: true }).catch(() => {});
    }
  }, 25000);

  test("one render-captured CONFIRM activation is single-use", async () => {
    const artifactDir = await mkdtemp(join(tmpdir(), "psm-train-repeat-repo-"));
    const custodyRoot = await mkdtemp(join(tmpdir(), "psm-train-repeat-authority-"));
    const authorityRunId = "train-repeat-run";
    const { certificatePath, ledgerPath, runSpecPath } = await writeExternalAuthority(
      custodyRoot,
      authorityRunId,
      {
        schema_version: "ember-certified-train-run-v1",
        run_id: authorityRunId,
        seed: 83,
        requested_scope: { optimizer_steps: 2, write_budget_bytes: 4096 },
      },
    );

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
          stdout: `${JSON.stringify({ execution_receipt: "receipt-psm-repeat", artifact_root: "artifacts/psm-repeat" })}\n`,
        };
      },
      repoRoot: artifactDir,
      pythonBin: "python-never-spawned",
      launchAuthorityCustodyRoot: custodyRoot,
      launchAuthorityRunId: authorityRunId,
    });
    const ctx: CommandContext = {
      sessionId: "issue1488-repeat",
      mode: "interactive",
      cwd: artifactDir,
    };

    try {
      await trainCmd.execute("", ctx);
      const offer = outstandingTrainOfferForSession(ctx.sessionId);
      expect(offer).toBeDefined();
      expect(offer!.runSpec).toBe(runSpecPath);
      const selected = buildProcessOptions([trainCmd])[0];
      expect(selected).toBeDefined();

      // This is the exact activation captured by the rendered CONFIRM button. Reusing that
      // same captured click context must hit the membrane's spent-offer refusal, never a
      // newly inferred START action.
      const captured = startActivation(selected, { process: "train", offerId: offer!.offerId });
      expect(captured).toEqual({ kind: "dispatch", text: `/train confirm ${offer!.offerId}` });
      if (captured.kind !== "dispatch") throw new Error("expected captured train confirmation");
      const args = captured.text.slice("/train ".length);
      const first = await trainCmd.execute(args, ctx);
      const second = await trainCmd.execute(args, ctx);

      expect(first?.message).toContain("certified bounded canary process completed");
      expect(second?.message).toContain("no outstanding train-launch offer");
      expect(preflightCalls).toHaveLength(1);
      expect(consumerCalls).toHaveLength(1);
      expect(consumerCalls[0]![2]).toBe(artifactDir);
      expect(consumerCalls[0]![4]).toBe(certificatePath);
      expect(consumerCalls[0]![4]).toEndWith("certificate.json");
      expect(consumerCalls[0]![6]).toEndWith("declaration-ledger.jsonl");
      expect(consumerCalls[0]![8]).toEndWith("run-spec.json");
    } finally {
      await rm(artifactDir, { recursive: true, force: true }).catch(() => {});
      await rm(custodyRoot, { recursive: true, force: true }).catch(() => {});
    }
  });
});
