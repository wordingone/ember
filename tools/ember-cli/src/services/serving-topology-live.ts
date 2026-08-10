import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import {
  evaluateServingTopology,
  type LiveServingProcess,
  type ServingRegistryRow,
  type ServingTopologyAlarm,
  type ServingTopologyResult,
} from "./serving-topology-drift.ts";
import { censusWindowsServingProcesses } from "./serving-topology-census.ts";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

export interface LiveServingTopologyOptions {
  repoRoot: string;
  alarmPath: string;
  census?: () => Promise<readonly LiveServingProcess[]>;
  now?: () => number;
  notifyOperator?: (alarm: ServingTopologyAlarm) => void | Promise<void>;
  intervalMs?: number;
  setIntervalFn?: typeof setInterval;
  clearIntervalFn?: typeof clearInterval;
  onPollError?: (error: unknown) => void;
}

export interface LiveServingTopologyService {
  pollOnce(): Promise<ServingTopologyResult>;
  start(): void;
  stop(): void;
  isRunning(): boolean;
}

function isWithin(parent: string, candidate: string): boolean {
  const rel = relative(parent, candidate);
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

function readRegistry(repoRoot: string): ServingRegistryRow[] {
  const registryPath = resolve(repoRoot, "state", "serving-registry.json");
  if (!existsSync(registryPath)) return [];
  const rows: ServingRegistryRow[] = [];
  for (const line of readFileSync(registryPath, "utf8").split(/\r?\n/)) {
    if (line === "") continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      throw new Error("SERVING_REGISTRY_JSON_INVALID");
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("SERVING_REGISTRY_ROW_INVALID");
    }
    rows.push(parsed as ServingRegistryRow);
  }
  return rows;
}

export function createLiveServingTopologyService(
  options: LiveServingTopologyOptions,
): LiveServingTopologyService {
  const repoRoot = resolve(options.repoRoot);
  const alarmPath = resolve(options.alarmPath);
  if (isWithin(repoRoot, alarmPath)) throw new Error("SERVING_ALARM_PATH_IN_CHECKOUT");

  let durableDriftSignature: string | null = null;
  let notifiedDriftSignature: string | null = null;
  let inFlight: Promise<ServingTopologyResult> | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;
  const setIntervalFn = options.setIntervalFn ?? setInterval;
  const clearIntervalFn = options.clearIntervalFn ?? clearInterval;
  const intervalMs = options.intervalMs ?? 5_000;
  const onPollError = options.onPollError ?? ((error: unknown) => {
    console.warn(
      `[serving-topology] poll failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  });

  const service: LiveServingTopologyService = {
    pollOnce(): Promise<ServingTopologyResult> {
      if (inFlight !== null) return inFlight;
      inFlight = (async () => {
        const result = evaluateServingTopology(
          await (options.census ?? censusWindowsServingProcesses)(),
          readRegistry(repoRoot),
          options.now,
        );
        if (result.status === "healthy") {
          durableDriftSignature = null;
          notifiedDriftSignature = null;
          return result;
        }
        const signature = JSON.stringify([
          result.alarm.unregistered_live_pids,
          result.alarm.dead_registry_pids,
        ]);
        if (signature !== durableDriftSignature) {
          mkdirSync(dirname(alarmPath), { recursive: true });
          appendFileSync(alarmPath, `${JSON.stringify(result.alarm)}\n`, "utf8");
          durableDriftSignature = signature;
          notifiedDriftSignature = null;
        }
        if (signature !== notifiedDriftSignature) {
          await options.notifyOperator?.(result.alarm);
          notifiedDriftSignature = signature;
        }
        return result;
      })().finally(() => { inFlight = null; });
      return inFlight;
    },
    start(): void {
      if (timer !== null) return;
      void service.pollOnce().catch(onPollError);
      timer = setIntervalFn(() => { void service.pollOnce().catch(onPollError); }, intervalMs);
    },
    stop(): void {
      if (timer === null) return;
      clearIntervalFn(timer);
      timer = null;
    },
    isRunning(): boolean {
      return timer !== null;
    },
  };
  return service;
}
