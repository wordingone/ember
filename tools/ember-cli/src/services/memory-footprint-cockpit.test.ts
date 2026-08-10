import { afterEach, describe, expect, test } from "bun:test";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createCockpitMemoryFootprintSupervisor } from "./memory-footprint-cockpit.ts";

const roots: string[] = [];
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function fixture() {
  const repoRoot = mkdtempSync(join(tmpdir(), "issue1282-cockpit-"));
  const stateRoot = mkdtempSync(join(tmpdir(), "issue1282-cockpit-state-"));
  roots.push(repoRoot, stateRoot);
  const dir = join(repoRoot, "tools", "ember-cli", "specs");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "liveness-watchdog-memory-v1.json"), JSON.stringify({
    schema_version: "ember-liveness-watchdog-memory-v1",
    goal_id: "EMBER-02",
    workstream_id: "EMBER-02A",
    next_executed_outcome: "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    classes: {
      cockpit: { soft_bytes: 2, hard_bytes: 4, consecutive_hard_polls: 3, process_names: ["ember"] },
      brain_server: { soft_bytes: 12, hard_bytes: 14, consecutive_hard_polls: 3, process_names: ["ember-lab"] },
    },
  }));
  return { repoRoot, receiptPath: join(stateRoot, "memory-footprint-trips.jsonl") };
}

describe("cockpit memory footprint supervisor", () => {
  test("requests current cockpit failure only after its external trip receipt", async () => {
    const { repoRoot, receiptPath } = fixture();
    const exits: number[] = [];
    const warnings: string[] = [];
    const service = createCockpitMemoryFootprintSupervisor({
      repoRoot,
      receiptPath,
      currentPid: 81,
      census: async () => [{ process_class: "cockpit", pid: 81, commit_bytes: 5 }],
      exitCockpit: (code) => exits.push(code),
      warn: (message) => warnings.push(message),
    });
    await service.pollOnce();
    await service.pollOnce();
    expect(exits).toEqual([]);
    await service.pollOnce();
    expect(exits).toEqual([75]);
    expect(warnings[0]).toContain("Task Scheduler restart-on-failure");
  });

  test("never exits for a foreign cockpit pid and routes brain server to Ember Lab request", async () => {
    const { repoRoot, receiptPath } = fixture();
    const exits: number[] = [];
    const requests: number[] = [];
    const samples = [
      { process_class: "cockpit" as const, pid: 82, commit_bytes: 5 },
      { process_class: "brain_server" as const, pid: 83, commit_bytes: 15 },
    ];
    const service = createCockpitMemoryFootprintSupervisor({
      repoRoot,
      receiptPath,
      currentPid: 81,
      census: async () => samples,
      exitCockpit: (code) => exits.push(code),
      requestEmberLabRestart: (pid) => requests.push(pid),
      warn: () => undefined,
    });
    await service.pollOnce();
    await service.pollOnce();
    await service.pollOnce();
    expect(exits).toEqual([]);
    expect(requests).toEqual([83]);
  });

  test("records a truthful pending-owner warning when no Ember Lab callback is installed", async () => {
    const { repoRoot, receiptPath } = fixture();
    const warnings: string[] = [];
    const service = createCockpitMemoryFootprintSupervisor({
      repoRoot,
      receiptPath,
      currentPid: 81,
      census: async () => [
        { process_class: "brain_server", pid: 84, commit_bytes: 15 },
      ],
      warn: (message) => warnings.push(message),
    });
    await service.pollOnce();
    await service.pollOnce();
    await service.pollOnce();
    expect(warnings).toEqual([
      expect.stringContaining("restart remains pending with the Ember Lab owner"),
    ]);
  });
});
