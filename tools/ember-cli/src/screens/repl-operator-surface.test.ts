// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { getActivityFeedState } from "../services/activity-feed.ts";
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
  test("keeps the banner, 500-event pane, and prompt bounded through live resize", async () => {
    resetCommandRegistryForTests();
    let handle: ReturnType<typeof mountInk> | undefined;
    let raw = "";
    const seedActivityBurst = () => getActivityFeedState().recentLines.push(
      ...Array.from({ length: 500 }, (_, index) => ({
        ts: `2026-07-09T12:${String(Math.floor(index / 60)).padStart(2, "0")}:${String(index % 60).padStart(2, "0")}.000Z`,
        source: "goal" as const,
        text: `evt${index}`,
        sequence: index + 1,
      })),
    );
    const realCommit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: process.cwd(), encoding: "utf8" }).trim();
    const realBinaryHash = createHash("sha256").update(fs.readFileSync(process.execPath)).digest("hex");
    const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
    const render = (columns: number, rows: number) =>
      React.createElement(
        TerminalSizeContext.Provider,
        { value: { columns, rows } },
        React.createElement(ReplScreen, {
          config,
          cwd: process.cwd(),
          env: {
            EMBER_DISABLE_TERMINAL_TITLE: "1",
            EMBER_DISABLE_VIRTUAL_SCROLL: "1",
            EMBER_PUBLIC_SOURCE_COMMIT: realCommit,
            EMBER_CLI_BINARY_SHA256: realBinaryHash,
          },
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
      await flushRepl();
      if (getActivityFeedState().recentLines.length === 0) {
        seedActivityBurst();
        expect(getActivityFeedState().recentLines).toHaveLength(500);
        handle.update(render(columns, rows));
        await flushRepl();
      }
      const lines = renderedLines(raw, columns, rows);
      expect(lines.length).toBe(rows);
      // #894: the old unbounded TRAINING/LOSS + RESOURCE EFFICIENCY stream has been replaced by
      // independently bounded chart cards. At every supported size at least one card title and
      // one complete horizontal card boundary must survive the actual Repl resize path.
      expect(lines.some((line) => /\+\s*(HOST|LOSS|TOKENS|LEARNING|ENERGY|GPU)/u.test(line))).toBe(true);
      expect(lines.some((line) => /\+-{3,}\+/u.test(line))).toBe(true);
      expect(lines.some((line) => line.includes("TRAINING/LOSS"))).toBe(false);
      if (columns <= 40) {
        // Content may never overwrite the pane's own right border column.
        const paneRows = lines.filter((line) => line.includes("│"));
        for (const line of paneRows) {
          const rightBorder = line.lastIndexOf("│");
          if (rightBorder > 0) expect(line[rightBorder]).toBe("│");
        }
      }
      expect(lines.some((line) => line.includes("IDLE"))).toBe(true);
      expect(lines.some((line) => line.includes("ACTIVITY/EVENT"))).toBe(true);
      if (columns >= 60) {
        expect(lines.some((line) => line.includes("SOURCE UNVERIFIED/UNBOUND"))).toBe(false);
      }
      if (columns >= 60) {
        // At usable widths, prove the newest row from the 500-event burst reaches
        // the mounted Repl. The 40-column fallback intentionally hides row text.
        expect(lines.some((line) => line.includes("evt499"))).toBe(true);
      }

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
    getActivityFeedState().recentLines.length = 0;
  });

  test("keeps a bounded right pane while preserving a usable conversation column", () => {
    expect(operatorSurfaceWidth(80)).toBe(33);
    expect(operatorSurfaceWidth(120)).toBe(50);
    expect(operatorSurfaceWidth(240)).toBe(100);
  });
});
