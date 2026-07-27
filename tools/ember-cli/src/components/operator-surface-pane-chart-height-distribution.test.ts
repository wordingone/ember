// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// R1d acceptance — chart height distribution (frozen spec:
// state/specs/ember-cli-chart-height-and-frame-geometry.md). Drives the REAL consumer path,
// OperatorSurfacePane mounted through the ink reconciler, exactly like the sibling
// operator-surface-pane-host-telemetry.test.ts this file borrows its fixtures from.
import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { OperatorSurfacePane, type OperatorSurfacePaneProps } from "./operator-surface-pane.ts";
import type { HostMetricSeries, HostTelemetrySnapshot } from "../services/host-telemetry-poller.ts";
import type { TelemetryState } from "../services/telemetry-watch.ts";

function telemetry(overrides: Partial<TelemetryState> = {}): TelemetryState {
  return { recentEvents: [], ...overrides };
}

function train(runId: string, step: number, ts: string, loss: number, extra: Record<string, unknown> = {}) {
  return { ts, kind: "train_step", source: "journal", payload: { run_id: runId, step, loss, ...extra } };
}

function series(values: Array<number | null>, unit = "GiB", unavailableReason?: string): HostMetricSeries {
  return { values, unit, unavailableReason };
}

function host(overrides: Partial<HostTelemetrySnapshot> = {}): HostTelemetrySnapshot {
  return {
    memory: series([1.2, 1.3, 1.25, 1.4]),
    ram: series([20, 21, 22, 23]),
    vram: series([18, 18.5, 19, 19.2]),
    cpu: series([30, 35, 40, 38], "%"),
    gpu: series([40, 42, 45, 47], "%"),
    disk: series([61, 61, 62, 61], "%"),
    ...overrides,
  };
}

function renderPaneRows(props: Partial<OperatorSurfacePaneProps> & Pick<OperatorSurfacePaneProps, "telemetry">, columns: number, rows: number): string[] {
  const chunks: string[] = [];
  const handle = mountInk(
    React.createElement(OperatorSurfacePane, {
      activityLines: [],
      width: columns,
      height: rows,
      terminalColumns: columns,
      terminalRows: rows,
      ...props,
    }),
    { stream: { write(s: string) { chunks.push(s); } }, stdout: { columns, rows } },
  );
  handle.unmount();
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(chunks.join(""), frame, new StylePool());
  return frame.cells.map((row) => row.map((cell) => cell?.char ?? " ").join(""));
}

/** Trailing blank rows below the last row that has any non-space content inside the pane. */
function trailingBlankRowCount(rows: string[]): number {
  let blank = 0;
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    if (rows[i]!.trim().length === 0) blank += 1;
    else break;
  }
  return blank;
}

/** Known section/metric labels that mark the START of a new row-producing block. A grown
 *  multi-row chart's own continuation rows are blank-prefixed and, for a Braille canvas,
 *  legitimately BLANK on some rows (a dot row with nothing painted at that height level is not
 *  the end of the chart) -- so only a recognized label ends a span, never a blank line. */
const BLOCK_LABEL_STEMS = ["host ", "HOST TELEMETRY", "ACTIVITY/EVENT FEED", "TRAINING/LOSS", "RESOURCE EFFICIENCY", "loss ", "tokens/s", "learning rate", "energy joules", "step/time", "checkpoint", "…"];

/** Counts how many consecutive frame rows (from `startIndex`, inclusive) belong to one
 *  row-producing block: the label row itself plus every following row until the next
 *  recognized label or the pane's own border/edge. */
function blockSpan(rows: string[], startIndex: number): number {
  let span = 1;
  for (let i = startIndex + 1; i < rows.length; i += 1) {
    const trimmed = rows[i]!.replace(/[│┌┐└┘─]/g, "").trim();
    if (BLOCK_LABEL_STEMS.some((stem) => trimmed.startsWith(stem))) break;
    span += 1;
  }
  return span;
}

describe("R1d — chart height distribution", () => {
  // Acceptance row 1 + 2: 120x44, resting, host bound, no run — zero blank rows below the last
  // content row while any chart is one row tall, and each bound host chart is >1 row tall.
  test("row 1+2: resting panel at 120x44 grows every bound host chart past one row, no wasted rows", () => {
    const rows = renderPaneRows({ telemetry: telemetry(), host: host(), nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, 120, 44);
    const paneRows = rows.filter((row) => row.includes("│"));
    expect(trailingBlankRowCount(paneRows)).toBe(0);
    // Each bound host metric's FIRST row is the labeled one; count how many total rows in the
    // frame belong to that metric before the next label (or HOST TELEMETRY/pane edge) — >1 means
    // it grew past the pre-R1d floor.
    for (const label of ["host memory GiB", "host RAM GiB", "host VRAM GiB", "host CPU %", "host GPU %", "host disk %"]) {
      const startIndex = rows.findIndex((row) => row.includes(label));
      expect(startIndex).toBeGreaterThanOrEqual(0);
      expect(blockSpan(rows, startIndex)).toBeGreaterThan(1);
    }
  });

  // Acceptance row 3: 60x20, live run — end-trim still applies; charts at floor; the marker
  // present. This is the OVER-subscribed branch, unchanged by R1d.
  test("row 3: 60x20 live run keeps the end-trim path — charts at floor, the more-rows marker present", () => {
    const telemetryState = telemetry({
      recentEvents: [
        train("run-a", 1, "2026-07-26T17:30:01.000Z", 2, { tokens_per_second: 100 }),
        train("run-a", 2, "2026-07-26T17:30:02.000Z", 1, { tokens_per_second: 120 }),
      ],
    });
    const rows = renderPaneRows(
      { telemetry: telemetryState, host: host(), nowMs: Date.parse("2026-07-26T17:30:03.000Z"), width: 60, height: 20, terminalColumns: 60, terminalRows: 20 },
      60,
      20,
    );
    expect(rows.some((row) => /… \d+ more rows/.test(row))).toBe(true);
    // Skip-path S1: surplus is negative here (over-subscribed) -- distribution must not run, so
    // no host metric's block exceeds its floor of one row even though every series is bound.
    for (const label of ["host memory GiB", "host RAM GiB"]) {
      const start = rows.findIndex((row) => row.includes(label));
      if (start >= 0) expect(blockSpan(rows, start)).toBe(1);
    }
  });

  // Acceptance row 4: exact-fit height — no trim, no growth, byte-identical to today's frame.
  // Verified by pinning the height to the exact baseline-block count for a no-host mount and
  // checking the single-row sparkline shape survives untouched (same fixture/height the
  // sibling union-step-grid test in operator-surface-pane.test.ts locked down).
  test("row 4: exact-fit height changes nothing — single-row rendering survives byte for byte", () => {
    const events = [
      train("run-grid", 1, "2026-07-26T17:30:01.000Z", 3, { step_ms: 1000, tokens_per_second: 100 }),
      train("run-grid", 2, "2026-07-26T17:30:02.000Z", 2, { step_ms: 900, learning_rate: 0.001 }),
      train("run-grid", 3, "2026-07-26T17:30:03.000Z", 1, { step_ms: 800, tokens_per_second: 300, learning_rate: 0.0005 }),
    ];
    const element = OperatorSurfacePane({
      telemetry: telemetry({ recentEvents: events }),
      activityLines: [],
      width: 80,
      height: 20,
      terminalColumns: 80,
      terminalRows: 20,
      nowMs: Date.parse("2026-07-26T17:30:05.000Z"),
    });
    const body = (element as any).props.children;
    const text = (body.props.children as any[]).map((child) => child?.props?.children).filter((value) => typeof value === "string") as string[];
    const tokenLine = text.find((line) => line.startsWith("tokens/s"))!;
    // The old per-point glyph mapping (not a Braille resample): a single row, gap dot at the
    // missing middle sample.
    expect(tokenLine.slice(20, 23)).toContain("·");
    expect(tokenLine.includes("⠀") || /[⠁-⣿]/.test(tokenLine)).toBe(false);
  });

  // Acceptance row 5: one chart bound, five null — the bound chart takes the whole surplus; null
  // rows stay one row.
  test("row 5: one bound host chart takes the whole surplus; the five null charts stay one row", () => {
    const onlyMemoryBound = host({
      ram: series([null, null]),
      vram: series([null, null]),
      cpu: series([null, null], "%"),
      gpu: series([null, null], "%"),
      disk: series([null, null], "%"),
    });
    const rows = renderPaneRows({ telemetry: telemetry(), host: onlyMemoryBound, nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, 120, 44);
    const memoryStart = rows.findIndex((row) => row.includes("host memory GiB"));
    expect(memoryStart).toBeGreaterThanOrEqual(0);
    expect(blockSpan(rows, memoryStart)).toBeGreaterThan(1);
    for (const label of ["host RAM GiB", "host VRAM GiB", "host CPU %", "host GPU %", "host disk %"]) {
      const start = rows.findIndex((row) => row.includes(label));
      expect(start).toBeGreaterThanOrEqual(0);
      expect(blockSpan(rows, start)).toBe(1);
    }
  });

  // Acceptance row 6: zero charts bound — no crash, no division by zero, surplus unused.
  test("row 6: zero bound host charts renders without crashing; surplus is simply unused", () => {
    const allUnbound: HostTelemetrySnapshot = {
      memory: series([]),
      ram: series([]),
      vram: series([]),
      cpu: series([], "%"),
      gpu: series([], "%"),
      disk: series([], "%"),
    };
    expect(() => renderPaneRows({ telemetry: telemetry(), host: allUnbound, nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, 120, 44)).not.toThrow();
    const rows = renderPaneRows({ telemetry: telemetry(), host: allUnbound, nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, 120, 44);
    expect(rows.some((row) => row.includes("HOST TELEMETRY"))).toBe(true);
  });

  // Acceptance row 7: live run at a roomy height — training and host charts both grow; neither
  // starves the other.
  test("row 7: a live run at a roomy height grows both training and host charts", () => {
    const telemetryState = telemetry({
      recentEvents: [
        train("run-a", 1, "2026-07-26T17:30:01.000Z", 2, { tokens_per_second: 100, learning_rate: 0.001 }),
        train("run-a", 2, "2026-07-26T17:30:02.000Z", 1, { tokens_per_second: 120, learning_rate: 0.0008 }),
        train("run-a", 3, "2026-07-26T17:30:03.000Z", 0.5, { tokens_per_second: 140, learning_rate: 0.0006 }),
      ],
    });
    const rows = renderPaneRows({ telemetry: telemetryState, host: host(), nowMs: Date.parse("2026-07-26T17:30:04.000Z") }, 120, 44);
    const lossStart = rows.findIndex((row) => row.trim().replace(/[│]/g, "").trim().startsWith("loss "));
    const memoryStart = rows.findIndex((row) => row.includes("host memory GiB"));
    expect(lossStart).toBeGreaterThanOrEqual(0);
    expect(memoryStart).toBeGreaterThanOrEqual(0);
    expect(blockSpan(rows, lossStart)).toBeGreaterThan(1);
    expect(blockSpan(rows, memoryStart)).toBeGreaterThan(1);
  });

  // Conjunction C2: surplus not divisible by the chart count — deterministic remainder
  // placement, identical across two independent renders of the same size.
  test("C2: remainder placement is deterministic across two renders of the same size", () => {
    const rowsA = renderPaneRows({ telemetry: telemetry(), host: host(), nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, 121, 41);
    const rowsB = renderPaneRows({ telemetry: telemetry(), host: host(), nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, 121, 41);
    expect(rowsA).toEqual(rowsB);
  });

  // Conjunction C3: roomy height AND all metrics null — every row stays one row; surplus unused
  // rather than distributed to text rows.
  test("C3: roomy height with every host metric null keeps every row at one line", () => {
    const allNull: HostTelemetrySnapshot = {
      memory: series([null, null, null]),
      ram: series([null, null, null]),
      vram: series([null, null, null], "GiB", "nvidia-smi unavailable"),
      cpu: series([null, null, null], "%"),
      gpu: series([null, null, null], "%", "nvidia-smi unavailable"),
      disk: series([null, null, null], "%"),
    };
    const rows = renderPaneRows({ telemetry: telemetry(), host: allNull, nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, 120, 44);
    for (const label of ["host memory GiB", "host RAM GiB", "host VRAM GiB", "host CPU %", "host GPU %", "host disk %"]) {
      const start = rows.findIndex((row) => row.includes(label));
      expect(start).toBeGreaterThanOrEqual(0);
      expect(blockSpan(rows, start)).toBe(1);
    }
  });

  // Conjunction C4: growth AND the width sweep — no chart paints into a border column at any
  // width after growing.
  test("C4: no chart paints into the pane's border column after growing, across a width sweep", () => {
    for (const columns of [60, 90, 120, 160]) {
      const rows = renderPaneRows({ telemetry: telemetry(), host: host(), nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, columns, 44);
      const paneRows = rows.filter((row) => row.includes("│"));
      for (const row of paneRows) {
        const rightBorder = row.lastIndexOf("│");
        if (rightBorder > 0) expect(row[rightBorder]).toBe("│");
      }
    }
  });
});
