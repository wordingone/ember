// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { ReplScreen } from "./repl.ts";
import { operatorSurfaceWidth } from "./repl.ts";

async function flushRepl(): Promise<void> {
  for (let index = 0; index < 5; index++) {
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
}

function renderedLines(raw: string, columns: number, rows: number): string[] {
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
}

function assertPaletteDoesNotContaminatePrompt(lines: string[], width: number): void {
  // Both the palette selection and the actual input use ❯. Select the bottom-most closed
  // region first (the prompt/status panel), then find its glyph inside that region.
  const promptBottom = lines
    .map((line, index) => ({ line, index }))
    .filter(({ line }) => line.startsWith("╰") && line.includes("╯"))
    .at(-1)?.index ?? -1;
  const promptTop = lines
    .slice(0, promptBottom)
    .map((line, index) => ({ line, index }))
    .filter(({ line }) => line.startsWith("╭") && line.includes("╮"))
    .at(-1)?.index ?? -1;
  const promptRowOffset = lines
    .slice(promptTop + 1, promptBottom)
    .findIndex((line) => line.includes("❯"));
  const promptRow = promptRowOffset < 0 ? -1 : promptTop + 1 + promptRowOffset;

  expect(promptTop).toBeGreaterThanOrEqual(0);
  expect(promptRow).toBeGreaterThan(promptTop);
  expect(promptBottom).toBeGreaterThan(promptRow);
  expect(lines[promptTop]?.indexOf("╮")).toBe(width - 1);
  expect(lines[promptBottom]?.indexOf("╯")).toBe(width - 1);

  const commandRow = /\/(?:observatory|watch|finetune|model|train|goal|cockpit|custody|benchmark|spine)\b/;
  const commandNames = [
    "observatory", "watch", "finetune", "model", "train",
    "goal", "cockpit", "custody", "benchmark", "spine",
  ];
  for (let row = promptTop; row <= promptBottom; row++) {
    expect(lines[row] ?? "").not.toMatch(commandRow);
  }
  const renderedCommands = commandNames.filter((name) =>
    lines.some((line) => new RegExp(`/${name}\\b`).test(line)),
  ).length;
  const shortfall = lines.reduce((count, line) => {
    const match = line.match(/\+(\d+) more\b/);
    return count + (match ? Number(match[1]) : 0);
  }, 0);
  expect(renderedCommands + shortfall).toBe(commandNames.length);
}

describe("repl operator surface layout", () => {
  test("keeps the pane and prompt bounded through live resize, including with the command palette open", async () => {
    resetCommandRegistryForTests();
    let handle: ReturnType<typeof mountInk> | undefined;
    let raw = "";
    const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
    const render = (columns: number, rows: number) =>
      React.createElement(
        TerminalSizeContext.Provider,
        { value: { columns, rows } },
        React.createElement(ReplScreen, {
          config,
          cwd: process.cwd(),
          env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
          onExit: () => {},
        }),
      );

    for (const [columns, rows] of [[60, 20], [80, 24], [40, 24], [80, 24]] as const) {
      const element = render(columns, rows);
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
      const lines = renderedLines(raw, columns, rows);
      expect(lines.length).toBe(rows);
      // Legibility bar (2026-07-26): "RESOURCE EFFICIENC" (a silent hard-cut, no marker) was the
      // exact pre-fix defect shape at this narrow width -- a heading truncated mid-word with
      // nothing to tell an operator it wasn't a genuinely different, shorter label. The pane now
      // bounds every line against its real inner width (boundedSurfaceLine) and always appends a
      // visible "…" marker when it must shorten a line, so at 40 columns the heading now reads
      // "RESOURCE EFFICI…" instead. (D2 scope addition, 2026-07-26: the pane's own inner-width
      // budget under-counted its border by 2 columns on top of padding -- fixed in
      // operator-surface-pane.ts's innerWidth, effectiveWidth-4 not effectiveWidth-2 -- so the
      // marker now lands 2 columns earlier than before, matching the pane's true content budget.)
      for (const heading of columns <= 40
        ? ["TRAINING/LOSS", "RESOURCE EFFICI…"]
        : ["TRAINING/LOSS", "RESOURCE EFFICIENCY"]) {
        expect(lines.some((line) => line.includes(heading))).toBe(true);
      }
      if (columns <= 40) {
        // The old silent-clip fragment must never reappear un-marked.
        expect(lines.some((line) => line.includes("RESOURCE EFFICIENC") && !line.includes("RESOURCE EFFICI…"))).toBe(false);
        // Nor may content ever reach the pane's own right border column (D2 structural fix).
        const paneRows = lines.filter((line) => line.includes("│"));
        for (const line of paneRows) {
          const rightBorder = line.lastIndexOf("│");
          if (rightBorder > 0) expect(line[rightBorder]).toBe("│");
        }
      }
      expect(lines.some((line) => line.includes("IDLE"))).toBe(true);

      const promptRow = lines.find((line) => line.includes("❯"));
      expect(promptRow).toBeDefined();
      expect(promptRow?.[0]).toBe("│");
      const promptRightBorder = promptRow?.indexOf("│", 1) ?? -1;
      expect(promptRightBorder).toBeGreaterThan(0);

      const statusRows = lines.filter((line) => line.includes("○ observe"));
      expect(statusRows).toHaveLength(1);
      expect(statusRows[0]?.[0]).toBe("│");
      expect(statusRows[0]?.indexOf("│", 1)).toBe(promptRightBorder);
    }

    expect(handle).toBeDefined();
    const activeHandle = handle!;
    await flushRepl();
    // Keep the last complete 80x24 paint and apply the palette's incremental ANSI delta to it.
    // Parsing only the delta into a blank frame aliases the palette's own ❯ row as the prompt.
    _deliverKeyEvent("/", {});
    await flushRepl();
    for (const width of [80, 40, 80]) {
      if (activeHandle.container.stdout.columns !== width) {
        raw = "";
      }
      activeHandle.container.stdout.columns = width;
      activeHandle.container.stdout.rows = 24;
      activeHandle.container.rootNode.layout.width = width;
      activeHandle.container.rootNode.layout.height = 24;
      activeHandle.update(render(width, 24));
      await flushRepl();
      assertPaletteDoesNotContaminatePrompt(
        renderedLines(raw, width, 24),
        width - operatorSurfaceWidth(width),
      );
      raw = "";
    }
    activeHandle.unmount();
  });

  test("keeps a bounded right pane while preserving a usable conversation column", () => {
    expect(operatorSurfaceWidth(80)).toBe(33);
    expect(operatorSurfaceWidth(120)).toBe(50);
    expect(operatorSurfaceWidth(240)).toBe(100);
  });
});
