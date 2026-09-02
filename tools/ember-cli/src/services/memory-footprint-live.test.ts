import { afterEach, describe, expect, test } from "bun:test";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  createLiveMemoryFootprintService,
  loadMemoryFootprintSpecBinding,
} from "./memory-footprint-live.ts";

const roots: string[] = [];
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function fixture(): { repoRoot: string; receiptPath: string } {
  const repoRoot = mkdtempSync(join(tmpdir(), "issue1282-live-"));
  const stateRoot = mkdtempSync(join(tmpdir(), "issue1282-state-"));
  roots.push(repoRoot);
  roots.push(stateRoot);
  const specPath = join(repoRoot, "tools", "ember-cli", "specs", "liveness-watchdog-memory-v1.json");
  mkdirSync(join(repoRoot, "tools", "ember-cli", "specs"), { recursive: true });
  writeFileSync(specPath, JSON.stringify({
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

describe("live memory footprint service", () => {
  test("binds the resident Ember Lab PID into the default process census", async () => {
    const { repoRoot, receiptPath } = fixture();
    let observedOwnedPids: readonly number[] | undefined;
    const service = createLiveMemoryFootprintService({
      repoRoot,
      receiptPath,
      cockpitPid: 41,
      identifyEmberLab: async () => ({
        schema_version: "ember-lab-runtime-identity-v1",
        pid: 77,
      }),
      censusProcessMemory: async (_spec, options) => {
        observedOwnedPids = options.ownedBrainPids;
        return [{ process_class: "cockpit", pid: 41, commit_bytes: 1 }];
      },
    });
    await service.pollOnce();
    expect(observedOwnedPids).toEqual([77]);
  });

  test("keeps the cockpit census bound when resident Ember Lab identity is unavailable", async () => {
    const { repoRoot, receiptPath } = fixture();
    const failures: unknown[] = [];
    let observedOwnedPids: readonly number[] | undefined;
    const service = createLiveMemoryFootprintService({
      repoRoot,
      receiptPath,
      cockpitPid: 41,
      identifyEmberLab: async () => {
        throw new Error("pipe unavailable");
      },
      onOwnershipError: (error) => failures.push(error),
      censusProcessMemory: async (_spec, options) => {
        observedOwnedPids = options.ownedBrainPids;
        return [{ process_class: "cockpit", pid: 41, commit_bytes: 1 }];
      },
    });
    await service.pollOnce();
    expect(observedOwnedPids).toEqual([]);
    expect(failures).toHaveLength(1);
    expect(failures[0]).toBeInstanceOf(Error);
  });

  test("binds the canonical spec bytes and appends one external JSONL trip before request", async () => {
    const { repoRoot, receiptPath } = fixture();
    const binding = loadMemoryFootprintSpecBinding(repoRoot);
    expect(binding.spec_path).toBe("src/ember/infrastructure/tools/ember-cli/specs/liveness-watchdog-memory-v1.json");
    expect(binding.spec_sha256).toMatch(/^[0-9a-f]{64}$/);

    const events: string[] = [];
    const service = createLiveMemoryFootprintService({
      repoRoot,
      receiptPath,
      census: async () => [{ process_class: "cockpit", pid: 71, commit_bytes: 5 }],
      now: () => Date.parse("2026-08-10T23:30:00Z"),
      requestCorrectiveAction: () => {
        expect(readFileSync(receiptPath, "utf8")).toContain('"pid":71');
        events.push("request");
      },
    });
    await service.pollOnce();
    await service.pollOnce();
    await service.pollOnce();

    const rows = readFileSync(receiptPath, "utf8").trim().split("\n").map((line) => JSON.parse(line));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      schema_version: "ember-memory-footprint-trip-v1",
      pid: 71,
      spec_path: binding.spec_path,
      spec_sha256: binding.spec_sha256,
      action: "exit_cockpit_for_task_scheduler",
    });
    expect(events).toEqual(["request"]);
  });

  test("refuses a missing or malformed canonical spec before creating a receipt writer", () => {
    const { repoRoot, receiptPath } = fixture();
    writeFileSync(join(repoRoot, "tools", "ember-cli", "specs", "liveness-watchdog-memory-v1.json"), "{}\n");
    expect(() => createLiveMemoryFootprintService({ repoRoot, receiptPath })).toThrow(
      "MEMORY_FOOTPRINT_SPEC_PROPERTIES_INVALID",
    );
    expect(() => readFileSync(receiptPath)).toThrow();
  });

  test("refuses an in-checkout receipt path before polling", () => {
    const { repoRoot } = fixture();
    expect(() => createLiveMemoryFootprintService({
      repoRoot,
      receiptPath: join(repoRoot, "state", "memory-footprint-trips.jsonl"),
    })).toThrow("MEMORY_FOOTPRINT_RECEIPT_PATH_IN_CHECKOUT");
  });
});
