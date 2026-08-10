import { describe, expect, test } from "bun:test";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { censusWindowsProcessMemory } from "./process-memory-census.ts";
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
