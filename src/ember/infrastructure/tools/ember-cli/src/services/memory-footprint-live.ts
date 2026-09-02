// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "node:crypto";
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import {
  createMemoryFootprintService,
  type BoundMemoryTripReceipt,
  type MemoryFootprintService,
  type MemoryFootprintServiceSpecBinding,
} from "./memory-footprint-service.ts";
import { censusWindowsProcessMemory } from "./process-memory-census.ts";
import type { ProcessMemoryCensusOptions } from "./process-memory-census.ts";
import type { ProcessMemorySample } from "./memory-footprint-governor.ts";
import {
  configuredEmberLabPipe,
  identifyEmberLabRuntime,
  type EmberLabRuntimeIdentity,
} from "./ember-lab-rpc.ts";

export const MEMORY_FOOTPRINT_SPEC_PATH =
  "src/ember/infrastructure/tools/ember-cli/specs/liveness-watchdog-memory-v1.json" as const;

export interface LiveMemoryFootprintServiceOptions {
  repoRoot: string;
  receiptPath: string;
  census?: () => Promise<ProcessMemorySample[]>;
  censusProcessMemory?: (
    spec: MemoryFootprintServiceSpecBinding["spec"],
    options: ProcessMemoryCensusOptions,
  ) => Promise<ProcessMemorySample[]>;
  identifyEmberLab?: () => Promise<EmberLabRuntimeIdentity>;
  onOwnershipError?: (error: unknown) => void;
  requestCorrectiveAction?: (receipt: BoundMemoryTripReceipt) => void;
  now?: () => number;
  intervalMs?: number;
  cockpitPid?: number;
  onPollError?: (error: unknown) => void;
}

function pathIsInside(candidate: string, container: string): boolean {
  const rel = relative(resolve(container), resolve(candidate));
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

export function loadMemoryFootprintSpecBinding(
  repoRoot: string,
): MemoryFootprintServiceSpecBinding {
  const filePath = join(repoRoot, ...MEMORY_FOOTPRINT_SPEC_PATH.split("/"));
  const bytes = readFileSync(filePath);
  let spec: unknown;
  try {
    spec = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw new Error("MEMORY_FOOTPRINT_SPEC_JSON_INVALID");
  }
  return {
    spec_path: MEMORY_FOOTPRINT_SPEC_PATH,
    spec_sha256: createHash("sha256").update(bytes).digest("hex"),
    spec: spec as MemoryFootprintServiceSpecBinding["spec"],
  };
}

export function createLiveMemoryFootprintService(
  options: LiveMemoryFootprintServiceOptions,
): MemoryFootprintService {
  if (!isAbsolute(options.repoRoot) || !isAbsolute(options.receiptPath)) {
    throw new Error("MEMORY_FOOTPRINT_PATH_NOT_ABSOLUTE");
  }
  if (pathIsInside(options.receiptPath, options.repoRoot)) {
    throw new Error("MEMORY_FOOTPRINT_RECEIPT_PATH_IN_CHECKOUT");
  }
  const binding = loadMemoryFootprintSpecBinding(options.repoRoot);
  const onOwnershipError = options.onOwnershipError ?? ((error: unknown) => {
    console.warn(
      `[memory-footprint] Ember Lab process identity unavailable: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  });
  const defaultCensus = async (): Promise<ProcessMemorySample[]> => {
    let ownedBrainPids: number[] = [];
    try {
      const identity = await (options.identifyEmberLab ?? (() => identifyEmberLabRuntime({
        pipeName: configuredEmberLabPipe(),
      })))();
      ownedBrainPids = [identity.pid];
    } catch (error) {
      onOwnershipError(error);
    }
    return (options.censusProcessMemory ?? censusWindowsProcessMemory)(binding.spec, {
      cockpitPid: options.cockpitPid ?? process.pid,
      ownedBrainPids,
    });
  };
  const appendReceipt = (receipt: BoundMemoryTripReceipt): void => {
    mkdirSync(dirname(options.receiptPath), { recursive: true });
    appendFileSync(options.receiptPath, `${JSON.stringify(receipt)}\n`, "utf8");
  };
  return createMemoryFootprintService({
    binding,
    census: options.census ?? defaultCensus,
    appendReceipt,
    requestCorrectiveAction: options.requestCorrectiveAction,
    now: options.now,
    intervalMs: options.intervalMs,
    onPollError: options.onPollError,
  });
}
