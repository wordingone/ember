// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// Issue #159: one release-blocking, receipt-producing CLI hardening matrix.
// The matrix runs only closed, checked-in test cells; no shell or caller-provided
// command is accepted.

import { createHash } from "node:crypto";
import {
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const SHA256 = /^[0-9a-f]{64}$/;
const COMMIT = /^[0-9a-f]{40}$/;

export const HARDENING_CELLS = [
  {
    id: "boot-matrix",
    files: ["entrypoints/process-entry.test.ts"],
    testNamePattern: "#159 cell 1",
  },
  {
    id: "registered-tool-failures",
    files: ["core/query-engine.tool-injection.test.ts"],
  },
  {
    id: "backend-death-and-recovery",
    files: [
      "core/query-engine.retry.test.ts",
      "entrypoints/session-init.test.ts",
    ],
  },
  {
    id: "terminal-abuse",
    files: [
      "ink/app-resize.test.ts",
      "ink/frame-geometry-repl-width-sweep.test.ts",
      "screens/repl-input-burst-race.test.ts",
      "screens/repl-enter-preempt-while-busy.test.ts",
    ],
  },
  {
    id: "compiled-source-version",
    files: [
      "build-tools/build-cockpit.test.ts",
      "entrypoints/process-entry.version-binding.test.ts",
    ],
  },
] as const;

export interface MatrixRunResult {
  status: number | null;
  stdout: string;
  stderr: string;
  error?: Error;
}

export type MatrixRunner = (
  executable: string,
  args: readonly string[],
  cwd: string,
) => MatrixRunResult;

export interface MatrixOptions {
  repositoryRoot: string;
  sourceRoot: string;
  receiptPath: string;
  sourceCommit?: string;
  runner?: MatrixRunner;
  executable?: string;
}

export interface MatrixRow {
  id: string;
  argv: string[];
  exit_code: number | null;
  stdout_sha256: string;
  stderr_sha256: string;
  outcome: "PASS" | "FAIL";
}

export interface HardeningMatrixReceipt {
  schema_version: "ember-cli-hardening-matrix/v1";
  issue: 159;
  source_commit: string;
  runner: {
    basename: string;
    sha256: string;
  };
  matrix: MatrixRow[];
  overall: "PASS" | "FAIL";
  claim_boundary: {
    compiled_binary_live_smoke: false;
    model_capability: false;
    training_completion: false;
  };
}

function sha256(bytes: string | Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function exactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (JSON.stringify(actual) !== JSON.stringify(wanted)) {
    throw new Error(`${label} fields are not closed`);
  }
}

function requireRelativeTestPath(value: string): void {
  if (
    value === "" ||
    value.includes("\\") ||
    value.startsWith("/") ||
    value.split("/").some((part) => part === "" || part === "." || part === "..") ||
    !value.endsWith(".test.ts")
  ) {
    throw new Error(`hardening test path is unsafe: ${value}`);
  }
}

export function validateHardeningMatrixReceipt(
  receipt: HardeningMatrixReceipt,
  expectedCommit: string,
  expectedRunnerSha256: string,
): void {
  exactKeys(receipt as unknown as Record<string, unknown>, [
    "schema_version",
    "issue",
    "source_commit",
    "runner",
    "matrix",
    "overall",
    "claim_boundary",
  ], "receipt");
  if (
    receipt.schema_version !== "ember-cli-hardening-matrix/v1" ||
    receipt.issue !== 159 ||
    !COMMIT.test(receipt.source_commit) ||
    receipt.source_commit !== expectedCommit
  ) {
    throw new Error("hardening receipt identity is invalid");
  }
  exactKeys(receipt.runner as unknown as Record<string, unknown>, [
    "basename",
    "sha256",
  ], "runner");
  if (
    receipt.runner.basename === "" ||
    receipt.runner.basename.includes("/") ||
    receipt.runner.basename.includes("\\") ||
    !SHA256.test(receipt.runner.sha256) ||
    receipt.runner.sha256 !== expectedRunnerSha256
  ) {
    throw new Error("hardening runner binding is invalid");
  }
  if (
    receipt.matrix.length !== HARDENING_CELLS.length ||
    receipt.matrix.some((row, index) => row.id !== HARDENING_CELLS[index]!.id)
  ) {
    throw new Error("hardening matrix cell order is invalid");
  }
  for (const row of receipt.matrix) {
    exactKeys(row as unknown as Record<string, unknown>, [
      "id",
      "argv",
      "exit_code",
      "stdout_sha256",
      "stderr_sha256",
      "outcome",
    ], `matrix row ${row.id}`);
    if (
      row.argv.length < 2 ||
      row.argv[0] !== "test" ||
      row.argv.some((arg) => typeof arg !== "string" || arg.includes("\0")) ||
      !SHA256.test(row.stdout_sha256) ||
      !SHA256.test(row.stderr_sha256) ||
      row.exit_code !== 0 ||
      row.outcome !== "PASS"
    ) {
      throw new Error(`hardening matrix row failed: ${row.id}`);
    }
  }
  exactKeys(receipt.claim_boundary as unknown as Record<string, unknown>, [
    "compiled_binary_live_smoke",
    "model_capability",
    "training_completion",
  ], "claim boundary");
  if (
    Object.values(receipt.claim_boundary).some((value) => value !== false) ||
    receipt.overall !== "PASS"
  ) {
    throw new Error("hardening matrix does not support its claimed result");
  }
}

function defaultRunner(
  executable: string,
  args: readonly string[],
  cwd: string,
): MatrixRunResult {
  const result = spawnSync(executable, [...args], {
    cwd,
    encoding: "utf8",
    windowsHide: true,
    timeout: 120_000,
    maxBuffer: 16 * 1024 * 1024,
  });
  return {
    status: result.status,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    error: result.error,
  };
}

function resolveSourceCommit(repositoryRoot: string): string {
  const result = spawnSync("git", ["-C", repositoryRoot, "rev-parse", "HEAD"], {
    encoding: "utf8",
    windowsHide: true,
    timeout: 15_000,
  });
  const commit = (result.stdout ?? "").trim();
  if (result.status !== 0 || !COMMIT.test(commit)) {
    throw new Error("cannot bind hardening matrix to an exact source commit");
  }
  return commit;
}

function requireCleanSource(repositoryRoot: string): void {
  const result = spawnSync(
    "git",
    [
      "-C",
      repositoryRoot,
      "status",
      "--porcelain",
      "--untracked-files=all",
      "--",
      "src/ember/infrastructure/tools/ember-cli/src",
      ".github/workflows/cli-windows-lifecycle-e2e.yml",
    ],
    { encoding: "utf8", windowsHide: true, timeout: 15_000 },
  );
  if (result.status !== 0 || (result.stdout ?? "").trim() !== "") {
    throw new Error("hardening matrix refuses source bytes that are not the exact Git commit");
  }
}

function assertExpectedRoots(repositoryRoot: string, sourceRoot: string): void {
  const expected = resolve(repositoryRoot, "tools", "ember-cli", "src");
  if (resolve(sourceRoot).toLowerCase() !== expected.toLowerCase()) {
    throw new Error("hardening source root is not the canonical Ember CLI source");
  }
}

function writeContentAddressed(path: string, bytes: string): void {
  try {
    writeFileSync(path, bytes, { encoding: "utf8", flag: "wx" });
  } catch (error) {
    if (
      !(error instanceof Error) ||
      (error as NodeJS.ErrnoException).code !== "EEXIST" ||
      readFileSync(path, "utf8") !== bytes
    ) {
      throw error;
    }
  }
}

function writeReceipt(receiptPath: string, receipt: HardeningMatrixReceipt): string {
  const bytes = JSON.stringify(receipt, null, 2) + "\n";
  const digest = sha256(bytes);
  const dir = dirname(receiptPath);
  mkdirSync(dir, { recursive: true });
  const temp = `${receiptPath}.${process.pid}.tmp`;
  writeFileSync(temp, bytes, { encoding: "utf8", flag: "wx" });
  renameSync(temp, receiptPath);
  writeContentAddressed(join(dir, `receipt-${digest}.json`), bytes);
  writeFileSync(join(dir, "receipt.sha256"), `${digest}  ${basename(receiptPath)}\n`, {
    encoding: "utf8",
  });
  return digest;
}

export function runHardeningMatrix(options: MatrixOptions): {
  receipt: HardeningMatrixReceipt;
  receiptSha256: string;
} {
  const repositoryRoot = resolve(options.repositoryRoot);
  const sourceRoot = resolve(options.sourceRoot);
  assertExpectedRoots(repositoryRoot, sourceRoot);

  const sourceCommit = options.sourceCommit ?? resolveSourceCommit(repositoryRoot);
  // Injected commits exist only for isolated unit tests. A real receipt must
  // describe exact committed bytes, never a dirty worktree under a true SHA.
  if (options.sourceCommit === undefined) requireCleanSource(repositoryRoot);

  if (!COMMIT.test(sourceCommit)) {
    throw new Error("hardening matrix source commit is invalid");
  }
  const executable = resolve(options.executable ?? process.execPath);
  const runnerBytes = readFileSync(executable);
  const runnerSha256 = sha256(runnerBytes);
  const runner = options.runner ?? defaultRunner;
  const matrix: MatrixRow[] = [];

  for (const cell of HARDENING_CELLS) {
    cell.files.forEach(requireRelativeTestPath);
    const argv = ["test", ...cell.files];
    if ("testNamePattern" in cell) {
      argv.push("--test-name-pattern", cell.testNamePattern);
    }
    const result = runner(executable, argv, sourceRoot);
    matrix.push({
      id: cell.id,
      argv,
      exit_code: result.status,
      stdout_sha256: sha256(result.stdout),
      stderr_sha256: sha256(result.stderr + (result.error?.message ?? "")),
      outcome: result.status === 0 && result.error === undefined ? "PASS" : "FAIL",
    });
    if (result.status !== 0 || result.error !== undefined) {
      const diagnostic = `${result.stdout}\n${result.stderr}\n${result.error?.message ?? ""}`;
      const tail = diagnostic.slice(-8_192);
      process.stderr.write(
        `\n[cli-hardening:${cell.id}] failed (exit ${String(result.status)}); bounded output tail:\n${tail}\n`,
      );
    }
  }

  const receipt: HardeningMatrixReceipt = {
    schema_version: "ember-cli-hardening-matrix/v1",
    issue: 159,
    source_commit: sourceCommit,
    runner: {
      basename: basename(executable),
      sha256: runnerSha256,
    },
    matrix,
    overall: matrix.every((row) => row.outcome === "PASS") ? "PASS" : "FAIL",
    claim_boundary: {
      compiled_binary_live_smoke: false,
      model_capability: false,
      training_completion: false,
    },
  };
  const receiptSha256 = writeReceipt(resolve(options.receiptPath), receipt);

  if (receipt.overall !== "PASS") {
    throw new Error(
      `CLI hardening matrix failed: ${matrix.filter((row) => row.outcome === "FAIL").map((row) => row.id).join(", ")}`,
    );
  }
  validateHardeningMatrixReceipt(receipt, sourceCommit, runnerSha256);
  return { receipt, receiptSha256 };
}

function parseArgs(argv: string[]): { receiptPath: string } {
  let receiptPath = "";
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--receipt") receiptPath = argv[++i] ?? "";
    else throw new Error(`unknown hardening matrix argument: ${argv[i]}`);
  }
  if (receiptPath === "") throw new Error("--receipt is required");
  return { receiptPath };
}

if (import.meta.main) {
  const { receiptPath } = parseArgs(process.argv.slice(2));
  const sourceRoot = resolve(import.meta.dir, "..");
  const repositoryRoot = resolve(sourceRoot, "..", "..", "..");
  const result = runHardeningMatrix({
    repositoryRoot,
    sourceRoot,
    receiptPath,
  });
  process.stdout.write(JSON.stringify({
    status: result.receipt.overall,
    source_commit: result.receipt.source_commit,
    receipt_sha256: result.receiptSha256,
  }) + "\n");
}
