// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { createHostTelemetryPoller } from "./host-telemetry-poller.ts";
import type { GpuStateSnapshot } from "./gpu-state-poller.ts";

const gpuSnapshot: GpuStateSnapshot = {
  memory: { vramUsedGib: 18, vramTotalGib: 24, utilPct: 42 },
  computeProcessNames: [],
};

function fakeReaders(overrides: Partial<Record<"memory" | "ram" | "cpu" | "disk", () => number | null>> = {}) {
  return {
    memory: () => 1.5,
    ram: () => 20,
    cpu: () => 33,
    disk: () => 61,
    ...overrides,
  };
}

describe("host telemetry poller", () => {
  test("a poll tick pushes one real sample per host metric", () => {
    const poller = createHostTelemetryPoller({ readers: fakeReaders() });
    poller.pollOnce();
    const snapshot = poller.snapshot();
    expect(snapshot.memory.values).toEqual([1.5]);
    expect(snapshot.ram.values).toEqual([20]);
    expect(snapshot.cpu.values).toEqual([33]);
    expect(snapshot.disk.values).toEqual([61]);
    expect(snapshot.memory.unavailableReason).toBeUndefined();
  });

  // Acceptance row 5: nvidia-smi absent — VRAM and GPU null-with-reason, other four normal.
  test("row 5: a null GPU snapshot nulls only vram+gpu with a stated reason", () => {
    const poller = createHostTelemetryPoller({ readers: fakeReaders() });
    poller.pollOnce();
    poller.pushGpuSample(null);
    const snapshot = poller.snapshot();
    expect(snapshot.vram.values).toEqual([null]);
    expect(snapshot.gpu.values).toEqual([null]);
    expect(snapshot.vram.unavailableReason).toBe("nvidia-smi unavailable");
    expect(snapshot.gpu.unavailableReason).toBe("nvidia-smi unavailable");
    // The other four are unaffected.
    expect(snapshot.memory.values).toEqual([1.5]);
    expect(snapshot.ram.values).toEqual([20]);
    expect(snapshot.cpu.values).toEqual([33]);
    expect(snapshot.disk.values).toEqual([61]);
  });

  test("a real GPU snapshot routes vram GiB and util % from the existing poller", () => {
    const poller = createHostTelemetryPoller({ readers: fakeReaders() });
    poller.pushGpuSample(gpuSnapshot);
    const snapshot = poller.snapshot();
    expect(snapshot.vram.values).toEqual([18]);
    expect(snapshot.gpu.values).toEqual([42]);
    expect(snapshot.vram.unavailableReason).toBeUndefined();
  });

  // Null-never-zero: a throwing reader records null-with-reason, isolated to its own metric.
  test("a throwing reader nulls only its own metric, never zero, never the others", () => {
    const poller = createHostTelemetryPoller({
      readers: fakeReaders({ disk: () => { throw new Error("statfs unsupported"); } }),
    });
    poller.pollOnce();
    const snapshot = poller.snapshot();
    expect(snapshot.disk.values).toEqual([null]);
    expect(snapshot.disk.unavailableReason).toBe("statfs unsupported");
    expect(snapshot.memory.values).toEqual([1.5]); // isolation: the rest kept rendering
    expect(snapshot.cpu.values).toEqual([33]);
  });

  // Acceptance row 6: a metric read of 0 is a reading, not unavailable.
  test("row 6: a 0 reading is stored as 0, distinct from null", () => {
    const poller = createHostTelemetryPoller({ readers: fakeReaders({ cpu: () => 0 }) });
    poller.pollOnce();
    const snapshot = poller.snapshot();
    expect(snapshot.cpu.values).toEqual([0]);
    expect(snapshot.cpu.unavailableReason).toBeUndefined();
  });

  // Acceptance row 7: stop() leaves no interval alive (and this module spawns no child).
  test("row 7: start establishes one interval and stop clears it", () => {
    let established = 0;
    let cleared = 0;
    const poller = createHostTelemetryPoller({
      readers: fakeReaders(),
      setIntervalFn: ((fn: () => void, ms: number) => { established += 1; return setInterval(fn, ms); }) as typeof setInterval,
      clearIntervalFn: ((id: Parameters<typeof clearInterval>[0]) => { cleared += 1; clearInterval(id); }) as typeof clearInterval,
    });
    poller.start();
    expect(poller.isRunning()).toBe(true);
    expect(established).toBe(1);
    poller.stop();
    expect(poller.isRunning()).toBe(false);
    expect(cleared).toBe(1);
    poller.stop(); // idempotent — no double-clear
    expect(cleared).toBe(1);
  });

  // Skip-path S3: the first poll fails before any interval is established.
  test("S3: a first-poll failure records nulls and start still establishes the interval", () => {
    const poller = createHostTelemetryPoller({
      readers: {
        memory: () => { throw new Error("boom"); },
        ram: () => { throw new Error("boom"); },
        cpu: () => { throw new Error("boom"); },
        disk: () => { throw new Error("boom"); },
      },
    });
    expect(() => poller.start()).not.toThrow();
    expect(poller.isRunning()).toBe(true);
    const snapshot = poller.snapshot();
    expect(snapshot.memory.values).toEqual([null]);
    expect(snapshot.memory.unavailableReason).toBe("boom");
    poller.stop();
    expect(poller.isRunning()).toBe(false);
  });

  test("ring buffer caps at capacity, oldest evicted first", () => {
    let tick = 0;
    const poller = createHostTelemetryPoller({ capacity: 3, readers: fakeReaders({ memory: () => (tick += 1) }) });
    for (let i = 0; i < 5; i++) poller.pollOnce();
    expect(poller.snapshot().memory.values).toEqual([3, 4, 5]);
  });
});
