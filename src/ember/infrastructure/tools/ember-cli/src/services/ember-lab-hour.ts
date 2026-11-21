// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ember-lab-hour.ts — typed client for the resident ember-lab hour job class (`start_hour`, `job_events`) and the
// existing job RPCs (`job_state`, `stop_job`, `job_exit_code`) Studio and ember-cli drive an hour through.
//
// `start_hour` is the same contract as `/resume-hour` (commands/resume-hour.ts): dispatch name, exact sha256, a log
// that must not exist, a pinned Git bash, the process environment minus every EMBER_* key. Both implementations
// satisfy the shared golden fixture commands/resume-hour-contract.json; the difference is that the lab keeps the
// hour as a job: the hour survives this client, Studio and a daemon crash, and a restarted daemon re-adopts it.

import { resolve } from "node:path";
import { hourEnv } from "../commands/resume-hour.ts";
import { callEmberLab, EmberLabRpcError } from "./ember-lab-rpc.ts";

/** The job kinds the lab runs through this verb. Default `hour`. */
export type HourJobKind = "hour" | "learn" | "dream";

export interface StartHourOptions {
  pipeName: string;
  /** Default `hour`. A learn job's script is `learn_<name>.sh`, a dream's `dream_<name>.sh`; the lab refuses any other kind (`hour_kind_unknown`). */
  kind?: HourJobKind;
  /** Absolute, or relative to `baseDir` (default: this process's cwd). */
  script: string;
  sha256: string;
  log: string;
  /** Default: `baseDir` (this process's cwd), exactly what `/resume-hour` inherits. Never the lab daemon's cwd (#2460 F8). */
  cwd?: string;
  bash?: string;
  baseDir?: string;
  /** Default: this process's environment minus every EMBER_* key, exactly what `/resume-hour` sends. */
  env?: Record<string, string | undefined>;
  timeoutMs?: number;
}

export interface HourStarted {
  ok: true;
  /** `hour`, `learn` or `dream`, as the lab ran it. An older lab that does not say is read as `hour`. */
  kind: string;
  jobId: string;
  pid: number;
  script: string;
  sha256: string;
  log: string;
  receiptPath: string;
  bash: string;
  cwd: string | null;
  /**
   * False when the hour is RUNNING but its `phase: started` receipt could not be completed (the intent receipt stays on disk).
   * The start succeeded: `jobId`/`pid` are the handle, so do not retry; `receiptError` says what failed.
   */
  receiptComplete: boolean;
  receiptError?: string;
  /**
   * Set when the lab's start returned an error AFTER the child was running (lead review 82583 S1). The hour is live and the lab kept
   * its `hour-chain` lease: do not retry; `jobId`/`pid` are the handle and this text says what failed.
   */
  startTailError?: string;
}

export interface HourRefused {
  ok: false;
  /** Distinct per check, e.g. hour_sha_mismatch. */
  refusalCode: string;
  /** The exit code `ember-lab start-hour` returns for this refusal. */
  rc: number;
  detail: string;
}

export type StartHourResult = HourStarted | HourRefused;

/** What `check_hour` answers when a start would be accepted right now: the same checks as `start_hour`, nothing created. */
export interface HourChecked {
  ok: true;
  kind: string;
  /** The job id the start would use (the next free attempt). */
  jobId: string;
  script: string;
  sha256: string;
  log: string;
  receiptPath: string;
  bash: string;
  cwd: string | null;
}

export type CheckHourResult = HourChecked | HourRefused;

/** A job's exit, with "still running" and "exit unknown" told apart (#2460 F14). */
export type HourJobExit =
  | { status: "running" }
  | { status: "exited"; exitCode: number }
  /** The job is over (or was lost) and the lab holds no exit code for it: the process was ended by stop_job, or its exit was never observed. */
  | { status: "unknown"; state: string };

export interface HourJobEvent {
  seq: number;
  ts_ms: number;
  kind: string;
  payload: unknown;
}

function malformed(what: string): Error {
  return new Error("ember-lab hour RPC rejected: " + what);
}

function record(value: unknown, what: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw malformed(what);
  return value as Record<string, unknown>;
}

function str(value: unknown, what: string): string {
  if (typeof value !== "string") throw malformed(what);
  return value;
}

function hourParams(options: StartHourOptions): Record<string, unknown> {
  const base = options.baseDir ?? process.cwd();
  return {
    kind: options.kind ?? "hour",
    script: resolve(base, options.script),
    sha256: options.sha256,
    log: resolve(base, options.log),
    // F8: the lab would otherwise run the hour in ITS OWN working directory, which /resume-hour never does.
    cwd: resolve(base, options.cwd ?? "."),
    bash: options.bash === undefined ? null : resolve(base, options.bash),
    env: hourEnv(options.env ?? process.env),
  };
}

function refusalOf(error: unknown): HourRefused | null {
  if (error instanceof EmberLabRpcError) {
    const data = error.rpcError["data"];
    if (data && typeof data === "object" && !Array.isArray(data) && "refusal_code" in data) {
      const refusal = data as Record<string, unknown>;
      return {
        ok: false,
        refusalCode: str(refusal["refusal_code"], "refusal_code"),
        rc: Number(refusal["rc"]),
        detail: typeof refusal["detail"] === "string" ? refusal["detail"] : "",
      };
    }
  }
  return null;
}

/**
 * Ask the lab whether a start would be accepted right now (`check_hour`): the same checks as `start_hour`, nothing created. Resolves with the
 * refusal (never throws) for a contract refusal; throws on transport faults.
 */
export async function checkHour(options: StartHourOptions): Promise<CheckHourResult> {
  let result: Record<string, unknown>;
  try {
    result = await callEmberLab({ pipeName: options.pipeName, timeoutMs: options.timeoutMs, method: "check_hour", params: hourParams(options) });
  } catch (error) {
    const refusal = refusalOf(error);
    if (refusal) return refusal;
    throw error;
  }
  const cwd = result["cwd"];
  return {
    ok: true,
    kind: typeof result["kind"] === "string" ? result["kind"] : "hour",
    jobId: str(result["job_id"], "job_id"),
    script: str(result["script"], "script"),
    sha256: str(result["sha256"], "sha256"),
    log: str(result["log"], "log"),
    receiptPath: str(result["receipt_path"], "receipt_path"),
    bash: str(result["bash"], "bash"),
    cwd: typeof cwd === "string" ? cwd : null,
  };
}

/** Start an hour as a lab job. Resolves with the refusal (never throws) for a contract refusal; throws on transport faults. */
export async function startHour(options: StartHourOptions): Promise<StartHourResult> {
  let result: Record<string, unknown>;
  try {
    result = await callEmberLab({ pipeName: options.pipeName, timeoutMs: options.timeoutMs, method: "start_hour", params: hourParams(options) });
  } catch (error) {
    const refusal = refusalOf(error);
    if (refusal) return refusal;
    throw error;
  }
  const pid = result["pid"];
  if (!Number.isSafeInteger(pid) || (pid as number) <= 0) throw malformed("start_hour result pid is malformed");
  const cwd = result["cwd"];
  return {
    ok: true,
    kind: typeof result["kind"] === "string" ? result["kind"] : "hour",
    jobId: str(result["job_id"], "job_id"),
    pid: pid as number,
    script: str(result["script"], "script"),
    sha256: str(result["sha256"], "sha256"),
    log: str(result["log"], "log"),
    receiptPath: str(result["receipt_path"], "receipt_path"),
    bash: str(result["bash"], "bash"),
    cwd: typeof cwd === "string" ? cwd : null,
    receiptComplete: result["receipt_complete"] !== false,
    ...(typeof result["receipt_error"] === "string" ? { receiptError: result["receipt_error"] } : {}),
    ...(typeof result["start_tail_error"] === "string" ? { startTailError: result["start_tail_error"] } : {}),
  };
}

/** Events of one job with `seq > afterSeq`, oldest first (limit at most 1000). */
export async function jobEvents(
  pipeName: string,
  jobId: string,
  afterSeq = 0,
  limit = 200,
  timeoutMs?: number,
): Promise<HourJobEvent[]> {
  const result = await callEmberLab({
    pipeName,
    timeoutMs,
    method: "job_events",
    params: { job_id: jobId, after_seq: afterSeq, limit },
  });
  const events = result["events"];
  if (!Array.isArray(events)) throw malformed("job_events result is malformed");
  return events.map((entry) => {
    const event = record(entry, "job event");
    if (!Number.isSafeInteger(event["seq"]) || !Number.isSafeInteger(event["ts_ms"])) throw malformed("job event numbers");
    return {
      seq: event["seq"] as number,
      ts_ms: event["ts_ms"] as number,
      kind: str(event["kind"], "job event kind"),
      payload: event["payload"],
    };
  });
}

/** The job's lifecycle state (`running`, `exited`, `stopped`, `failed`, ...). Throws for an unknown job. */
export async function hourJobState(pipeName: string, jobId: string, timeoutMs?: number): Promise<string> {
  const result = await callEmberLab({ pipeName, timeoutMs, method: "job_state", params: { job_id: jobId } });
  return str(result["state"], "job_state result");
}

/**
 * The job's exit with "still running" and "exit unknown" told apart (#2460 F14): `running` while the lab says so, `exited` with the code,
 * `unknown` for a job that is over without a code (stopped by `stop_job`, or lost). Prefer this to `hourJobExitCode`.
 */
export async function hourJobExit(pipeName: string, jobId: string, timeoutMs?: number): Promise<HourJobExit> {
  const state = await hourJobState(pipeName, jobId, timeoutMs);
  if (state === "running" || state === "starting" || state === "prepared" || state === "stopping") return { status: "running" };
  const code = await hourJobExitCode(pipeName, jobId, timeoutMs);
  return code === null ? { status: "unknown", state } : { status: "exited", exitCode: code };
}

/** The exit code of a terminal job, or null while it has none (null is ALSO "exit unknown": use `hourJobExit` to tell them apart). */
export async function hourJobExitCode(pipeName: string, jobId: string, timeoutMs?: number): Promise<number | null> {
  const result = await callEmberLab({ pipeName, timeoutMs, method: "job_exit_code", params: { job_id: jobId } });
  const code = result["exit_code"];
  if (code === null || code === undefined) return null;
  if (!Number.isSafeInteger(code)) throw malformed("job_exit_code result is malformed");
  return code as number;
}

/** Stop the hour and its whole process tree. */
export async function stopHourJob(pipeName: string, jobId: string, timeoutMs?: number): Promise<void> {
  const result = await callEmberLab({ pipeName, timeoutMs, method: "stop_job", params: { job_id: jobId } });
  if (result["stopped"] !== true) throw malformed("stop_job result is malformed");
}
