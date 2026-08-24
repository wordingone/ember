// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 renderer/census evidence consumer

import { expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  appendInstalledCockpitSoakPoll,
  createInstalledCockpitSoakLedger,
  sealInstalledCockpitSoak,
} from "./issue898-installed-cockpit-soak.ts";
import {
  sealIssue898RendererCensusEvidence,
  verifyIssue898RendererCensusEvidenceReceipt,
  type Issue898RendererCensusEvidenceBindings,
  type Issue898RendererCensusEvidenceInput,
} from "./issue898-renderer-census-evidence.ts";

const SHA = "a".repeat(64);
const SOURCE = "b".repeat(40);
const COCKPIT_PID = 11;
const KERNEL_TOKEN = "638915652000000000";
const RUNTIME_TOKEN = "638915652000100000";
const DAEMON_PID = 44;
const STARTED_AT_MS = Date.parse("2026-08-24T00:00:00.000Z");

interface EvidenceFixture {
  input: Issue898RendererCensusEvidenceInput;
  bindings: Issue898RendererCensusEvidenceBindings;
}

interface MutablePollFixtureRow {
  schema_version: string;
  sequence: number;
  census: {
    observed_at: string;
    admitted_process_count: number;
    class_cardinality: { cockpit: number; brain_server: number };
    ownership_overlap: { count: number; pids: number[] };
    samples: Array<{
      process_class: string;
      pid: number;
      process_start_token: string;
      commit_bytes: number;
    }>;
  };
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const row = value as Record<string, unknown>;
  return `{${Object.keys(row).sort().map((key) =>
    `${JSON.stringify(key)}:${canonicalJson(row[key])}`
  ).join(",")}}`;
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function rendererRow(sequence: number) {
  const capturedAtMs = STARTED_AT_MS + sequence * 120_000;
  return {
    schema_version: "ember-renderer-diagnostic-v1",
    sequence,
    captured_at: new Date(capturedAtMs).toISOString(),
    captured_at_ms: capturedAtMs,
    source_commit: SOURCE,
    pid: COCKPIT_PID,
    runtime_origin_token: RUNTIME_TOKEN,
    render_calls: sequence * 2,
    render_passes: sequence * 2,
    backpressured_coalesces: 0,
    full_repaints: sequence === 0 ? 1 : 2,
    rendered_frame_utf8_bytes: sequence * 1_000,
    diff_cells: sequence * 10,
    optimized_runs: sequence * 5,
    stream_write_calls: sequence * 2,
    submitted_utf8_bytes: sequence * 100,
    write_false_events: 0,
    drain_repaints: 0,
    style_pool_size: 37,
    hyperlink_pool_size: 0,
  };
}

function createEvidenceFixture(): EvidenceFixture {
  const parent = mkdtempSync(path.join(os.tmpdir(), "issue898-renderer-census-"));
  const armRoot = path.join(parent, "arm");
  mkdirSync(armRoot);
  const soakRoot = path.join(armRoot, "soak");
  const pollsPath = createInstalledCockpitSoakLedger(soakRoot);
  const jobId = "issue898-renderer-census-fixture-sidecar";

  for (let sequence = 0; sequence <= 120; sequence += 1) {
    const observedAtMs = STARTED_AT_MS + sequence * 60_000;
    appendInstalledCockpitSoakPoll(pollsPath, {
      schema_version: "ember-issue898-installed-cockpit-soak-poll-v1",
      sequence,
      census: {
        schema_version: "ember-process-memory-census-poll-v1",
        observed_at: new Date(observedAtMs).toISOString(),
        provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks",
        candidate_process_count: 3,
        admitted_process_count: 2,
        class_cardinality: { cockpit: 1, brain_server: 1 },
        ownership_overlap: { count: 0, pids: [] },
        samples: [
          {
            process_class: "cockpit",
            pid: COCKPIT_PID,
            parent_pid: 1,
            process_name: "ember",
            process_start_token: KERNEL_TOKEN,
            provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks",
            commit_bytes: 1_000_000 + sequence * 10_000,
            ownership_basis: ["cockpit_pid"],
          },
          {
            process_class: "brain_server",
            pid: DAEMON_PID,
            parent_pid: 1,
            process_name: "ember-lab",
            process_start_token: "638915651999000000",
            provider: "win32_process+cim/get-process:paged-memory-size64+start-time-utc-ticks",
            commit_bytes: 2_000_000,
            ownership_basis: ["ember_lab_runtime_pid"],
          },
        ],
      },
      walls: {
        schema_version: "ember-lab-wall-observation-snapshot-v1",
        captured_at_ms: observedAtMs,
        after_vram_seq: sequence,
        after_disk_seq: sequence,
        next_vram_seq: sequence + 1,
        next_disk_seq: sequence + 1,
        daemon_identity: {
          schema_version: "ember-lab-runtime-identity-v1",
          pid: DAEMON_PID,
          binary_sha256: SHA,
          source_sha256: SHA,
        },
        vram_observations: [{
          seq: sequence + 1,
          job_id: jobId,
          observed_at_ms: observedAtMs,
          outcome: "healthy",
          payload: {},
        }],
        disk_observations: [{
          seq: sequence + 1,
          job_id: jobId,
          write_root: "B:\\fixture",
          observed_at_ms: observedAtMs,
          outcome: "healthy",
          payload: { measurement_duration_ms: 1 },
        }],
      },
    });
  }

  const soakReceiptPath = path.join(soakRoot, "soak-receipt.json");
  sealInstalledCockpitSoak({
    raw_ledger_path: pollsPath,
    receipt_path: soakReceiptPath,
    identity: {
      source_commit: SOURCE,
      cockpit_binary_sha256: SHA,
      ember_lab_binary_sha256: SHA,
      ember_lab_source_sha256: SHA,
      cockpit_pid: COCKPIT_PID,
      cockpit_process_start_token: KERNEL_TOKEN,
      sidecar_job_id: jobId,
      sidecar_manifest_sha256: SHA,
    },
    negatives: {
      above_hard_trip: { passed: true, receipt_sha256: SHA },
      below_reset: { passed: true, receipt_sha256: SHA },
      soft_observe: { passed: true, receipt_sha256: SHA },
      foreign_identity_never_controlled: { passed: true, receipt_sha256: SHA },
    },
    poll_interval_seconds: 60,
    receipt_written_at: "2026-08-24T02:00:01.000Z",
    restart_event_count_before_receipt: 0,
  });

  const rendererPath = path.join(armRoot, "renderer.jsonl");
  const rendererText = Array.from({ length: 61 }, (_, sequence) =>
    JSON.stringify(rendererRow(sequence))
  ).join("\n") + "\n";
  writeFileSync(rendererPath, rendererText, { encoding: "utf8", flag: "wx" });

  const outputPath = path.join(parent, "arm-evidence", "renderer-census-receipt.json");
  const input: Issue898RendererCensusEvidenceInput = {
    soakReceiptPath,
    pollsPath,
    rendererPath,
    outputPath,
    sourceCommit: SOURCE,
    cockpitPid: COCKPIT_PID,
    cockpitProcessStartToken: KERNEL_TOKEN,
    receiptWrittenAt: "2026-08-24T02:00:02.000Z",
  };
  return {
    input,
    bindings: {
      soakReceiptText: readFileSync(soakReceiptPath, "utf8"),
      pollsText: readFileSync(pollsPath, "utf8"),
      rendererText,
      sourceCommit: SOURCE,
      cockpitPid: COCKPIT_PID,
      cockpitProcessStartToken: KERNEL_TOKEN,
    },
  };
}

function writeRendererFixture(fixture: EvidenceFixture, rendererText: string): void {
  writeFileSync(fixture.input.rendererPath, rendererText, "utf8");
  fixture.bindings.rendererText = rendererText;
}

function mutateRendererFixture(
  fixture: EvidenceFixture,
  index: number,
  mutate: (row: Record<string, unknown>) => void,
): void {
  const rows = fixture.bindings.rendererText.trimEnd().split("\n")
    .map((line) => JSON.parse(line) as Record<string, unknown>);
  mutate(rows[index]!);
  writeRendererFixture(fixture, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`);
}

function writePollFixture(fixture: EvidenceFixture, pollsText: string): void {
  writeFileSync(fixture.input.pollsPath, pollsText, "utf8");
  const receipt = JSON.parse(readFileSync(fixture.input.soakReceiptPath, "utf8")) as Record<string, unknown>;
  receipt.raw_ledger_sha256 = sha256(pollsText);
  receipt.raw_ledger_bytes = Buffer.byteLength(pollsText);
  delete receipt.receipt_sha256;
  receipt.receipt_sha256 = sha256(canonicalJson(receipt));
  const receiptText = `${JSON.stringify(receipt, null, 2)}\n`;
  writeFileSync(fixture.input.soakReceiptPath, receiptText, "utf8");
  fixture.bindings.pollsText = pollsText;
  fixture.bindings.soakReceiptText = receiptText;
}

function mutatePollFixture(
  fixture: EvidenceFixture,
  index: number,
  mutate: (row: MutablePollFixtureRow) => void,
): void {
  const rows = fixture.bindings.pollsText.trimEnd().split("\n")
    .map((line) => JSON.parse(line) as MutablePollFixtureRow);
  mutate(rows[index]!);
  writePollFixture(fixture, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`);
}

function mutateSoakReceiptFixture(
  fixture: EvidenceFixture,
  mutate: (receipt: Record<string, unknown>) => void,
): void {
  const receipt = JSON.parse(readFileSync(fixture.input.soakReceiptPath, "utf8")) as Record<string, unknown>;
  mutate(receipt);
  delete receipt.receipt_sha256;
  receipt.receipt_sha256 = sha256(canonicalJson(receipt));
  const receiptText = `${JSON.stringify(receipt, null, 2)}\n`;
  writeFileSync(fixture.input.soakReceiptPath, receiptText, "utf8");
  fixture.bindings.soakReceiptText = receiptText;
}

function setRendererRuntimeToken(fixture: EvidenceFixture, token: string): void {
  const rows = fixture.bindings.rendererText.trimEnd().split("\n")
    .map((line) => JSON.parse(line) as Record<string, unknown>);
  for (const row of rows) row.runtime_origin_token = token;
  writeRendererFixture(fixture, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`);
}

function mutateAllRendererRows(
  fixture: EvidenceFixture,
  mutate: (row: Record<string, unknown>, index: number) => void,
): void {
  const rows = fixture.bindings.rendererText.trimEnd().split("\n")
    .map((line) => JSON.parse(line) as Record<string, unknown>);
  rows.forEach(mutate);
  writeRendererFixture(fixture, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`);
}

function clusterPollTimesBeforeFinalRendererRow(fixture: EvidenceFixture): void {
  const rows = fixture.bindings.pollsText.trimEnd().split("\n")
    .map((line) => JSON.parse(line) as MutablePollFixtureRow);
  rows.forEach((row, index) => {
    const offsetMs = index === 0
      ? 0
      : 7_199_000 + Math.floor(((index - 1) * 1_000) / (rows.length - 2));
    row.census.observed_at = new Date(STARTED_AT_MS + offsetMs).toISOString();
  });
  writePollFixture(fixture, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`);
}

function mutateReceiptText(
  text: string,
  mutate: (receipt: Record<string, unknown>) => void,
): string {
  const receipt = JSON.parse(text) as Record<string, unknown>;
  mutate(receipt);
  return `${JSON.stringify(receipt, null, 2)}\n`;
}

test("joins by prior renderer row and retains zero-advance positive-commit intervals", () => {
  const fixture = createEvidenceFixture();
  const receipt = sealIssue898RendererCensusEvidence(fixture.input);

  expect(receipt.schema_version).toBe("ember-issue898-renderer-census-evidence-v1");
  expect(receipt.verdict).toBe("MEASURED_NEEDS_INDEPENDENT_ADJUDICATION");
  expect(receipt.join.zero_renderer_advance_positive_commit_count).toBeGreaterThan(0);
  const zero = receipt.intervals.find((row) =>
    row.renderer_start_sequence === row.renderer_end_sequence && row.commit_delta_bytes > 0
  );
  expect(zero?.render_pass_delta).toBe(0);
  expect(zero?.submitted_utf8_byte_delta).toBe(0);
  expect(receipt.full_run.fits.commit_bytes.slope_per_second).toBeFinite();
  expect(receipt.settled_windows.length).toBeGreaterThan(0);
  expect(verifyIssue898RendererCensusEvidenceReceipt(
    readFileSync(fixture.input.outputPath, "utf8"),
    fixture.bindings,
  )).toEqual(receipt);
});

test.each([
  ["renderer missing final newline", (fixture: EvidenceFixture) => {
    writeRendererFixture(fixture, fixture.bindings.rendererText.trimEnd());
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_UNSEALED_LINE"],
  ["renderer malformed JSON", (fixture: EvidenceFixture) => {
    const lines = fixture.bindings.rendererText.trimEnd().split("\n");
    lines[1] = "{";
    writeRendererFixture(fixture, `${lines.join("\n")}\n`);
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_JSON_INVALID"],
  ["renderer fewer than three rows", (fixture: EvidenceFixture) => {
    writeRendererFixture(fixture, `${fixture.bindings.rendererText.trimEnd().split("\n").slice(0, 2).join("\n")}\n`);
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_ROWS_SHORT"],
  ["polls missing final newline", (fixture: EvidenceFixture) => {
    writePollFixture(fixture, fixture.bindings.pollsText.trimEnd());
  }, "ISSUE898_RENDERER_CENSUS_POLLS_UNSEALED_LINE"],
  ["polls malformed JSON", (fixture: EvidenceFixture) => {
    const lines = fixture.bindings.pollsText.trimEnd().split("\n");
    lines[1] = "{";
    writePollFixture(fixture, `${lines.join("\n")}\n`);
  }, "ISSUE898_RENDERER_CENSUS_POLLS_JSON_INVALID"],
  ["polls fewer than three rows", (fixture: EvidenceFixture) => {
    writePollFixture(fixture, `${fixture.bindings.pollsText.trimEnd().split("\n").slice(0, 2).join("\n")}\n`);
  }, "ISSUE898_RENDERER_CENSUS_POLL_ROWS_SHORT"],
] as const)("family A refuses %s", (_name, mutate, error) => {
  const fixture = createEvidenceFixture();
  mutate(fixture);
  expect(() => sealIssue898RendererCensusEvidence(fixture.input)).toThrow(error);
  expect(existsSync(fixture.input.outputPath)).toBe(false);
});

test.each([
  ["existing evidence root", (fixture: EvidenceFixture) => {
    mkdirSync(path.dirname(fixture.input.outputPath));
  }, "ISSUE898_RENDERER_CENSUS_OUTPUT_ROOT_EXISTS"],
  ["output root equals arm root", (fixture: EvidenceFixture) => {
    const armRoot = path.dirname(path.dirname(fixture.input.pollsPath));
    fixture.input.outputPath = path.join(armRoot, "renderer-census-receipt.json");
  }, "ISSUE898_RENDERER_CENSUS_OUTPUT_ROOT_INVALID"],
  ["output root inside arm root", (fixture: EvidenceFixture) => {
    const armRoot = path.dirname(path.dirname(fixture.input.pollsPath));
    fixture.input.outputPath = path.join(armRoot, "evidence", "renderer-census-receipt.json");
  }, "ISSUE898_RENDERER_CENSUS_OUTPUT_ROOT_INVALID"],
  ["output root outside arm parent", (fixture: EvidenceFixture) => {
    const outside = mkdtempSync(path.join(os.tmpdir(), "issue898-renderer-census-outside-"));
    fixture.input.outputPath = path.join(outside, "evidence", "renderer-census-receipt.json");
  }, "ISSUE898_RENDERER_CENSUS_OUTPUT_ROOT_INVALID"],
] as const)("family E refuses %s", (_name, mutate, error) => {
  const fixture = createEvidenceFixture();
  mutate(fixture);
  expect(() => sealIssue898RendererCensusEvidence(fixture.input)).toThrow(error);
  expect(existsSync(fixture.input.outputPath)).toBe(false);
});

test("family E preserves pre-existing output bytes", () => {
  const fixture = createEvidenceFixture();
  const sentinel = "preserved-existing-receipt\n";
  mkdirSync(path.dirname(fixture.input.outputPath));
  writeFileSync(fixture.input.outputPath, sentinel, "utf8");
  expect(() => sealIssue898RendererCensusEvidence(fixture.input)).toThrow(
    "ISSUE898_RENDERER_CENSUS_OUTPUT_ROOT_EXISTS",
  );
  expect(readFileSync(fixture.input.outputPath, "utf8")).toBe(sentinel);
});

test.each([
  ["receipt malformed JSON", (text: string): string => "{", "ISSUE898_RENDERER_CENSUS_RECEIPT_JSON_INVALID"],
  ["receipt schema drift", (text: string): string => mutateReceiptText(text, (receipt) => {
    receipt.schema_version = "wrong";
  }), "ISSUE898_RENDERER_CENSUS_RECEIPT_SCHEMA_INVALID"],
  ["receipt verdict drift", (text: string): string => mutateReceiptText(text, (receipt) => {
    receipt.verdict = "wrong";
  }), "ISSUE898_RENDERER_CENSUS_RECEIPT_SCHEMA_INVALID"],
  ["receipt self hash drift", (text: string): string => mutateReceiptText(text, (receipt) => {
    receipt.receipt_sha256 = "c".repeat(64);
  }), "ISSUE898_RENDERER_CENSUS_RECEIPT_SHA256_INVALID"],
  ["receipt content tamper", (text: string): string => mutateReceiptText(text, (receipt) => {
    (receipt.join as Record<string, unknown>).anchor_count = 999;
  }), "ISSUE898_RENDERER_CENSUS_RECEIPT_SHA256_INVALID"],
] as const)("family F refuses %s", (_name, mutate, error) => {
  const fixture = createEvidenceFixture();
  sealIssue898RendererCensusEvidence(fixture.input);
  const validText = readFileSync(fixture.input.outputPath, "utf8");
  expect(() => verifyIssue898RendererCensusEvidenceReceipt(
    mutate(validText),
    fixture.bindings,
  )).toThrow(error);
});

test.each([
  ["soak receipt byte substitution", (bindings: Issue898RendererCensusEvidenceBindings) => {
    bindings.soakReceiptText = `${bindings.soakReceiptText.trimEnd()} \n`;
  }, "ISSUE898_RENDERER_CENSUS_RECEIPT_BINDING_INVALID"],
  ["poll ledger byte substitution", (bindings: Issue898RendererCensusEvidenceBindings) => {
    bindings.pollsText = `${bindings.pollsText}\n`;
  }, "ISSUE898_SOAK_LEDGER_CUSTODY_INVALID"],
  ["renderer byte substitution", (bindings: Issue898RendererCensusEvidenceBindings) => {
    bindings.rendererText = `${bindings.rendererText}\n`;
  }, "ISSUE898_RENDERER_CENSUS_RECEIPT_BINDING_INVALID"],
  ["source binding substitution", (bindings: Issue898RendererCensusEvidenceBindings) => {
    bindings.sourceCommit = "c".repeat(40);
  }, "ISSUE898_RENDERER_CENSUS_RECEIPT_BINDING_INVALID"],
  ["cockpit PID binding substitution", (bindings: Issue898RendererCensusEvidenceBindings) => {
    bindings.cockpitPid += 1;
  }, "ISSUE898_RENDERER_CENSUS_RECEIPT_BINDING_INVALID"],
  ["kernel token binding substitution", (bindings: Issue898RendererCensusEvidenceBindings) => {
    bindings.cockpitProcessStartToken = String(BigInt(bindings.cockpitProcessStartToken) + 1n);
  }, "ISSUE898_RENDERER_CENSUS_RECEIPT_BINDING_INVALID"],
] as const)("family F refuses %s", (_name, mutate, error) => {
  const fixture = createEvidenceFixture();
  sealIssue898RendererCensusEvidence(fixture.input);
  const validText = readFileSync(fixture.input.outputPath, "utf8");
  const bindings = { ...fixture.bindings };
  mutate(bindings);
  expect(() => verifyIssue898RendererCensusEvidenceReceipt(validText, bindings)).toThrow(error);
});

test("retains and flags renderer staleness above 60 seconds", () => {
  const fixture = createEvidenceFixture();
  mutateRendererFixture(fixture, 1, (row) => {
    row.captured_at_ms = STARTED_AT_MS + 180_000;
    row.captured_at = new Date(Number(row.captured_at_ms)).toISOString();
  });
  const receipt = sealIssue898RendererCensusEvidence(fixture.input);
  const stale = receipt.intervals.find((row) => row.renderer_staleness_ms > 60_000);
  expect(stale).toBeDefined();
  expect(stale?.stale_over_60s).toBe(true);
  expect(receipt.join.stale_interval_count).toBeGreaterThan(0);
});

test("nulls ratio for an exactly constant denominator series", () => {
  const fixture = createEvidenceFixture();
  mutateAllRendererRows(fixture, (row) => { row.submitted_utf8_bytes = 0; });
  const receipt = sealIssue898RendererCensusEvidence(fixture.input);
  expect(receipt.full_run.fits.submitted_utf8_bytes.slope_per_second).toBe(0);
  expect(receipt.full_run.normalized_ratios.commit_bytes_per_submitted_utf8_byte).toBeNull();
});

test("nulls ratio when denominator slope is within its standard error", () => {
  const fixture = createEvidenceFixture();
  mutateAllRendererRows(fixture, (row, index) => {
    row.submitted_utf8_bytes = index === 60 ? 1 : 0;
  });
  clusterPollTimesBeforeFinalRendererRow(fixture);
  const receipt = sealIssue898RendererCensusEvidence(fixture.input);
  const denominator = receipt.full_run.fits.submitted_utf8_bytes;
  expect(Math.abs(denominator.slope_per_second)).toBeLessThanOrEqual(
    denominator.slope_standard_error,
  );
  expect(receipt.full_run.normalized_ratios.commit_bytes_per_submitted_utf8_byte).toBeNull();
});

test.each([
  ["renderer extra property", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 1, (row) => { row.unexpected = true; });
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_PROPERTIES_INVALID"],
  ["renderer missing property", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 1, (row) => { delete row.style_pool_size; });
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_PROPERTIES_INVALID"],
] as const)("family B exactness refuses %s", (_name, mutate, error) => {
  const fixture = createEvidenceFixture();
  mutate(fixture);
  expect(() => sealIssue898RendererCensusEvidence(fixture.input)).toThrow(error);
  expect(existsSync(fixture.input.outputPath)).toBe(false);
});

test.each([
  ["poll extra property", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      (row as unknown as Record<string, unknown>).unexpected = true;
    });
  }, "ISSUE898_RENDERER_CENSUS_POLL_PROPERTIES_INVALID"],
  ["census extra property", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      (row.census as unknown as Record<string, unknown>).unexpected = true;
    });
  }, "ISSUE898_RENDERER_CENSUS_CENSUS_PROPERTIES_INVALID"],
  ["sample extra property", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      (row.census.samples[0] as unknown as Record<string, unknown>).unexpected = true;
    });
  }, "ISSUE898_RENDERER_CENSUS_SAMPLE_PROPERTIES_INVALID"],
  ["class cardinality extra property", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      (row.census.class_cardinality as unknown as Record<string, unknown>).unexpected = true;
    });
  }, "ISSUE898_RENDERER_CENSUS_CARDINALITY_PROPERTIES_INVALID"],
  ["ownership overlap extra property", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      (row.census.ownership_overlap as unknown as Record<string, unknown>).unexpected = true;
    });
  }, "ISSUE898_RENDERER_CENSUS_OVERLAP_PROPERTIES_INVALID"],
] as const)("family C exactness refuses %s", (_name, mutate, error) => {
  const fixture = createEvidenceFixture();
  mutate(fixture);
  expect(() => sealIssue898RendererCensusEvidence(fixture.input)).toThrow(error);
  expect(existsSync(fixture.input.outputPath)).toBe(false);
});

test.each([
  ["relative input path", (fixture: EvidenceFixture) => {
    fixture.input.soakReceiptPath = "soak-receipt.json";
  }, "ISSUE898_RENDERER_CENSUS_PATH_NOT_ABSOLUTE"],
  ["invalid source pin", (fixture: EvidenceFixture) => {
    fixture.input.sourceCommit = "not-a-commit";
  }, "ISSUE898_RENDERER_CENSUS_SOURCE_COMMIT_INVALID"],
  ["invalid cockpit PID pin", (fixture: EvidenceFixture) => {
    fixture.input.cockpitPid = 0;
  }, "ISSUE898_RENDERER_CENSUS_COCKPIT_PID_INVALID"],
  ["invalid kernel token pin", (fixture: EvidenceFixture) => {
    fixture.input.cockpitProcessStartToken = "0";
  }, "ISSUE898_RENDERER_CENSUS_COCKPIT_TOKEN_INVALID"],
  ["noncanonical receipt time", (fixture: EvidenceFixture) => {
    fixture.input.receiptWrittenAt = "2026-08-24T02:00:02Z";
  }, "ISSUE898_RENDERER_CENSUS_RECEIPT_TIME_INVALID"],
  ["renderer source drift", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 2, (row) => { row.source_commit = "c".repeat(40); });
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_IDENTITY_DRIFT"],
  ["renderer PID drift", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 2, (row) => { row.pid = COCKPIT_PID + 1; });
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_IDENTITY_DRIFT"],
  ["renderer runtime token invalid", (fixture: EvidenceFixture) => {
    setRendererRuntimeToken(fixture, "0");
  }, "ISSUE898_RENDERER_CENSUS_RUNTIME_ORIGIN_INVALID"],
  ["renderer runtime token drift", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 2, (row) => {
      row.runtime_origin_token = String(BigInt(RUNTIME_TOKEN) + 1n);
    });
  }, "ISSUE898_RENDERER_CENSUS_RUNTIME_ORIGIN_DRIFT"],
  ["renderer runtime before kernel", (fixture: EvidenceFixture) => {
    setRendererRuntimeToken(fixture, String(BigInt(KERNEL_TOKEN) - 10_000n));
  }, "ISSUE898_RENDERER_CENSUS_RUNTIME_ORIGIN_OUT_OF_RANGE"],
  ["renderer runtime above tolerance", (fixture: EvidenceFixture) => {
    setRendererRuntimeToken(fixture, String(BigInt(KERNEL_TOKEN) + 50_010_000n));
  }, "ISSUE898_RENDERER_CENSUS_RUNTIME_ORIGIN_OUT_OF_RANGE"],
  ["standard soak source identity drift", (fixture: EvidenceFixture) => {
    mutateSoakReceiptFixture(fixture, (receipt) => {
      (receipt.identity as Record<string, unknown>).source_commit = "c".repeat(40);
    });
  }, "ISSUE898_RENDERER_CENSUS_SOAK_IDENTITY_DRIFT"],
  ["standard soak cockpit PID drift", (fixture: EvidenceFixture) => {
    mutateSoakReceiptFixture(fixture, (receipt) => {
      (receipt.identity as Record<string, unknown>).cockpit_pid = COCKPIT_PID + 1;
    });
  }, "ISSUE898_RENDERER_CENSUS_SOAK_IDENTITY_DRIFT"],
  ["standard soak kernel token drift", (fixture: EvidenceFixture) => {
    mutateSoakReceiptFixture(fixture, (receipt) => {
      (receipt.identity as Record<string, unknown>).cockpit_process_start_token =
        String(BigInt(KERNEL_TOKEN) + 1n);
    });
  }, "ISSUE898_RENDERER_CENSUS_SOAK_IDENTITY_DRIFT"],
] as const)("family D refuses %s", (_name, mutate, error) => {
  const fixture = createEvidenceFixture();
  mutate(fixture);
  expect(() => sealIssue898RendererCensusEvidence(fixture.input)).toThrow(error);
  expect(existsSync(fixture.input.outputPath)).toBe(false);
});

test.each([
  ["poll schema drift", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => { row.schema_version = "wrong"; });
  }, "ISSUE898_RENDERER_CENSUS_POLL_SEQUENCE_INVALID"],
  ["poll sequence gap", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => { row.sequence = 2; });
  }, "ISSUE898_RENDERER_CENSUS_POLL_SEQUENCE_INVALID"],
  ["poll noncanonical timestamp", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => { row.census.observed_at = "2026-08-24T00:01:00Z"; });
  }, "ISSUE898_RENDERER_CENSUS_POLL_TIME_INVALID"],
  ["poll timestamp rollback", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 2, (row) => {
      row.census.observed_at = new Date(STARTED_AT_MS + 60_000).toISOString();
    });
  }, "ISSUE898_RENDERER_CENSUS_POLL_TIME_NONMONOTONE"],
  ["poll admitted count drift", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => { row.census.admitted_process_count = 1; });
  }, "ISSUE898_RENDERER_CENSUS_CENSUS_CARDINALITY_INVALID"],
  ["poll class cardinality drift", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => { row.census.class_cardinality.cockpit = 2; });
  }, "ISSUE898_RENDERER_CENSUS_CENSUS_CARDINALITY_INVALID"],
  ["poll ownership overlap", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      row.census.ownership_overlap = { count: 1, pids: [COCKPIT_PID] };
    });
  }, "ISSUE898_RENDERER_CENSUS_CENSUS_CARDINALITY_INVALID"],
  ["poll missing brain sample", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      row.census.samples = row.census.samples.filter((sample) => sample.process_class !== "brain_server");
    });
  }, "ISSUE898_RENDERER_CENSUS_COCKPIT_IDENTITY_DRIFT"],
  ["poll cockpit PID drift", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      row.census.samples.find((sample) => sample.process_class === "cockpit")!.pid += 1;
    });
  }, "ISSUE898_RENDERER_CENSUS_COCKPIT_IDENTITY_DRIFT"],
  ["poll kernel token drift", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      row.census.samples.find((sample) => sample.process_class === "cockpit")!.process_start_token =
        String(BigInt(KERNEL_TOKEN) + 1n);
    });
  }, "ISSUE898_RENDERER_CENSUS_COCKPIT_IDENTITY_DRIFT"],
  ["poll negative commit bytes", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      row.census.samples.find((sample) => sample.process_class === "cockpit")!.commit_bytes = -1;
    });
  }, "ISSUE898_RENDERER_CENSUS_COMMIT_BYTES_INVALID"],
  ["poll fractional commit bytes", (fixture: EvidenceFixture) => {
    mutatePollFixture(fixture, 1, (row) => {
      row.census.samples.find((sample) => sample.process_class === "brain_server")!.commit_bytes = 1.5;
    });
  }, "ISSUE898_RENDERER_CENSUS_COMMIT_BYTES_INVALID"],
] as const)("family C refuses %s", (_name, mutate, error) => {
  const fixture = createEvidenceFixture();
  mutate(fixture);
  expect(() => sealIssue898RendererCensusEvidence(fixture.input)).toThrow(error);
  expect(existsSync(fixture.input.outputPath)).toBe(false);
});

test.each([
  ["renderer schema drift", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 1, (row) => { row.schema_version = "wrong"; });
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_SEQUENCE_INVALID"],
  ["renderer sequence gap", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 1, (row) => { row.sequence = 2; });
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_SEQUENCE_INVALID"],
  ["renderer noncanonical timestamp", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 1, (row) => { row.captured_at = "2026-08-24T00:02:00Z"; });
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_TIME_INVALID"],
  ["renderer timestamp millisecond mismatch", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 1, (row) => {
      row.captured_at_ms = Number(row.captured_at_ms) + 1;
    });
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_TIME_NONMONOTONE"],
  ["renderer timestamp rollback", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 2, (row) => {
      row.captured_at_ms = STARTED_AT_MS + 120_000;
      row.captured_at = new Date(Number(row.captured_at_ms)).toISOString();
    });
  }, "ISSUE898_RENDERER_CENSUS_RENDERER_TIME_NONMONOTONE"],
  ["renderer counter invalid", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 2, (row) => { row.render_passes = -1; });
  }, "ISSUE898_RENDERER_CENSUS_COUNTER_INVALID"],
  ["renderer counter rollback", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 2, (row) => { row.render_passes = 1; });
  }, "ISSUE898_RENDERER_CENSUS_COUNTER_ROLLBACK"],
  ["renderer pool size invalid", (fixture: EvidenceFixture) => {
    mutateRendererFixture(fixture, 2, (row) => { row.style_pool_size = -1; });
  }, "ISSUE898_RENDERER_CENSUS_POOL_SIZE_INVALID"],
] as const)("family B refuses %s", (_name, mutate, error) => {
  const fixture = createEvidenceFixture();
  mutate(fixture);
  expect(() => sealIssue898RendererCensusEvidence(fixture.input)).toThrow(error);
  expect(existsSync(fixture.input.outputPath)).toBe(false);
});
