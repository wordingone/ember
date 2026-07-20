// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/model.ts — /model load|unload|status command for managed model lifecycle.
// Allows the operator to free GPU VRAM by unloading the local model without closing the cockpit.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import {
  getModelState,
  loadModel,
  unloadModel,
  type ModelLifecycleDeps,
} from "../services/model-lifecycle.ts";
import { waitForServerReady, LLAMA_SERVER_DEFAULT_PORT } from "../services/runtime-bootstrap.ts";
import { appendFile } from "fs/promises";
import { existsSync } from "fs";
import { spawnSync } from "child_process";
import { dirname, join, resolve } from "path";
import { getGitRepositoryRoot } from "../utils/git.ts";

// ---------------------------------------------------------------------------
// Checkpoint identity resolution (cond3 inc2a)
// ---------------------------------------------------------------------------

const SHA256_RE = /^[0-9a-f]{64}$/;

/** Resolved, VALIDATED checkpoint identity -- never a raw/unvalidated field. */
export interface ResolvedModelIdentity {
  byte_sha256: string;
  disposition: string;
}

interface ResolveIdentityRunner {
  status: number | null;
  stdout: string;
}

function _defaultIdentityRunner(executable: string, args: string[]): ResolveIdentityRunner {
  try {
    const result = spawnSync(executable, args, {
      encoding: "utf8",
      windowsHide: true,
      timeout: 30_000,
    });
    return { status: result.status, stdout: result.stdout ?? "" };
  } catch {
    return { status: null, stdout: "" };
  }
}

/**
 * Resolves the active checkpoint's identity by spawning validate_identity.py
 * (scripts/ember_01_identity/validate_identity.py) against the manifest at
 * `manifestPath`, and parsing its JSON verdict.
 *
 * FAIL-CLOSED: returns null (never a guessed/partial identity) whenever the
 * manifest is missing, the resolver script is missing, the subprocess fails
 * or times out, the resolver's exit code is non-zero (validation rejected
 * the manifest), the output is not parseable JSON, or the parsed payload
 * doesn't carry a well-formed sha256 + non-empty disposition. Callers must
 * treat a null return as "identity unverified" -- never render/spawn a bare
 * name as though it were checkpoint-identity-bearing.
 *
 * A checkpoint file, if present alongside the manifest as `checkpoint`,
 * is passed via --checkpoint so byte-for-byte re-derivation is exercised;
 * this is the convention documented in
 * scripts/ember_01_identity/README-model-command-identity.md.
 *
 * @internal exported (prefixed _) for unit tests to inject a mock runner.
 */
export async function _resolveModelIdentity(
  manifestPath: string,
  runner: (executable: string, args: string[]) => ResolveIdentityRunner = _defaultIdentityRunner,
): Promise<ResolvedModelIdentity | null> {
  if (!manifestPath || !existsSync(manifestPath)) return null;

  const repoRoot = (await getGitRepositoryRoot(dirname(manifestPath))) ?? process.cwd();
  const scriptPath = resolve(repoRoot, "scripts", "ember_01_identity", "validate_identity.py");
  if (!existsSync(scriptPath)) return null;

  const args = [scriptPath, manifestPath];
  const checkpointPath = join(dirname(manifestPath), "checkpoint");
  if (existsSync(checkpointPath)) {
    args.push("--checkpoint", checkpointPath);
  }

  const pythonExecutable = process.env["EMBER_PYTHON_BIN"] ?? "python";
  let result: ResolveIdentityRunner;
  try {
    result = runner(pythonExecutable, args);
  } catch {
    // Any injected/real runner throwing (crash, ENOENT, timeout raised as an
    // exception, etc.) fails closed -- never propagates as an uncaught
    // rejection that would crash the /model command itself.
    return null;
  }
  if (result.status !== 0) return null;

  let payload: unknown;
  try {
    payload = JSON.parse(result.stdout);
  } catch {
    return null;
  }
  if (typeof payload !== "object" || payload === null) return null;
  const record = payload as Record<string, unknown>;
  if (record["ok"] !== true) return null;

  const byteSha256 = record["byte_sha256"];
  const disposition = record["disposition"];
  if (
    typeof byteSha256 !== "string" ||
    !SHA256_RE.test(byteSha256) ||
    typeof disposition !== "string" ||
    disposition.trim() === ""
  ) {
    return null;
  }

  return { byte_sha256: byteSha256, disposition };
}

// ---------------------------------------------------------------------------
// Kill-receipts ledger wiring
// ---------------------------------------------------------------------------

/** Default kill-receipt audit ledger (cwd-relative .ember/; used only when neither
 *  EMBER_KILL_RECEIPTS_PATH nor the legacy KILL_RECEIPTS_PATH is set). */
const DEFAULT_KILL_RECEIPTS_PATH = ".ember/kill-receipts.jsonl";

/**
 * Factory that produces a kill-receipt writer function.
 * Exported (prefixed _) for unit tests to inject a mock appendFileFn and
 * inspect the JSONL that would be written, without touching the real ledger.
 *
 * issue #881: two defects fixed here.
 * (a) Path: EMBER_KILL_RECEIPTS_PATH is now honored first — the SAME env var
 *     services/activity-feed.ts's watchdog dashboard resolves the authoritative
 *     shared vigil kill-receipts ledger from (liveness-watchdog-state.json's
 *     `kill_receipts_path` / EMBER_KILL_RECEIPTS_PATH). The old default wrote to
 *     a cwd-relative `.ember/kill-receipts.jsonl` that ledger tail-poll never
 *     watches — a receipt landed, but nowhere authoritative.
 * (b) Durability: the returned writer is now awaited by the caller and REJECTS
 *     on I/O failure instead of swallowing it fire-and-forget — receipt-first
 *     (kill-discipline) requires the write to durably land BEFORE release, not
 *     merely be attempted.
 * @internal
 */
export function _makeKillReceiptWriter(opts: {
  ledgerPath?: string;
  appendFileFn?: (path: string, data: string) => Promise<void>;
}): (rec: { pid: number; match_rule: string }) => Promise<void> {
  const ledgerPath =
    opts.ledgerPath ??
    process.env["EMBER_KILL_RECEIPTS_PATH"] ??
    process.env["KILL_RECEIPTS_PATH"] ??
    DEFAULT_KILL_RECEIPTS_PATH;
  const afn: (path: string, data: string) => Promise<void> =
    opts.appendFileFn ?? ((p, d) => appendFile(p, d));

  return async (rec: { pid: number; match_rule: string }): Promise<void> => {
    const entry =
      JSON.stringify({
        ts: new Date().toISOString(),
        script: "ember-cli /model unload",
        pids: [rec.pid],
        match_rule: rec.match_rule,
        survivors_expected: "none",
      }) + "\n";
    // Durable, awaited: a rejection propagates to the caller (unloadModel), which aborts
    // the unload before the child is released — fail-closed, never fire-and-forget.
    await afn(ledgerPath, entry);
  };
}

// ---------------------------------------------------------------------------
// Deps interface (injectable for testing)
// ---------------------------------------------------------------------------

interface ModelCommandDeps {
  loadModel?: (deps: ModelLifecycleDeps) => Promise<string>;
  unloadModel?: (deps: ModelLifecycleDeps) => Promise<string>;
  getModelState?: () => string;
  writeKillReceipt?: (rec: { pid: number; match_rule: string }) => Promise<void>;
  /** Injectable for tests; defaults to the real _resolveModelIdentity. */
  resolveModelIdentity?: (manifestPath: string) => Promise<ResolvedModelIdentity | null>;
  /** Injectable for tests; defaults to EMBER_MODEL_IDENTITY_MANIFEST env / cwd convention. */
  manifestPath?: string;
}

/** Default manifest path convention: EMBER_MODEL_IDENTITY_MANIFEST env override,
 * else `.ember/model-identity.json` relative to cwd. */
function _defaultManifestPath(cwd: string): string {
  return process.env["EMBER_MODEL_IDENTITY_MANIFEST"] ?? join(cwd, ".ember", "model-identity.json");
}

// ---------------------------------------------------------------------------
// Real implementations of injected deps
// ---------------------------------------------------------------------------

/**
 * Production kill-receipt writer. Appends a JSONL line to the infra ledger.
 * Fire-and-forget; I/O errors are swallowed with a warn log (non-fatal).
 * The function returns void synchronously; the append is async under the hood.
 */
const realWriteKillReceipt = _makeKillReceiptWriter({});

// ---------------------------------------------------------------------------
// Factory (AC8)
// ---------------------------------------------------------------------------

/**
 * Creates the /model command with injected deps.
 * AC8: registered in command-registry.ts with name "model", no alias collision.
 */
export function createModelCommand(deps: ModelCommandDeps = {}): RegistryCommand {
  const doLoadModel = deps.loadModel ?? loadModel;
  const doUnloadModel = deps.unloadModel ?? unloadModel;
  const doGetModelState = deps.getModelState ?? getModelState;
  const doWriteKillReceipt = deps.writeKillReceipt ?? realWriteKillReceipt;
  const doResolveModelIdentity = deps.resolveModelIdentity ?? _resolveModelIdentity;

  return {
    name: "model",
    description: "Control the local model: load|unload|status",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, ctx: CommandContext) {
      // AC9, AC10: parse subcommand
      const subcommand = args.trim().split(/\s+/)[0] ?? "";
      const manifestPath = deps.manifestPath ?? _defaultManifestPath(ctx.cwd);

      // AC9: /model status → current state + pid (if loaded)
      if (subcommand === "status" || subcommand === "") {
        const state = doGetModelState();

        // cond3 inc2a: checkpoint identity is SOURCED from a validated
        // manifest only. Fail-closed at the RENDER level -- status ALWAYS
        // reports the model's runtime state (its core job: is the model
        // loaded?), but it never renders a checkpoint identity it could not
        // validate. When the manifest is absent/invalid/mismatched, the
        // identity is shown as an explicit UNVERIFIED marker (never a bare
        // or guessed sha), so the operator sees the truth rather than a
        // false claim -- and a read-only status query is never broken by a
        // missing manifest.
        const identity = await doResolveModelIdentity(manifestPath);
        const statusLine =
          identity === null
            ? `model: ${state} — identity: UNVERIFIED (no validated manifest)`
            : `model: ${state} — identity: ${identity.byte_sha256} (${identity.disposition})`;
        return {
          type: "message" as const,
          message: statusLine,
        };
      }

      // AC10: /model unload
      if (subcommand === "unload") {
        const modelLifecycleDeps: ModelLifecycleDeps = {
          spawnModel: () => ({ pid: 0 }), // unused in unload
          // issue #881: fallback child-only release for a registration that carried no real
          // handle (e.g. deps-injection seam / an adopted-but-unregistered server). Exact
          // tracked PID only — never a name-pattern match. Production always prefers the
          // real owned ServerHandle.kill() wired through registerManagedModel
          // (entrypoints/process-entry.ts), so this fallback is not the normal path.
          killPid: (pid: number) => {
            try {
              process.kill(pid, "SIGTERM");
            } catch {
              // already gone / not our process — nothing more a PID-scoped kill can do.
            }
          },
          waitReady: async () => {}, // unused in unload
          writeKillReceipt: doWriteKillReceipt,
          isExternal: () => process.env["EMBER_MODEL_URL"] !== undefined,
          now: () => new Date().toISOString(),
        };

        try {
          const status = await doUnloadModel(modelLifecycleDeps);
          return {
            type: "message" as const,
            message: status,
          };
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          return {
            type: "message" as const,
            message: `error: failed to unload: ${msg}`,
          };
        }
      }

      // AC10: /model load
      if (subcommand === "load") {
        const modelLifecycleDeps: ModelLifecycleDeps = {
          spawnModel: () => ({ pid: 0 }), // Will be set by the real spawn
          killPid: () => {}, // unused in load
          waitReady: async (port?: number) => {
            await waitForServerReady(port ?? LLAMA_SERVER_DEFAULT_PORT);
          },
          writeKillReceipt: async () => {}, // unused in load
          isExternal: () => process.env["EMBER_MODEL_URL"] !== undefined,
          now: () => new Date().toISOString(),
          manifestPath,
        };

        try {
          // cond3 inc2a: validate checkpoint identity BEFORE spawning the
          // model process. A failed/withheld identity throws -- caught below
          // and returned as a fail-closed error with a non-zero exit; the
          // load never proceeds on an unverified checkpoint.
          const identity = await doResolveModelIdentity(manifestPath);
          if (identity === null) {
            throw new Error("checkpoint identity validation failed");
          }

          const status = await doLoadModel(modelLifecycleDeps);
          return {
            type: "message" as const,
            message: status,
          };
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          return {
            type: "message" as const,
            message: `error: failed to load: ${msg}`,
            exitCode: 1,
          };
        }
      }

      // Unknown subcommand → clear usage line
      return {
        type: "message" as const,
        message: `usage: /model status|load|unload`,
      };
    },
  };
}
