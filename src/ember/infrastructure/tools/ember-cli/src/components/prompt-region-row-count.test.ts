// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, test } from "bun:test";
import React from "react";
import { Box } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import { PromptInput, type PromptInputState } from "./prompt-input.ts";
import { StatusLine, type StatusLineProps } from "./status-bar.ts";

const STATE: PromptInputState = {
  text: "/",
  cursor: 1,
  mode: "prompt",
  isStashed: true,
  permissionMode: "bypass",
  pastedContents: null,
  stashNotice: "Input stashed",
};

const STATUS: StatusLineProps = {
  permissionMode: { mode: "bypass", cycle: () => {} } as StatusLineProps["permissionMode"],
  interrupt: { interrupt: () => {} } as StatusLineProps["interrupt"],
  taskPanel: {
    visible: true,
    toggle: () => {},
    tasks: [{ id: "t1", name: "long task that must remain hidden", completed: false }],
  },
  telemetry: {
    recentEvents: [],
    lastGovernor: { vramUsedGib: 12, vramTotalGib: 24 } as NonNullable<
      StatusLineProps["telemetry"]["lastGovernor"]
    >,
  },
  effort: { active: true, label: "high effort" },
  degraded: { active: true, endpoint: "model endpoint" },
  roundtripAge: { lastSuccessAt: 0 } as NonNullable<StatusLineProps["roundtripAge"]>,
};

function render(width: number, compact: boolean): string[] {
  let raw = "";
  const handle = mountInk(
    React.createElement(
      Box,
      { flexDirection: "column", width },
      React.createElement(PromptInput, {
        state: STATE,
        queuedItems: ["one", "two", "three", "four"],
        notifications: [{ id: "n", message: "retrying", kind: "error" }],
        isProcessing: true,
        compact,
        showStatusLine: false,
        width,
        statusLine: React.createElement(StatusLine, { ...STATUS, compact }),
      }),
    ),
    { stream: { write(value: string) { raw += value; } }, stdout: { columns: width, rows: 30 } },
  );
  handle.unmount();
  const frame = buildFrame(width, 30);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((row) => row.map((cell) => cell?.char ?? " ").join(""));
}

function occupied(lines: string[]): string[] {
  return lines.filter((line) => /\S/.test(line));
}

describe("palette compact prompt/status contract", () => {
  for (const width of [10, 20, 60, 80]) {
    test(`is exactly four rows at width ${width}, even with busy+stash+queue+status details`, () => {
      const lines = occupied(render(width, true));
      expect(lines).toHaveLength(4);
      expect(lines.some((line) => line.includes("❯"))).toBe(true);
      expect(lines.join("\n")).not.toMatch(/stashed|retrying|long task|VRAM|degraded|high effort/i);
    });
  }

  test("the same live state expands when compact mode is absent", () => {
    expect(occupied(render(80, false)).length).toBeGreaterThan(4);
  });
});
