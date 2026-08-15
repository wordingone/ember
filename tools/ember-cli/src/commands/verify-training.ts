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
// worktree pinning. The resident Ember Lab daemon owns the bounded async job and its custody.
// Entangling the two into one command's state machine
// would reintroduce the "unbounded verified surface" complaint #1400 opens with. Scope split
// mirrors #1400's own framing: the full census stays the completion/audit gate; this is the
// training-launch preflight.
//
// No process bypasses ember-cli here either: this command is the only caller of the
// `ember-lab verify-training` subcommand in the cockpit.

import { createHash, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import {
  callEmberLab as callResidentEmberLab,
  configuredEmberLabPipe,
  type EmberLabRequestOptions,
} from "../services/ember-lab-rpc.ts";
import { emberStatePath } from "../utils/ember-state-root.ts";
import { resolveEmberSourceRootOrCwd } from "../utils/repo-root.ts";

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

interface VerifyTrainingCommandDeps {
  repoRoot?: string;
  env?: NodeJS.ProcessEnv;
  emberLabBinary?: string;
  timeoutMs?: number;
  readReceipt?: (path: string) => TrainingVerifyReceipt;
  callLab?: (options: EmberLabRequestOptions) => Promise<Record<string, unknown>>;
  sourceCommit?: string;
  nowMs?: () => number;
  sleep?: (milliseconds: number) => Promise<void>;
}

function defaultReadReceipt(path: string): TrainingVerifyReceipt {
  return JSON.parse(readFileSync(path, "utf8")) as TrainingVerifyReceipt;
}


function sha256File(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function embeddedSourceCommit(): string {
  const value = (globalThis as typeof globalThis & { __EMBER_BUILD_COMMIT__?: unknown }).__EMBER_BUILD_COMMIT__;
  if (typeof value !== "string" || !/^[0-9a-f]{40}$/.test(value)) {
    throw new Error("the Ember CLI build lacks one exact source commit identity");
  }
  return value;
}

function buildEvidenceVerifierManifest(options: {
  repoRoot: string;
  binary: string;
  args: string[];
  env: NodeJS.ProcessEnv;
  sourceCommit: string;
  nowMs: number;
  jobId: string;
  custodyRoot: string;
}): Record<string, unknown> {
  const cargoPath = join(options.repoRoot, "runtime", "ember-lab", "Cargo.toml");
  const closurePath = join(options.repoRoot, "manifests", "training-dependency-closure.json");
  const rootBindingPath = join(options.repoRoot, "README.md");
  const cacheRoot = join(options.custodyRoot, "cache");
  mkdirSync(cacheRoot, { recursive: true });
  const cacheEnv = Object.fromEntries(
    ["TEMP", "TMP", "TORCH_HOME", "TRITON_CACHE_DIR", "CUDA_CACHE_PATH", "HF_HOME", "XDG_CACHE_HOME"]
      .map((key) => {
        const path = join(cacheRoot, key.toLowerCase());
        mkdirSync(path, { recursive: true });
        return [key, path];
      }),
  );
  const maximumJobMemoryBytes = 512 * 1024 * 1024;
  return {
    schema_version: "ember-lab-dispatch-manifest-v3",
    job_id: options.jobId,
    source_commit: options.sourceCommit,
    not_before_ms: options.nowMs,
    expires_at_ms: options.nowMs + 60_000,
    resource_lease: `evidence-verifier:${options.jobId}`,
    program: { path: options.binary, sha256: sha256File(options.binary) },
    args: options.args,
    workload_profile: {
      profile_id: "evidence_verifier",
      pinned_host_producers: [{ kind: "receipt_verifier", maximum_bytes: 1024 * 1024 }],
      requires_ui_responsiveness: false,
      cpu_rate_percent: 50,
    },
    // evidence_verifier is not CPU-paced today and presents no window (truth-declared, not
    // aspirational -- runtime/ember-lab is the sole spawner and this command never opens a UI).
    cpu_pacing_class: "unpaced",
    window_contract: "headless_no_windows",
    env: { ...cacheEnv, EMBER_LAB_PIPE: configuredEmberLabPipe(options.env) },
    bindings: [
      { kind: "config", path: rootBindingPath, sha256: sha256File(rootBindingPath) },
      { kind: "config", path: cargoPath, sha256: sha256File(cargoPath) },
      { kind: "manifest", path: closurePath, sha256: sha256File(closurePath) },
    ],
    custody_root: options.custodyRoot,
    storage_reserves: [{ root: options.custodyRoot, minimum_free_bytes: 1 }],
    minimum_free_vram_bytes: 0,
    required_available_maximum_commit_bytes: maximumJobMemoryBytes + 10 * 1024 * 1024 * 1024,
    maximum_job_memory_bytes: maximumJobMemoryBytes,
    simulated_peak_commit_bytes: 1024 * 1024,
    preflight_receipt: join(options.custodyRoot, "dispatch-preflight.json"),
  };
}
// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createVerifyTrainingCommand(deps: VerifyTrainingCommandDeps = {}): RegistryCommand {
  const env = deps.env ?? process.env;
  const timeoutMs = deps.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const readReceipt = deps.readReceipt ?? defaultReadReceipt;
  const callLab = deps.callLab ?? callResidentEmberLab;
  const nowMs = deps.nowMs ?? Date.now;
  const sleep = deps.sleep ?? ((milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds)));

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

      if (!env["EMBER_LAB_PIPE"] && !deps.callLab) {
        return {
          type: "message" as const,
          message: "error: EMBER_LAB_PIPE is required; direct verify-training launch is forbidden",
          exitCode: 1,
        };
      }

      const repoRoot = deps.repoRoot ?? resolveEmberSourceRootOrCwd({ startDir: ctx.cwd }, "[ember] /verify-training");
      const emberLabBinary = deps.emberLabBinary ?? resolveEmberLabBinary(repoRoot, env);
      const dispatchNow = nowMs();
      const jobId = `verify-training-${dispatchNow}-${randomUUID()}`;
      const custodyBase = env["EMBER_STATE_ROOT"]
        ? resolve(env["EMBER_STATE_ROOT"]!, "verify-training")
        : emberStatePath(repoRoot, "verify-training");
      const custodyRoot = join(custodyBase, jobId);
      mkdirSync(custodyRoot, { recursive: true });
      const receiptPath = join(custodyRoot, "verify-training-receipt.json");

      const runArgs = ["verify-training", "--root", repoRoot, "--receipt", receiptPath];
      if (certificatePath) runArgs.push("--certificate", certificatePath);

      let dispatchSucceeded = false;
      let terminalObserved = false;
      try {
        const sourceCommit = deps.sourceCommit ?? embeddedSourceCommit();
        const manifest = buildEvidenceVerifierManifest({
          repoRoot,
          binary: emberLabBinary,
          args: runArgs,
          env,
          sourceCommit,
          nowMs: dispatchNow,
          jobId,
          custodyRoot,
        });
        if (certificatePath) {
          (manifest["bindings"] as Array<Record<string, unknown>>).push({
            kind: "verifier",
            path: certificatePath,
            sha256: sha256File(certificatePath),
          });
        }
        const manifestUtf8 = JSON.stringify(manifest);
        const dispatch = await callLab({
          pipeName: configuredEmberLabPipe(env),
          method: "dispatch_manifest",
          params: {
            manifest_utf8: manifestUtf8,
            manifest_sha256: createHash("sha256").update(manifestUtf8).digest("hex"),
          },
          timeoutMs: 5_000,
        });
        dispatchSucceeded = true;
        const expectedPreflightPath = manifest["preflight_receipt"] as string;
        const preflightSha256 = dispatch["preflight_receipt_sha256"];
        if (!Number.isSafeInteger(dispatch["pid"]) || (dispatch["pid"] as number) < 1) {
          throw new Error("ember-lab dispatch result lacks a positive pid");
        }
        if (dispatch["preflight_receipt_path"] !== expectedPreflightPath) {
          throw new Error("ember-lab dispatch returned the wrong preflight receipt path");
        }
        if (
          typeof preflightSha256 !== "string"
          || !/^[0-9a-f]{64}$/.test(preflightSha256)
          || sha256File(expectedPreflightPath) !== preflightSha256
        ) {
          throw new Error("ember-lab dispatch preflight receipt hash does not match custody bytes");
        }
        const deadline = nowMs() + timeoutMs;
        while (true) {
          const state = await callLab({
            pipeName: configuredEmberLabPipe(env),
            method: "job_state",
            params: { job_id: jobId },
            timeoutMs: 5_000,
          });
          const jobState = state["state"];
          if (jobState === "exited") {
            terminalObserved = true;
            break;
          }
          if (jobState !== "prepared" && jobState !== "running") {
            throw new Error(`ember-lab verify-training entered terminal state ${String(jobState)}`);
          }
          if (nowMs() >= deadline) throw new Error("ember-lab verify-training job timed out");
          await sleep(20);
        }
        const terminal = await callLab({
          pipeName: configuredEmberLabPipe(env),
          method: "job_exit_code",
          params: { job_id: jobId },
          timeoutMs: 5_000,
        });
        const exitCode = terminal["exit_code"];
        if (exitCode !== 0 && exitCode !== 1) {
          throw new Error(`ember-lab verify-training exited with code ${String(exitCode)}`);
        }
      } catch (err) {
        let message = err instanceof Error ? err.message : String(err);
        if (dispatchSucceeded && !terminalObserved) {
          let cleanupError: string | undefined;
          try {
            const stopped = await callLab({
              pipeName: configuredEmberLabPipe(env),
              method: "stop_job",
              params: { job_id: jobId },
              timeoutMs: 5_000,
            });
            if (stopped["stopped"] !== true) {
              throw new Error("stop_job did not confirm ownership cleanup");
            }
          } catch (stopError) {
            cleanupError = stopError instanceof Error ? stopError.message : String(stopError);
          }
          try {
            const settled = await callLab({
              pipeName: configuredEmberLabPipe(env),
              method: "job_state",
              params: { job_id: jobId },
              timeoutMs: 5_000,
            });
            if (!["stopped", "failed", "exited"].includes(String(settled["state"]))) {
              throw new Error(`job remained nonterminal in state ${String(settled["state"])}`);
            }
          } catch (settlementError) {
            const detail = settlementError instanceof Error
              ? settlementError.message
              : String(settlementError);
            cleanupError = cleanupError ? `${cleanupError}; ${detail}` : detail;
          }
          if (cleanupError) message += `; cleanup failed: ${cleanupError}`;
        }
        return {
          type: "message" as const,
          message: `error: ember-lab verify-training could not run: ${message}`,
          exitCode: 1,
        };
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
