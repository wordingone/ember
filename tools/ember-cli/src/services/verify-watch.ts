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
//
// #1371 (operator P0, 2026-08-03): "/verify must never freeze repository-wide
// development." Before this node every repository-scoped leg ran with `--root
// <repoRoot>` -- the SAME live checkout every other worktree, commit, and build touches.
// A concurrent commit landing mid-census could flip the checkout dirty, retarget HEAD, or
// change file bytes mid-hash, so operators learned to hold writes until a run finished.
// That informal hold is the freeze this issue kills. The fix: every repository-scoped leg
// now runs against a DEDICATED, MANAGED worktree pinned to the exact commit at dispatch
// (`scripts/worktree_lifecycle.py create`), created before the pipeline's first leg and
// retired after the last one, success or failure. Development in every OTHER worktree
// (including the live repoRoot checkout the cockpit itself runs from) is never touched by
// this pipeline and never needs to wait for it.
//
// Residual scope (disclosed, not fixed here -- see notes/1371-slice2-fingerprint-cache.md
// in this issue's staging note): the custody census's OPERATOR-MACHINE roots (bound via
// `/custody set`, e.g. `registered-worktree-registry` / `registered-worktree-material-
// registry`) still read live machine paths outside the pinned worktree, because those
// roots are deliberately NOT repo-scoped -- they attest custody of machine state the
// pinned worktree cannot represent. Snapshot-or-fail already applies at the file level
// inside census.py (final byte/membership re-verification, #1365's exclusion mechanism);
// scoping those specific roots so ordinary concurrent development in unrelated worktrees
// can never read as a contradiction is tracked as slice 2b, named explicitly in the PR
// body rather than silently left for a future reader to rediscover.

import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import os from "node:os";
import path from "node:path";

export type VerifyPhase =
  | "idle"
  | "preparing-worktree"
  | "fetching-issues"
  | "issue-census"
  | "verifying"
  | "retiring-worktree"
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
  /** True only when the leg was killed by the pipeline's own timeout, never when the
   *  child merely exited non-zero. Terminal handling branches on this to record
   *  failure_kind "timeout" in the run receipt (see VerifyRunReceipt). */
  timedOut?: boolean;
  /** PIDs actually terminated by the timeout tree-reap, root process first. Recorded in
   *  the run receipt so an operator can tell a clean reap from a partial one. */
  reapedPids?: number[];
}

/** Injectable async subprocess runner. Real implementation uses child_process.spawn
 *  (never spawnSync) so the event loop -- and therefore the whole cockpit UI -- keeps
 *  ticking while a leg (gh API call, multi-minute custody census, verifier run) is in
 *  flight. Tests inject a mock so no real gh/python/git subprocess ever runs. */
export type VerifyProcessRunner = (
  executable: string,
  args: string[],
  cwd: string,
  timeoutMs?: number,
) => Promise<VerifyProcessResult>;

/** MEASURED, not guessed: run verify-msdz1l2eum570b (2026-08-04) was killed by the
 *  previous 20-minute cap while still mid-census, and the custody census leg ALONE
 *  measured ~95 minutes end to end on the operator machine. 180 minutes is that measured
 *  worst leg with roughly 2x headroom, so the cap catches a genuinely wedged pipeline
 *  instead of amputating a healthy slow one. Override per-machine with
 *  EMBER_VERIFY_TIMEOUT_MINUTES when a run is legitimately longer; values below the
 *  measured census duration are accepted (an operator may want a short leash) but the
 *  DEFAULT never drops under it again. */
export const DEFAULT_VERIFY_TIMEOUT_MINUTES = 180;
export const DEFAULT_VERIFY_TIMEOUT_MS = DEFAULT_VERIFY_TIMEOUT_MINUTES * 60_000;

/** Resolves the per-leg pipeline timeout from EMBER_VERIFY_TIMEOUT_MINUTES, falling back
 *  to the measured default above. A non-numeric or non-positive value falls back rather
 *  than throwing -- a malformed env var must never be the reason a verification refuses
 *  to start, and it must never silently become "no timeout" either. */
export function resolveVerifyTimeoutMs(env: NodeJS.ProcessEnv = process.env): number {
  const raw = env["EMBER_VERIFY_TIMEOUT_MINUTES"];
  if (raw === undefined || raw.trim() === "") return DEFAULT_VERIFY_TIMEOUT_MS;
  const minutes = Number(raw.trim());
  if (!Number.isFinite(minutes) || minutes <= 0) return DEFAULT_VERIFY_TIMEOUT_MS;
  return Math.round(minutes * 60_000);
}

/** The tree-kill argv for one platform. `proc.kill()` signals only the DIRECT child: on
 *  run verify-msdz1l2eum570b the direct child died on timeout while its census.py
 *  GRANDCHILD survived as an orphan for 84 more minutes, writing a 1.4GB temp file no
 *  one ever consumed. Windows has no process groups to signal, so the whole descendant
 *  tree is reaped explicitly via `taskkill /T /F`; POSIX kills the spawned process's
 *  children by parent pid via `pkill -KILL -P`. */
export function _buildTreeKillCommand(
  pid: number,
  platform: NodeJS.Platform = process.platform,
): { executable: string; args: string[] } {
  if (platform === "win32") {
    return { executable: "taskkill", args: ["/PID", String(pid), "/T", "/F"] };
  }
  return { executable: "pkill", args: ["-KILL", "-P", String(pid)] };
}

/** Extracts every PID `taskkill /T /F` reports terminating (it prints one line per
 *  process in the tree, including "child of PID <root>" lines). The root pid is always
 *  included even when the output is unparseable or empty, so the receipt never claims a
 *  reap of zero processes after a kill actually ran. */
export function _parseReapedPids(killStdout: string, rootPid: number): number[] {
  const pids = new Set<number>([rootPid]);
  for (const match of killStdout.matchAll(/PID[:\s]+(\d+)/gi)) {
    const value = Number(match[1]);
    if (Number.isFinite(value) && value > 0) pids.add(value);
  }
  return [...pids];
}

/** Best-effort descendant reap. Never rejects: a failed reap degrades to "we killed what
 *  we could and say so", it never turns into a second failure on top of the timeout. */
function reapProcessTree(pid: number): Promise<number[]> {
  return new Promise((resolve) => {
    const { executable, args } = _buildTreeKillCommand(pid);
    const chunks: Buffer[] = [];
    let killer;
    try {
      killer = spawn(executable, args, { windowsHide: true });
    } catch {
      resolve([pid]);
      return;
    }
    killer.stdout?.on("data", (chunk: Buffer) => chunks.push(chunk));
    killer.on("error", () => resolve([pid]));
    killer.on("close", () => resolve(_parseReapedPids(Buffer.concat(chunks).toString("utf8"), pid)));
  });
}

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
      const rootPid = proc.pid;
      const reap = rootPid === undefined ? Promise.resolve<number[]>([]) : reapProcessTree(rootPid);
      void reap.then((reapedPids) => {
        resolve({
          status: null,
          timedOut: true,
          reapedPids,
          stdout: Buffer.concat(stdoutChunks).toString("utf8"),
          stderr:
            Buffer.concat(stderrChunks).toString("utf8") +
            `\n[verify: timed out after ${Math.round(timeoutMs / 60_000)} min; reaped process tree: ${reapedPids.join(", ") || "none"}]`,
        });
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
  /** The RUN receipt this service always writes on every terminal state (#1371 cure c),
   *  distinct from verifierReceiptPath below, which only exists when the verifier itself
   *  ran far enough to emit one. */
  receiptPath?: string;
  /** Where the verifier's own leg-vector receipt lands (`--receipt`). Absent from disk
   *  whenever the verifier never ran or crashed before writing it -- which is exactly the
   *  hole the run receipt fills. */
  verifierReceiptPath?: string;
  preservedCustodyOutputPath?: string;
  /** Parsed `ok` + per-leg vector from the receipt JSON once the verifier exits 0 or 1
   *  (both produce a receipt; only a crash before the receipt is written leaves this
   *  unset). */
  receiptSummary?: { ok: boolean; legs: Record<string, { status: string; title: string }> };
  error?: string;
  /** #1371: the dedicated managed worktree every repository-scoped leg runs against, and
   *  the exact commit it is pinned to -- disclosed so an operator can see this run never
   *  touched the live checkout. Unset only if worktree creation itself never started
   *  (should not happen once phase has advanced past "preparing-worktree"). */
  worktreePath?: string;
  pinnedCommit?: string;
  /** Set only if worktree retirement failed after the pipeline finished -- best-effort
   *  cleanup, never escalated into a run failure (the run's verdict is about the pinned
   *  commit, not about whether its scratch worktree was tidied away afterward). A leaked
   *  worktree here is a known, named residue for `worktree_lifecycle.py audit` to catch,
   *  not a silent leak. */
  worktreeRetireError?: string;
  /** #1371 cure c: the machine-readable cause of a terminal state, mirrored into the run
   *  receipt. Null/undefined on a clean green run. */
  failureKind?: VerifyFailureKind;
  /** #1371 cure b: PIDs reaped by the timeout tree-kill, empty unless a leg timed out. */
  reapedPids?: number[];
  /** Per-leg wall time, keyed by leg name -- the evidence that says WHICH leg ate the
   *  timeout, which the 2026-08-04 run could not answer because nothing was written. */
  legTimingsMs?: Record<string, number>;
  /** The resolved per-leg timeout this run used (#1371 cure a), disclosed so a run killed
   *  by the cap can be told apart from one killed by something else. */
  timeoutMs?: number;
  /** Set only if writing the run receipt itself failed. The job still goes terminal --
   *  but it says so rather than presenting a terminal state whose receipt silently is not
   *  on disk, which is the exact failure #1371 cure c exists to end. */
  runReceiptWriteError?: string;
}

/** Machine-readable terminal causes. "verifier-not-ok" is a COMPLETED run whose verdict
 *  was red -- the pipeline succeeded, the repository did not verify -- and is the one
 *  value that pairs with status "done". */
export type VerifyFailureKind =
  | "pin-head"
  | "worktree-create"
  | "gh"
  | "issue-census"
  | "verifier-infra"
  | "verifier-not-ok"
  | "timeout"
  | "crash";

/** The receipt written to `<jobDir>/receipt.json` on EVERY terminal state (#1371 cure c).
 *  Run verify-msdz1l2eum570b died on the 20-minute cap and left NOTHING on disk: the job
 *  existed only in this module's in-memory singleton, so once the cockpit was restarted
 *  there was no way to say what had run, how far it got, or what was killed. A terminal
 *  state without a receipt is now impossible by construction. */
export interface VerifyRunReceipt {
  schema: "ember-cli/verify-run-receipt@1";
  job_id: string;
  ok: boolean;
  status: "done" | "failed";
  failure_kind: VerifyFailureKind | null;
  phase: VerifyPhase;
  pinned_commit: string | null;
  worktree_path: string | null;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  leg_timings_ms: Record<string, number>;
  reaped_pids: number[];
  timeout_ms: number;
  verifier_receipt_path: string | null;
  legs: Record<string, { status: string; title: string }> | null;
  error: string | null;
  worktree_retire_error: string | null;
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
// Managed worktree helpers (#1371)
// ---------------------------------------------------------------------------

const WORKTREE_LIFECYCLE_SCRIPT = "scripts/worktree_lifecycle.py";

function defaultWorktreeRoot(): string {
  return path.join(os.homedir(), "ember-verify-worktrees");
}

/** One day's headroom past dispatch: this run always retires its own worktree on every
 *  exit path (success, failure, or crash inside runPipeline's try/finally), so the lease
 *  is not meant to be consumed by expiry -- it exists only so a run that crashes the WHOLE
 *  node process (not just the pipeline) leaves a worktree `worktree_lifecycle.py audit`
 *  flags as expired within a day, never a silent permanent leak. */
function shortLeaseExpiry(now: Date = new Date()): string {
  const expiry = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  return expiry.toISOString().slice(0, 10);
}

interface WorktreeCreateResult {
  status: "CREATED";
  path: string;
  branch: string;
}

function parseWorktreeCreateResult(stdout: string): WorktreeCreateResult | null {
  try {
    const parsed = JSON.parse(stdout) as Record<string, unknown>;
    if (
      parsed["status"] === "CREATED" &&
      typeof parsed["path"] === "string" &&
      typeof parsed["branch"] === "string"
    ) {
      return { status: "CREATED", path: parsed["path"], branch: parsed["branch"] };
    }
  } catch {
    // fall through to null -- caller treats an unparseable result as a create failure
  }
  return null;
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
  /** git executable used only to resolve the exact commit to pin the managed worktree to
   *  (`git rev-parse HEAD`, read-only, run against repoRoot). Defaults to "git". */
  gitBin?: string;
  /** Directory managed verify worktrees are created under, one subdirectory per job id.
   *  Defaults to `<homedir>/ember-verify-worktrees`. Never under `.claude/` (repo-guard
   *  #1009) and never inside repoRoot itself. */
  worktreeRoot?: string;
  /** Environment the per-leg timeout is resolved from (EMBER_VERIFY_TIMEOUT_MINUTES).
   *  Defaults to process.env. */
  env?: NodeJS.ProcessEnv;
  /** Explicit per-leg timeout, overriding the env-resolved one. Tests use it to keep
   *  runs instant; production leaves it unset. */
  timeoutMs?: number;
  runProcess?: VerifyProcessRunner;
  mkdirSyncFn?: typeof mkdirSync;
}

/**
 * Starts the pinned-worktree verification pipeline (create managed worktree -> gh issue
 * list -> issue_census.py -> verify_ember01_completion.py -> retire managed worktree) as
 * async subprocesses and returns IMMEDIATELY after seeding the singleton state -- the
 * caller (commands/verify.ts) never awaits this function's returned promise before
 * responding to the operator. Errors inside the pipeline land in `_state.status =
 * "failed"` / `_state.error`, never an unhandled rejection. Every repository-scoped leg
 * (issue census's --repo-root and the verifier's --root) targets the managed worktree,
 * never `deps.repoRoot` -- so nothing this pipeline does can observe, or be disrupted by,
 * a concurrent commit/branch/PR/build in any other worktree, including the live checkout
 * the cockpit itself runs from.
 */
export function startVerifyRun(deps: VerifyPipelineDeps): VerifyJobState {
  const runProcess = deps.runProcess ?? _defaultRunVerifyProcess;
  const mkdir = deps.mkdirSyncFn ?? mkdirSync;
  const gitBin = deps.gitBin ?? "git";
  const timeoutMs = deps.timeoutMs ?? resolveVerifyTimeoutMs(deps.env ?? process.env);
  const worktreeRoot = deps.worktreeRoot ?? defaultWorktreeRoot();
  const worktreePath = path.join(worktreeRoot, deps.jobId);
  const worktreeBranch = `verify/${deps.jobId}`;

  mkdir(deps.jobDir, { recursive: true });

  const issuesJsonPath = `${deps.jobDir}/issues.json`;
  const issueCensusPath = `${deps.jobDir}/issue-census.json`;
  // #1371 cure c: `receipt.json` is the RUN receipt this service owns and always writes.
  // The verifier's own leg-vector receipt gets its own filename so the two never race for
  // one path -- before this split, a timeout left `receipt.json` simply absent.
  const runReceiptPath = `${deps.jobDir}/receipt.json`;
  const verifierReceiptPath = `${deps.jobDir}/verifier-receipt.json`;
  const preservedCustodyOutputPath = `${deps.jobDir}/custody-census-output.json`;

  const startedAt = new Date().toISOString();
  const legTimingsMs: Record<string, number> = {};
  let reapedPids: number[] = [];
  let pinnedCommit: string | null = null;

  const initial: VerifyJobState = {
    jobId: deps.jobId,
    status: "running",
    phase: "preparing-worktree",
    startedAt,
    envBindings: deps.envBindings,
    stdoutTail: "",
    receiptPath: runReceiptPath,
    verifierReceiptPath,
    preservedCustodyOutputPath,
    timeoutMs,
    legTimingsMs: {},
    reapedPids: [],
  };
  _state = initial;

  void runPipeline();

  return { ..._state };

  /** Runs one leg under the resolved timeout, recording its wall time and any PIDs the
   *  timeout tree-reap killed. Every subprocess in the pipeline goes through here so no
   *  leg can be silently un-timed or un-timed-out. */
  async function runLeg(
    leg: string,
    executable: string,
    args: string[],
    cwd: string,
  ): Promise<VerifyProcessResult> {
    const startedMs = Date.now();
    const result = await runProcess(executable, args, cwd, timeoutMs);
    legTimingsMs[leg] = Date.now() - startedMs;
    if (result.reapedPids && result.reapedPids.length > 0) {
      reapedPids = [...reapedPids, ...result.reapedPids];
    }
    _update(deps.jobId, { legTimingsMs: { ...legTimingsMs }, reapedPids: [...reapedPids] });
    return result;
  }

  /** Writes the run receipt. Returns an error message instead of throwing: a receipt-write
   *  failure is disclosed on the job, never swallowed and never escalated into a second
   *  failure that hides the first. */
  async function writeRunReceipt(fields: {
    ok: boolean;
    status: "done" | "failed";
    failureKind: VerifyFailureKind | null;
    phase: VerifyPhase;
    finishedAt: string;
    error: string | null;
    legs: Record<string, { status: string; title: string }> | null;
    verifierReceiptWritten: boolean;
  }): Promise<string | undefined> {
    const receipt: VerifyRunReceipt = {
      schema: "ember-cli/verify-run-receipt@1",
      job_id: deps.jobId,
      ok: fields.ok,
      status: fields.status,
      failure_kind: fields.failureKind,
      phase: fields.phase,
      pinned_commit: pinnedCommit,
      worktree_path: _state?.jobId === deps.jobId ? (_state.worktreePath ?? null) : null,
      started_at: startedAt,
      finished_at: fields.finishedAt,
      duration_ms: new Date(fields.finishedAt).getTime() - new Date(startedAt).getTime(),
      leg_timings_ms: { ...legTimingsMs },
      reaped_pids: [...reapedPids],
      timeout_ms: timeoutMs,
      verifier_receipt_path: fields.verifierReceiptWritten ? verifierReceiptPath : null,
      legs: fields.legs,
      error: fields.error,
      worktree_retire_error:
        _state?.jobId === deps.jobId ? (_state.worktreeRetireError ?? null) : null,
    };
    try {
      const fsp = await import("node:fs/promises");
      mkdir(deps.jobDir, { recursive: true });
      await fsp.writeFile(runReceiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
      return undefined;
    } catch (err) {
      return err instanceof Error ? err.message : String(err);
    }
  }

  /** The ONLY way this pipeline reaches a terminal state: receipt on disk first, job
   *  marked terminal second. */
  async function finish(fields: {
    ok: boolean;
    status: "done" | "failed";
    failureKind: VerifyFailureKind | null;
    phase: VerifyPhase;
    error: string | null;
    legs: Record<string, { status: string; title: string }> | null;
    verifierReceiptWritten: boolean;
    stdoutTail?: string;
    receiptSummary?: VerifyJobState["receiptSummary"];
  }): Promise<void> {
    const finishedAt = new Date().toISOString();
    const writeError = await writeRunReceipt({ ...fields, finishedAt });
    if (_state === null || _state.jobId !== deps.jobId) return;
    _state = {
      ..._state,
      status: fields.status,
      phase: fields.phase,
      finishedAt,
      failureKind: fields.failureKind ?? undefined,
      legTimingsMs: { ...legTimingsMs },
      reapedPids: [...reapedPids],
      ...(fields.error !== null ? { error: fields.error } : {}),
      ...(fields.stdoutTail !== undefined ? { stdoutTail: fields.stdoutTail } : {}),
      ...(fields.receiptSummary ? { receiptSummary: fields.receiptSummary } : {}),
      ...(writeError ? { runReceiptWriteError: writeError } : {}),
    };
  }

  /** A leg that hit the pipeline timeout: the tree is already reaped by the runner, so
   *  this only has to retire the worktree and go terminal WITH a receipt naming the leg,
   *  its timings, and the PIDs killed. */
  async function finishTimedOut(phase: VerifyPhase, leg: string, result: VerifyProcessResult): Promise<void> {
    await retireWorktreeBestEffort();
    await finish({
      ok: false,
      status: "failed",
      failureKind: "timeout",
      phase,
      error:
        `${leg} exceeded the ${Math.round(timeoutMs / 60_000)}-minute verify timeout ` +
        `(EMBER_VERIFY_TIMEOUT_MINUTES); reaped process tree: ${(result.reapedPids ?? []).join(", ") || "none"}`,
      legs: null,
      verifierReceiptWritten: false,
    });
  }

  async function retireWorktreeBestEffort(): Promise<void> {
    if (_state?.jobId !== deps.jobId || _state.worktreePath === undefined) return;
    // Retire the ACTUAL path the lifecycle script reported back from `create` (the
    // canonicalized path it registered), never the locally-requested `worktreePath` --
    // `canonical_path()` on the python side may normalize it differently than this
    // process's own `path.join`, and retiring the wrong string would leave the real
    // managed row stranded while reporting a false success.
    const actualPath = _state.worktreePath;
    _update(deps.jobId, { phase: "retiring-worktree" });
    try {
      const result = await runProcess(
        deps.pythonBin,
        [
          "-B", WORKTREE_LIFECYCLE_SCRIPT,
          "--repo", deps.repoRoot,
          "retire",
          "--path", actualPath,
        ],
        deps.repoRoot,
        timeoutMs,
      );
      if (_state?.jobId !== deps.jobId) return;
      if (result.status !== 0) {
        _update(deps.jobId, {
          worktreeRetireError: `worktree_lifecycle.py retire exited ${result.status ?? "null"}: ${tail(result.stderr)}`,
        });
      }
    } catch (err) {
      if (_state?.jobId !== deps.jobId) return;
      _update(deps.jobId, {
        worktreeRetireError: err instanceof Error ? err.message : String(err),
      });
    }
  }

  async function runPipeline(): Promise<void> {
    let worktreeCreated = false;
    try {
      // --- Phase 0 (#1371): pin the exact commit, then create the dedicated managed
      // worktree every later leg runs against. Read-only against repoRoot (git
      // rev-parse); the ONLY write this pipeline ever makes to repoRoot's own git state
      // is the `worktree add` call itself, which registers a new worktree row -- it never
      // touches repoRoot's working tree, index, or HEAD.
      const headResult = await runLeg("rev-parse", gitBin, ["rev-parse", "HEAD"], deps.repoRoot);
      if (_state?.jobId !== deps.jobId) return;
      const head = headResult.stdout.trim();
      if (headResult.status !== 0 || !/^[0-9a-f]{40}$/i.test(head)) {
        await finish({
          ok: false,
          status: "failed",
          failureKind: headResult.timedOut ? "timeout" : "pin-head",
          phase: "preparing-worktree",
          error: `git rev-parse HEAD failed: ${tail(headResult.stderr || headResult.stdout)}`,
          legs: null,
          verifierReceiptWritten: false,
        });
        return;
      }
      pinnedCommit = head;

      const createResult = await runLeg(
        "worktree-create",
        deps.pythonBin,
        [
          "-B", WORKTREE_LIFECYCLE_SCRIPT,
          "--repo", deps.repoRoot,
          "create",
          "--path", worktreePath,
          "--branch", worktreeBranch,
          "--owner", "ember-cli-verify",
          "--purpose", `verify dispatch ${deps.jobId}`,
          "--expires", shortLeaseExpiry(),
          "--start-point", pinnedCommit,
        ],
        deps.repoRoot,
      );
      if (_state?.jobId !== deps.jobId) return;
      const created = createResult.status === 0 ? parseWorktreeCreateResult(createResult.stdout) : null;
      if (created === null) {
        await finish({
          ok: false,
          status: "failed",
          failureKind: createResult.timedOut ? "timeout" : "worktree-create",
          phase: "preparing-worktree",
          error: `worktree_lifecycle.py create exited ${createResult.status ?? "null"}: ${tail(createResult.stderr || createResult.stdout)}`,
          legs: null,
          verifierReceiptWritten: false,
        });
        return;
      }
      worktreeCreated = true;
      _update(deps.jobId, {
        phase: "fetching-issues",
        worktreePath: created.path,
        pinnedCommit,
      });

      const ghResult = await runLeg(
        "gh-issue-list",
        deps.ghBin,
        [
          "issue", "list", "--repo", "wordingone/ember", "--state", "open", "--limit", "1000",
          "--json", "number,title,body,url,createdAt,updatedAt,labels,author,state,stateReason,closedAt,comments",
        ],
        deps.repoRoot,
      );
      if (_state?.jobId !== deps.jobId) return;
      if (ghResult.timedOut) {
        await finishTimedOut("fetching-issues", "gh issue list", ghResult);
        return;
      }
      if (ghResult.status !== 0) {
        await retireWorktreeBestEffort();
        if (_state?.jobId !== deps.jobId) return;
        await finish({
          ok: false,
          status: "failed",
          failureKind: "gh",
          phase: "fetching-issues",
          error: `gh issue list exited ${ghResult.status ?? "null"}: ${tail(ghResult.stderr)}`,
          legs: null,
          verifierReceiptWritten: false,
        });
        return;
      }
      mkdir(deps.jobDir, { recursive: true });
      await import("node:fs/promises").then((fs) => fs.writeFile(issuesJsonPath, ghResult.stdout, "utf8"));

      _update(deps.jobId, { phase: "issue-census", stdoutTail: tail(ghResult.stdout) });

      const censusResult = await runLeg(
        "issue-census",
        deps.pythonBin,
        [
          "-B", "scripts/ember_01_custody/issue_census.py",
          // #1371: repository-scoped, so this reads the PINNED worktree, never repoRoot.
          "--repo-root", created.path,
          "--public-ref", "refs/remotes/origin/master",
          "--issues-json", issuesJsonPath,
          "--output", issueCensusPath,
        ],
        deps.repoRoot,
      );
      if (_state?.jobId !== deps.jobId) return;
      if (censusResult.timedOut) {
        await finishTimedOut("issue-census", "issue_census.py", censusResult);
        return;
      }
      if (censusResult.status !== 0) {
        await retireWorktreeBestEffort();
        if (_state?.jobId !== deps.jobId) return;
        await finish({
          ok: false,
          status: "failed",
          failureKind: "issue-census",
          phase: "issue-census",
          error: `issue_census.py exited ${censusResult.status ?? "null"}: ${tail(censusResult.stderr)}`,
          legs: null,
          verifierReceiptWritten: false,
        });
        return;
      }

      _update(deps.jobId, { phase: "verifying", stdoutTail: tail(censusResult.stdout) });

      const verifierArgs = [
        "-B", "scripts/verify_ember01_completion.py",
        // #1371: the whole point -- every repository-scoped leg (checkout integrity,
        // launch-packet, authority, identity, custody-census's own repo-relative reads)
        // now runs against the pinned worktree, never the live repoRoot checkout.
        "--root", created.path,
        "--selection", deps.envBindings.selection.value as string, // refused upstream if unset
        "--receipt", verifierReceiptPath,
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

      const verifyResult = await runLeg("verifier", deps.pythonBin, verifierArgs, deps.repoRoot);
      if (_state?.jobId !== deps.jobId) return;
      if (verifyResult.timedOut) {
        await finishTimedOut("verifying", "verify_ember01_completion.py", verifyResult);
        return;
      }

      let receiptSummary: VerifyJobState["receiptSummary"];
      try {
        const fsp = await import("node:fs/promises");
        const raw = await fsp.readFile(verifierReceiptPath, "utf8");
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
        await retireWorktreeBestEffort();
        await finish({
          ok: false,
          status: "failed",
          failureKind: "verifier-infra",
          phase: "verifying",
          error: `verifier exited ${verifyResult.status ?? "null"} (not a completed run): ${tail(verifyResult.stderr)}`,
          legs: receiptSummary?.legs ?? null,
          verifierReceiptWritten: receiptSummary !== undefined,
          ...(receiptSummary ? { receiptSummary } : {}),
        });
        return;
      }

      await retireWorktreeBestEffort();
      if (_state?.jobId !== deps.jobId) return;
      // A completed-but-red run is still status "done" (the PIPELINE succeeded); the
      // receipt carries ok:false + failure_kind "verifier-not-ok" so a consumer reading
      // only the receipt cannot mistake red for green.
      const ok = receiptSummary ? receiptSummary.ok : verifyResult.status === 0;
      await finish({
        ok,
        status: "done",
        failureKind: ok ? null : "verifier-not-ok",
        phase: "done",
        error: null,
        legs: receiptSummary?.legs ?? null,
        verifierReceiptWritten: receiptSummary !== undefined,
        stdoutTail: tail(verifyResult.stdout),
        ...(receiptSummary ? { receiptSummary } : {}),
      });
    } catch (err) {
      if (worktreeCreated) {
        await retireWorktreeBestEffort();
      }
      if (_state?.jobId !== deps.jobId) return;
      await finish({
        ok: false,
        status: "failed",
        failureKind: "crash",
        phase: _state?.phase ?? "verifying",
        error: err instanceof Error ? err.message : String(err),
        legs: null,
        verifierReceiptWritten: false,
      });
    }
  }
}

function _update(jobId: string, patch: Partial<VerifyJobState>): void {
  if (_state === null || _state.jobId !== jobId) return;
  _state = { ..._state, ...patch };
}

// (A module-level `_fail` used to exist here. It is gone on purpose: it set a terminal
// state WITHOUT writing anything to disk, which is precisely how run
// verify-msdz1l2eum570b ended with no receipt. Terminal state is reachable only through
// the pipeline-scoped `finish()`, which writes the run receipt first -- #1371 cure c.)
