import { execFile } from "node:child_process";
import type { LiveServingProcess } from "./serving-topology-drift.ts";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

export interface ServingTopologyCensusOptions {
  runPowerShell?: () => Promise<string>;
}

interface WindowsServingProcessRow {
  Id: unknown;
  ProcessName: unknown;
  CommandLine: unknown;
}

function defaultPowerShellCensus(): Promise<string> {
  const script = [
    "Get-CimInstance Win32_Process",
    "Select-Object @{n='Id';e={[int]$_.ProcessId}}, @{n='ProcessName';e={[string]$_.Name}}, @{n='CommandLine';e={[string]$_.CommandLine}}",
    "ConvertTo-Json -Compress",
  ].join(" | ");
  return new Promise((resolve, reject) => {
    execFile(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
      { encoding: "utf8", windowsHide: true },
      (error, stdout) => error ? reject(error) : resolve(stdout),
    );
  });
}

export async function censusWindowsServingProcesses(
  options: ServingTopologyCensusOptions = {},
): Promise<LiveServingProcess[]> {
  let parsed: unknown;
  try {
    parsed = JSON.parse((await (options.runPowerShell ?? defaultPowerShellCensus)()).trim() || "[]");
  } catch {
    throw new Error("SERVING_CENSUS_JSON_INVALID");
  }

  const candidates = Array.isArray(parsed) ? parsed : [parsed];
  const seen = new Set<number>();
  const rows: LiveServingProcess[] = [];
  for (const candidate of candidates) {
    if (typeof candidate !== "object" || candidate === null || Array.isArray(candidate)) {
      throw new Error("SERVING_CENSUS_ROW_INVALID");
    }
    const row = candidate as WindowsServingProcessRow;
    if (
      !Number.isSafeInteger(row.Id)
      || (row.Id as number) <= 0
      || typeof row.ProcessName !== "string"
      || row.ProcessName.trim() === ""
      || typeof row.CommandLine !== "string"
    ) {
      throw new Error("SERVING_CENSUS_ROW_INVALID");
    }
    const pid = row.Id as number;
    if (seen.has(pid)) throw new Error(`SERVING_CENSUS_PID_DUPLICATE:${pid}`);
    seen.add(pid);
    rows.push({ pid, name: row.ProcessName, command_line: row.CommandLine });
  }
  return rows.sort((left, right) => left.pid - right.pid);
}
