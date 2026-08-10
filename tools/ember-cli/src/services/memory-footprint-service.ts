// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import {
  createMemoryFootprintGovernor,
  type MemoryFootprintSpec,
  type MemoryTripReceipt,
  type ProcessMemorySample,
} from "./memory-footprint-governor.ts";

export interface MemoryFootprintServiceSpecBinding {
  spec_path: "tools/ember-cli/specs/liveness-watchdog-memory-v1.json";
  spec_sha256: string;
  spec: MemoryFootprintSpec;
}

export interface BoundMemoryTripReceipt extends MemoryTripReceipt {
  spec_path: MemoryFootprintServiceSpecBinding["spec_path"];
  spec_sha256: string;
}

export interface MemoryFootprintServiceOptions {
  binding: MemoryFootprintServiceSpecBinding;
  census: () => Promise<ProcessMemorySample[]>;
  appendReceipt: (receipt: BoundMemoryTripReceipt) => void;
  requestCorrectiveAction?: (receipt: BoundMemoryTripReceipt) => void;
  now?: () => number;
  intervalMs?: number;
  setIntervalFn?: typeof setInterval;
  clearIntervalFn?: typeof clearInterval;
  onPollError?: (error: unknown) => void;
}

export interface MemoryFootprintService {
  pollOnce(): Promise<void>;
  start(): void;
  stop(): void;
  isRunning(): boolean;
}

function validateBinding(binding: MemoryFootprintServiceSpecBinding): void {
  if (binding.spec_path !== "tools/ember-cli/specs/liveness-watchdog-memory-v1.json") {
    throw new Error("MEMORY_FOOTPRINT_SPEC_PATH_INVALID");
  }
  if (!/^[0-9a-f]{64}$/.test(binding.spec_sha256)) {
    throw new Error("MEMORY_FOOTPRINT_SPEC_SHA256_INVALID");
  }
}

export function createMemoryFootprintService(
  options: MemoryFootprintServiceOptions,
): MemoryFootprintService {
  validateBinding(options.binding);
  let polling = false;
  let timer: ReturnType<typeof setInterval> | null = null;
  let pendingReceipt: BoundMemoryTripReceipt | null = null;
  const governor = createMemoryFootprintGovernor({
    spec: options.binding.spec,
    now: options.now,
    writeReceipt: (receipt) => {
      const bound: BoundMemoryTripReceipt = {
        ...receipt,
        spec_path: options.binding.spec_path,
        spec_sha256: options.binding.spec_sha256,
      };
      options.appendReceipt(bound);
      pendingReceipt = bound;
    },
    correctiveAction: () => {
      const bound = pendingReceipt;
      pendingReceipt = null;
      if (!bound) throw new Error("MEMORY_FOOTPRINT_RECEIPT_ORDER_INVALID");
      options.requestCorrectiveAction?.(bound);
    },
  });
  const intervalMs = options.intervalMs ?? 1_000;
  const setIntervalFn = options.setIntervalFn ?? setInterval;
  const clearIntervalFn = options.clearIntervalFn ?? clearInterval;
  const onPollError = options.onPollError ?? ((error: unknown) => {
    console.warn(
      `[memory-footprint] poll failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  });

  const service: MemoryFootprintService = {
    async pollOnce(): Promise<void> {
      if (polling) return;
      polling = true;
      try {
        const samples = await options.census();
        governor.reconcile(samples);
        for (const sample of samples) governor.observe(sample);
      } finally {
        polling = false;
      }
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
