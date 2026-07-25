// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "node:crypto";
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
} from "node:path";
import { Terminal } from "@xterm/headless";
import { spawn as spawnPty, type IPty } from "node-pty";

const SHA256 = /^[0-9a-f]{64}$/;
const COMMIT = /^[0-9a-f]{40}$/;
const EXPECTED_COLUMNS = [80, 40, 80] as const;
const ROWS = 24;

export interface ClosedPromptRegion {
  top: number;
  bottom: number;
  contentColumns: number;
}

export interface CaptureStageInput {
  columns: number;
  rows: number;
  rawPath: string;
  privateRawLocator: string;
  privateRawBytes: Uint8Array;
  redactions: HostPathRedaction[];
  framePath: string;
  rawBytes: Uint8Array;
  frameText: string;
  region: ClosedPromptRegion;
}

export interface CaptureReceiptInput {
  sourceCommit: string;
  binaryArtifact: string;
  binarySha256Before: string;
  binarySha256After: string;
  stages: CaptureStageInput[];
}

function sha256(bytes: Uint8Array | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}
export interface HostPathRedaction {
  sourceSha256: string;
  replacement: string;
  occurrences: number;
}

export function redactHostPaths(
  privateBytes: Uint8Array,
  hostPaths: string[],
): { publicBytes: Uint8Array; redactions: HostPathRedaction[] } {
  let text = Buffer.from(privateBytes).toString("utf8");
  const redactions: HostPathRedaction[] = [];
  const uniquePaths = [...new Set(hostPaths)].sort((a, b) => b.length - a.length);
  for (const source of uniquePaths) {
    const sourceBytes = Buffer.byteLength(source);
    const longToken = `{local-${sha256(source).slice(0, 12)}}`;
    const base = sourceBytes >= Buffer.byteLength(longToken) ? longToken : "<p>";
    if (sourceBytes < Buffer.byteLength(base)) {
      throw new Error("host path is too short for a fixed-width token");
    }
    const replacement = base.padEnd(sourceBytes, "~");
    const occurrences = text.split(source).length - 1;
    if (occurrences > 0) {
      text = text.split(source).join(replacement);
      redactions.push({ sourceSha256: sha256(source), replacement, occurrences });
    }
  }
  if (/[A-Za-z]:[\\/]/.test(text)) {
    throw new Error("unredacted absolute host path remains in public evidence");
  }
  const publicBytes = Buffer.from(text, "utf8");
  if (publicBytes.byteLength !== privateBytes.byteLength) {
    throw new Error("path redaction changed byte length");
  }
  for (const source of uniquePaths) {
    if (Buffer.from(publicBytes).includes(Buffer.from(source))) {
      throw new Error("path redaction left a supplied host path");
    }
  }
  return { publicBytes, redactions };
}

function frameLines(terminal: Terminal): string[] {
  const start = terminal.buffer.active.viewportY;
  return Array.from({ length: terminal.rows }, (_, row) =>
    terminal.buffer.active.getLine(start + row)?.translateToString(false) ?? "",
  );
}

export function findClosedPromptRegion(frame: string[], width: number): ClosedPromptRegion {
  if (!Number.isInteger(width) || width < 2) throw new Error("terminal width is invalid");
  if (frame.length === 0 || frame.some((line) => line.length !== width)) {
    throw new Error("frame does not match terminal width");
  }

  for (let top = 0; top < frame.length; top++) {
    if (!frame[top]!.startsWith("╭")) continue;
    const right = frame[top]!.indexOf("╮", 1);
    if (right <= 1 || right >= width) continue;
    for (let bottom = top + 2; bottom < frame.length; bottom++) {
      if (frame[bottom]![0] !== "╰" || frame[bottom]![right] !== "╯") continue;
      const interior = frame.slice(top + 1, bottom);
      if (!interior.some((line) => line.includes("❯"))) continue;
      if (interior.length < 2) continue;
      if (!interior.every((line) => line[0] === "│" && line[right] === "│")) continue;
      return { top, bottom, contentColumns: right - 1 };
    }
  }
  throw new Error("closed prompt region not found");
}

function safeArtifactPath(value: string, label: string): string {
  if (
    value.length === 0 ||
    isAbsolute(value) ||
    value.includes("\\") ||
    value.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    throw new Error(`${label} must be a normalized repository-relative path`);
  }
  return value;
}

export function buildCaptureReceipt(input: CaptureReceiptInput): Record<string, unknown> {
  if (!COMMIT.test(input.sourceCommit)) throw new Error("source commit is invalid");
  if (!SHA256.test(input.binarySha256Before) || !SHA256.test(input.binarySha256After)) {
    throw new Error("binary hash is invalid");
  }
  if (input.binarySha256Before !== input.binarySha256After) {
    throw new Error("binary changed during capture");
  }
  safeArtifactPath(input.binaryArtifact, "binary artifact");
  if (
    input.stages.length !== EXPECTED_COLUMNS.length ||
    input.stages.some((stage, index) => stage.columns !== EXPECTED_COLUMNS[index] || stage.rows !== ROWS)
  ) {
    throw new Error("capture dimensions must be 80x24, 40x24, 80x24");
  }

  const stages = input.stages.map((stage, index) => {
    safeArtifactPath(stage.rawPath, `stage ${index + 1} raw path`);
    if (!stage.privateRawLocator.startsWith("EMBER_PRIVATE_EVIDENCE:")) {
      throw new Error(`stage ${index + 1} private raw locator is invalid`);
    }
    safeArtifactPath(stage.framePath, `stage ${index + 1} frame path`);
    if (stage.rawBytes.byteLength === 0) throw new Error(`stage ${index + 1} raw output is empty`);
    if (stage.privateRawBytes.byteLength === 0) {
      throw new Error(`stage ${index + 1} private raw output is empty`);
    }
    if (stage.privateRawBytes.byteLength !== stage.rawBytes.byteLength) {
      throw new Error(`stage ${index + 1} public/private raw byte length differs`);
    }
    if (stage.frameText.length === 0) throw new Error(`stage ${index + 1} frame is empty`);
    const lines = stage.frameText.replace(/\n$/, "").split("\n");
    const region = findClosedPromptRegion(lines, stage.columns);
    if (
      region.top !== stage.region.top ||
      region.bottom !== stage.region.bottom ||
      region.contentColumns !== stage.region.contentColumns
    ) {
      throw new Error(`stage ${index + 1} region does not match frame bytes`);
    }
    if (stage.columns === 40 && region.contentColumns <= 0) {
      throw new Error("narrow prompt viewport is not positive");
    }
    return {
      stage: index + 1,
      columns: stage.columns,
      rows: stage.rows,
      raw_public_redacted: {
        path: stage.rawPath,
        bytes: stage.rawBytes.byteLength,
        sha256: sha256(stage.rawBytes),
      },
      raw_private_exact: {
        logical_locator: stage.privateRawLocator,
        bytes: stage.privateRawBytes.byteLength,
        sha256: sha256(stage.privateRawBytes),
      },
      path_redaction: {
        byte_length_preserved: true,
        mappings: stage.redactions.map((row) => ({
          source_sha256: row.sourceSha256,
          replacement: row.replacement,
          occurrences: row.occurrences,
        })),
      },
      frame: {
        path: stage.framePath,
        bytes: Buffer.byteLength(stage.frameText),
        sha256: sha256(stage.frameText),
      },
      closed_prompt_region: region,
    };
  });

  return {
    schema_version: "ember-cli-issue-243-live-resize/v1",
    issue: 243,
    evidence_class: "LIVE_COMPILED_BINARY_CONPTY",
    source_commit: input.sourceCommit,
    binary: {
      artifact: input.binaryArtifact,
      sha256: input.binarySha256Before,
    },
    transport: "windows-conpty/node-pty",
    argv: [basename(input.binaryArtifact)],
    dimensions: EXPECTED_COLUMNS.map((columns) => ({ columns, rows: ROWS })),
    stages,
    result: "PASS",
  };
}

function commandText(args: string[], cwd: string): string {
  const result = Bun.spawnSync(args, { cwd, stdout: "pipe", stderr: "pipe" });
  if (result.exitCode !== 0) {
    throw new Error(Buffer.from(result.stderr).toString("utf8").trim() || `${args[0]} failed`);
  }
  return Buffer.from(result.stdout).toString("utf8").trim();
}

function within(root: string, target: string, label: string): string {
  const rel = relative(root, target).replaceAll("\\", "/");
  if (rel === "" || rel === ".." || rel.startsWith("../")) {
    throw new Error(`${label} must be inside the repository`);
  }
  return safeArtifactPath(rel, label);
}

async function waitForRegion(
  terminal: Terminal,
  rawChunks: string[],
  flushWrites: () => Promise<void>,
  timeoutMs: number,
): Promise<{ lines: string[]; region: ClosedPromptRegion }> {
  const deadline = Date.now() + timeoutMs;
  let lastError = "no terminal output";
  while (Date.now() < deadline) {
    if (rawChunks.length > 0) {
      await flushWrites();
      const current = frameLines(terminal);
      try {
        return { lines: current, region: findClosedPromptRegion(current, terminal.cols) };
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }
    }
    await Bun.sleep(50);
  }
  throw new Error(`timed out waiting for closed prompt region: ${lastError}`);
}

function parseArgs(argv: string[]): { binary: string; outDir: string; privateOutDir: string } {
  let binary = "";
  let outDir = "";
  let privateOutDir = "";
  for (let index = 0; index < argv.length; index++) {
    if (argv[index] === "--binary") binary = argv[++index] ?? "";
    else if (argv[index] === "--out-dir") outDir = argv[++index] ?? "";
    else if (argv[index] === "--private-out-dir") privateOutDir = argv[++index] ?? "";
    else throw new Error(`unknown argument: ${argv[index]}`);
  }
  if (binary === "" || outDir === "" || privateOutDir === "") {
    throw new Error("--binary, --out-dir, and --private-out-dir are required");
  }
  return { binary: resolve(binary), outDir: resolve(outDir), privateOutDir: resolve(privateOutDir) };
}

export async function capturePromptInput243(argv: string[]): Promise<void> {
  if (process.platform !== "win32") throw new Error("compiled prompt capture requires Windows ConPTY");
  const { binary, outDir, privateOutDir } = parseArgs(argv);
  const repoRoot = commandText(["git", "rev-parse", "--show-toplevel"], process.cwd());
  const sourceCommit = commandText(["git", "rev-parse", "HEAD"], repoRoot);
  const resolvedEmberRoot = dirname(
    commandText(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], repoRoot),
  );
  if (commandText(["git", "status", "--porcelain", "--untracked-files=no"], repoRoot) !== "") {
    throw new Error("tracked worktree must be clean before compiled capture");
  }
  const binaryArtifact = within(repoRoot, binary, "binary artifact");
  const outArtifact = within(repoRoot, outDir, "output directory");
  const privateRelative = relative(repoRoot, privateOutDir);
  if (privateRelative === "" || (!privateRelative.startsWith("..") && !isAbsolute(privateRelative))) {
    throw new Error("private output directory must be outside the public repository");
  }
  const binaryBefore = readFileSync(binary);
  const binarySha256Before = sha256(binaryBefore);
  mkdirSync(outDir, { recursive: true });
  mkdirSync(privateOutDir, { recursive: true });

  const home = mkdtempSync(join(tmpdir(), "ember-issue-243-"));
  const terminal = new Terminal({ cols: 80, rows: ROWS, allowProposedApi: true });
  const rawChunks: string[] = [];
  let writes = Promise.resolve();
  let child: IPty | undefined;
  try {
    child = spawnPty(binary, [], {
      name: "xterm-256color",
      cols: 80,
      rows: ROWS,
      cwd: repoRoot,
      env: {
        ...process.env,
        EMBER_HOME: home,
        EMBER_REPO_ROOT: repoRoot,
        EMBER_GPU_FREE: "1",
        EMBER_DISABLE_TERMINAL_TITLE: "1",
      },
    });
    child.onData((data) => {
      rawChunks.push(data);
      writes = writes.then(() => new Promise<void>((resolveWrite) => terminal.write(data, resolveWrite)));
    });

    const stages: CaptureStageInput[] = [];
    for (let index = 0; index < EXPECTED_COLUMNS.length; index++) {
      const columns = EXPECTED_COLUMNS[index]!;
      if (index > 0) {
        rawChunks.length = 0;
        terminal.resize(columns, ROWS);
        child.resize(columns, ROWS);
      }
      const observed = await waitForRegion(terminal, rawChunks, () => writes, 15_000);
      await writes;
      const privateRawBytes = Buffer.from(rawChunks.join(""), "utf8");
      const privateFrameText = `${observed.lines.join("\n")}\n`;
      const stem = `stage-${index + 1}-${columns}`;
      const rawPath = join(outDir, `${stem}.raw`);
      const privateRawPath = join(privateOutDir, `${stem}.raw`);
      const framePath = join(outDir, `${stem}.frame.txt`);
      const rawRedaction = redactHostPaths(privateRawBytes, [binary, repoRoot, resolvedEmberRoot]);
      const frameRedaction = redactHostPaths(Buffer.from(privateFrameText, "utf8"), [binary, repoRoot, resolvedEmberRoot]);
      const rawBytes = rawRedaction.publicBytes;
      const frameText = Buffer.from(frameRedaction.publicBytes).toString("utf8");
      const publicRegion = findClosedPromptRegion(frameText.replace(/\n$/, "").split("\n"), columns);
      if (
        publicRegion.top !== observed.region.top ||
        publicRegion.bottom !== observed.region.bottom ||
        publicRegion.contentColumns !== observed.region.contentColumns
      ) {
        throw new Error("path redaction changed prompt geometry");
      }
      writeFileSync(privateRawPath, privateRawBytes);
      writeFileSync(rawPath, rawBytes);
      writeFileSync(framePath, frameText, "utf8");
      stages.push({
        columns,
        rows: ROWS,
        rawPath: `${outArtifact}/${stem}.raw`,
        privateRawLocator: `EMBER_PRIVATE_EVIDENCE:ember-cli/issue-243/live-resize-v1/${sourceCommit}/${stem}.raw`,
        privateRawBytes,
        redactions: rawRedaction.redactions,
        framePath: `${outArtifact}/${stem}.frame.txt`,
        rawBytes,
        frameText,
        region: publicRegion,
      });
    }

    const binarySha256After = sha256(readFileSync(binary));
    const receipt = buildCaptureReceipt({
      sourceCommit,
      binaryArtifact,
      binarySha256Before,
      binarySha256After,
      stages,
    });
    const receiptPath = join(outDir, "receipt.json");
    writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");

    for (const [index, stage] of stages.entries()) {
      const privateRawPath = join(privateOutDir, `stage-${index + 1}-${stage.columns}.raw`);
      if (sha256(readFileSync(privateRawPath)) !== sha256(stage.privateRawBytes)) {
        throw new Error("private raw capture changed after publication");
      }
      if (sha256(readFileSync(resolve(repoRoot, stage.rawPath))) !== sha256(stage.rawBytes)) {
        throw new Error("raw capture changed after publication");
      }
      if (sha256(readFileSync(resolve(repoRoot, stage.framePath))) !== sha256(stage.frameText)) {
        throw new Error("frame capture changed after publication");
      }
    }
    JSON.parse(readFileSync(receiptPath, "utf8"));
  } finally {
    if (child != null) {
      // node-pty's Bun-hosted kill helper fails AttachConsole on this host. Terminate only
      // the exact PTY root PID and its owned tree; never enumerate or target foreign PIDs.
      Bun.spawnSync(["taskkill", "/PID", String(child.pid), "/T", "/F"], {
        stdout: "ignore",
        stderr: "ignore",
      });
    }
    terminal.dispose();
    rmSync(home, { recursive: true, force: true });
  }
}

if (import.meta.main) {
  capturePromptInput243(Bun.argv.slice(2)).then(
    () => process.exit(0),
    (error) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exit(1);
    },
  );
}
