import { describe, expect, test } from "bun:test";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import {
  createMemoryFootprintService,
  type MemoryFootprintServiceSpecBinding,
} from "./memory-footprint-service.ts";

const binding: MemoryFootprintServiceSpecBinding = {
  spec_path: "src/ember/infrastructure/tools/ember-cli/specs/liveness-watchdog-memory-v1.json",
  spec_sha256: "a".repeat(64),
  spec: {
    schema_version: "ember-liveness-watchdog-memory-v1",
    goal_id: "EMBER-02",
    workstream_id: "EMBER-02A",
    next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    classes: {
      cockpit: {
        soft_bytes: 2,
        hard_bytes: 4,
        consecutive_hard_polls: 3,
        process_names: ["ember"],
      },
      brain_server: {
        soft_bytes: 12,
        hard_bytes: 14,
        consecutive_hard_polls: 3,
        process_names: ["ember-lab"],
      },
    },
  },
};

describe("memory footprint service", () => {
  test("polls live census and persists the spec-bound receipt before restart request", async () => {
    const events: string[] = [];
    const service = createMemoryFootprintService({
      binding,
      census: async () => [{ process_class: "cockpit", pid: 41, commit_bytes: 5 }],
      appendReceipt: (receipt) => {
        expect(receipt.spec_path).toBe(binding.spec_path);
        expect(receipt.spec_sha256).toBe(binding.spec_sha256);
        events.push(`receipt:${receipt.pid}`);
      },
      requestCorrectiveAction: (receipt) => events.push(`request:${receipt.action}:${receipt.pid}`),
      now: () => Date.parse("2026-08-10T23:00:00Z"),
    });

    await service.pollOnce();
    await service.pollOnce();
    await service.pollOnce();
    expect(events).toEqual([
      "receipt:41",
      "request:exit_cockpit_for_task_scheduler:41",
    ]);
  });

  test("does not overlap slow census polls", async () => {
    let release!: () => void;
    const blocked = new Promise<void>((resolve) => { release = resolve; });
    let calls = 0;
    const service = createMemoryFootprintService({
      binding,
      census: async () => {
        calls += 1;
        await blocked;
        return [];
      },
      appendReceipt: () => undefined,
    });
    const first = service.pollOnce();
    await service.pollOnce();
    expect(calls).toBe(1);
    release();
    await first;
  });

  test("a receipt failure prevents the corrective request and permits a later retry", async () => {
    let writes = 0;
    let requests = 0;
    const service = createMemoryFootprintService({
      binding,
      census: async () => [{ process_class: "brain_server", pid: 51, commit_bytes: 15 }],
      appendReceipt: () => {
        writes += 1;
        if (writes === 1) throw new Error("disk full");
      },
      requestCorrectiveAction: () => { requests += 1; },
    });
    await service.pollOnce();
    await service.pollOnce();
    await expect(service.pollOnce()).rejects.toThrow("disk full");
    expect(requests).toBe(0);
    await service.pollOnce();
    expect(requests).toBe(1);
  });

  test("scheduled census failures are contained and reported without an unhandled rejection", async () => {
    const errors: string[] = [];
    let scheduled: (() => void) | undefined;
    const service = createMemoryFootprintService({
      binding,
      census: async () => { throw new Error("census denied"); },
      appendReceipt: () => undefined,
      onPollError: (error) => errors.push(error instanceof Error ? error.message : String(error)),
      setIntervalFn: ((callback: () => void) => {
        scheduled = callback;
        return 1 as unknown as ReturnType<typeof setInterval>;
      }) as typeof setInterval,
      clearIntervalFn: (() => undefined) as typeof clearInterval,
    });
    service.start();
    await Bun.sleep(0);
    expect(errors).toEqual(["census denied"]);
    scheduled?.();
    await Bun.sleep(0);
    expect(errors).toEqual(["census denied", "census denied"]);
    service.stop();
  });

  test("an absent process resets debounce before a recycled pid can trip", async () => {
    const batches = [
      [{ process_class: "cockpit" as const, pid: 61, commit_bytes: 5 }],
      [{ process_class: "cockpit" as const, pid: 61, commit_bytes: 5 }],
      [],
      [{ process_class: "cockpit" as const, pid: 61, commit_bytes: 5 }],
    ];
    const receipts: number[] = [];
    const service = createMemoryFootprintService({
      binding,
      census: async () => batches.shift() ?? [],
      appendReceipt: (receipt) => receipts.push(receipt.pid),
    });
    await service.pollOnce();
    await service.pollOnce();
    await service.pollOnce();
    await service.pollOnce();
    expect(receipts).toEqual([]);
  });
});
