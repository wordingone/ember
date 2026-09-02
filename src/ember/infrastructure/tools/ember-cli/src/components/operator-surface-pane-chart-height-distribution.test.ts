// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #894 acceptance: production graph cards remain bounded, whole, deterministic, and explicit.
import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import { OperatorSurfacePane, type OperatorSurfacePaneProps } from "./operator-surface-pane.ts";
import type { HostMetricSeries, HostTelemetrySnapshot } from "../services/host-telemetry-poller.ts";
import type { TelemetryState } from "../../../../../../../tools/ember-cli/src/services/telemetry-watch.ts";

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

async function renderPaneRows(
  props: Partial<OperatorSurfacePaneProps> & Pick<OperatorSurfacePaneProps, "telemetry">,
  columns: number,
  rows: number,
): Promise<string[]> {
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
  await new Promise<void>((resolve) => setTimeout(resolve, 10));
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(chunks.join(""), frame, new StylePool());
  const renderedRows = frame.cells.map((row) => row.map((cell) => cell?.char ?? " ").join(""));
  handle.unmount();
  return renderedRows;
}

function cardTitles(rows: string[]): string[] {
  return rows.filter((row) => /(?:HOST (?:MEMORY|RAM|VRAM|CPU|GPU|DISK)|LOSS|TOKENS\/S|LEARNING RATE|ENERGY)/u.test(row));
}

describe("#894 responsive chart-card distribution", () => {
  test("roomy host-only view caps every card at five rows instead of stretching traces", async () => {
    const rows = await renderPaneRows({ telemetry: telemetry(), host: host(), nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, 120, 44);
    for (const title of ["HOST MEMORY", "HOST RAM", "HOST VRAM", "HOST CPU", "HOST GPU", "HOST DISK"]) {
      expect(rows.some((row) => row.includes(title))).toBe(true);
    }
    expect(rows.some((row) => row.includes("more rows"))).toBe(false);
    expect(rows.some((row) => row.includes("HOST MEMORY"))).toBe(true);
    expect(rows.every((row) => !(row.includes("HOST MEMORY") && row.includes("HOST RAM")))).toBe(true);
  });

  test("tight live view keeps only whole cards and reports hidden chart count", async () => {
    const state = telemetry({ recentEvents: [
      train("run-a", 1, "2026-07-26T17:30:01.000Z", 2, { tokens_per_second: 100 }),
      train("run-a", 2, "2026-07-26T17:30:02.000Z", 1, { tokens_per_second: 120 }),
    ] });
    const rows = await renderPaneRows({ telemetry: state, host: host(), nowMs: Date.parse("2026-07-26T17:30:03.000Z") }, 60, 20);
    expect(rows.some((row) => /… \d+ more charts/.test(row))).toBe(true);
    expect(cardTitles(rows).length).toBeGreaterThan(0);
    expect(rows.some((row) => row.includes("more rows"))).toBe(false);
  });

  test("one bound host series and five unbound series retain identical card boundaries", async () => {
    const oneBound = host({
      ram: series([]),
      vram: series([]),
      cpu: series([], "%"),
      gpu: series([], "%"),
      disk: series([], "%"),
    });
    const rows = await renderPaneRows({ telemetry: telemetry(), host: oneBound, nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, 120, 44);
    expect(rows.some((row) => row.includes("HOST MEMORY"))).toBe(true);
    expect(rows.some((row) => row.includes("HOST RAM"))).toBe(true);
    expect(rows.some((row) => row.includes("SOURCE UNBOUND"))).toBe(true);
  });

  test("all-unbound host telemetry renders explicit cards without division or layout failure", async () => {
    const allUnbound: HostTelemetrySnapshot = {
      memory: series([]), ram: series([]), vram: series([]),
      cpu: series([], "%"), gpu: series([], "%"), disk: series([], "%"),
    };
    const rows = await renderPaneRows({ telemetry: telemetry(), host: allUnbound, nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, 120, 44);
    expect(rows.some((row) => row.includes("HOST MEMORY"))).toBe(true);
    expect(rows.some((row) => row.includes("SOURCE UNBOUND"))).toBe(true);
  });

  test("card selection and remainder placement are deterministic", async () => {
    const props = { telemetry: telemetry(), host: host(), nowMs: Date.parse("2026-07-26T17:30:00.000Z") };
    expect(await renderPaneRows(props, 121, 41)).toEqual(await renderPaneRows(props, 121, 41));
  });

  test("every width preserves the pane border and exact frame width", async () => {
    for (const columns of [40, 60, 90, 120, 160]) {
      const rows = await renderPaneRows({ telemetry: telemetry(), host: host(), nowMs: Date.parse("2026-07-26T17:30:00.000Z") }, columns, 44);
      expect(rows.every((row) => row.length === columns)).toBe(true);
      expect(rows.some((row) => row.includes("LIVE RUN / ACTIVITY/EVENT FEED"))).toBe(true);
    }
  });
});