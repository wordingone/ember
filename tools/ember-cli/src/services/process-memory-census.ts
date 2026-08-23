// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { execFile } from "node:child_process";
import type {
  MemoryFootprintSpec,
  MemoryProcessClass,
  ProcessMemorySample,
} from "./memory-footprint-governor.ts";

export interface ProcessMemoryCensusOptions {
  cockpitPid: number;
  ownedBrainPids?: readonly number[];
  observedAt?: () => string;
  runPowerShell?: () => Promise<string>;
}

export const WINDOWS_PROCESS_MEMORY_PROVIDER =
  "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks" as const;

export interface ProcessMemoryCensusSample extends ProcessMemorySample {
  parent_pid: number;
  process_name: string;
  process_start_token: string;
  provider: typeof WINDOWS_PROCESS_MEMORY_PROVIDER;
  ownership_basis: string[];
}

export interface ProcessMemoryCensusBatch {
  schema_version: "ember-process-memory-census-poll-v1";
  observed_at: string;
  provider: typeof WINDOWS_PROCESS_MEMORY_PROVIDER;
  candidate_process_count: number;
  admitted_process_count: number;
  class_cardinality: Record<MemoryProcessClass, number>;
  ownership_overlap: { count: number; pids: number[] };
  samples: ProcessMemoryCensusSample[];
}

interface WindowsProcessRow {
  Id: unknown;
  ParentProcessId: unknown;
  ProcessName: unknown;
  PagedMemorySize64: unknown;
  ProcessStartToken?: unknown;
}

function normalizedProcessName(value: string): string {
  return value.trim().toLowerCase().replace(/\.exe$/i, "");
}

function ownershipByName(spec: MemoryFootprintSpec): Map<string, MemoryProcessClass> {
  const owners = new Map<string, MemoryProcessClass>();
  for (const processClass of ["cockpit", "brain_server"] as const) {
    for (const configured of spec.classes[processClass].process_names) {
      const name = normalizedProcessName(configured);
      const prior = owners.get(name);
      if (prior && prior !== processClass) {
        throw new Error(`MEMORY_CENSUS_NAME_AMBIGUOUS:${name}`);
      }
      owners.set(name, processClass);
    }
  }
  return owners;
}

function defaultPowerShellCensus(): Promise<string> {
  const script = [
    "$rows = @()",
    "Get-CimInstance Win32_Process | ForEach-Object {",
    "$commit = $null; $start = $null; try { $p = Get-Process -Id $_.ProcessId -ErrorAction Stop; $commit = [int64]$p.PagedMemorySize64; $start = [string]$p.StartTime.ToUniversalTime().Ticks } catch {}",
    "$rows += [PSCustomObject]@{ Id = [int]$_.ProcessId; ParentProcessId = [int]$_.ParentProcessId; ProcessName = [string]$_.Name; PagedMemorySize64 = $commit; ProcessStartToken = $start } }",
    "$rows | ConvertTo-Json -Compress",
  ].join("; ");
  return new Promise((resolve, reject) => {
    execFile(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
      { encoding: "utf8", windowsHide: true },
      (error, stdout) => error ? reject(error) : resolve(stdout),
    );
  });
}

async function censusWindowsProcessMemoryBatchInner(
  spec: MemoryFootprintSpec,
  options: ProcessMemoryCensusOptions,
  requireStartToken: boolean,
): Promise<ProcessMemoryCensusBatch> {
  if (!Number.isSafeInteger(options.cockpitPid) || options.cockpitPid <= 0) {
    throw new Error("MEMORY_CENSUS_COCKPIT_PID_INVALID");
  }
  const owners = ownershipByName(spec);
  const ownedBrainPids = new Set<number>();
  for (const pid of options.ownedBrainPids ?? []) {
    if (!Number.isSafeInteger(pid) || pid <= 0 || ownedBrainPids.has(pid)) {
      throw new Error("MEMORY_CENSUS_BRAIN_PID_INVALID");
    }
    ownedBrainPids.add(pid);
  }
  const raw = await (options.runPowerShell ?? defaultPowerShellCensus)();
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw.trim() || "[]");
  } catch {
    throw new Error("MEMORY_CENSUS_JSON_INVALID");
  }
  const rows = Array.isArray(parsed) ? parsed : [parsed];
  const samples: ProcessMemoryCensusSample[] = [];
  const overlapPids: number[] = [];
  const seen = new Set<number>();
  for (const candidate of rows) {
    if (typeof candidate !== "object" || candidate === null) {
      throw new Error("MEMORY_CENSUS_ROW_INVALID");
    }
    const row = candidate as WindowsProcessRow;
    if (
      !Number.isSafeInteger(row.Id)
      || (row.Id as number) <= 0
      || !Number.isSafeInteger(row.ParentProcessId)
      || (row.ParentProcessId as number) < 0
      || typeof row.ProcessName !== "string"
    ) {
      throw new Error("MEMORY_CENSUS_ROW_INVALID");
    }
    const pid = row.Id as number;
    const processName = normalizedProcessName(row.ProcessName);
    const owner = owners.get(processName);
    const isCockpit = pid === options.cockpitPid;
    const brainBases: string[] = [];
    if (owner === "brain_server") {
      if (ownedBrainPids.has(pid)) brainBases.push("ember_lab_runtime_pid");
      if (ownedBrainPids.has(row.ParentProcessId as number)) brainBases.push("ember_lab_runtime_child");
      if (row.ParentProcessId === options.cockpitPid) brainBases.push("cockpit_child");
    }
    const isOwnedBrainServer = brainBases.length > 0;
    if (!isCockpit && !isOwnedBrainServer) continue;
    if (!Number.isFinite(row.PagedMemorySize64) || (row.PagedMemorySize64 as number) < 0) {
      throw new Error(`MEMORY_CENSUS_COMMIT_UNREADABLE:${pid}`);
    }
    let processStartToken: string;
    if (typeof row.ProcessStartToken === "string" && /^[1-9][0-9]*$/.test(row.ProcessStartToken)) {
      processStartToken = row.ProcessStartToken;
    } else if (requireStartToken) {
      throw new Error(`MEMORY_CENSUS_START_TOKEN_UNREADABLE:${pid}`);
    } else {
      processStartToken = "unavailable-legacy-call";
    }
    if (seen.has(pid)) throw new Error(`MEMORY_CENSUS_PID_DUPLICATE:${pid}`);
    seen.add(pid);
    const ownershipBasis = isCockpit ? ["cockpit_pid"] : brainBases;
    if (ownershipBasis.length > 1) overlapPids.push(pid);
    samples.push({
      process_class: isCockpit ? "cockpit" : "brain_server",
      pid,
      parent_pid: row.ParentProcessId as number,
      process_name: processName,
      process_start_token: processStartToken,
      provider: WINDOWS_PROCESS_MEMORY_PROVIDER,
      commit_bytes: row.PagedMemorySize64 as number,
      ownership_basis: ownershipBasis,
    });
  }
  if (!samples.some((sample) => sample.process_class === "cockpit" && sample.pid === options.cockpitPid)) {
    throw new Error(`MEMORY_CENSUS_COCKPIT_MISSING:${options.cockpitPid}`);
  }
  samples.sort((left, right) => left.pid - right.pid);
  const observedAt = (options.observedAt ?? (() => new Date().toISOString()))();
  const observedAtMs = Date.parse(observedAt);
  if (Number.isNaN(observedAtMs) || new Date(observedAtMs).toISOString() !== observedAt) throw new Error("MEMORY_CENSUS_OBSERVED_AT_INVALID");
  return {
    schema_version: "ember-process-memory-census-poll-v1",
    observed_at: observedAt,
    provider: WINDOWS_PROCESS_MEMORY_PROVIDER,
    candidate_process_count: rows.length,
    admitted_process_count: samples.length,
    class_cardinality: {
      cockpit: samples.filter((sample) => sample.process_class === "cockpit").length,
      brain_server: samples.filter((sample) => sample.process_class === "brain_server").length,
    },
    ownership_overlap: { count: overlapPids.length, pids: overlapPids.sort((a, b) => a - b) },
    samples,
  };
}

export function censusWindowsProcessMemoryBatch(
  spec: MemoryFootprintSpec,
  options: ProcessMemoryCensusOptions,
): Promise<ProcessMemoryCensusBatch> {
  return censusWindowsProcessMemoryBatchInner(spec, options, true);
}

export async function censusWindowsProcessMemory(
  spec: MemoryFootprintSpec,
  options: ProcessMemoryCensusOptions,
): Promise<ProcessMemorySample[]> {
  const batch = await censusWindowsProcessMemoryBatchInner(spec, options, false);
  return batch.samples.map(({ process_class, pid, commit_bytes }) => ({
    process_class,
    pid,
    commit_bytes,
  }));
}
