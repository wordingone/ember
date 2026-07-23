// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/train.ts — /train: the phase-gated pre-training spine surface.
//
// HARD PRE-TRAINING GATE (load-bearing): this command NEVER invokes GPU/training.
// It runs the cond7 launch-packet readiness preflight
// (tools/ember-restart-3b/launch_packet.py) FIRST, and only when EVERY preflight
// passes (launch_packet exits 0) does it SURFACE the run_vertical_slice.py launch
// command STRING for the operator to run themselves. On ANY preflight failure,
// missing/malformed config, or unparseable output it FAILS CLOSED: no command is
// surfaced and a non-zero exit code is returned. The launch command's identity is
// read from launch_packet.py's own machine-readable summary
// (`named_ember02_command.command`) -- never hardcoded here, so a wrong/false
// entrypoint can never be printed as if it were the real governed one.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";
import { spawnSync } from "child_process";
import { join } from "path";

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
  try {
    const result = spawnSync(executable, args, {
      encoding: "utf8",
      windowsHide: true,
      // The clean-genesis + recovery preflights instantiate a tiny CPU model and
      // round-trip a checkpoint, so allow generous headroom; still CPU-only.
      timeout: 600_000,
      maxBuffer: 16 * 1024 * 1024,
    });
    return { status: result.status, stdout: result.stdout ?? "" };
  } catch {
    return { status: null, stdout: "" };
  }
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
  /** Certified B7 consumer, separate so tests prove the second boundary. */
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
}

interface TrainArgs {
  execute: boolean;
  certificate?: string;
  declarationLedger?: string;
  runSpec?: string;
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
 *  2. If it exits 0 AND its summary reports overall_ready with a named command:
 *     surface that run_vertical_slice.py launch COMMAND STRING as text.
 *  3. NEVER invoke the GPU/training launch itself.
 *  4. Any nonzero exit / missing-malformed config / unparseable output: FAIL
 *     CLOSED -- report the failure, surface NO command, non-zero exitCode.
 */
export function createTrainCommand(deps: TrainCommandDeps = {}): RegistryCommand {
  const runLaunchPacket = deps.runLaunchPacket ?? _defaultLaunchPacketRunner;
  const runCertifiedLaunch =
    deps.runCertifiedLaunch ?? _defaultLaunchPacketRunner;

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

      // (1) Run the preflight FIRST. This is the ONLY subprocess this command
      // ever spawns -- it never spawns a training/GPU launch.
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
        const executionReceipt = execution["execution_receipt"];
        const artifactRoot = execution["artifact_root"];
        if (
          typeof executionReceipt !== "string" ||
          executionReceipt === "" ||
          typeof artifactRoot !== "string" ||
          artifactRoot === ""
        ) {
          return {
            type: "message" as const,
            message:
              "error: certified train consumer response omitted execution_receipt or artifact_root.",
            exitCode: 1,
          };
        }
        return {
          type: "message" as const,
          message: [
            "certified bounded canary process completed.",
            `execution receipt: ${executionReceipt}`,
            `artifact root: ${artifactRoot}`,
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
