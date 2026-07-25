// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { ReplScreen } from "./repl.ts";
import { operatorSurfaceWidth } from "./repl.ts";

describe("repl operator surface layout", () => {
  test("real REPL workspace keeps the bounded pane visible at 60x20 and 80x24", () => {
    let handle: ReturnType<typeof mountInk> | undefined;
    let raw = "";
    for (const [columns, rows] of [[60, 20], [80, 24]] as const) {
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
      if (!handle) {
        handle = mountInk(element, { stream: { write(s: string) { raw += s; } }, stdout: { columns, rows } });
      } else {
        handle.container.stdout.columns = columns;
        handle.container.stdout.rows = rows;
        handle.container.rootNode.layout.width = columns;
        handle.container.rootNode.layout.height = rows;
        raw = "";
        handle.update(element);
      }
      const frame = buildFrame(columns, rows);
      parseRenderedIntoFrame(raw, frame, new StylePool());
      const lines = frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
      expect(lines.length).toBe(rows);
      // At these bounded heights the activity feed intentionally occupies the lower pane;
      // assert the graph families that are actually paintable without changing that layout.
      for (const heading of ["TRAINING/LOSS", "RESOURCE EFFICIENCY"]) {
        expect(lines.some((line) => line.includes(heading))).toBe(true);
      }
      expect(lines.some((line) => line.includes("IDLE"))).toBe(true);

      const promptRow = lines.find((line) => line.includes("❯"));
      expect(promptRow).toBeDefined();
      expect(promptRow?.[0]).toBe("│");
      const promptRightBorder = promptRow?.indexOf("│", 1) ?? -1;
      expect(promptRightBorder).toBeGreaterThan(0);

      const statusRows = lines.filter((line) => line.includes("bypass permis"));
      expect(statusRows).toHaveLength(1);
      expect(statusRows[0]?.[0]).toBe("│");
      expect(statusRows[0]?.indexOf("│", 1)).toBe(promptRightBorder);
    }
    handle?.unmount();
  });

  test("keeps a bounded right pane while preserving a usable conversation column", () => {
    expect(operatorSurfaceWidth(80)).toBe(33);
    expect(operatorSurfaceWidth(120)).toBe(50);
    expect(operatorSurfaceWidth(240)).toBe(100);
  });
});