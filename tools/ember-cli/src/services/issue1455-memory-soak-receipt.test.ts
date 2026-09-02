import { afterEach, describe, expect, test } from "bun:test";
import Ajv2020 from "ajv/dist/2020";

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  buildIssue1455MemoryReceipt,
  sealIssue1455TerminalExitObservation,
  verifyIssue1455MemoryReceipt,
  writeIssue1455MemoryReceipt,
  type Issue1455MemoryReceiptInput,
  type Issue1455MemorySample,
} from "./issue1455-memory-soak-receipt.ts";
import receiptSchema from "../../specs/issue1455-memory-evidence-v1.schema.json";

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
      memory_spec_path: "src/ember/infrastructure/tools/ember-cli/specs/liveness-watchdog-memory-v1.json",
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

// Verbatim bytes from a real #1455 idle-soak capture (see issue #1704 for
// provenance), samples for cockpit pid 35436 captured *after* the pre-soak
// EMBER-EXITED restart noise. Real 5-minute-cadence idle-soak evidence,
// embedded as a literal so the test stays hermetic (issue #1704).
const REAL_5MIN_CADENCE_JSONL = `
{"target_pid":35436,"private_mib":803.8,"ws_mib":542.1,"ts":"2026-08-13T00:35:24Z"}
{"target_pid":35436,"private_mib":1182.4,"ws_mib":933.7,"ts":"2026-08-13T00:40:25Z"}
{"target_pid":35436,"private_mib":1589.6,"ws_mib":1338.4,"ts":"2026-08-13T00:45:25Z"}
{"target_pid":35436,"private_mib":2012.2,"ws_mib":1754.3,"ts":"2026-08-13T00:50:26Z"}
{"target_pid":35436,"private_mib":2447.7,"ws_mib":2178,"ts":"2026-08-13T00:55:27Z"}
{"target_pid":35436,"private_mib":2912.6,"ws_mib":2625.1,"ts":"2026-08-13T01:00:28Z"}
{"target_pid":35436,"private_mib":3398.4,"ws_mib":3122.5,"ts":"2026-08-13T01:05:29Z"}
{"target_pid":35436,"private_mib":3978.7,"ws_mib":3662.4,"ts":"2026-08-13T01:10:30Z"}
{"target_pid":35436,"private_mib":4464.1,"ws_mib":4147.9,"ts":"2026-08-13T01:15:31Z"}
{"target_pid":35436,"private_mib":5023.6,"ws_mib":4707.9,"ts":"2026-08-13T01:20:32Z"}
{"target_pid":35436,"private_mib":5552.4,"ws_mib":5200.7,"ts":"2026-08-13T01:25:32Z"}
{"target_pid":35436,"private_mib":6082.9,"ws_mib":5742.1,"ts":"2026-08-13T01:30:33Z"}
{"target_pid":35436,"private_mib":6513.6,"ws_mib":6179.2,"ts":"2026-08-13T01:35:34Z"}
{"target_pid":35436,"private_mib":6831.7,"ws_mib":6517.8,"ts":"2026-08-13T01:40:34Z"}
{"target_pid":35436,"private_mib":7193.4,"ws_mib":6865.9,"ts":"2026-08-13T01:45:34Z"}
{"target_pid":35436,"private_mib":7704.1,"ws_mib":7353.2,"ts":"2026-08-13T01:50:35Z"}
{"target_pid":35436,"private_mib":8106.3,"ws_mib":7735.6,"ts":"2026-08-13T01:55:35Z"}
{"target_pid":35436,"private_mib":8615.6,"ws_mib":8174.2,"ts":"2026-08-13T02:00:35Z"}
{"target_pid":35436,"private_mib":9209.4,"ws_mib":8631.5,"ts":"2026-08-13T02:05:36Z"}
{"target_pid":35436,"private_mib":9824.9,"ws_mib":9099.4,"ts":"2026-08-13T02:10:36Z"}
{"target_pid":35436,"private_mib":10532.8,"ws_mib":9680.9,"ts":"2026-08-13T02:15:36Z"}
{"target_pid":35436,"private_mib":11182.8,"ws_mib":10227,"ts":"2026-08-13T02:20:37Z"}
{"target_pid":35436,"private_mib":11821,"ws_mib":10696.5,"ts":"2026-08-13T02:25:37Z"}
{"target_pid":35436,"private_mib":12351,"ws_mib":11118.3,"ts":"2026-08-13T02:30:37Z"}
{"target_pid":35436,"private_mib":12976.9,"ws_mib":11569.6,"ts":"2026-08-13T02:35:38Z"}
`;

function parseRealCadenceJsonl(jsonl: string): Issue1455MemorySample[] {
  return jsonl
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as { target_pid: number; private_mib: number; ws_mib: number; ts: string })
    .map((row) => ({
      ts: row.ts.replace("Z", ".000Z"),
      commit_bytes: Math.round(row.private_mib * MIB),
      working_set_bytes: Math.round(row.ws_mib * MIB),
    }));
}

function real5MinCadenceIdleInput(
  overrides: Partial<{ sample_interval_seconds: number; samples: Issue1455MemorySample[] }> = {},
): Issue1455MemoryReceiptInput {
  return {
    schema_version: "ember-issue1455-memory-evidence-input-v1",
    evidence_kind: "idle_soak",
    incident: incident(),
    source: {
      source_commit: SOURCE_COMMIT,
      cockpit_binary_sha256: SHA_B,
      memory_spec_path: "src/ember/infrastructure/tools/ember-cli/specs/liveness-watchdog-memory-v1.json",
      memory_spec_sha256: SHA_A,
    },
    cockpit_pid: 35436,
    sample_interval_seconds: 300,
    samples: parseRealCadenceJsonl(REAL_5MIN_CADENCE_JSONL),
    ...overrides,
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
        memory_spec_path: "src/ember/infrastructure/tools/ember-cli/specs/liveness-watchdog-memory-v1.json",
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
        spec_path: "src/ember/infrastructure/tools/ember-cli/specs/liveness-watchdog-memory-v1.json",
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
    const validate = new Ajv2020({ strict: false }).compile(receiptSchema);
    expect(validate(receipt)).toBe(true);
    expect(validate({ ...receipt, min_commit_bytes: 0 })).toBe(false);
  });

  test("refuses a forged injected trip, wrong pid, or non-clean exit", () => {
    const valid = {
      schema_version: "ember-issue1455-memory-evidence-input-v1" as const,
      evidence_kind: "injected_growth" as const,
      incident: incident(),
      source: {
        source_commit: SOURCE_COMMIT,
        cockpit_binary_sha256: SHA_B,
        memory_spec_path: "src/ember/infrastructure/tools/ember-cli/specs/liveness-watchdog-memory-v1.json" as const,
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
        spec_path: "src/ember/infrastructure/tools/ember-cli/specs/liveness-watchdog-memory-v1.json" as const,
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

  describe("issue #1704 cadence-tolerant idle soak", () => {
    test("accepts a genuine 5-minute-cadence soak and reflects the real interval, not a hardcoded 60s", () => {
      const realSamples = parseRealCadenceJsonl(REAL_5MIN_CADENCE_JSONL);
      const start = realSamples[0]!.commit_bytes;
      // Real 5-minute-spaced timestamps, synthetic in-ceiling byte values --
      // isolates the cadence fix from the fixture's real ~12GB growth (that
      // growth is genuine #1455 leak evidence and belongs in the refusal
      // test below, not a "does cadence work" test).
      const samples: Issue1455MemorySample[] = realSamples.map((sample, index) => ({
        ts: sample.ts,
        commit_bytes: start + index * MIB,
        working_set_bytes: start + index * MIB,
      }));
      const receipt = buildIssue1455MemoryReceipt(real5MinCadenceIdleInput({ samples }));
      expect(receipt).toMatchObject({
        evidence_kind: "idle_soak",
        sample_interval_seconds: 300,
        sample_count: 25,
      });
      const validate = new Ajv2020({ strict: false }).compile(receiptSchema);
      expect(validate(receipt)).toBe(true);
    });

    test("refuses the real 2h/5-min-cadence #1455 fixture on the growth ceiling, not on cadence", () => {
      expect(() => buildIssue1455MemoryReceipt(real5MinCadenceIdleInput())).toThrow(
        "ISSUE1455_IDLE_GROWTH_EXCEEDED",
      );
    });

    test("refuses a declared interval that does not match the real sample spacing", () => {
      expect(() =>
        buildIssue1455MemoryReceipt(real5MinCadenceIdleInput({ sample_interval_seconds: 60 })),
      ).toThrow("ISSUE1455_IDLE_CADENCE_INVALID");
    });

    test("refuses a declared cadence with a gap stretched outside tolerance", () => {
      const samples = parseRealCadenceJsonl(REAL_5MIN_CADENCE_JSONL);
      const stretched = samples.map((sample, index) =>
        index === 10
          ? { ...sample, ts: new Date(Date.parse(sample.ts) + 20 * 60_000).toISOString() }
          : sample,
      );
      expect(() => buildIssue1455MemoryReceipt(real5MinCadenceIdleInput({ samples: stretched }))).toThrow(
        "ISSUE1455_IDLE_CADENCE_INVALID",
      );
    });

    test("refuses a cadence below the sample-count floor implied by the declared interval", () => {
      const samples = parseRealCadenceJsonl(REAL_5MIN_CADENCE_JSONL).slice(0, -1);
      expect(() => buildIssue1455MemoryReceipt(real5MinCadenceIdleInput({ samples }))).toThrow(
        "ISSUE1455_IDLE_CADENCE_INVALID",
      );
    });
  });
});
