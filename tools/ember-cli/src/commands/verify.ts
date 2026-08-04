// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/verify.ts — /verify: dispatch the EMBER-01 completion verification pipeline
// from ember-cli (issue #1344 slice 1; #1371 pins every repository-scoped leg to a
// dedicated managed worktree so verification never freezes repository-wide development).
//
// Operator mandate (2026-08-03): "no process regarding anything ember should even be
// able to bypass ember-cli" and "embercli needs to be able to stay up during
// verification ... or it's useless" -- so /verify never blocks the UI: the pipeline
// (create managed worktree -> gh issue list -> issue_census.py ->
// verify_ember01_completion.py -> retire managed worktree) runs via async
// child_process.spawn (services/verify-watch.ts), started here and polled with
// `/verify status`, mirroring /watch's telemetry-watch.ts singleton.
//
// #1371 operator ruling (2026-08-03, binding, P0): "/verify must never freeze
// repository-wide development. The only write-protected surface is the dedicated
// verification worktree." Every repository-scoped leg targets that dedicated worktree,
// never the live checkout `ctx.cwd`/`repoRoot` resolves to -- so a concurrent
// commit/branch/PR/build in any other worktree, including this cockpit's own host
// checkout, is never read by and never has to wait on a running verification. See
// services/verify-watch.ts's module doc for the mechanism and specs/verify-completion-
// dispatch.md for the full contract.
//
// NO SILENT DEGRADATION (non-negotiable, operator ruling): the verifier honestly reports
// an UNRESOLVED leg when an operator-machine identity/checkpoint/config path is absent
// (DESIGN RULE in verify_ember01_completion.py -- "honesty over green"), but a cli run
// that quietly produces a weaker vector than a manual script run would be a regression
// dressed as a feature. So both `/verify` (start) and `/verify status` ALWAYS print the
// 4 env-var bindings as set/unset plus the exact legs an unset one costs, directly above
// any vector -- see EnvBindingReport in verify-watch.ts.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";
import { resolveEmberSourceRootOrCwd } from "../utils/repo-root.ts";
import { emberStatePath } from "../utils/ember-state-root.ts";
import { readRootBindingsStore, type CustodyBindingsDeps } from "../services/custody-bindings.ts";
import {
  startVerifyRun,
  getVerifyState,
  type EnvBindingReport,
  type EnvBindingStatus,
  type VerifyJobState,
  type VerifyProcessRunner,
} from "../services/verify-watch.ts";

// ---------------------------------------------------------------------------
// Env-binding report (the loud set/unset block)
// ---------------------------------------------------------------------------

function _envStatus(name: string, env: NodeJS.ProcessEnv): EnvBindingStatus {
  const value = env[name];
  return value !== undefined && value.trim().length > 0
    ? { envVar: name, set: true, value: value.trim() }
    : { envVar: name, set: false };
}

/** Builds the EnvBindingReport plus the human-readable UNRESOLVED-leg consequence lines.
 *  Exported for direct unit testing of the mapping without going through execute(). */
export function buildEnvBindingReport(env: NodeJS.ProcessEnv): EnvBindingReport {
  const selection = _envStatus("EMBER_VERIFY_SELECTION", env);
  const identityManifest = _envStatus("EMBER_VERIFY_IDENTITY_MANIFEST", env);
  const checkpointManifest = _envStatus("EMBER_VERIFY_CHECKPOINT_MANIFEST", env);
  const modelConfig = _envStatus("EMBER_VERIFY_MODEL_CONFIG", env);

  const unresolvedLegLines: string[] = [];
  const missingIdentityVars = [
    !identityManifest.set ? "EMBER_VERIFY_IDENTITY_MANIFEST" : null,
    !checkpointManifest.set ? "EMBER_VERIFY_CHECKPOINT_MANIFEST" : null,
    !modelConfig.set ? "EMBER_VERIFY_MODEL_CONFIG" : null,
  ].filter((v): v is string => v !== null);
  if (missingIdentityVars.length > 0) {
    unresolvedLegLines.push(
      `  - legs 3 (identity round-trip on real checkpoint) and 4 (identity fail-closed ` +
        `on tampered checkpoint) will be UNRESOLVED: ${missingIdentityVars.join(", ")} unset`,
    );
  }

  return { selection, identityManifest, checkpointManifest, modelConfig, unresolvedLegLines };
}

/** Renders the env-binding block shown at start AND in every /verify status response --
 *  the two paths must never diverge in what they report. */
export function renderEnvBindingBlock(report: EnvBindingReport): string {
  const line = (label: string, status: EnvBindingStatus) =>
    status.set ? `  ${label}: SET (${status.value})` : `  ${label}: UNSET`;
  const lines = [
    "env bindings:",
    line("EMBER_VERIFY_SELECTION", report.selection),
    line("EMBER_VERIFY_IDENTITY_MANIFEST", report.identityManifest),
    line("EMBER_VERIFY_CHECKPOINT_MANIFEST", report.checkpointManifest),
    line("EMBER_VERIFY_MODEL_CONFIG", report.modelConfig),
  ];
  if (report.unresolvedLegLines.length > 0) {
    lines.push("unresolved-leg consequences of the above:");
    lines.push(...report.unresolvedLegLines);
  } else {
    lines.push("unresolved-leg consequences of the above: none -- all identity paths bound");
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Status rendering
// ---------------------------------------------------------------------------

export function renderVerifyStatus(state: VerifyJobState | null): string {
  if (state === null) {
    return "verify: no verification job has been run this session. Run /verify to start one.";
  }
  const lines = [
    `verify: job ${state.jobId} -- status=${state.status} phase=${state.phase}`,
    `started: ${state.startedAt}${state.finishedAt ? `  finished: ${state.finishedAt}` : ""}`,
  ];
  // #1371: disclose the pinned worktree up front -- this IS the "development never
  // waits" guarantee made legible, not an implementation detail worth hiding.
  if (state.pinnedCommit) {
    lines.push(`pinned commit: ${state.pinnedCommit}`);
  }
  if (state.worktreePath) {
    lines.push(`verification worktree (isolated from the live checkout): ${state.worktreePath}`);
  }
  lines.push("", renderEnvBindingBlock(state.envBindings));
  if (state.error) {
    lines.push("", `error: ${state.error}`);
  }
  // #1371 cures a/b: a run killed by the cap says so, names the cap it hit, and lists the
  // descendant PIDs it reaped -- the 2026-08-04 run reported none of the three, so an
  // orphaned census kept writing for 84 minutes with nothing on screen to show for it.
  if (state.failureKind) {
    lines.push(`failure kind: ${state.failureKind}`);
  }
  if (state.failureKind === "timeout" && state.timeoutMs) {
    lines.push(
      `timeout: ${Math.round(state.timeoutMs / 60_000)} min (set EMBER_VERIFY_TIMEOUT_MINUTES to raise it)`,
    );
  }
  if (state.reapedPids && state.reapedPids.length > 0) {
    lines.push(`reaped process tree on timeout: ${state.reapedPids.join(", ")}`);
  }
  if (state.legTimingsMs && Object.keys(state.legTimingsMs).length > 0) {
    const timings = Object.entries(state.legTimingsMs)
      .map(([leg, ms]) => `${leg}=${(ms / 1000).toFixed(1)}s`)
      .join("  ");
    lines.push(`leg timings: ${timings}`);
  }
  if (state.status === "running") {
    lines.push("", "recent output:", state.stdoutTail || "(no output yet)");
  }
  if (state.receiptSummary) {
    lines.push("", `receipt ok: ${state.receiptSummary.ok}`, "legs:");
    for (const [num, leg] of Object.entries(state.receiptSummary.legs).sort(
      (a, b) => Number(a[0]) - Number(b[0]),
    )) {
      lines.push(`  ${num}. ${leg.title}: ${leg.status}`);
    }
  }
  if (state.receiptPath) lines.push("", `run receipt (always written on every terminal state): ${state.receiptPath}`);
  if (state.verifierReceiptPath) {
    lines.push(`verifier receipt (present only once the verifier itself ran): ${state.verifierReceiptPath}`);
  }
  if (state.runReceiptWriteError) {
    lines.push(`WARNING: the run receipt could not be written: ${state.runReceiptWriteError}`);
  }
  if (state.preservedCustodyOutputPath) {
    lines.push(`preserved custody-census output: ${state.preservedCustodyOutputPath}`);
  }
  if (state.worktreeRetireError) {
    lines.push(
      "",
      `note: the managed verification worktree could not be retired automatically: ${state.worktreeRetireError}`,
      `  run \`python scripts/worktree_lifecycle.py --repo <repo> retire --path ${state.worktreePath ?? "<path above>"}\` ` +
        `to clean it up, or leave it -- it expires on its own lease within a day.`,
    );
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Deps (injectable for testing)
// ---------------------------------------------------------------------------

interface VerifyCommandDeps {
  repoRoot?: string;
  env?: NodeJS.ProcessEnv;
  pythonBin?: string;
  ghBin?: string;
  gitBin?: string;
  worktreeRoot?: string;
  bindingsFs?: CustodyBindingsDeps;
  /** Injected subprocess runner passed through to services/verify-watch.ts; tests inject
   *  a mock so no real gh/python/git subprocess ever runs. */
  runProcess?: VerifyProcessRunner;
  /** Injectable job-id generator for deterministic tests. */
  mintJobId?: () => string;
  /** Injectable startVerifyRun / getVerifyState for tests that want to observe the call
   *  without exercising the real singleton. Defaults to the real module functions. */
  startVerifyRunFn?: typeof startVerifyRun;
  getVerifyStateFn?: typeof getVerifyState;
}

function _mintJobId(): string {
  return `verify-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createVerifyCommand(deps: VerifyCommandDeps = {}): RegistryCommand {
  const env = deps.env ?? process.env;
  const pythonBin = deps.pythonBin ?? env["EMBER_PYTHON_BIN"] ?? "python";
  const ghBin = deps.ghBin ?? env["EMBER_GH_BIN"] ?? "gh";
  const gitBin = deps.gitBin ?? env["EMBER_GIT_BIN"] ?? "git";
  const worktreeRoot = deps.worktreeRoot ?? env["EMBER_VERIFY_WORKTREE_ROOT"];
  const mintJobId = deps.mintJobId ?? _mintJobId;
  const doStartVerifyRun = deps.startVerifyRunFn ?? startVerifyRun;
  const doGetVerifyState = deps.getVerifyStateFn ?? getVerifyState;

  return {
    name: "verify",
    description:
      "Dispatch the EMBER-01 completion verification pipeline against a dedicated pinned worktree (gh issue census + custody census + verifier), staying live while it runs and never holding writes in any other worktree: /verify (start) | /verify status",
    isEnabled(): boolean {
      return true;
    },
    async execute(args: string, ctx: CommandContext) {
      const trimmed = args.trim();

      if (trimmed === "status") {
        return {
          type: "message" as const,
          message: renderVerifyStatus(doGetVerifyState()),
        };
      }

      if (trimmed !== "" && trimmed !== "start") {
        return {
          type: "message" as const,
          message: "usage: /verify (start) | /verify status",
          exitCode: 1,
        };
      }

      const existing = doGetVerifyState();
      if (existing !== null && existing.status === "running") {
        return {
          type: "message" as const,
          message: `verify: job ${existing.jobId} is already running (phase ${existing.phase}) -- use /verify status. A second run is never started over a live one. (This never blocks unrelated work in other worktrees -- only a second /verify dispatch is deduplicated.)`,
          exitCode: 1,
        };
      }

      const repoRoot = deps.repoRoot ?? resolveEmberSourceRootOrCwd({ startDir: ctx.cwd }, "[ember] /verify");
      const envBindings = buildEnvBindingReport(env);

      // EMBER_VERIFY_SELECTION is mandatory: the verifier's --selection has no fallback
      // (argparse required=True), so an unset selection refuses OUTRIGHT here -- never a
      // job that starts and then dies deep in the pipeline for a cause the operator
      // could have been told about immediately.
      if (!envBindings.selection.set) {
        return {
          type: "message" as const,
          message: [
            "error: EMBER_VERIFY_SELECTION is unset -- verification cannot start (mandatory, no fallback; the verifier's --selection is a required argument).",
            "",
            renderEnvBindingBlock(envBindings),
          ].join("\n"),
          exitCode: 1,
        };
      }

      let bindings: string[];
      try {
        const bindingsFs = deps.bindingsFs ?? {};
        const store = readRootBindingsStore(repoRoot, bindingsFs);
        bindings = Object.values(store.roots).map((b) => `${b.root_id}=${b.machine_path}`);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          type: "message" as const,
          message: `error: could not read the /custody root-bindings store: ${msg}`,
          exitCode: 1,
        };
      }

      const jobId = mintJobId();
      const jobDir = emberStatePath(repoRoot, "verify-receipts", jobId);

      const state = doStartVerifyRun({
        repoRoot,
        jobDir,
        jobId,
        envBindings,
        bindings,
        pythonBin,
        ghBin,
        gitBin,
        // Forwarded so EMBER_VERIFY_TIMEOUT_MINUTES is resolved from the SAME env this
        // command reads its other bindings from, never a second source of truth.
        env,
        ...(worktreeRoot ? { worktreeRoot } : {}),
        ...(deps.runProcess ? { runProcess: deps.runProcess } : {}),
      });

      return {
        type: "message" as const,
        message: [
          `verify: job ${state.jobId} started (phase ${state.phase}) -- ember-cli stays live; run /verify status for progress.`,
          "this run is pinned to a dedicated managed worktree (created next) and never holds writes in this or any other worktree.",
          bindings.length === 0
            ? "note: no custody root bindings are set -- run /custody set <root_id>=<path> to bind them before this run, or legs 1/2/6/9 will resolve UNRESOLVED for lack of ROOT bindings."
            : `custody root bindings: ${bindings.length} bound (from /custody set store)`,
          "",
          renderEnvBindingBlock(envBindings),
        ].join("\n"),
      };
    },
  };
}
