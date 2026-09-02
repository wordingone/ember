// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Issue #1043: Text wrapping is a renderer contract, not an ancestor clip side effect.
import { describe, expect, test } from "bun:test";
import React from "react";
import { Box, Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import { ActivityTranscriptBlock } from "../components/activity-feed-pane.ts";

function renderLines(element: React.ReactElement, columns = 20, rows = 8): string[] {
  let output = "";
  mountInk(element, {
    stream: { write(chunk: string) { output += chunk; } },
    stdout: { columns, rows },
  });
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(output, frame, new StylePool());
  return frame.cells.map((row) => row.map((cell) => cell.char).join("").trimEnd());
}

describe("Text wrap policy", () => {
  test("wrap uses word boundaries, grows layout rows, and preserves every character", () => {
    const lines = renderLines(
      React.createElement(
        Box,
        { width: 10, flexDirection: "column", overflow: "hidden" },
        React.createElement(Text, { wrap: "wrap" }, "alpha beta gamma delta"),
        React.createElement(Text, null, "sentinel"),
      ),
      20,
      8,
    );

    expect(lines.slice(0, 4)).toEqual(["alpha beta", "gamma", "delta", "sentinel"]);
    expect(lines.slice(0, 3).join(" ")).toBe("alpha beta gamma delta");
  });

  test("wrap is the default and hard-wraps an overlong token without losing cells", () => {
    const lines = renderLines(
      React.createElement(
        Box,
        { width: 5, flexDirection: "column", overflow: "hidden" },
        React.createElement(Text, null, "ABCDEFGHIJK"),
      ),
      12,
      5,
    );

    expect(lines.slice(0, 3)).toEqual(["ABCDE", "FGHIJ", "K"]);
  });
  test("truncate-end stays one row and ends with an ellipsis", () => {
    const lines = renderLines(
      React.createElement(
        Box,
        { width: 8, flexDirection: "column", overflow: "hidden" },
        React.createElement(Text, { wrap: "truncate-end" }, "watchdog activity"),
        React.createElement(Text, null, "sentinel"),
      ),
      16,
      5,
    );

    expect(lines[0]).toBe("watchdo…");
    expect(lines[1]).toBe("sentinel");
  });

  test.each([60, 80, 100])(
    "a production watchdog activity card preserves its full message at %i columns",
    (columns) => {
      const message =
        "watchdog launch packet rejected because the checkpoint identity changed during verification";
      const lines = renderLines(
        React.createElement(
          Box,
          { width: columns, flexDirection: "column", overflow: "hidden" },
          React.createElement(ActivityTranscriptBlock, {
            line: {
              ts: "2026-07-28T00:00:00.000Z",
              source: "watchdog",
              text: message,
            },
            nowMs: Date.parse("2026-07-28T00:00:01.000Z"),
          }),
        ),
        columns,
        20,
      );
      const visible = lines.filter((line) => line.length > 0);
      expect(visible.every((line) => [...line].length <= columns)).toBe(true);
      const flattened = visible.join(" ");
      for (const word of message.split(" ")) {
        expect(flattened).toContain(word);
      }
    },
  );

  test("a half-width production activity row preserves one long filename", () => {
    const token = "checkpoint-identity-changed-during-watchdog-launch-packet-verification.json";
    const lines = renderLines(
      React.createElement(
        Box,
        { width: 30, flexDirection: "column", overflow: "hidden" },
        React.createElement(ActivityTranscriptBlock, {
          line: {
            ts: "2026-07-28T00:00:00.000Z",
            source: "receipt",
            text: `receipt landed [watchdog] ${token} - REJECTED`,
          },
          nowMs: Date.parse("2026-07-28T00:00:01.000Z"),
        }),
      ),
      30,
      12,
    );
    expect(lines.map((line) => line.replace(/^  /u, "")).join("")).toContain(token);
  });
});
