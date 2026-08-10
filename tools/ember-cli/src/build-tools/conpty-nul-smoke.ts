// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Issue #354: compiled-product Windows ConPTY transport falsifier at the reported 190x85 geometry.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { spawn as spawnPty, type IPty } from "node-pty";
import { requireNulFreeConptyOutput } from "./conpty-output-integrity.ts";

const COLS = 190;
const ROWS = 85;
const CAPTURE_MS = 10_000;

function sha256File(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

async function main(): Promise<void> {
  const binary = resolve(process.argv[2] ?? "");
  const outDir = resolve(process.argv[3] ?? "");
  const implementationCommit = process.argv[4] ?? "";
  const cwdClass = process.argv[5] ?? "";
  const cwd = resolve(process.argv[6] ?? "");
  if (!existsSync(binary) || !existsSync(cwd) || !/^[0-9a-f]{40}$/u.test(implementationCommit)) {
    throw new Error("usage: conpty-nul-smoke.ts <binary> <out-dir> <implementation-commit> <repository|managed-worktree> <cwd>");
  }
  if (cwdClass !== "repository" && cwdClass !== "managed-worktree") {
    throw new Error("cwd class must be repository or managed-worktree");
  }
  mkdirSync(outDir, { recursive: true });

  let raw = "";
  let child: IPty | undefined;
  let exited = false;
  try {
    child = spawnPty(binary, [], {
      name: "xterm-256color",
      cols: COLS,
      rows: ROWS,
      cwd,
      env: {
        ...process.env,
        EMBER_HOME: join(outDir, `.home-${cwdClass}`),
        EMBER_MODEL_URL: "http://127.0.0.1:1",
        EMBER_DISABLE_TERMINAL_TITLE: "1",
        EMBER_CLI_HEADLESS_CAPTURE: "1",
      },
    });
    child.onData((data) => { raw += data; });
    child.onExit(() => { exited = true; });
    await sleep(CAPTURE_MS);
    const integrity = requireNulFreeConptyOutput(raw);
    const receipt = {
      schema_version: "ember-cli-conpty-nul-smoke-v1",
      issue: 354,
      implementation_commit: implementationCommit,
      binary: { name: basename(binary), sha256: sha256File(binary) },
      transport: "windows-conpty/node-pty",
      geometry: { columns: COLS, rows: ROWS },
      cwd_class: cwdClass,
      capture_ms: CAPTURE_MS,
      transport_integrity: integrity,
      verdict: "PASS",
      claim_boundary: "compiled Windows ConPTY raw-output NUL transport integrity only",
    };
    writeFileSync(join(outDir, `conpty-nul-smoke-${cwdClass}.json`), `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
    process.stdout.write(`${JSON.stringify(receipt)}\n`);
  } finally {
    if (child && !exited) {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
        timeout: 5_000,
      });
    }
  }
}

if (import.meta.main) {
  main().then(
    () => process.exit(0),
    (error) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exit(1);
    },
  );
}
