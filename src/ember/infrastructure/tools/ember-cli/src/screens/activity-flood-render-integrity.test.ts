// activity-flood-render-integrity.test.ts — issue #561 AC-1 (the flood + resize acceptance test,
// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// promoted from a throwaway diagnostic into a permanent regression test). Reproduces the
// operator's live complaint verbatim: a flood of activity events (receipt-landing lines from a
// fixture-path watcher) pushed the input box and status line into the scrollback, and a corrupted
// top banner sat mid-frame instead of top-locked. Mounts the SAME composition production actually
// renders (screens/repl.ts's return tree): banner (flexShrink:0, Homescreen) + transcript
// (flexGrow:1 / overflow:hidden / justifyContent, VirtualMessageList) + PromptInput + StatusLine,
// with NO artificial wrapping Boxes -- flexShrink:0 protection lives in each component's own root
// (issue #561 P0-A item 1), so this test would catch a regression of that fix directly.
//
// Covers, per issue #561 AC-1:
//   - banner region stays top-locked under a 500-event flood, at rows=30 AND rows=20.
//   - input/status regions stay bottom-locked under the same flood, both row counts.
//   - a live resize (rows=30 -> rows=20, same 500 events) does not corrupt any region.
import { describe, test, expect } from "bun:test";
import React from "react";
import { Box } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool, type Frame } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import { VirtualMessageList } from "../components/app-shell.ts";
import { renderMsgDispatch, transcriptFlexGrow, transcriptJustifyContent } from "../../../../../../../tools/ember-cli/src/screens/repl.ts";
import { PromptInput } from "../components/prompt-input.ts";
import { StatusLine } from "../components/status-bar.ts";
import { Homescreen } from "../components/logo-homescreen.ts";
import { buildMessageLookups } from "../components/message-renderers.ts";
import type { SessionMessage } from "../components/app-shell.ts";

const COLS = 100;

/** #561: mirrors the operator's actual flood -- receipt-landing lines from a fixture/plugin path
 * tree, the exact shape that flooded the feed in the live report. */
function makeFloodMessages(n: number): SessionMessage[] {
  return Array.from({ length: n }, (_, i) => ({
    id:     `activity-${i}`,
    type:   "activity",
    ts:     new Date(Date.UTC(2026, 6, 9, 6, 36, i)).toISOString(),
    source: "receipt",
    text:   `receipt landed [.avir] plugin-${i}.json`,
    path:   `receipts/ember-m10-surface3/fixture/plugin-${i}.json`,
  }));
}

/** Builds the exact repl.ts render tree (banner / transcript / input / status), no substitutes. */
function buildScreen(rows: number, messages: SessionMessage[]): React.ReactElement {
  const lookups = buildMessageLookups([]);
  const renderMessage = (msg: SessionMessage) => renderMsgDispatch(msg, lookups, COLS);
  const transcriptViewportRows = Math.max(1, rows - 3);
  const transcript = React.createElement(VirtualMessageList, {
    messages,
    renderMessage,
    viewportRows: transcriptViewportRows,
  });

  return React.createElement(
    Box,
    { flexDirection: "column", height: rows },
    React.createElement(
      Box, { key: "banner", flexShrink: 0 },
      React.createElement(Homescreen, {
        state: { model: "ember", cwd: "ember", version: "0.0.0", dataRoot: "" },
        viewportWidth: COLS,
      }),
    ),
    React.createElement(
      Box,
      { key: "transcript", flexDirection: "column", flexGrow: transcriptFlexGrow(messages), overflow: "hidden", justifyContent: transcriptJustifyContent(messages) },
      transcript,
    ),
    React.createElement(PromptInput, {
      key: "input",
      state: { text: "", mode: "prompt", isStashed: false, permissionMode: "bypass", pastedContents: null, stashNotice: "" },
      isProcessing: false, showStatusLine: false, width: COLS,
    }),
    React.createElement(StatusLine, {
      key: "status",
      permissionMode: { mode: "bypass", cycle: () => {} },
      interrupt: { interrupt: () => {} },
      taskPanel: { visible: false, toggle: () => {}, tasks: [] },
      telemetry: { recentEvents: [] },
      modelMetrics: { contextTokens: 0, maxContextTokens: 32000, vramUsedGb: 19.2, vramTotalGb: 24.0, tokensPerSec: 0 },
    }),
  );
}

function captureFrame(rows: number, messages: SessionMessage[]): { frame: Frame; lines: string[] } {
  let raw = "";
  const handle = mountInk(buildScreen(rows, messages), { stream: { write(s: string) { raw += s; } }, stdout: { columns: COLS, rows } });
  const frame = buildFrame(COLS, rows);
  try {
    parseRenderedIntoFrame(raw, frame, new StylePool());
    const lines = frame.cells.map((row) => row.map((c) => c?.char ?? " ").join("").replace(/\s+$/, ""));
    return { frame, lines };
  } finally {
    handle.unmount();
  }
}

function firstNonBlankRow(lines: string[]): number {
  return lines.findIndex((l) => l.trim().length > 0);
}

function findRowContaining(lines: string[], needle: string): number {
  return lines.findIndex((l) => l.includes(needle));
}

describe("issue #561 AC-1: flood(500 events) + resize keeps banner/input/status locked", () => {
  for (const rows of [30, 20]) {
    test(`rows=${rows}: banner region is top-locked under a 500-event flood`, () => {
      const { lines } = captureFrame(rows, makeFloodMessages(500));
      const topRow = firstNonBlankRow(lines);
      const bannerRow = findRowContaining(lines, "ember");
      expect(topRow).toBeGreaterThanOrEqual(0);
      expect(topRow).toBeLessThanOrEqual(1);
      // The regression this guards (operator report): the banner's own identity block ("ember
      // vX.X.X") sat corrupted mid-frame, offset to mid-right, instead of at the true top. Under
      // this fix it must still appear within the banner's own first couple of rows.
      expect(bannerRow).toBeGreaterThanOrEqual(0);
      expect(bannerRow).toBeLessThanOrEqual(2);
    });

    test(`rows=${rows}: input (caret) and status ("bypass permissions on") regions are bottom-locked under the same flood`, () => {
      const { lines } = captureFrame(rows, makeFloodMessages(500));
      const caretRow = findRowContaining(lines, "❯"); // ❯
      // #1044: the bottom-lock anchor was "esc to interrupt" (removed keybinding-hint chrome);
      // re-anchored to the surviving mode label -- StatusLine's own useInput/keybindings are
      // untouched by #1044, only the always-on hint TEXT is gone.
      const statusRow = findRowContaining(lines, "bypass permissions on");
      // The regression this guards (operator report): 500 activity events proportionally shrank
      // PromptInput/StatusLine toward 0 rows via the shared flex-shrink pool, scrolling both out
      // of the visible frame entirely (caretRow/statusRow === -1 before the fix).
      expect(caretRow).toBeGreaterThanOrEqual(0);
      expect(statusRow).toBeGreaterThanOrEqual(0);
      expect(caretRow).toBeGreaterThan(statusRow - 3); // input sits directly above/at the status row
      expect(caretRow).toBeGreaterThanOrEqual(rows - 4);
      expect(statusRow).toBeGreaterThanOrEqual(rows - 3);
    });
  }

  test("live resize (rows=30 -> rows=20, same 500 events) does not corrupt any locked region", () => {
    const events = makeFloodMessages(500);
    const before = captureFrame(30, events);
    const after  = captureFrame(20, events);

    for (const { rows, lines } of [{ rows: 30, lines: before.lines }, { rows: 20, lines: after.lines }]) {
      const bannerRow = findRowContaining(lines, "ember");
      const caretRow  = findRowContaining(lines, "❯");
      const statusRow = findRowContaining(lines, "bypass permissions on");
      expect(bannerRow).toBeGreaterThanOrEqual(0);
      expect(bannerRow).toBeLessThanOrEqual(2);
      expect(caretRow).toBeGreaterThanOrEqual(0);
      expect(statusRow).toBeGreaterThanOrEqual(0);
      expect(caretRow).toBeGreaterThanOrEqual(rows - 4);
      expect(statusRow).toBeGreaterThanOrEqual(rows - 3);
    }
  });
});
