// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

export interface LiveServingProcess {
  pid: number;
  name: string;
  command_line: string;
}

export interface ServingRegistryRow {
  port: number;
  model_path: string;
  pid: number;
  launched_by: string;
  ts: string;
  device: string;
}

export interface ServingTopologyAlarm {
  schema_version: "ember-serving-topology-drift-v1";
  ts: string;
  registry_identity: "state/serving-registry.json";
  live_pids: number[];
  registry_pids: number[];
  unregistered_live_pids: number[];
  dead_registry_pids: number[];
  action: "notify_operator";
}

export type ServingTopologyResult =
  | { status: "healthy"; live_pids: number[]; registry_pids: number[] }
  | {
      status: "drift";
      live_pids: number[];
      registry_pids: number[];
      alarm: ServingTopologyAlarm;
    };

function isPositiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) > 0;
}

function isServingProcess(row: LiveServingProcess): boolean {
  const name = row.name.trim().toLowerCase().replace(/\.exe$/i, "");
  const command = row.command_line.toLowerCase().replace(/\\/g, "/");
  return /^(?:llama[-_]?server|brain-server)$/.test(name)
    || /(?:^|[\s/])serve_cbase_openai\.py(?:\s|$)/.test(command);
}

function validateLive(row: LiveServingProcess): void {
  if (
    !isPositiveInteger(row.pid)
    || typeof row.name !== "string"
    || row.name.trim() === ""
    || typeof row.command_line !== "string"
  ) {
    throw new Error("SERVING_PROCESS_ROW_INVALID");
  }
}

function validateRegistry(row: ServingRegistryRow): void {
  if (
    !isPositiveInteger(row.port)
    || row.port > 65535
    || !isPositiveInteger(row.pid)
    || typeof row.model_path !== "string"
    || row.model_path.trim() === ""
    || typeof row.launched_by !== "string"
    || row.launched_by.trim() === ""
    || typeof row.device !== "string"
    || row.device.trim() === ""
    || typeof row.ts !== "string"
    || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(row.ts)
  ) {
    throw new Error("SERVING_REGISTRY_ROW_INVALID");
  }
}

function sortedUniquePids(values: readonly number[], duplicateCode: string): number[] {
  const seen = new Set<number>();
  for (const pid of values) {
    if (seen.has(pid)) throw new Error(`${duplicateCode}:${pid}`);
    seen.add(pid);
  }
  return [...seen].sort((left, right) => left - right);
}

export function evaluateServingTopology(
  processes: readonly LiveServingProcess[],
  registryRows: readonly ServingRegistryRow[],
  now: () => number = Date.now,
): ServingTopologyResult {
  for (const row of processes) validateLive(row);
  for (const row of registryRows) validateRegistry(row);

  const livePids = sortedUniquePids(
    processes.filter(isServingProcess).map((row) => row.pid),
    "SERVING_PROCESS_PID_DUPLICATE",
  );
  const registryPids = sortedUniquePids(
    registryRows.map((row) => row.pid),
    "SERVING_REGISTRY_PID_DUPLICATE",
  );
  const liveSet = new Set(livePids);
  const registrySet = new Set(registryPids);
  const unregistered = livePids.filter((pid) => !registrySet.has(pid));
  const dead = registryPids.filter((pid) => !liveSet.has(pid));

  if (unregistered.length === 0 && dead.length === 0) {
    return { status: "healthy", live_pids: livePids, registry_pids: registryPids };
  }

  return {
    status: "drift",
    live_pids: livePids,
    registry_pids: registryPids,
    alarm: {
      schema_version: "ember-serving-topology-drift-v1",
      ts: new Date(now()).toISOString(),
      registry_identity: "state/serving-registry.json",
      live_pids: livePids,
      registry_pids: registryPids,
      unregistered_live_pids: unregistered,
      dead_registry_pids: dead,
      action: "notify_operator",
    },
  };
}
