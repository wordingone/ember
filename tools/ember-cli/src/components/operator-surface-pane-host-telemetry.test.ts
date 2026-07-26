// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// Panel-level acceptance for the host-telemetry binding (frozen spec: chart widget + host
// telemetry). Drives the REAL consumer path — OperatorSurfacePane mounted through the ink
// reconciler — not the chart in isolation.
import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { hostMetricLine, hostTelemetryLines, OperatorSurfacePane, type OperatorSurfacePaneProps } from "./operator-surface-pane.ts";
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
    memory: series([1.2, 1.3]),
    ram: series([20, 21]),
    vram: series([18, 18.5]),
    cpu: series([30, 35], "%"),
    gpu: series([40, 42], "%"),
    disk: series([61, 61], "%"),
    ...overrides,
  };
}

function renderPaneRows(props: Partial<OperatorSurfacePaneProps> & Pick<OperatorSurfacePaneProps, "telemetry">, columns = 80, rows = 30): string[] {
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

describe("operator surface pane host telemetry", () => {
  // Acceptance row 1: resting panel, no run — six host curves, zero SOURCE UNBOUND among them.
  test("row 1: resting panel binds all six host curves with no SOURCE UNBOUND among them", () => {
    const rows = renderPaneRows({ telemetry: telemetry(), host: host(), nowMs: Date.parse("2026-07-17T17:30:00.000Z") });
    expect(rows.some((row) => row.includes("HOST TELEMETRY"))).toBe(true);
    for (const label of ["host memory GiB", "host RAM GiB", "host VRAM GiB", "host CPU %", "host GPU %", "host disk %"]) {
      const line = rows.find((row) => row.includes(label));
      expect(line).toBeDefined();
      expect(line!).not.toContain("SOURCE UNBOUND");
    }
  });

  // Acceptance row 2: live run — training curves join, no host curve dropped.
  test("row 2: a live run adds training sections without dropping any host curve", () => {
    const telemetryState = telemetry({
      recentEvents: [
        train("run-a", 1, "2026-07-17T17:30:01.000Z", 2, { tokens_per_second: 100 }),
        train("run-a", 2, "2026-07-17T17:30:02.000Z", 1, { tokens_per_second: 120 }),
      ],
    });
    const rows = renderPaneRows({ telemetry: telemetryState, host: host(), nowMs: Date.parse("2026-07-17T17:30:03.000Z") });
    expect(rows.some((row) => row.includes("TRAINING/LOSS"))).toBe(true);
    expect(rows.some((row) => row.includes("RESOURCE EFFICIENCY"))).toBe(true);
    for (const label of ["host memory GiB", "host RAM GiB", "host VRAM GiB", "host CPU %", "host GPU %", "host disk %"]) {
      expect(rows.some((row) => row.includes(label))).toBe(true);
    }
  });

  // Order invariant: bound is decided before has-samples. Bound-but-empty renders an empty
  // axis (gap glyphs), NEVER the SOURCE UNBOUND path.
  test("order invariant: a bound-but-empty series renders an empty axis, not SOURCE UNBOUND", () => {
    const line = hostMetricLine("memory", series([]), 10);
    expect(line).not.toContain("SOURCE UNBOUND");
    expect(line).toContain("·".repeat(10)); // empty axis: all gaps
    // And genuinely-unwired stays SOURCE UNBOUND — the exceptional state, not the resting one.
    expect(hostMetricLine("memory", undefined, 10)).toContain("SOURCE UNBOUND");
  });

  // Acceptance row 5 at panel level: vram/gpu null-with-reason; the other four render curves.
  test("row 5: nvidia-smi absence shows a stated reason on vram/gpu only", () => {
    const degraded = host({
      vram: series([null], "GiB", "nvidia-smi unavailable"),
      gpu: series([null], "%", "nvidia-smi unavailable"),
    });
    const lines = hostTelemetryLines(degraded, 12);
    const vramLine = lines.find((line) => line.includes("host VRAM"))!;
    const gpuLine = lines.find((line) => line.includes("host GPU"))!;
    expect(vramLine).toContain("[nvidia-smi unavailable]");
    expect(gpuLine).toContain("[nvidia-smi unavailable]");
    for (const label of ["host memory", "host RAM", "host CPU", "host disk"]) {
      const line = lines.find((candidate) => candidate.includes(label))!;
      expect(line).not.toContain("unavailable");
      expect(line).not.toContain("SOURCE UNBOUND");
    }
  });

  // Conjunction C1: narrowest supported width AND live run — every curve present, none dropped.
  test("C1: at the narrowest supported width with a live run, all six host labels survive", () => {
    const telemetryState = telemetry({
      recentEvents: [
        train("run-a", 1, "2026-07-17T17:30:01.000Z", 2),
        train("run-a", 2, "2026-07-17T17:30:02.000Z", 1),
      ],
    });
    const rows = renderPaneRows(
      { telemetry: telemetryState, host: host(), nowMs: Date.parse("2026-07-17T17:30:03.000Z"), width: 40, height: 30 },
      40,
      30,
    );
    // Labels are 20-char prefixed and the pane truncates; assert each label's distinctive stem.
    for (const stem of ["host memory", "host RAM", "host VRAM", "host CPU", "host GPU", "host disk"]) {
      expect(rows.some((row) => row.includes(stem))).toBe(true);
    }
  });

  // Conjunction C2: nvidia-smi absent AND live run — training curves unaffected.
  test("C2: host GPU-source failure leaves the training sections intact", () => {
    const telemetryState = telemetry({
      recentEvents: [
        train("run-a", 1, "2026-07-17T17:30:01.000Z", 2),
        train("run-a", 2, "2026-07-17T17:30:02.000Z", 1),
      ],
    });
    const degraded = host({
      vram: series([null], "GiB", "nvidia-smi unavailable"),
      gpu: series([null], "%", "nvidia-smi unavailable"),
    });
    const rows = renderPaneRows({ telemetry: telemetryState, host: degraded, nowMs: Date.parse("2026-07-17T17:30:03.000Z") });
    expect(rows.some((row) => row.includes("TRAINING/LOSS"))).toBe(true);
    expect(rows.some((row) => row.includes("loss"))).toBe(true);
  });
});
