// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import type { BoundMemoryTripReceipt } from "./memory-footprint-service.ts";

const GIT_COMMIT = /^[0-9a-f]{40}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const GIB = 1024 ** 3;
const MIB = 1024 ** 2;
const SOAK_SECONDS = 7_200;
const SAMPLE_INTERVAL_SECONDS = 60;
const GROWTH_CEILING_BYTES = 256 * MIB;
const INCIDENT = {
  provider: "Microsoft-Windows-Resource-Exhaustion-Detector",
  event_id: 2004,
  observed_local: "2026-08-05T02:01:10-07:00",
  process_name: "Ember.exe",
  pid: 48660,
  commit_bytes: 69_208_911_872,
} as const;

export interface Issue1455Incident {
  provider: typeof INCIDENT.provider;
  event_id: typeof INCIDENT.event_id;
  observed_local: typeof INCIDENT.observed_local;
  process_name: typeof INCIDENT.process_name;
  pid: typeof INCIDENT.pid;
  commit_bytes: typeof INCIDENT.commit_bytes;
}

export interface Issue1455SourceIdentity {
  source_commit: string;
  cockpit_binary_sha256: string;
  memory_spec_path: "tools/ember-cli/specs/liveness-watchdog-memory-v1.json";
  memory_spec_sha256: string;
}

export interface Issue1455MemorySample {
  ts: string;
  commit_bytes: number;
  working_set_bytes: number;
}

interface CommonInput {
  schema_version: "ember-issue1455-memory-evidence-input-v1";
  incident: Issue1455Incident;
  source: Issue1455SourceIdentity;
  cockpit_pid: number;
}

export interface Issue1455IdleSoakInput extends CommonInput {
  evidence_kind: "idle_soak";
  sample_interval_seconds: 60;
  samples: Issue1455MemorySample[];
}

export interface Issue1455InjectedGrowthInput extends CommonInput {
  evidence_kind: "injected_growth";
  injected_commit_bytes: number;
  expected_exit_code: 75;
  observed_exit_code: number;
  process_start_time: string;
  exit_observation: Issue1455TerminalExitObservation;
  trip_receipt: BoundMemoryTripReceipt;
}

export interface Issue1455TerminalExitObservation {
  schema_version: "ember-process-terminal-observation-v1";
  observer: "wait_for_single_object+get_exit_code_process";
  pid: number;
  process_start_time: string;
  observed_at: string;
  exit_code: number;
  receipt_sha256: string;
}

export type Issue1455MemoryReceiptInput =
  | Issue1455IdleSoakInput
  | Issue1455InjectedGrowthInput;

export type Issue1455MemoryEvidenceReceipt = Record<string, unknown> & {
  schema_version: "ember-issue1455-memory-evidence-v1";
  evidence_kind: "idle_soak" | "injected_growth";
  verdict: "PASS";
  receipt_sha256: string;
};

function exactKeys(value: object, keys: readonly string[], error: string): void {
  if (Object.keys(value).sort().join(",") !== [...keys].sort().join(",")) throw new Error(error);
}

function validateCommon(input: Issue1455MemoryReceiptInput): void {
  if (input.schema_version !== "ember-issue1455-memory-evidence-input-v1") {
    throw new Error("ISSUE1455_INPUT_SCHEMA_INVALID");
  }
  exactKeys(input.incident, Object.keys(INCIDENT), "ISSUE1455_INCIDENT_PROPERTIES_INVALID");
  for (const [key, expected] of Object.entries(INCIDENT)) {
    if (input.incident[key as keyof Issue1455Incident] !== expected) {
      throw new Error(`ISSUE1455_INCIDENT_BINDING_INVALID:${key}`);
    }
  }
  exactKeys(
    input.source,
    ["source_commit", "cockpit_binary_sha256", "memory_spec_path", "memory_spec_sha256"],
    "ISSUE1455_SOURCE_PROPERTIES_INVALID",
  );
  if (
    !GIT_COMMIT.test(input.source.source_commit)
    || !SHA256.test(input.source.cockpit_binary_sha256)
    || !SHA256.test(input.source.memory_spec_sha256)
    || input.source.memory_spec_path !== "tools/ember-cli/specs/liveness-watchdog-memory-v1.json"
  ) {
    throw new Error("ISSUE1455_SOURCE_IDENTITY_INVALID");
  }
  if (!Number.isSafeInteger(input.cockpit_pid) || input.cockpit_pid <= 0) {
    throw new Error("ISSUE1455_COCKPIT_PID_INVALID");
  }
}

function parseSample(sample: Issue1455MemorySample): number {
  exactKeys(sample, ["ts", "commit_bytes", "working_set_bytes"], "ISSUE1455_SAMPLE_PROPERTIES_INVALID");
  const timestamp = Date.parse(sample.ts);
  if (
    !Number.isFinite(timestamp)
    || new Date(timestamp).toISOString() !== sample.ts
    || !Number.isSafeInteger(sample.commit_bytes)
    || sample.commit_bytes < 0
    || !Number.isSafeInteger(sample.working_set_bytes)
    || sample.working_set_bytes < 0
  ) {
    throw new Error("ISSUE1455_SAMPLE_INVALID");
  }
  return timestamp;
}

function sha256Text(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const row = value as Record<string, unknown>;
  return `{${Object.keys(row).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(row[key])}`).join(",")}}`;
}

function finalize(base: Record<string, unknown>): Issue1455MemoryEvidenceReceipt {
  const receiptSha256 = sha256Text(canonicalJson(base));
  return { ...base, receipt_sha256: receiptSha256 } as Issue1455MemoryEvidenceReceipt;
}

export function sealIssue1455TerminalExitObservation(
  input: Omit<Issue1455TerminalExitObservation, "receipt_sha256"> & { receipt_sha256?: never },
): Issue1455TerminalExitObservation {
  exactKeys(
    input,
    ["schema_version", "observer", "pid", "process_start_time", "observed_at", "exit_code"],
    "ISSUE1455_EXIT_OBSERVATION_PROPERTIES_INVALID",
  );
  if (
    input.schema_version !== "ember-process-terminal-observation-v1"
    || input.observer !== "wait_for_single_object+get_exit_code_process"
    || !Number.isSafeInteger(input.pid)
    || input.pid <= 0
    || !Number.isSafeInteger(input.exit_code)
    || !Number.isFinite(Date.parse(input.process_start_time))
    || new Date(Date.parse(input.process_start_time)).toISOString() !== input.process_start_time
    || !Number.isFinite(Date.parse(input.observed_at))
    || new Date(Date.parse(input.observed_at)).toISOString() !== input.observed_at
    || Date.parse(input.observed_at) < Date.parse(input.process_start_time)
  ) {
    throw new Error("ISSUE1455_EXIT_OBSERVATION_INVALID");
  }
  return { ...input, receipt_sha256: sha256Text(canonicalJson(input)) };
}

function validateExitObservation(
  observation: Issue1455TerminalExitObservation,
): Issue1455TerminalExitObservation {
  const { receipt_sha256: claimed, ...base } = observation;
  const sealed = sealIssue1455TerminalExitObservation(base);
  if (!SHA256.test(claimed) || sealed.receipt_sha256 !== claimed) {
    throw new Error("ISSUE1455_EXIT_OBSERVATION_SHA256_INVALID");
  }
  return sealed;
}

function buildIdleReceipt(input: Issue1455IdleSoakInput): Issue1455MemoryEvidenceReceipt {
  exactKeys(
    input,
    ["schema_version", "evidence_kind", "incident", "source", "cockpit_pid", "sample_interval_seconds", "samples"],
    "ISSUE1455_IDLE_PROPERTIES_INVALID",
  );
  if (input.sample_interval_seconds !== SAMPLE_INTERVAL_SECONDS || input.samples.length < 121) {
    throw new Error("ISSUE1455_IDLE_CADENCE_INVALID");
  }
  const timestamps = input.samples.map(parseSample);
  for (let index = 1; index < timestamps.length; index += 1) {
    const elapsed = timestamps[index]! - timestamps[index - 1]!;
    if (elapsed < 45_000 || elapsed > 75_000) {
      throw new Error("ISSUE1455_IDLE_CADENCE_INVALID");
    }
  }
  const durationSeconds = (timestamps.at(-1)! - timestamps[0]!) / 1_000;
  if (durationSeconds < SOAK_SECONDS) throw new Error("ISSUE1455_IDLE_DURATION_SHORT");
  const commits = input.samples.map((sample) => sample.commit_bytes);
  const workingSets = input.samples.map((sample) => sample.working_set_bytes);
  const commitGrowth = Math.max(...commits) - Math.min(...commits);
  const workingSetGrowth = Math.max(...workingSets) - Math.min(...workingSets);
  if (commitGrowth > GROWTH_CEILING_BYTES || workingSetGrowth > GROWTH_CEILING_BYTES) {
    throw new Error("ISSUE1455_IDLE_GROWTH_EXCEEDED");
  }
  return finalize({
    schema_version: "ember-issue1455-memory-evidence-v1",
    evidence_kind: "idle_soak",
    verdict: "PASS",
    incident: input.incident,
    source: input.source,
    cockpit_pid: input.cockpit_pid,
    started_at: input.samples[0]!.ts,
    ended_at: input.samples.at(-1)!.ts,
    duration_seconds: durationSeconds,
    sample_interval_seconds: SAMPLE_INTERVAL_SECONDS,
    sample_count: input.samples.length,
    min_commit_bytes: Math.min(...commits),
    max_commit_bytes: Math.max(...commits),
    max_commit_growth_bytes: commitGrowth,
    min_working_set_bytes: Math.min(...workingSets),
    max_working_set_bytes: Math.max(...workingSets),
    max_working_set_growth_bytes: workingSetGrowth,
    growth_ceiling_bytes: GROWTH_CEILING_BYTES,
    samples: input.samples,
  });
}

function buildInjectedReceipt(input: Issue1455InjectedGrowthInput): Issue1455MemoryEvidenceReceipt {
  exactKeys(
    input,
    ["schema_version", "evidence_kind", "incident", "source", "cockpit_pid", "injected_commit_bytes", "expected_exit_code", "observed_exit_code", "process_start_time", "exit_observation", "trip_receipt"],
    "ISSUE1455_INJECTED_PROPERTIES_INVALID",
  );
  const trip = input.trip_receipt;
  const exitObservation = validateExitObservation(input.exit_observation);
  const tripTimestamp = Date.parse(trip.ts);
  if (
    input.expected_exit_code !== 75
    || input.observed_exit_code !== 75
    || !Number.isSafeInteger(input.injected_commit_bytes)
    || input.injected_commit_bytes < 4 * GIB
    || trip.schema_version !== "ember-memory-footprint-trip-v1"
    || trip.pid !== input.cockpit_pid
    || trip.process_class !== "cockpit"
    || trip.action !== "exit_cockpit_for_task_scheduler"
    || trip.threshold !== 4
    || trip.commit_gb !== input.injected_commit_bytes / GIB
    || trip.spec_path !== input.source.memory_spec_path
    || trip.spec_sha256 !== input.source.memory_spec_sha256
    || !Number.isFinite(tripTimestamp)
    || !Number.isFinite(Date.parse(input.process_start_time))
    || new Date(Date.parse(input.process_start_time)).toISOString() !== input.process_start_time
    || exitObservation.pid !== input.cockpit_pid
    || exitObservation.process_start_time !== input.process_start_time
    || exitObservation.exit_code !== input.observed_exit_code
    || tripTimestamp < Date.parse(input.process_start_time)
    || tripTimestamp > Date.parse(exitObservation.observed_at)
  ) {
    throw new Error("ISSUE1455_INJECTED_EVIDENCE_INVALID");
  }
  return finalize({
    schema_version: "ember-issue1455-memory-evidence-v1",
    evidence_kind: "injected_growth",
    verdict: "PASS",
    incident: input.incident,
    source: input.source,
    cockpit_pid: input.cockpit_pid,
    injected_commit_bytes: input.injected_commit_bytes,
    expected_exit_code: 75,
    observed_exit_code: 75,
    process_start_time: input.process_start_time,
    exit_observation: exitObservation,
    trip_precedes_exit_observation: true,
    trip_receipt: trip,
  });
}

export function buildIssue1455MemoryReceipt(
  input: Issue1455MemoryReceiptInput,
): Issue1455MemoryEvidenceReceipt {
  validateCommon(input);
  if (input.evidence_kind === "idle_soak") return buildIdleReceipt(input);
  if (input.evidence_kind === "injected_growth") return buildInjectedReceipt(input);
  throw new Error("ISSUE1455_EVIDENCE_KIND_INVALID");
}

export function writeIssue1455MemoryReceipt(
  outputPath: string,
  input: Issue1455MemoryReceiptInput,
): Issue1455MemoryEvidenceReceipt {
  const receipt = buildIssue1455MemoryReceipt(input);
  try {
    writeFileSync(outputPath, `${JSON.stringify(receipt, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") throw new Error("ISSUE1455_RECEIPT_EXISTS");
    throw error;
  }
  return receipt;
}

export function verifyIssue1455MemoryReceipt(
  text: string,
): Issue1455MemoryEvidenceReceipt {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("ISSUE1455_RECEIPT_JSON_INVALID");
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("ISSUE1455_RECEIPT_INVALID");
  }
  const row = parsed as Record<string, unknown>;
  const { receipt_sha256: claimed, ...base } = row;
  if (typeof claimed !== "string" || !SHA256.test(claimed) || sha256Text(canonicalJson(base)) !== claimed) {
    throw new Error("ISSUE1455_RECEIPT_SHA256_INVALID");
  }
  let rebuilt: Issue1455MemoryEvidenceReceipt;
  if (row.evidence_kind === "idle_soak") {
    rebuilt = buildIssue1455MemoryReceipt({
      schema_version: "ember-issue1455-memory-evidence-input-v1",
      evidence_kind: "idle_soak",
      incident: row.incident as Issue1455Incident,
      source: row.source as Issue1455SourceIdentity,
      cockpit_pid: row.cockpit_pid as number,
      sample_interval_seconds: row.sample_interval_seconds as 60,
      samples: row.samples as Issue1455MemorySample[],
    });
  } else if (row.evidence_kind === "injected_growth") {
    rebuilt = buildIssue1455MemoryReceipt({
      schema_version: "ember-issue1455-memory-evidence-input-v1",
      evidence_kind: "injected_growth",
      incident: row.incident as Issue1455Incident,
      source: row.source as Issue1455SourceIdentity,
      cockpit_pid: row.cockpit_pid as number,
      injected_commit_bytes: row.injected_commit_bytes as number,
      expected_exit_code: row.expected_exit_code as 75,
      observed_exit_code: row.observed_exit_code as number,
      process_start_time: row.process_start_time as string,
      exit_observation: row.exit_observation as Issue1455TerminalExitObservation,
      trip_receipt: row.trip_receipt as BoundMemoryTripReceipt,
    });
  } else {
    throw new Error("ISSUE1455_EVIDENCE_KIND_INVALID");
  }
  if (canonicalJson(rebuilt) !== canonicalJson(row)) {
    throw new Error("ISSUE1455_RECEIPT_DERIVATION_INVALID");
  }
  return rebuilt;
}
