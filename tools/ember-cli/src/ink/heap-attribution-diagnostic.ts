// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue #898: absent-by-default, pass-bound JS/native retained-allocation attribution.

import fs from "node:fs";
import path from "node:path";
import {
  fullGC,
  gcAndSweep,
  heapStats,
  memoryUsage as jscMemoryUsage,
} from "bun:jsc";

export const HEAP_ATTRIBUTION_ENV = "EMBER_ISSUE898_HEAP_ATTRIBUTION_PATH";
export const HEAP_ATTRIBUTION_SOURCE_ENV = "EMBER_PUBLIC_SOURCE_COMMIT";
export const HEAP_ATTRIBUTION_MILESTONES = [120, 240, 480, 720] as const;
export const HEAP_ATTRIBUTION_SETTLE_MS = 30_000;
export const HEAP_ATTRIBUTION_MAX_MS = 600_000;

type CountMap = Record<string, number>;

export interface HeapAttributionStats {
  heap: {
    heapSize: number;
    heapCapacity: number;
    extraMemorySize: number;
    objectCount: number;
    protectedObjectCount: number;
    globalObjectCount: number;
    protectedGlobalObjectCount: number;
    objectTypeCounts: CountMap;
    protectedObjectTypeCounts: CountMap;
  };
  jscMemory: {
    current: number;
    peak: number;
    currentCommit: number;
    peakCommit: number;
    pageFaults: number;
  };
  processMemory: {
    rss: number;
    heapTotal: number;
    heapUsed: number;
    external: number;
    arrayBuffers: number;
  };
}

export interface HeapAttributionDependencies {
  forceFullCollection(): void;
  collectStats(): HeapAttributionStats;
  collectV8Snapshot(): ArrayBuffer;
}

export interface HeapAttributionRenderSample {
  frameWidth: number;
  frameHeight: number;
  frameCellCount: number;
  patchChanges: number;
  optimizedRuns: number;
  renderedBytes: number;
  patchBufferBytes: number;
  stylePoolSize: number;
  hyperlinkPoolSize: number;
}

export interface HeapAttributionRow {
  schema_version: "ember-issue898-heap-attribution-v1";
  sequence: number;
  captured_at: string;
  captured_at_ms: number;
  source_commit: string;
  pid: number;
  render_passes: number;
  heap: HeapAttributionStats["heap"];
  jsc_memory: HeapAttributionStats["jscMemory"];
  process_memory: HeapAttributionStats["processMemory"];
  renderer: {
    frame_width: number;
    frame_height: number;
    frame_cell_count: number;
    patch_changes: number;
    optimized_runs: number;
    rendered_bytes: number;
    patch_buffer_bytes: number;
    style_pool_size: number;
    hyperlink_pool_size: number;
  };
  snapshot_path: string | null;
}

export interface HeapAttributionDiagnosticOptions {
  filePath: string;
  sourceCommit: string;
  dependencies?: HeapAttributionDependencies;
  now?: () => number;
  onError?: (error: Error) => void;
}

export interface HeapAttributionDiagnostic {
  readonly filePath: string;
  recordRenderPass(sample: HeapAttributionRenderSample): void;
  close(): void;
}

interface BunHeapSnapshotApi {
  generateHeapSnapshot(format: "v8", encoding: "arraybuffer"): ArrayBuffer;
}

const defaultDependencies: HeapAttributionDependencies = {
  forceFullCollection(): void {
    fullGC();
    gcAndSweep();
  },
  collectStats(): HeapAttributionStats {
    const heap = heapStats() as HeapAttributionStats["heap"];
    const jscMemory = jscMemoryUsage() as HeapAttributionStats["jscMemory"];
    const processMemory = process.memoryUsage();
    return {
      heap,
      jscMemory,
      processMemory: {
        rss: processMemory.rss,
        heapTotal: processMemory.heapTotal,
        heapUsed: processMemory.heapUsed,
        external: processMemory.external,
        arrayBuffers: processMemory.arrayBuffers,
      },
    };
  },
  collectV8Snapshot(): ArrayBuffer {
    const bun = (globalThis as unknown as { Bun: BunHeapSnapshotApi }).Bun;
    return bun.generateHeapSnapshot("v8", "arraybuffer");
  },
};

function snapshotPath(filePath: string, pass: number): string {
  return `${filePath}.pass${pass}.heapsnapshot`;
}

function writeExclusive(filePath: string, bytes: ArrayBuffer): void {
  const fd = fs.openSync(filePath, "wx");
  try {
    fs.writeSync(fd, new Uint8Array(bytes));
  } finally {
    fs.closeSync(fd);
  }
}

export function createHeapAttributionDiagnostic(
  options: HeapAttributionDiagnosticOptions,
): HeapAttributionDiagnostic {
  if (!path.isAbsolute(options.filePath)) throw new Error("HEAP_ATTRIBUTION_PATH_NOT_ABSOLUTE");
  if (!/^[0-9a-f]{40}$/i.test(options.sourceCommit)) {
    throw new Error("HEAP_ATTRIBUTION_SOURCE_COMMIT_INVALID");
  }
  const parent = path.dirname(options.filePath);
  let parentStat: fs.Stats;
  try {
    parentStat = fs.statSync(parent);
  } catch {
    throw new Error("HEAP_ATTRIBUTION_PARENT_MISSING");
  }
  if (!parentStat.isDirectory()) throw new Error("HEAP_ATTRIBUTION_PARENT_NOT_DIRECTORY");

  const outputs = [
    options.filePath,
    snapshotPath(options.filePath, 120),
    snapshotPath(options.filePath, 720),
  ];
  if (outputs.some((candidate) => fs.existsSync(candidate))) {
    throw new Error("HEAP_ATTRIBUTION_OUTPUT_EXISTS");
  }

  let fd: number;
  try {
    fd = fs.openSync(options.filePath, "wx");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      throw new Error("HEAP_ATTRIBUTION_OUTPUT_EXISTS");
    }
    throw error;
  }

  const dependencies = options.dependencies ?? defaultDependencies;
  const now = options.now ?? Date.now;
  const startedAtMs = now();
  const sourceCommit = options.sourceCommit.toLowerCase();
  let baselineAtMs: number | undefined;
  let renderPasses = 0;
  let milestoneIndex = 0;
  let sequence = 0;
  let disabled = false;
  let closed = false;

  const disable = (error: unknown): void => {
    if (disabled) return;
    disabled = true;
    options.onError?.(error instanceof Error ? error : new Error(String(error)));
  };

  return {
    filePath: options.filePath,
    recordRenderPass(sample): void {
      renderPasses += 1;
      if (disabled || closed || milestoneIndex >= HEAP_ATTRIBUTION_MILESTONES.length) return;
      const capturedAtMs = now();
      if (capturedAtMs - startedAtMs > HEAP_ATTRIBUTION_MAX_MS) return;
      const milestone = HEAP_ATTRIBUTION_MILESTONES[milestoneIndex]!;
      if (renderPasses < milestone) return;
      if (milestone === 240 && baselineAtMs !== undefined
          && capturedAtMs - baselineAtMs < HEAP_ATTRIBUTION_SETTLE_MS) return;

      try {
        dependencies.forceFullCollection();
        dependencies.forceFullCollection();
        const stats = dependencies.collectStats();
        const shouldSnapshot = milestone === 120 || milestone === 720;
        const heapSnapshotPath = shouldSnapshot ? snapshotPath(options.filePath, milestone) : null;
        if (heapSnapshotPath !== null) {
          writeExclusive(heapSnapshotPath, dependencies.collectV8Snapshot());
        }
        const row: HeapAttributionRow = {
          schema_version: "ember-issue898-heap-attribution-v1",
          sequence,
          captured_at: new Date(capturedAtMs).toISOString(),
          captured_at_ms: capturedAtMs,
          source_commit: sourceCommit,
          pid: process.pid,
          render_passes: renderPasses,
          heap: stats.heap,
          jsc_memory: stats.jscMemory,
          process_memory: stats.processMemory,
          renderer: {
            frame_width: sample.frameWidth,
            frame_height: sample.frameHeight,
            frame_cell_count: sample.frameCellCount,
            patch_changes: sample.patchChanges,
            optimized_runs: sample.optimizedRuns,
            rendered_bytes: sample.renderedBytes,
            patch_buffer_bytes: sample.patchBufferBytes,
            style_pool_size: sample.stylePoolSize,
            hyperlink_pool_size: sample.hyperlinkPoolSize,
          },
          snapshot_path: heapSnapshotPath,
        };
        fs.writeSync(fd, `${JSON.stringify(row)}\n`, null, "utf8");
        if (milestone === 120) baselineAtMs = capturedAtMs;
        milestoneIndex += 1;
        sequence += 1;
      } catch (error) {
        disable(error);
      }
    },
    close(): void {
      if (closed) return;
      closed = true;
      try {
        fs.closeSync(fd);
      } catch (error) {
        disable(error);
      }
    },
  };
}

export function createHeapAttributionDiagnosticFromEnv(
  env: NodeJS.ProcessEnv = process.env,
  dependencies: HeapAttributionDependencies = defaultDependencies,
  onError?: (error: Error) => void,
): HeapAttributionDiagnostic | undefined {
  const filePath = env[HEAP_ATTRIBUTION_ENV];
  if (!filePath) return undefined;
  const sourceCommit = env[HEAP_ATTRIBUTION_SOURCE_ENV];
  if (!sourceCommit) throw new Error("HEAP_ATTRIBUTION_SOURCE_COMMIT_MISSING");
  return createHeapAttributionDiagnostic({ filePath, sourceCommit, dependencies, onError });
}
