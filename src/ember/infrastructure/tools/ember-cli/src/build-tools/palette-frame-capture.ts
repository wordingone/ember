// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Machine check for the "rendered frame" undecidable row of verify_nosource_operability:
// proves the spine commands' SlashDropdown JSX becomes actual terminal cells, by driving the
// real compiled binary through ConPTY and asserting on the reconstructed frame.
//
// Byte provenance: the instrument types only "/" + a 3-char prefix per target. Every asserted
// substring (the full command name, and a description fragment the instrument never typed) can
// only have been written by the product's own renderer through the PTY.

import { mkdtempSync, rmSync, writeFileSync, mkdirSync, appendFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import xtermHeadless from "@xterm/headless";
import { spawn as spawnPty, type IPty } from "node-pty";
import { READY_OSC } from "../cli/ready-sentinel.ts";

const { Terminal } = xtermHeadless;
const COLS = 160;
const ROWS = 40;
const TIMEOUT_MS = 20_000;
/** Append-only kill ledger. An operator with a shared ledger points EMBER_KILL_RECEIPTS at it;
 *  otherwise the receipt lands beside the captured frames, so the record exists either way and
 *  no machine-specific path is baked into the repo. */
function killReceiptsPath(outDir: string): string {
  return process.env["EMBER_KILL_RECEIPTS"] ?? join(outDir, "kill-receipts.jsonl");
}

interface SpineTarget {
  /** what the instrument actually types after "/" — deliberately a strict prefix */
  typed: string;
  /** full command name that must appear rendered (instrument never typed its tail) */
  name: string;
  /** description fragment the instrument never typed at all */
  descriptionFragment: string;
}

const SPINE_TARGETS: SpineTarget[] = [
  { typed: "cus", name: "custody", descriptionFragment: "Show the current model seat classification" },
  { typed: "mod", name: "model", descriptionFragment: "Control the local owned model" },
  { typed: "ben", name: "benchmark", descriptionFragment: "Show the benchmark registry" },
  { typed: "tra", name: "train", descriptionFragment: "Preflight EMBER-02 training readiness" },
];

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function frameText(terminal: InstanceType<typeof Terminal>): string {
  const buffer = terminal.buffer.active;
  const start = buffer.viewportY;
  const lines: string[] = [];
  for (let row = 0; row < terminal.rows; row += 1) {
    lines.push(buffer.getLine(start + row)?.translateToString(true) ?? "");
  }
  return lines.join("\n");
}

async function main(): Promise<void> {
  const binary = resolve(process.argv[2] ?? "");
  const outDir = resolve(process.argv[3] ?? "");
  if (!binary || !outDir) throw new Error("usage: palette-frame-capture.ts <binary> <out-dir>");
  mkdirSync(outDir, { recursive: true });
  const rootProc = spawnSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8" });
  const repoRoot = (rootProc.stdout ?? "").trim();
  const home = mkdtempSync(join(tmpdir(), "ember-palette-capture-"));
  const terminal = new Terminal({ cols: COLS, rows: ROWS, allowProposedApi: true });
  const raw: string[] = [];
  let writes = Promise.resolve();
  let child: IPty | undefined;
  const failures: string[] = [];
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
        // This process is an instrument, not the operator's cockpit. Without this the compiled
        // binary publishes a liveness heartbeat that the watchdog reads as "the cockpit is
        // alive" -- and it lands in the MAIN repo's state dir even from an isolated worktree,
        // because the heartbeat resolves through the strict root resolver by design. A harness
        // that drives the real product inherits every side effect the product has.
        EMBER_CLI_HEADLESS_CAPTURE: "1",
      },
    });
    child.onData((data) => {
      raw.push(data);
      writes = writes.then(() => new Promise<void>((done) => terminal.write(data, done)));
    });
    child.onExit((e) => console.error(`CHILD EXIT code=${e.exitCode} signal=${e.signal}`));
    const started = Date.now();
    while (!raw.join("").includes(READY_OSC)) {
      if (Date.now() - started > TIMEOUT_MS) throw new Error("readiness marker was not observed");
      await sleep(50);
    }
    await writes;

    for (const target of SPINE_TARGETS) {
      // type "/" + prefix, one key at a time like a person
      for (const ch of `/${target.typed}`) {
        child.write(ch);
        await sleep(30);
      }
      // let the product repaint the dropdown
      await sleep(700);
      await writes;
      const frame = frameText(terminal);
      writeFileSync(join(outDir, `palette-${target.name}.frame.txt`), `${frame}\n`, "utf8");
      // Both substrings must land on ONE line, which is what a rendered dropdown ROW is.
      // Searching the whole frame independently would pass when the name is on one row and the
      // description on an unrelated one -- and it has a concrete false-pass: "model" appears
      // inside custody's own description ("the current model seat classification"), so a
      // frame-wide name search for `model` is satisfied by the custody row alone.
      const row = frame
        .split("\n")
        .find((line) => line.includes(target.name) && line.includes(target.descriptionFragment));
      if (row !== undefined) {
        console.log(`PASS ${target.name}: name + untyped description fragment on ONE rendered row`);
      } else {
        const nameLines = frame.split("\n").filter((line) => line.includes(target.name)).length;
        const descLines = frame
          .split("\n")
          .filter((line) => line.includes(target.descriptionFragment)).length;
        failures.push(
          `FAIL ${target.name}: no single row carries both (typed only "/${target.typed}"; ` +
            `rows with name=${nameLines}, rows with description=${descLines})`,
        );
        console.error(failures[failures.length - 1]);
      }
      // clear the input: backspace over the prefix and the slash
      for (let i = 0; i < target.typed.length + 1; i += 1) {
        child.write("\x7f");
        await sleep(30);
      }
      await sleep(300);
      await writes;
    }
    if (failures.length > 0) {
      throw new Error(`palette frame capture FAILED:\n${failures.join("\n")}`);
    }
    console.log("VERDICT PASS: all four spine commands rendered as terminal cells (frames in out-dir)");
  } finally {
    if (child != null) {
      // Receipt BEFORE the kill, and the selector is the PID this process spawned -- never a
      // name pattern, which could reach an operator's own cockpit or an unrelated founder's
      // pane. Written to the shared append-only ledger by a JSON serializer rather than by
      // string assembly. A failure to write the receipt does not block the kill: leaving the
      // driven binary running would be the worse outcome, so the fallback is a loud warning.
      const receipt = {
        ts: new Date().toISOString(),
        script: "src/ember/infrastructure/tools/ember-cli/src/build-tools/palette-frame-capture.ts",
        pids: [child.pid],
        match_rule: "pid returned by this process's own node-pty spawn of the binary under test",
        survivors_expected: "none",
      };
      try {
        appendFileSync(killReceiptsPath(outDir), `${JSON.stringify(receipt)}\n`, "utf8");
      } catch (err) {
        console.error(
          `[palette-frame-capture] kill receipt could not be written (${
            err instanceof Error ? err.message : String(err)
          }) -- proceeding with the kill so no driven binary is left running`,
        );
      }
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
      });
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
