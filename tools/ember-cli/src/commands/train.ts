// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/train.ts — /train: the phase-gated pre-training spine surface.
//
// HARD PRE-TRAINING GATE (load-bearing): the default command is preflight-only.
// Explicit `--execute` mode is available only with all three certificate paths,
// after the same cond7 launch-packet readiness preflight succeeds, and invokes only
// the fixed certified_train_launch.py consumer. The named run_vertical_slice.py
// command from launch_packet output is never executed as a command string. On any
// preflight, certificate-consumer, or response failure, execution fails closed.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";
import { spawnSync } from "child_process";
import { createHash } from "crypto";
import { readFileSync } from "fs";
import { isAbsolute, join } from "path";

// ---------------------------------------------------------------------------
// Preflight spawn seam (injectable for testing; mirrors model.ts's runner)
// ---------------------------------------------------------------------------

/** Result of running the launch-packet preflight subprocess. */
export interface LaunchPacketRunResult {
  /** Subprocess exit code; null means it never ran / crashed / timed out. */
  status: number | null;
  /** Captured stdout (JSONL preflight rows + a summary object + comment lines). */
  stdout: string;
}

export const PREFLIGHT_TIMEOUT_MS = 600_000;
// The certificate permits at most 15 minutes of training. Keep one minute for
// interpreter startup, final receipt emission, and orderly process exit.
export const CERTIFIED_LAUNCH_TIMEOUT_MS = 16 * 60_000;

function _runPythonProcess(
  executable: string,
  args: string[],
  timeout: number,
): LaunchPacketRunResult {
  try {
    const result = spawnSync(executable, args, {
      encoding: "utf8",
      windowsHide: true,
      timeout,
      maxBuffer: 16 * 1024 * 1024,
    });
    return { status: result.status, stdout: result.stdout ?? "" };
  } catch {
    return { status: null, stdout: "" };
  }
}

/**
 * Real launch-packet runner: spawns `python launch_packet.py --config <cfg>`,
 * CPU-only, no GPU allocated (launch_packet.py itself allocates nothing). Any
 * spawn throw (ENOENT/timeout/crash) is caught and reported as status:null so
 * the command fails closed rather than propagating an uncaught rejection.
 *
 * @internal exported (prefixed _) so unit tests inject a mock and NO real
 *           subprocess ever runs.
 */
export function _defaultLaunchPacketRunner(
  executable: string,
  args: string[],
): LaunchPacketRunResult {
  // The clean-genesis + recovery preflights instantiate a tiny CPU model and
  // round-trip a checkpoint, so allow generous headroom; still CPU-only.
  return _runPythonProcess(executable, args, PREFLIGHT_TIMEOUT_MS);
}

/** Fixed certified-consumer runner with headroom above the 15-minute canary. */
export function _defaultCertifiedLaunchRunner(
  executable: string,
  args: string[],
): LaunchPacketRunResult {
  return _runPythonProcess(executable, args, CERTIFIED_LAUNCH_TIMEOUT_MS);
}

// ---------------------------------------------------------------------------
// Output parsing (fail-closed)
// ---------------------------------------------------------------------------

interface PreflightRow {
  record?: unknown;
  name?: unknown;
  status?: unknown;
  reason?: unknown;
}

interface LaunchPacketSummary {
  record?: unknown;
  overall_ready?: unknown;
  named_ember02_command?: unknown;
}

interface ParsedLaunchPacketOutput {
  /** Every parseable JSON object line (preflight rows + summary). */
  rows: Record<string, unknown>[];
  /** The single `record: "launch-packet-summary"` object, if present. */
  summary: LaunchPacketSummary | null;
}

/**
 * Parse launch_packet.py's stdout. It prints one JSON object per line (each
 * preflight row, then a `launch-packet-summary` object) plus `# ...` comment
 * lines. Non-JSON / comment lines are skipped. Returns whatever parsed, plus
 * the summary object located by its `record` tag. Never throws.
 */
function _parseLaunchPacketOutput(stdout: string): ParsedLaunchPacketOutput {
  const rows: Record<string, unknown>[] = [];
  let summary: LaunchPacketSummary | null = null;
  for (const line of stdout.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("{")) continue;
    let obj: unknown;
    try {
      obj = JSON.parse(trimmed);
    } catch {
      continue;
    }
    if (typeof obj !== "object" || obj === null) continue;
    const record = obj as Record<string, unknown>;
    rows.push(record);
    if (record["record"] === "launch-packet-summary") {
      summary = record as LaunchPacketSummary;
    }
  }
  return { rows, summary };
}

/** Collect human-readable reasons from any failing preflight rows. */
function _failureReasons(rows: Record<string, unknown>[]): string[] {
  const reasons: string[] = [];
  for (const row of rows) {
    if (row["record"] === "preflight" && row["status"] === "fail") {
      const name = typeof row["name"] === "string" ? row["name"] : "(unnamed)";
      const reason = typeof row["reason"] === "string" ? row["reason"] : "no reason given";
      reasons.push(`  - ${name}: ${reason}`);
    }
  }
  return reasons;
}

/**
 * Extract the validated launch command string from a summary object, or null.
 * FAIL-CLOSED: only returns a command when overall_ready === true AND
 * named_ember02_command.command is a non-empty string.
 */
function _extractLaunchCommand(
  summary: LaunchPacketSummary | null,
): { command: string; note: string | null; entrypoint: string | null } | null {
  if (summary === null) return null;
  if (summary.overall_ready !== true) return null;
  const named = summary.named_ember02_command;
  if (typeof named !== "object" || named === null) return null;
  const namedRec = named as Record<string, unknown>;
  const command = namedRec["command"];
  if (typeof command !== "string" || command.trim() === "") return null;
  const note = typeof namedRec["note"] === "string" ? namedRec["note"] : null;
  const entrypoint =
    typeof namedRec["library_entrypoint"] === "string" ? namedRec["library_entrypoint"] : null;
  return { command, note, entrypoint };
}

// ---------------------------------------------------------------------------
// Path defaults
// ---------------------------------------------------------------------------

/** Default ember repo root, re-derived read-only the same way sibling commands do. */
function _defaultRepoRoot(cwd: string): string {
  return resolveEmberRepoRootOrCwd({ startDir: cwd }, "[ember] /train");
}

// ---------------------------------------------------------------------------
// Deps (injectable for testing)
// ---------------------------------------------------------------------------

interface TrainCommandDeps {
  /**
   * The launch-packet preflight runner. Tests inject a mock so NO real
   * subprocess (and therefore no torch/CPU work, and never any GPU/training
   * launch) is ever invoked. Defaults to _defaultLaunchPacketRunner.
   */
  runLaunchPacket?: (executable: string, args: string[]) => LaunchPacketRunResult;
  /** Certified B7 consumer with a timeout separate from the CPU preflight. */
  runCertifiedLaunch?: (executable: string, args: string[]) => LaunchPacketRunResult;
  /** Python executable; defaults to EMBER_PYTHON_BIN env, else "python". */
  pythonBin?: string;
  /** Ember repo root override; defaults to _defaultRepoRoot(ctx.cwd). */
  repoRoot?: string;
  /** Config path override; defaults to <repoRoot>/configs/ember-restart-3b.json. */
  configPath?: string;
  /** launch_packet.py path override; defaults to <repoRoot>/tools/ember-restart-3b/launch_packet.py. */
  scriptPath?: string;
  /** certified_train_launch.py path override. */
  certifiedLaunchScriptPath?: string;
  /** Read exact authority and receipt bytes; injectable so tests never touch disk. */
  readExecutionReceipt?: (path: string) => Buffer;
}

interface TrainArgs {
  execute: boolean;
  certificate?: string;
  declarationLedger?: string;
  runSpec?: string;
}

const CERTIFIED_EXECUTION_RECEIPT_FIELDS = [
  "schema_version",
  "certificate_sha256",
  "certificate_file_sha256",
  "declaration_ledger_sha256",
  "run_spec_sha256",
  "public_master_sha",
  "argv",
  "exit_code",
  "artifact_root",
  "runner_receipt",
  "dispatch_job_id",
  "dispatch_pid",
  "dispatch_manifest_sha256",
  "preflight_receipt",
  "preflight_receipt_sha256",
  "emberd_binary_sha256",
  "emberd_source_sha256",
  "claim_scope",
].sort();
const EMBERD_PREFLIGHT_RECEIPT_FIELDS = [
  "schema_version",
  "result",
  "job_id",
  "source_commit",
  "observed_at_ms",
  "not_before_ms",
  "expires_at_ms",
  "dispatch_manifest_sha256",
  "program",
  "bindings",
  "args_sha256",
  "env_sha256",
  "custody_root",
  "storage_reserves",
  "vram_reserve",
  "maximum_job_memory_bytes",
  "host_commit",
  "emberd_identity",
  "governed_canary",
].sort();
const CERTIFIED_EXECUTION_CLAIM_FIELDS = [
  "capability_claimed",
  "admission_claimed",
  "sufficient_pretraining_claimed",
  "verified_expert_accretion_claimed",
  "competitiveness_claimed",
].sort();

function _verifyCertifiedExecutionReceipt(
  execution: Record<string, unknown>,
  readReceipt: (path: string) => Buffer,
  expectedAuthoritySha256: {
    certificateFile: string;
    declarationLedger: string;
    runSpec: string;
  },
): { path: string; artifactRoot: string } {
  const path = execution["execution_receipt"];
  const expectedSha256 = execution["execution_receipt_sha256"];
  const artifactRoot = execution["artifact_root"];
  if (
    execution["outcome"] !== "DISPATCHED" ||
    typeof path !== "string" ||
    !isAbsolute(path) ||
    typeof expectedSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(expectedSha256) ||
    typeof artifactRoot !== "string" ||
    !isAbsolute(artifactRoot)
  ) {
    throw new Error("certified response omitted content-addressed receipt bytes");
  }
  const bytes = readReceipt(path);
  if (createHash("sha256").update(bytes).digest("hex") !== expectedSha256) {
    throw new Error("certified execution receipt hash does not match receipt bytes");
  }
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new Error("certified execution receipt bytes are not strict UTF-8 JSON");
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("certified execution receipt is not an object");
  }
  const receipt = value as Record<string, unknown>;
  const actualFields = Object.keys(receipt).sort();
  if (
    actualFields.length !== CERTIFIED_EXECUTION_RECEIPT_FIELDS.length ||
    actualFields.some(
      (field, index) => field !== CERTIFIED_EXECUTION_RECEIPT_FIELDS[index],
    )
  ) {
    throw new Error("certified execution receipt fields are not closed");
  }
  if (
    receipt["schema_version"] !== "ember-certified-train-execution-v1" ||
    receipt["exit_code"] !== 0 ||
    receipt["artifact_root"] !== artifactRoot ||
    receipt["certificate_file_sha256"] !==
      expectedAuthoritySha256.certificateFile ||
    receipt["declaration_ledger_sha256"] !==
      expectedAuthoritySha256.declarationLedger ||
    receipt["run_spec_sha256"] !== expectedAuthoritySha256.runSpec
  ) {
    throw new Error(
      "certified execution receipt does not bind the supplied certificate, declaration ledger, run specification, and Emberd dispatch",
    );
  }
  const dispatchJobId = receipt["dispatch_job_id"];
  const dispatchPid = receipt["dispatch_pid"];
  const manifestSha256 = receipt["dispatch_manifest_sha256"];
  const preflightPath = receipt["preflight_receipt"];
  const preflightSha256 = receipt["preflight_receipt_sha256"];
  const emberdBinarySha256 = receipt["emberd_binary_sha256"];
  const emberdSourceSha256 = receipt["emberd_source_sha256"];
  if (
    typeof dispatchJobId !== "string" ||
    dispatchJobId.length === 0 ||
    !Number.isSafeInteger(dispatchPid) ||
    (dispatchPid as number) < 1 ||
    typeof preflightPath !== "string" ||
    !isAbsolute(preflightPath) ||
    [manifestSha256, preflightSha256, emberdBinarySha256, emberdSourceSha256]
      .some((value) => typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value))
  ) {
    throw new Error("certified execution receipt has invalid Emberd dispatch identity");
  }
  const preflightBytes = readReceipt(preflightPath);
  if (
    createHash("sha256").update(preflightBytes).digest("hex") !==
    preflightSha256
  ) {
    throw new Error("Emberd preflight receipt hash does not match receipt bytes");
  }
  let preflightValue: unknown;
  try {
    preflightValue = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(preflightBytes),
    );
  } catch {
    throw new Error("Emberd preflight receipt bytes are not strict UTF-8 JSON");
  }
  if (
    typeof preflightValue !== "object" ||
    preflightValue === null ||
    Array.isArray(preflightValue)
  ) {
    throw new Error("Emberd preflight receipt is not an object");
  }
  const preflight = preflightValue as Record<string, unknown>;
  const preflightFields = Object.keys(preflight).sort();
  if (
    preflightFields.length !== EMBERD_PREFLIGHT_RECEIPT_FIELDS.length ||
    preflightFields.some(
      (field, index) => field !== EMBERD_PREFLIGHT_RECEIPT_FIELDS[index],
    )
  ) {
    throw new Error("Emberd preflight receipt fields are not closed");
  }
  const emberdIdentity = preflight["emberd_identity"];
  if (
    preflight["schema_version"] !== "emberd-dispatch-preflight-v1" ||
    preflight["result"] !== "PREFLIGHT_PASSED" ||
    preflight["job_id"] !== dispatchJobId ||
    preflight["source_commit"] !== receipt["public_master_sha"] ||
    preflight["dispatch_manifest_sha256"] !== manifestSha256 ||
    typeof emberdIdentity !== "object" ||
    emberdIdentity === null ||
    Array.isArray(emberdIdentity) ||
    (emberdIdentity as Record<string, unknown>)["binary_sha256"] !==
      emberdBinarySha256 ||
    (emberdIdentity as Record<string, unknown>)["source_sha256"] !==
      emberdSourceSha256
  ) {
    throw new Error("Emberd preflight receipt does not bind the certified dispatch");
  }
  const claims = receipt["claim_scope"];
  if (
    typeof claims !== "object" ||
    claims === null ||
    Array.isArray(claims)
  ) {
    throw new Error("certified execution receipt exceeds the canary claim boundary");
  }
  const claimRecord = claims as Record<string, unknown>;
  const claimFields = Object.keys(claimRecord).sort();
  if (
    claimFields.length !== CERTIFIED_EXECUTION_CLAIM_FIELDS.length ||
    claimFields.some(
      (field, index) => field !== CERTIFIED_EXECUTION_CLAIM_FIELDS[index],
    ) ||
    Object.values(claimRecord).some(
      (claimed) => claimed !== false,
    )
  ) {
    throw new Error("certified execution receipt exceeds the canary claim boundary");
  }
  return { path, artifactRoot };
}

function _parseTrainArgs(raw: string): TrainArgs {
  const tokens = raw.trim() === "" ? [] : raw.trim().split(/\s+/);
  const parsed: TrainArgs = { execute: false };
  const seen = new Set<string>();
  const valued = new Map<string, "certificate" | "declarationLedger" | "runSpec">([
    ["--certificate", "certificate"],
    ["--declaration-ledger", "declarationLedger"],
    ["--run-spec", "runSpec"],
  ]);
  for (let index = 0; index < tokens.length; index += 1) {
    const option = tokens[index]!;
    if (seen.has(option)) {
      throw new Error(`duplicate train option: ${option}`);
    }
    seen.add(option);
    if (option === "--execute") {
      parsed.execute = true;
      continue;
    }
    const field = valued.get(option);
    if (field === undefined) {
      throw new Error(`unknown train option: ${option}`);
    }
    const value = tokens[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`missing value for ${option}`);
    }
    parsed[field] = value;
    index += 1;
  }
  if (
    !parsed.execute &&
    (parsed.certificate !== undefined ||
      parsed.declarationLedger !== undefined ||
      parsed.runSpec !== undefined)
  ) {
    throw new Error("authority paths require --execute");
  }
  if (
    parsed.execute &&
    (parsed.certificate === undefined ||
      parsed.declarationLedger === undefined ||
      parsed.runSpec === undefined)
  ) {
    throw new Error(
      "usage: /train --execute --certificate <path> --declaration-ledger <path> --run-spec <path>",
    );
  }
  return parsed;
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Creates the /train command. Registered in command-registry.ts as "train".
 *
 * Behavior (spec):
 *  1. Spawn the cond7 launch-packet preflight FIRST (never training).
 *  2. Without `--execute`, surface the validated named command as text only.
 *  3. With `--execute` and all certificate paths, invoke exactly one fixed
 *     certified_train_launch.py consumer; never execute the named command string.
 *  4. Any malformed input, nonzero exit, or invalid response fails closed.
 */
export function createTrainCommand(deps: TrainCommandDeps = {}): RegistryCommand {
  const runLaunchPacket = deps.runLaunchPacket ?? _defaultLaunchPacketRunner;
  const runCertifiedLaunch =
    deps.runCertifiedLaunch ?? _defaultCertifiedLaunchRunner;
  const readExecutionReceipt =
    deps.readExecutionReceipt ?? ((path: string) => readFileSync(path));

  return {
    name: "train",
    description: "Preflight EMBER-02 training readiness; execute only through an explicit declared B7 certificate",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, ctx: CommandContext) {
      let trainArgs: TrainArgs;
      try {
        trainArgs = _parseTrainArgs(args);
      } catch (error) {
        return {
          type: "message" as const,
          message: `error: ${error instanceof Error ? error.message : "invalid /train arguments"}`,
          exitCode: 1,
        };
      }

      const repoRoot = deps.repoRoot ?? _defaultRepoRoot(ctx.cwd);
      const pythonBin = deps.pythonBin ?? process.env["EMBER_PYTHON_BIN"] ?? "python";
      const configPath =
        deps.configPath ?? join(repoRoot, "configs", "ember-restart-3b.json");
      const scriptPath =
        deps.scriptPath ?? join(repoRoot, "tools", "ember-restart-3b", "launch_packet.py");
      const certifiedLaunchScriptPath =
        deps.certifiedLaunchScriptPath ??
        join(
          repoRoot,
          "tools",
          "ember-restart-3b",
          "certified_train_launch.py",
        );

      // (1) Run the preflight first. It is the only subprocess in default mode;
      // certified execute mode may invoke only the fixed consumer below.
      let result: LaunchPacketRunResult;
      try {
        result = runLaunchPacket(pythonBin, [scriptPath, "--config", configPath]);
      } catch {
        // A runner that throws (crash/ENOENT/timeout raised as an exception)
        // fails closed rather than crashing the command.
        return {
          type: "message" as const,
          message:
            "error: launch-packet preflight could not be started -- training is BLOCKED (fail-closed). No launch command surfaced.",
          exitCode: 1,
        };
      }

      const parsed = _parseLaunchPacketOutput(result.stdout);

      // (4) Nonzero exit => a preflight failed OR config missing/malformed
      // (launch_packet.py raises on a missing/unreadable config, exiting
      // nonzero). Fail closed with whatever reasons we could parse.
      if (result.status !== 0) {
        const reasons = _failureReasons(parsed.rows);
        const lines = [
          "error: launch-packet preflight FAILED -- EMBER-02 training is BLOCKED (fail-closed).",
        ];
        if (reasons.length > 0) {
          lines.push("failing preflights:");
          lines.push(...reasons);
        } else {
          lines.push(
            `  (no parseable preflight rows; launch_packet exit=${result.status ?? "null"} -- config missing/malformed or the runner never produced output)`,
          );
        }
        lines.push("No launch command surfaced.");
        return {
          type: "message" as const,
          message: lines.join("\n"),
          exitCode: 1,
        };
      }

      // (2) Exit 0: parse the summary and extract the VALIDATED launch command.
      // Fail closed if the summary is missing/unparseable, not overall_ready,
      // or carries no command string (defensive -- exit 0 should imply all of
      // these hold, but never surface a command we could not validate).
      const extracted = _extractLaunchCommand(parsed.summary);
      if (extracted === null) {
        return {
          type: "message" as const,
          message:
            "error: launch-packet exited 0 but its readiness summary was missing/unparseable or named no launch command -- training is BLOCKED (fail-closed). No launch command surfaced.",
          exitCode: 1,
        };
      }

      if (trainArgs.execute) {
        let expectedAuthoritySha256: {
          certificateFile: string;
          declarationLedger: string;
          runSpec: string;
        };
        try {
          expectedAuthoritySha256 = {
            certificateFile: createHash("sha256")
              .update(readExecutionReceipt(trainArgs.certificate!))
              .digest("hex"),
            declarationLedger: createHash("sha256")
              .update(readExecutionReceipt(trainArgs.declarationLedger!))
              .digest("hex"),
            runSpec: createHash("sha256")
              .update(readExecutionReceipt(trainArgs.runSpec!))
              .digest("hex"),
          };
        } catch {
          return {
            type: "message" as const,
            message:
              "error: certified authority bytes could not be read before dispatch; no training process was authorized.",
            exitCode: 1,
          };
        }
        let certifiedResult: LaunchPacketRunResult;
        try {
          certifiedResult = runCertifiedLaunch(pythonBin, [
            certifiedLaunchScriptPath,
            "--root",
            repoRoot,
            "--certificate",
            trainArgs.certificate!,
            "--declaration-ledger",
            trainArgs.declarationLedger!,
            "--run-spec",
            trainArgs.runSpec!,
            "--expected-certificate-file-sha256",
            expectedAuthoritySha256.certificateFile,
            "--expected-declaration-ledger-sha256",
            expectedAuthoritySha256.declarationLedger,
            "--expected-run-spec-sha256",
            expectedAuthoritySha256.runSpec,
          ]);
        } catch {
          return {
            type: "message" as const,
            message:
              "error: certified train consumer could not be started; no training process was authorized.",
            exitCode: 1,
          };
        }
        if (certifiedResult.status !== 0) {
          const detail = certifiedResult.stdout.trim();
          return {
            type: "message" as const,
            message: [
              "error: certified train consumer refused or failed.",
              detail || "No certified execution receipt was produced.",
            ].join("\n"),
            exitCode: certifiedResult.status ?? 1,
          };
        }
        let execution: Record<string, unknown>;
        try {
          const parsedResult: unknown = JSON.parse(certifiedResult.stdout);
          if (typeof parsedResult !== "object" || parsedResult === null) {
            throw new Error("not an object");
          }
          execution = parsedResult as Record<string, unknown>;
        } catch {
          return {
            type: "message" as const,
            message:
              "error: certified train consumer exited 0 without a valid execution receipt response.",
            exitCode: 1,
          };
        }
        let verifiedExecution: { path: string; artifactRoot: string };
        try {
          verifiedExecution = _verifyCertifiedExecutionReceipt(
            execution,
            readExecutionReceipt,
            expectedAuthoritySha256,
          );
        } catch (error) {
          return {
            type: "message" as const,
            message:
              "error: certified train consumer returned unverified receipt bytes: " +
              (error instanceof Error ? error.message : String(error)),
            exitCode: 1,
          };
        }
        return {
          type: "message" as const,
          message: [
            "certified bounded canary was accepted by Emberd.",
            `execution receipt: ${verifiedExecution.path}`,
            `artifact root: ${verifiedExecution.artifactRoot}`,
          ].join("\n"),
        };
      }

      // Success: surface the command STRING as text for the operator to run.
      // (3) The command is NOT executed here -- this is the hard pre-training gate.
      const lines = [
        "launch-packet: all preflights GREEN -- EMBER-02 is launch-ready.",
        "",
        "This command does NOT launch training. Run the following yourself to start the governed clean-genesis 3B pretrain:",
        "",
        extracted.command,
      ];
      if (extracted.entrypoint) {
        lines.push("", `entrypoint: ${extracted.entrypoint}`);
      }
      if (extracted.note) {
        lines.push("", `note: ${extracted.note}`);
      }
      return {
        type: "message" as const,
        message: lines.join("\n"),
      };
    },
  };
}
