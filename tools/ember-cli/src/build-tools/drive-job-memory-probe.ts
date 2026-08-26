// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Production-path driver for one already-authorized issue #898 job-memory probe leg.
// This file has no workflow trigger and mints no authority. A later reviewed carrier
// pins exactly two immutable packet digests and invokes it once per signed leg.

import { createHash } from "node:crypto";
import {
  spawn as spawnProcess,
  type ChildProcessWithoutNullStreams,
} from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import xtermHeadless from "@xterm/headless";
import { spawn as spawnPty, type IPty } from "node-pty";
import { headlessCaptureEnv } from "../services/headless-capture.ts";
import {
  observeTrainSample,
  parseDaemonJobMemoryEnforcementWitness,
  parsePreflightJobMembershipSamples,
  type DaemonJobMemoryEnforcementEvidence,
  type GovernedStart,
  type PreflightJobMembershipEvidence,
} from "./job-memory-probe-driver-state.ts";
import { readPacketBinding } from "./job-memory-probe-packet.ts";

const { Terminal } = xtermHeadless as unknown as {
  Terminal: new (options: unknown) => any;
};
const COLS = 120;
const ROWS = 40;
const PREFLIGHT_PROBE_INTERVAL_MS = 100;

type JsonObject = Record<string, unknown>;

interface RunningPreflightProbe {
  child: ChildProcessWithoutNullStreams;
  exit: Promise<void>;
  stderr: string[];
  stdout: string[];
}

interface PtyInputSocket {
  destroyed?: boolean;
  writable?: boolean;
  off(event: "error", listener: (error: Error) => void): PtyInputSocket;
  once(event: "error", listener: (error: Error) => void): PtyInputSocket;
  write(data: string, callback: (error?: Error | null) => void): boolean;
}

interface DrainedPreflightProbe {
  stderr: string;
  stdout: string;
  stopError?: Error;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface TimedPreflightJobMembershipEvidence
  extends PreflightJobMembershipEvidence {
  offerObservedAtMs: number;
  requestedSamplingIntervalMs: number;
  trainCommandTypingStartedAtMs: number;
  windowDurationMs: number;
}

function object(value: unknown, label: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} is not an object`);
  }
  return value as JsonObject;
}

function sha256(path: string): string {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function writeExclusive(path: string, data: string): void {
  writeFileSync(path, data, { encoding: "utf8", flag: "wx" });
}

function frameText(terminal: any): string {
  const buffer = terminal.buffer.active;
  const lines: string[] = [];
  for (let y = 0; y < terminal.rows; y += 1) {
    const line = buffer.getLine(buffer.viewportY + y);
    lines.push(line ? line.translateToString(true) : "");
  }
  return `${lines.join("\n")}\n`;
}

async function settle(writes: () => Promise<void>, milliseconds: number): Promise<void> {
  await new Promise((done) => setTimeout(done, milliseconds));
  await writes();
}

// PRECONDITION: observed cockpit output has proved the node-pty agent is ready.
export async function writePtyData(child: IPty, data: string): Promise<void> {
  const socket = (child as unknown as { _agent?: { inSocket?: PtyInputSocket } })._agent
    ?.inSocket;
  if (!socket) {
    throw new Error("ConPTY input write failed: input socket is unavailable");
  }
  if (socket.destroyed === true || socket.writable === false) {
    throw new Error("ConPTY input write failed: Socket is closed");
  }
  await new Promise<void>((resolveWrite, rejectWrite) => {
    let settled = false;
    const finish = (error?: Error | null): void => {
      if (settled) return;
      settled = true;
      socket.off("error", onError);
      if (error) {
        rejectWrite(new Error(`ConPTY input write failed: ${errorMessage(error)}`));
      } else {
        resolveWrite();
      }
    };
    const onError = (error: Error): void => finish(error);
    socket.once("error", onError);
    try {
      socket.write(data, finish);
    } catch (error) {
      finish(error instanceof Error ? error : new Error(String(error)));
    }
  });
}

async function typeCommand(child: IPty, command: string): Promise<void> {
  for (const character of command) {
    await writePtyData(child, character);
    await new Promise((done) => setTimeout(done, 20));
  }
  await writePtyData(child, "\r");
}

async function waitFor<T>(
  inspect: () => T | undefined,
  writes: () => Promise<void>,
  deadlineMs: number | undefined,
  label: string,
): Promise<T> {
  let nextHeartbeat = Date.now() + 30_000;
  for (;;) {
    await settle(writes, 200);
    const value = inspect();
    if (value !== undefined) return value;
    if (deadlineMs !== undefined && Date.now() >= deadlineMs) {
      throw new Error(`timed out before ${label}`);
    }
    if (Date.now() >= nextHeartbeat) {
      console.log(`[probe-driver] waiting for ${label}`);
      nextHeartbeat = Date.now() + 30_000;
    }
  }
}

function startPreflightJobMembershipProbe(cockpitPid: number): RunningPreflightProbe {
  if (process.platform !== "win32") {
    throw new Error("preflight job-membership probe requires Windows");
  }
  if (!Number.isSafeInteger(cockpitPid) || cockpitPid <= 0) {
    throw new Error("cockpit PID is invalid for preflight job-membership probe");
  }
  const script = String.raw`
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class EmberIssue898JobProbe {
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool IsProcessInJob(IntPtr process, IntPtr job, out bool result);
  [DllImport("kernel32.dll")]
  public static extern bool CloseHandle(IntPtr handle);
}
'@
$rootPid = ${cockpitPid}
$sampleIndex = 0
while ($true) {
  $sampleIndex += 1
  $observedAtMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop)
  $children = @{}
  foreach ($process in $processes) {
    $parent = [uint32]$process.ParentProcessId
    if (-not $children.ContainsKey($parent)) { $children[$parent] = @() }
    $children[$parent] += $process
  }
  $queue = [Collections.Generic.Queue[uint32]]::new()
  $queue.Enqueue([uint32]$rootPid)
  $descendants = @()
  while ($queue.Count -gt 0) {
    $parent = $queue.Dequeue()
    if (-not $children.ContainsKey($parent)) { continue }
    foreach ($process in $children[$parent]) {
      $descendants += $process
      $queue.Enqueue([uint32]$process.ProcessId)
    }
  }
  $membershipMatches = @()
  foreach ($process in $descendants) {
    $commandLine = [string]$process.CommandLine
    if ($commandLine -notmatch '(?i)(^|[\\/])launch_packet\.py"?(?:\s|$)') { continue }
    $handle = [EmberIssue898JobProbe]::OpenProcess(0x1000, $false, [uint32]$process.ProcessId)
    if ($handle -eq [IntPtr]::Zero) { continue }
    try {
      $inJob = $false
      if (-not [EmberIssue898JobProbe]::IsProcessInJob($handle, [IntPtr]::Zero, [ref]$inJob)) {
        continue
      }
      $sha = [Security.Cryptography.SHA256]::Create()
      try {
        $digest = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($commandLine))).Replace('-', '').ToLowerInvariant()
      } finally { $sha.Dispose() }
      $membershipMatches += [ordered]@{
        pid = [uint32]$process.ProcessId
        parent_pid = [uint32]$process.ParentProcessId
        command_line = $commandLine
        command_line_sha256 = $digest
        is_process_in_job = [bool]$inJob
      }
    } finally {
      [void][EmberIssue898JobProbe]::CloseHandle($handle)
    }
  }
  [ordered]@{
    schema_version = 'ember-issue898-preflight-job-membership-sample-v1'
    sample_index = $sampleIndex
    observed_at_ms = $observedAtMs
    descendant_count = $descendants.Count
    matches = @($membershipMatches)
  } | ConvertTo-Json -Compress -Depth 4
  Start-Sleep -Milliseconds ${PREFLIGHT_PROBE_INTERVAL_MS}
}
`;
  const encoded = Buffer.from(script, "utf16le").toString("base64");
  const child = spawnProcess(
    "powershell.exe",
    ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
    { windowsHide: true, stdio: ["pipe", "pipe", "pipe"] },
  );
  const stdout: string[] = [];
  const stderr: string[] = [];
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk: string) => stdout.push(chunk));
  child.stderr.on("data", (chunk: string) => stderr.push(chunk));
  const exit = new Promise<void>((resolveExit) => child.once("exit", () => resolveExit()));
  return { child, exit, stderr, stdout };
}

async function waitForPreflightProbeReady(probe: RunningPreflightProbe): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (!probe.stdout.join("").includes("\n")) {
    if (probe.child.exitCode !== null) {
      throw new Error(
        `preflight job-membership probe exited before its first census: ${probe.stderr.join("").trim()}`,
      );
    }
    if (Date.now() >= deadline) {
      throw new Error("preflight job-membership probe did not emit its first census");
    }
    await new Promise((done) => setTimeout(done, 50));
  }
}

export function persistPreflightProbeStreams(
  outputRoot: string,
  stdout: string,
  stderr: string,
): void {
  writeExclusive(join(outputRoot, "preflight-probe.stdout.jsonl"), stdout);
  writeExclusive(join(outputRoot, "preflight-probe.stderr.txt"), stderr);
}

export function persistCockpitEvidence(
  outputRoot: string,
  raw: string,
  frame: string,
): void {
  writeExclusive(join(outputRoot, "cockpit.raw.txt"), raw);
  writeExclusive(join(outputRoot, "cockpit.frame.txt"), frame);
}

async function drainPreflightProbe(
  probe: RunningPreflightProbe,
): Promise<DrainedPreflightProbe> {
  let stopError: Error | undefined;
  try {
    if (probe.child.exitCode === null) probe.child.kill();
    await Promise.race([
      probe.exit,
      new Promise<void>((_, reject) =>
        setTimeout(
          () => reject(new Error("preflight job-membership probe did not stop")),
          5_000,
        ),
      ),
    ]);
  } catch (error) {
    stopError = error instanceof Error ? error : new Error(String(error));
  }
  return {
    stderr: probe.stderr.join(""),
    stdout: probe.stdout.join(""),
    ...(stopError ? { stopError } : {}),
  };
}

function disclosePreflightFinalizationError(outputRoot: string, errors: unknown[]): void {
  const message = errors.map(errorMessage).join("; ");
  console.error(`[probe-driver] preflight probe finalization failed: ${message}`);
  try {
    writeExclusive(join(outputRoot, "preflight-probe-finalization-error.txt"), `${message}\n`);
  } catch (recordError) {
    console.error(
      `[probe-driver] could not persist preflight finalization error: ${errorMessage(recordError)}`,
    );
  }
}

function discloseCockpitEvidenceFinalizationError(outputRoot: string, error: unknown): void {
  const message = errorMessage(error);
  console.error(`[probe-driver] cockpit evidence finalization failed: ${message}`);
  try {
    writeExclusive(
      join(outputRoot, "cockpit-evidence-finalization-error.txt"),
      `${message}\n`,
    );
  } catch (recordError) {
    console.error(
      `[probe-driver] could not persist cockpit evidence finalization error: ${errorMessage(recordError)}`,
    );
  }
}

async function stopPreflightJobMembershipProbe(
  probe: RunningPreflightProbe,
  outputRoot: string,
): Promise<PreflightJobMembershipEvidence> {
  const drained = await drainPreflightProbe(probe);
  persistPreflightProbeStreams(outputRoot, drained.stdout, drained.stderr);
  if (drained.stopError) throw drained.stopError;
  if (drained.stderr.trim().length > 0) {
    throw new Error(
      `preflight job-membership probe stderr was not empty: ${drained.stderr.trim()}`,
    );
  }
  return parsePreflightJobMembershipSamples(drained.stdout);
}

interface RuntimeProbeProcessResult {
  exitCode: number | null;
  stderr: string;
  stdout: string;
}

interface SqliteDatabaseAdapter {
  close(): void;
  readExactJobObjectRow(jobId: string): unknown;
}

function sqliteAdapterError(
  runtime: string,
  specifier: string,
  operation: string,
  error: unknown,
): Error {
  return new Error(
    `sqlite adapter failed: runtime=${runtime} specifier=${specifier} operation=${operation}: ${errorMessage(error)}`,
  );
}

async function openSqliteDatabase(databasePath: string): Promise<{
  database: SqliteDatabaseAdapter;
  runtime: string;
  specifier: string;
}> {
  const isBun = typeof (process.versions as Record<string, string | undefined>).bun === "string";
  const runtime = isBun ? "bun" : "node";
  const specifier = isBun ? "bun:sqlite" : "node:sqlite";
  let module: Record<string, unknown>;
  try {
    module = await import(specifier) as Record<string, unknown>;
  } catch (error) {
    throw sqliteAdapterError(runtime, specifier, "import", error);
  }
  try {
    if (isBun) {
      const Database = module.Database as
        | (new (path: string, options: { readonly: boolean }) => {
            close(): void;
            query(sql: string): { get(jobId: string): unknown };
          })
        | undefined;
      if (typeof Database !== "function") throw new Error("Database export is unavailable");
      const database = new Database(databasePath, { readonly: true });
      return {
        database: {
          close: () => database.close(),
          readExactJobObjectRow: (jobId) =>
            database
              .query("SELECT job_id, pid, job_object_name FROM jobs WHERE job_id = ?1")
              .get(jobId),
        },
        runtime,
        specifier,
      };
    }
    const DatabaseSync = module.DatabaseSync as
      | (new (path: string, options: { readOnly: boolean }) => {
          close(): void;
          prepare(sql: string): { get(jobId: string): unknown };
        })
      | undefined;
    if (typeof DatabaseSync !== "function") throw new Error("DatabaseSync export is unavailable");
    const database = new DatabaseSync(databasePath, { readOnly: true });
    return {
      database: {
        close: () => database.close(),
        readExactJobObjectRow: (jobId) =>
          database
            .prepare("SELECT job_id, pid, job_object_name FROM jobs WHERE job_id = ?1")
            .get(jobId),
      },
      runtime,
      specifier,
    };
  } catch (error) {
    throw sqliteAdapterError(runtime, specifier, "open", error);
  }
}

async function readDaemonJobRow(databasePath: string, jobId: string): Promise<unknown> {
  const { database, runtime, specifier } = await openSqliteDatabase(databasePath);
  let row: unknown;
  try {
    try {
      row = database.readExactJobObjectRow(jobId);
    } catch (error) {
      throw sqliteAdapterError(runtime, specifier, "read exact job-object row", error);
    }
  } finally {
    try {
      database.close();
    } catch (error) {
      console.error(
        `[probe-driver] ${sqliteAdapterError(runtime, specifier, "close", error).message}`,
      );
    }
  }
  return row;
}

export async function readJobObjectName(databasePath: string, jobId: string): Promise<string> {
  const row = await readDaemonJobRow(databasePath, jobId);
  // bun:sqlite returns null for a miss; node:sqlite returns undefined, so typeof is load-bearing.
  const objectRow = row as { job_object_name?: unknown } | null;
  if (
    objectRow === null ||
    typeof objectRow !== "object" ||
    typeof objectRow.job_object_name !== "string" ||
    objectRow.job_object_name.length === 0
  ) {
    throw new Error("daemon database lacks the exact governed job-object name");
  }
  return objectRow.job_object_name;
}

export async function readGovernedStartFromArtifacts(
  preflightReceiptPath: string,
  databasePath: string,
  expectedRunId: string,
  expectedMaximumJobMemoryBytes: number,
  timeoutMs = 30_000,
): Promise<GovernedStart> {
  if (!Number.isSafeInteger(expectedMaximumJobMemoryBytes) || expectedMaximumJobMemoryBytes <= 0) {
    throw new Error("authenticated maximum job memory is invalid for authored start");
  }
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 0) {
    throw new Error("authored-start wait timeout is invalid");
  }
  const deadline = Date.now() + timeoutMs;
  let preflight: JsonObject | undefined;
  let jobId: string | undefined;
  let lastNotReady: "job-object-name" | "pid" | undefined;
  for (;;) {
    if (preflight === undefined && existsSync(preflightReceiptPath)) {
      try {
        preflight = object(
          JSON.parse(readFileSync(preflightReceiptPath, "utf8")),
          "daemon preflight receipt",
        );
      } catch (error) {
        throw new Error(`daemon preflight receipt is invalid: ${errorMessage(error)}`);
      }
      if (
        preflight["schema_version"] !== "ember-lab-dispatch-preflight-v1" ||
        preflight["result"] !== "PREFLIGHT_PASSED"
      ) {
        throw new Error("daemon preflight receipt is not PREFLIGHT_PASSED");
      }
      if (preflight["maximum_job_memory_bytes"] !== expectedMaximumJobMemoryBytes) {
        throw new Error("preflight receipt maximum does not match authenticated maximum");
      }
      const candidateJobId = preflight["job_id"];
      const prefix = `${expectedRunId}-launch-`;
      if (
        typeof candidateJobId !== "string" ||
        !candidateJobId.startsWith(prefix) ||
        !/^[1-9][0-9]*$/.test(candidateJobId.slice(prefix.length))
      ) {
        throw new Error("preflight receipt job id is not bound to packet run id");
      }
      jobId = candidateJobId;
    }
    if (jobId !== undefined && existsSync(databasePath)) {
      const row = await readDaemonJobRow(databasePath, jobId);
      if (row !== null && typeof row === "object") {
        const identity = row as {
          job_id?: unknown;
          job_object_name?: unknown;
          pid?: unknown;
        };
        if (identity.job_id !== jobId) {
          throw new Error("daemon database row identity mismatches preflight job id");
        }
        if (!Number.isSafeInteger(identity.pid)) {
          throw new Error("daemon database row governed pid is not an integer");
        }
        if (Number(identity.pid) <= 0) {
          lastNotReady = "pid";
        } else if (
          typeof identity.job_object_name !== "string" || identity.job_object_name.length === 0
        ) {
          lastNotReady = "job-object-name";
        } else {
          return { governedPid: Number(identity.pid), jobId };
        }
      }
    }
    if (Date.now() >= deadline) {
      if (preflight === undefined) {
        throw new Error("timed out before daemon preflight receipt appeared");
      }
      if (lastNotReady === "pid") {
        throw new Error(
          "daemon database lacks positive governed identity for preflight job id: row exists but pid is not positive",
        );
      }
      if (lastNotReady === "job-object-name") {
        throw new Error("daemon database row lacks exact governed job-object name at deadline");
      }
      throw new Error("daemon preflight receipt appeared but database has no row for its job id");
    }
    await new Promise((done) => setTimeout(done, 25));
  }
}

export async function queryRuntimeJobEnforcement(
  jobId: string,
  jobObjectName: string,
  governedPid: number,
  outsideControlPid: number,
): Promise<RuntimeProbeProcessResult> {
  const script = String.raw`
$ProgressPreference = 'SilentlyContinue'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class EmberIssue898RuntimeJobProbe {
  [StructLayout(LayoutKind.Sequential)]
  public struct IO_COUNTERS {
    public ulong ReadOperationCount; public ulong WriteOperationCount; public ulong OtherOperationCount;
    public ulong ReadTransferCount; public ulong WriteTransferCount; public ulong OtherTransferCount;
  }
  [StructLayout(LayoutKind.Sequential)]
  public struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
    public long PerProcessUserTimeLimit; public long PerJobUserTimeLimit; public uint LimitFlags;
    public UIntPtr MinimumWorkingSetSize; public UIntPtr MaximumWorkingSetSize;
    public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass; public uint SchedulingClass;
  }
  [StructLayout(LayoutKind.Sequential)]
  public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
    public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
    public IO_COUNTERS IoInfo;
    public UIntPtr ProcessMemoryLimit; public UIntPtr JobMemoryLimit;
    public UIntPtr PeakProcessMemoryUsed; public UIntPtr PeakJobMemoryUsed;
  }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern IntPtr OpenJobObject(uint access, bool inheritHandle, string name);
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern IntPtr OpenProcess(uint access, bool inheritHandle, uint processId);
  [DllImport("kernel32.dll", SetLastError=true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool IsProcessInJob(IntPtr processHandle, IntPtr jobHandle,
    [MarshalAs(UnmanagedType.Bool)] out bool result);
  [DllImport("kernel32.dll", SetLastError=true)]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool QueryInformationJobObject(IntPtr jobHandle, int infoClass,
    IntPtr info, uint infoLength, IntPtr returnLength);
  [DllImport("kernel32.dll")]
  [return: MarshalAs(UnmanagedType.Bool)]
  public static extern bool CloseHandle(IntPtr handle);
}
'@
$jobId = [Environment]::GetEnvironmentVariable('EMBER_PROBE_JOB_ID')
$jobObjectName = [Environment]::GetEnvironmentVariable('EMBER_PROBE_JOB_OBJECT_NAME')
$governedPid = [uint32][Environment]::GetEnvironmentVariable('EMBER_PROBE_GOVERNED_PID')
$outsidePid = [uint32][Environment]::GetEnvironmentVariable('EMBER_PROBE_OUTSIDE_PID')
$row = [ordered]@{
  schema_version = 'ember-issue898-runtime-job-enforcement-v1'
  job_id = $jobId
  job_object_name = $jobObjectName
  governed_pid = [uint64]$governedPid
  outside_control_pid = [uint64]$outsidePid
  governed_membership_query_succeeded = $false
  governed_is_member = $false
  outside_membership_query_succeeded = $false
  outside_is_member = $false
  extended_limit_query_succeeded = $false
  limit_flags = [uint64]0
  job_memory_limit_bytes = [uint64]0
}
$job = [IntPtr]::Zero
$governed = [IntPtr]::Zero
$outside = [IntPtr]::Zero
$buffer = [IntPtr]::Zero
try {
  $job = [EmberIssue898RuntimeJobProbe]::OpenJobObject(0x0004, $false, $jobObjectName)
  if ($job -ne [IntPtr]::Zero) {
    $governed = [EmberIssue898RuntimeJobProbe]::OpenProcess(0x1000, $false, $governedPid)
    if ($governed -ne [IntPtr]::Zero) {
      $isMember = $false
      $row.governed_membership_query_succeeded =
        [EmberIssue898RuntimeJobProbe]::IsProcessInJob($governed, $job, [ref]$isMember)
      $row.governed_is_member = [bool]$isMember
    }
    $outside = [EmberIssue898RuntimeJobProbe]::OpenProcess(0x1000, $false, $outsidePid)
    if ($outside -ne [IntPtr]::Zero) {
      $isMember = $false
      $row.outside_membership_query_succeeded =
        [EmberIssue898RuntimeJobProbe]::IsProcessInJob($outside, $job, [ref]$isMember)
      $row.outside_is_member = [bool]$isMember
    }
    $size = [Runtime.InteropServices.Marshal]::SizeOf(
      [type][EmberIssue898RuntimeJobProbe+JOBOBJECT_EXTENDED_LIMIT_INFORMATION])
    $buffer = [Runtime.InteropServices.Marshal]::AllocHGlobal($size)
    $row.extended_limit_query_succeeded =
      [EmberIssue898RuntimeJobProbe]::QueryInformationJobObject($job, 9, $buffer, $size, [IntPtr]::Zero)
    if ($row.extended_limit_query_succeeded) {
      $limits = [Runtime.InteropServices.Marshal]::PtrToStructure(
        $buffer, [type][EmberIssue898RuntimeJobProbe+JOBOBJECT_EXTENDED_LIMIT_INFORMATION])
      $row.limit_flags = [uint64]$limits.BasicLimitInformation.LimitFlags
      $row.job_memory_limit_bytes = [uint64]$limits.JobMemoryLimit.ToUInt64()
    }
  }
} finally {
  if ($buffer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::FreeHGlobal($buffer) }
  if ($outside -ne [IntPtr]::Zero) { [void][EmberIssue898RuntimeJobProbe]::CloseHandle($outside) }
  if ($governed -ne [IntPtr]::Zero) { [void][EmberIssue898RuntimeJobProbe]::CloseHandle($governed) }
  if ($job -ne [IntPtr]::Zero) { [void][EmberIssue898RuntimeJobProbe]::CloseHandle($job) }
}
$row | ConvertTo-Json -Compress
`;
  const encoded = Buffer.from(script, "utf16le").toString("base64");
  const child = spawnProcess(
    "powershell.exe",
    ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
    {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        EMBER_PROBE_JOB_ID: jobId,
        EMBER_PROBE_JOB_OBJECT_NAME: jobObjectName,
        EMBER_PROBE_GOVERNED_PID: String(governedPid),
        EMBER_PROBE_OUTSIDE_PID: String(outsideControlPid),
      },
    },
  );
  return await new Promise<RuntimeProbeProcessResult>((resolveProbe, rejectProbe) => {
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
      if (stdout.length > 1_048_576) child.kill();
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
      if (stderr.length > 1_048_576) child.kill();
    });
    child.once("error", rejectProbe);
    child.once("close", (exitCode) => {
      if (stdout.length > 1_048_576 || stderr.length > 1_048_576) {
        rejectProbe(new Error("runtime job enforcement probe output exceeded 1 MiB"));
        return;
      }
      resolveProbe({ exitCode, stderr, stdout });
    });
  });
}

function readTerminalOperationalReceipt(path: string): JsonObject {
  const operational = object(JSON.parse(readFileSync(path, "utf8")), "operational receipt");
  const state = operational["state"];
  if (
    operational["schema"] !== "ember-lab-operational-receipt-v1" ||
    (state !== "stopped" && state !== "exited" && state !== "failed")
  ) {
    throw new Error("operational receipt is not a daemon-authored terminal receipt");
  }
  return operational;
}

async function main(): Promise<void> {
  const repoRoot = resolve(process.argv[2] ?? "");
  const binary = resolve(process.argv[3] ?? "");
  const authorityRoot = resolve(process.argv[4] ?? "");
  const outputRoot = resolve(process.argv[5] ?? "");
  if (!process.argv[2] || !process.argv[3] || !process.argv[4] || !process.argv[5]) {
    throw new Error("usage: drive-job-memory-probe.ts <repo-root> <ember-binary> <authority-root> <new-output-root>");
  }
  if (existsSync(outputRoot)) throw new Error(`no-overwrite output root exists: ${outputRoot}`);
  const binding = readPacketBinding(repoRoot, authorityRoot);
  mkdirSync(outputRoot);
  const home = mkdtempSync(join(tmpdir(), "ember-job-memory-probe-"));
  const terminal: any = new (Terminal as any)({
    cols: COLS,
    rows: ROWS,
    allowProposedApi: true,
  });
  const raw: string[] = [];
  let writes = Promise.resolve();
  let child: IPty | undefined;
  let preflightProbe: RunningPreflightProbe | undefined;
  let preflightEvidence: TimedPreflightJobMembershipEvidence | undefined;
  let dispatchPossible = false;
  let terminalReceiptObserved = false;
  let childExited = false;
  let primaryFailure = false;
  let resolveChildExit: (() => void) | undefined;
  const childExit = new Promise<void>((resolveExit) => {
    resolveChildExit = resolveExit;
  });

  try {
    child = spawnPty(binary, [], {
      name: "xterm-256color",
      cols: COLS,
      rows: ROWS,
      cwd: repoRoot,
      env: {
        ...process.env,
        ...headlessCaptureEnv(),
        EMBER_HOME: home,
        EMBER_REPO_ROOT: repoRoot,
        EMBER_SOURCE_ROOT: repoRoot,
        EMBER_LAUNCH_AUTHORITY_ROOT: authorityRoot,
        EMBER_DISABLE_TERMINAL_TITLE: "1",
      },
      useConpty: true,
    });
    child.onData((data) => {
      raw.push(data);
      writes = writes.then(() => new Promise<void>((done) => terminal.write(data, done)));
    });
    child.onExit(() => {
      childExited = true;
      resolveChildExit?.();
    });

    await waitFor(
      () => (raw.join("").length > 0 ? true : undefined),
      () => writes,
      Date.now() + 30_000,
      "cockpit paint",
    );
    preflightProbe = startPreflightJobMembershipProbe(child.pid);
    await waitForPreflightProbeReady(preflightProbe);
    const trainCommandTypingStartedAtMs = Date.now();
    await typeCommand(child, "/train");
    await settle(() => writes, 2_000);
    let offerMatch = frameText(terminal).match(/OFFER (train-[A-Za-z0-9-]+) action=train-launch/);
    if (!offerMatch) {
      await writePtyData(child, "\r");
      offerMatch = await waitFor(
        () => frameText(terminal).match(/OFFER (train-[A-Za-z0-9-]+) action=train-launch/) ?? undefined,
        () => writes,
        Date.now() + 11 * 60_000,
        "production /train offer",
      );
    }
    const offerId = offerMatch[1]!;
    const offerObservedAtMs = Date.now();
    const probeToStop = preflightProbe;
    preflightProbe = undefined;
    const sampledEvidence = await stopPreflightJobMembershipProbe(probeToStop, outputRoot);
    preflightEvidence = {
      ...sampledEvidence,
      offerObservedAtMs,
      requestedSamplingIntervalMs: PREFLIGHT_PROBE_INTERVAL_MS,
      trainCommandTypingStartedAtMs,
      windowDurationMs: offerObservedAtMs - trainCommandTypingStartedAtMs,
    };
    writeExclusive(join(outputRoot, "01-offer.frame.txt"), frameText(terminal));
    writeExclusive(
      join(outputRoot, "01-preflight-job-membership.json"),
      `${JSON.stringify(preflightEvidence, null, 2)}\n`,
    );
    if (preflightEvidence.result === "NEVER_OBSERVED_MEASUREMENT_FAILED") {
      throw new Error("default /train preflight job-membership measurement failed");
    }

    await typeCommand(child, `/train confirm ${offerId}`);
    dispatchPossible = true;
    await settle(() => writes, 2_000);
    if (!/governed child pid: [1-9][0-9]*/.test(frameText(terminal))) {
      await writePtyData(child, "\r");
    }

    let governedEvidenceSeen = false;
    const dispatchOutcome = await waitFor(
      () => {
        const frame = frameText(terminal);
        const observation = observeTrainSample(
          frame,
          raw.join(""),
          undefined,
          governedEvidenceSeen,
        );
        governedEvidenceSeen = observation.governedEvidenceSeen;
        if (observation.governedEvidenceSeen) return "governed-evidence" as const;
        if (existsSync(binding.operationalReceipt)) return "receipt-before-start" as const;
        if (observation.synchronousRefusal) return "synchronous-refusal" as const;
        return undefined;
      },
      () => writes,
      undefined,
      "governed start, terminal receipt, or pre-dispatch refusal",
    );
    if (dispatchOutcome === "synchronous-refusal") {
      dispatchPossible = false;
      writeExclusive(join(outputRoot, "02-refusal.frame.txt"), frameText(terminal));
      writeExclusive(join(outputRoot, "raw.ansi.txt"), raw.join(""));
      throw new Error("production /train confirmation refused before governed dispatch");
    }
    if (dispatchOutcome === "receipt-before-start") {
      readTerminalOperationalReceipt(binding.operationalReceipt);
      terminalReceiptObserved = true;
      writeExclusive(join(outputRoot, "02-terminal-without-start.frame.txt"), frameText(terminal));
      writeExclusive(join(outputRoot, "raw.ansi.txt"), raw.join(""));
      throw new Error("terminal operational receipt arrived without governed start evidence");
    }
    if (dispatchOutcome !== "governed-evidence") {
      throw new Error("governed projection evidence vanished before authored identity lookup");
    }
    const preflightReceiptPath = binding.operationalReceipt.replace(/\.json$/, ".preflight.json");
    const databasePath = join(dirname(binding.operationalReceipt), "ember-lab.sqlite3");
    const start = await readGovernedStartFromArtifacts(
      preflightReceiptPath,
      databasePath,
      binding.runId,
      binding.maximumJobMemoryBytes,
    );
    if (!Number.isSafeInteger(start.governedPid) || start.governedPid <= 0) {
      throw new Error("governed start PID is invalid");
    }
    if (!start.jobId.startsWith(`${binding.runId}-launch-`)) {
      throw new Error("governed start job id is not bound to the packet run id");
    }
    if (!Number.isSafeInteger(child.pid) || child.pid <= 0) {
      throw new Error("outside-control cockpit PID is invalid");
    }
    writeExclusive(join(outputRoot, "02-start.frame.txt"), frameText(terminal));

    await waitFor(
      () => (existsSync(binding.operationalReceipt) ? true : undefined),
      () => writes,
      undefined,
      "terminal operational receipt",
    );
    const operational = readTerminalOperationalReceipt(binding.operationalReceipt);
    terminalReceiptObserved = true;
    if (
      operational["job_id"] !== start.jobId ||
      operational["pid"] !== start.governedPid
    ) {
      throw new Error("terminal operational receipt does not bind the governed start identity");
    }
    await settle(() => writes, 2_000);
    writeExclusive(join(outputRoot, "03-terminal.frame.txt"), frameText(terminal));
    writeExclusive(join(outputRoot, "raw.ansi.txt"), raw.join(""));
    let runtimeEvidence: DaemonJobMemoryEnforcementEvidence;
    try {
      runtimeEvidence = parseDaemonJobMemoryEnforcementWitness(operational, {
        jobId: start.jobId,
        governedPid: start.governedPid,
        maximumJobMemoryBytes: binding.maximumJobMemoryBytes,
      });
    } catch (error) {
      throw new Error(
        `daemon pre-execution job-memory witness failed terminal-receipt review: ${errorMessage(error)}`,
      );
    }
    writeExclusive(
      join(outputRoot, "03-daemon-job-memory-enforcement-witness.json"),
      `${JSON.stringify(runtimeEvidence, null, 2)}\n`,
    );
    const result = {
      schema_version: "ember-issue898-production-train-confirm-probe-leg-v1",
      route: "compiled_ember_cli_conpty_train_confirm",
      offer_id: offerId,
      run_id: binding.runId,
      job_id: start.jobId,
      governed_pid: start.governedPid,
      daemon_control_pid: runtimeEvidence.daemonControlPid,
      maximum_job_memory_bytes: binding.maximumJobMemoryBytes,
      signed_delta_bytes: binding.signedDeltaBytes,
      authority_root: authorityRoot,
      authority_packet_sha256: binding.hashes,
      operational_receipt: binding.operationalReceipt,
      operational_receipt_sha256: sha256(binding.operationalReceipt),
      default_train_preflight_job_membership: preflightEvidence,
      runtime_job_enforcement: runtimeEvidence,
      scientific_capability_evidence: false,
    };
    writeExclusive(join(outputRoot, "driver-receipt.json"), `${JSON.stringify(result, null, 2)}\n`);

    if (!childExited) {
      await typeCommand(child, "/exit");
      await Promise.race([
        childExit,
        new Promise<void>((resolveTimeout) => setTimeout(resolveTimeout, 10_000)),
      ]);
    }
  } catch (error) {
    primaryFailure = true;
    throw error;
  } finally {
    let cockpitPersistenceError: unknown;
    if (preflightProbe) {
      const drained = await drainPreflightProbe(preflightProbe);
      const finalizationErrors: unknown[] = [];
      if (drained.stopError) finalizationErrors.push(drained.stopError);
      try {
        persistPreflightProbeStreams(outputRoot, drained.stdout, drained.stderr);
      } catch (error) {
        finalizationErrors.push(error);
      }
      if (finalizationErrors.length > 0) {
        disclosePreflightFinalizationError(outputRoot, finalizationErrors);
      }
    }
    try {
      persistCockpitEvidence(outputRoot, raw.join(""), frameText(terminal));
    } catch (error) {
      discloseCockpitEvidenceFinalizationError(outputRoot, error);
      cockpitPersistenceError = error;
    }
    // Before confirmation, hard cleanup is safe because no governed launch can exist.
    // After confirmation, never terminate the cockpit until the daemon-authored terminal
    // receipt proves the governed job ended; doing so could strand the helper/daemon chain.
    if (child && !childExited && (!dispatchPossible || terminalReceiptObserved)) child.kill();
    if (!primaryFailure && cockpitPersistenceError !== undefined) {
      throw cockpitPersistenceError;
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
