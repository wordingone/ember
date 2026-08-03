// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/verify-watch.ts — non-blocking job-state singleton for /verify.
//
// Mirrors telemetry-watch.ts's shape: a background job mutates module-level state via
// async subprocess spawns (never spawnSync -- this is the whole reason the cockpit stays
// up while a multi-minute verification runs), and getVerifyState() returns a read-only
// snapshot for /verify status (and, later, a live panel widget) to poll. Only one job runs
// at a time; starting a new one replaces the singleton state.

import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";

export type VerifyPhase =
  | "idle"
  | "fetching-issues"
  | "issue-census"
  | "verifying"
  | "done"
  | "failed";

/** One of the four operator-machine paths /verify forwards to the verifier, always
 *  reported explicitly rather than silently omitted -- see EnvBindingReport. */
export interface EnvBindingStatus {
  envVar: string;
  set: boolean;
  value?: string;
}

/** The loud set/unset -> unresolved-legs mapping shown at start and in every /verify
 *  status response, so a weaker vector is never presented without its cause attached. */
export interface EnvBindingReport {
  selection: EnvBindingStatus;
  identityManifest: EnvBindingStatus;
  checkpointManifest: EnvBindingStatus;
  modelConfig: EnvBindingStatus;
  /** Human-readable lines naming exactly which verifier legs will be UNRESOLVED because of
   *  an unset var, empty when all identity-path vars are set. selection has no fallback in
   *  the verifier (--selection is required) so an unset selection is refused before any
   *  job starts, never listed here as a "leg" consequence. */
  unresolvedLegLines: string[];
}

export interface VerifyProcessResult {
  status: number | null;
  stdout: string;
  stderr: string;
}

/** Injectable async subprocess runner. Real implementation uses child_process.spawn
 *  (never spawnSync) so the event loop -- and therefore the whole cockpit UI -- keeps
 *  ticking while a leg (gh API call, multi-minute custody census, verifier run) is in
 *  flight. Tests inject a mock so no real gh/python subprocess ever runs. */
export type VerifyProcessRunner = (
  executable: string,
  args: string[],
  cwd: string,
) => Promise<VerifyProcessResult>;

export const DEFAULT_VERIFY_TIMEOUT_MS = 20 * 60_000;

export function _defaultRunVerifyProcess(
  executable: string,
  args: string[],
  cwd: string,
  timeoutMs: number = DEFAULT_VERIFY_TIMEOUT_MS,
): Promise<VerifyProcessResult> {
  return new Promise((resolve) => {
    let settled = false;
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];

    let proc;
    try {
      proc = spawn(executable, args, { cwd, windowsHide: true });
    } catch {
      resolve({ status: null, stdout: "", stderr: "spawn threw synchronously" });
      return;
    }

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      proc.kill();
      resolve({
        status: null,
        stdout: Buffer.concat(stdoutChunks).toString("utf8"),
        stderr: Buffer.concat(stderrChunks).toString("utf8") + "\n[verify: timed out]",
      });
    }, timeoutMs);

    proc.stdout?.on("data", (chunk: Buffer) => stdoutChunks.push(chunk));
    proc.stderr?.on("data", (chunk: Buffer) => stderrChunks.push(chunk));

    proc.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({
        status: code,
        stdout: Buffer.concat(stdoutChunks).toString("utf8"),
        stderr: Buffer.concat(stderrChunks).toString("utf8"),
      });
    });

    proc.on("error", (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ status: null, stdout: "", stderr: String(err) });
    });
  });
}

// ---------------------------------------------------------------------------
// Job state
// ---------------------------------------------------------------------------

export interface VerifyJobState {
  jobId: string;
  status: "running" | "done" | "failed";
  phase: VerifyPhase;
  startedAt: string;
  finishedAt?: string;
  envBindings: EnvBindingReport;
  /** Last ~4KB of the currently-running (or most recently run) leg's stdout, coarse
   *  progress for slice 1 -- see the #1344 delivery note on a future --progress-jsonl
   *  leg-by-leg stream from the python side. */
  stdoutTail: string;
  receiptPath?: string;
  preservedCustodyOutputPath?: string;
  /** Parsed `ok` + per-leg vector from the receipt JSON once the verifier exits 0 or 1
   *  (both produce a receipt; only a crash before the receipt is written leaves this
   *  unset). */
  receiptSummary?: { ok: boolean; legs: Record<string, { status: string; title: string }> };
  error?: string;
}

let _state: VerifyJobState | null = null;

export function getVerifyState(): VerifyJobState | null {
  return _state === null ? null : { ..._state };
}

/** Test/internal seam: replace the singleton directly without running a job. */
export function _setVerifyStateForTest(state: VerifyJobState | null): void {
  _state = state;
}

function tail(text: string, maxBytes = 4096): string {
  if (Buffer.byteLength(text, "utf8") <= maxBytes) return text;
  return text.slice(-maxBytes);
}

// ---------------------------------------------------------------------------
// Pipeline
// ---------------------------------------------------------------------------

export interface VerifyPipelineDeps {
  repoRoot: string;
  jobDir: string;
  jobId: string;
  envBindings: EnvBindingReport;
  bindings: string[];
  pythonBin: string;
  ghBin: string;
  runProcess?: VerifyProcessRunner;
  mkdirSyncFn?: typeof mkdirSync;
}

/**
 * Starts the three-leg verification pipeline (gh issue list -> issue_census.py ->
 * verify_ember01_completion.py) as async subprocesses and returns IMMEDIATELY after
 * seeding the singleton state -- the caller (commands/verify.ts) never awaits this
 * function's returned promise before responding to the operator. Errors inside the
 * pipeline land in `_state.status = "failed"` / `_state.error`, never an unhandled
 * rejection.
 */
export function startVerifyRun(deps: VerifyPipelineDeps): VerifyJobState {
  const runProcess = deps.runProcess ?? _defaultRunVerifyProcess;
  const mkdir = deps.mkdirSyncFn ?? mkdirSync;

  mkdir(deps.jobDir, { recursive: true });

  const issuesJsonPath = `${deps.jobDir}/issues.json`;
  const issueCensusPath = `${deps.jobDir}/issue-census.json`;
  const receiptPath = `${deps.jobDir}/receipt.json`;
  const preservedCustodyOutputPath = `${deps.jobDir}/custody-census-output.json`;

  const initial: VerifyJobState = {
    jobId: deps.jobId,
    status: "running",
    phase: "fetching-issues",
    startedAt: new Date().toISOString(),
    envBindings: deps.envBindings,
    stdoutTail: "",
    receiptPath,
    preservedCustodyOutputPath,
  };
  _state = initial;

  void runPipeline();

  return { ..._state };

  async function runPipeline(): Promise<void> {
    try {
      const ghResult = await runProcess(
        deps.ghBin,
        [
          "issue", "list", "--repo", "wordingone/ember", "--state", "open", "--limit", "1000",
          "--json", "number,title,body,url,createdAt,updatedAt,labels,author,state,stateReason,closedAt,comments",
        ],
        deps.repoRoot,
      );
      if (_state?.jobId !== deps.jobId) return; // superseded by a newer run
      if (ghResult.status !== 0) {
        _fail(deps.jobId, "fetching-issues", `gh issue list exited ${ghResult.status ?? "null"}: ${tail(ghResult.stderr)}`);
        return;
      }
      mkdir(deps.jobDir, { recursive: true });
      await import("node:fs/promises").then((fs) => fs.writeFile(issuesJsonPath, ghResult.stdout, "utf8"));

      _update(deps.jobId, { phase: "issue-census", stdoutTail: tail(ghResult.stdout) });

      const censusResult = await runProcess(
        deps.pythonBin,
        [
          "-B", "scripts/ember_01_custody/issue_census.py",
          "--repo-root", deps.repoRoot,
          "--public-ref", "refs/remotes/origin/master",
          "--issues-json", issuesJsonPath,
          "--output", issueCensusPath,
        ],
        deps.repoRoot,
      );
      if (_state?.jobId !== deps.jobId) return;
      if (censusResult.status !== 0) {
        _fail(deps.jobId, "issue-census", `issue_census.py exited ${censusResult.status ?? "null"}: ${tail(censusResult.stderr)}`);
        return;
      }

      _update(deps.jobId, { phase: "verifying", stdoutTail: tail(censusResult.stdout) });

      const verifierArgs = [
        "-B", "scripts/verify_ember01_completion.py",
        "--root", deps.repoRoot,
        "--selection", deps.envBindings.selection.value as string, // refused upstream if unset
        "--receipt", receiptPath,
        "--run-custody",
        "--issue-census", issueCensusPath,
        "--preserve-custody-output", preservedCustodyOutputPath,
        "--run-seat",
        ...deps.bindings.flatMap((b) => ["--binding", b]),
      ];
      if (deps.envBindings.identityManifest.set) {
        verifierArgs.push("--identity-manifest", deps.envBindings.identityManifest.value as string);
      }
      if (deps.envBindings.checkpointManifest.set) {
        verifierArgs.push("--checkpoint-manifest", deps.envBindings.checkpointManifest.value as string);
      }
      if (deps.envBindings.modelConfig.set) {
        verifierArgs.push("--model-config", deps.envBindings.modelConfig.value as string);
      }

      const verifyResult = await runProcess(deps.pythonBin, verifierArgs, deps.repoRoot);
      if (_state?.jobId !== deps.jobId) return;

      let receiptSummary: VerifyJobState["receiptSummary"];
      try {
        const fsp = await import("node:fs/promises");
        const raw = await fsp.readFile(receiptPath, "utf8");
        const parsed = JSON.parse(raw) as { ok?: unknown; legs?: unknown };
        if (typeof parsed.ok === "boolean" && parsed.legs && typeof parsed.legs === "object") {
          const legs: Record<string, { status: string; title: string }> = {};
          for (const [key, value] of Object.entries(parsed.legs as Record<string, unknown>)) {
            const v = value as Record<string, unknown>;
            legs[key] = {
              status: typeof v["status"] === "string" ? v["status"] : "unknown",
              title: typeof v["title"] === "string" ? v["title"] : key,
            };
          }
          receiptSummary = { ok: parsed.ok, legs };
        }
      } catch {
        // No parseable receipt (verifier crashed before writing one) -- status/error
        // below still surfaces the exit code and stderr tail; never a crash here.
      }

      if (verifyResult.status !== 0 && verifyResult.status !== 1) {
        // 0/1 are the verifier's own "ran to completion" exits (ok / not-ok); anything
        // else (crash, missing script, bad args) is an infra failure of the run itself.
        _fail(
          deps.jobId,
          "verifying",
          `verifier exited ${verifyResult.status ?? "null"} (not a completed run): ${tail(verifyResult.stderr)}`,
        );
        return;
      }

      _update(deps.jobId, {
        status: "done",
        phase: "done",
        finishedAt: new Date().toISOString(),
        stdoutTail: tail(verifyResult.stdout),
        ...(receiptSummary ? { receiptSummary } : {}),
      });
    } catch (err) {
      if (_state?.jobId !== deps.jobId) return;
      _fail(deps.jobId, _state?.phase ?? "verifying", err instanceof Error ? err.message : String(err));
    }
  }
}

function _update(jobId: string, patch: Partial<VerifyJobState>): void {
  if (_state === null || _state.jobId !== jobId) return;
  _state = { ..._state, ...patch };
}

function _fail(jobId: string, phase: VerifyPhase, message: string): void {
  if (_state === null || _state.jobId !== jobId) return;
  _state = {
    ..._state,
    status: "failed",
    phase,
    finishedAt: new Date().toISOString(),
    error: message,
  };
}
