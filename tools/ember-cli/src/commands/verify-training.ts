// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/verify-training.ts — /verify-training: dispatch the training-scoped, GitHub-free
// closure verify implemented in runtime/ember-lab (issue #1400).
//
// This is deliberately a SEPARATE command from /verify (commands/verify.ts), not a flag on
// it. /verify dispatches the EMBER-01 completion census -- an async job against a pinned
// detached worktree, tens of minutes, gh + custody-census legs, its own job-state singleton
// (services/verify-watch.ts). /verify-training is a synchronous, single-shot check of
// EXACTLY the training dependency closure (#1332's closure_hash set): no gh, no network, no
// worktree pinning, no async job state -- a bounded child_process.execFile of the ember-lab
// binary that returns in low seconds. Entangling the two into one command's state machine
// would reintroduce the "unbounded verified surface" complaint #1400 opens with. Scope split
// mirrors #1400's own framing: the full census stays the completion/audit gate; this is the
// training-launch preflight.
//
// No process bypasses ember-cli here either: this command is the only caller of the
// `ember-lab verify-training` subcommand in the cockpit.

import { execFile } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { promisify } from "node:util";
import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import { resolveEmberSourceRootOrCwd } from "../utils/repo-root.ts";

const execFileAsync = promisify(execFile);

// Seconds-scale by design (#1400 target: "seconds to low minutes"); bounded so a hang here
// is itself a signal, never something worth waiting the way /verify's 180-minute census
// budget is.
const DEFAULT_TIMEOUT_MS = 60_000;

// ---------------------------------------------------------------------------
// ember-lab binary resolution
// ---------------------------------------------------------------------------

/** No prior TS-side convention resolves the ember-lab.exe path (grepped the cockpit source
 *  tree; the only existing consumer, services/ember-lab-rpc.ts, talks to an ALREADY-RUNNING
 *  daemon over a named pipe supplied via EMBER_LAB_PIPE -- it never locates or spawns the
 *  binary itself). This is new surface for this command, documented here rather than
 *  silently invented: `EMBER_LAB_BIN` env override first, else the cargo-conventional
 *  release then debug build output under the resolved repo root. */
export function resolveEmberLabBinary(
  repoRoot: string,
  env: NodeJS.ProcessEnv = process.env,
  fileExists: (path: string) => boolean = existsSync,
): string {
  const override = env["EMBER_LAB_BIN"];
  if (override && override.trim().length > 0) return override.trim();
  const exeName = process.platform === "win32" ? "ember-lab.exe" : "ember-lab";
  const release = join(repoRoot, "runtime", "ember-lab", "target", "release", exeName);
  if (fileExists(release)) return release;
  const debug = join(repoRoot, "runtime", "ember-lab", "target", "debug", exeName);
  if (fileExists(debug)) return debug;
  // Neither build output exists yet; return the release path so the resulting ENOENT
  // names the exact path an operator needs to build, rather than a bare "ember-lab.exe".
  return release;
}

// ---------------------------------------------------------------------------
// Receipt parsing (loose -- this command renders a summary, it does not re-validate the
// receipt's cryptographic content; that is ember-lab's job, proven by its own tests)
// ---------------------------------------------------------------------------

interface TrainingVerifyCheck {
  name: string;
  ok: boolean;
  detail: string;
}

interface TrainingVerifyReceipt {
  schema_version: string;
  ok: boolean;
  duration_ms: number;
  closure: { declared_files: number; closure_sha256: string };
  checks: TrainingVerifyCheck[];
  certificate: { path: string; closure_sha256_matches: boolean; pin_is_ancestor: boolean } | null;
}

export function renderVerifyTrainingResult(receipt: TrainingVerifyReceipt, receiptPath: string): string {
  const lines = [
    `verify-training: ${receipt.ok ? "PASS" : "FAIL"} -- ${receipt.duration_ms} ms`,
    `closure: ${receipt.closure.declared_files} declared files, closure_sha256=${receipt.closure.closure_sha256}`,
    "checks:",
    ...receipt.checks.map((check) => `  ${check.ok ? "ok" : "FAIL"}  ${check.name}: ${check.detail}`),
  ];
  if (receipt.certificate) {
    lines.push(
      `certificate: closure_sha256_matches=${receipt.certificate.closure_sha256_matches} ` +
        `pin_is_ancestor=${receipt.certificate.pin_is_ancestor}`,
    );
  }
  lines.push(`receipt: ${receiptPath}`);
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Deps (injectable for testing -- no real subprocess ever runs under test)
// ---------------------------------------------------------------------------

export interface VerifyTrainingRunner {
  (binary: string, args: string[], timeoutMs: number): Promise<{ stdout: string; stderr: string }>;
}

interface VerifyTrainingCommandDeps {
  repoRoot?: string;
  env?: NodeJS.ProcessEnv;
  emberLabBinary?: string;
  timeoutMs?: number;
  runProcess?: VerifyTrainingRunner;
  readReceipt?: (path: string) => TrainingVerifyReceipt;
}

const defaultRunProcess: VerifyTrainingRunner = async (binary, args, timeoutMs) => {
  const { stdout, stderr } = await execFileAsync(binary, args, { timeout: timeoutMs });
  return { stdout, stderr };
};

function defaultReadReceipt(path: string): TrainingVerifyReceipt {
  return JSON.parse(readFileSync(path, "utf8")) as TrainingVerifyReceipt;
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createVerifyTrainingCommand(deps: VerifyTrainingCommandDeps = {}): RegistryCommand {
  const env = deps.env ?? process.env;
  const timeoutMs = deps.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const runProcess = deps.runProcess ?? defaultRunProcess;
  const readReceipt = deps.readReceipt ?? defaultReadReceipt;

  return {
    name: "verify-training",
    description:
      "Dispatch the training-scoped, GitHub-free closure verify (runtime/ember-lab): exactly the training dependency closure, seconds-scale, zero gh/network. Distinct from /verify (the full EMBER-01 completion census). Usage: /verify-training [--certificate <path>]",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, ctx: CommandContext) {
      const trimmed = args.trim();
      let certificatePath: string | undefined;
      if (trimmed.length > 0) {
        const match = trimmed.match(/^--certificate\s+(\S+)$/);
        if (!match) {
          return {
            type: "message" as const,
            message: "usage: /verify-training [--certificate <path>]",
            exitCode: 1,
          };
        }
        certificatePath = match[1];
      }

      const repoRoot = deps.repoRoot ?? resolveEmberSourceRootOrCwd({ startDir: ctx.cwd }, "[ember] /verify-training");
      const emberLabBinary = deps.emberLabBinary ?? resolveEmberLabBinary(repoRoot, env);
      const receiptPath = join(repoRoot, ".ember", "verify-training-receipt.json");

      const runArgs = ["verify-training", "--root", repoRoot, "--receipt", receiptPath];
      if (certificatePath) runArgs.push("--certificate", certificatePath);

      try {
        await runProcess(emberLabBinary, runArgs, timeoutMs);
      } catch (err) {
        // Exit code 1 from ember-lab means a COMPLETED-but-red run (see main.rs) -- the
        // receipt still exists and is the thing to render, never swallowed as a bare
        // subprocess failure. Any other failure (ENOENT, timeout, crash) has no receipt to
        // read and is reported as an infra error.
        //
        // `code` here is the NUMERIC exit code Node's child_process attaches to the
        // rejected error object -- never a string to pattern-match. Node's real message for
        // a nonzero exit is just "Command failed: <cmd>\n"; it never contains the literal
        // text "code: 1" or "exit code 1", so a message-regex classifier here silently
        // never matches and every genuine FAIL used to render as an infra crash instead of
        // showing the receipt (rev-1400 finding, reproduced by driving the real compiled
        // binary -- see verify-training.test.ts).
        const code = typeof err === "object" && err !== null && "code" in err
          ? (err as { code?: unknown }).code
          : undefined;
        const looksLikeCompletedRedRun = code === 1;
        if (!looksLikeCompletedRedRun) {
          const message = err instanceof Error ? err.message : String(err);
          return {
            type: "message" as const,
            message: `error: ember-lab verify-training could not run: ${message}`,
            exitCode: 1,
          };
        }
      }

      let receipt: TrainingVerifyReceipt;
      try {
        receipt = readReceipt(receiptPath);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        return {
          type: "message" as const,
          message: `error: ember-lab verify-training produced no readable receipt at ${receiptPath}: ${message}`,
          exitCode: 1,
        };
      }

      return {
        type: "message" as const,
        message: renderVerifyTrainingResult(receipt, receiptPath),
        exitCode: receipt.ok ? undefined : 1,
      };
    },
  };
}
