import { afterEach, describe, expect, test } from "bun:test";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  sealIssue1455TerminalExitObservation,
  verifyIssue1455MemoryReceipt,
  writeIssue1455MemoryReceipt,
  type Issue1455MemoryReceiptInput,
} from "./issue1455-memory-soak-receipt.ts";

const roots: string[] = [];
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

const SOURCE_COMMIT = "fdf12f72bef79ede8d9a7c1446df035be2d75e85";
const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);
const MIB = 1024 ** 2;

function incident() {
  return {
    provider: "Microsoft-Windows-Resource-Exhaustion-Detector" as const,
    event_id: 2004 as const,
    observed_local: "2026-08-05T02:01:10-07:00" as const,
    process_name: "Ember.exe" as const,
    pid: 48660 as const,
    commit_bytes: 69_208_911_872 as const,
  };
}

function idleInput(): Issue1455MemoryReceiptInput {
  const start = Date.parse("2026-08-12T04:00:00Z");
  return {
    schema_version: "ember-issue1455-memory-evidence-input-v1",
    evidence_kind: "idle_soak",
    incident: incident(),
    source: {
      source_commit: SOURCE_COMMIT,
      cockpit_binary_sha256: SHA_B,
      memory_spec_path: "tools/ember-cli/specs/liveness-watchdog-memory-v1.json",
      memory_spec_sha256: SHA_A,
    },
    cockpit_pid: 5100,
    sample_interval_seconds: 60,
    samples: Array.from({ length: 121 }, (_, index) => ({
      ts: new Date(start + index * 60_000).toISOString(),
      commit_bytes: 700 * MIB + index * MIB,
      working_set_bytes: 600 * MIB + index * MIB,
    })),
  };
}

function exitObservation(overrides: Record<string, unknown> = {}) {
  return sealIssue1455TerminalExitObservation({
    schema_version: "ember-process-terminal-observation-v1",
    observer: "wait_for_single_object+get_exit_code_process",
    pid: 5100,
    process_start_time: "2026-08-12T06:00:00.000Z",
    observed_at: "2026-08-12T06:30:01.000Z",
    exit_code: 75,
    ...overrides,
  });
}

describe("issue #1455 memory evidence receipt", () => {
  test("writes a self-hashed incident-bound idle candidate without execution credit", () => {
    const root = mkdtempSync(join(tmpdir(), "issue1455-receipt-"));
    roots.push(root);
    const output = join(root, "idle-soak.json");
    const receipt = writeIssue1455MemoryReceipt(output, idleInput());

    expect(receipt).toMatchObject({
      schema_version: "ember-issue1455-memory-evidence-v1",
      evidence_kind: "idle_soak",
      verdict: "NEEDS_EXECUTION",
      duration_seconds: 7200,
      sample_count: 121,
      max_commit_growth_bytes: 120 * MIB,
      max_working_set_growth_bytes: 120 * MIB,
      growth_ceiling_bytes: 256 * MIB,
      incident: incident(),
    });
    expect(receipt.receipt_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(JSON.stringify(receipt)).not.toContain('"verdict":"PASS"');
    expect(JSON.parse(readFileSync(output, "utf8"))).toEqual(receipt);
    expect(verifyIssue1455MemoryReceipt(readFileSync(output, "utf8"))).toEqual(receipt);
    expect(() => writeIssue1455MemoryReceipt(output, idleInput())).toThrow(
      "ISSUE1455_RECEIPT_EXISTS",
    );
  });

  test("rederives the receipt and refuses a tampered persisted sample", () => {
    const root = mkdtempSync(join(tmpdir(), "issue1455-tamper-"));
    roots.push(root);
    const output = join(root, "idle-soak.json");
    writeIssue1455MemoryReceipt(output, idleInput());
    const tampered = JSON.parse(readFileSync(output, "utf8"));
    tampered.samples[60].commit_bytes += 1;
    expect(() => verifyIssue1455MemoryReceipt(JSON.stringify(tampered))).toThrow(
      "ISSUE1455_RECEIPT_SHA256_INVALID",
    );
  });

  test("refuses a short, sparse, growing, or incident-detached idle soak", () => {
    const base = idleInput();
    const cases: Issue1455MemoryReceiptInput[] = [
      { ...base, samples: base.samples.slice(0, -1) },
      { ...base, samples: base.samples.filter((_row, index) => index !== 60) },
      {
        ...base,
        samples: base.samples.map((row, index) => ({
          ...row,
          commit_bytes: row.commit_bytes + index * 3 * MIB,
        })),
      },
      { ...base, incident: { ...base.incident, commit_bytes: 69_208_911_871 } },
    ];
    for (const [index, candidate] of cases.entries()) {
      const root = mkdtempSync(join(tmpdir(), `issue1455-refuse-${index}-`));
      roots.push(root);
      expect(() => writeIssue1455MemoryReceipt(join(root, "receipt.json"), candidate)).toThrow();
    }
  });

  test("binds an injected trip to the same reported process lifetime", () => {
    const root = mkdtempSync(join(tmpdir(), "issue1455-injected-"));
    roots.push(root);
    const output = join(root, "injected.json");
    const receipt = writeIssue1455MemoryReceipt(output, {
      schema_version: "ember-issue1455-memory-evidence-input-v1",
      evidence_kind: "injected_growth",
      incident: incident(),
      source: {
        source_commit: SOURCE_COMMIT,
        cockpit_binary_sha256: SHA_B,
        memory_spec_path: "tools/ember-cli/specs/liveness-watchdog-memory-v1.json",
        memory_spec_sha256: SHA_A,
      },
      cockpit_pid: 5100,
      injected_commit_bytes: 4.5 * 1024 ** 3,
      expected_exit_code: 75,
      observed_exit_code: 75,
      process_start_time: "2026-08-12T06:00:00.000Z",
      exit_observation: exitObservation(),
      trip_receipt: {
        schema_version: "ember-memory-footprint-trip-v1",
        ts: "2026-08-12T06:30:00.000Z",
        pid: 5100,
        process_class: "cockpit",
        commit_gb: 4.5,
        threshold: 4,
        action: "exit_cockpit_for_task_scheduler",
        spec_path: "tools/ember-cli/specs/liveness-watchdog-memory-v1.json",
        spec_sha256: SHA_A,
      },
    });
    expect(receipt).toMatchObject({
      evidence_kind: "injected_growth",
      verdict: "NEEDS_EXECUTION",
      observed_exit_code: 75,
      trip_precedes_exit_observation: true,
      process_start_time: "2026-08-12T06:00:00.000Z",
      incident: incident(),
    });
    expect(JSON.stringify(receipt)).not.toContain('"verdict":"PASS"');
  });

  test("refuses a forged injected trip, wrong pid, or non-clean exit", () => {
    const valid = {
      schema_version: "ember-issue1455-memory-evidence-input-v1" as const,
      evidence_kind: "injected_growth" as const,
      incident: incident(),
      source: {
        source_commit: SOURCE_COMMIT,
        cockpit_binary_sha256: SHA_B,
        memory_spec_path: "tools/ember-cli/specs/liveness-watchdog-memory-v1.json" as const,
        memory_spec_sha256: SHA_A,
      },
      cockpit_pid: 5100,
      injected_commit_bytes: 4.5 * 1024 ** 3,
      expected_exit_code: 75 as const,
      observed_exit_code: 75,
      process_start_time: "2026-08-12T06:00:00.000Z",
      exit_observation: exitObservation(),
      trip_receipt: {
        schema_version: "ember-memory-footprint-trip-v1" as const,
        ts: "2026-08-12T06:30:00.000Z",
        pid: 5100,
        process_class: "cockpit" as const,
        commit_gb: 4.5,
        threshold: 4,
        action: "exit_cockpit_for_task_scheduler" as const,
        spec_path: "tools/ember-cli/specs/liveness-watchdog-memory-v1.json" as const,
        spec_sha256: SHA_A,
      },
    };
    for (const [index, candidate] of [
      { ...valid, observed_exit_code: 1 },
      { ...valid, trip_receipt: { ...valid.trip_receipt, pid: 5101 } },
      { ...valid, trip_receipt: { ...valid.trip_receipt, spec_sha256: SHA_B } },
      { ...valid, source: { ...valid.source, source_commit: SHA_A } },
      {
        ...valid,
        exit_observation: exitObservation({ pid: 5101 }),
      },
      {
        ...valid,
        exit_observation: exitObservation({ observed_at: "2026-08-12T06:29:59.000Z" }),
      },
      {
        ...valid,
        trip_receipt: { ...valid.trip_receipt, ts: "2026-08-12T05:59:59.000Z" },
      },
    ].entries()) {
      const root = mkdtempSync(join(tmpdir(), `issue1455-injected-refuse-${index}-`));
      roots.push(root);
      expect(() => writeIssue1455MemoryReceipt(join(root, "receipt.json"), candidate)).toThrow();
    }
  });
});
