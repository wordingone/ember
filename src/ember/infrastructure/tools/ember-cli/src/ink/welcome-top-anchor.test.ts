// welcome-top-anchor.test.ts — #561/#565: banner extraction (issue #561 P0-A item 3) turned the
// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// welcome/board panel from a `messages[0]` transcript entry into an always-mounted, top-locked
// region, structurally separate from the scrolling transcript below it (see screens/repl.ts's
// render tree). This file used to mount a synthetic composition where the welcome panel WAS
// `messages[0]` -- that assumption is now false (repl.ts's `messages` state starts empty and never
// contains a `{type:"welcome"}` entry for a fresh session), so this rewrite mounts the SAME
// three-region composition production actually renders: banner (flexShrink:0) + transcript
// (flexGrow:1 / overflow:hidden / justifyContent) + input-wrap + status-wrap.
//
// Covers, updated for the new architecture:
//   - the banner region top-anchors unconditionally (row 0), regardless of transcript message
//     count -- the structural guarantee the extraction exists to provide (issue #561 AC-1's
//     locked-regions contract, at the unit level rather than a 500-event flood).
//   - transcriptJustifyContent's anchor flip is now purely about REAL messages: zero messages ->
//     flex-start; one or more -> flex-end (unchanged behavior, re-expressed against the new
//     "no welcome entry" input shape).
//   - height-fill: input/status still pin to the true viewport bottom regardless of banner or
//     transcript content (issue #114 final leg, unaffected by the extraction).
import { describe, test, expect } from "bun:test";
import React from "react";
import { Box } from "./components.ts";
import { mountInk } from "./reconciler.ts";
import { renderMsgDispatch, transcriptJustifyContent, transcriptFlexGrow } from "../screens/repl.ts";
import { buildMessageLookups } from "../components/message-renderers.ts";
import { StatusLine } from "../components/status-bar.ts";
import { PromptInput } from "../components/prompt-input.ts";
import { Homescreen } from "../components/logo-homescreen.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "./rendering-pipeline.ts";
import type { SessionMessage } from "../components/app-shell.ts";

const COLS = 170;
const ROWS = 71;

function buildScreen(messages: SessionMessage[]) {
  const lookups = buildMessageLookups([]);
  const rendered = messages.map((m) => renderMsgDispatch(m, lookups, COLS));

  // Mirrors screens/repl.ts's render tree exactly, including its absence of wrapping Boxes
  // around PromptInput/StatusLine -- both components protect their OWN root with flexShrink:0
  // now (issue #561 P0-A item 1); an artificial wrapping Box here would mask a regression of
  // that exact fix instead of catching it.
  return React.createElement(
    Box, { flexDirection: "column", height: ROWS },

    // Banner -- always mounted, top-locked. It is no longer messages[0], so it is never absent
    // and never keyed off `messages` at all.
    React.createElement(
      Box, { key: "banner", flexShrink: 0 },
      React.createElement(Homescreen, {
        state: { model: "ember", cwd: "x", version: "0.0.0", dataRoot: "" },
        viewportWidth: COLS,
      }),
    ),

    React.createElement(
      Box,
      { key: "transcript", flexDirection: "column", flexGrow: transcriptFlexGrow(messages), overflow: "hidden", justifyContent: transcriptJustifyContent(messages) },
      ...rendered,
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

function captureFrame(messages: SessionMessage[]) {
  let raw = "";
  mountInk(buildScreen(messages), { stream: { write(s: string) { raw += s; } }, stdout: { columns: COLS, rows: ROWS } });
  const frame = buildFrame(COLS, ROWS);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame;
}

function firstNonBlankRow(frame: ReturnType<typeof buildFrame>): number {
  for (let r = 0; r < ROWS; r++) {
    const line = frame.cells[r]!.map((c) => c?.char ?? " ").join("");
    if (line.trim().length > 0) return r;
  }
  return -1;
}

describe("banner region top-anchors unconditionally (#561/#565 extraction)", () => {
  test(`zero real messages at ${COLS}x${ROWS}: banner starts within the first couple of rows`, () => {
    const frame = captureFrame([]);
    const topRow = firstNonBlankRow(frame);
    expect(topRow).toBeGreaterThanOrEqual(0);
    expect(topRow).toBeLessThanOrEqual(2);
  });

  test("banner still starts at the top with real turns landed (it no longer scrolls away with the transcript)", () => {
    const messages: SessionMessage[] = [{ id: "u1", type: "user", content: "hello" }];
    const frame = captureFrame(messages);
    const topRow = firstNonBlankRow(frame);
    // The regression this guards: before the extraction, the banner WAS messages[0] inside the
    // flex-end-anchored transcript -- the moment a real turn landed, flex-end pushed the whole
    // transcript (banner included) down toward the input/status chrome (the operator's "banner
    // scrolled away" report). The banner is now a structurally separate top-locked region, so it
    // stays at row 0 regardless of transcript content.
    expect(topRow).toBeGreaterThanOrEqual(0);
    expect(topRow).toBeLessThanOrEqual(2);
  });
});

describe("transcriptJustifyContent anchor flip (re-expressed for the no-welcome-entry input shape)", () => {
  test("zero real messages -> flex-start (nothing to bottom-anchor)", () => {
    expect(transcriptJustifyContent([])).toBe("flex-start");
  });

  test("one or more real messages -> flex-end (kill-the-void behavior, unchanged)", () => {
    expect(transcriptJustifyContent([{ id: "u1", type: "user", content: "hello" }])).toBe("flex-end");
  });
});

function findCaretRow(frame: ReturnType<typeof buildFrame>): number {
  for (let r = 0; r < ROWS; r++) {
    const line = frame.cells[r]!.map((c) => c?.char ?? " ").join("");
    if (line.includes("❯")) return r;
  }
  return -1;
}

describe("height-fill: input pins to the viewport bottom regardless of content (issue #114 final leg, unaffected by the banner extraction)", () => {
  test(`zero real messages at ${COLS}x${ROWS}: the input row sits at the true bottom, not floating under the banner`, () => {
    const frame = captureFrame([]);
    const caretRow = findCaretRow(frame);
    expect(caretRow).toBeGreaterThanOrEqual(0);
    // The regression this guards: input+status must pin to the true bottom rows regardless of how
    // little (or how much) content sits above them -- unchanged by the banner extraction, since
    // transcriptFlexGrow is still always 1 and the banner itself is flexShrink:0.
    expect(caretRow).toBeGreaterThanOrEqual(ROWS - 6);
  });

  test("content exceeding the viewport: the input row still sits at the true bottom (existing overflow-clip behavior unaffected)", () => {
    const messages: SessionMessage[] = Array.from(
      { length: 40 },
      (_, i) => ({ id: `u${i}`, type: "user" as const, content: `turn number ${i}` }),
    );
    const frame = captureFrame(messages);
    const caretRow = findCaretRow(frame);
    expect(caretRow).toBeGreaterThanOrEqual(0);
    expect(caretRow).toBeGreaterThanOrEqual(ROWS - 6);
  });
});
