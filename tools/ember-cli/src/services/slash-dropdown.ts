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
 * slashDropdownMaxVisible(terminalRows, bannerRows, matches.length) instead -- see that function's
 * own comment (2026-07-25 palette-overflow-render finding) for why a fixed 8 alone is not honest
 * on a short terminal. `visible.length + overflowCount === matches.length` always, by
 * construction, regardless of what `cap` resolves to -- the shared invariant with the
 * prompt-region's own regression (visible count + shortfall count == full match count at every
 * terminal size).
 *
 * `maxVisible` (and therefore `cap`) may be 0 -- deliberately no forced floor of 1 (2026-07-25
 * counterparty finding): on a viewport too tight to show even a single entry honestly, the correct
 * disposition is zero rendered entries plus an honest full-count "+N more", not one entry painted
 * over a row that was never budgeted for it. repl.ts's own render gate
 * (`dropdownDisplay.visible.length > 0`) already suppresses the whole SlashDropdown box when cap
 * resolves to 0 with nothing to show -- see slashDropdownMaxVisible's own comment for how that
 * residual case is handled. */
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

/** Reserved rows for the prompt+status chrome below the dropdown -- deliberately a generous,
 * documented CONSTANT rather than an analytically derived figure. Unlike the banner (whose exact
 * height is now computed for real via homescreenRowCount), PromptInput/StatusLine are another
 * founder's actively-rebuilt surface (issue #243) -- reading their code to derive an exact row
 * count would create a dependency on internals mid-rework, and any change there could silently
 * invalidate a "precise" number. Erring generous here can only make the dropdown show FEWER
 * entries than the terminal could technically fit (always safe: visible+overflowCount still sums
 * to the exact total by construction, so the shared count-plus-shortfall invariant never breaks);
 * erring tight risks pushing that region off-screen, which is the one interaction with their lane
 * this fix must never cause. 6 rows covers today's 1-2 rows each with headroom for a bordered
 * input box (#243's own direction) without needing to track its exact shape. */
export const DROPDOWN_PROMPT_STATUS_RESERVE_ROWS = 6;
export const DROPDOWN_BORDER_ROWS = 2;

/** 2026-07-25 palette-overflow-render finding (state/operability-finding-palette-renders-broken):
 * components/slash-dropdown.ts's Box now carries flexShrink:0 + overflow:"hidden", which
 * guarantees the panel is NEVER corrupted -- it renders exactly as many rows as it's TOLD to
 * (border + one row per visible command, cleanly clipped at the terminal's own edge if that's
 * still too many). What flexShrink:0 does NOT do is make the *decision* of how many commands to
 * show honest on a short terminal: SLASH_DROPDOWN_MAX_VISIBLE(8) alone doesn't know whether 8
 * rows plus the banner plus prompt/status chrome actually fit in `terminalRows`, so on a short
 * terminal the app would ask for more rows than exist and the excess would be silently clipped by
 * the terminal's own physical edge with no "+N more" -- the same "silently hiding entries" defect
 * the acceptance bar names, just moved one layer up from rendering into the visible-count
 * decision.
 *
 * `bannerRows` must come from components/logo-homescreen.ts's `homescreenRowCount(props)`, called
 * with the SAME props object passed to the real <Homescreen> element -- banner height is NOT a
 * fixed constant (recentFeedEntries appends one line per live boardSummary.topAttention entry
 * with no cap), so a guessed number here would again silently over- or under-ask depending on
 * live board state. Everything else this reserves is DROPDOWN_PROMPT_STATUS_RESERVE_ROWS (a
 * deliberately generous constant -- see its own comment for why that region isn't measured) plus
 * the dropdown's own 2 border rows. Erring toward reserving slightly more than strictly necessary
 * (showing "+N more" a little early on an edge case) is the safe direction; erring the other way
 * is the corruption/silent-drop defect this whole fix is for.
 *
 * `matchCount` (2026-07-25 counterparty finding, second round): the "+N more" overflow row itself
 * costs a row of height whenever it renders, and the budget above did not account for it -- the
 * over-ask came back exactly in the constrained case that matters. Whether the indicator row is
 * needed depends on whether the chosen cap causes overflow, which depends on the very budget being
 * computed -- resolving that circularity by iterating would oscillate, so this resolves it with
 * ONE deterministic recomputation instead: first size the cap against the budget as though no
 * indicator were needed; if that cap turns out to cover every match (no overflow), it's already
 * correct and no indicator row will render. If it doesn't (`capNoIndicator < matchCount`), the
 * indicator WILL render, so the true budget has one fewer row to spend on entries -- recompute
 * exactly once against that reduced budget and return it. Never re-checks its own output a second
 * time (that's the oscillation this deliberately avoids). May resolve to 0 -- see
 * computeSlashDropdownDisplay's own comment for why a floor of 1 was wrong. */
export function slashDropdownMaxVisible(terminalRows: number, bannerRows: number, matchCount: number): number {
  const baseAvailable = terminalRows - bannerRows - DROPDOWN_PROMPT_STATUS_RESERVE_ROWS - DROPDOWN_BORDER_ROWS;
  const capNoIndicator = Math.max(0, Math.min(SLASH_DROPDOWN_MAX_VISIBLE, baseAvailable));
  if (capNoIndicator >= matchCount) return capNoIndicator;
  const availableWithIndicator = baseAvailable - 1; // the "+N more" row itself
  return Math.max(0, Math.min(SLASH_DROPDOWN_MAX_VISIBLE, availableWithIndicator));
}
