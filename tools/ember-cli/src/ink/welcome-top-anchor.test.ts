// welcome-top-anchor.test.ts — B7 item 2 regrade ("welcome void dominance", operator regrade
// 2026-07-03): mounts the SAME building blocks repl.ts composes (transcript wrapper +
// welcome/Homescreen + input-wrap + status-wrap) via the production frame parser, matching this
// campaign's isolation-test lesson (an explicit-height/synthetic-Box stand-in hid instance 4's
// bug entirely -- the wiring test must mount the SAME composition production uses, not a
// convenient substitute). Covers both halves of transcriptJustifyContent's anchor flip:
//   - welcome-only (fresh boot): panel top-anchors, so content starts near row 0.
//   - welcome + a landed turn: transcript still bottom-anchors (hugs the prompt), unchanged from
//     the existing B7 item 2 "kill the void" behavior.
import { describe, test, expect } from "bun:test";
import React from "react";
import { Box } from "./components.ts";
import { mountInk } from "./reconciler.ts";
import { renderMsgDispatch, transcriptJustifyContent, transcriptFlexGrow } from "../screens/repl.ts";
import { buildMessageLookups } from "../components/message-renderers.ts";
import { StatusLine } from "../components/status-bar.ts";
import { PromptInput } from "../components/prompt-input.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "./rendering-pipeline.ts";
import type { SessionMessage } from "../components/app-shell.ts";

const COLS = 170;
const ROWS = 71;

function buildScreen(messages: SessionMessage[]) {
  const lookups = buildMessageLookups([]);
  const rendered = messages.map((m) =>
    renderMsgDispatch(m, lookups, COLS, {
      green: 23, total: 30, pctComplete: 76.7, topAttention: [],
    }),
  );

  return React.createElement(
    Box, { flexDirection: "column", height: ROWS },
    React.createElement(
      Box,
      { key: "transcript", flexDirection: "column", flexGrow: transcriptFlexGrow(messages), overflow: "hidden", justifyContent: transcriptJustifyContent(messages) },
      ...rendered,
    ),
    React.createElement(
      Box, { key: "input-wrap", flexShrink: 0 },
      React.createElement(PromptInput, {
        state: { text: "", mode: "prompt", isStashed: false, permissionMode: "bypass", pastedContents: null, stashNotice: "" },
        isProcessing: false, showStatusLine: false, width: COLS,
      }),
    ),
    React.createElement(
      Box, { key: "status-wrap", flexShrink: 0 },
      React.createElement(StatusLine, {
        permissionMode: { mode: "bypass", cycle: () => {} },
        interrupt: { interrupt: () => {} },
        taskPanel: { visible: false, toggle: () => {}, tasks: [] },
        modelMetrics: { contextTokens: 0, maxContextTokens: 32000, vramUsedGb: 19.2, vramTotalGb: 24.0, tokensPerSec: 0 },
        observatory: { board: { green: 23, total: 30 }, activeRun: null },
        width: COLS,
      }),
    ),
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

describe("welcome-only state top-anchors (transcriptJustifyContent regression)", () => {
  test(`fresh boot at ${COLS}x${ROWS}: panel top row is near the top of the viewport, not the bottom`, () => {
    const messages: SessionMessage[] = [{ id: "w1", type: "welcome", model: "ember", cwd: "x", content: "hi" }];
    const frame = captureFrame(messages);
    const topRow = firstNonBlankRow(frame);
    expect(topRow).toBeGreaterThanOrEqual(0);
    // The regression this guards: before the fix, justifyContent:"flex-end" pushed the whole
    // welcome panel down near the input-wrap, leaving 50+ rows of pure black above it. Top-anchor
    // means content starts within the first couple of rows.
    expect(topRow).toBeLessThanOrEqual(2);
  });

  test("adding one conversation entry flips the anchor back to the bottom (existing kill-the-void behavior preserved)", () => {
    const messages: SessionMessage[] = [
      { id: "w1", type: "welcome", model: "ember", cwd: "x", content: "hi" },
      { id: "u1", type: "user", content: "hello" },
    ];
    const frame = captureFrame(messages);
    const topRow = firstNonBlankRow(frame);
    // Once a real turn has landed, the anchor is flex-end again -- content should now sit LOW in
    // the viewport (hugging the input/status chrome), not near row 0.
    expect(topRow).toBeGreaterThan(10);
  });
});

// issue #44 item (c) -- "document-flow" (operator's live-pixel verdict, 2026-07-04) -- REVERTED
// by issue #114's final leg (operator's live DESKTOP-scale verdict, 2026-07-05). The document-flow
// fix set flexGrow:0 for welcome-only sessions on the theory that the field exemplar "never
// stretches at session start" -- a real side-by-side desktop capture (half-split 1720x1440, the
// exemplar visible in the same frame) disproved that: the exemplar pins prompt+status to the
// WINDOW BOTTOM even when almost no content exists above. flexGrow:0 instead left input+status
// floating directly under a content-sized panel with ~85% of the terminal below the status bar
// completely unclaimed -- worse than the "gap between panel and input" the document-flow fix was
// chasing (that gap sits INSIDE the frame, above the prompt, which is exactly the exemplar's own
// shape). This block now asserts the CORRECTED behavior: input+status pin to the true bottom rows
// in every state, welcome-only included. transcriptJustifyContent (unchanged, tested above) still
// controls where content sits inside that grown box.
function findCaretRow(frame: ReturnType<typeof buildFrame>): number {
  for (let r = 0; r < ROWS; r++) {
    const line = frame.cells[r]!.map((c) => c?.char ?? " ").join("");
    if (line.includes("❯")) return r;
  }
  return -1;
}

describe("height-fill: input pins to the viewport bottom regardless of content (issue #114 final leg)", () => {
  test(`welcome-only at ${COLS}x${ROWS}: the input row sits at the true bottom, not floating under the panel`, () => {
    const messages: SessionMessage[] = [{ id: "w1", type: "welcome", model: "ember", cwd: "x", content: "hi" }];
    const frame = captureFrame(messages);
    const caretRow = findCaretRow(frame);
    expect(caretRow).toBeGreaterThanOrEqual(0);
    // The regression this guards: under the reverted document-flow fix, caretRow sat well above
    // the viewport bottom (content-sized box, input followed immediately). Now the transcript
    // Box's flexGrow:1 pushes input-wrap/status-wrap down to the true bottom rows regardless of
    // how little content the welcome panel contributes.
    expect(caretRow).toBeGreaterThanOrEqual(ROWS - 6);
  });

  test("content exceeding the viewport: the input row still sits at the true bottom (existing overflow-clip behavior unaffected)", () => {
    const messages: SessionMessage[] = [
      { id: "w1", type: "welcome", model: "ember", cwd: "x", content: "hi" },
      ...Array.from({ length: 40 }, (_, i) => ({ id: `u${i}`, type: "user" as const, content: `turn number ${i}` })),
    ];
    const frame = captureFrame(messages);
    const caretRow = findCaretRow(frame);
    expect(caretRow).toBeGreaterThanOrEqual(0);
    // With far more content than the viewport can hold, the transcript's flexGrow must still be 1
    // (or the input-wrap/status-wrap would be crushed off-screen or overlap the transcript) -- the
    // input row belongs at the bottom of the viewport here, same as before this fix (unchanged).
    expect(caretRow).toBeGreaterThanOrEqual(ROWS - 6);
  });
});
