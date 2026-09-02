// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { EventEmitter } from "node:events";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import React, { useState } from "react";
import { Box, Text } from "../ink/components.ts";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import { startStdinBridge } from "../ink/stdin-bridge.ts";
import { VirtualMessageList } from "../components/app-shell.ts";
import { OperatorSurfacePane } from "../components/operator-surface-pane.ts";
import { isExitCommandInput, transcriptViewportJustifyContent } from "../../../../../../../tools/ember-cli/src/screens/repl.ts";

class FakeStdin extends EventEmitter {
  isTTY = true;
  setRawMode(): void {}
  resume(): void {}
  pause(): void {}
}

async function flush(times = 5): Promise<void> {
  for (let index = 0; index < times; index += 1) {
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
}

function renderedLines(raw: string, columns: number, rows: number): string[] {
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
}

function locate(lines: string[], needle: string): { col: number; row: number } {
  for (let row = 0; row < lines.length; row += 1) {
    const col = lines[row]!.indexOf(needle);
    if (col >= 0) return { col, row };
  }
  throw new Error(`missing rendered needle: ${needle}`);
}

function wheelUp(col: number, row: number): string {
  return `\x1b[<64;${col + 1};${row + 1}M`;
}

describe("fixed cockpit scroll containment", () => {
  test("the production transcript flex item can shrink inside the fixed viewport", () => {
    const source = readFileSync(join(import.meta.dir, "repl.ts"), "utf8");
    expect(source).toContain(
      'key: "transcript", flexDirection: "column", flexGrow: 1, minWidth: 0, minHeight: 0, overflow: "hidden"',
    );
  });

  test("virtual transcript owns bottom anchoring without a conflicting flex-end parent", () => {
    const messages = [{ id: "landed", type: "assistant", content: "landed" }] as any;
    expect(transcriptViewportJustifyContent(true, messages)).toBe("flex-start");
    expect(transcriptViewportJustifyContent(false, messages)).toBe("flex-end");
    expect(transcriptViewportJustifyContent(true, [])).toBe("flex-start");

    const source = readFileSync(join(import.meta.dir, "repl.ts"), "utf8");
    expect(source).toContain(
      "justifyContent: transcriptViewportJustifyContent(useVirtualScroll, messages)",
    );
  });
  test("accepts only exact exit commands as clean operator lifecycle requests", () => {
    expect(isExitCommandInput("/exit")).toBe(true);
    expect(isExitCommandInput("/quit  ")).toBe(true);
    expect(isExitCommandInput("/exit now")).toBe(false);
    expect(isExitCommandInput("exit")).toBe(false);
  });


  test("raw pointer wheels independently move only transcript or activity while chrome stays fixed", async () => {
    const columns = 100;
    const rows = 30;
    const messages = Array.from({ length: 8 }, (_, index) => ({
      id: `message-${index}`,
      role: "assistant",
      content: `message-${index}`,
    })) as any;
    const activityLines = Array.from({ length: 4 }, (_, index) => ({
      ts: `2026-07-31T12:00:0${index}.000Z`,
      source: "goal" as const,
      text: `activity-${index}`,
    }));

    function Harness(): React.ReactElement {
      const [activityOffset, setActivityOffset] = useState(0);
      return React.createElement(
        Box,
        { flexDirection: "row", width: columns, height: rows, overflow: "hidden" },
        React.createElement(
          Box,
          { flexDirection: "column", width: 58, height: rows, overflow: "hidden" },
          React.createElement(Box, { height: 2, flexShrink: 0 }, React.createElement(Text, null, "EMBER HERO FIXED")),
          React.createElement(
            Box,
            { flexDirection: "column", flexGrow: 1, minHeight: 0, overflow: "hidden" },
            React.createElement(VirtualMessageList, {
              messages,
              viewportRows: 4,
              renderMessage: (message: any) => React.createElement(Text, null, message.content),
            }),
          ),
          React.createElement(Box, { height: 2, flexShrink: 0 }, React.createElement(Text, null, "PROMPT FIXED")),
        ),
        React.createElement(OperatorSurfacePane, {
          telemetry: { recentEvents: [], channelStatus: "UNKNOWN" },
          activityLines,
          activityScrollOffset: activityOffset,
          onActivityScroll: (deltaY) => setActivityOffset((current) =>
            Math.max(0, Math.min(activityLines.length - 1, current + (deltaY < 0 ? 1 : -1)))),
          width: 42,
          height: rows,
          terminalColumns: columns,
          terminalRows: rows,
        }),
      );
    }

    let raw = "";
    const handle = mountInk(React.createElement(Harness), {
      stream: { write(chunk: string) { raw += chunk; } },
      stdout: { columns, rows },
    });
    const stdin = new FakeStdin();
    const stopBridge = startStdinBridge({ stdin: stdin as never, emitKeypressEvents: () => {} });
    try {
      await flush();
      let lines = renderedLines(raw, columns, rows);
      const latestTranscript = locate(lines, "message-7");
      const latestActivity = locate(lines, "activity-3");
      expect(lines.some((line) => line.includes("EMBER HERO FIXED"))).toBe(true);
      expect(lines.some((line) => line.includes("PROMPT FIXED"))).toBe(true);
      expect(lines.some((line) => line.includes("LIVE RUN / ACTIVITY/EVENT FEED"))).toBe(true);

      stdin.emit("data", Buffer.from(wheelUp(latestTranscript.col, latestTranscript.row)));
      await flush();
      lines = renderedLines(raw, columns, rows);
      expect(lines.some((line) => line.includes("message-6"))).toBe(true);
      expect(lines.some((line) => line.includes("message-7"))).toBe(false);
      expect(lines.some((line) => line.includes("activity-3"))).toBe(true);

      const activityAfterTranscriptWheel = locate(lines, "activity-3");
      stdin.emit("data", Buffer.from(wheelUp(activityAfterTranscriptWheel.col, activityAfterTranscriptWheel.row)));
      await flush();
      lines = renderedLines(raw, columns, rows);
      expect(lines.some((line) => line.includes("activity-2"))).toBe(true);
      expect(lines.some((line) => line.includes("activity-3"))).toBe(false);
      expect(lines.some((line) => line.includes("message-6"))).toBe(true);
      expect(lines.some((line) => line.includes("EMBER HERO FIXED"))).toBe(true);
      expect(lines.some((line) => line.includes("PROMPT FIXED"))).toBe(true);
    } finally {
      stopBridge();
      handle.unmount();
    }
  });
});
