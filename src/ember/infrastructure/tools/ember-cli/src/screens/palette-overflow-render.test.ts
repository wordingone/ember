// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// screens/palette-overflow-render.test.ts — the palette overflow-corruption defect
// (state/operability-finding-palette-renders-broken-2026-07-25.md). A real ConPTY capture (50x140,
// 4 registered commands) showed the command palette rendering broken: the third entry painted
// THROUGH the box's own closing border, the fourth escaped the box entirely and fused with the
// input prompt row, and the status line showed two overlapping strings in the same cells. Root
// cause: components/slash-dropdown.ts's outer Box had no `flexShrink` (defaults to 1, per
// layout-engine.ts) and no `overflow:"hidden"`, so when total sibling content exceeded the
// terminal's row budget, the real CSS flex-shrink algorithm (layout-engine.ts's weighted-deficit
// pass, B6 W4') proportionally compressed the dropdown's own computed height right alongside the
// transcript -- and because the dropdown never declared overflow:"hidden", its children painted
// past its own (now too-short) computed bounds into whatever the next sibling (the real prompt
// row) was about to occupy, instead of clipping cleanly the way overflow-clip.test.ts's W4 fix
// already proved for a tall transcript child.
//
// This file asserts on RENDERED OUTPUT -- the same shape of assertion the real PTY capture made --
// by reconstructing, from the reconciler's own absolute cursor-position escapes (the same
// `\x1b[(\d+);(\d+)H` addressing overflow-clip.test.ts's `maxRowWritten` helper already reads),
// which text landed on which terminal row, then asserting no entry's text shares a row with a
// border glyph and no entry's row falls outside the box's own [top-border, bottom-border] span.
//
// A single module-level mount, driven sequentially (same pattern as
// screens/repl-slash-dropdown.test.ts) -- mounting the real ReplScreen twice in one process
// crashed the Bun test runner outright (module-level polling timers / heartbeat side effects
// collide across mounts), so this file follows that file's proven-stable one-mount-per-file shape
// rather than one mount per `it`.

import { afterAll, beforeAll, describe, it, expect } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { ReplScreen } from "../../../../../../../tools/ember-cli/src/screens/repl.ts";
import { _deliverKeyEvent } from "../ink/hooks.ts";
import { resetCommandRegistryForTests } from "../../../../../../../tools/ember-cli/src/command-registry.ts";

const COLS = 80;
// Deliberately BELOW the 28-row floor documented in repl-slash-dropdown.test.ts (banner 16 +
// dropdown 8 + input/status 4, zero squeeze) -- this is exactly the squeeze condition that file's
// ROWS=34 fixture was deliberately sized to AVOID, and the condition the real 50x140 PTY capture's
// build hit (its capture had additional watchdog-panel chrome this synthetic fixture doesn't
// reproduce, but the mechanism -- total sibling content exceeding the terminal's row budget -- is
// the same one).
const ROWS = 20;

const BORDER_GLYPH_RE = /[╭╮╰╯]/;

/** Reconstructs, from the reconciler's raw ANSI writes, an actual per-column terminal GRID (not a
 * write-order string concatenation -- an earlier version of this helper concatenated all text
 * written to a row in WRITE order regardless of column, which silently merges two side-by-side
 * panels' text into one misleading string whenever the diff-repaint algorithm interleaves their
 * writes; this repl's layout is a two-pane row split (main-column + the operator-surface pane), so
 * that happens on nearly every frame here). Tracks the live cursor (row, col) via the same
 * `\x1b[(\d+);(\d+)H` addressing overflow-clip.test.ts's `maxRowWritten` reads, places each
 * printable character at its true column (advancing the column per character, skipping other ANSI
 * codes that don't reposition the cursor, e.g. SGR/color), and returns one left-to-right string per
 * row -- an honest reconstruction of what a real terminal would show. */
function reconstructRows(out: string): Map<number, string> {
  const grid = new Map<number, Map<number, string>>();
  const TOKEN_RE = /\x1b\[(\d+);(\d+)H|\x1b\[[0-9;]*[A-Za-z]|[^\x1b]+/g;
  let row = 1;
  let col = 1;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(out))) {
    const token = m[0];
    if (token.startsWith("\x1b[") && /H$/.test(token) && m[1] !== undefined) {
      row = Number(m[1]);
      col = Number(m[2]);
      continue;
    }
    if (token.startsWith("\x1b[")) continue; // other ANSI code (color/etc) -- no position change
    // Plain text run -- place each character at its own column, advancing.
    let rowMap = grid.get(row);
    if (!rowMap) { rowMap = new Map(); grid.set(row, rowMap); }
    for (const ch of token) {
      rowMap.set(col, ch);
      col += 1;
    }
  }
  const rows = new Map<number, string>();
  for (const [r, rowMap] of grid) {
    const maxCol = Math.max(...rowMap.keys());
    let line = "";
    for (let c = 1; c <= maxCol; c++) line += rowMap.get(c) ?? " ";
    rows.set(r, line);
  }
  return rows;
}

async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) {
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
}

resetCommandRegistryForTests();

const chunks: string[] = [];
const captureStream = {
  write(s: string | Uint8Array): void {
    chunks.push(typeof s === "string" ? s : new TextDecoder().decode(s));
  },
};
const config = { model: "qwen3.6-27b", permissionMode: "bypass" as const, baseSystemPrompt: "" };

let handle: ReturnType<typeof mountInk> | null = null;
beforeAll(() => {
  resetCommandRegistryForTests();
  handle = mountInk(
  React.createElement(
    TerminalSizeContext.Provider,
    { value: { columns: COLS, rows: ROWS } },
    React.createElement(ReplScreen, {
      config,
      cwd: process.cwd(),
      env: { EMBER_DISABLE_TERMINAL_TITLE: "1" },
      onExit: () => {},
    }),
  ),
  { stream: captureStream as unknown as { write(s: string): void }, stdout: { columns: COLS, rows: ROWS } },
  );
});
afterAll(() => {
  handle?.unmount();
});


// Every registered builtin command this fixture cycles through (per
// repl-slash-dropdown.test.ts's own `resetCommandRegistryForTests` comment: observatory, watch,
// finetune, model, world-state).
const ENTRY_NAMES = ["/observatory", "/watch", "/finetune", "/model", "/world-state"];

describe(`command palette at ${ROWS} rows (below the 28-row floor) does not corrupt the screen (operability finding, 2026-07-25)`, () => {
  it("typing '/' opens the dropdown without a crash", async () => {
    await flush(); // let the initial getCommands(cwd) load land
    _deliverKeyEvent("/", {});
    await flush();
    const buf = chunks.join("");
    expect(buf).toContain("/observatory");
  });

  it("no entry text shares a row with a border glyph, and no entry renders outside the box's own bounds", () => {
    const fullOutput = chunks.join("");
    const rows = reconstructRows(fullOutput);

    const entryRows = [...rows.entries()]
      .filter(([, text]) => ENTRY_NAMES.some((name) => text.includes(name)))
      .map(([row]) => row)
      .sort((a, b) => a - b);
    expect(entryRows.length).toBeGreaterThan(0);

    const topEntryRow = entryRows[0]!;
    const bottomEntryRow = entryRows[entryRows.length - 1]!;

    // Scope the box's OWN border rows by adjacency to the entries, not a screen-wide min/max --
    // the banner (Homescreen) also uses round-corner box-drawing glyphs, so a global scan
    // conflates the banner's border with the dropdown's. The dropdown's top border, if present, is
    // the row immediately above the topmost entry row; its bottom border, if present, is the row
    // immediately below the bottommost entry row. Either can legitimately be ABSENT (clipped by
    // the terminal's own physical edge, e.g. the top border scrolled off, or the box is cut short
    // by row ROWS) -- flexShrink:0 + overflow:"hidden" guarantee clean clipping, not that a border
    // is always visible.
    const aboveText = rows.get(topEntryRow - 1);
    const belowText = rows.get(bottomEntryRow + 1);
    const topBorderRow = aboveText !== undefined && BORDER_GLYPH_RE.test(aboveText) ? topEntryRow - 1 : undefined;
    const bottomBorderRow = belowText !== undefined && BORDER_GLYPH_RE.test(belowText) ? bottomEntryRow + 1 : undefined;

    for (const [row, text] of rows) {
      const entriesOnThisRow = ENTRY_NAMES.filter((name) => text.includes(name));
      if (entriesOnThisRow.length === 0) continue;

      // Defect #1: an entry's text must never land on a row that ALSO carries a border glyph
      // (the observed "row 45 is simultaneously /finetune's row and the closing border").
      expect(
        BORDER_GLYPH_RE.test(text),
        `row ${row} carries both a border glyph and entry text ${entriesOnThisRow.join(",")}: ${JSON.stringify(text)}`,
      ).toBe(false);

      // Defect #1b: an entry's row must start with the box's OWN left border cell ("│", column 1
      // -- the dropdown Box sits flush against the terminal's left edge with no sibling to its
      // left), not with foreign content spliced onto the same physical row. This is the master
      // reproduction actually observed at ROWS=20: the box's border collapses away entirely (no
      // ╭╮╰╯ anywhere near it, so a border-glyph-only check misses it) and the entry text gets
      // painted directly onto the PROMPT INPUT's own row, which shows as `"❯ / /observatory  ..."`
      // -- the leading "❯ /" is the real prompt's echoed "/" keystroke, not the dropdown's own
      // SELECTED_MARKER, and the row has no "│" at all because the dropdown never got its own row.
      expect(
        text.startsWith("│"),
        `row ${row} (entry ${entriesOnThisRow.join(",")}) does not start with the box's own left border -- it is fused onto a different row's content: ${JSON.stringify(text)}`,
      ).toBe(true);

      // Defect #2: an entry's text must never land strictly outside the box's own bounds -- if a
      // border row was found on that side, the entry must be strictly inside it; if no border row
      // was found (clipped at the terminal edge), the entry itself must be the row AT that edge,
      // never beyond it (the observed "/train escapes the box entirely, fused with the input
      // prompt" was an entry rendering on a row belonging to a DIFFERENT sibling, not merely an
      // unbordered edge).
      if (topBorderRow !== undefined) {
        expect(row > topBorderRow, `row ${row} (entry ${entriesOnThisRow.join(",")}) is above the box's own top border (row ${topBorderRow})`).toBe(true);
      }
      if (bottomBorderRow !== undefined) {
        expect(row < bottomBorderRow, `row ${row} (entry ${entriesOnThisRow.join(",")}) is below the box's own bottom border (row ${bottomBorderRow})`).toBe(true);
      }
      expect(row <= ROWS, `row ${row} (entry ${entriesOnThisRow.join(",")}) is beyond the terminal's own last row (${ROWS})`).toBe(true);
    }
  });

  it("if not every match fits, the operator can tell (an honest '+N more', never a silent drop)", () => {
    const fullOutput = chunks.join("");
    const rows = reconstructRows(fullOutput);
    const renderedEntryCount = [...rows.values()].filter((text) =>
      ENTRY_NAMES.some((name) => text.includes(name)),
    ).length;
    if (renderedEntryCount < ENTRY_NAMES.length) {
      const hasOverflowIndicator = [...rows.values()].some((text) => /\+\d+ more/.test(text));
      expect(
        hasOverflowIndicator,
        `only ${renderedEntryCount}/${ENTRY_NAMES.length} entries rendered, with no "+N more" indicator anywhere in the output -- entries were silently dropped`,
      ).toBe(true);
    }
  });

  // 2026-07-25 counterparty finding (third round): a zero-cap render (or any other no-room
  // disposition) must never come at the cost of clipping the input the operator still needs to
  // see -- count conservation and region survival are two SEPARATE assertions, not one. Checked
  // with minimal-width glyphs, not the full status phrase: BYPASS_GLYPH ("⏵⏵",
  // components/status-bar.ts:29) and the prompt's own "❯" are single/near-single glyphs at the
  // start of their own row, so they survive regardless of how narrow mainColumnWidth resolves to
  // at this fixture's COLS -- unlike the full "bypass permissions on" phrase, which a tight
  // column width can legitimately clip (a truncated-but-present status bar is not this defect).
  it("the prompt and status regions are still present and intact, not clipped to make room for the palette", () => {
    const fullOutput = chunks.join("");
    const rows = reconstructRows(fullOutput);
    const frameText = [...rows.values()].join("\n");
    expect(
      frameText.includes("❯"),
      `prompt region ("❯" marker) not found in the current frame -- input region clipped`,
    ).toBe(true);
    expect(
      frameText.includes("⏵⏵"),
      `status region (bypass-mode glyph) not found in the current frame -- status region clipped`,
    ).toBe(true);
  });
});
