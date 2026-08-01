// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Issue #1251: compiled-product proof for the physical Windows ConPTY pointer path.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import xtermHeadless from "@xterm/headless";
import { spawn as spawnPty, type IPty } from "node-pty";
import { READY_OSC } from "../cli/ready-sentinel.ts";
import {
  DISABLE_MOUSE_TRACKING,
  ENABLE_MOUSE_TRACKING,
  ENTER_ALT_SCREEN,
  EXIT_ALT_SCREEN,
  HIDE_CURSOR,
  SHOW_CURSOR,
} from "../ink/termio.ts";

const { Terminal } = xtermHeadless;
const COLS = 100;
const ROWS = 30;
const TIMEOUT_MS = 20_000;

function sha256File(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

async function waitFor(predicate: () => boolean, description: string): Promise<void> {
  const started = Date.now();
  while (!predicate()) {
    if (Date.now() - started > TIMEOUT_MS) throw new Error(`timed out waiting for ${description}`);
    await sleep(50);
  }
}

function frameLines(terminal: InstanceType<typeof Terminal>): string[] {
  return Array.from({ length: terminal.rows }, (_, row) =>
    terminal.buffer.active.getLine(row)?.translateToString(true) ?? "",
  );
}

function findGlyph(lines: string[], needle: string): { col: number; row: number } | undefined {
  for (let row = 0; row < lines.length; row += 1) {
    const col = lines[row]!.indexOf(needle);
    if (col >= 0) return { col, row };
  }
  return undefined;
}

function cellStyle(terminal: InstanceType<typeof Terminal>, col: number, row: number): string {
  const cell = terminal.buffer.active.getLine(row)?.getCell(col);
  if (!cell) return "missing";
  return [cell.getFgColorMode(), cell.getFgColor(), cell.getBgColorMode(), cell.getBgColor(), cell.isBold(), cell.isInverse()].join(":");
}

function sgrHover(col: number, row: number): string {
  return `\x1b[<35;${col + 1};${row + 1}M`;
}

function sgrLeftClick(col: number, row: number): string {
  return `\x1b[<0;${col + 1};${row + 1}M`;
}

function sgrLeftRelease(col: number, row: number): string {
  return `\x1b[<0;${col + 1};${row + 1}m`;
}

async function main(): Promise<void> {
  const binary = resolve(process.argv[2] ?? "");
  const outDir = resolve(process.argv[3] ?? "");
  const implementationCommit = process.argv[4] ?? "";
  const targetAction = process.argv[5] === "START" ? "START" : "PAUSE";
  if (!existsSync(binary) || !/^[0-9a-f]{40}$/u.test(implementationCommit)) {
    throw new Error("usage: pointer-conpty-smoke.ts <compiled-binary> <out-dir> <implementation-commit> [PAUSE|START]");
  }
  mkdirSync(outDir, { recursive: true });
  const repoRoot = resolve(import.meta.dirname, "../../../..");
  const home = mkdtempSync(join(tmpdir(), "ember-pointer-conpty-"));
  const telemetryPath = join(home, "telemetry.jsonl");
  const controlPath = join(home, "control.jsonl");
  const runId = "run-pointer-conpty-smoke";
  writeFileSync(telemetryPath, targetAction === "START" ? "" : `${JSON.stringify({
    ts: new Date().toISOString(),
    kind: "train_step",
    source: "journal",
    payload: { run_id: runId, step: 1, loss: 1.5 },
  })}\n`, "utf8");

  const terminal = new Terminal({ cols: COLS, rows: ROWS, allowProposedApi: true, scrollback: 0 });
  const raw: string[] = [];
  let writes = Promise.resolve();
  let child: IPty | undefined;
  let exitCode: number | undefined;
  const conptyInputCloseErrors: string[] = [];
  try {
    child = spawnPty(binary, [], {
      name: "xterm-256color",
      cols: COLS,
      rows: ROWS,
      cwd: repoRoot,
      env: {
        ...process.env,
        EMBER_HOME: home,
        EMBER_REPO_ROOT: repoRoot,
        EMBER_SOURCE_ROOT: repoRoot,
        EMBER_GPU_FREE: "1",
        EMBER_DISABLE_TERMINAL_TITLE: "1",
        EMBER_CLI_HEADLESS_CAPTURE: "1",
        EMBER_TELEMETRY_PATH: telemetryPath,
        EMBER_FINETUNE_CONTROL_PATH: controlPath,
        ...(targetAction === "START" ? { EMBER_PYTHON_BIN: join(home, "missing-python.exe") } : {}),
      },
    });
    child.onData((data) => {
      raw.push(data);
      writes = writes.then(() => new Promise<void>((done) => terminal.write(data, done)));
    });
    child.onExit(({ exitCode: code }) => { exitCode = code; });
    // node-pty 1.1 listens for errors on ConPTY's output socket but not its input socket. A fast,
    // clean Ctrl-C teardown can close the input socket while its asynchronous write callback is
    // still settling, producing an otherwise unhandled ERR_SOCKET_CLOSED. Capture that exact
    // transport race; any other input error remains terminal, and PASS still requires the child
    // exit plus all three terminal-restoration sequences.
    const inputSocket = (child as unknown as {
      _agent?: { inSocket?: { on(event: "error", listener: (error: NodeJS.ErrnoException) => void): unknown } };
    })._agent?.inSocket;
    inputSocket?.on("error", (error) => conptyInputCloseErrors.push(error.code ?? error.message));

    await waitFor(() => raw.join("").includes(READY_OSC), "compiled cockpit readiness");
    await waitFor(
      () => frameLines(terminal).some((line) => line.includes(targetAction === "START" ? "IDLE" : "RUNNING")),
      `${targetAction} telemetry frame`,
    );
    await writes;
    const before = frameLines(terminal);
    const pauseAt = findGlyph(before, `[${targetAction}]`);
    if (!pauseAt) throw new Error(`compiled frame did not expose [${targetAction}]`);

    const pointerCol = pauseAt.col + 1;
    const beforeHoverStyle = cellStyle(terminal, pointerCol, pauseAt.row);
    child.write(sgrHover(pointerCol, pauseAt.row));
    await waitFor(
      () => cellStyle(terminal, pointerCol, pauseAt.row) !== beforeHoverStyle,
      `${targetAction} hover highlight`,
    );
    child.write(targetAction === "START"
      ? sgrLeftRelease(pointerCol, pauseAt.row)
      : sgrLeftClick(pointerCol, pauseAt.row));
    if (targetAction === "START") {
      await waitFor(
        () => frameLines(terminal).some((line) => line.includes("/train") || line.includes("BLOCKED")),
        "START visible acknowledgement",
      );
    } else {
      await waitFor(() => existsSync(controlPath) && readFileSync(controlPath, "utf8").includes('"verb":"pause"'), "PAUSE control effect");
    }
    const controls = existsSync(controlPath)
      ? readFileSync(controlPath, "utf8").trim().split(/\r?\n/u).filter(Boolean).map((line) => JSON.parse(line))
      : [];
    if (targetAction === "PAUSE" && (controls.length !== 1 || controls[0]?.verb !== "pause" || controls[0]?.runId !== runId)) {
      throw new Error("compiled click did not produce exactly one bound PAUSE command");
    }
    if (targetAction === "START" && controls.length !== 0) throw new Error("START wrote the dead control channel");

    if (exitCode !== undefined) throw new Error(`compiled cockpit exited before Ctrl-C (exit=${exitCode})`);
    try {
      child.write("\x03");
    } catch (error) {
      await sleep(200);
      const detail = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
      throw new Error(`compiled cockpit PTY closed before Ctrl-C delivery (exit=${exitCode}; ${detail})`);
    }
    await waitFor(() => exitCode !== undefined, "compiled cockpit exit");
    // node-pty may publish the exit notification before its final ConPTY output callback. Give
    // that bounded tail a turn, then await the complete xterm write chain before inspecting it.
    await sleep(300);
    await writes;
    const output = raw.join("");
    const readyAt = output.indexOf(READY_OSC);
    const negotiation = [ENTER_ALT_SCREEN, HIDE_CURSOR, ENABLE_MOUSE_TRACKING].map((sequence) => output.indexOf(sequence));
    if (negotiation.some((index) => index < 0 || index > readyAt)) throw new Error("mouse/viewport negotiation was not complete before readiness");
    const teardown = [DISABLE_MOUSE_TRACKING, SHOW_CURSOR, EXIT_ALT_SCREEN].map((sequence) => output.lastIndexOf(sequence));
    if (teardown.some((index) => index < readyAt)) throw new Error(`terminal teardown sequences were not emitted after interaction (exit=${exitCode}, indexes=${teardown.join(",")})`);
    if (conptyInputCloseErrors.some((code) => code !== "ERR_SOCKET_CLOSED")) {
      throw new Error(`unexpected ConPTY input errors: ${conptyInputCloseErrors.join(",")}`);
    }

    const receipt = {
      schema_version: "ember-cli-pointer-conpty-smoke-v1",
      issue: targetAction === "START" ? 1253 : 1251,
      implementation_commit: implementationCommit,
      binary: { name: basename(binary), sha256: sha256File(binary) },
      transport: "windows-conpty/node-pty",
      geometry: { columns: COLS, rows: ROWS },
      negotiation: { alternate_screen: true, cursor_hidden: true, sgr_mouse_1003_1006: true },
      pointer: {
        hover_sent: true,
        hover_highlight_verified: true,
        click_sent: true,
        report_kind: targetAction === "START" ? "release-only" : "press",
        target: targetAction,
        terminal_cell: pauseAt,
      },
      effect: targetAction === "START"
        ? { visible_acknowledgement: true, exact_control_rows: controls.length }
        : { verb: controls[0].verb, run_id: controls[0].runId, exact_control_rows: controls.length },
      teardown: { mouse_disabled: true, cursor_shown: true, primary_screen_restored: true, exit_code: exitCode, conpty_input_close_errors: conptyInputCloseErrors },
      verdict: "PASS",
      claim_boundary: `compiled Windows ConPTY negotiation, raw hover/click delivery, ${targetAction} effect, and terminal teardown only`,
    };
    writeFileSync(join(outDir, "pointer-conpty-smoke-receipt.json"), `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
    console.log(JSON.stringify(receipt));
  } catch (error) {
    await writes;
    writeFileSync(join(outDir, "failure.raw.txt"), raw.join(""), "utf8");
    writeFileSync(join(outDir, "failure.frame.txt"), `${frameLines(terminal).join("\n")}\n`, "utf8");
    throw error;
  } finally {
    if (child && exitCode === undefined) {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore", timeout: 5_000 });
    }
    terminal.dispose();
    rmSync(home, { recursive: true, force: true });
  }
}

main().then(
  () => process.exit(0),
  (error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  },
);
