// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/telemetry-watch.ts — tail-polling watcher for the ember telemetry channel.
//
// Reads the shared telemetry JSONL file on a 500ms interval, parses newly-appended
// lines, and maintains:
//   - A ring buffer of the last 200 raw events.
//   - The latest governor snapshot (VRAM usage, fraction applied).
//   - The latest active training run (step, loss, elapsed).
//
// The watcher is steerable: consumers call startTelemetryWatch() and hold the
// returned handle.stop() to tear it down cleanly.

import { createHash } from "node:crypto";
import { readFile, stat } from "fs/promises";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Default path to the telemetry JSONL channel file. */
export const DEFAULT_CHANNEL_PATH = "state/ember-telemetry.jsonl";

/** Poll interval in ms. */
export const POLL_INTERVAL_MS = 500;

/** Maximum number of events to retain in the ring buffer. */
export const RING_BUFFER_CAP = 200;

/**
 * How long (ms) with no train_step events before an active run is considered stale
 * and cleared from state.
 */
export const ACTIVE_RUN_TTL_MS = 30_000;

// ---------------------------------------------------------------------------
// Event types
// ---------------------------------------------------------------------------

/** A single parsed event from the telemetry channel. */
export interface TelemetryEvent {
  ts: string;
  kind: string;
  source: string;
  payload: Record<string, unknown>;
}

/** VRAM / governor snapshot extracted from governor-kind events. */
export interface GovernorSnapshot {
  runId?: string;
  vramUsedGib: number;
  vramTotalGib: number;
  fractionApplied: number;
}

/** Active training run state extracted from train_step events. */
export interface ActiveRunState {
  runId: string;
  step: number;
  totalSteps?: number;
  loss?: number;
  stepMs?: number;
  tokensPerSecond?: number;
  learningRate?: number;
  gpuUuid?: string;
  gpuWatts?: number;
  boardEnergyJoulesTotal?: number;
  energyStatus?: "MEASURED" | "UNAVAILABLE";
  lastTs: string;
}

export interface CheckpointState {
  runId: string;
  step: number;
  checkpointManifestSha256: string;
  lastTs: string;
}

export interface RunStatusState {
  runId: string;
  phase: string;
  modelChat: string;
  restoreNotBefore?: string;
  lastTs: string;
}

// ---------------------------------------------------------------------------
// Watcher state
// ---------------------------------------------------------------------------

export interface TelemetryState {
  recentEvents: TelemetryEvent[];
  channelStatus?: "UNKNOWN" | "ONLINE" | "OFFLINE";
  lastGovernor?: GovernorSnapshot;
  activeRun?: ActiveRunState;
  lastCheckpoint?: CheckpointState;
  runStatus?: RunStatusState;
}

// Module-level state (singleton watcher)
let _state: TelemetryState = { recentEvents: [] };
let _byteOffset = 0;
let _lineBuffer = "";
let _fileIdentity: string | undefined;
let _prefixDigest: string | undefined;
let _intervalHandle: ReturnType<typeof setInterval> | null = null;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function validVram(free: unknown, total: unknown): { free: number; total: number } | undefined {
  if (typeof free !== "number" || !Number.isFinite(free)) return undefined;
  if (typeof total !== "number" || !Number.isFinite(total)) return undefined;
  if (free < 0 || total <= 0 || free > total) return undefined;
  return { free, total };
}

function pushEvent(event: TelemetryEvent): void {
  _state.recentEvents.push(event);
  if (_state.recentEvents.length > RING_BUFFER_CAP) {
    _state.recentEvents.shift();
  }
}

function processLine(line: string, clock: () => number): void {
  let parsed: unknown;
  try {
    parsed = JSON.parse(line);
  } catch {
    return;
  }

  if (!parsed || typeof parsed !== "object") return;

  const ev = parsed as Record<string, unknown>;

  const ts = typeof ev["ts"] === "string" ? ev["ts"] : undefined;
  const eventTimestamp = ts ? Date.parse(ts) : NaN;
  if (!ts || !Number.isFinite(eventTimestamp) || eventTimestamp > clock()) return;
  const kind = typeof ev["kind"] === "string" ? ev["kind"] : "unknown";
  const source = typeof ev["source"] === "string" ? ev["source"] : "";
  const payload =
    ev["payload"] != null && typeof ev["payload"] === "object"
      ? (ev["payload"] as Record<string, unknown>)
      : {};

  const event: TelemetryEvent = { ts, kind, source, payload };
  pushEvent(event);

  if (kind === "governor") {
    const free = payload["free_gib"];
    const total = payload["total_gib"];
    const fraction = typeof payload["vram_fraction_applied"] === "number" && Number.isFinite(payload["vram_fraction_applied"])
      ? payload["vram_fraction_applied"]
      : 0;
    const runId = typeof payload["run_id"] === "string" && payload["run_id"].length > 0 ? payload["run_id"] : undefined;
    const vram = validVram(free, total);
    if (vram) {
      _state.lastGovernor = {
        ...(runId ? { runId } : {}),
        vramUsedGib: vram.total - vram.free,
        vramTotalGib: vram.total,
        fractionApplied: fraction,
      };
    }
  } else if (kind === "train_step") {
    const runId =
      typeof payload["run_id"] === "string" ? payload["run_id"] : "";
    const step =
      typeof payload["step"] === "number" ? payload["step"] : 0;
    const totalSteps =
      typeof payload["total_steps"] === "number"
        ? payload["total_steps"]
        : undefined;
    const loss =
      typeof payload["loss"] === "number" ? payload["loss"] : undefined;
    const stepMs =
      typeof payload["step_ms"] === "number" ? payload["step_ms"] : undefined;
    const nonnegative = (value: unknown): number | undefined =>
      typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : undefined;
    const tokensPerSecond = nonnegative(payload["tokens_per_second"]);
    const learningRate = nonnegative(payload["learning_rate"]);
    const gpuWatts = nonnegative(payload["gpu_watts"]);
    const boardEnergyJoulesTotal = nonnegative(payload["board_energy_joules_total"]);
    const gpuUuid = typeof payload["gpu_uuid"] === "string" && payload["gpu_uuid"].length > 0
      ? payload["gpu_uuid"] : undefined;
    const energyStatus = payload["energy_status"] === "MEASURED" || payload["energy_status"] === "UNAVAILABLE"
      ? payload["energy_status"] : undefined;
    const measuredEnergy = energyStatus === "MEASURED" && gpuUuid && gpuWatts !== undefined && boardEnergyJoulesTotal !== undefined;
    _state.activeRun = {
      runId, step, totalSteps, loss, stepMs, tokensPerSecond, learningRate,
      ...(measuredEnergy ? { gpuUuid, gpuWatts, boardEnergyJoulesTotal, energyStatus: "MEASURED" as const }
        : energyStatus === "UNAVAILABLE" ? { energyStatus: "UNAVAILABLE" as const } : {}),
      lastTs: ts,
    };
    const free = typeof payload["free_gib"] === "number" ? payload["free_gib"] : undefined;
    const total = typeof payload["total_gib"] === "number" ? payload["total_gib"] : undefined;
    const vram = validVram(free, total);
    if (vram) {
      const governorRunId = typeof payload["run_id"] === "string" && payload["run_id"].length > 0 ? payload["run_id"] : undefined;
      _state.lastGovernor = {
        ...(governorRunId ? { runId: governorRunId } : {}),
        vramUsedGib: vram.total - vram.free,
        vramTotalGib: vram.total,
        fractionApplied: typeof payload["vram_fraction_applied"] === "number" && Number.isFinite(payload["vram_fraction_applied"])
          ? payload["vram_fraction_applied"]
          : 0,
      };
    }
  } else if (kind === "checkpoint") {
    const runId = typeof payload["run_id"] === "string" ? payload["run_id"] : "";
    const step = typeof payload["step"] === "number" ? payload["step"] : 0;
    const digest = typeof payload["checkpoint_manifest_sha256"] === "string"
      ? payload["checkpoint_manifest_sha256"]
      : "";
    if (runId && step > 0 && /^[0-9a-f]{64}$/.test(digest)) {
      _state.lastCheckpoint = { runId, step, checkpointManifestSha256: digest, lastTs: ts };
    }
  } else if (kind === "run_status") {
    const runId = typeof payload["run_id"] === "string" ? payload["run_id"] : "";
    const phase = typeof payload["phase"] === "string" ? payload["phase"] : "";
    const modelChat = typeof payload["model_chat"] === "string" ? payload["model_chat"] : "";
    const restoreNotBefore = typeof payload["restore_not_before"] === "string"
      ? payload["restore_not_before"]
      : undefined;
    if (runId && phase && modelChat) {
      _state.runStatus = { runId, phase, modelChat, restoreNotBefore, lastTs: ts };
    }
  }
}

function checkActiveRunExpiry(clock: () => number): void {
  if (!_state.activeRun) return;
  const lastMs = new Date(_state.activeRun.lastTs).getTime();
  if (clock() - lastMs > ACTIVE_RUN_TTL_MS) {
    _state.activeRun = undefined;
  }
}

function markChannelOffline(): void {
  _state = { ..._state, channelStatus: "OFFLINE", activeRun: undefined };
}

function resetForNewChannelFile(): void {
  _state = { recentEvents: [], channelStatus: "ONLINE" };
  _byteOffset = 0;
  _lineBuffer = "";
  _prefixDigest = undefined;
}

function fileIdentity(info: { dev: number; ino: number; birthtimeMs: number }): string {
  return `${info.dev}:${info.ino}:${info.birthtimeMs}`;
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

async function pollOnce(path: string, clock: () => number): Promise<void> {
  let buf: Buffer;
  let identity: string;
  try {
    const info = await stat(path);
    if (!info.isFile()) throw new Error("telemetry channel is not a regular file");
    identity = fileIdentity(info);
    buf = await readFile(path);
  } catch {
    markChannelOffline();
    return;
  }

  const rotated = _fileIdentity !== undefined && identity !== _fileIdentity;
  const truncated = buf.length < _byteOffset;
  const rewritten = _byteOffset > 0 && _prefixDigest !== undefined &&
    buf.length >= _byteOffset && sha256(buf.subarray(0, _byteOffset)) !== _prefixDigest;
  if (rotated || truncated || rewritten) resetForNewChannelFile();
  _fileIdentity = identity;
  _state = { ..._state, channelStatus: "ONLINE" };

  if (buf.length === 0) {
    _prefixDigest = sha256(buf);
    checkActiveRunExpiry(clock);
    return;
  }

  if (buf.length <= _byteOffset) {
    _prefixDigest = sha256(buf.subarray(0, _byteOffset));
    checkActiveRunExpiry(clock);
    return;
  }

  const newBytes = buf.slice(_byteOffset);
  _byteOffset = buf.length;

  const text = _lineBuffer + newBytes.toString("utf-8");
  _lineBuffer = "";

  const lines = text.split("\n");
  // The last element may be a partial line — stash it for the next poll
  _lineBuffer = lines.pop() ?? "";

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed) processLine(trimmed, clock);
  }

  _prefixDigest = sha256(buf.subarray(0, _byteOffset));
  checkActiveRunExpiry(clock);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Handle returned by startTelemetryWatch(). */
export interface TelemetryWatchHandle {
  /** Stops the polling interval and cleans up. */
  stop: () => void;
}

/** Optional dependency injection for testing. */
export interface TelemetryWatchDeps {
  /** Override the channel file path (default: DEFAULT_CHANNEL_PATH). */
  channelPath?: string;
  /** Override the wall-clock function (default: Date.now). */
  now?: () => number;
}

/**
 * Starts the telemetry polling watcher.
 *
 * If a watcher is already running, it is stopped and replaced.
 * Call handle.stop() to tear down the watcher cleanly.
 *
 * @param deps - Optional overrides for path and clock (for testing).
 * @returns A handle with a stop() method.
 */
export function startTelemetryWatch(
  deps?: TelemetryWatchDeps,
): TelemetryWatchHandle {
  if (_intervalHandle !== null) {
    clearInterval(_intervalHandle);
    _intervalHandle = null;
  }

  const path =
    deps?.channelPath ??
    process.env["EMBER_TELEMETRY_PATH"] ??
    DEFAULT_CHANNEL_PATH;
  const clock = deps?.now ?? Date.now.bind(Date);

  // Reset state for a fresh watch session
  _state = { recentEvents: [], channelStatus: "UNKNOWN" };
  _byteOffset = 0;
  _lineBuffer = "";
  _fileIdentity = undefined;
  _prefixDigest = undefined;

  _intervalHandle = setInterval(() => {
    pollOnce(path, clock);
  }, POLL_INTERVAL_MS);

  return {
    stop: () => {
      if (_intervalHandle !== null) {
        clearInterval(_intervalHandle);
        _intervalHandle = null;
      }
    },
  };
}

/**
 * Returns a shallow copy of the current telemetry state.
 * Safe to call at any time; returns the last-polled snapshot.
 */
export function getState(): TelemetryState {
  return _state;
}
