// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Issue #1043: compiled-cockpit proof that a real, long activity message wraps at
// narrow and half-screen geometries without losing text or growing one-row chrome.
import { createHash } from "node:crypto";
import {
  appendFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { basename, join, resolve } from "node:path";
import xtermHeadless from "@xterm/headless";
import { spawn as spawnPty, type IPty } from "node-pty";
import { READY_OSC } from "../cli/ready-sentinel.ts";

const { Terminal } = xtermHeadless;
const TIMEOUT_MS = 20_000;
const GEOMETRIES = [
  { columns: 60, rows: 20, label: "narrow-60x20" },
  { columns: 80, rows: 24, label: "narrow-80x24" },
  { columns: 100, rows: 30, label: "half-screen-100x30" },
] as const;
const RECEIPT_NAME =
  "checkpoint-identity-changed-during-watchdog-launch-packet-verification.json";
const EXPECTED_TOKENS = [
  "Receiptlanded",
  "checkpoint-identity-changed",
  "watchdog-launch-packet-verification.json",
  "REJECTED",
] as const;

function sleep(ms: number): Promise<void> {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}

function sha256File(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function frameLines(terminal: InstanceType<typeof Terminal>): string[] {
  const buffer = terminal.buffer.active;
  const start = buffer.viewportY;
  return Array.from({ length: terminal.rows }, (_, row) =>
    buffer.getLine(start + row)?.translateToString(true) ?? "",
  );
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function frameSvg(lines: string[], columns: number, rows: number): string {
  const cellWidth = 8;
  const cellHeight = 16;
  const text = lines
    .slice(0, rows)
    .map(
      (line, index) =>
        `<text x="8" y="${(index + 1) * cellHeight}" ` +
        `fill="#e6edf3">${escapeXml(line.slice(0, columns))}</text>`,
    )
    .join("\n");
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${columns * cellWidth + 16}" ` +
      `height="${rows * cellHeight + 16}" viewBox="0 0 ${columns * cellWidth + 16} ${rows * cellHeight + 16}">`,
    `<rect width="100%" height="100%" fill="#0d1117"/>`,
    `<g font-family="Cascadia Mono,Consolas,monospace" font-size="13" xml:space="preserve">`,
    text,
    `</g>`,
    `</svg>`,
    "",
  ].join("\n");
}

function normalizedLeftPane(lines: string[], columns: number): string {
  const leftPaneColumns = Math.floor(columns / 2);
  return lines
    .map((line) => {
      // The repository's current box glyph literals arrive through ConPTY as
      // either Unicode or their legacy mojibake sequence. Prefer the actual
      // pane divider; only use the geometric half as a fallback. Starting the
      // search after column zero avoids mistaking the left box edge for the
      // divider.
      const unicodeDivider = line.indexOf("│", 1);
      const legacyDivider = line.indexOf("â”‚", 3);
      const divider = unicodeDivider >= 0 ? unicodeDivider : legacyDivider;
      if (divider >= 0) return line.slice(0, divider);
      return [...line].slice(0, leftPaneColumns).join("");
    })
    .join("")
    .replace(/\s+/gu, "");
}

async function waitFor(
  predicate: () => boolean,
  description: string,
  timeoutMs = TIMEOUT_MS,
): Promise<void> {
  const started = Date.now();
  while (!predicate()) {
    if (Date.now() - started > timeoutMs) {
      throw new Error(`timed out waiting for ${description}`);
    }
    await sleep(50);
  }
}

async function main(): Promise<void> {
  const binary = resolve(process.argv[2] ?? "");
  const outDir = resolve(process.argv[3] ?? "");
  const implementationCommit = process.argv[4] ?? "";
  if (!binary || !outDir || !/^[0-9a-f]{40}$/u.test(implementationCommit)) {
    throw new Error(
      "usage: capture-text-wrap-1043.ts <compiled-binary> <out-dir> <implementation-commit>",
    );
  }
  mkdirSync(outDir, { recursive: true });
  const repoRoot = resolve(import.meta.dir, "../../../..");
  const home = mkdtempSync(join(tmpdir(), "ember-text-wrap-1043-"));
  const receiptsDir = join(home, "receipts");
  const watchdogDir = join(receiptsDir, "watchdog");
  mkdirSync(watchdogDir, { recursive: true });
  const initial = GEOMETRIES[0];
  const terminal = new Terminal({
    cols: initial.columns,
    rows: initial.rows,
    allowProposedApi: true,
    scrollback: 0,
  });
  const raw: string[] = [];
  let writes = Promise.resolve();
  let child: IPty | undefined;
  const frameReceipts: Array<Record<string, unknown>> = [];
  try {
    child = spawnPty(binary, [], {
      name: "xterm-256color",
      cols: initial.columns,
      rows: initial.rows,
      cwd: repoRoot,
      env: {
        ...process.env,
        EMBER_HOME: home,
        EMBER_REPO_ROOT: repoRoot,
        EMBER_SOURCE_ROOT: repoRoot,
        EMBER_GPU_FREE: "1",
        EMBER_DISABLE_TERMINAL_TITLE: "1",
        EMBER_CLI_HEADLESS_CAPTURE: "1",
        EMBER_ACTIVITY_RECEIPTS_DIR: receiptsDir,
      },
    });
    child.onData((data) => {
      raw.push(data);
      writes = writes.then(() => new Promise<void>((done) => terminal.write(data, done)));
    });
    await waitFor(() => raw.join("").includes(READY_OSC), "compiled cockpit readiness");
    await writes;
    await sleep(1_000);

    writeFileSync(
      join(watchdogDir, RECEIPT_NAME),
      `${JSON.stringify({ verdict: "REJECTED" })}\n`,
      "utf8",
    );
    await waitFor(
      () => EXPECTED_TOKENS.every((token) => normalizedLeftPane(frameLines(terminal), initial.columns).includes(token)),
      "wrapped watchdog receipt in the visible frame",
    );

    for (const geometry of GEOMETRIES) {
      terminal.resize(geometry.columns, geometry.rows);
      child.resize(geometry.columns, geometry.rows);
      await sleep(800);
      await writes;
      const lines = frameLines(terminal);
      const normalized = normalizedLeftPane(lines, geometry.columns);
      const missing = EXPECTED_TOKENS.filter((token) => !normalized.includes(token));
      if (missing.length > 0) {
        throw new Error(`${geometry.label} lost wrapped activity tokens: ${missing.join(", ")}`);
      }
      const textPath = join(outDir, `${geometry.label}.frame.txt`);
      const svgPath = join(outDir, `${geometry.label}.frame.svg`);
      const text = `${lines.join("\n")}\n`;
      const svg = frameSvg(lines, geometry.columns, geometry.rows);
      writeFileSync(textPath, text, "utf8");
      writeFileSync(svgPath, svg, "utf8");
      frameReceipts.push({
        ...geometry,
        text,
        text_sha256: sha256File(textPath),
        svg,
        svg_sha256: sha256File(svgPath),
        expected_tokens_present: true,
      });
    }
    const receipt = {
      schema_version: "ember-cli-text-wrap-capture-v1",
      goal_id: "EMBER-02",
      workstream_id: "EMBER-02A",
      next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
      issue: 1043,
      implementation_commit: implementationCommit,
      binary: {
        name: basename(binary),
        sha256: sha256File(binary),
      },
      transport: "windows-conpty/node-pty",
      source_event: {
        class: "watchdog",
        filename: RECEIPT_NAME,
        verdict: "REJECTED",
      },
      frames: frameReceipts,
      verdict: "PASS",
      claim_boundary: "compiled text wrapping and one-row truncation only",
    };
    writeFileSync(
      join(outDir, "capture-receipt.json"),
      `${JSON.stringify(receipt, null, 2)}\n`,
      "utf8",
    );
    console.log(JSON.stringify(receipt));
  } catch (error) {
    await writes;
    const diagnosticLines = frameLines(terminal);
    writeFileSync(join(outDir, "failure.frame.txt"), `${diagnosticLines.join("\n")}\n`, "utf8");
    writeFileSync(join(outDir, "failure.raw.txt"), raw.join(""), "utf8");
    writeFileSync(
      join(outDir, "failure.normalized-left.txt"),
      `${normalizedLeftPane(diagnosticLines, terminal.cols)}\n`,
      "utf8",
    );
    throw error;
  } finally {
    if (child) {
      const killReceiptPath = join(outDir, "kill-receipt.json");
      appendFileSync(
        killReceiptPath,
        `${JSON.stringify({
          schema_version: "ember-cli-pid-kill-receipt-v1",
          reason: "capture-complete",
          pids: [child.pid],
          match_rule: "pid returned by this process's own node-pty spawn",
          survivors_expected: "none",
        })}\n`,
        "utf8",
      );
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
        timeout: 5_000,
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
