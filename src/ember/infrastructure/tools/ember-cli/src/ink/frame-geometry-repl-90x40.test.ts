// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Acceptance row 1 (R4b, state/specs/ember-cli-chart-height-and-frame-geometry.md): the full
// ReplScreen at 90x40. Isolated to its own file/bun-invocation -- see frame-geometry.test.ts's
// module docstring for why every ReplScreen-mounting acceptance row lives one-per-file.
import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "./reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "./rendering-pipeline.ts";
import { TerminalSizeContext } from "./components.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { ReplScreen } from "../screens/repl.ts";
import { checkFrameGeometry } from "./frame-geometry.ts";

function renderedLines(raw: string, columns: number, rows: number): string[] {
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
}

function mountReplAt(columns: number, rows: number): string[] {
  resetCommandRegistryForTests();
  let raw = "";
  const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
  const element = React.createElement(
    TerminalSizeContext.Provider,
    { value: { columns, rows } },
    React.createElement(ReplScreen, {
      config,
      cwd: process.cwd(),
      env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
      onExit: () => {},
    }),
  );
  mountInk(element, { stream: { write(s: string) { raw += s; } }, stdout: { columns, rows } });
  return renderedLines(raw, columns, rows);
}

describe("frame geometry — R4b acceptance row 1 (90x40)", () => {
  test("every box closes at 90x40 -- zero violations, homescreen panel corner-closed and not clipped", () => {
    const lines = mountReplAt(90, 40);
    const result = checkFrameGeometry(lines);
    expect(result.violations).toEqual([]);
    const homescreenPanel = result.boxes.find(
      (b) => b.styleName === "round" && b.leftCol === 0 && b.topRow === 0,
    );
    expect(homescreenPanel).toBeDefined();
    expect(homescreenPanel!.clipped).toBe(false);
    expect(homescreenPanel!.rightCol).toBe(52);
    // Every row strictly between top and bottom must hold the vertical glyph at both edges --
    // this is exactly what the pre-fix right-edge drop (state/operator-pass-2026-07-26.md W2)
    // would fail (RED-baseline regression guard).
    for (let r = homescreenPanel!.topRow + 1; r < homescreenPanel!.bottomRow; r++) {
      expect(lines[r]![homescreenPanel!.leftCol]).toBe("│");
      expect(lines[r]![homescreenPanel!.rightCol]).toBe("│");
    }
  });
});
