// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/slash-dropdown.ts — pure logic for the slash-command completion dropdown
// (issue b22 item 1, ledgered since b14 as ember-cli-slash-dropdown). Exemplar: the field's own
// "/" menu convention (Claude Code, Crush) per field-ux-map §8b/§9 — a filterable list of
// available commands appears the moment "/" is typed, narrows as more characters are typed, and
// completes into the input on selection. Pure and dependency-free (mirrors slash-dispatch.ts's
// own style): the REPL wiring calls these from its existing useInput/render loop, never
// re-derives the logic inline.

import type { RegistryCommand } from "../types/command-types.ts";

/** Cap on visible rows before an "+N more" overflow indicator — same pattern as
 * QUEUE_MAX_VISIBLE (prompt-input.ts) applied to the command list instead of the message queue. */
export const SLASH_DROPDOWN_MAX_VISIBLE = 8;

/**
 * True while the input still looks like "composing a slash-command name": exactly one leading
 * "/" followed by zero or more non-whitespace characters, nothing else. A space, a newline, or a
 * non-slash first character means the user has moved past command selection (into args, or
 * ordinary chat text) and the dropdown must not show.
 */
export function shouldShowSlashDropdown(text: string): boolean {
  return /^\/[^\s]*$/.test(text);
}

/** Strips the leading "/" — call only when shouldShowSlashDropdown(text) is true. */
export function slashQueryFrom(text: string): string {
  return text.slice(1);
}

/**
 * Case-insensitive prefix match against each command's name or any alias. An empty query (bare
 * "/") returns every command, in registry order — the full menu, matching the field convention of
 * showing all options before the user narrows.
 */
export function filterSlashCommands(commands: RegistryCommand[], query: string): RegistryCommand[] {
  if (query === "") return commands;
  const q = query.toLowerCase();
  return commands.filter(
    (c) =>
      c.name.toLowerCase().startsWith(q) ||
      (c.aliases ?? []).some((a) => a.toLowerCase().startsWith(q)),
  );
}

/** Moves the selection by `delta`, wrapping past either end (down past the last item returns to
 * the first; up past the first goes to the last) — the field's standard dropdown-nav convention.
 * Safe against an empty list (never divides by zero). */
export function moveDropdownSelection(index: number, length: number, delta: number): number {
  if (length <= 0) return 0;
  return ((index + delta) % length + length) % length;
}

/** Clamps a (possibly stale, e.g. after the match list shrank) index into [0, length-1], or 0 for
 * an empty list. */
export function clampDropdownSelection(index: number, length: number): number {
  if (length <= 0) return 0;
  return Math.max(0, Math.min(index, length - 1));
}

/** The text to set as the full input value once a command is selected — a trailing space so the
 * user can immediately start typing args (and so shouldShowSlashDropdown naturally goes false,
 * closing the dropdown without any extra state to manage). */
export function completeSlashSelection(cmd: RegistryCommand): string {
  return `/${cmd.name} `;
}

/**
 * b23: truncates `text` to fit within `maxWidth` columns, appending a single "…" whenever
 * truncation actually happened (never on an exact fit) -- the fix for the b22 gate's banked
 * wince, where a description longer than the available row width was hard-clipped by the
 * terminal buffer with no signal that anything was cut off. Degenerates safely: a non-positive
 * budget returns "", and a 1-column budget returns just the ellipsis.
 */
export function truncateWithEllipsis(text: string, maxWidth: number): string {
  if (maxWidth <= 0) return "";
  if (text.length <= maxWidth) return text;
  if (maxWidth === 1) return "…";
  return text.slice(0, maxWidth - 1) + "…";
}

/**
 * b23: how many columns are left for a command's description text once the panel's fixed
 * overhead is subtracted -- the round border (1 col each side), paddingX:1 (1 col each side), the
 * marker ("❯ " or "  ", 2 cols either way), the leading "/", the command's own name, and the
 * "  " gap before the description column. Recomputed from `panelWidth` on every call (never
 * cached), so it tracks the b14 resize/reflow path automatically: the caller just re-derives it
 * from the current terminal width on every render, the same way PromptInput already does with its
 * own `width` prop.
 */
export function slashDropdownDescriptionWidth(panelWidth: number, commandName: string): number {
  const RESERVED = 2 /* border, both sides */ + 2 /* paddingX, both sides */ + 2 /* marker */ + 1 /* "/" */ + 2 /* gap */;
  return Math.max(0, panelWidth - RESERVED - commandName.length);
}

export interface SlashDropdownDisplay {
  visible: RegistryCommand[];
  overflowCount: number;
  selectedIndex: number;
}

/** Assembles what the dropdown actually renders: a scrolled WINDOW of `matches` that always
 * contains the (clamped) selection, how many matches fall outside that window, and a selection
 * index re-based to the window (0 = the window's own first row) for the renderer to highlight —
 * mirrors computeQueueDisplay's visible+overflowCount shape (prompt-input.ts) for consistency with
 * the codebase's existing "capped list + overflow count" convention.
 *
 * `selectedIndex` is an index into the FULL `matches` list, not the visible window -- this is what
 * makes hidden entries reachable by keyboard at all (2026-07-25 palette-overflow-render finding:
 * moveDropdownSelection used to wrap only over the previously-fixed first-N slice, so anything
 * past the cap was unreachable regardless of how many times Down was pressed). The window is
 * re-centered on the selection each call (a pure function of selectedIndex, not persisted scroll
 * state), so wrap-around (moveDropdownSelection wrapping index length-1 -> 0) immediately scrolls
 * the window back to the top on the very next render.
 *
 * `maxVisible` defaults to SLASH_DROPDOWN_MAX_VISIBLE (every existing call site keeps working
 * unchanged) but a caller with real terminal-geometry knowledge should pass
 * slashDropdownMaxVisible(terminalRows, matches.length) instead -- see that function's
 * own comment (2026-07-25 palette-overflow-render finding) for why a fixed 8 alone is not honest
 * on a short terminal. `visible.length + overflowCount === matches.length` always, by
 * construction, regardless of what `cap` resolves to -- the shared invariant with the
 * prompt-region's own regression (visible count + shortfall count == full match count at every
 * terminal size).
 *
 * `maxVisible` (and therefore `cap`) may be 0 -- deliberately no forced floor of 1 (2026-07-25
 * counterparty finding): on a viewport too tight to show even a single entry honestly, the correct
 * disposition is zero rendered entries plus an honest full-count "+N more", not one entry painted
 * over a row that was never budgeted for it. slashDropdownCanRender separately distinguishes
 * an honest indicator-only panel from a viewport too short even for that indicator; the REPL
 * uses that structural gate rather than the visible-command count.
 * When cap resolves to 0, slashDropdownCanRender distinguishes an honest indicator-only
 * panel from a viewport too short even for that indicator. */
export function computeSlashDropdownDisplay(
  matches: RegistryCommand[],
  selectedIndex: number,
  maxVisible: number = SLASH_DROPDOWN_MAX_VISIBLE,
): SlashDropdownDisplay {
  const cap = Math.max(0, Math.min(SLASH_DROPDOWN_MAX_VISIBLE, maxVisible));
  const total = matches.length;
  if (cap === 0) {
    return { visible: [], overflowCount: total, selectedIndex: 0 };
  }
  const absoluteSelected = clampDropdownSelection(selectedIndex, total);
  const maxWindowStart = Math.max(0, total - cap);
  const windowStart = Math.min(Math.max(0, absoluteSelected - Math.floor(cap / 2)), maxWindowStart);
  const visible = matches.slice(windowStart, windowStart + cap);
  const overflowCount = Math.max(0, total - visible.length);
  return {
    visible,
    overflowCount,
    selectedIndex: absoluteSelected - windowStart,
  };
}

/** The slash palette collapses prompt/status chrome to one bordered input row, one embedded
 * compact status row, and the input box's two borders. This four-row total is a render contract,
 * not a sampled estimate of live transient state. */
export const DROPDOWN_COMPACT_CHROME_ROWS = 4;
export const DROPDOWN_BORDER_ROWS = 2;

/** True when the fixed compact region leaves room for the palette border and at least one
 * content row. That content row may be the honest overflow indicator with zero commands. */
export function slashDropdownCanRender(terminalRows: number, matchCount: number): boolean {
  return matchCount > 0
    && terminalRows - DROPDOWN_COMPACT_CHROME_ROWS - DROPDOWN_BORDER_ROWS >= 1;
}

export function slashDropdownMaxVisible(terminalRows: number, matchCount: number): number {
  const contentRows = terminalRows - DROPDOWN_COMPACT_CHROME_ROWS - DROPDOWN_BORDER_ROWS;
  const capWithoutIndicator = Math.max(
    0,
    Math.min(SLASH_DROPDOWN_MAX_VISIBLE, matchCount, contentRows),
  );
  if (capWithoutIndicator >= matchCount) return capWithoutIndicator;
  return Math.max(
    0,
    Math.min(SLASH_DROPDOWN_MAX_VISIBLE, matchCount, contentRows - 1),
  );
}
