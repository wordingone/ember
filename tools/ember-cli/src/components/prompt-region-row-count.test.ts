// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// components/prompt-region-row-count.test.ts — binds promptInputRowCount + statusLineRowCount to
// the real PromptInput/StatusLine render (2026-07-25 counterparty finding, fourth round).
//
// The finding: DROPDOWN_PROMPT_STATUS_RESERVE_ROWS=6 was a literal, and the test that "bound" it
// only reconstructed ONE frame (idle, no queue, no stash, no notifications) -- proving the fixture,
// not the budget. Live counterexamples the review supplied: QUEUE_MAX_VISIBLE=3 means a queue of
// 4+ items already adds a visible row plus an overflow row; Ctrl+S stash adds a persistent row;
// busy (isProcessing) adds a shimmer row; notifications each add their own row. None of those are
// exotic -- they are ordinary PromptInput states any operator can reach.
//
// So this test does not trust promptInputRowCount/statusLineRowCount's own arithmetic -- for each
// state below it mounts the REAL PromptInput + StatusLine, reconstructs the REAL rendered screen
// (the same column-aware technique homescreen-row-count.test.ts uses), counts genuinely-occupied
// rows, and asserts the count EQUALS what the two row-count functions return for the identical
// props. If a future edit changes either component's structure without updating its row-count
// function to match, this is the assertion that fails, loudly, instead of the palette silently
// over-asking again one layer up.

import { describe, it, expect } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { Box } from "../ink/components.ts";
import {
  PromptInput,
  promptInputRowCount,
  type PromptInputState,
  type PromptInputProps,
  type PromptInputRowCountProps,
} from "./prompt-input.ts";
import {
  StatusLine,
  statusLineRowCount,
  type StatusLineProps,
  type StatusLineRowCountProps,
} from "./status-bar.ts";

/** Same column-aware reconstruction as homescreen-row-count.test.ts / palette-overflow-render.test.ts. */
function reconstructRows(out: string): Map<number, string> {
  const grid = new Map<number, Map<number, string>>();
  const TOKEN_RE = /\x1b\[(\d+);(\d+)H|\x1b\[[0-9;]*[A-Za-z]|[^\x1b]+/g;
  let row = 1;
  let col = 1;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(out))) {
    if (m[1] !== undefined && m[2] !== undefined) {
      row = parseInt(m[1], 10);
      col = parseInt(m[2], 10);
    } else if (m[0].startsWith("\x1b")) {
      // non-positioning escape, skip
    } else {
      for (const ch of m[0]) {
        if (ch === "\n") { row++; col = 1; continue; }
        if (!grid.has(row)) grid.set(row, new Map());
        grid.get(row)!.set(col, ch);
        col++;
      }
    }
  }
  const rows = new Map<number, string>();
  for (const [r, cols] of grid) {
    const maxCol = Math.max(...cols.keys());
    let s = "";
    for (let c = 1; c <= maxCol; c++) s += cols.get(c) ?? " ";
    rows.set(r, s);
  }
  return rows;
}

function occupiedRowCount(rows: Map<number, string>): number {
  let count = 0;
  for (const text of rows.values()) {
    if (/\S/.test(text)) count++;
  }
  return count;
}

const BASE_INPUT_STATE: PromptInputState = {
  text: "", cursor: 0, mode: "prompt", isStashed: false,
  permissionMode: "bypass", pastedContents: null, stashNotice: "Input stashed \xB7 press Esc to restore",
};

const BASE_STATUS_PROPS: StatusLineProps = {
  permissionMode: { mode: "bypass", cycle: () => {} } as StatusLineProps["permissionMode"],
  interrupt: { interrupt: () => {} } as StatusLineProps["interrupt"],
  taskPanel: { visible: false, toggle: () => {}, tasks: [] },
  telemetry: { recentEvents: [] },
};

/** Mounts PromptInput stacked directly above StatusLine (the same order repl.ts renders them),
 * generously sized so nothing this test renders could ever be clipped by the mount's own stdout
 * size -- the reconstructed row count must reflect true content height, never a clip artifact. */
function renderPromptRegionRows(
  promptProps: PromptInputProps,
  statusProps: StatusLineProps,
): Map<number, string> {
  const chunks: string[] = [];
  const stream = { write(s: string): void { chunks.push(s); } };
  mountInk(
    React.createElement(
      Box, { flexDirection: "column" },
      React.createElement(PromptInput, { key: "input", ...promptProps }),
      React.createElement(StatusLine, { key: "status", ...statusProps }),
    ),
    { stream, stdout: { columns: 80, rows: 200 } },
  );
  return reconstructRows(chunks.join(""));
}

function rowCountProps(
  promptProps: PromptInputProps,
): PromptInputRowCountProps {
  return {
    queuedItems: promptProps.queuedItems,
    notifications: promptProps.notifications,
    isProcessing: promptProps.isProcessing,
    prefersReducedMotion: promptProps.prefersReducedMotion,
    isStashed: promptProps.state.isStashed,
    showStatusLine: promptProps.showStatusLine,
  };
}

function statusRowCountProps(statusProps: StatusLineProps): StatusLineRowCountProps {
  return {
    taskPanel: statusProps.taskPanel,
    telemetry: statusProps.telemetry,
    coordinator: statusProps.coordinator,
    effort: statusProps.effort,
    degraded: statusProps.degraded,
    outage: statusProps.outage,
  };
}

describe("promptInputRowCount + statusLineRowCount are bound to the real render across the full state range (2026-07-25 counterparty finding, fourth round)", () => {
  it("idle: no queue, no stash, not processing, no notifications -- the state the retired constant was checked against", () => {
    const promptProps: PromptInputProps = { state: BASE_INPUT_STATE, showStatusLine: false, width: 80 };
    const rows = renderPromptRegionRows(promptProps, BASE_STATUS_PROPS);
    const expected = promptInputRowCount(rowCountProps(promptProps)) + statusLineRowCount(statusRowCountProps(BASE_STATUS_PROPS));
    expect(occupiedRowCount(rows)).toBe(expected);
  });

  it("queue > QUEUE_MAX_VISIBLE (3): a visible-capped queue plus an honest overflow row", () => {
    const promptProps: PromptInputProps = {
      state: BASE_INPUT_STATE,
      queuedItems: ["one", "two", "three", "four", "five"],
      showStatusLine: false,
      width: 80,
    };
    const rows = renderPromptRegionRows(promptProps, BASE_STATUS_PROPS);
    const expected = promptInputRowCount(rowCountProps(promptProps)) + statusLineRowCount(statusRowCountProps(BASE_STATUS_PROPS));
    expect(occupiedRowCount(rows)).toBe(expected);
  });

  it("stashed input (Ctrl+S): the persistent stash-notice row", () => {
    const promptProps: PromptInputProps = {
      state: { ...BASE_INPUT_STATE, isStashed: true },
      showStatusLine: false,
      width: 80,
    };
    const rows = renderPromptRegionRows(promptProps, BASE_STATUS_PROPS);
    const expected = promptInputRowCount(rowCountProps(promptProps)) + statusLineRowCount(statusRowCountProps(BASE_STATUS_PROPS));
    expect(occupiedRowCount(rows)).toBe(expected);
  });

  it("busy + notifications + shimmer: the live multi-row-addition case (this is the seven-row witness the review named)", () => {
    const promptProps: PromptInputProps = {
      state: { ...BASE_INPUT_STATE, isStashed: true },
      isProcessing: true,
      notifications: [
        { id: "n1", message: "model roundtrip slow", kind: "info" },
        { id: "n2", message: "retrying", kind: "error" },
      ],
      showStatusLine: false,
      width: 80,
    };
    const rows = renderPromptRegionRows(promptProps, BASE_STATUS_PROPS);
    const expected = promptInputRowCount(rowCountProps(promptProps)) + statusLineRowCount(statusRowCountProps(BASE_STATUS_PROPS));
    expect(occupiedRowCount(rows)).toBe(expected);
    // Sanity: this shape genuinely adds rows over idle -- otherwise the equality above would be
    // trivially satisfied by two small numbers agreeing for the wrong reason.
    const idlePromptProps: PromptInputProps = { state: BASE_INPUT_STATE, showStatusLine: false, width: 80 };
    const idleExpected = promptInputRowCount(rowCountProps(idlePromptProps)) + statusLineRowCount(statusRowCountProps(BASE_STATUS_PROPS));
    expect(expected).toBeGreaterThan(idleExpected);
  });

  it("StatusLine's own conditional rows: degraded + effort + coordinator + telemetry + visible tasks, all live at once", () => {
    const statusProps: StatusLineProps = {
      ...BASE_STATUS_PROPS,
      taskPanel: { visible: true, toggle: () => {}, tasks: [
        { id: "t1", name: "task one", completed: false },
        { id: "t2", name: "task two", completed: true },
      ] },
      telemetry: { recentEvents: [], lastGovernor: { vramUsedGib: 12, vramTotalGib: 24 } as NonNullable<StatusLineProps["telemetry"]["lastGovernor"]> },
      coordinator: { active: true, state: { taskDescription: "d", agentCount: 2, phase: "planning" } },
      effort: { active: true, label: "high effort" },
      degraded: { active: true, endpoint: "x" },
      outage: undefined,
    };
    const promptProps: PromptInputProps = { state: BASE_INPUT_STATE, showStatusLine: false, width: 80 };
    const rows = renderPromptRegionRows(promptProps, statusProps);
    const expected = promptInputRowCount(rowCountProps(promptProps)) + statusLineRowCount(statusRowCountProps(statusProps));
    expect(occupiedRowCount(rows)).toBe(expected);
  });
});
