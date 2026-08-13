// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/host-telemetry-poller.ts — the resting-state producer for the right panel's host
// curves: memory (process RSS), RAM (system used), CPU %, disk used %. VRAM and GPU % are NOT
// read here — they route from the EXISTING services/gpu-state-poller.ts via pushGpuSample; a
// second nvidia-smi reader would be the duplicate-producer defect the spec rules out.
//
// Contract (each clause is an acceptance row):
// - A metric that cannot be read is `null`, never zero. Zero is a reading; absence is not.
//   Each series carries an unavailableReason so the label can say why.
// - One unavailable source never suppresses the others: every reader is individually
//   try/caught, so an nvidia-smi failure isolates to VRAM+GPU and a disk-stat failure isolates
//   to disk (skip-path S3: a first-poll failure before any interval exists is the same path).
// - stop()/unmount clears the interval and leaves no child process behind (this module spawns
//   none; the GPU child lives in gpu-state-poller, which already cleans up its own).

import { useEffect, useRef, useState } from "react";
import type { GpuStateSnapshot } from "./gpu-state-poller.ts";

export type HostMetricId = "memory" | "ram" | "vram" | "cpu" | "gpu" | "disk";

export const HOST_METRIC_IDS: readonly HostMetricId[] = ["memory", "ram", "vram", "cpu", "gpu", "disk"];

export interface HostMetricSeries {
  /** Ring-buffered samples, oldest first. null = unavailable at that tick (a gap, never zero). */
  values: Array<number | null>;
  unit: string;
  /** Why the LATEST sample is null; undefined when the latest sample is a real reading. */
  unavailableReason?: string;
}

export type HostTelemetrySnapshot = Record<HostMetricId, HostMetricSeries>;

/** Injectable readers — tests supply fakes; production uses the node:os / node:fs defaults.
 *  Each returns a number or null (unavailable); a throw is treated as null-with-reason. */
export interface HostTelemetryReaders {
  /** Process RSS, GiB. */
  memory?: () => number | null;
  /** System RAM used, GiB. */
  ram?: () => number | null;
  /** Aggregate CPU busy %, from os.cpus() deltas between polls. */
  cpu?: () => number | null;
  /** Disk used %, from statfs of the working directory's volume. */
  disk?: () => number | null;
}

export interface HostTelemetryPollerOptions {
  intervalMs?: number;
  capacity?: number;
  readers?: HostTelemetryReaders;
  setIntervalFn?: typeof setInterval;
  clearIntervalFn?: typeof clearInterval;
  /** #1455: called with the fresh snapshot immediately after each poll tick AND after each
   *  pushGpuSample -- the single publish point a consumer subscribes to instead of running its
   *  own decoupled timer over snapshot(). Two independent 1s timers (this poller's internal tick
   *  and a caller's separate republish interval) can interleave out of phase, so a consumer
   *  reading snapshot() from its own timer can observe a snapshot up to one tick stale relative
   *  to the poll that just landed -- and, being decoupled, that consumer has to re-derive "did
   *  anything change" on ITS OWN independent cadence rather than being told the moment new data
   *  is ready. onUpdate removes the second timer entirely: one interval, one publish point. */
  onUpdate?: (snapshot: HostTelemetrySnapshot) => void;
}

export const DEFAULT_HOST_TELEMETRY_INTERVAL_MS = 1000;
export const DEFAULT_HOST_TELEMETRY_CAPACITY = 600;

const GIB = 1024 ** 3;

function defaultMemoryReader(): number | null {
  return process.memoryUsage().rss / GIB;
}

// os.cpus() reports cumulative jiffies; CPU % needs two observations, so the reader closes over
// its previous snapshot. First call has no baseline -> null-with-reason, never a fabricated 0.
function makeDefaultCpuReader(): () => number | null {
  let previous: { idle: number; total: number } | null = null;
  return () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const os = require("node:os") as typeof import("node:os");
    const cpus = os.cpus();
    if (!cpus || cpus.length === 0) return null;
    let idle = 0;
    let total = 0;
    for (const cpu of cpus) {
      idle += cpu.times.idle;
      total += cpu.times.user + cpu.times.nice + cpu.times.sys + cpu.times.idle + cpu.times.irq;
    }
    const last = previous;
    previous = { idle, total };
    if (!last || total <= last.total) return null; // no baseline yet
    const busy = 1 - (idle - last.idle) / (total - last.total);
    return Math.max(0, Math.min(100, busy * 100));
  };
}

function defaultRamReader(): number | null {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const os = require("node:os") as typeof import("node:os");
  const total = os.totalmem();
  const free = os.freemem();
  if (!Number.isFinite(total) || !Number.isFinite(free) || total <= 0) return null;
  return (total - free) / GIB;
}

function defaultDiskReader(): number | null {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const fs = require("node:fs") as typeof import("node:fs");
  const statfs = (fs as { statfsSync?: (path: string) => { blocks: number; bfree: number } }).statfsSync;
  if (typeof statfs !== "function") return null;
  const stat = statfs(process.cwd());
  if (!Number.isFinite(stat.blocks) || stat.blocks <= 0 || !Number.isFinite(stat.bfree)) return null;
  return Math.max(0, Math.min(100, ((stat.blocks - stat.bfree) / stat.blocks) * 100));
}

interface SeriesState {
  values: Array<number | null>;
  unit: string;
  unavailableReason?: string;
}

export interface HostTelemetryPoller {
  start(): void;
  stop(): void;
  /** Runs one poll tick synchronously (tests drive ticks without timers). */
  pollOnce(): void;
  /** Routes a GPU reading from the EXISTING gpu-state-poller into the vram/gpu series.
   *  null = nvidia-smi unavailable -> both series get null-with-reason; the other four are
   *  untouched by construction (separate series, separate readers). */
  pushGpuSample(gpu: GpuStateSnapshot | null): void;
  snapshot(): HostTelemetrySnapshot;
  /** True while the interval is alive (acceptance row 7 asserts false after stop). */
  isRunning(): boolean;
}

export function createHostTelemetryPoller(options: HostTelemetryPollerOptions = {}): HostTelemetryPoller {
  const capacity = Math.max(2, options.capacity ?? DEFAULT_HOST_TELEMETRY_CAPACITY);
  const intervalMs = options.intervalMs ?? DEFAULT_HOST_TELEMETRY_INTERVAL_MS;
  const setIntervalFn = options.setIntervalFn ?? setInterval;
  const clearIntervalFn = options.clearIntervalFn ?? clearInterval;
  const readers: Required<HostTelemetryReaders> = {
    memory: options.readers?.memory ?? defaultMemoryReader,
    ram: options.readers?.ram ?? defaultRamReader,
    cpu: options.readers?.cpu ?? makeDefaultCpuReader(),
    disk: options.readers?.disk ?? defaultDiskReader,
  };

  const series: Record<HostMetricId, SeriesState> = {
    memory: { values: [], unit: "GiB" },
    ram: { values: [], unit: "GiB" },
    vram: { values: [], unit: "GiB" },
    cpu: { values: [], unit: "%" },
    gpu: { values: [], unit: "%" },
    disk: { values: [], unit: "%" },
  };
  let timer: ReturnType<typeof setInterval> | null = null;

  function push(id: HostMetricId, value: number | null, reason?: string): void {
    const state = series[id];
    state.values.push(value);
    if (state.values.length > capacity) state.values.splice(0, state.values.length - capacity);
    state.unavailableReason = value === null ? (reason ?? "unavailable") : undefined;
  }

  function readInto(id: Exclude<HostMetricId, "vram" | "gpu">): void {
    // Per-metric isolation: a throwing reader nulls ONLY its own series (spec: one unavailable
    // source never suppresses the others; also skip-path S3 — a first-poll throw lands here
    // identically, before or after the interval exists).
    try {
      const value = readers[id]();
      push(id, Number.isFinite(value as number) ? (value as number) : null, value === null ? "no reading" : "non-finite reading");
    } catch (error) {
      push(id, null, error instanceof Error ? error.message : "read failed");
    }
  }

  function buildSnapshot(): HostTelemetrySnapshot {
    const out = {} as HostTelemetrySnapshot;
    for (const id of HOST_METRIC_IDS) {
      out[id] = { values: [...series[id].values], unit: series[id].unit, unavailableReason: series[id].unavailableReason };
    }
    return out;
  }

  return {
    start(): void {
      if (timer !== null) return;
      this.pollOnce();
      timer = setIntervalFn(() => this.pollOnce(), intervalMs);
    },
    stop(): void {
      if (timer !== null) {
        clearIntervalFn(timer);
        timer = null;
      }
    },
    pollOnce(): void {
      readInto("memory");
      readInto("ram");
      readInto("cpu");
      readInto("disk");
      options.onUpdate?.(buildSnapshot());
    },
    pushGpuSample(gpu: GpuStateSnapshot | null): void {
      if (gpu === null) {
        push("vram", null, "nvidia-smi unavailable");
        push("gpu", null, "nvidia-smi unavailable");
      } else {
        const used = gpu.memory.vramUsedGib;
        const util = gpu.memory.utilPct;
        push("vram", Number.isFinite(used) ? used : null, "non-finite reading");
        push("gpu", Number.isFinite(util) ? util : null, "non-finite reading");
      }
      options.onUpdate?.(buildSnapshot());
    },
    snapshot(): HostTelemetrySnapshot {
      return buildSnapshot();
    },
    isRunning(): boolean {
      return timer !== null;
    },
  };
}

/**
 * React hook: owns one poller for the component's lifetime, routes the EXISTING
 * useGpuStatePoller's snapshot into vram/gpu, republishes the snapshot each tick, and stops the
 * poller on unmount (acceptance row 7: no interval alive after unmount; no child process was
 * ever spawned here).
 *
 * #1455: republishing used to run on a SECOND, independent setInterval(intervalMs) layered on
 * top of the poller's own internal tick -- two decoupled 1s timers computing and cloning the
 * same 6-series snapshot out of phase with each other. onUpdate collapses this to the poller's
 * single tick: one interval, one publish, called exactly when new data actually lands.
 */
export function useHostTelemetryPoller(
  gpuState: GpuStateSnapshot | null,
  intervalMs: number = DEFAULT_HOST_TELEMETRY_INTERVAL_MS,
  options: HostTelemetryPollerOptions = {},
): HostTelemetrySnapshot {
  const pollerRef = useRef<HostTelemetryPoller | null>(null);
  const setSnapshotRef = useRef<((snapshot: HostTelemetrySnapshot) => void) | null>(null);
  if (pollerRef.current === null) {
    pollerRef.current = createHostTelemetryPoller({
      ...options,
      intervalMs,
      onUpdate: (snapshot) => setSnapshotRef.current?.(snapshot),
    });
  }
  const [snapshot, setSnapshot] = useState<HostTelemetrySnapshot>(() => pollerRef.current!.snapshot());
  setSnapshotRef.current = setSnapshot;

  useEffect(() => {
    const poller = pollerRef.current!;
    poller.start();
    return () => poller.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  useEffect(() => {
    pollerRef.current!.pushGpuSample(gpuState);
  }, [gpuState]);

  return snapshot;
}
