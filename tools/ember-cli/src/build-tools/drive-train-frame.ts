// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Last-leg operator probe for the /train launch-operability spec: drive the COMPILED binary
// through a pty as the operator, type `/train`, and print the rendered frame. The frame is the
// receipt. The test suite establishes that nothing else broke; this establishes what the operator
// actually sees, which no unit test can answer.
//
// Read-only on the repo: it writes nothing but its own frame files under the given out dir.
//
// RUN IT UNDER NODE, NOT BUN:
//
//   node --experimental-strip-types ./build-tools/drive-train-frame.ts <repoRoot> <binary> <outDir>
//
// Under bun, node-pty's OUTPUT works and its INPUT does not: every child.write() throws
// ERR_SOCKET_CLOSED from windowsTerminal.js while the child is still alive and painting. The
// failure is quiet in the worst way — frames render, keystrokes vanish, and the capture looks
// like a cockpit that ignores input. Neither useConpty setting changes it. Under node the same
// code types fine. The only in-repo precedent (build-tools/capture-prompt-input-243.ts) resizes
// but never types, so nothing here had exercised the input half before.
//
// @xterm/headless is CommonJS, so under node it needs the default-import interop below.

import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import xtermHeadless from "@xterm/headless";
const { Terminal } = xtermHeadless as unknown as { Terminal: new (opts: unknown) => Terminal };
import { spawn as spawnPty, type IPty } from "node-pty";

const COLS = 100;
const ROWS = 30;

function frameLines(terminal: any): string[] {
  const buffer = terminal.buffer.active;
  const lines: string[] = [];
  for (let y = 0; y < terminal.rows; y++) {
    const line = buffer.getLine(buffer.viewportY + y);
    lines.push(line ? line.translateToString(true) : "");
  }
  return lines;
}

async function settle(
  drained: () => Promise<void>,
  ms: number,
): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
  await drained();
}

async function main(): Promise<void> {
  const repoRoot = resolve(process.argv[2] ?? process.cwd());
  const binary = resolve(process.argv[3] ?? join(repoRoot, "tools/ember-cli/src/ember.exe"));
  const outDir = resolve(process.argv[4] ?? join(tmpdir(), "train-frame"));
  mkdirSync(outDir, { recursive: true });

  const home = mkdtempSync(join(tmpdir(), "ember-train-probe-"));
  const terminal: any = new (Terminal as any)({ cols: COLS, rows: ROWS, allowProposedApi: true });
  let writes = Promise.resolve();
  const raw: string[] = [];
  let child: IPty | undefined;

  const capture = (stem: string): string => {
    const text = `${frameLines(terminal).join("\n")}\n`;
    writeFileSync(join(outDir, `${stem}.frame.txt`), text, "utf8");
    return text;
  };

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
      },
      useConpty: true,
    });
    child.onExit(({ exitCode, signal }) => {
      console.log(`[probe] child exited early: code=${exitCode} signal=${signal}`);
    });
    child.onData((data) => {
      raw.push(data);
      writes = writes.then(
        () => new Promise<void>((done) => terminal.write(data, done)),
      );
    });

    // 1. the cockpit as it opens. Wait for the output to go quiet rather than for a fixed delay —
    // writing into the pty before the child has finished attaching gets ERR_SOCKET_CLOSED on
    // Windows, which reads exactly like a dead child.
    {
      const deadline = Date.now() + 30_000;
      let lastLen = 0;
      let lastChange = Date.now();
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 100));
        const len = raw.join("").length;
        if (len !== lastLen) {
          lastLen = len;
          lastChange = Date.now();
        } else if (len > 0 && Date.now() - lastChange > 1500) {
          break;
        }
      }
      await writes;
    }
    const opened = capture("01-opened");
    console.log("=== FRAME 1: cockpit opened ===");
    console.log(opened);

    // 2. type /train exactly as the operator would — char by char, as the in-repo lifecycle driver
    // does, because a bulk write races the pty's input pipe.
    for (const ch of "/train") {
      child.write(ch);
      await new Promise((r) => setTimeout(r, 20));
    }
    await settle(() => writes, 1500);
    const typed = capture("02-typed");
    console.log("=== FRAME 2: /train typed, before Enter ===");
    console.log(typed);

    child.write("\r");
    await settle(() => writes, 3000);
    const ran = capture("03-after-enter");
    console.log("=== FRAME 3: after Enter ===");
    console.log(ran);

    // The panel's command palette can require a second Enter to submit a selected entry; the
    // in-repo lifecycle driver has the same step. Capture both so the frame shows which it was.
    child.write("\r");
    await settle(() => writes, 12000);
    const ran2 = capture("04-after-second-enter");
    console.log("=== FRAME 4: after second Enter ===");
    console.log(ran2);

    writeFileSync(join(outDir, "raw.txt"), raw.join(""), "utf8");
    console.log(`frames written to ${outDir}`);
  } finally {
    child?.kill();
  }
}

await main();
