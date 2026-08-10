import { describe, expect, test } from "bun:test";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import {
  createMemoryFootprintGovernor,
  type MemoryFootprintSpec,
} from "./memory-footprint-governor.ts";

const GIB = 1024 ** 3;

const spec: MemoryFootprintSpec = {
  schema_version: "ember-liveness-watchdog-memory-v1",
  goal_id: "EMBER-02",
  workstream_id: "EMBER-02A",
  next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
  classes: {
    cockpit: {
      soft_bytes: 2 * GIB,
      hard_bytes: 4 * GIB,
      consecutive_hard_polls: 3,
      process_names: ["ember"],
    },
    brain_server: {
      soft_bytes: 12.5 * GIB,
      hard_bytes: 14 * GIB,
      consecutive_hard_polls: 3,
      process_names: ["ember-lab", "brain-server"],
    },
  },
};

describe("memory footprint governor", () => {
  test("three consecutive hard polls write a receipt before corrective action", () => {
    const events: string[] = [];
    const governor = createMemoryFootprintGovernor({
      spec,
      now: () => Date.parse("2026-08-10T20:00:00Z"),
      writeReceipt: (receipt) => {
        events.push(`receipt:${receipt.pid}`);
        expect(receipt).toMatchObject({
          schema_version: "ember-memory-footprint-trip-v1",
          ts: "2026-08-10T20:00:00.000Z",
          pid: 4242,
          commit_gb: 4.5,
          threshold: 4,
          action: "exit_cockpit_for_task_scheduler",
          process_class: "cockpit",
        });
      },
      correctiveAction: (receipt) => events.push(`action:${receipt.pid}`),
    });

    expect(governor.observe({ process_class: "cockpit", pid: 4242, commit_bytes: 4.5 * GIB }).state).toBe("hard_debouncing");
    expect(governor.observe({ process_class: "cockpit", pid: 4242, commit_bytes: 4.5 * GIB }).state).toBe("hard_debouncing");
    expect(governor.observe({ process_class: "cockpit", pid: 4242, commit_bytes: 4.5 * GIB }).state).toBe("tripped");
    expect(events).toEqual(["receipt:4242", "action:4242"]);
  });

  test("below-hard poll resets debounce and below-soft never trips", () => {
    const events: string[] = [];
    const governor = createMemoryFootprintGovernor({
      spec,
      writeReceipt: () => events.push("receipt"),
      correctiveAction: () => events.push("action"),
    });

    expect(governor.observe({ process_class: "cockpit", pid: 7, commit_bytes: 1.5 * GIB }).state).toBe("below_soft");
    governor.observe({ process_class: "cockpit", pid: 7, commit_bytes: 4.5 * GIB });
    governor.observe({ process_class: "cockpit", pid: 7, commit_bytes: 4.5 * GIB });
    expect(governor.observe({ process_class: "cockpit", pid: 7, commit_bytes: 3 * GIB }).state).toBe("soft");
    expect(governor.observe({ process_class: "cockpit", pid: 7, commit_bytes: 4.5 * GIB }).consecutive_hard_polls).toBe(1);
    expect(events).toEqual([]);
  });

  test("debounce is isolated by process class and pid", () => {
    const receipts: number[] = [];
    const governor = createMemoryFootprintGovernor({
      spec,
      writeReceipt: (receipt) => receipts.push(receipt.pid),
    });
    for (let i = 0; i < 2; i += 1) {
      governor.observe({ process_class: "cockpit", pid: 1, commit_bytes: 5 * GIB });
      governor.observe({ process_class: "brain_server", pid: 2, commit_bytes: 15 * GIB });
    }
    expect(governor.observe({ process_class: "brain_server", pid: 2, commit_bytes: 15 * GIB }).state).toBe("tripped");
    expect(receipts).toEqual([2]);
    expect(governor.observe({ process_class: "cockpit", pid: 1, commit_bytes: 5 * GIB }).state).toBe("tripped");
    expect(receipts).toEqual([2, 1]);
  });

  test("a receipt-write failure blocks corrective action", () => {
    let actions = 0;
    const governor = createMemoryFootprintGovernor({
      spec,
      writeReceipt: () => { throw new Error("receipt disk unavailable"); },
      correctiveAction: () => { actions += 1; },
    });
    governor.observe({ process_class: "cockpit", pid: 9, commit_bytes: 5 * GIB });
    governor.observe({ process_class: "cockpit", pid: 9, commit_bytes: 5 * GIB });
    expect(() => governor.observe({ process_class: "cockpit", pid: 9, commit_bytes: 5 * GIB })).toThrow(
      "receipt disk unavailable",
    );
    expect(actions).toBe(0);
  });

  test("one hard episode trips once and rearms only below hard", () => {
    const receipts: number[] = [];
    const governor = createMemoryFootprintGovernor({
      spec,
      writeReceipt: (receipt) => receipts.push(receipt.pid),
    });
    for (let i = 0; i < 6; i += 1) {
      governor.observe({ process_class: "cockpit", pid: 11, commit_bytes: 5 * GIB });
    }
    expect(receipts).toEqual([11]);
    governor.observe({ process_class: "cockpit", pid: 11, commit_bytes: 3 * GIB });
    for (let i = 0; i < 3; i += 1) {
      governor.observe({ process_class: "cockpit", pid: 11, commit_bytes: 5 * GIB });
    }
    expect(receipts).toEqual([11, 11]);
  });

  test("refuses authority drift and unknown spec properties", () => {
    expect(() => createMemoryFootprintGovernor({
      spec: { ...spec, goal_id: "EMBER-99" } as MemoryFootprintSpec,
      writeReceipt: () => undefined,
    })).toThrow("MEMORY_FOOTPRINT_SPEC_AUTHORITY_INVALID");
    expect(() => createMemoryFootprintGovernor({
      spec: { ...spec, parallel_authority: true } as unknown as MemoryFootprintSpec,
      writeReceipt: () => undefined,
    })).toThrow("MEMORY_FOOTPRINT_SPEC_PROPERTIES_INVALID");
  });
});
