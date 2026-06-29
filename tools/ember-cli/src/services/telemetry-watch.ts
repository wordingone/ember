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

import { readFile } from "fs/promises";

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
  lastTs: string;
}

// ---------------------------------------------------------------------------
// Watcher state
// ---------------------------------------------------------------------------

export interface TelemetryState {
  recentEvents: TelemetryEvent[];
  lastGovernor?: GovernorSnapshot;
  activeRun?: ActiveRunState;
}

// Module-level state (singleton watcher)
let _state: TelemetryState = { recentEvents: [] };
let _byteOffset = 0;
let _lineBuffer = "";
let _intervalHandle: ReturnType<typeof setInterval> | null = null;

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

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

  const ts =
    typeof ev["ts"] === "string" ? ev["ts"] : new Date(clock()).toISOString();
  const kind = typeof ev["kind"] === "string" ? ev["kind"] : "unknown";
  const source = typeof ev["source"] === "string" ? ev["source"] : "";
  const payload =
    ev["payload"] != null && typeof ev["payload"] === "object"
      ? (ev["payload"] as Record<string, unknown>)
      : {};

  const event: TelemetryEvent = { ts, kind, source, payload };
  pushEvent(event);

  if (kind === "governor") {
    const free =
      typeof payload["free_gib"] === "number" ? payload["free_gib"] : 0;
    const total =
      typeof payload["total_gib"] === "number" ? payload["total_gib"] : 0;
    const fraction =
      typeof payload["vram_fraction_applied"] === "number"
        ? payload["vram_fraction_applied"]
        : 0;
    _state.lastGovernor = {
      vramUsedGib: total - free,
      vramTotalGib: total,
      fractionApplied: fraction,
    };
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
    _state.activeRun = { runId, step, totalSteps, loss, stepMs, lastTs: ts };
  }
}

function checkActiveRunExpiry(clock: () => number): void {
  if (!_state.activeRun) return;
  const lastMs = new Date(_state.activeRun.lastTs).getTime();
  if (clock() - lastMs > ACTIVE_RUN_TTL_MS) {
    _state.activeRun = undefined;
  }
}

async function pollOnce(path: string, clock: () => number): Promise<void> {
  let buf: Buffer;
  try {
    buf = await readFile(path);
  } catch {
    return;
  }

  if (buf.length === 0) {
    checkActiveRunExpiry(clock);
    return;
  }

  if (buf.length <= _byteOffset) {
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
  _state = { recentEvents: [] };
  _byteOffset = 0;
  _lineBuffer = "";

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
