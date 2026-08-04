// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// services/command-buttons.ts — turns the LIVE command registry into the button model the
// command bar renders and clicks against.
//
// The whole point of this module is that there is no second list of commands anywhere. The
// buttons are DERIVED from the same `RegistryCommand[]` that `services/slash-dispatch.ts`
// dispatches against, in the same order the slash palette shows, so registering a command is
// the only thing anyone ever has to do to get its button — and a command that is removed loses
// its button in the same breath. A hand-maintained button list is the banned shape here: it is
// exactly how "the palette has /benchmark but the buttons don't" bugs are born.
//
// Everything below is pure. Rendering lives in components/command-bar-pane.ts; the effect of an
// activation (dispatch vs. compose) is executed by screens/repl.ts through the SAME
// submitPrompt/setText paths the keyboard uses — this module only decides WHICH of those two a
// click means, and never performs either itself.

import type { RegistryCommand } from "../types/command-types.ts";

// ---------------------------------------------------------------------------
// Button model
// ---------------------------------------------------------------------------

export interface CommandButton {
  /** Registry command name, without the leading slash. */
  readonly name: string;
  /** Rendered, clickable label — the button-shaped form used by the operator controls. */
  readonly label: string;
  /** `cmd.isEnabled()` at build time. A disabled button still renders (so the operator can see
   *  the command exists) but activates to a `rejected` result carrying a named reason. */
  readonly enabled: boolean;
  /** True when the command declares an `argumentHint`, i.e. it cannot do anything useful
   *  without arguments. Such a button composes instead of dispatching. */
  readonly needsArgument: boolean;
  readonly argumentHint?: string;
  readonly description?: string;
  /** Why this button is disabled, surfaced on activation. Never left implicit: a control that
   *  does nothing and says nothing is the defect the operator controls already fixed once. */
  readonly disabledReason?: string;
}

/**
 * What a click means. `dispatch` runs the command exactly as typing `/name` + Enter would;
 * `prefill` puts `/name ` in the composer and lets the operator finish the arguments (never a
 * blind execution of a command whose required arguments are missing); `rejected` is a disabled
 * button, carrying the reason to surface.
 */
export type CommandButtonActivation =
  | { readonly kind: "dispatch"; readonly text: string }
  | { readonly kind: "prefill"; readonly text: string; readonly hint?: string }
  | { readonly kind: "rejected"; readonly reason: string };

/**
 * Button-shaped label, matching the operator controls' `[START]`-style affordance.
 *
 * The slash is NOT part of the label (#1399): the operator reads a control surface, and a control
 * reading `[/verify]` advertises its own keyboard spelling instead of naming what it does. What a
 * click MEANS is built independently in `commandButtonActivation` from `button.name`, so the
 * dispatched text is `/verify` whatever this function renders — dropping the slash here cannot
 * silently change what any button runs.
 */
export function commandButtonLabel(name: string): string {
  return `[${name}]`;
}

const DEFAULT_DISABLED_REASON = "the command reports itself unavailable in this context";

/**
 * Builds the button model for `commands`, preserving registry order (the same order the slash
 * palette lists, so the click surface and the type surface never disagree about what exists or
 * where it sits) and de-duplicating by name, first occurrence winning — the same precedence
 * `getCommands` itself applies when a dynamic command collides with a builtin.
 *
 * A command whose `isEnabled()` THROWS is rendered disabled with the thrown reason rather than
 * taking the cockpit's render down with it: an availability probe that reaches a missing file or
 * an unset env var is a routine condition, not a crash.
 */
export function buildCommandButtons(commands: readonly RegistryCommand[]): CommandButton[] {
  const seen = new Set<string>();
  const buttons: CommandButton[] = [];
  for (const cmd of commands) {
    if (!cmd || typeof cmd.name !== "string" || cmd.name === "") continue;
    if (seen.has(cmd.name)) continue;
    seen.add(cmd.name);
    let enabled = true;
    let disabledReason: string | undefined;
    try {
      enabled = cmd.isEnabled();
      if (!enabled) disabledReason = DEFAULT_DISABLED_REASON;
    } catch (error) {
      enabled = false;
      disabledReason = error instanceof Error ? error.message : String(error);
    }
    const argumentHint = cmd.argumentHint;
    buttons.push({
      name: cmd.name,
      label: commandButtonLabel(cmd.name),
      enabled,
      needsArgument: typeof argumentHint === "string" && argumentHint.length > 0,
      ...(argumentHint ? { argumentHint } : {}),
      ...(cmd.description ? { description: cmd.description } : {}),
      ...(disabledReason ? { disabledReason } : {}),
    });
  }
  return buttons;
}

/**
 * The command a click means. Note what this deliberately does NOT return: any notion of focus.
 * Activating a button can only ever produce text to run or text to compose, so no click path can
 * move keyboard focus away from the composer — the "buttons are equivalents, not replacements"
 * requirement is structural here, not a convention the caller has to remember.
 */
export function commandButtonActivation(button: CommandButton): CommandButtonActivation {
  if (!button.enabled) {
    const reason = button.disabledReason ?? DEFAULT_DISABLED_REASON;
    return { kind: "rejected", reason: `/${button.name} is not available right now: ${reason}` };
  }
  if (button.needsArgument) {
    return {
      kind: "prefill",
      text: `/${button.name} `,
      ...(button.argumentHint ? { hint: `/${button.name} ${button.argumentHint}` } : {}),
    };
  }
  return { kind: "dispatch", text: `/${button.name}` };
}

// ---------------------------------------------------------------------------
// Grouping (#1399)
// ---------------------------------------------------------------------------

/**
 * The grouping logic, stated (issue #1399 acceptance 3): commands are grouped by WHAT THE
 * OPERATOR IS DOING TO THE WORK, which is the same axis the run controls already sit on.
 *
 *  - `launch`  — puts work in flight or qualifies it: /train, /finetune, /verify, /benchmark.
 *    These are the commands that sit conceptually next to [START]: they begin something.
 *  - `inspect` — read the state of the system without changing it: /watch, /model, /custody,
 *    /spine, /observatory, /cockpit.
 *  - `govern`  — change what the system is BOUND to (identity, seat, objective): /admit,
 *    /designate, /goal. These are the commands that alter authority rather than run anything.
 *  - `more`    — the catch-all, and the reason grouping does not reintroduce the second-list
 *    failure #1370 killed. Every command that matches no group above lands here and still gets a
 *    button, so a newly registered command (a skill, a plugin, an MCP command, /resume) is
 *    grouped without anyone editing this file. Membership below is a PRESENTATION hint layered
 *    over the registry, never a gate on which commands exist.
 *
 * Note the deliberate separation of `/resume` (session resume, lands in `more`) from the run
 * control `[RESUME]`: putting a lowercase `[resume]` inside the run-lifecycle group directly
 * under `[RESUME]` would read as two spellings of one control.
 */
export type CommandButtonGroupId = "launch" | "inspect" | "govern" | "more";

export interface CommandButtonGroupDef {
  readonly id: CommandButtonGroupId;
  /** Rendered caption at the head of the group's first row. */
  readonly caption: string;
  /** Names in this group. Empty means "everything not claimed above" (the catch-all). */
  readonly members: readonly string[];
}

export const COMMAND_BUTTON_GROUPS: readonly CommandButtonGroupDef[] = [
  { id: "launch", caption: "launch", members: ["train", "finetune", "verify", "benchmark"] },
  { id: "inspect", caption: "inspect", members: ["watch", "model", "custody", "spine", "observatory", "cockpit"] },
  { id: "govern", caption: "govern", members: ["admit", "designate", "goal"] },
  { id: "more", caption: "more", members: [] },
];

/** The group a command name belongs to. Total by construction: the last group is the catch-all. */
export function commandButtonGroupId(name: string): CommandButtonGroupId {
  for (const group of COMMAND_BUTTON_GROUPS) {
    if (group.members.includes(name)) return group.id;
  }
  return COMMAND_BUTTON_GROUPS[COMMAND_BUTTON_GROUPS.length - 1]!.id;
}

export interface CommandButtonGroup {
  readonly id: CommandButtonGroupId;
  readonly caption: string;
  readonly buttons: CommandButton[];
}

/**
 * Partitions `buttons` into the groups above, in group order, each group holding its members in
 * REGISTRY order. Empty groups are dropped — a caption with nothing under it is chrome that says
 * nothing. Every input button appears in exactly one output group; nothing is filtered.
 */
export function groupCommandButtons(buttons: readonly CommandButton[]): CommandButtonGroup[] {
  return COMMAND_BUTTON_GROUPS
    .map((group) => ({
      id: group.id,
      caption: group.caption,
      buttons: buttons.filter((button) => commandButtonGroupId(button.name) === group.id),
    }))
    .filter((group) => group.buttons.length > 0);
}

// ---------------------------------------------------------------------------
// Width-bounded layout
// ---------------------------------------------------------------------------

/**
 * One rendered cell of the bar: a group caption, a real button, or the pager.
 *
 * The pager is a CELL, not a caption: it carries the count it is hiding so the component can
 * render it, and the component gives it a click handler that advances the page. An overflow
 * marker with no handler was the #1370 review's blocking finding — at 80x24 it made half the
 * registry mouse-unreachable, which is the exact keyboard-only state the issue exists to end.
 *
 * A `group` cell is the only cell that is NOT clickable: it is the caption that opens its group's
 * first row, and it always starts a row (see `packCommandBarRows`) so the groups read as blocks
 * rather than as one undifferentiated stream of brackets.
 */
export type CommandBarCell =
  | { readonly kind: "group"; readonly label: string; readonly group: CommandButtonGroupId }
  | { readonly kind: "button"; readonly label: string; readonly button: CommandButton }
  | { readonly kind: "overflow"; readonly label: string; readonly hiddenCount: number };

/** Caption column width, so every group's buttons start at the same column. Spent only when the
 *  pane can afford it; below this the caption takes exactly its own text and the buttons follow. */
const GROUP_CAPTION_COLUMN = 8;
const GROUP_CAPTION_MIN_WIDTH = 32;

function groupCell(group: CommandButtonGroup, availableWidth: number): CommandBarCell {
  const caption = availableWidth >= GROUP_CAPTION_MIN_WIDTH
    ? group.caption.padEnd(GROUP_CAPTION_COLUMN, " ")
    : group.caption;
  return { kind: "group", label: caption, group: group.id };
}

export interface CommandBarLayout {
  readonly rows: CommandBarCell[][];
  /** Commands with no visible button on this page. Rendered as `+N more`, which PAGES to them. */
  readonly hiddenCount: number;
}

/** Rendered width of a cell including its own single-column trailing gap. */
function cellWidth(cell: CommandBarCell): number {
  return cell.label.length + 1;
}

/**
 * The pager's compact form, for panes too narrow to spend 8 columns on a caption. Two columns
 * (glyph + gap) is the floor at which a page can still hold one button AND remain escapable, so
 * there is no width at which the bar can strand the operator on a page.
 */
export const COMMAND_BAR_PAGER_GLYPH = "›";

function overflowCell(hiddenCount: number, compact: boolean): CommandBarCell {
  return {
    kind: "overflow",
    label: compact ? COMMAND_BAR_PAGER_GLYPH : `+${hiddenCount} more`,
    hiddenCount,
  };
}

/**
 * Greedily packs cells into as few rows as fit `availableWidth`, NEVER splitting a label: every
 * row gets at least one whole cell even when that cell alone is wider than the pane. This is the
 * same rule `layoutControlRows` applies to the run controls, for the same reason — the layout
 * engine declares `flexWrap` but never implements it, so a too-narrow row would otherwise be
 * raw-clipped by the enclosing `overflow:"hidden"` box with no marker at all.
 */
export function packCommandBarRows(
  cells: readonly CommandBarCell[],
  availableWidth: number,
): CommandBarCell[][] {
  if (cells.length === 0) return [];
  const rows: CommandBarCell[][] = [[]];
  let used = 0;
  for (const cell of cells) {
    const width = cellWidth(cell);
    const current = rows[rows.length - 1]!;
    // A group caption ALWAYS opens a row (#1399). Letting it flow inline would put the caption
    // for one group in the middle of the previous group's buttons, which is exactly the
    // undifferentiated bracket stream the issue was filed about.
    if (current.length > 0 && (cell.kind === "group" || used + width > availableWidth)) {
      rows.push([cell]);
      used = width;
    } else {
      current.push(cell);
      used += width;
    }
  }
  return rows;
}

/** Drops a trailing row that is nothing but captions — a group header whose buttons all landed on
 *  the next page is a row of chrome introducing nothing. */
function dropDanglingCaptionRow(rows: CommandBarCell[][]): CommandBarCell[][] {
  const last = rows[rows.length - 1];
  return last && last.length > 0 && last.every((cell) => cell.kind === "group")
    ? rows.slice(0, -1)
    : rows;
}

/** One page of the bar: the rows to render, and which slice of the registry they cover. */
export interface CommandBarPage {
  readonly rows: CommandBarCell[][];
  /** Index into the button array of this page's first button. */
  readonly startIndex: number;
  /** How many buttons this page actually shows. Always >= 1, so paging always makes progress. */
  readonly count: number;
  /** Buttons not on this page — the number the pager cell discloses. */
  readonly hiddenCount: number;
}

/**
 * Splits `buttons` into pages that each fit `maxRows` rows of `availableWidth`, NEVER dropping a
 * command. When more than one page exists every page carries a pager cell, and the pager WRAPS:
 * from the last page it returns to the first. That is what makes the guarantee total — every
 * registered command is reachable by mouse at every width in a bounded number of clicks, rather
 * than "reachable by typing `/`", which is the keyboard-only state #1370 was filed to end.
 *
 * The pager's width is reserved BEFORE the buttons are packed, never allowed to push a row past
 * the pane edge; if its caption will not fit it degrades to a single glyph, so no width can
 * produce a page the operator cannot leave.
 */
export function commandBarPages(
  buttons: readonly CommandButton[],
  availableWidth: number,
  maxRows: number,
): CommandBarPage[] {
  if (buttons.length === 0 || maxRows <= 0) return [];
  const groups = groupCommandButtons(buttons);
  // Grouped order, flattened. Paging slices THIS, not the raw registry order, so a page is always
  // a contiguous run of the grouped layout and every command still appears exactly once.
  const flat = groups.flatMap((group) =>
    group.buttons.map((button) => ({ button, group })),
  );

  // A one-row bar has nothing to group: the single row is one fragment of one group, and a caption
  // on it would spend scarce columns saying so while pushing buttons onto a page they need not be
  // on. Below two rows the bar reverts to exactly its pre-#1399 shape — plain labels, no captions.
  const captionsAllowed = maxRows >= 2;

  /** Cells for `flat[start .. start+shown)`, re-emitting the caption of whichever group the slice
   *  opens in. Without the re-emit, a page starting mid-group would show captionless buttons. */
  const sliceCells = (start: number, shown: number, pager?: CommandBarCell): CommandBarCell[] => {
    const cells: CommandBarCell[] = [];
    let currentGroup: CommandButtonGroupId | undefined;
    for (let index = start; index < start + shown; index++) {
      const entry = flat[index]!;
      if (captionsAllowed && entry.group.id !== currentGroup) {
        cells.push(groupCell(entry.group, availableWidth));
        currentGroup = entry.group.id;
      }
      cells.push({ kind: "button", label: entry.button.label, button: entry.button });
    }
    if (pager) cells.push(pager);
    return cells;
  };

  // Fast path: the whole registry fits, so there is no pager and no paging.
  const full = packCommandBarRows(sliceCells(0, flat.length), availableWidth);
  if (full.length <= maxRows) {
    return [{ rows: full, startIndex: 0, count: flat.length, hiddenCount: 0 }];
  }

  const pages: CommandBarPage[] = [];
  let start = 0;
  while (start < flat.length) {
    const remaining = flat.length - start;
    let count = 0;
    let rows: CommandBarCell[][] | undefined;
    // Caption first, glyph only if the caption cannot be afforded at this width.
    for (const compact of [false, true]) {
      for (let shown = remaining; shown >= 1; shown--) {
        const hidden = flat.length - shown;
        const candidate = dropDanglingCaptionRow(
          packCommandBarRows(sliceCells(start, shown, overflowCell(hidden, compact)), availableWidth),
        );
        if (candidate.length <= maxRows) {
          count = shown;
          rows = candidate;
          break;
        }
      }
      if (rows) break;
    }
    if (!rows) {
      // A single label alone is wider than the pane. `packCommandBarRows` gives it its own whole
      // row rather than a clipped fragment; the page overruns the budget by that one row, which
      // is strictly better than a command with no button at all.
      count = 1;
      rows = packCommandBarRows(
        sliceCells(start, 1, overflowCell(flat.length - 1, true)),
        availableWidth,
      );
    }
    pages.push({ rows, startIndex: start, count, hiddenCount: flat.length - count });
    start += count;
  }
  return pages;
}

/**
 * How many terminal rows the bar will actually occupy for this input — the number the enclosing
 * pane must reserve before it hands the rest of its height to charts. Derived from the SAME
 * `commandBarPages` call the component renders from, so the reservation and the render can never
 * disagree about the bar's height (a pane that reserves fewer rows than the bar draws is how a
 * chart silently loses its bottom line).
 */
export function commandBarRowCount(
  buttons: readonly CommandButton[],
  availableWidth: number,
  maxRows: number,
  pageIndex: number = 0,
  hasNotice: boolean = false,
): number {
  const pages = commandBarPages(buttons, availableWidth, maxRows);
  if (pages.length === 0) return 0;
  const page = pages[resolveCommandBarPage(pageIndex, pages.length)]!;
  return page.rows.length + (hasNotice ? 1 : 0);
}

/**
 * The first page of the bar. Retained as the single-page view of `commandBarPages` for callers
 * that only need the opening layout; `hiddenCount` is now the count the pager PAGES to, not a
 * count of commands that have been given up on.
 */
export function commandBarLayout(
  buttons: readonly CommandButton[],
  availableWidth: number,
  maxRows: number,
): CommandBarLayout {
  if (buttons.length === 0) return { rows: [], hiddenCount: 0 };
  if (maxRows <= 0) return { rows: [], hiddenCount: buttons.length };
  const first = commandBarPages(buttons, availableWidth, maxRows)[0];
  if (!first) return { rows: [], hiddenCount: buttons.length };
  return { rows: first.rows, hiddenCount: first.hiddenCount };
}

/**
 * Clamps a remembered page index onto a live page count, wrapping past the end. Extracted so the
 * screen's stored index and the component's rendered index can never disagree about what a
 * shrunken terminal or a changed registry means: both go through this.
 */
export function resolveCommandBarPage(pageIndex: number, pageCount: number): number {
  if (pageCount <= 0) return 0;
  if (!Number.isFinite(pageIndex)) return 0;
  const wrapped = Math.trunc(pageIndex) % pageCount;
  return wrapped < 0 ? wrapped + pageCount : wrapped;
}
