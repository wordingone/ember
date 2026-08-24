// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue: #898 renderer/census evidence consumer

import { createHash } from "node:crypto";
import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  writeSync,
} from "node:fs";
import path from "node:path";
import { verifyInstalledCockpitSoakCustody } from "./issue898-installed-cockpit-soak.ts";
import { linearFit } from "./ols-fit.ts";

export const ISSUE898_RUNTIME_ORIGIN_TOLERANCE_MS = 5_000;
export const ISSUE898_RENDERER_STALE_MS = 60_000;
export const ISSUE898_SETTLE_MS = 60_000;
export const ISSUE898_WINDOW_MS = 300_000;

const SOURCE_COMMIT = /^[0-9a-f]{40}$/;
const POSITIVE_DECIMAL = /^[1-9][0-9]*$/;

const RENDERER_ROW_KEYS = [
  "schema_version", "sequence", "captured_at", "captured_at_ms", "source_commit", "pid",
  "runtime_origin_token", "render_calls", "render_passes", "backpressured_coalesces",
  "full_repaints", "rendered_frame_utf8_bytes", "diff_cells", "optimized_runs",
  "stream_write_calls", "submitted_utf8_bytes", "write_false_events", "drain_repaints",
  "style_pool_size", "hyperlink_pool_size",
] as const;

const POLL_ROW_KEYS = ["schema_version", "sequence", "census", "walls"] as const;
const CENSUS_KEYS = [
  "schema_version", "observed_at", "provider", "candidate_process_count",
  "admitted_process_count", "class_cardinality", "ownership_overlap", "samples",
] as const;
const CENSUS_SAMPLE_KEYS = [
  "process_class", "pid", "parent_pid", "process_name", "process_start_token",
  "provider", "commit_bytes", "ownership_basis",
] as const;
const CLASS_CARDINALITY_KEYS = ["cockpit", "brain_server"] as const;
const OWNERSHIP_OVERLAP_KEYS = ["count", "pids"] as const;

const RENDERER_COUNTERS = [
  "render_calls",
  "render_passes",
  "backpressured_coalesces",
  "full_repaints",
  "rendered_frame_utf8_bytes",
  "diff_cells",
  "optimized_runs",
  "stream_write_calls",
  "submitted_utf8_bytes",
  "write_false_events",
  "drain_repaints",
] as const;

const FIT_METRICS = [
  "commit_bytes",
  "render_calls",
  "render_passes",
  "rendered_frame_utf8_bytes",
  "diff_cells",
  "optimized_runs",
  "stream_write_calls",
  "submitted_utf8_bytes",
  "backpressured_coalesces",
  "write_false_events",
  "drain_repaints",
] as const;

type RendererCounter = typeof RENDERER_COUNTERS[number];
type FitMetric = typeof FIT_METRICS[number];

interface RendererRow extends Record<RendererCounter, number> {
  schema_version: "ember-renderer-diagnostic-v1";
  sequence: number;
  captured_at: string;
  captured_at_ms: number;
  source_commit: string;
  pid: number;
  runtime_origin_token: string;
  style_pool_size: number;
  hyperlink_pool_size: number;
}

interface CensusSample {
  process_class: "cockpit" | "brain_server";
  pid: number;
  process_start_token: string;
  commit_bytes: number;
}

interface PollRow {
  schema_version: "ember-issue898-installed-cockpit-soak-poll-v1";
  sequence: number;
  census: {
    observed_at: string;
    admitted_process_count: number;
    class_cardinality: { cockpit: number; brain_server: number };
    ownership_overlap: { count: number; pids: number[] };
    samples: CensusSample[];
  };
}

interface Anchor {
  observedAt: string;
  observedAtMs: number;
  commitBytes: number;
  renderer: RendererRow;
  rendererStalenessMs: number;
}

export interface Issue898RendererCensusEvidenceInput {
  soakReceiptPath: string;
  pollsPath: string;
  rendererPath: string;
  outputPath: string;
  sourceCommit: string;
  cockpitPid: number;
  cockpitProcessStartToken: string;
  receiptWrittenAt: string;
}

export interface Issue898RendererCensusEvidenceBindings {
  soakReceiptText: string;
  pollsText: string;
  rendererText: string;
  sourceCommit: string;
  cockpitPid: number;
  cockpitProcessStartToken: string;
}

export interface EvidenceFit {
  sample_count: number;
  slope_per_second: number;
  intercept: number;
  r2: number;
  slope_standard_error: number;
}

export interface EvidenceFitGroup {
  started_at: string;
  ended_at: string;
  sample_count: number;
  fits: Record<FitMetric, EvidenceFit>;
  normalized_ratios: {
    commit_bytes_per_render_pass: number | null;
    commit_bytes_per_submitted_utf8_byte: number | null;
  };
}

export interface EvidenceInterval {
  started_at: string;
  ended_at: string;
  elapsed_seconds: number;
  renderer_start_sequence: number;
  renderer_end_sequence: number;
  renderer_staleness_ms: number;
  stale_over_60s: boolean;
  commit_delta_bytes: number;
  commit_bytes_per_second: number;
  render_call_delta: number;
  render_calls_per_second: number;
  render_pass_delta: number;
  render_passes_per_second: number;
  rendered_frame_utf8_byte_delta: number;
  rendered_frame_utf8_bytes_per_second: number;
  diff_cell_delta: number;
  diff_cells_per_second: number;
  optimized_run_delta: number;
  optimized_runs_per_second: number;
  stream_write_delta: number;
  stream_writes_per_second: number;
  submitted_utf8_byte_delta: number;
  submitted_utf8_bytes_per_second: number;
  backpressured_coalesce_delta: number;
  backpressured_coalesces_per_second: number;
  write_false_event_delta: number;
  write_false_events_per_second: number;
  drain_repaint_delta: number;
  drain_repaints_per_second: number;
}

export interface Issue898RendererCensusEvidenceReceipt {
  schema_version: "ember-issue898-renderer-census-evidence-v1";
  verdict: "MEASURED_NEEDS_INDEPENDENT_ADJUDICATION";
  inputs: {
    soak_receipt: { path: string; sha256: string; bytes: number };
    polls: { path: string; sha256: string; bytes: number };
    renderer: { path: string; sha256: string; bytes: number };
  };
  identity: {
    source_commit: string;
    cockpit_pid: number;
    cockpit_process_start_token: string;
    renderer_runtime_origin_token: string;
    runtime_origin_delta_ms: number;
    runtime_origin_tolerance_ms: number;
  };
  join_contract: {
    renderer_anchor: "latest_at_or_before_census_timestamp";
    identity_authority: "kernel_census_pid_and_process_start_token";
    runtime_origin_role: "sanity_only";
    renderer_stale_threshold_ms: number;
    settle_ms: number;
    window_ms: number;
  };
  join: {
    anchor_count: number;
    interval_count: number;
    stale_interval_count: number;
    zero_renderer_advance_count: number;
    zero_renderer_advance_positive_commit_count: number;
  };
  intervals: EvidenceInterval[];
  full_run: EvidenceFitGroup;
  settled_windows: EvidenceFitGroup[];
  receipt_written_at: string;
  receipt_sha256: string;
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const row = value as Record<string, unknown>;
  return `{${Object.keys(row).sort().map((key) =>
    `${JSON.stringify(key)}:${canonicalJson(row[key])}`
  ).join(",")}}`;
}

function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function exactKeys(value: unknown, keys: readonly string[], error: string): void {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).sort().join(",") !== [...keys].sort().join(",")) {
    throw new Error(error);
  }
}

function requireCanonicalTimestamp(value: unknown, error: string): number {
  if (typeof value !== "string") throw new Error(error);
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed) || new Date(parsed).toISOString() !== value) throw new Error(error);
  return parsed;
}

function validateInput(input: Issue898RendererCensusEvidenceInput): void {
  for (const value of [input.soakReceiptPath, input.pollsPath, input.rendererPath, input.outputPath]) {
    if (!path.isAbsolute(value)) throw new Error("ISSUE898_RENDERER_CENSUS_PATH_NOT_ABSOLUTE");
  }
  if (!SOURCE_COMMIT.test(input.sourceCommit)) {
    throw new Error("ISSUE898_RENDERER_CENSUS_SOURCE_COMMIT_INVALID");
  }
  if (!Number.isSafeInteger(input.cockpitPid) || input.cockpitPid <= 0) {
    throw new Error("ISSUE898_RENDERER_CENSUS_COCKPIT_PID_INVALID");
  }
  if (!POSITIVE_DECIMAL.test(input.cockpitProcessStartToken)) {
    throw new Error("ISSUE898_RENDERER_CENSUS_COCKPIT_TOKEN_INVALID");
  }
  requireCanonicalTimestamp(
    input.receiptWrittenAt,
    "ISSUE898_RENDERER_CENSUS_RECEIPT_TIME_INVALID",
  );
}

function parseJsonLines<T>(
  text: string,
  unsealedError: string,
  jsonError: string,
  shortError: string,
): T[] {
  if (text.length === 0 || !text.endsWith("\n")) throw new Error(unsealedError);
  let rows: T[];
  try {
    rows = text.trimEnd().split("\n").map((line) => JSON.parse(line) as T);
  } catch {
    throw new Error(jsonError);
  }
  if (rows.length < 3) throw new Error(shortError);
  return rows;
}

function parseRendererRows(text: string, input: Issue898RendererCensusEvidenceInput): RendererRow[] {
  const rows = parseJsonLines<RendererRow>(
    text,
    "ISSUE898_RENDERER_CENSUS_RENDERER_UNSEALED_LINE",
    "ISSUE898_RENDERER_CENSUS_RENDERER_JSON_INVALID",
    "ISSUE898_RENDERER_CENSUS_RENDERER_ROWS_SHORT",
  );
  let previousTime = -1;
  let previous: RendererRow | undefined;
  let runtimeToken: string | undefined;
  for (const [index, row] of rows.entries()) {
    exactKeys(
      row,
      RENDERER_ROW_KEYS,
      "ISSUE898_RENDERER_CENSUS_RENDERER_PROPERTIES_INVALID",
    );
    if (!row || row.schema_version !== "ember-renderer-diagnostic-v1" || row.sequence !== index) {
      throw new Error("ISSUE898_RENDERER_CENSUS_RENDERER_SEQUENCE_INVALID");
    }
    const capturedAtMs = requireCanonicalTimestamp(
      row.captured_at,
      "ISSUE898_RENDERER_CENSUS_RENDERER_TIME_INVALID",
    );
    if (row.captured_at_ms !== capturedAtMs || capturedAtMs <= previousTime) {
      throw new Error("ISSUE898_RENDERER_CENSUS_RENDERER_TIME_NONMONOTONE");
    }
    if (row.source_commit !== input.sourceCommit || row.pid !== input.cockpitPid) {
      throw new Error("ISSUE898_RENDERER_CENSUS_RENDERER_IDENTITY_DRIFT");
    }
    if (!POSITIVE_DECIMAL.test(row.runtime_origin_token)) {
      throw new Error("ISSUE898_RENDERER_CENSUS_RUNTIME_ORIGIN_INVALID");
    }
    runtimeToken ??= row.runtime_origin_token;
    if (row.runtime_origin_token !== runtimeToken) {
      throw new Error("ISSUE898_RENDERER_CENSUS_RUNTIME_ORIGIN_DRIFT");
    }
    for (const counter of RENDERER_COUNTERS) {
      if (!Number.isSafeInteger(row[counter]) || row[counter] < 0) {
        throw new Error("ISSUE898_RENDERER_CENSUS_COUNTER_INVALID");
      }
      if (previous && row[counter] < previous[counter]) {
        throw new Error("ISSUE898_RENDERER_CENSUS_COUNTER_ROLLBACK");
      }
    }
    for (const size of [row.style_pool_size, row.hyperlink_pool_size]) {
      if (!Number.isSafeInteger(size) || size < 0) {
        throw new Error("ISSUE898_RENDERER_CENSUS_POOL_SIZE_INVALID");
      }
    }
    previousTime = capturedAtMs;
    previous = row;
  }
  const deltaMs = Number((BigInt(runtimeToken!) - BigInt(input.cockpitProcessStartToken)) / 10_000n);
  if (deltaMs < 0 || deltaMs > ISSUE898_RUNTIME_ORIGIN_TOLERANCE_MS) {
    throw new Error("ISSUE898_RENDERER_CENSUS_RUNTIME_ORIGIN_OUT_OF_RANGE");
  }
  return rows;
}

function parsePollRows(text: string, input: Issue898RendererCensusEvidenceInput): PollRow[] {
  const rows = parseJsonLines<PollRow>(
    text,
    "ISSUE898_RENDERER_CENSUS_POLLS_UNSEALED_LINE",
    "ISSUE898_RENDERER_CENSUS_POLLS_JSON_INVALID",
    "ISSUE898_RENDERER_CENSUS_POLL_ROWS_SHORT",
  );
  let previousTime = -1;
  for (const [index, row] of rows.entries()) {
    exactKeys(row, POLL_ROW_KEYS, "ISSUE898_RENDERER_CENSUS_POLL_PROPERTIES_INVALID");
    exactKeys(row.census, CENSUS_KEYS, "ISSUE898_RENDERER_CENSUS_CENSUS_PROPERTIES_INVALID");
    exactKeys(
      row.census.class_cardinality,
      CLASS_CARDINALITY_KEYS,
      "ISSUE898_RENDERER_CENSUS_CARDINALITY_PROPERTIES_INVALID",
    );
    exactKeys(
      row.census.ownership_overlap,
      OWNERSHIP_OVERLAP_KEYS,
      "ISSUE898_RENDERER_CENSUS_OVERLAP_PROPERTIES_INVALID",
    );
    for (const sample of row.census.samples) {
      exactKeys(
        sample,
        CENSUS_SAMPLE_KEYS,
        "ISSUE898_RENDERER_CENSUS_SAMPLE_PROPERTIES_INVALID",
      );
    }
    if (!row || row.schema_version !== "ember-issue898-installed-cockpit-soak-poll-v1" || row.sequence !== index) {
      throw new Error("ISSUE898_RENDERER_CENSUS_POLL_SEQUENCE_INVALID");
    }
    const observedAtMs = requireCanonicalTimestamp(
      row.census?.observed_at,
      "ISSUE898_RENDERER_CENSUS_POLL_TIME_INVALID",
    );
    if (observedAtMs <= previousTime) {
      throw new Error("ISSUE898_RENDERER_CENSUS_POLL_TIME_NONMONOTONE");
    }
    if (row.census.admitted_process_count !== 2
      || row.census.class_cardinality?.cockpit !== 1
      || row.census.class_cardinality?.brain_server !== 1
      || row.census.ownership_overlap?.count !== 0) {
      throw new Error("ISSUE898_RENDERER_CENSUS_CENSUS_CARDINALITY_INVALID");
    }
    const cockpit = row.census.samples.find((sample) => sample.process_class === "cockpit");
    const brain = row.census.samples.find((sample) => sample.process_class === "brain_server");
    if (!cockpit || !brain || row.census.samples.length !== 2
      || cockpit.pid !== input.cockpitPid
      || cockpit.process_start_token !== input.cockpitProcessStartToken) {
      throw new Error("ISSUE898_RENDERER_CENSUS_COCKPIT_IDENTITY_DRIFT");
    }
    if (![cockpit.commit_bytes, brain.commit_bytes].every((value) =>
      Number.isSafeInteger(value) && value >= 0
    )) {
      throw new Error("ISSUE898_RENDERER_CENSUS_COMMIT_BYTES_INVALID");
    }
    previousTime = observedAtMs;
  }
  return rows;
}

function anchorsFromRows(polls: PollRow[], renderer: RendererRow[]): Anchor[] {
  const anchors: Anchor[] = [];
  let rendererIndex = 0;
  for (const poll of polls) {
    const observedAtMs = Date.parse(poll.census.observed_at);
    if (observedAtMs < renderer[0]!.captured_at_ms) continue;
    while (rendererIndex + 1 < renderer.length
      && renderer[rendererIndex + 1]!.captured_at_ms <= observedAtMs) rendererIndex += 1;
    const selected = renderer[rendererIndex]!;
    anchors.push({
      observedAt: poll.census.observed_at,
      observedAtMs,
      commitBytes: poll.census.samples.reduce((sum, sample) => sum + sample.commit_bytes, 0),
      renderer: selected,
      rendererStalenessMs: observedAtMs - selected.captured_at_ms,
    });
  }
  return anchors;
}

function evidenceFit(points: ReadonlyArray<{ x: number; y: number }>): EvidenceFit {
  const fit = linearFit(points);
  const meanX = points.reduce((sum, point) => sum + point.x, 0) / points.length;
  const sxx = points.reduce((sum, point) => sum + (point.x - meanX) ** 2, 0);
  const ssResidual = points.reduce(
    (sum, point) => sum + (point.y - (fit.intercept + fit.slope * point.x)) ** 2,
    0,
  );
  const slopeStandardError = Math.sqrt((ssResidual / (points.length - 2)) / sxx);
  return {
    sample_count: points.length,
    slope_per_second: fit.slope,
    intercept: fit.intercept,
    r2: fit.r2,
    slope_standard_error: slopeStandardError,
  };
}

function metricValue(anchor: Anchor, metric: FitMetric): number {
  return metric === "commit_bytes" ? anchor.commitBytes : anchor.renderer[metric];
}

function normalizedRatio(numerator: EvidenceFit, denominator: EvidenceFit): number | null {
  if (Math.abs(denominator.slope_per_second) <= denominator.slope_standard_error) {
    return null;
  }
  return numerator.slope_per_second / denominator.slope_per_second;
}

function fitGroup(anchors: Anchor[]): EvidenceFitGroup {
  const origin = anchors[0]!.observedAtMs;
  const fits = {} as Record<FitMetric, EvidenceFit>;
  for (const metric of FIT_METRICS) {
    fits[metric] = evidenceFit(anchors.map((anchor) => ({
      x: (anchor.observedAtMs - origin) / 1_000,
      y: metricValue(anchor, metric),
    })));
  }
  return {
    started_at: anchors[0]!.observedAt,
    ended_at: anchors.at(-1)!.observedAt,
    sample_count: anchors.length,
    fits,
    normalized_ratios: {
      commit_bytes_per_render_pass: normalizedRatio(fits.commit_bytes, fits.render_passes),
      commit_bytes_per_submitted_utf8_byte: normalizedRatio(fits.commit_bytes, fits.submitted_utf8_bytes),
    },
  };
}

function intervalRows(anchors: Anchor[]): EvidenceInterval[] {
  const rows: EvidenceInterval[] = [];
  for (let index = 1; index < anchors.length; index += 1) {
    const previous = anchors[index - 1]!;
    const current = anchors[index]!;
    const elapsed = (current.observedAtMs - previous.observedAtMs) / 1_000;
    const delta = (counter: RendererCounter) => current.renderer[counter] - previous.renderer[counter];
    const rate = (value: number) => value / elapsed;
    const renderCallDelta = delta("render_calls");
    const renderPassDelta = delta("render_passes");
    const renderedFrameDelta = delta("rendered_frame_utf8_bytes");
    const diffCellDelta = delta("diff_cells");
    const optimizedRunDelta = delta("optimized_runs");
    const streamWriteDelta = delta("stream_write_calls");
    const submittedDelta = delta("submitted_utf8_bytes");
    const coalesceDelta = delta("backpressured_coalesces");
    const writeFalseDelta = delta("write_false_events");
    const drainDelta = delta("drain_repaints");
    const commitDelta = current.commitBytes - previous.commitBytes;
    rows.push({
      started_at: previous.observedAt,
      ended_at: current.observedAt,
      elapsed_seconds: elapsed,
      renderer_start_sequence: previous.renderer.sequence,
      renderer_end_sequence: current.renderer.sequence,
      renderer_staleness_ms: current.rendererStalenessMs,
      stale_over_60s: current.rendererStalenessMs > ISSUE898_RENDERER_STALE_MS,
      commit_delta_bytes: commitDelta,
      commit_bytes_per_second: rate(commitDelta),
      render_call_delta: renderCallDelta,
      render_calls_per_second: rate(renderCallDelta),
      render_pass_delta: renderPassDelta,
      render_passes_per_second: rate(renderPassDelta),
      rendered_frame_utf8_byte_delta: renderedFrameDelta,
      rendered_frame_utf8_bytes_per_second: rate(renderedFrameDelta),
      diff_cell_delta: diffCellDelta,
      diff_cells_per_second: rate(diffCellDelta),
      optimized_run_delta: optimizedRunDelta,
      optimized_runs_per_second: rate(optimizedRunDelta),
      stream_write_delta: streamWriteDelta,
      stream_writes_per_second: rate(streamWriteDelta),
      submitted_utf8_byte_delta: submittedDelta,
      submitted_utf8_bytes_per_second: rate(submittedDelta),
      backpressured_coalesce_delta: coalesceDelta,
      backpressured_coalesces_per_second: rate(coalesceDelta),
      write_false_event_delta: writeFalseDelta,
      write_false_events_per_second: rate(writeFalseDelta),
      drain_repaint_delta: drainDelta,
      drain_repaints_per_second: rate(drainDelta),
    });
  }
  return rows;
}

function settledWindows(anchors: Anchor[]): EvidenceFitGroup[] {
  const windows: EvidenceFitGroup[] = [];
  const last = anchors.at(-1)!.observedAtMs;
  for (let start = anchors[0]!.observedAtMs + ISSUE898_SETTLE_MS;
    start + ISSUE898_WINDOW_MS <= last;
    start += ISSUE898_WINDOW_MS) {
    const selected = anchors.filter((anchor) =>
      anchor.observedAtMs >= start && anchor.observedAtMs <= start + ISSUE898_WINDOW_MS
    );
    if (selected.length >= 3) windows.push(fitGroup(selected));
  }
  return windows;
}

function inputBinding(filePath: string, bytes: Buffer) {
  return { path: path.resolve(filePath), sha256: sha256(bytes), bytes: bytes.length };
}

function buildReceipt(
  input: Issue898RendererCensusEvidenceInput,
  soakBytes: Buffer,
  pollsBytes: Buffer,
  rendererBytes: Buffer,
): Issue898RendererCensusEvidenceReceipt {
  const soakText = soakBytes.toString("utf8");
  const pollsText = pollsBytes.toString("utf8");
  const rendererText = rendererBytes.toString("utf8");
  const soakReceipt = verifyInstalledCockpitSoakCustody(soakText, pollsBytes) as Record<string, unknown>;
  const soakIdentity = soakReceipt.identity as Record<string, unknown>;
  if (soakIdentity.source_commit !== input.sourceCommit
    || soakIdentity.cockpit_pid !== input.cockpitPid
    || soakIdentity.cockpit_process_start_token !== input.cockpitProcessStartToken) {
    throw new Error("ISSUE898_RENDERER_CENSUS_SOAK_IDENTITY_DRIFT");
  }
  const polls = parsePollRows(pollsText, input);
  const renderer = parseRendererRows(rendererText, input);
  const anchors = anchorsFromRows(polls, renderer);
  const intervals = intervalRows(anchors);
  const runtimeToken = renderer[0]!.runtime_origin_token;
  const runtimeDeltaMs = Number((BigInt(runtimeToken) - BigInt(input.cockpitProcessStartToken)) / 10_000n);
  const base = {
    schema_version: "ember-issue898-renderer-census-evidence-v1" as const,
    verdict: "MEASURED_NEEDS_INDEPENDENT_ADJUDICATION" as const,
    inputs: {
      soak_receipt: inputBinding(input.soakReceiptPath, soakBytes),
      polls: inputBinding(input.pollsPath, pollsBytes),
      renderer: inputBinding(input.rendererPath, rendererBytes),
    },
    identity: {
      source_commit: input.sourceCommit,
      cockpit_pid: input.cockpitPid,
      cockpit_process_start_token: input.cockpitProcessStartToken,
      renderer_runtime_origin_token: runtimeToken,
      runtime_origin_delta_ms: runtimeDeltaMs,
      runtime_origin_tolerance_ms: ISSUE898_RUNTIME_ORIGIN_TOLERANCE_MS,
    },
    join_contract: {
      renderer_anchor: "latest_at_or_before_census_timestamp" as const,
      identity_authority: "kernel_census_pid_and_process_start_token" as const,
      runtime_origin_role: "sanity_only" as const,
      renderer_stale_threshold_ms: ISSUE898_RENDERER_STALE_MS,
      settle_ms: ISSUE898_SETTLE_MS,
      window_ms: ISSUE898_WINDOW_MS,
    },
    join: {
      anchor_count: anchors.length,
      interval_count: intervals.length,
      stale_interval_count: intervals.filter((row) => row.stale_over_60s).length,
      zero_renderer_advance_count: intervals.filter((row) =>
        row.renderer_start_sequence === row.renderer_end_sequence
      ).length,
      zero_renderer_advance_positive_commit_count: intervals.filter((row) =>
        row.renderer_start_sequence === row.renderer_end_sequence && row.commit_delta_bytes > 0
      ).length,
    },
    intervals,
    full_run: fitGroup(anchors),
    settled_windows: settledWindows(anchors),
    receipt_written_at: input.receiptWrittenAt,
  };
  return { ...base, receipt_sha256: sha256(canonicalJson(base)) };
}

function validateEvidenceRoot(input: Issue898RendererCensusEvidenceInput): string {
  const armRoot = path.dirname(path.dirname(path.resolve(input.pollsPath)));
  const evidenceRoot = path.dirname(path.resolve(input.outputPath));
  const armPrefix = armRoot.endsWith(path.sep) ? armRoot : `${armRoot}${path.sep}`;
  if (path.dirname(evidenceRoot) !== path.dirname(armRoot)
    || evidenceRoot === armRoot
    || evidenceRoot.startsWith(armPrefix)) {
    throw new Error("ISSUE898_RENDERER_CENSUS_OUTPUT_ROOT_INVALID");
  }
  if (existsSync(evidenceRoot)) {
    throw new Error("ISSUE898_RENDERER_CENSUS_OUTPUT_ROOT_EXISTS");
  }
  return evidenceRoot;
}

export function sealIssue898RendererCensusEvidence(
  input: Issue898RendererCensusEvidenceInput,
): Issue898RendererCensusEvidenceReceipt {
  validateInput(input);
  const evidenceRoot = validateEvidenceRoot(input);
  const soakBytes = readFileSync(input.soakReceiptPath);
  const pollsBytes = readFileSync(input.pollsPath);
  const rendererBytes = readFileSync(input.rendererPath);
  const receipt = buildReceipt(input, soakBytes, pollsBytes, rendererBytes);
  mkdirSync(evidenceRoot);
  const handle = openSync(input.outputPath, "wx");
  try {
    writeSync(handle, `${JSON.stringify(receipt, null, 2)}\n`, undefined, "utf8");
    fsyncSync(handle);
  } finally {
    closeSync(handle);
  }
  return receipt;
}

export function verifyIssue898RendererCensusEvidenceReceipt(
  text: string,
  bindings?: Issue898RendererCensusEvidenceBindings,
): Issue898RendererCensusEvidenceReceipt {
  let receipt: Issue898RendererCensusEvidenceReceipt;
  try {
    receipt = JSON.parse(text) as Issue898RendererCensusEvidenceReceipt;
  } catch {
    throw new Error("ISSUE898_RENDERER_CENSUS_RECEIPT_JSON_INVALID");
  }
  if (!receipt || receipt.schema_version !== "ember-issue898-renderer-census-evidence-v1"
    || receipt.verdict !== "MEASURED_NEEDS_INDEPENDENT_ADJUDICATION") {
    throw new Error("ISSUE898_RENDERER_CENSUS_RECEIPT_SCHEMA_INVALID");
  }
  const { receipt_sha256: claimed, ...base } = receipt;
  if (typeof claimed !== "string" || sha256(canonicalJson(base)) !== claimed) {
    throw new Error("ISSUE898_RENDERER_CENSUS_RECEIPT_SHA256_INVALID");
  }
  if (bindings) {
    verifyInstalledCockpitSoakCustody(bindings.soakReceiptText, bindings.pollsText);
    if (receipt.inputs.soak_receipt.sha256 !== sha256(bindings.soakReceiptText)
      || receipt.inputs.soak_receipt.bytes !== Buffer.byteLength(bindings.soakReceiptText)
      || receipt.inputs.polls.sha256 !== sha256(bindings.pollsText)
      || receipt.inputs.polls.bytes !== Buffer.byteLength(bindings.pollsText)
      || receipt.inputs.renderer.sha256 !== sha256(bindings.rendererText)
      || receipt.inputs.renderer.bytes !== Buffer.byteLength(bindings.rendererText)
      || receipt.identity.source_commit !== bindings.sourceCommit
      || receipt.identity.cockpit_pid !== bindings.cockpitPid
      || receipt.identity.cockpit_process_start_token !== bindings.cockpitProcessStartToken) {
      throw new Error("ISSUE898_RENDERER_CENSUS_RECEIPT_BINDING_INVALID");
    }
  }
  return receipt;
}
