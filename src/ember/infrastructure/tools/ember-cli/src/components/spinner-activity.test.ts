// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// #2380 S24: while a tool runs, the spinner names it, counts its own time and shows the last line
// of output, instead of "Thinking… 6m 29s".
import { expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import {
  fitActivityLabel,
  formatSpinnerTail,
  pickSpinnerActivity,
  runningToolLabel,
  SpinnerAnimationRow,
  type ActiveToolCall,
} from "./spinner.ts";

function renderLines(element: React.ReactElement, columns: number, rows: number): string[] {
  let output = "";
  mountInk(element, { stream: { write(chunk: string) { output += chunk; } }, stdout: { columns, rows } });
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(output, frame, new StylePool());
  return frame.cells.map((row) => row.map((cell) => cell.char).join("").trimEnd());
}

const call = (over: Partial<ActiveToolCall> = {}): ActiveToolCall => ({
  toolName: "Bash", summary: "ping -t 127.0.0.1", startedAt: 1_000, tail: "", ...over,
});

test("no running tool and no approval: the spinner stays on Thinking", () => {
  expect(pickSpinnerActivity([], null, 5_000)).toBeUndefined();
});

test("a running tool is named with its own elapsed time", () => {
  const a = pickSpinnerActivity([call()], null, 7_500)!;
  expect(a.label).toBe("Running Bash: ping -t 127.0.0.1");
  expect(a.elapsedMs).toBe(6_500);
  expect(a.tail).toBeUndefined();
});

test("with several calls running (an Agent and the tool it started) the newest names the spinner", () => {
  const a = pickSpinnerActivity([call({ toolName: "Agent", summary: "explore", startedAt: 1_000 }), call({ startedAt: 2_000, tail: "Reply from 127.0.0.1" })], null, 3_000)!;
  expect(a.label).toBe("Running Bash: ping -t 127.0.0.1");
  expect(a.tail).toBe("Reply from 127.0.0.1");
});

test("a pending approval wins: nothing is running while the user is asked", () => {
  const a = pickSpinnerActivity([call()], { summary: "Bash: rd /s /q decoy", since: 4_000 }, 6_000)!;
  expect(a.label).toBe("Waiting for your approval: Bash: rd /s /q decoy");
  expect(a.elapsedMs).toBe(2_000);
});

test("a long command is cut in the label; an empty summary still names the tool", () => {
  expect(runningToolLabel("Bash", "x".repeat(200)).length).toBeLessThan(80);
  expect(runningToolLabel("Read", "")).toBe("Running Read");
});

test("the tail row is one dim line cut to the width", () => {
  expect(formatSpinnerTail("  Reply   from\t127.0.0.1  ", 80)).toBe("  ⎿ Reply from 127.0.0.1");
  const cut = formatSpinnerTail("y".repeat(300), 40);
  expect(cut.length).toBeLessThanOrEqual(40);
  expect(cut.endsWith("…")).toBe(true);
});

test("rendered: the row says Running Bash with the tool's elapsed time, never Thinking, and the tail sits under it", () => {
  const lines = renderLines(
    React.createElement(SpinnerAnimationRow, {
      elapsedMs: 389_000,
      startedAtMs: 0,
      width: 70,
      activity: { label: "Running Bash: ping -t 127.0.0.1", elapsedMs: 389_000, tail: "Reply from 127.0.0.1: bytes=32" },
    }),
    80, 6,
  );
  const text = lines.join("\n");
  expect(lines[0]).toContain("Running Bash: ping -t 127.0.0.1");
  expect(lines[0]).toContain("6m 29s");
  expect(lines[0]).toContain("Esc to interrupt");
  expect(text).not.toContain("Thinking");
  expect(lines[1]).toContain("Reply from 127.0.0.1: bytes=32");
});

test("rendered without an activity: unchanged, still Thinking", () => {
  const lines = renderLines(
    React.createElement(SpinnerAnimationRow, { elapsedMs: 5_000, startedAtMs: 0 }),
    80, 3,
  );
  expect(lines[0]).toContain("Thinking…");
  expect(lines[0]).toContain("5s");
});

test("the label is cut so the time and the Esc hint stay on the same row", () => {
  const long = { label: "Waiting for your approval: Bash: command=echo " + "x".repeat(80), elapsedMs: 65_000 };
  const fit = fitActivityLabel(long, 60);
  expect(fit.length + " 1m 05s · Esc to interrupt".length + 2).toBeLessThanOrEqual(60);
  expect(fit.endsWith("…")).toBe(true);
  expect(fitActivityLabel({ label: "Running Bash: ls", elapsedMs: 0 }, 60)).toBe("Running Bash: ls");
  expect(fitActivityLabel(long)).toBe(long.label);
  const lines = renderLines(
    React.createElement(SpinnerAnimationRow, { elapsedMs: 1_000, startedAtMs: 0, width: 60, activity: long }),
    60, 4,
  );
  expect(lines[0]).toContain("Esc to interrupt");
  expect(lines[0]).toContain("Waiting for your approval");
  expect(lines[1] ?? "").toBe("");
});
