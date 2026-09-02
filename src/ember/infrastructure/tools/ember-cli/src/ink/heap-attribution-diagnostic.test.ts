// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue #898: RED contract for the minutes-scale retained-allocation attribution carrier.
import { afterEach, describe, expect, test } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import React from "react";
import { Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";
import {
  createHeapAttributionDiagnostic,
  createHeapAttributionDiagnosticFromEnv,
  HEAP_ATTRIBUTION_ENV,
  type HeapAttributionDependencies,
  type HeapAttributionRenderSample,
  type HeapAttributionRow,
} from "./heap-attribution-diagnostic.ts";

const roots: string[] = [];

function scratch(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "issue898-heap-attribution-"));
  roots.push(root);
  return root;
}

afterEach(() => {
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});

function dependencies(events: string[]): HeapAttributionDependencies {
  let sample = 0;
  return {
    forceFullCollection() { events.push("gc"); },
    collectStats() {
      sample += 1;
      return {
        heap: {
          heapSize: sample * 100,
          heapCapacity: sample * 200,
          extraMemorySize: sample * 10,
          objectCount: sample,
          protectedObjectCount: 0,
          globalObjectCount: 1,
          protectedGlobalObjectCount: 0,
          objectTypeCounts: { string: sample },
          protectedObjectTypeCounts: {},
        },
        jscMemory: {
          current: sample * 1_000,
          peak: sample * 1_100,
          currentCommit: sample * 1_200,
          peakCommit: sample * 1_300,
          pageFaults: sample,
        },
        processMemory: { rss: sample * 2_000, heapTotal: 0, heapUsed: 0, external: 0, arrayBuffers: 0 },
      };
    },
    collectV8Snapshot() {
      events.push("snapshot");
      return new TextEncoder().encode(`snapshot-${sample}`).buffer;
    },
  };
}

function rows(filePath: string): HeapAttributionRow[] {
  return fs.readFileSync(filePath, "utf8").trim().split("\n").filter(Boolean)
    .map((line) => JSON.parse(line) as HeapAttributionRow);
}

describe("issue #898 heap attribution diagnostic", () => {
  test("is absent by default", () => {
    const root = scratch();
    expect(createHeapAttributionDiagnosticFromEnv({}, dependencies([]))).toBeUndefined();
    expect(fs.readdirSync(root)).toEqual([]);
  });

  test("requires an absolute path and refuses every output collision", () => {
    expect(() => createHeapAttributionDiagnostic({
      filePath: "relative.jsonl",
      sourceCommit: "e9fd74c3c3f1df8352fe5c40c6713c17d9201c81",
      dependencies: dependencies([]),
    })).toThrow("HEAP_ATTRIBUTION_PATH_NOT_ABSOLUTE");

    const root = scratch();
    const filePath = path.join(root, "heap.jsonl");
    fs.writeFileSync(filePath, "custody\n");
    expect(() => createHeapAttributionDiagnostic({
      filePath,
      sourceCommit: "e9fd74c3c3f1df8352fe5c40c6713c17d9201c81",
      dependencies: dependencies([]),
    })).toThrow("HEAP_ATTRIBUTION_OUTPUT_EXISTS");
    expect(fs.readFileSync(filePath, "utf8")).toBe("custody\n");

    for (const pass of [120, 720]) {
      const siblingBase = path.join(root, `heap-${pass}.jsonl`);
      const siblingPath = `${siblingBase}.pass${pass}.heapsnapshot`;
      fs.writeFileSync(siblingPath, `snapshot-custody-${pass}\n`);
      expect(() => createHeapAttributionDiagnostic({
        filePath: siblingBase,
        sourceCommit: "e9fd74c3c3f1df8352fe5c40c6713c17d9201c81",
        dependencies: dependencies([]),
      })).toThrow("HEAP_ATTRIBUTION_OUTPUT_EXISTS");
      expect(fs.existsSync(siblingBase)).toBe(false);
      expect(fs.readFileSync(siblingPath, "utf8")).toBe(`snapshot-custody-${pass}\n`);
    }
  });

  test("emits only frozen milestones, forces two collections, and snapshots only 120 and 720", () => {
    const events: string[] = [];
    const filePath = path.join(scratch(), "heap.jsonl");
    let now = 1_000;
    const diagnostic = createHeapAttributionDiagnostic({
      filePath,
      sourceCommit: "e9fd74c3c3f1df8352fe5c40c6713c17d9201c81",
      dependencies: dependencies(events),
      now: () => now,
    });

    for (let pass = 1; pass <= 720; pass += 1) {
      if (pass === 240) now += 30_000;
      diagnostic.recordRenderPass({
        frameWidth: 190,
        frameHeight: 85,
        frameCellCount: 16_150,
        patchChanges: pass,
        optimizedRuns: 1,
        renderedBytes: 10,
        patchBufferBytes: 2,
        stylePoolSize: 37,
        hyperlinkPoolSize: 0,
      });
    }
    diagnostic.close();

    const emitted = rows(filePath);
    expect(emitted.map((row) => row.render_passes)).toEqual([120, 240, 480, 720]);
    expect(emitted.every((row) => row.source_commit === "e9fd74c3c3f1df8352fe5c40c6713c17d9201c81")).toBe(true);
    expect(events.filter((event) => event === "gc")).toHaveLength(8);
    expect(events.filter((event) => event === "snapshot")).toHaveLength(2);
    expect(fs.readFileSync(`${filePath}.pass120.heapsnapshot`, "utf8")).toBe("snapshot-1");
    expect(fs.readFileSync(`${filePath}.pass720.heapsnapshot`, "utf8")).toBe("snapshot-4");
    expect(emitted[3]!.heap.objectTypeCounts.string).toBe(4);
    expect(emitted[3]!.renderer.frame_cell_count).toBe(16_150);
  });

  test("environment activation binds the existing public source commit", () => {
    const filePath = path.join(scratch(), "heap.jsonl");
    const diagnostic = createHeapAttributionDiagnosticFromEnv({
      [HEAP_ATTRIBUTION_ENV]: filePath,
      EMBER_PUBLIC_SOURCE_COMMIT: "e9fd74c3c3f1df8352fe5c40c6713c17d9201c81",
    }, dependencies([]));
    expect(diagnostic).toBeDefined();
    diagnostic!.close();
    expect(fs.existsSync(filePath)).toBe(true);
  });

  test("reports the first runtime sink failure once and disables without throwing", () => {
    const filePath = path.join(scratch(), "heap.jsonl");
    const errors: string[] = [];
    const failing = dependencies([]);
    failing.collectStats = () => { throw new Error("HEAP_STATS_TEST_FAILURE"); };
    const diagnostic = createHeapAttributionDiagnostic({
      filePath,
      sourceCommit: "e9fd74c3c3f1df8352fe5c40c6713c17d9201c81",
      dependencies: failing,
      onError(error) { errors.push(error.message); },
    });
    const sample: HeapAttributionRenderSample = {
      frameWidth: 20,
      frameHeight: 2,
      frameCellCount: 40,
      patchChanges: 1,
      optimizedRuns: 1,
      renderedBytes: 1,
      patchBufferBytes: 1,
      stylePoolSize: 1,
      hyperlinkPoolSize: 0,
    };
    expect(() => {
      for (let pass = 1; pass <= 240; pass += 1) diagnostic.recordRenderPass(sample);
      diagnostic.close();
    }).not.toThrow();
    expect(errors).toEqual(["HEAP_STATS_TEST_FAILURE"]);
    expect(fs.readFileSync(filePath, "utf8")).toBe("");
  });

  test("the installed mount path activates from the exact environment pair", () => {
    const filePath = path.join(scratch(), "heap.jsonl");
    const previousPath = process.env[HEAP_ATTRIBUTION_ENV];
    const previousSource = process.env.EMBER_PUBLIC_SOURCE_COMMIT;
    let handle: ReturnType<typeof mountInk> | undefined;
    try {
      process.env[HEAP_ATTRIBUTION_ENV] = filePath;
      process.env.EMBER_PUBLIC_SOURCE_COMMIT = "e9fd74c3c3f1df8352fe5c40c6713c17d9201c81";
      handle = mountInk(React.createElement(Text, null, "heap-env-wired"), {
        stream: { write() { return true; } },
        stdout: { columns: 20, rows: 2 },
      });
      expect(fs.existsSync(filePath)).toBe(true);
    } finally {
      handle?.unmount();
      if (previousPath === undefined) delete process.env[HEAP_ATTRIBUTION_ENV];
      else process.env[HEAP_ATTRIBUTION_ENV] = previousPath;
      if (previousSource === undefined) delete process.env.EMBER_PUBLIC_SOURCE_COMMIT;
      else process.env.EMBER_PUBLIC_SOURCE_COMMIT = previousSource;
    }
  });

  test("mount forwards completed render-stage dimensions and closes the injected sink", () => {
    const samples: HeapAttributionRenderSample[] = [];
    let closes = 0;
    const handle = mountInk(React.createElement(Text, null, "frame-0"), {
      stream: { write() { return true; } },
      stdout: { columns: 24, rows: 3 },
      heapAttributionDiagnostic: {
        filePath: "injected",
        recordRenderPass(sample) { samples.push(sample); },
        close() { closes += 1; },
      },
    });
    handle.update(React.createElement(Text, null, "frame-1"));
    handle.unmount();

    expect(samples.length).toBeGreaterThanOrEqual(2);
    expect(samples[0]!.frameWidth).toBe(24);
    expect(samples[0]!.frameHeight).toBe(3);
    expect(samples[0]!.frameCellCount).toBe(72);
    expect(samples[0]!.renderedBytes).toBeGreaterThan(0);
    expect(samples[0]!.patchBufferBytes).toBeGreaterThan(0);
    expect(closes).toBe(1);
  });
});
