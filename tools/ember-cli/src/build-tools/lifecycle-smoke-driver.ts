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
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { createHash } from "node:crypto";
import { basename, dirname, join, relative, resolve } from "node:path";
import { tmpdir } from "node:os";
import { Terminal } from "@xterm/headless";
import { spawn as spawnPty, type IPty } from "node-pty";
import { READY_OSC } from "../cli/ready-sentinel.ts";
import {
  findClosedPromptRegion,
  rebuildBinaryFromSource,
  redactHostPaths,
} from "./capture-prompt-input-243.ts";
import {
  LIFECYCLE_ACTIONS,
  validateLifecycleReceipt,
  type LifecycleAction,
  type LifecycleActionEvidence,
  type LifecycleReceipt,
} from "./lifecycle-smoke.ts";

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

function commandText(args: string[], cwd: string): string {
  const result = Bun.spawnSync(args, { cwd, stdout: "pipe", stderr: "pipe" });
  if (result.exitCode !== 0) {
    throw new Error(Buffer.from(result.stderr).toString("utf8").trim() || `${args[0]} failed`);
  }
  return Buffer.from(result.stdout).toString("utf8").trim();
}

function frameLines(terminal: Terminal): string[] {
  const lines: string[] = [];
  const buffer = terminal.buffer.active;
  for (let row = 0; row < terminal.rows; row += 1) {
    lines.push(buffer.getLine(row)?.translateToString(true) ?? "");
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

function newestReceipt(root: string): string | null {
  if (!existsSync(root)) return null;
  const files: string[] = [];
  const walk = (dir: string): void => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      const stat = statSync(path);
      if (stat.isDirectory()) walk(path);
      else files.push(path);
    }
  };
  walk(root);
  files.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
  return files[0] ?? null;
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
  terminal: Terminal,
): Promise<{ elapsedMs: number; frameSha256: string }> {
  const started = Date.now();
  while (Date.now() - started < TIMEOUT_MS) {
    if (raw.join("").includes(READY_OSC)) {
      await flush();
      const frame = `${frameLines(terminal).join("\n")}\n`;
      findClosedPromptRegion(frame.replace(/\n$/, "").split("\n"), COLS);
      return { elapsedMs: Date.now() - started, frameSha256: sha256(frame) };
    }
    await Bun.sleep(25);
  }
  throw new Error("readiness marker was not observed");
}

async function driveInput(
  child: IPty,
  terminal: Terminal,
  raw: string[],
  flush: () => Promise<void>,
  input: string,
): Promise<{ before: string; after: string; delta: string }> {
  await flush();
  const before = `${frameLines(terminal).join("\n")}\n`;
  const rawStart = raw.join("").length;
  let lastRawLength = rawStart;
  let lastChange = Date.now();
  child.write(`${input}\r`);
  const deadline = Date.now() + TIMEOUT_MS;
  while (Date.now() < deadline) {
    const currentRawLength = raw.join("").length;
    if (currentRawLength !== lastRawLength) {
      lastRawLength = currentRawLength;
      lastChange = Date.now();
    }
    if (currentRawLength > rawStart && Date.now() - lastChange >= 200) {
      await flush();
      const after = `${frameLines(terminal).join("\n")}\n`;
      try {
        findClosedPromptRegion(after.replace(/\n$/, "").split("\n"), COLS);
        const delta = raw.join("").slice(rawStart);
        const nonEcho = delta.replaceAll(input, "").replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "");
        if (sha256(before) !== sha256(after) && nonEcho.trim().length > 0) {
          return { before, after, delta };
        }
      } catch {
        // The product has not repainted a complete prompt yet.
      }
    }
    await Bun.sleep(25);
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
  const stateDir = join(home, "state");
  mkdirSync(stateDir, { recursive: true });
  writeFileSync(
    join(stateDir, "ember-telemetry.jsonl"),
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
      cwd: home,
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
    const readyFrame = `${frameLines(terminal).join("\n")}\n`;
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
      let driven: Awaited<ReturnType<typeof driveInput>>;
      try {
        driven = await driveInput(child, terminal, raw, () => writes, input);
      } catch (error) {
        attempts.push({
          action,
          input,
          status: "NO_EFFECT",
          frame_artifact: "",
          detail: error instanceof Error ? error.message : String(error),
        });
        const failedFrame = `${frameLines(terminal).join("\n")}\n`;
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
      const lower = driven.delta.toLowerCase();
      const missing = lower.includes("unknown command");
      const refused = lower.includes("error:") || lower.includes("failed to");
      const status = missing ? "MISSING" : refused ? "REFUSED" : "PASS";
      const publicDelta = Buffer.from(
        redactHostPaths(Buffer.from(driven.delta, "utf8"), [repoRoot, home, binary]).publicBytes,
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
      const control = join(stateDir, "ember-finetune-control.jsonl");
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
    await Bun.sleep(200);
    cleanupAttempted = true;
    Bun.spawnSync(["taskkill", "/PID", String(child.pid), "/T", "/F"], {
      stdout: "ignore",
      stderr: "ignore",
    });
    const exitDeadline = Date.now() + 2_000;
    while (!exitObserved && Date.now() < exitDeadline) {
      await Bun.sleep(25);
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
        builder_sha256_after: sha256(readFileSync(process.execPath)),
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
  runLifecycleSmoke(Bun.argv.slice(2)).then(
    () => process.exit(0),
    (error) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exit(1);
    },
  );
}
