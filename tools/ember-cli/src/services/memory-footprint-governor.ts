// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

export type MemoryProcessClass = "cockpit" | "brain_server";

export interface MemoryClassSpec {
  soft_bytes: number;
  hard_bytes: number;
  consecutive_hard_polls: number;
  process_names: string[];
}

export interface MemoryFootprintSpec {
  schema_version: "ember-liveness-watchdog-memory-v1";
  goal_id: "EMBER-02";
  workstream_id: "EMBER-02A";
  next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember";
  classes: Record<MemoryProcessClass, MemoryClassSpec>;
}

export interface ProcessMemorySample {
  process_class: MemoryProcessClass;
  pid: number;
  commit_bytes: number;
}

export interface MemoryTripReceipt {
  schema_version: "ember-memory-footprint-trip-v1";
  ts: string;
  pid: number;
  process_class: MemoryProcessClass;
  commit_gb: number;
  threshold: number;
  action: "exit_cockpit_for_task_scheduler" | "notify_ember_lab_owner";
}

export interface MemoryObservation {
  state: "below_soft" | "soft" | "hard_debouncing" | "tripped";
  consecutive_hard_polls: number;
  receipt?: MemoryTripReceipt;
}

export interface MemoryFootprintGovernorOptions {
  spec: MemoryFootprintSpec;
  writeReceipt: (receipt: MemoryTripReceipt) => void;
  correctiveAction?: (receipt: MemoryTripReceipt) => void;
  now?: () => number;
}

export interface MemoryFootprintGovernor {
  reconcile(activeSamples: readonly ProcessMemorySample[]): void;
  observe(sample: ProcessMemorySample): MemoryObservation;
}

const GIB = 1024 ** 3;
const ACTIONS: Record<MemoryProcessClass, MemoryTripReceipt["action"]> = {
  cockpit: "exit_cockpit_for_task_scheduler",
  brain_server: "notify_ember_lab_owner",
};

function validateSpec(spec: MemoryFootprintSpec): void {
  if (
    Object.keys(spec).sort().join(",") !==
      "classes,goal_id,next_executed_outcome,schema_version,workstream_id"
    || Object.keys(spec.classes ?? {}).sort().join(",") !== "brain_server,cockpit"
  ) {
    throw new Error("MEMORY_FOOTPRINT_SPEC_PROPERTIES_INVALID");
  }
  if (spec.schema_version !== "ember-liveness-watchdog-memory-v1") {
    throw new Error("MEMORY_FOOTPRINT_SPEC_SCHEMA_INVALID");
  }
  if (
    spec.goal_id !== "EMBER-02"
    || spec.workstream_id !== "EMBER-02A"
    || spec.next_executed_outcome !==
      "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
  ) {
    throw new Error("MEMORY_FOOTPRINT_SPEC_AUTHORITY_INVALID");
  }
  for (const processClass of ["cockpit", "brain_server"] as const) {
    const row = spec.classes[processClass];
    if (
      !row
      || Object.keys(row).sort().join(",") !==
        "consecutive_hard_polls,hard_bytes,process_names,soft_bytes"
      || !Number.isSafeInteger(row.soft_bytes)
      || !Number.isSafeInteger(row.hard_bytes)
      || row.soft_bytes <= 0
      || row.hard_bytes <= row.soft_bytes
      || !Number.isSafeInteger(row.consecutive_hard_polls)
      || row.consecutive_hard_polls <= 0
      || !Array.isArray(row.process_names)
      || row.process_names.length === 0
      || row.process_names.some((name) => typeof name !== "string" || name.trim() === "")
    ) {
      throw new Error(`MEMORY_FOOTPRINT_SPEC_CLASS_INVALID:${processClass}`);
    }
  }
}

export function createMemoryFootprintGovernor(
  options: MemoryFootprintGovernorOptions,
): MemoryFootprintGovernor {
  validateSpec(options.spec);
  const now = options.now ?? Date.now;
  const episodes = new Map<string, { consecutive: number; tripped: boolean }>();

  return {
    reconcile(activeSamples): void {
      const active = new Set(
        activeSamples.map((sample) => `${sample.process_class}:${sample.pid}`),
      );
      for (const key of episodes.keys()) {
        if (!active.has(key)) episodes.delete(key);
      }
    },
    observe(sample: ProcessMemorySample): MemoryObservation {
      if (
        !Number.isSafeInteger(sample.pid)
        || sample.pid <= 0
        || !Number.isFinite(sample.commit_bytes)
        || sample.commit_bytes < 0
      ) {
        throw new Error("MEMORY_FOOTPRINT_SAMPLE_INVALID");
      }
      const row = options.spec.classes[sample.process_class];
      if (!row) throw new Error("MEMORY_FOOTPRINT_CLASS_UNKNOWN");
      const key = `${sample.process_class}:${sample.pid}`;
      const episode = episodes.get(key) ?? { consecutive: 0, tripped: false };

      if (sample.commit_bytes < row.hard_bytes) {
        episode.consecutive = 0;
        episode.tripped = false;
        episodes.set(key, episode);
        return {
          state: sample.commit_bytes < row.soft_bytes ? "below_soft" : "soft",
          consecutive_hard_polls: 0,
        };
      }

      if (episode.tripped) {
        return {
          state: "tripped",
          consecutive_hard_polls: episode.consecutive,
        };
      }

      episode.consecutive += 1;
      episodes.set(key, episode);
      if (episode.consecutive < row.consecutive_hard_polls) {
        return {
          state: "hard_debouncing",
          consecutive_hard_polls: episode.consecutive,
        };
      }

      const receipt: MemoryTripReceipt = {
        schema_version: "ember-memory-footprint-trip-v1",
        ts: new Date(now()).toISOString(),
        pid: sample.pid,
        process_class: sample.process_class,
        commit_gb: sample.commit_bytes / GIB,
        threshold: row.hard_bytes / GIB,
        action: ACTIONS[sample.process_class],
      };
      options.writeReceipt(receipt);
      episode.tripped = true;
      options.correctiveAction?.(receipt);
      return {
        state: "tripped",
        consecutive_hard_polls: episode.consecutive,
        receipt,
      };
    },
  };
}
