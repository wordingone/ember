// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/slash-dropdown-row-accounting.test.ts — range battery for the palette's row budget
// (2026-07-25 operability finding, state/operability-finding-palette-renders-broken). The cure
// (slashDropdownMaxVisible + computeSlashDropdownDisplay's honest overflow) landed with
// single-height receipts (20/24/34 rows); this battery binds the invariants across the RANGE of
// terminal heights and match counts, per review-order.md's byte-provenance rule: "binding a value
// to one observation is not binding it to the value."
//
// Invariants, at EVERY (terminalRows, matchCount) pair:
//   (1) conservation: visible.length + overflowCount === matchCount — nothing silently dropped.
//   (2) row budget: the palette block's total rows (entries + optional "+N more" indicator +
//       DROPDOWN_BORDER_ROWS) plus DROPDOWN_COMPACT_CHROME_ROWS never exceed terminalRows
//       whenever slashDropdownCanRender says the palette may render at all.
//   (3) cross-limit discrimination: the 8-cap and the height budget are TWO independent limits;
//       whichever binds must drive BOTH the slice and the shortfall. The constant-8 default
//       (pre-cure behavior) violates (2) at short heights — asserted here as the explicit RED
//       counterpart, so this file discriminates against the exact defect class rather than
//       restating the implementation.

import { describe, it, expect } from "bun:test";
import type { RegistryCommand } from "../types/command-types.ts";
import {
  computeSlashDropdownDisplay,
  slashDropdownMaxVisible,
  slashDropdownCanRender,
  DROPDOWN_COMPACT_CHROME_ROWS,
  DROPDOWN_BORDER_ROWS,
  SLASH_DROPDOWN_MAX_VISIBLE,
} from "../services/slash-dropdown.ts";

const cmd = (name: string): RegistryCommand =>
  ({ name, description: `desc of ${name}`, execute: async () => ({ message: "" }) }) as unknown as RegistryCommand;

const mkMatches = (n: number): RegistryCommand[] =>
  Array.from({ length: n }, (_, i) => cmd(`cmd${i}`));

/** Rows the rendered palette block occupies for a given display: one row per visible entry,
 * one indicator row iff overflowCount > 0, plus the box's own two border rows. */
function paletteBlockRows(visibleCount: number, overflowCount: number): number {
  return visibleCount + (overflowCount > 0 ? 1 : 0) + DROPDOWN_BORDER_ROWS;
}

// The tasking's named heights (20/30/50/70) plus the short tail where the height budget, not the
// 8-cap, is the binding limit (7..14) and a degenerate floor (1..6).
const HEIGHTS = [1, 4, 6, 7, 8, 9, 10, 12, 14, 20, 30, 50, 70];
// Zero, one, the real registry's ten, below/at/above the cap, and a large registry.
const TOTALS = [0, 1, 4, 8, 10, 30];

describe("palette row accounting across the height x match-count range", () => {
  for (const rows of HEIGHTS) {
    for (const total of TOTALS) {
      it(`rows=${rows} total=${total}: conservation + row budget hold at every selection index`, () => {
        const matches = mkMatches(total);
        const maxVisible = slashDropdownMaxVisible(rows, total);
        // Sweep every selection index (wrap-around reachability): the window re-centers on the
        // selection, so the budget must hold for ALL of them, not just index 0.
        for (let sel = 0; sel < Math.max(1, total); sel++) {
          const d = computeSlashDropdownDisplay(matches, sel, maxVisible);
          // (1) conservation — silent loss is the gate blocker.
          expect(d.visible.length + d.overflowCount).toBe(total);
          // Selected row is inside the visible window whenever anything is visible.
          if (d.visible.length > 0) {
            expect(d.selectedIndex).toBeGreaterThanOrEqual(0);
            expect(d.selectedIndex).toBeLessThan(d.visible.length);
          }
          // (2) row budget, gated exactly as the REPL gates the render.
          if (slashDropdownCanRender(rows, total)) {
            const block = paletteBlockRows(d.visible.length, d.overflowCount);
            expect(block + DROPDOWN_COMPACT_CHROME_ROWS).toBeLessThanOrEqual(rows);
          }
        }
      });
    }
  }

  it("every registered command is reachable via the selection sweep at every height (no silent loss)", () => {
    for (const rows of HEIGHTS) {
      if (!slashDropdownCanRender(rows, 10)) continue;
      const matches = mkMatches(10);
      const maxVisible = slashDropdownMaxVisible(rows, 10);
      const seen = new Set<string>();
      for (let sel = 0; sel < 10; sel++) {
        const d = computeSlashDropdownDisplay(matches, sel, maxVisible);
        for (const c of d.visible) seen.add(c.name);
        // The selected command itself is always on screen.
        if (d.visible.length > 0) expect(d.visible[d.selectedIndex]!.name).toBe(`cmd${sel}`);
      }
      // Either everything was shown across the sweep, or the shortfall was always declared.
      if (maxVisible > 0) expect(seen.size).toBe(10);
    }
  });

  it("RED counterpart: the constant-8 default violates the row budget exactly where the height binds", () => {
    // Pre-cure shape: computeSlashDropdownDisplay with the bare SLASH_DROPDOWN_MAX_VISIBLE cap,
    // ignoring terminal height. At rows=12 with 10 matches the height budget allows
    // 12 - 4 (chrome) - 2 (borders) - 1 (indicator) = 5 entries; the constant cap paints 8 + 1.
    const rows = 12;
    const matches = mkMatches(10);
    const constant = computeSlashDropdownDisplay(matches, 0, SLASH_DROPDOWN_MAX_VISIBLE);
    const constantBlock = paletteBlockRows(constant.visible.length, constant.overflowCount);
    expect(constantBlock + DROPDOWN_COMPACT_CHROME_ROWS).toBeGreaterThan(rows); // the defect
    const derived = computeSlashDropdownDisplay(matches, 0, slashDropdownMaxVisible(rows, 10));
    const derivedBlock = paletteBlockRows(derived.visible.length, derived.overflowCount);
    expect(derivedBlock + DROPDOWN_COMPACT_CHROME_ROWS).toBeLessThanOrEqual(rows); // the cure
    // And the shortfall is keyed to what actually FIT, not to the cap (defect 2's cross-limit trap).
    expect(derived.visible.length + derived.overflowCount).toBe(10);
    expect(derived.overflowCount).toBe(10 - derived.visible.length);
  });
});
