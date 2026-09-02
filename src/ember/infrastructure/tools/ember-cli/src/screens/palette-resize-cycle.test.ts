// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// screens/palette-resize-cycle.test.ts — the countersigned cross-lane contract
// (state/operability-finding-palette-renders-broken-2026-07-25.md; contract from the founder
// reworking the input region, issue #243): the same running cockpit, resized 80x24 -> 40x24 ->
// 80x24, must hold at EVERY stage:
//   (a) zero palette rows fused onto the prompt input's own row.
//   (b) rendered command count + the explicit shortfall count == the full match count.
//
// Uses the real resize mechanism (App's process.stdout.columns/rows + 'resize' event -- the same
// pattern ink/app-resize.test.ts already proves works end to end), not a fresh
// TerminalSizeContext.Provider mount per height, so this is the same "one running instance gets
// resized" shape the countersigning regression exercises. Follows the single-module-level-mount
// pattern (screens/repl-slash-dropdown.test.ts, screens/palette-overflow-render.test.ts) --
// mounting the real ReplScreen twice in one Bun process crashes the test runner outright.
//
// The exact registered command count is NOT hardcoded (it can include filesystem-discovered
// skill/plugin commands beyond the synchronous builtins) -- this test reads the SAME
// getCommands(cwd) the real app calls, as ground truth, rather than assuming a fixed total.

import { describe, it, expect } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { App } from "../ink/components.ts";
import { ReplScreen, operatorSurfaceWidth } from "../../../../../../../tools/ember-cli/src/screens/repl.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { resetCommandRegistryForTests, getCommands } from "../../../../../../../tools/ember-cli/src/command-registry.ts";

resetCommandRegistryForTests();

const origColumns = process.stdout.columns;
const origRows    = process.stdout.rows;

function reconstructRows(out: string): Map<number, string> {
  const grid = new Map<number, Map<number, string>>();
  const TOKEN_RE = /\x1b\[(\d+);(\d+)H|\x1b\[[0-9;]*[A-Za-z]|[^\x1b]+/g;
  let row = 1;
  let col = 1;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(out))) {
    if (m[1] !== undefined && m[2] !== undefined) {
      row = parseInt(m[1], 10);
      col = parseInt(m[2], 10);
    } else if (m[0].startsWith("\x1b")) {
      // non-positioning escape, skip
    } else {
      for (const ch of m[0]) {
        if (ch === "\n") { row++; col = 1; continue; }
        if (!grid.has(row)) grid.set(row, new Map());
        grid.get(row)!.set(col, ch);
        col++;
      }
    }
  }
  const rows = new Map<number, string>();
  for (const [r, cols] of grid) {
    const maxCol = Math.max(...cols.keys());
    let s = "";
    for (let c = 1; c <= maxCol; c++) s += cols.get(c) ?? " ";
    rows.set(r, s);
  }
  return rows;
}

async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) {
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
}

/** Asserts the shared cross-lane contract against whatever is CURRENTLY on screen. `allNames` is
 * the ground-truth full registered command list (from the real getCommands(cwd), not assumed).
 *
 * 2026-07-25 counterparty finding (stale-shortfall bug): the indicator count and the rendered
 * names must both come from the SAME reconstructed CURRENT frame (`rows`, built fresh from the
 * full cumulative output on every call) -- never from a raw regex against the cumulative output
 * string directly, which returns the FIRST historical "+N more" ever written, not the one in the
 * frame being checked right now. Also requires exactly one indicator row when there is a
 * shortfall, and none when there isn't -- more than one surviving in the current frame is its own
 * defect (a stale row that repaint failed to clear), not something to silently sum away. */
function assertContract(fullOutput: string, allNames: string[], stage: string, columns: number): void {
  const rows = reconstructRows(fullOutput);
  // The contract is about the PALETTE, which lives in the transcript column. Since #1399 the
  // live-run pane on the right of the SAME rows carries the command bar, whose pager renders its
  // own "+N more" — a whole-row scan sees two indicators and reads the second as a stale row the
  // repaint failed to clear. Every row is therefore trimmed to the transcript column first.
  const mainColumnWidth = Math.max(20, columns - operatorSurfaceWidth(columns));
  const paletteRows = new Map<number, string>(
    [...rows].map(([row, text]) => [row, text.slice(0, mainColumnWidth)] as const),
  );

  // (a) zero palette rows fused onto the prompt row: any row containing a registered command's
  // name must start with the dropdown's own left border ("│") -- the master reproduction of this
  // exact defect showed entry text landing on "❯ / /observatory ..." with NO leading "│" at all,
  // because it had been painted directly onto the prompt input's own row instead of the box's own.
  const renderedNames = new Set<string>();
  for (const [row, text] of paletteRows) {
    const namesOnThisRow = allNames.filter((name) => text.includes(`/${name}`));
    if (namesOnThisRow.length === 0) continue;
    expect(
      text.startsWith("│"),
      `[${stage}] row ${row} carries command text but not the box's own left border -- fused onto a different row: ${JSON.stringify(text)}`,
    ).toBe(true);
    for (const name of namesOnThisRow) renderedNames.add(name);
  }

  // (b) rendered count + explicit shortfall == full match count, read from the CURRENT frame only.
  const indicatorRows: { row: number; count: number }[] = [];
  for (const [row, text] of paletteRows) {
    const m = text.match(/\+(\d+) more/);
    if (m) indicatorRows.push({ row, count: parseInt(m[1]!, 10) });
  }
  const shortfallFromRendering = allNames.length - renderedNames.size;
  expect(
    indicatorRows.length,
    `[${stage}] expected exactly ${shortfallFromRendering > 0 ? "one" : "zero"} "+N more" row in the current frame, found ${indicatorRows.length}: ${JSON.stringify(indicatorRows)}`,
  ).toBe(shortfallFromRendering > 0 ? 1 : 0);
  const shortfall = indicatorRows.length > 0 ? indicatorRows[0]!.count : 0;
  expect(
    renderedNames.size + shortfall,
    `[${stage}] rendered ${renderedNames.size} + shortfall ${shortfall} != total ${allNames.length} (renderedNames=${[...renderedNames].join(",")})`,
  ).toBe(allNames.length);

  // (c) 2026-07-25 counterparty finding (third round): region survival, separate from count
  // conservation -- a zero-cap render (or any no-room disposition) must never come at the cost of
  // clipping the input the operator still needs to see. Checked with minimal-width glyphs rather
  // than the full status phrase: at the 40-col cramped stage, mainColumnWidth resolves to 20 cols
  // (operatorSurfaceWidth(40)=20 -- repl.ts:147-154), too narrow for the full "bypass permissions
  // on" (22 chars) to survive a horizontal clip, so asserting the full phrase would false-fail on
  // a status bar that DID render, just truncated -- the wrong kind of finding for this test.
  // BYPASS_GLYPH ("⏵⏵", status-bar.ts:29) and the prompt's own "❯" are both single/near-single
  // glyphs at the start of their row and survive any width this cycle exercises.
  const frameText = [...rows.values()].join("\n");
  expect(
    frameText.includes("❯"),
    `[${stage}] prompt region ("❯" marker) not found in the current frame -- input region clipped`,
  ).toBe(true);
  expect(
    frameText.includes("⏵⏵"),
    `[${stage}] status region (bypass-mode glyph) not found in the current frame -- status region clipped`,
  ).toBe(true);
}

describe("palette resize cycle 80x24 -> 40x24 -> 80x24 (countersigned cross-lane contract)", () => {
  it("holds (a) and (b) at every stage of the resize", async () => {
    const allCommands = await getCommands(process.cwd());
    const allNames = allCommands.map((c) => c.name);
    expect(allNames.length).toBeGreaterThan(0);

    // 2026-07-25 counterparty finding: restore stdout's real dimensions in a `finally` so a
    // failing assertion mid-cycle doesn't leave the terminal mutated for every test that runs
    // after this one -- one real failure turning into a cascade of unrelated ones.
    let handle: ReturnType<typeof mountInk> | null = null;
    try {
      Object.defineProperty(process.stdout, "columns", { value: 80, configurable: true });
      Object.defineProperty(process.stdout, "rows",    { value: 24, configurable: true });

      const chunks: string[] = [];
      const captureStream = {
        write(s: string | Uint8Array): void {
          chunks.push(typeof s === "string" ? s : new TextDecoder().decode(s));
        },
      };
      const config = { model: "qwen3.6-27b", permissionMode: "bypass" as const, baseSystemPrompt: "" };

      handle = mountInk(
        React.createElement(
          App,
          { onExit: () => {} },
          React.createElement(ReplScreen, {
            config,
            cwd:    process.cwd(),
            env:    { EMBER_DISABLE_TERMINAL_TITLE: "1" },
            onExit: () => {},
          }),
        ),
        { stream: captureStream as unknown as { write(s: string): void }, stdout: { columns: 80, rows: 24 } },
      );

      await flush();
      _deliverKeyEvent("/", {});
      await flush();
      assertContract(chunks.join(""), allNames, "80x24 (initial)", 80);

      // Resize down to a genuinely cramped height.
      Object.defineProperty(process.stdout, "columns", { value: 40, configurable: true });
      Object.defineProperty(process.stdout, "rows",    { value: 24, configurable: true });
      process.stdout.emit("resize");
      await flush();
      assertContract(chunks.join(""), allNames, "40x24 (cramped)", 40);

      // Resize back up.
      Object.defineProperty(process.stdout, "columns", { value: 80, configurable: true });
      Object.defineProperty(process.stdout, "rows",    { value: 24, configurable: true });
      process.stdout.emit("resize");
      await flush();
      assertContract(chunks.join(""), allNames, "80x24 (restored)", 80);
    } finally {
      handle?.unmount();
      Object.defineProperty(process.stdout, "columns", { value: origColumns, configurable: true });
      Object.defineProperty(process.stdout, "rows",    { value: origRows,    configurable: true });
    }
  });
});
