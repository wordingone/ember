// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// build-tools/wait-ready-proof.ts — proof driver for the readiness sentinel.
//
// Boots a compiled ember-cli binary through Windows ConPTY and blocks until the
// product-emitted READY_OSC sentinel (cli/ready-sentinel.ts) appears in the raw
// byte stream, the child exits, or the deadline lapses. Prints a single verdict
// line so both directions of the gate are demonstrable:
//   READY <ms>        — sentinel observed in the stream (positive proof)
//   NOT-READY exit=N  — child exited before ever becoming ready (negative proof)
//   NOT-READY timeout — deadline lapsed without the sentinel (negative proof)
// Exit code: 0 only for READY.
//
// Usage: bun run wait-ready-proof.ts --binary <path> [--timeout-ms 15000] [--broken]
//   --broken strips EMBER_GPU_FREE (and any model-seat env) so the seat gate
//   refuses the boot — a genuinely broken boot, not a simulated one.

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn as spawnPty } from "node-pty";
import { READY_OSC } from "../cli/ready-sentinel.ts";

function parseArgs(argv: string[]): { binary: string; timeoutMs: number; broken: boolean } {
  let binary = "";
  let timeoutMs = 15_000;
  let broken = false;
  for (let index = 0; index < argv.length; index++) {
    if (argv[index] === "--binary") binary = argv[++index] ?? "";
    else if (argv[index] === "--timeout-ms") timeoutMs = Number(argv[++index] ?? "");
    else if (argv[index] === "--broken") broken = true;
    else throw new Error(`unknown argument: ${argv[index]}`);
  }
  if (binary === "" || !Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new Error("--binary is required and --timeout-ms must be a positive number");
  }
  return { binary: resolve(binary), timeoutMs, broken };
}

export async function waitReadyProof(argv: string[]): Promise<void> {
  if (process.platform !== "win32") throw new Error("readiness proof requires Windows ConPTY");
  const { binary, timeoutMs, broken } = parseArgs(argv);
  const home = mkdtempSync(join(tmpdir(), "ember-ready-proof-"));
  const env: Record<string, string> = {
    ...(process.env as Record<string, string>),
    EMBER_HOME: home,
    EMBER_DISABLE_TERMINAL_TITLE: "1",
  };
  if (broken) {
    // Genuine broken boot: with no GPU_FREE grant, no model URL, and no owned
    // identity, resolveModelSeat refuses the seat and main() exits 1 before
    // any TUI mounts — the sentinel arm point is never reached.
    delete env["EMBER_GPU_FREE"];
    delete env["EMBER_MODEL_URL"];
    env["EMBER_HOME"] = join(home, "empty-config");
  } else {
    env["EMBER_GPU_FREE"] = "1";
  }

  const started = Date.now();
  const child = spawnPty(binary, [], {
    name: "xterm-256color",
    cols: 80,
    rows: 24,
    cwd: process.cwd(),
    env,
  });

  let buffered = "";
  let settled = false;
  const verdict = await new Promise<string>((resolveVerdict) => {
    const timer = setTimeout(() => {
      if (!settled) { settled = true; resolveVerdict("NOT-READY timeout"); }
    }, timeoutMs);
    child.onData((data) => {
      buffered += data;
      if (!settled && buffered.includes(READY_OSC)) {
        settled = true;
        clearTimeout(timer);
        resolveVerdict(`READY ${Date.now() - started}`);
      }
    });
    child.onExit(({ exitCode }) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        resolveVerdict(`NOT-READY exit=${exitCode}`);
      }
    });
  });

  // Terminate only the exact PTY root PID and its owned tree (same discipline
  // as capture-prompt-input-243.ts); never enumerate or target foreign PIDs.
  Bun.spawnSync(["taskkill", "/PID", String(child.pid), "/T", "/F"], {
    stdout: "ignore",
    stderr: "ignore",
  });
  rmSync(home, { recursive: true, force: true });

  process.stdout.write(`${verdict}\n`);
  process.stdout.write(`stream-bytes=${Buffer.byteLength(buffered)}\n`);
  const tail = buffered.slice(-300).replace(/\u001b/g, "\\e");
  process.stdout.write(`tail: ${tail}\n`);
  if (!verdict.startsWith("READY")) process.exit(1);
}

if (import.meta.main) {
  waitReadyProof(Bun.argv.slice(2)).then(
    () => process.exit(0),
    (error) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exit(1);
    },
  );
}
