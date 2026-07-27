// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Acceptance row 2 half B (R4b): identical verdict at 120x44 -- panelIsRow=true here (viewportWidth
// >= LEFT_PANEL_MAX_WIDTH*2), the row-flex branch, distinct from the stacked-mode width bug fixed
// at 90x40/60x30; this row's original defect (operator-pass W2) was the height-based content/border
// collision only. Isolated to its own file/bun-invocation -- see frame-geometry.test.ts's docstring.
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

describe("frame geometry — R4b acceptance row 2 (120x44)", () => {
  test("identical verdict at 120x44 -- zero violations, homescreen panel not clipped", () => {
    const lines = mountReplAt(120, 44);
    const result = checkFrameGeometry(lines);
    expect(result.violations).toEqual([]);
    const homescreenPanel = result.boxes.find(
      (b) => b.styleName === "round" && b.leftCol === 0 && b.topRow === 0,
    );
    expect(homescreenPanel).toBeDefined();
    expect(homescreenPanel!.clipped).toBe(false);
  });
});
