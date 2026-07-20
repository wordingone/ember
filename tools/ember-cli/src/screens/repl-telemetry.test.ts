// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import React from "react";

import { StatusLine } from "../components/status-bar.ts";
import { mountInk } from "../ink/reconciler.ts";
import { telemetryMemoKey } from "../services/telemetry-label.ts";

describe("cockpit training telemetry label", () => {
  test("renders progress, step rate, VRAM, verified checkpoint, and model-chat downtime", () => {
    const label = telemetryMemoKey({
      recentEvents: [],
      lastGovernor: { vramUsedGib: 20.5, vramTotalGib: 24, fractionApplied: 0.95 },
      activeRun: { runId: "vision-v4", step: 8192, totalSteps: 65538, loss: 4.125, stepMs: 1250, lastTs: "2026-07-17T05:00:02.000Z" },
      lastCheckpoint: { runId: "vision-v4", step: 8192, checkpointManifestSha256: "abcdef0123456789".repeat(4), lastTs: "2026-07-17T05:00:03.000Z" },
      runStatus: { runId: "vision-v4", phase: "TRAINING", modelChat: "OFFLINE", restoreNotBefore: "2026-07-18T11:00:00-07:00", lastTs: "2026-07-17T05:00:00.000Z" },
    });
    expect(label).toContain("VRAM 20.5/24.0");
    expect(label).toContain("step 8192/65538");
    expect(label).toContain("loss 4.13");
    expect(label).toContain("0.80 step/s");
    expect(label).toContain("ckpt 8192 abcdef012345");
    expect(label).toContain("model chat OFFLINE");
    expect(label).toContain("restore 2026-07-18T11:00:00-07:00");
  });

  test("mounts the live telemetry label through the production StatusLine render seam", () => {
    let output = "";
    mountInk(
      React.createElement(StatusLine, {
        permissionMode: { mode: "bypass", cycle: () => {} },
        interrupt: { interrupt: () => {} },
        taskPanel: { visible: false, toggle: () => {}, tasks: [] },
        telemetry: {
          recentEvents: [],
          lastGovernor: { vramUsedGib: 15.7, vramTotalGib: 24.0, fractionApplied: 1.0 },
          activeRun: {
            runId: "vision-v4-20260716T1915PDT",
            step: 3,
            totalSteps: 65538,
            loss: 10.745058,
            stepMs: 1220.974,
            lastTs: "2026-07-17T02:22:56.641482Z",
          },
          runStatus: {
            runId: "vision-v4-20260716T1915PDT",
            phase: "TRAINING",
            modelChat: "OFFLINE",
            restoreNotBefore: "2026-07-17T18:00:00-07:00",
            lastTs: "2026-07-17T02:22:37.736008Z",
          },
        },
      }),
      {
        stream: { write(value: string) { output += value; } },
        stdout: { columns: 240, rows: 12 },
      },
    );

    expect(output).toContain("train r=vision-v4-20260716T1915PDT step 3/65538");
    expect(output).toContain("loss 10.75");
    expect(output).toContain("model chat OFFLINE");
  });
});
