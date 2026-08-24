// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue #898: optional renderer-work/byte counters for matched installed-cockpit diagnostics.

import fs from "node:fs";
import path from "node:path";
import { performance } from "node:perf_hooks";

export const RENDER_DIAGNOSTIC_ENV = "EMBER_RENDER_DIAGNOSTIC_PATH";
export const RENDER_DIAGNOSTIC_SOURCE_ENV = "EMBER_PUBLIC_SOURCE_COMMIT";
export const DEFAULT_RENDER_DIAGNOSTIC_EMIT_MS = 30_000;

const DOTNET_UNIX_EPOCH_TICKS = 621_355_968_000_000_000n;

export interface RendererDiagnosticRow {
  schema_version: "ember-renderer-diagnostic-v1";
  sequence: number;
  captured_at: string;
  captured_at_ms: number;
  source_commit: string;
  pid: number;
  process_start_token: string;
  render_calls: number;
  render_passes: number;
  backpressured_coalesces: number;
  full_repaints: number;
  rendered_frame_utf8_bytes: number;
  diff_cells: number;
  optimized_runs: number;
  stream_write_calls: number;
  submitted_utf8_bytes: number;
  write_false_events: number;
  drain_repaints: number;
  style_pool_size: number;
  hyperlink_pool_size: number;
}

export interface RendererDiagnosticOptions {
  filePath: string;
  sourceCommit: string;
  now?: () => number;
  emitEveryMs?: number;
  onError?: (error: Error) => void;
  processStartTimeOriginMs?: number;
}

export interface RendererDiagnostic {
  readonly filePath: string;
  recordRenderCall(coalesced: boolean): void;
  recordRenderPass(sample: {
    fullRepaint: boolean;
    renderedFrameUtf8Bytes: number;
    diffCells: number;
    optimizedRuns: number;
  }): void;
  recordStreamWrite(submittedUtf8Bytes: number, accepted: boolean): void;
  recordDrainRepaint(): void;
  maybeEmit(stylePoolSize: number, hyperlinkPoolSize: number): void;
  close(): void;
}

/** Converts the runtime's process time origin to the same UTC DateTime-ticks shape Get-Process uses. */
export function processStartToken(timeOriginMs: number = performance.timeOrigin): string {
  const finite = Number.isFinite(timeOriginMs)
    ? timeOriginMs
    : Date.now() - process.uptime() * 1000;
  const wholeMs = Math.floor(finite);
  let fractionalTicks = Math.round((finite - wholeMs) * 10_000);
  let carriedMs = wholeMs;
  if (fractionalTicks >= 10_000) {
    carriedMs += 1;
    fractionalTicks -= 10_000;
  }
  return (
    DOTNET_UNIX_EPOCH_TICKS
    + BigInt(carriedMs) * 10_000n
    + BigInt(Math.max(0, fractionalTicks))
  ).toString();
}

export function createRendererDiagnostic(options: RendererDiagnosticOptions): RendererDiagnostic {
  if (!path.isAbsolute(options.filePath)) throw new Error("RENDER_DIAGNOSTIC_PATH_NOT_ABSOLUTE");
  if (!/^[0-9a-f]{40}$/i.test(options.sourceCommit)) throw new Error("RENDER_DIAGNOSTIC_SOURCE_COMMIT_INVALID");
  const parent = path.dirname(options.filePath);
  let parentStat: fs.Stats;
  try {
    parentStat = fs.statSync(parent);
  } catch {
    throw new Error("RENDER_DIAGNOSTIC_PARENT_MISSING");
  }
  if (!parentStat.isDirectory()) throw new Error("RENDER_DIAGNOSTIC_PARENT_NOT_DIRECTORY");

  let fd: number;
  try {
    fd = fs.openSync(options.filePath, "wx");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      throw new Error("RENDER_DIAGNOSTIC_PATH_EXISTS");
    }
    throw error;
  }

  const now = options.now ?? Date.now;
  const emitEveryMs = Math.max(1, options.emitEveryMs ?? DEFAULT_RENDER_DIAGNOSTIC_EMIT_MS);
  const startToken = processStartToken(options.processStartTimeOriginMs);
  let lastEmitMs = now();
  let sequence = 0;
  let disabled = false;
  let closed = false;
  const counters = {
    renderCalls: 0,
    renderPasses: 0,
    backpressuredCoalesces: 0,
    fullRepaints: 0,
    renderedFrameUtf8Bytes: 0,
    diffCells: 0,
    optimizedRuns: 0,
    streamWriteCalls: 0,
    submittedUtf8Bytes: 0,
    writeFalseEvents: 0,
    drainRepaints: 0,
  };

  const disable = (error: unknown): void => {
    if (disabled) return;
    disabled = true;
    options.onError?.(error instanceof Error ? error : new Error(String(error)));
  };

  return {
    filePath: options.filePath,
    recordRenderCall(coalesced): void {
      counters.renderCalls += 1;
      if (coalesced) counters.backpressuredCoalesces += 1;
    },
    recordRenderPass(sample): void {
      counters.renderPasses += 1;
      if (sample.fullRepaint) counters.fullRepaints += 1;
      counters.renderedFrameUtf8Bytes += sample.renderedFrameUtf8Bytes;
      counters.diffCells += sample.diffCells;
      counters.optimizedRuns += sample.optimizedRuns;
    },
    recordStreamWrite(submittedUtf8Bytes, accepted): void {
      counters.streamWriteCalls += 1;
      counters.submittedUtf8Bytes += submittedUtf8Bytes;
      if (!accepted) counters.writeFalseEvents += 1;
    },
    recordDrainRepaint(): void {
      counters.drainRepaints += 1;
    },
    maybeEmit(stylePoolSize, hyperlinkPoolSize): void {
      if (disabled || closed) return;
      const capturedAtMs = now();
      if (capturedAtMs - lastEmitMs < emitEveryMs) return;
      const row: RendererDiagnosticRow = {
        schema_version: "ember-renderer-diagnostic-v1",
        sequence,
        captured_at: new Date(capturedAtMs).toISOString(),
        captured_at_ms: capturedAtMs,
        source_commit: options.sourceCommit.toLowerCase(),
        pid: process.pid,
        process_start_token: startToken,
        render_calls: counters.renderCalls,
        render_passes: counters.renderPasses,
        backpressured_coalesces: counters.backpressuredCoalesces,
        full_repaints: counters.fullRepaints,
        rendered_frame_utf8_bytes: counters.renderedFrameUtf8Bytes,
        diff_cells: counters.diffCells,
        optimized_runs: counters.optimizedRuns,
        stream_write_calls: counters.streamWriteCalls,
        submitted_utf8_bytes: counters.submittedUtf8Bytes,
        write_false_events: counters.writeFalseEvents,
        drain_repaints: counters.drainRepaints,
        style_pool_size: stylePoolSize,
        hyperlink_pool_size: hyperlinkPoolSize,
      };
      try {
        fs.writeSync(fd, `${JSON.stringify(row)}\n`, null, "utf8");
        sequence += 1;
        lastEmitMs = capturedAtMs;
      } catch (error) {
        disable(error);
      }
    },
    close(): void {
      if (closed) return;
      closed = true;
      try { fs.closeSync(fd); } catch (error) { disable(error); }
    },
  };
}

export function createRendererDiagnosticFromEnv(
  env: NodeJS.ProcessEnv = process.env,
  onError?: (error: Error) => void,
): RendererDiagnostic | undefined {
  const filePath = env[RENDER_DIAGNOSTIC_ENV];
  if (!filePath) return undefined;
  const sourceCommit = env[RENDER_DIAGNOSTIC_SOURCE_ENV];
  if (!sourceCommit) throw new Error("RENDER_DIAGNOSTIC_SOURCE_COMMIT_MISSING");
  return createRendererDiagnostic({ filePath, sourceCommit, onError });
}
