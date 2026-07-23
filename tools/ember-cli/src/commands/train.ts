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

  return {
    name: "train",
    description: "Preflight EMBER-02 training readiness (cond7 launch packet) and surface the launch command; never launches training",
    isEnabled(): boolean {
      return true;
    },
    async execute(_args: string, ctx: CommandContext) {
      const repoRoot = deps.repoRoot ?? _defaultRepoRoot(ctx.cwd);
      const pythonBin = deps.pythonBin ?? process.env["EMBER_PYTHON_BIN"] ?? "python";
      const configPath =
        deps.configPath ?? join(repoRoot, "configs", "ember-restart-3b.json");
      const scriptPath =
        deps.scriptPath ?? join(repoRoot, "tools", "ember-restart-3b", "launch_packet.py");

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
