// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 packet-2 J

import { createHash } from "node:crypto";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, writeFileSync, writeSync, fsyncSync } from "node:fs";
import path from "node:path";
import { linearFit } from "./ols-fit.ts";
import { censusWindowsProcessMemoryBatch, type ProcessMemoryCensusBatch } from "./process-memory-census.ts";
import { readEmberLabWallObservationSnapshot, type EmberLabWallObservationSnapshot } from "./ember-lab-rpc.ts";
import type { MemoryFootprintSpec } from "./memory-footprint-governor.ts";

const SHA256 = /^[0-9a-f]{64}$/;
const COMMIT = /^[0-9a-f]{40}$/;
const MIN_DURATION_MS = 2 * 60 * 60 * 1_000;
const SETTLE_MS = 60 * 1_000;
const WINDOW_MS = 5 * 60 * 1_000;
const FINAL_HOUR_MS = 60 * 60 * 1_000;

export interface InstalledCockpitSoakRawRow {
  schema_version: "ember-issue898-installed-cockpit-soak-poll-v1";
  sequence: number;
  census: ProcessMemoryCensusBatch;
  walls: EmberLabWallObservationSnapshot;
}

export interface InstalledCockpitSoakIdentity {
  source_commit: string;
  cockpit_binary_sha256: string;
  ember_lab_binary_sha256: string;
  ember_lab_source_sha256: string;
  cockpit_pid: number;
  cockpit_process_start_token: string;
  sidecar_job_id: string;
  sidecar_manifest_sha256: string;
}

export interface InstalledCockpitSoakNegatives {
  above_hard_trip: { passed: true; receipt_sha256: string };
  below_reset: { passed: true; receipt_sha256: string };
  soft_observe: { passed: true; receipt_sha256: string };
  foreign_identity_never_controlled: { passed: true; receipt_sha256: string };
}

export interface InstalledCockpitSoakSealInput {
  raw_ledger_path: string;
  receipt_path: string;
  identity: InstalledCockpitSoakIdentity;
  negatives: InstalledCockpitSoakNegatives;
  poll_interval_seconds: number;
  receipt_written_at: string;
  restart_event_count_before_receipt: 0;
}

export interface InstalledCockpitSoakRunOptions {
  outputRoot: string;
  pipeName: string;
  memorySpec: MemoryFootprintSpec;
  cockpitPid: number;
  ownedBrainPids: readonly number[];
  durationSeconds: number;
  pollIntervalSeconds: number;
}

export type InstalledCockpitSoakReceipt = Record<string, unknown> & {
  schema_version: "ember-issue898-installed-cockpit-soak-v1";
  verdict: "MEASURED_NEEDS_INDEPENDENT_ADJUDICATION";
  receipt_sha256: string;
};

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const row = value as Record<string, unknown>;
  return `{${Object.keys(row).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(row[key])}`).join(",")}}`;
}

function sha256(bytes: string | Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function exactKeys(value: object, keys: readonly string[], error: string): void {
  if (Object.keys(value).sort().join(",") !== [...keys].sort().join(",")) throw new Error(error);
}

export function createInstalledCockpitSoakLedger(outputRoot: string): string {
  if (existsSync(outputRoot)) throw new Error("ISSUE898_SOAK_OUTPUT_ROOT_EXISTS");
  mkdirSync(outputRoot);
  const ledgerPath = path.join(outputRoot, "polls.jsonl");
  const handle = openSync(ledgerPath, "wx");
  fsyncSync(handle);
  closeSync(handle);
  return ledgerPath;
}

export function appendInstalledCockpitSoakPoll(
  ledgerPath: string,
  row: InstalledCockpitSoakRawRow,
): void {
  exactKeys(row, ["schema_version", "sequence", "census", "walls"], "ISSUE898_SOAK_POLL_PROPERTIES_INVALID");
  if (row.schema_version !== "ember-issue898-installed-cockpit-soak-poll-v1" || !Number.isSafeInteger(row.sequence) || row.sequence < 0) {
    throw new Error("ISSUE898_SOAK_POLL_INVALID");
  }
  const handle = openSync(ledgerPath, "a");
  try {
    writeSync(handle, `${canonicalJson(row)}\n`, undefined, "utf8");
    fsyncSync(handle);
  } finally {
    closeSync(handle);
  }
}

export async function runInstalledCockpitSoak(
  options: InstalledCockpitSoakRunOptions,
  dependencies: {
    now?: () => number;
    sleep?: (milliseconds: number) => Promise<void>;
    census?: typeof censusWindowsProcessMemoryBatch;
    readWalls?: typeof readEmberLabWallObservationSnapshot;
  } = {},
): Promise<string> {
  if (!Number.isSafeInteger(options.durationSeconds) || options.durationSeconds < MIN_DURATION_MS / 1_000) throw new Error("ISSUE898_SOAK_DURATION_SHORT");
  if (!Number.isSafeInteger(options.pollIntervalSeconds) || options.pollIntervalSeconds < 1 || options.pollIntervalSeconds > 60) throw new Error("ISSUE898_SOAK_CADENCE_INVALID");
  const now = dependencies.now ?? Date.now;
  const sleep = dependencies.sleep ?? ((milliseconds) => new Promise<void>((resolve) => setTimeout(resolve, milliseconds)));
  const census = dependencies.census ?? censusWindowsProcessMemoryBatch;
  const readWalls = dependencies.readWalls ?? readEmberLabWallObservationSnapshot;
  const ledgerPath = createInstalledCockpitSoakLedger(options.outputRoot);
  const startedAt = now();
  let sequence = 0;
  let afterVramSeq = 0;
  let afterDiskSeq = 0;
  while (true) {
    const poll = await census(options.memorySpec, {
      cockpitPid: options.cockpitPid,
      ownedBrainPids: options.ownedBrainPids,
    });
    const walls = await readWalls({
      pipeName: options.pipeName,
      afterVramSeq,
      afterDiskSeq,
    });
    appendInstalledCockpitSoakPoll(ledgerPath, {
      schema_version: "ember-issue898-installed-cockpit-soak-poll-v1",
      sequence,
      census: poll,
      walls,
    });
    afterVramSeq = walls.next_vram_seq;
    afterDiskSeq = walls.next_disk_seq;
    sequence += 1;
    if (now() - startedAt >= options.durationSeconds * 1_000) break;
    await sleep(options.pollIntervalSeconds * 1_000);
  }
  return ledgerPath;
}

function readRows(ledgerPath: string): { bytes: Buffer; rows: InstalledCockpitSoakRawRow[] } {
  const bytes = readFileSync(ledgerPath);
  if (bytes.length === 0 || bytes.at(-1) !== 0x0a) throw new Error("ISSUE898_SOAK_LEDGER_UNSEALED_LINE");
  const rows = bytes.toString("utf8").trimEnd().split("\n").map((line) => {
    const parsed = JSON.parse(line) as InstalledCockpitSoakRawRow;
    if (`${canonicalJson(parsed)}\n` !== `${line}\n`) throw new Error("ISSUE898_SOAK_LEDGER_NONCANONICAL");
    return parsed;
  });
  return { bytes, rows };
}

function validateIdentity(identity: InstalledCockpitSoakIdentity): void {
  exactKeys(identity, ["source_commit", "cockpit_binary_sha256", "ember_lab_binary_sha256", "ember_lab_source_sha256", "cockpit_pid", "cockpit_process_start_token", "sidecar_job_id", "sidecar_manifest_sha256"], "ISSUE898_SOAK_IDENTITY_PROPERTIES_INVALID");
  if (!COMMIT.test(identity.source_commit) || !SHA256.test(identity.cockpit_binary_sha256)
    || !SHA256.test(identity.ember_lab_binary_sha256) || !SHA256.test(identity.ember_lab_source_sha256)
    || !SHA256.test(identity.sidecar_manifest_sha256) || !Number.isSafeInteger(identity.cockpit_pid)
    || identity.cockpit_pid <= 0 || !/^[1-9][0-9]*$/.test(identity.cockpit_process_start_token)
    || !identity.sidecar_job_id) throw new Error("ISSUE898_SOAK_IDENTITY_INVALID");
}

function windowFits(points: Array<{ x: number; y: number }>, startMs: number, endMs: number) {
  const selected = points.filter((point) => point.x >= startMs && point.x <= endMs);
  if (selected.length < 2) throw new Error("ISSUE898_SOAK_OLS_WINDOW_UNDERSAMPLED");
  const fit = linearFit(selected.map((point) => ({ x: (point.x - startMs) / 1_000, y: point.y })));
  return { started_at: new Date(startMs).toISOString(), ended_at: new Date(endMs).toISOString(), sample_count: selected.length, slope_bytes_per_second: fit.slope, intercept_bytes: fit.intercept, r2: fit.r2 };
}

function fitWindows(points: Array<{ x: number; y: number }>, firstMs: number, lastMs: number) {
  const fits = [];
  for (let start = firstMs; start + WINDOW_MS <= lastMs; start += WINDOW_MS) fits.push(windowFits(points, start, start + WINDOW_MS));
  return fits;
}

function band(fits: Array<{ slope_bytes_per_second: number }>) {
  if (fits.length === 0) throw new Error("ISSUE898_SOAK_OLS_BAND_EMPTY");
  const slopes = fits.map((fit) => fit.slope_bytes_per_second).sort((a, b) => a - b);
  return { window_count: fits.length, min_slope_bytes_per_second: slopes[0], max_slope_bytes_per_second: slopes.at(-1), median_slope_bytes_per_second: slopes[Math.floor(slopes.length / 2)] };
}

function validateNegatives(negatives: InstalledCockpitSoakNegatives): void {
  exactKeys(negatives, ["above_hard_trip", "below_reset", "soft_observe", "foreign_identity_never_controlled"], "ISSUE898_SOAK_NEGATIVES_PROPERTIES_INVALID");
  for (const [name, result] of Object.entries(negatives)) {
    exactKeys(result, ["passed", "receipt_sha256"], `ISSUE898_SOAK_NEGATIVE_PROPERTIES_INVALID:${name}`);
    if (result.passed !== true || !SHA256.test(result.receipt_sha256)) throw new Error(`ISSUE898_SOAK_NEGATIVE_INVALID:${name}`);
  }
}

export function sealInstalledCockpitSoak(input: InstalledCockpitSoakSealInput): InstalledCockpitSoakReceipt {
  if (path.dirname(path.resolve(input.raw_ledger_path)) !== path.dirname(path.resolve(input.receipt_path))) throw new Error("ISSUE898_SOAK_RECEIPT_ROOT_INVALID");
  validateIdentity(input.identity);
  validateNegatives(input.negatives);
  if (input.restart_event_count_before_receipt !== 0) throw new Error("ISSUE898_SOAK_RECEIPT_AFTER_RESTART");
  const receiptWrittenAtMs = Date.parse(input.receipt_written_at);
  if (!Number.isFinite(receiptWrittenAtMs) || new Date(receiptWrittenAtMs).toISOString() !== input.receipt_written_at) throw new Error("ISSUE898_SOAK_RECEIPT_TIME_INVALID");
  const { bytes, rows } = readRows(input.raw_ledger_path);
  if (rows.length < 2) throw new Error("ISSUE898_SOAK_ROWS_SHORT");
  const points: Array<{ x: number; y: number }> = [];
  const intervalsMs: number[] = [];
  let priorTs = -1;
  let priorVramSeq = 0;
  let priorDiskSeq = 0;
  const vramOutcomeCounts: Record<string, number> = {};
  const debounceDispositions: Record<string, number> = {};
  const diskDurations: number[] = [];
  const vramObservedAt: number[] = [];
  const diskObservedAt: number[] = [];
  for (const [index, row] of rows.entries()) {
    if (row.sequence !== index || row.schema_version !== "ember-issue898-installed-cockpit-soak-poll-v1") throw new Error("ISSUE898_SOAK_SEQUENCE_INVALID");
    const ts = Date.parse(row.census.observed_at);
    if (!Number.isFinite(ts) || ts <= priorTs) throw new Error("ISSUE898_SOAK_TIME_NONMONOTONE");
    if (priorTs >= 0) intervalsMs.push(ts - priorTs);
    priorTs = ts;
    const cockpit = row.census.samples.find((sample) => sample.process_class === "cockpit" && sample.pid === input.identity.cockpit_pid);
    if (!cockpit || cockpit.process_start_token !== input.identity.cockpit_process_start_token) throw new Error("ISSUE898_SOAK_COCKPIT_IDENTITY_DRIFT");
    if (row.census.ownership_overlap.count !== 0) throw new Error("ISSUE898_SOAK_OWNERSHIP_OVERLAP");
    if (row.walls.daemon_identity.binary_sha256 !== input.identity.ember_lab_binary_sha256 || row.walls.daemon_identity.source_sha256 !== input.identity.ember_lab_source_sha256) throw new Error("ISSUE898_SOAK_DAEMON_IDENTITY_DRIFT");
    if (row.walls.after_vram_seq !== priorVramSeq || row.walls.after_disk_seq !== priorDiskSeq) throw new Error("ISSUE898_SOAK_WALL_CURSOR_GAP");
    priorVramSeq = row.walls.next_vram_seq;
    priorDiskSeq = row.walls.next_disk_seq;
    for (const observation of row.walls.vram_observations) {
      if (observation.job_id !== input.identity.sidecar_job_id) throw new Error("ISSUE898_SOAK_FOREIGN_WALL_JOB");
      vramObservedAt.push(observation.observed_at_ms);
      vramOutcomeCounts[observation.outcome] = (vramOutcomeCounts[observation.outcome] ?? 0) + 1;
      const disposition = observation.payload["debounce_disposition"];
      if (typeof disposition === "string") debounceDispositions[disposition] = (debounceDispositions[disposition] ?? 0) + 1;
    }
    for (const observation of row.walls.disk_observations) {
      if (observation.job_id !== input.identity.sidecar_job_id) throw new Error("ISSUE898_SOAK_FOREIGN_WALL_JOB");
      diskObservedAt.push(observation.observed_at_ms);
      const duration = observation.payload["measurement_duration_ms"];
      if (!Number.isSafeInteger(duration) || (duration as number) < 0) throw new Error("ISSUE898_SOAK_DISK_DURATION_MISSING");
      diskDurations.push(duration as number);
    }
    points.push({ x: ts, y: row.census.samples.reduce((sum, sample) => sum + sample.commit_bytes, 0) });
  }
  const startedAtMs = points[0].x;
  const endedAtMs = points.at(-1)!.x;
  if (endedAtMs - startedAtMs < MIN_DURATION_MS) throw new Error("ISSUE898_SOAK_DURATION_SHORT");
  if (!Number.isSafeInteger(input.poll_interval_seconds) || input.poll_interval_seconds < 1 || input.poll_interval_seconds > 60) throw new Error("ISSUE898_SOAK_CADENCE_INVALID");
  const expectedIntervalMs = input.poll_interval_seconds * 1_000;
  if (intervalsMs.some((interval) => interval < expectedIntervalMs * 0.75 || interval > expectedIntervalMs * 1.25)) throw new Error("ISSUE898_SOAK_CADENCE_INVALID");
  if (receiptWrittenAtMs < endedAtMs) throw new Error("ISSUE898_SOAK_RECEIPT_TIME_INVALID");
  if (vramObservedAt.length === 0 || diskDurations.length === 0) throw new Error("ISSUE898_SOAK_WALL_OBSERVATIONS_MISSING");
  const coverageToleranceMs = expectedIntervalMs * 1.25;
  if (Math.min(...vramObservedAt) > startedAtMs + coverageToleranceMs || Math.max(...vramObservedAt) < endedAtMs - coverageToleranceMs
    || Math.min(...diskObservedAt) > startedAtMs + coverageToleranceMs || Math.max(...diskObservedAt) < endedAtMs - coverageToleranceMs) {
    throw new Error("ISSUE898_SOAK_WALL_COVERAGE_INCOMPLETE");
  }
  const settledAtMs = startedAtMs + SETTLE_MS;
  const finalHourAtMs = endedAtMs - FINAL_HOUR_MS;
  const earlyFits = fitWindows(points, settledAtMs, finalHourAtMs);
  const finalFits = fitWindows(points, finalHourAtMs, endedAtMs);
  const base = {
    schema_version: "ember-issue898-installed-cockpit-soak-v1",
    verdict: "MEASURED_NEEDS_INDEPENDENT_ADJUDICATION",
    identity: input.identity,
    started_at: new Date(startedAtMs).toISOString(),
    ended_at: new Date(endedAtMs).toISOString(),
    duration_seconds: (endedAtMs - startedAtMs) / 1_000,
    sample_count: rows.length,
    cadence: { configured_seconds: input.poll_interval_seconds, min_observed_ms: Math.min(...intervalsMs), max_observed_ms: Math.max(...intervalsMs) },
    raw_ledger_sha256: sha256(bytes),
    raw_ledger_bytes: bytes.length,
    settle_seconds: SETTLE_MS / 1_000,
    ols_window_seconds: WINDOW_MS / 1_000,
    early_calibration: { band: band(earlyFits), windows: earlyFits },
    final_hour: { band: band(finalFits), windows: finalFits },
    wall_summary: {
      final_vram_seq: priorVramSeq,
      final_disk_seq: priorDiskSeq,
      vram_outcome_counts: vramOutcomeCounts,
      provider_unavailable_count: vramOutcomeCounts["provider_unavailable"] ?? 0,
      provider_unavailable_debounce_dispositions: debounceDispositions,
      disk_observation_count: diskDurations.length,
      disk_measurement_duration_cap_ms: 250,
      disk_measurement_duration_max_ms: Math.max(...diskDurations),
      disk_measurement_duration_cap_met: diskDurations.every((duration) => duration <= 250),
    },
    negatives: input.negatives,
    receipt_before_restart: { receipt_written_at: input.receipt_written_at, restart_event_count_before_receipt: 0 },
  };
  const receipt = { ...base, receipt_sha256: sha256(canonicalJson(base)) } as InstalledCockpitSoakReceipt;
  try {
    writeFileSync(input.receipt_path, `${JSON.stringify(receipt, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") throw new Error("ISSUE898_SOAK_RECEIPT_EXISTS");
    throw error;
  }
  return receipt;
}

export function verifyInstalledCockpitSoakReceipt(text: string): InstalledCockpitSoakReceipt {
  let parsed: Record<string, unknown>;
  try {
    const value = JSON.parse(text) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    parsed = value as Record<string, unknown>;
  } catch {
    throw new Error("ISSUE898_SOAK_RECEIPT_JSON_INVALID");
  }
  exactKeys(parsed, ["schema_version", "verdict", "identity", "started_at", "ended_at", "duration_seconds", "sample_count", "cadence", "raw_ledger_sha256", "raw_ledger_bytes", "settle_seconds", "ols_window_seconds", "early_calibration", "final_hour", "wall_summary", "negatives", "receipt_before_restart", "receipt_sha256"], "ISSUE898_SOAK_RECEIPT_PROPERTIES_INVALID");
  const { receipt_sha256: claimed, ...base } = parsed;
  if (parsed["schema_version"] !== "ember-issue898-installed-cockpit-soak-v1" || parsed["verdict"] !== "MEASURED_NEEDS_INDEPENDENT_ADJUDICATION") throw new Error("ISSUE898_SOAK_RECEIPT_SCHEMA_INVALID");
  validateIdentity(parsed["identity"] as InstalledCockpitSoakIdentity);
  validateNegatives(parsed["negatives"] as InstalledCockpitSoakNegatives);
  const beforeRestart = parsed["receipt_before_restart"];
  if (!beforeRestart || typeof beforeRestart !== "object" || Array.isArray(beforeRestart)) throw new Error("ISSUE898_SOAK_RECEIPT_BEFORE_RESTART_INVALID");
  exactKeys(beforeRestart, ["receipt_written_at", "restart_event_count_before_receipt"], "ISSUE898_SOAK_RECEIPT_BEFORE_RESTART_INVALID");
  const beforeRestartRow = beforeRestart as Record<string, unknown>;
  if (beforeRestartRow["restart_event_count_before_receipt"] !== 0 || typeof beforeRestartRow["receipt_written_at"] !== "string") throw new Error("ISSUE898_SOAK_RECEIPT_BEFORE_RESTART_INVALID");
  if (typeof parsed["raw_ledger_sha256"] !== "string" || !SHA256.test(parsed["raw_ledger_sha256"])) throw new Error("ISSUE898_SOAK_LEDGER_SHA256_INVALID");
  if (typeof claimed !== "string" || !SHA256.test(claimed) || sha256(canonicalJson(base)) !== claimed) throw new Error("ISSUE898_SOAK_RECEIPT_SHA256_INVALID");
  return parsed as InstalledCockpitSoakReceipt;
}

export function verifyInstalledCockpitSoakCustody(
  receiptText: string,
  rawLedger: string | Buffer,
): InstalledCockpitSoakReceipt {
  const receipt = verifyInstalledCockpitSoakReceipt(receiptText);
  const bytes = Buffer.isBuffer(rawLedger) ? rawLedger : Buffer.from(rawLedger, "utf8");
  if (receipt.raw_ledger_sha256 !== sha256(bytes) || receipt.raw_ledger_bytes !== bytes.length) throw new Error("ISSUE898_SOAK_LEDGER_CUSTODY_INVALID");
  return receipt;
}
