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
  runPowerShell?: () => Promise<string>;
}

interface WindowsProcessRow {
  Id: unknown;
  ParentProcessId: unknown;
  ProcessName: unknown;
  PagedMemorySize64: unknown;
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
    "$commit = $null; try { $p = Get-Process -Id $_.ProcessId -ErrorAction Stop; $commit = [int64]$p.PagedMemorySize64 } catch {}",
    "$rows += [PSCustomObject]@{ Id = [int]$_.ProcessId; ParentProcessId = [int]$_.ParentProcessId; ProcessName = [string]$_.Name; PagedMemorySize64 = $commit } }",
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

export async function censusWindowsProcessMemory(
  spec: MemoryFootprintSpec,
  options: ProcessMemoryCensusOptions,
): Promise<ProcessMemorySample[]> {
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
  const samples: ProcessMemorySample[] = [];
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
    const owner = owners.get(normalizedProcessName(row.ProcessName));
    const isCockpit = pid === options.cockpitPid;
    const isOwnedBrainServer = owner === "brain_server" && (
      row.ParentProcessId === options.cockpitPid
      || ownedBrainPids.has(pid)
      || ownedBrainPids.has(row.ParentProcessId as number)
    );
    if (!isCockpit && !isOwnedBrainServer) continue;
    if (!Number.isFinite(row.PagedMemorySize64) || (row.PagedMemorySize64 as number) < 0) {
      throw new Error(`MEMORY_CENSUS_COMMIT_UNREADABLE:${pid}`);
    }
    if (seen.has(pid)) throw new Error(`MEMORY_CENSUS_PID_DUPLICATE:${pid}`);
    seen.add(pid);
    samples.push({
      process_class: isCockpit ? "cockpit" : "brain_server",
      pid,
      commit_bytes: row.PagedMemorySize64 as number,
    });
  }
  if (!samples.some((sample) => sample.process_class === "cockpit" && sample.pid === options.cockpitPid)) {
    throw new Error(`MEMORY_CENSUS_COCKPIT_MISSING:${options.cockpitPid}`);
  }
  return samples.sort((left, right) => left.pid - right.pid);
}
