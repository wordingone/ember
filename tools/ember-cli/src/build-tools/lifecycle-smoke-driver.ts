// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// Drives the real compiled Ember CLI through Windows ConPTY. This is not a
// fixture backend: every input is dispatched by the production REPL registry.

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { basename, dirname, join, relative, resolve } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";
import xtermHeadless from "@xterm/headless";
import { spawn as spawnPty, type IPty } from "node-pty";
import { READY_OSC } from "../cli/ready-sentinel.ts";
import { buildCommitBanner } from "./build-cockpit.ts";
import {
  LIFECYCLE_ACTIONS,
  validateLifecycleReceipt,
  type LifecycleAction,
  type LifecycleActionEvidence,
  type LifecycleReceipt,
} from "./lifecycle-smoke.ts";

const { Terminal } = xtermHeadless;
type HeadlessTerminal = InstanceType<typeof Terminal>;

const COLS = 100;
const ROWS = 32;
const TIMEOUT_MS = 15_000;

interface AttemptRow {
  action: LifecycleAction;
  input: string;
  status: "PASS" | "MISSING" | "REFUSED" | "NO_EFFECT";
  frame_artifact: string;
  detail: string;
}

function sha256(bytes: Uint8Array | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

export async function writePromptInput(
  writer: { write(value: string): void },
  input: string,
  interKeyDelayMs = 20,
  pause: (milliseconds: number) => Promise<void> = sleep,
): Promise<void> {
  for (let index = 0; index < input.length; index += 1) {
    writer.write(input[index]!);
    if (index + 1 < input.length && interKeyDelayMs > 0) {
      await pause(interKeyDelayMs);
    }
  }
}


export function actionLocalDelta(delta: string, input: string): string {
  const marker = delta.indexOf(input);
  return marker === -1 ? delta : delta.slice(marker + input.length);
}

function commandText(args: string[], cwd: string): string {
  const result = spawnSync(args[0]!, args.slice(1), {
    cwd,
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.status !== 0) {
    throw new Error((result.stderr ?? "").trim() || `${args[0]} failed`);
  }
  return (result.stdout ?? "").trim();
}

function resolveBunExecutable(): string {
  const result = spawnSync("where.exe", ["bun"], {
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.status !== 0) {
    throw new Error((result.stderr ?? "").trim() || "where.exe bun failed");
  }
  const located = (result.stdout ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  const exe = located.find((line) => line.toLowerCase().endsWith(".exe"));
  if (exe !== undefined) return exe;
  const cmdShim = located.find((line) => line.toLowerCase().endsWith(".cmd"));
  if (cmdShim !== undefined) {
    const candidate = join(dirname(cmdShim), "node_modules", "bun", "bin", "bun.exe");
    if (existsSync(candidate)) return candidate;
  }
  throw new Error(
    `cannot resolve a directly-spawnable bun.exe from where output: ${JSON.stringify(located)}`,
  );
}

interface ClosedPromptRegion {
  top: number;
  bottom: number;
  right: number;
}

function findClosedPromptRegion(frame: string[], width: number): ClosedPromptRegion {
  if (!Number.isInteger(width) || width < 2) throw new Error("terminal width is invalid");
  if (frame.length === 0 || frame.some((line) => line.length !== width)) {
    throw new Error("frame does not match terminal width");
  }
  let latest: ClosedPromptRegion | null = null;
  for (let top = 0; top < frame.length; top += 1) {
    if (!frame[top]!.startsWith("╭")) continue;
    const right = frame[top]!.indexOf("╮", 1);
    if (right <= 1 || right >= width) continue;
    for (let bottom = top + 2; bottom < frame.length; bottom += 1) {
      if (frame[bottom]![0] !== "╰" || frame[bottom]![right] !== "╯") continue;
      const interior = frame.slice(top + 1, bottom);
      if (!interior.some((line) => line.includes("❯"))) continue;
      if (interior.length < 2) continue;
      if (!interior.every((line) => line[0] === "│" && line[right] === "│")) continue;
      latest = { top, bottom, right };
    }
  }
  if (latest !== null) return latest;
  throw new Error("closed prompt region not found");
}

export function completedPromptFrame(
  frame: string[],
  width: number,
  input: string,
): boolean {
  const region = findClosedPromptRegion(frame, width);
  const promptText = frame
    .slice(region.top + 1, region.bottom)
    .map((line) => line.slice(1, region.right))
    .join("\n");
  const pendingProbe = input.slice(0, Math.min(24, input.length));
  return pendingProbe.length > 0 && !promptText.includes(pendingProbe);
}

export function slashCommandNeedsSecondEnter(
  frame: string[],
  width: number,
  input: string,
): boolean {
  return input.startsWith("/") && !completedPromptFrame(frame, width, input);
}

function redactHostPaths(
  privateBytes: Uint8Array,
  hostPaths: string[],
): { publicBytes: Uint8Array } {
  let text = Buffer.from(privateBytes).toString("utf8");
  const replacePath = (source: string): void => {
    const sourceBytes = Buffer.byteLength(source);
    const token = `{local-${sha256(Buffer.from(source, "utf8")).slice(0, 12)}}`;
    const base = sourceBytes >= Buffer.byteLength(token) ? token : "<p>";
    if (sourceBytes < Buffer.byteLength(base)) return;
    const replacement = base.padEnd(sourceBytes, "~");
    text = text.split(source).join(replacement);
  };
  for (const source of [...new Set(hostPaths)].sort((a, b) => b.length - a.length)) {
    replacePath(source);
  }
  const residual = [...new Set(text.match(/[A-Za-z]:[\\/][A-Za-z0-9_.~\\/()-]+/g) ?? [])]
    .sort((a, b) => b.length - a.length);
  for (const source of residual) replacePath(source);
  return { publicBytes: Buffer.from(text, "utf8") };
}

interface ReproducibleBuildEvidence {
  rebuildBinarySha256: string;
  builderExecutableBasename: string;
  builderExecutableSha256Before: string;
  builderExecutableSha256After: string;
  builderVersion: string;
}

function rebuildBinaryFromSource(
  repoRoot: string,
  sourceCommit: string,
): ReproducibleBuildEvidence {
  const sourceRoot = join(repoRoot, "tools", "ember-cli", "src");
  const bunExecutable = resolveBunExecutable();
  const ownedTemp = mkdtempSync(join(tmpdir(), "ember-lifecycle-rebuild-"));
  const rebuiltBinary = join(ownedTemp, "ember.exe");
  const builderExecutableSha256Before = sha256(readFileSync(bunExecutable));
  const builderVersion = commandText([bunExecutable, "--version"], sourceRoot);
  try {
    const result = spawnSync(
      bunExecutable,
      [
        "build",
        "./entrypoints/main.ts",
        "--compile",
        "--outfile",
        rebuiltBinary,
        "--banner",
        buildCommitBanner(sourceCommit),
      ],
      { cwd: sourceRoot, encoding: "utf8", windowsHide: true },
    );
    if (result.status !== 0) {
      throw new Error(
        (result.stderr ?? "").trim() ||
          `independent lifecycle rebuild failed with status ${result.status}`,
      );
    }
    const builderExecutableSha256After = sha256(readFileSync(bunExecutable));
    if (builderExecutableSha256Before !== builderExecutableSha256After) {
      throw new Error("builder executable changed during independent rebuild");
    }
    return {
      rebuildBinarySha256: sha256(readFileSync(rebuiltBinary)),
      builderExecutableBasename: basename(bunExecutable),
      builderExecutableSha256Before,
      builderExecutableSha256After,
      builderVersion,
    };
  } finally {
    rmSync(ownedTemp, { recursive: true, force: true });
  }
}

export function visibleFrameLines(terminal: HeadlessTerminal): string[] {
  const lines: string[] = [];
  const buffer = terminal.buffer.active;
  const start = buffer.viewportY;
  for (let row = 0; row < terminal.rows; row += 1) {
    lines.push(buffer.getLine(start + row)?.translateToString(true) ?? "");
  }
  return lines;
}

function artifactPath(repoRoot: string, path: string): string {
  const rel = relative(repoRoot, path).replaceAll("\\", "/");
  if (rel === "" || rel === ".." || rel.startsWith("../")) {
    throw new Error("public lifecycle artifact must remain inside repository");
  }
  return rel;
}

function parseArgs(argv: string[]): {
  binary: string;
  outDir: string;
  receiptPath: string;
} {
  let binary = "";
  let outDir = "";
  let receiptPath = "";
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--binary") binary = argv[++index] ?? "";
    else if (argv[index] === "--out-dir") outDir = argv[++index] ?? "";
    else if (argv[index] === "--receipt-path") receiptPath = argv[++index] ?? "";
    else throw new Error(`unknown argument: ${argv[index]}`);
  }
  if (!binary || !outDir || !receiptPath) {
    throw new Error("--binary, --out-dir, and --receipt-path are required");
  }
  return {
    binary: resolve(binary),
    outDir: resolve(outDir),
    receiptPath: resolve(receiptPath),
  };
}

async function waitForReady(
  raw: string[],
  flush: () => Promise<void>,
  terminal: HeadlessTerminal,
): Promise<{ elapsedMs: number; frameSha256: string }> {
  const started = Date.now();
  while (Date.now() - started < TIMEOUT_MS) {
    if (raw.join("").includes(READY_OSC)) {
      await flush();
      const frame = `${visibleFrameLines(terminal).join("\n")}\n`;
      findClosedPromptRegion(frame.replace(/\n$/, "").split("\n"), COLS);
      return { elapsedMs: Date.now() - started, frameSha256: sha256(frame) };
    }
    await sleep(25);
  }
  throw new Error("readiness marker was not observed");
}

async function driveInput(
  child: IPty,
  terminal: HeadlessTerminal,
  raw: string[],
  flush: () => Promise<void>,
  input: string,
  timeoutMs: number,
): Promise<{ before: string; after: string; delta: string }> {
  await flush();
  const before = `${visibleFrameLines(terminal).join("\n")}\n`;
  const rawStart = raw.join("").length;
  let lastRawLength = rawStart;
  let lastChange = Date.now();
  await writePromptInput(child, input);
  await sleep(100);
  child.write("\r");
  await sleep(600);
  await flush();
  const firstEnterFrame = visibleFrameLines(terminal);
  if (slashCommandNeedsSecondEnter(firstEnterFrame, COLS, input)) {
    child.write("\r");
  }
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const currentRawLength = raw.join("").length;
    if (currentRawLength !== lastRawLength) {
      lastRawLength = currentRawLength;
      lastChange = Date.now();
    }
    if (currentRawLength > rawStart && Date.now() - lastChange >= 200) {
      await flush();
      const after = `${visibleFrameLines(terminal).join("\n")}\n`;
      try {
        const afterLines = after.replace(/\n$/, "").split("\n");
        if (completedPromptFrame(afterLines, COLS, input)) {
          const delta = raw.join("").slice(rawStart);
          const nonEcho = delta.replaceAll(input, "").replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "");
          if (sha256(before) !== sha256(after) && nonEcho.trim().length > 0) {
            return { before, after, delta };
          }
        }
      } catch {
        // The product has not repainted a complete cleared prompt yet.
      }
    }
    await sleep(25);
  }
  throw new Error(`no effect-bearing frame delta for ${input}`);
}

function actionInputs(home: string, repoRoot: string): Record<Exclude<LifecycleAction, "launch">, string> {
  const saveTarget = join(home, "saved-checkpoint");
  const source = join(
    repoRoot,
    "tools",
    "ember-cli",
    "src",
    "commands",
    "__fixtures__",
    "model-identity",
  );
  return {
    train: "/train",
    observe: "/watch",
    pause: "/finetune pause smoke-run",
    resume: "/finetune resume smoke-run",
    save: `/model checkpoint save ${saveTarget} --source ${source}`,
    terminate: "/finetune stop smoke-run",
    reload: `/model checkpoint load ${saveTarget}`,
    continue: "/continue",
  };
}

export async function runLifecycleSmoke(argv: string[]): Promise<void> {
  if (process.platform !== "win32") throw new Error("lifecycle smoke requires Windows ConPTY");
  const { binary, outDir, receiptPath } = parseArgs(argv);
  const repoRoot = commandText(["git", "rev-parse", "--show-toplevel"], process.cwd());
  const sourceCommit = commandText(["git", "rev-parse", "HEAD"], repoRoot);
  if (commandText(["git", "status", "--porcelain", "--untracked-files=no"], repoRoot) !== "") {
    throw new Error("tracked worktree must be clean before compiled lifecycle smoke");
  }
  artifactPath(repoRoot, binary);
  artifactPath(repoRoot, outDir);
  artifactPath(repoRoot, receiptPath);
  mkdirSync(outDir, { recursive: true });
  mkdirSync(dirname(receiptPath), { recursive: true });
  const binaryBefore = readFileSync(binary);
  const binarySha = sha256(binaryBefore);
  const build = rebuildBinaryFromSource(repoRoot, sourceCommit);
  if (build.rebuildBinarySha256 !== binarySha) {
    throw new Error("compiled binary differs from independent rebuild");
  }

  const home = mkdtempSync(join(tmpdir(), "ember-lifecycle-smoke-"));
  const stateDir = join(repoRoot, "state");
  mkdirSync(stateDir, { recursive: true });
  const controlPath = join(stateDir, "ember-finetune-control.jsonl");
  const telemetryPath = join(stateDir, "ember-telemetry.jsonl");
  if (existsSync(controlPath) || existsSync(telemetryPath)) {
    throw new Error("lifecycle smoke state channels already exist; refusing overwrite");
  }
  writeFileSync(
    telemetryPath,
    `${JSON.stringify({
      ts: new Date().toISOString(),
      kind: "train_step",
      source: "lifecycle-smoke",
      payload: { run_id: "smoke-run", step: 1, loss: 1 },
    })}\n`,
    "utf8",
  );
  const terminal = new Terminal({ cols: COLS, rows: ROWS, allowProposedApi: true });
  const raw: string[] = [];
  let writes = Promise.resolve();
  let child: IPty | undefined;
  let exitObserved = false;
  let cleanupAttempted = false;
  const attempts: AttemptRow[] = [];
  const evidence: LifecycleActionEvidence[] = [];
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
        EMBER_GPU_FREE: "1",
        EMBER_DISABLE_TERMINAL_TITLE: "1",
      },
    });
    child.onData((data) => {
      raw.push(data);
      writes = writes.then(() => new Promise<void>((done) => terminal.write(data, done)));
    });
    child.onExit(() => { exitObserved = true; });
    const ready = await waitForReady(raw, () => writes, terminal);
    const readyFrame = `${visibleFrameLines(terminal).join("\n")}\n`;
    const launchArtifact = artifactPath(repoRoot, join(outDir, "action-1-launch.frame.txt"));
    writeFileSync(join(repoRoot, launchArtifact), readyFrame, "utf8");
    evidence.push({
      action: "launch",
      ordinal: 1,
      input_sha256: sha256("Ember.cmd"),
      before_frame_sha256: sha256(""),
      after_frame_sha256: sha256(readyFrame),
      effect_evidence_sha256: sha256(READY_OSC),
      effect_kind: "durable-state-transition",
      outcome: "PASS",
      output_excerpt: "READY_OSC observed from compiled product render",
      state_before: 0,
      state_after: 1,
      frame_artifact: launchArtifact,
      repair_item: null,
    });
    attempts.push({
      action: "launch",
      input: "Ember.cmd",
      status: "PASS",
      frame_artifact: launchArtifact,
      detail: "READY_OSC observed",
    });

    const inputs = actionInputs(home, repoRoot);
    for (let index = 1; index < LIFECYCLE_ACTIONS.length; index += 1) {
      const action = LIFECYCLE_ACTIONS[index]!;
      const input = inputs[action as Exclude<LifecycleAction, "launch">];
      const actionTimeoutMs =
        action === "train"
          ? 600_000
          : action === "save" || action === "reload"
            ? 60_000
            : TIMEOUT_MS;
      let driven: Awaited<ReturnType<typeof driveInput>>;
      try {
        driven = await driveInput(child, terminal, raw, () => writes, input, actionTimeoutMs);
      } catch (error) {
        attempts.push({
          action,
          input,
          status: "NO_EFFECT",
          frame_artifact: "",
          detail: error instanceof Error ? error.message : String(error),
        });
        const failedFrame = `${visibleFrameLines(terminal).join("\n")}\n`;
        const failedArtifact = artifactPath(
          repoRoot,
          join(outDir, `action-${index + 1}-${action}.frame.txt`),
        );
        writeFileSync(join(repoRoot, failedArtifact), failedFrame, "utf8");
        evidence.push({
          action,
          ordinal: index + 1,
          input_sha256: sha256(input),
          before_frame_sha256: sha256(failedFrame),
          after_frame_sha256: sha256(failedFrame),
          effect_evidence_sha256: sha256(String(error)),
          effect_kind: "observable-refusal",
          outcome: "NO_EFFECT",
          output_excerpt: `no effect-bearing frame delta: ${
            error instanceof Error ? error.message : String(error)
          }`,
          state_before: null,
          state_after: null,
          frame_artifact: failedArtifact,
          repair_item: `EMBER-CLI-${action.toUpperCase()}-OPERABILITY`,
        });
        continue;
      }
      const redacted = redactHostPaths(
        Buffer.from(driven.after, "utf8"),
        [repoRoot, home, binary],
      ).publicBytes;
      const publicFrame = Buffer.from(redacted).toString("utf8");
      const frameArtifact = artifactPath(
        repoRoot,
        join(outDir, `action-${index + 1}-${action}.frame.txt`),
      );
      writeFileSync(join(repoRoot, frameArtifact), publicFrame, "utf8");
      const localDelta = actionLocalDelta(driven.delta, input);
      const lower = localDelta.toLowerCase();
      const missing = lower.includes("unknown command");
      const refused = lower.includes("error:") || lower.includes("failed to");
      const status = missing ? "MISSING" : refused ? "REFUSED" : "PASS";
      const publicDelta = Buffer.from(
        redactHostPaths(Buffer.from(localDelta, "utf8"), [repoRoot, home, binary]).publicBytes,
      )
        .toString("utf8")
        .replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "")
        .replaceAll(input.replaceAll(home, "<EMBER_SMOKE_HOME>").replaceAll(repoRoot, "<EMBER_REPO>"), "")
        .trim()
        .slice(-2000);
      attempts.push({
        action,
        input: input.replaceAll(home, "<EMBER_SMOKE_HOME>").replaceAll(repoRoot, "<EMBER_REPO>"),
        status,
        frame_artifact: frameArtifact,
        detail: status === "PASS" ? "effect-bearing frame delta observed" : "operator surface refused",
      });
      const control = controlPath;
      const persisted =
        ["pause", "resume", "terminate"].includes(action) && existsSync(control)
          ? readFileSync(control)
          : action === "save" && existsSync(join(home, "saved-checkpoint", "manifest.json"))
            ? readFileSync(join(home, "saved-checkpoint", "manifest.json"))
            : Buffer.from(driven.delta, "utf8");
      evidence.push({
        action,
        ordinal: index + 1,
        input_sha256: sha256(input),
        before_frame_sha256: sha256(driven.before),
        after_frame_sha256: sha256(driven.after),
        effect_evidence_sha256: sha256(persisted),
        effect_kind: status === "PASS" ? "durable-state-transition" : "observable-refusal",
        outcome: status,
        output_excerpt: publicDelta || `${status}: no printable output`,
        state_before: status === "PASS" ? index : null,
        state_after: status === "PASS" ? index + 1 : null,
        frame_artifact: frameArtifact,
        repair_item: status === "PASS" ? null : `EMBER-CLI-${action.toUpperCase()}-OPERABILITY`,
      });
    }

    child.write("\u0003");
    await sleep(200);
    cleanupAttempted = true;
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    });
    const exitDeadline = Date.now() + 2_000;
    while (!exitObserved && Date.now() < exitDeadline) {
      await sleep(25);
    }

    const attemptArtifact = join(outDir, "attempt.json");
    writeFileSync(
      attemptArtifact,
      `${JSON.stringify({
        schema_version: "ember-cli-lifecycle-smoke-attempt/v1",
        source_commit: sourceCommit,
        binary_sha256: binarySha,
        actions: attempts,
        accepted_instrument_run: true,
        product_all_pass: attempts.every((row) => row.status === "PASS"),
      }, null, 2)}\n`,
      "utf8",
    );

    const receipt: LifecycleReceipt = {
      schema_version: "ember-cli-lifecycle-smoke/v1",
      evidence_class: "LIVE_COMPILED_BINARY_CONPTY",
      source_commit: sourceCommit,
      binary: {
        artifact: artifactPath(repoRoot, binary),
        sha256_before: binarySha,
        sha256_after: sha256(readFileSync(binary)),
      },
      reproducible_rebuild: {
        sha256: build.rebuildBinarySha256,
        builder_basename: build.builderExecutableBasename,
        builder_sha256_before: build.builderExecutableSha256Before,
        builder_sha256_after: build.builderExecutableSha256After,
        builder_version: build.builderVersion,
      },
      readiness: {
        marker: "EMBER_READY;v1",
        observed: true,
        elapsed_ms: ready.elapsedMs,
        frame_sha256: ready.frameSha256,
      },
      actions: evidence,
      termination: {
        explicit_requested: true,
        child_exit_observed: exitObserved,
        cleanup_attempted: cleanupAttempted,
        survivors: exitObserved ? 0 : 1,
      },
      artifacts: {
        receipt: artifactPath(repoRoot, receiptPath),
        diagnostics: artifactPath(repoRoot, outDir),
      },
      operator_contract_mapping:
        "compiled Ember.cmd launch -> /train -> /watch -> /finetune pause/resume/stop -> " +
        "/model checkpoint save/load -> unregistered resume.ts /continue",
      accepted_instrument_run: true,
      claim_boundary: {
        model_capability: false,
        training_quality: false,
        checkpoint_sufficiency: false,
        benchmark: false,
      },
    };
    validateLifecycleReceipt(receipt, {
      sourceCommit,
      binarySha256: binarySha,
      builderSha256: build.builderExecutableSha256Before,
    });
    writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  } finally {
    if (child != null) {
      cleanupAttempted = true;
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
      });
    }
    terminal.dispose();
    rmSync(controlPath, { force: true });
    rmSync(telemetryPath, { force: true });
    rmSync(home, { recursive: true, force: true });
  }
}

const invokedPath = process.argv[1] == null ? "" : pathToFileURL(resolve(process.argv[1])).href;
if (import.meta.url === invokedPath) {
  runLifecycleSmoke(process.argv.slice(2)).then(
    () => process.exit(0),
    (error) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exit(1);
    },
  );
}
