// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// Drives the real compiled Ember CLI through Windows ConPTY. This is not a
// fixture backend: actions enter through the production operator pipe and are
// dispatched by the same production REPL registry used by interactive input.

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
import net from "node:net";
import { basename, dirname, join, relative, resolve } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";
import xtermHeadless from "@xterm/headless";
import { spawn as spawnPty, type IPty } from "node-pty";
import { headlessCaptureEnv } from "../../../../src/ember/infrastructure/tools/ember-cli/src/services/headless-capture.ts";
import { READY_OSC } from "../../../../src/ember/infrastructure/tools/ember-cli/src/cli/ready-sentinel.ts";
import { operatorPipeName } from "../../../../src/ember/infrastructure/tools/ember-cli/src/services/operator-pipe.ts";
import { cockpitCompileArgs } from "../../../../src/ember/infrastructure/tools/ember-cli/src/build-tools/build-cockpit.ts";
import {
  LIFECYCLE_ACTIONS,
  validateLifecycleActionArtifacts,
  validateLifecycleReceipt,
  type LifecycleAction,
  type LifecycleActionEvidence,
  type LifecycleReceipt,
  type LifecycleStateEvidence,
} from "../../../../src/ember/infrastructure/tools/ember-cli/src/build-tools/lifecycle-smoke.ts";

const { Terminal } = xtermHeadless;
type HeadlessTerminal = InstanceType<typeof Terminal>;

const COLS = 160;
const ROWS = 32;
const TIMEOUT_MS = 15_000;

interface AttemptRow {
  action: LifecycleAction;
  input: string;
  status: "PASS" | "PREFLIGHT_ONLY" | "MISSING" | "REFUSED" | "NO_EFFECT";
  frame_artifact: string;
  detail: string;
}

function sha256(bytes: Uint8Array | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function stateSha(bytes: Uint8Array): string {
  return sha256(bytes);
}

export function deriveControlAppendState(
  before: Uint8Array | null,
  after: Uint8Array,
  expectedCommand: "pause" | "resume" | "stop",
  artifact: string,
): LifecycleStateEvidence {
  const prior = before ?? new Uint8Array();
  if (
    after.byteLength <= prior.byteLength ||
    !Buffer.from(after.subarray(0, prior.byteLength)).equals(Buffer.from(prior))
  ) {
    throw new Error("control channel is not an append-only extension");
  }
  const delta = after.subarray(prior.byteLength);
  const lines = Buffer.from(delta)
    .toString("utf8")
    .split(/\r?\n/)
    .filter((line) => line.length > 0);
  if (lines.length !== 1) {
    throw new Error("control append must contain exactly one JSON row");
  }
  let row: unknown;
  try {
    row = JSON.parse(lines[0]!);
  } catch {
    throw new Error("control append row is not JSON");
  }
  if (
    typeof row !== "object" ||
    row === null ||
    Array.isArray(row) ||
    JSON.stringify(Object.keys(row).sort()) !==
      JSON.stringify(["runId", "ts", "verb"])
  ) {
    throw new Error("control append row has missing or unknown fields");
  }
  const record = row as Record<string, unknown>;
  if (
    record.verb !== expectedCommand ||
    record.runId !== "smoke-run" ||
    typeof record.ts !== "string" ||
    !Number.isFinite(Date.parse(record.ts))
  ) {
    throw new Error("control command is not the expected run-bound row");
  }
  return {
    artifact,
    before_exists: before !== null,
    before_sha256: before === null ? null : stateSha(before),
    after_exists: true,
    after_sha256: stateSha(after),
    delta_sha256: stateSha(delta),
    command: expectedCommand,
    run_id: "smoke-run",
  };
}

export function derivePublicationState(
  before: Uint8Array | null,
  after: Uint8Array,
  artifact: string,
): LifecycleStateEvidence {
  if (before !== null) {
    throw new Error("publication target existed before the lifecycle action");
  }
  if (after.byteLength === 0) {
    throw new Error("publication produced no artifact bytes");
  }
  return {
    artifact,
    before_exists: false,
    before_sha256: null,
    after_exists: true,
    after_sha256: stateSha(after),
    delta_sha256: stateSha(after),
    command: null,
    run_id: null,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

export function isBenignConptyClosureError(error: unknown): boolean {
  return typeof error === "object" && error !== null &&
    (error as { code?: unknown }).code === "ERR_SOCKET_CLOSED";
}

export function bindConptyInputErrorFence(
  pty: IPty,
  onError: (error: unknown) => void,
): void {
  const inputSocket = (
    pty as IPty & {
      _agent?: {
        _inSocket?: { on(event: "error", listener: (error: unknown) => void): unknown };
      };
    }
  )._agent?._inSocket;
  if (inputSocket === undefined) {
    throw new Error("node-pty Windows input socket is unavailable");
  }
  inputSocket.on("error", onError);
}

export async function terminateLifecycleChild(
  requestExit: () => void | Promise<void>,
  isExitObserved: () => boolean,
  forceCleanup: () => void,
  wait: (ms: number) => Promise<void> = sleep,
  now: () => number = Date.now,
  cleanExitWaitMs = 2_000,
): Promise<LifecycleReceipt["termination"]> {
  if (!Number.isInteger(cleanExitWaitMs) || cleanExitWaitMs < 1) {
    throw new Error("clean exit wait must be a positive integer");
  }
  if (isExitObserved()) {
    return {
      explicit_requested: true,
      clean_exit_observed: true,
      clean_exit_wait_ms: 0,
      forced_cleanup_required: false,
      forced_cleanup_attempted: false,
      final_exit_observed: true,
      survivors: 0,
    };
  }
  try {
    await requestExit();
  } catch (error) {
    if (!isBenignConptyClosureError(error)) throw error;
  }
  const startedAt = now();
  const cleanDeadline = startedAt + cleanExitWaitMs;
  while (!isExitObserved() && now() < cleanDeadline) {
    await wait(25);
  }
  const cleanExitObserved = isExitObserved();
  const cleanExitWaitElapsed = Math.max(0, now() - startedAt);
  let forcedCleanupAttempted = false;
  if (!cleanExitObserved) {
    forcedCleanupAttempted = true;
    forceCleanup();
    const forcedDeadline = now() + 2_000;
    while (!isExitObserved() && now() < forcedDeadline) {
      await wait(25);
    }
  }
  const finalExitObserved = isExitObserved();
  return {
    explicit_requested: true,
    clean_exit_observed: cleanExitObserved,
    clean_exit_wait_ms: Math.min(cleanExitWaitElapsed, cleanExitWaitMs),
    forced_cleanup_required: !cleanExitObserved,
    forced_cleanup_attempted: forcedCleanupAttempted,
    final_exit_observed: finalExitObserved,
    survivors: finalExitObserved ? 0 : 1,
  };
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

async function writeOperatorLine(
  pid: number,
  input: string,
  timeoutMs = 5_000,
): Promise<void> {
  const pipe = operatorPipeName(pid);
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      await new Promise<void>((resolveWrite, rejectWrite) => {
        const socket = net.createConnection(pipe);
        let settled = false;
        let timer: ReturnType<typeof setTimeout>;
        const finish = (error?: unknown) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          socket.removeAllListeners();
          socket.destroy();
          if (error === undefined) resolveWrite();
          else rejectWrite(error);
        };
        timer = setTimeout(() => finish(new Error("operator pipe write timed out")), 1_000);
        socket.once("error", finish);
        socket.once("connect", () => {
          socket.end(input + "\n", "utf8", () => finish());
        });
      });
      return;
    } catch (error) {
      lastError = error;
      await sleep(50);
    }
  }
  throw new Error("operator pipe did not accept lifecycle input: " + String(lastError));
}


export function actionLocalDelta(delta: string, input: string): string {
  const marker = delta.indexOf(input);
  return marker === -1 ? delta : delta.slice(marker + input.length);
}

export function actionVisibleDelta(before: string, after: string): string {
  const remaining = new Map<string, number>();
  for (const line of before.split(/\r?\n/).map((row) => row.trimEnd())) {
    remaining.set(line, (remaining.get(line) ?? 0) + 1);
  }
  const added: string[] = [];
  for (const line of after.split(/\r?\n/).map((row) => row.trimEnd())) {
    const count = remaining.get(line) ?? 0;
    if (count > 0) {
      remaining.set(line, count - 1);
    } else if (line.trim() !== "") {
      added.push(line);
    }
  }
  return added.join("\n").trim();
}


export function classifyActionFrame(
  action: Exclude<LifecycleAction, "launch">,
  delta: string,
): AttemptRow["status"] {
  const lower = delta.toLowerCase();
  if (lower.includes("unknown command") || lower.includes("not registered")) {
    return "MISSING";
  }
  if (lower.includes("error:") || lower.includes("failed to")) return "REFUSED";
  if (action === "continue" && lower.includes("no resumable session selected")) {
    return "REFUSED";
  }
  if (
    action === "train" &&
    lower.includes("launch-packet") &&
    (
      lower.includes("not all present") ||
      lower.includes("missing/invalid prerequisites") ||
      lower.includes("no offer minted") ||
      lower.includes("training is blocked")
    )
  ) {
    return "REFUSED";
  }
  if (
    action === "train" &&
    lower.includes("launch-packet") &&
    lower.includes("does not launch training")
  ) {
    return "PREFLIGHT_ONLY";
  }
  const positive: Record<Exclude<LifecycleAction, "launch" | "train">, RegExp> = {
    observe: /watching state[\\/]ember-telemetry/i,
    pause: /pause run=smoke-run/i,
    resume: /resume run=smoke-run/i,
    save: /modern governed sparse checkpoint saved: [0-9a-f]{64}/i,
    terminate: /stop run=smoke-run/i,
    reload: /checkpoint loaded/i,
    continue: /continu(?:e|ed|ing)/i,
  };
  if (action !== "train" && positive[action].test(delta)) return "PASS";
  return "NO_EFFECT";
}

export function saveActionCompletionObserved(frame: string, delta: string): boolean {
  const observed = `${frame}\n${delta}`;
  return (
    /modern governed sparse checkpoint saved: [0-9a-f]{64}/i.test(observed) ||
    /error: failed to save checkpoint/i.test(observed)
  );
}

export function actionCompletionObserved(
  action: Exclude<LifecycleAction, "launch">,
  frame: string,
  delta: string,
): boolean {
  const observed = frame + "\n" + delta;
  if (action === "train") return classifyActionFrame(action, observed) !== "NO_EFFECT";
  if (action === "save") return saveActionCompletionObserved(frame, delta);
  const completion: Record<Exclude<LifecycleAction, "launch" | "train" | "save">, RegExp> = {
    observe: /watching state[\\/]ember-telemetry\.jsonl/i,
    pause: /pause run=smoke-run/i,
    resume: /resume run=smoke-run/i,
    terminate: /stop run=smoke-run/i,
    reload: /checkpoint loaded|error: failed to load checkpoint/i,
    continue: /unknown command|not registered|no resumable session selected/i,
  };
  return completion[action].test(observed);
}

export function actionOutputExcerpt(
  action: Exclude<LifecycleAction, "launch">,
  _frame: string,
  delta: string,
): string {
  const modernSave = delta.match(
    /modern governed sparse checkpoint saved: [0-9a-f]{64}/i,
  )?.[0];
  if (action === "save" && modernSave) return modernSave;
  const lines = delta.split("\n");
  const patterns: Record<Exclude<LifecycleAction, "launch">, RegExp> = {
    train: /launch-packet/i,
    observe: /watching state\/ember-telemetry/i,
    pause: /pause run=/i,
    resume: /resume run=/i,
    save: /modern governed sparse checkpoint saved|error: failed to save checkpoint/i,
    terminate: /stop run=/i,
    reload: /error: failed to load checkpoint/i,
    continue: /unknown command|not registered|no resumable session selected/i,
  };
  const observedIndex = lines.findLastIndex((line) => patterns[action].test(line));
  if (observedIndex !== -1) {
    const observed = lines[observedIndex]!.trim();
    const continuation = lines[observedIndex + 1]?.trim() ?? "";
    if (action === "train" && /does not launch training/i.test(continuation)) {
      return `${observed}\n${continuation}`;
    }
    return observed;
  }
  const trimmedDelta = delta.trim();
  if (trimmedDelta !== "") return trimmedDelta.slice(-2000);
  return "";
}

export function classifyActionEvidence(
  action: Exclude<LifecycleAction, "launch">,
  frame: string,
  delta: string,
): { status: AttemptRow["status"]; excerpt: string } {
  const excerpt = actionOutputExcerpt(action, frame, delta);
  return {
    status: classifyActionFrame(action, excerpt),
    excerpt,
  };
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

export function submitSecondEnterIfNeeded(
  writer: { write(value: string): void },
  input: string,
  frame: string[],
  width: number,
  needsSecondEnter: (
    frame: string[],
    width: number,
    input: string,
  ) => boolean = slashCommandNeedsSecondEnter,
): boolean {
  if (!needsSecondEnter(frame, width, input)) return false;
  writer.write("\r");
  return true;
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

export function redactPublicText(text: string, hostPaths: string[]): string {
  return Buffer.from(redactHostPaths(Buffer.from(text, "utf8"), hostPaths).publicBytes)
    .toString("utf8");
}

export function publicFailureFrame(
  frame: string,
  hostPaths: string[],
): string {
  let publicFrame = frame;
  for (const hostPath of [...new Set(hostPaths)].sort(
    (left, right) => right.length - left.length,
  )) {
    publicFrame = publicFrame.replaceAll(hostPath, "<HOST_PATH>");
  }
  return redactPublicText(publicFrame, []);
}

export function attemptDetail(status: AttemptRow["status"]): string {
  if (status === "PASS") return "effect-bearing frame delta observed";
  if (status === "PREFLIGHT_ONLY") {
    return "preflight-only product outcome observed";
  }
  if (status === "NO_EFFECT") return "instrument observed no attributable effect";
  return "operator surface refused";
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
      cockpitCompileArgs(sourceCommit, rebuiltBinary),
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
    const visible = buffer.getLine(start + row)?.translateToString(true) ?? "";
    lines.push(visible.padEnd(terminal.cols).slice(0, terminal.cols));
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
  action: Exclude<LifecycleAction, "launch">,
): Promise<{ before: string; after: string; delta: string }> {
  await flush();
  const before = `${visibleFrameLines(terminal).join("\n")}\n`;
  const rawStart = raw.join("").length;
  await writeOperatorLine(child.pid, input);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const currentRawLength = raw.join("").length;
    if (currentRawLength > rawStart) {
      await flush();
      const after = visibleFrameLines(terminal).join("\n") + "\n";
      const delta = raw.join("").slice(rawStart);
      if (actionCompletionObserved(action, after, delta)) {
        await sleep(250);
        await flush();
        return {
          before,
          after: visibleFrameLines(terminal).join("\n") + "\n",
          delta: raw.join("").slice(rawStart),
        };
      }
    }
    await sleep(25);
  }
  throw new Error("no effect-bearing frame delta for " + input);
}

export function actionInputs(home: string, _repoRoot: string): Record<Exclude<LifecycleAction, "launch">, string> {
  const saveTarget = join(home, "saved-checkpoint");
  const source = join(
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
  let ptyError: Error | null = null;
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
        EMBER_SOURCE_ROOT: repoRoot,
        EMBER_GPU_FREE: "1",
        EMBER_DISABLE_TERMINAL_TITLE: "1",
        ...headlessCaptureEnv(),
      },
    });
    bindConptyInputErrorFence(child, (error) => {
      if (isBenignConptyClosureError(error)) return;
      ptyError = error instanceof Error
        ? error
        : new Error(`ConPTY error: ${String(error)}`);
    });
    child.onData((data) => {
      raw.push(data);
      writes = writes.then(() => new Promise<void>((done) => terminal.write(data, done)));
    });
    child.onExit(() => { exitObserved = true; });
    const ready = await waitForReady(raw, () => writes, terminal);
    const readyFrame = redactPublicText(
      `${visibleFrameLines(terminal).join("\n")}\n`,
      [repoRoot, home, binary],
    );
    const launchArtifact = artifactPath(repoRoot, join(outDir, "action-1-launch.frame.txt"));
    const launchDeltaArtifact = artifactPath(
      repoRoot,
      join(outDir, "action-1-launch.delta.txt"),
    );
    writeFileSync(join(repoRoot, launchArtifact), readyFrame, "utf8");
    writeFileSync(join(repoRoot, launchDeltaArtifact), readyFrame, "utf8");
    evidence.push({
      action: "launch",
      ordinal: 1,
      input_sha256: sha256("tools/launchers/Ember.cmd"),
      before_frame_sha256: sha256(""),
      after_frame_sha256: sha256(readyFrame),
      effect_evidence_sha256: sha256(READY_OSC),
      effect_kind: "observable-readiness",
      outcome: "PASS",
      output_excerpt: "READY_OSC observed from compiled product render",
      state_evidence: null,
      frame_artifact: launchArtifact,
      delta_artifact: launchDeltaArtifact,
      delta_sha256: sha256(readyFrame),
      repair_item: null,
    });
    attempts.push({
      action: "launch",
      input: "tools/launchers/Ember.cmd",
      status: "PASS",
      frame_artifact: launchArtifact,
      detail: "READY_OSC observed",
    });

    const inputs = actionInputs(home, repoRoot);
    for (let index = 1; index < LIFECYCLE_ACTIONS.length; index += 1) {
      const action = LIFECYCLE_ACTIONS[index]! as Exclude<
        LifecycleAction, "launch">;
      const input = inputs[action as Exclude<LifecycleAction, "launch">];
      const controlCommand =
        action === "pause" ? "pause"
          : action === "resume" ? "resume"
            : action === "terminate" ? "stop"
              : null;
      const saveManifestPath = join(home, "saved-checkpoint", "manifest.json");
      const stateSourcePath =
        controlCommand === null
          ? action === "save" ? saveManifestPath : null
          : controlPath;
      const stateBefore =
        stateSourcePath !== null && existsSync(stateSourcePath)
          ? readFileSync(stateSourcePath)
          : null;
      const actionTimeoutMs =
        action === "train"
          ? 600_000
          : action === "save" || action === "reload"
            ? 60_000
            : TIMEOUT_MS;
      let driven: Awaited<ReturnType<typeof driveInput>>;
      try {
        driven = await driveInput(
          child,
          terminal,
          raw,
          () => writes,
          input,
          actionTimeoutMs,
          action,
        );
      } catch (error) {
        attempts.push({
          action,
          input,
          status: "NO_EFFECT",
          frame_artifact: "",
          detail: error instanceof Error ? error.message : String(error),
        });
        const failedFrame = publicFailureFrame(
          `${visibleFrameLines(terminal).join("\n")}\n`,
          [repoRoot, home, binary],
        );
        const failedArtifact = artifactPath(
          repoRoot,
          join(outDir, `action-${index + 1}-${action}.frame.txt`),
        );
        writeFileSync(join(repoRoot, failedArtifact), failedFrame, "utf8");
        const failedDeltaArtifact = artifactPath(
          repoRoot,
          join(outDir, `action-${index + 1}-${action}.delta.txt`),
        );
        const failedDelta =
          `no effect-bearing frame delta: ${String(error)}\n`;
        writeFileSync(
          join(repoRoot, failedDeltaArtifact),
          failedDelta,
          "utf8",
        );
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
          state_evidence: null,
          frame_artifact: failedArtifact,
          delta_artifact: failedDeltaArtifact,
          delta_sha256: sha256(failedDelta),
          repair_item: `EMBER-CLI-${action.toUpperCase()}-OPERABILITY`,
        });
        continue;
      }
      const redacted = redactHostPaths(
        Buffer.from(driven.after, "utf8"),
        [repoRoot, home, binary],
      ).publicBytes;
      const publicFrame = Buffer.from(redacted).toString("utf8");
      const publicBefore = Buffer.from(
        redactHostPaths(
          Buffer.from(driven.before, "utf8"),
          [repoRoot, home, binary],
        ).publicBytes,
      ).toString("utf8");
      const frameArtifact = artifactPath(
        repoRoot,
        join(outDir, `action-${index + 1}-${action}.frame.txt`),
      );
      writeFileSync(join(repoRoot, frameArtifact), publicFrame, "utf8");
      const localDelta = actionLocalDelta(driven.delta, input);
      const redactedDelta = Buffer.from(
        redactHostPaths(Buffer.from(localDelta, "utf8"), [repoRoot, home, binary]).publicBytes,
      )
        .toString("utf8")
        .replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "")
        .replaceAll(input.replaceAll(home, "<EMBER_SMOKE_HOME>").replaceAll(repoRoot, "<EMBER_REPO>"), "")
        .trim();
      const visibleDelta = actionVisibleDelta(publicBefore, publicFrame);
      const semanticDelta = [redactedDelta, visibleDelta]
        .filter((part) => part.trim() !== "")
        .join("\n");
      const deltaArtifact = artifactPath(
        repoRoot,
        join(outDir, `action-${index + 1}-${action}.delta.txt`),
      );
      writeFileSync(join(repoRoot, deltaArtifact), semanticDelta, "utf8");
      const {
        status,
        excerpt: publicDelta,
      } = classifyActionEvidence(action, publicFrame, semanticDelta);
      attempts.push({
        action,
        input: redactPublicText(input, [repoRoot, home, binary]),
        status,
        frame_artifact: frameArtifact,
        detail: attemptDetail(status),
      });
      let stateEvidence: LifecycleStateEvidence | null = null;
      let effectEvidence = Buffer.from(semanticDelta, "utf8");
      let effectKind: LifecycleActionEvidence["effect_kind"] =
        status === "PREFLIGHT_ONLY"
          ? "preflight-only"
          : status === "PASS"
            ? "observable-product-effect"
            : "observable-refusal";
      if (status === "PASS" && controlCommand !== null) {
        if (!existsSync(controlPath)) {
          throw new Error(`${action} reported PASS without a control artifact`);
        }
        const after = readFileSync(controlPath);
        const stateArtifact = artifactPath(
          repoRoot,
          join(outDir, `action-${index + 1}-${action}.state.jsonl`),
        );
        stateEvidence = deriveControlAppendState(
          stateBefore,
          after,
          controlCommand,
          stateArtifact,
        );
        effectEvidence = after.subarray(stateBefore?.byteLength ?? 0);
        writeFileSync(join(repoRoot, stateArtifact), effectEvidence);
        effectKind = "durable-control-append";
      } else if (status === "PASS" && action === "save") {
        if (!existsSync(saveManifestPath)) {
          throw new Error("save reported PASS without a published manifest");
        }
        const after = readFileSync(saveManifestPath);
        const stateArtifact = artifactPath(
          repoRoot,
          join(outDir, `action-${index + 1}-save.state.json`),
        );
        stateEvidence = derivePublicationState(stateBefore, after, stateArtifact);
        effectEvidence = after;
        writeFileSync(join(repoRoot, stateArtifact), after);
        effectKind = "durable-artifact-publication";
      }
      evidence.push({
        action,
        ordinal: index + 1,
        input_sha256: sha256(input),
        before_frame_sha256: sha256(publicBefore),
        after_frame_sha256: sha256(publicFrame),
        effect_evidence_sha256: sha256(effectEvidence),
        effect_kind: effectKind,
        outcome: status,
        output_excerpt: publicDelta || `${status}: no printable output`,
        state_evidence: stateEvidence,
        frame_artifact: frameArtifact,
        delta_artifact: deltaArtifact,
        delta_sha256: sha256(semanticDelta),
        repair_item: status === "PASS"
          ? null
          : action === "train" && status === "PREFLIGHT_ONLY"
            ? "EMBER-CLI-TRAIN-EXECUTION-WIRING"
            : action === "reload"
            ? "EMBER-CLI-SAVE-RELOAD-COMPATIBILITY"
            : action === "continue"
              ? "EMBER-CLI-CONTINUE-PRODUCTION-WIRING"
              : `EMBER-CLI-${action.toUpperCase()}-OPERABILITY`,
      });
    }

    const termination = await terminateLifecycleChild(
      () => writeOperatorLine(child!.pid, "/exit"),
      () => exitObserved,
      () => {
        spawnSync("taskkill", ["/PID", String(child!.pid), "/T", "/F"], {
          windowsHide: true,
          stdio: "ignore",
        });
      },
    );
    if (ptyError !== null) throw ptyError;

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
      schema_version: "ember-cli-lifecycle-smoke/v2",
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
        frame_sha256: sha256(readyFrame),
      },
      actions: evidence,
      termination,
      artifacts: {
        receipt: artifactPath(repoRoot, receiptPath),
        diagnostics: artifactPath(repoRoot, outDir),
      },
      operator_contract_mapping:
        "compiled tools/launchers/Ember.cmd launch -> /train -> /watch -> /finetune pause/resume/stop -> " +
        "/model checkpoint save/load -> registered resume.ts /continue",
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
    for (const row of receipt.actions) {
      validateLifecycleActionArtifacts(
        row,
        (artifact) => readFileSync(join(repoRoot, artifact)),
      );
    }
    writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
  } finally {
    if (child != null && !exitObserved) {
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
