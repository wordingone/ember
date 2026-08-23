import { describe, expect, test } from "bun:test";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import {
  censusWindowsProcessMemory,
  censusWindowsProcessMemoryBatch,
} from "./process-memory-census.ts";
import type { MemoryFootprintSpec } from "./memory-footprint-governor.ts";

const spec: MemoryFootprintSpec = {
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
      process_names: ["ember-lab", "brain-server"],
    },
  },
};

describe("Windows process memory census", () => {
  test("receipts provider, start tokens, cardinality, and ownership overlaps per poll", async () => {
    const batch = await censusWindowsProcessMemoryBatch(spec, {
      cockpitPid: 11,
      ownedBrainPids: [14],
      observedAt: () => "2026-08-23T17:00:00.000Z",
      runPowerShell: async () => JSON.stringify([
        { Id: 11, ParentProcessId: 1, ProcessName: "ember.exe", PagedMemorySize64: 5, ProcessStartToken: "638915652000000000" },
        { Id: 14, ParentProcessId: 999, ProcessName: "ember-lab.exe", PagedMemorySize64: 16, ProcessStartToken: "638915652010000000" },
        { Id: 16, ParentProcessId: 14, ProcessName: "brain-server.exe", PagedMemorySize64: 17, ProcessStartToken: "638915652020000000" },
        { Id: 17, ParentProcessId: 999, ProcessName: "ember-lab.exe", PagedMemorySize64: 99, ProcessStartToken: "638915652030000000" },
      ]),
    });
    expect(batch).toEqual({
      schema_version: "ember-process-memory-census-poll-v1",
      observed_at: "2026-08-23T17:00:00.000Z",
      provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks",
      candidate_process_count: 4,
      admitted_process_count: 3,
      class_cardinality: { cockpit: 1, brain_server: 2 },
      ownership_overlap: { count: 0, pids: [] },
      samples: [
        { process_class: "cockpit", pid: 11, parent_pid: 1, process_name: "ember", process_start_token: "638915652000000000", provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks", commit_bytes: 5, ownership_basis: ["cockpit_pid"] },
        { process_class: "brain_server", pid: 14, parent_pid: 999, process_name: "ember-lab", process_start_token: "638915652010000000", provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks", commit_bytes: 16, ownership_basis: ["ember_lab_runtime_pid"] },
        { process_class: "brain_server", pid: 16, parent_pid: 14, process_name: "brain-server", process_start_token: "638915652020000000", provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks", commit_bytes: 17, ownership_basis: ["ember_lab_runtime_child"] },
      ],
    });
  });

  test("maps exact configured process names to commit-byte samples", async () => {
    const samples = await censusWindowsProcessMemory(spec, {
      cockpitPid: 11,
      runPowerShell: async () => JSON.stringify([
        { Id: 11, ParentProcessId: 1, ProcessName: "bun", PagedMemorySize64: 5 },
        { Id: 12, ParentProcessId: 11, ProcessName: "EMBER-LAB.exe", PagedMemorySize64: 15 },
        { Id: 13, ParentProcessId: 11, ProcessName: "unrelated", PagedMemorySize64: 99 },
        { Id: 14, ParentProcessId: 999, ProcessName: "ember-lab", PagedMemorySize64: 16 },
      ]),
    });
    expect(samples).toEqual([
      { process_class: "cockpit", pid: 11, commit_bytes: 5 },
      { process_class: "brain_server", pid: 12, commit_bytes: 15 },
    ]);
  });

  test("admits the resident Ember Lab PID even when it is not a cockpit child", async () => {
    const samples = await censusWindowsProcessMemory(spec, {
      cockpitPid: 11,
      ownedBrainPids: [14],
      runPowerShell: async () => JSON.stringify([
        { Id: 11, ParentProcessId: 1, ProcessName: "bun", PagedMemorySize64: 5 },
        { Id: 14, ParentProcessId: 999, ProcessName: "ember-lab.exe", PagedMemorySize64: 16 },
        { Id: 15, ParentProcessId: 999, ProcessName: "ember-lab.exe", PagedMemorySize64: 99 },
      ]),
    });
    expect(samples).toEqual([
      { process_class: "cockpit", pid: 11, commit_bytes: 5 },
      { process_class: "brain_server", pid: 14, commit_bytes: 16 },
    ]);
  });

  test("admits the canonical brain server child of the resident Ember Lab daemon", async () => {
    const samples = await censusWindowsProcessMemory(spec, {
      cockpitPid: 11,
      ownedBrainPids: [14],
      runPowerShell: async () => JSON.stringify([
        { Id: 11, ParentProcessId: 1, ProcessName: "bun", PagedMemorySize64: 5 },
        { Id: 14, ParentProcessId: 999, ProcessName: "ember-lab.exe", PagedMemorySize64: 16 },
        { Id: 16, ParentProcessId: 14, ProcessName: "brain-server.exe", PagedMemorySize64: 17 },
        { Id: 17, ParentProcessId: 999, ProcessName: "brain-server.exe", PagedMemorySize64: 99 },
      ]),
    });
    expect(samples).toEqual([
      { process_class: "cockpit", pid: 11, commit_bytes: 5 },
      { process_class: "brain_server", pid: 14, commit_bytes: 16 },
      { process_class: "brain_server", pid: 16, commit_bytes: 17 },
    ]);
  });

  test("refuses invalid or duplicate resident Ember Lab identities", async () => {
    for (const ownedBrainPids of [[0], [14, 14], [1.5]]) {
      await expect(censusWindowsProcessMemory(spec, {
        cockpitPid: 11,
        ownedBrainPids,
        runPowerShell: async () => "[]",
      })).rejects.toThrow("MEMORY_CENSUS_BRAIN_PID_INVALID");
    }
  });

  test("accepts PowerShell's single-object JSON shape", async () => {
    const samples = await censusWindowsProcessMemory(spec, {
      cockpitPid: 20,
      runPowerShell: async () => JSON.stringify({
        Id: 20,
        ParentProcessId: 1,
        ProcessName: "bun",
        PagedMemorySize64: 17,
      }),
    });
    expect(samples).toEqual([
      { process_class: "cockpit", pid: 20, commit_bytes: 17 },
    ]);
  });

  test("refuses malformed rows and ambiguous configured ownership", async () => {
    await expect(censusWindowsProcessMemory(spec, {
      cockpitPid: 11,
      runPowerShell: async () => JSON.stringify({ Id: "11", ParentProcessId: 1, ProcessName: "ember", PagedMemorySize64: 5 }),
    })).rejects.toThrow("MEMORY_CENSUS_ROW_INVALID");

    const ambiguous: MemoryFootprintSpec = {
      ...spec,
      classes: {
        ...spec.classes,
        brain_server: { ...spec.classes.brain_server, process_names: ["ember.exe"] },
      },
    };
    await expect(censusWindowsProcessMemory(ambiguous, {
      cockpitPid: 11,
      runPowerShell: async () => "[]",
    })).rejects.toThrow("MEMORY_CENSUS_NAME_AMBIGUOUS:ember");
  });

  test("refuses a census with no exact current cockpit identity", async () => {
    await expect(censusWindowsProcessMemory(spec, {
      cockpitPid: 11,
      runPowerShell: async () => JSON.stringify([
        { Id: 99, ParentProcessId: 1, ProcessName: "ember", PagedMemorySize64: 5 },
      ]),
    })).rejects.toThrow("MEMORY_CENSUS_COCKPIT_MISSING:11");
  });

  test("refuses an unreadable owned child but ignores unreadable unrelated processes", async () => {
    await expect(censusWindowsProcessMemory(spec, {
      cockpitPid: 11,
      runPowerShell: async () => JSON.stringify([
        { Id: 11, ParentProcessId: 1, ProcessName: "bun", PagedMemorySize64: 5 },
        { Id: 12, ParentProcessId: 11, ProcessName: "ember-lab", PagedMemorySize64: null },
        { Id: 13, ParentProcessId: 1, ProcessName: "unrelated", PagedMemorySize64: null },
      ]),
    })).rejects.toThrow("MEMORY_CENSUS_COMMIT_UNREADABLE:12");

    await expect(censusWindowsProcessMemory(spec, {
      cockpitPid: 11,
      runPowerShell: async () => JSON.stringify([
        { Id: 11, ParentProcessId: 1, ProcessName: "bun", PagedMemorySize64: 5 },
        { Id: 13, ParentProcessId: 1, ProcessName: "unrelated", PagedMemorySize64: null },
      ]),
    })).resolves.toEqual([{ process_class: "cockpit", pid: 11, commit_bytes: 5 }]);
  });

});
