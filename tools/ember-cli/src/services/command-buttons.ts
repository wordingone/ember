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

/** Button-shaped label, matching the operator controls' `[START]`-style affordance. */
export function commandButtonLabel(name: string): string {
  return `[/${name}]`;
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
// Width-bounded layout
// ---------------------------------------------------------------------------

/** One rendered cell of the bar: a real button, or the honest overflow marker. */
export type CommandBarCell =
  | { readonly kind: "button"; readonly label: string; readonly button: CommandButton }
  | { readonly kind: "overflow"; readonly label: string; readonly hiddenCount: number };

export interface CommandBarLayout {
  readonly rows: CommandBarCell[][];
  /** Commands with no visible button in this layout. Rendered as `+N more` so a hidden command
   *  is DISCLOSED rather than silently absent. */
  readonly hiddenCount: number;
}

/** Rendered width of a cell including its own single-column trailing gap. */
function cellWidth(cell: CommandBarCell): number {
  return cell.label.length + 1;
}

function overflowCell(hiddenCount: number): CommandBarCell {
  return { kind: "overflow", label: `+${hiddenCount} more`, hiddenCount };
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
    if (current.length > 0 && used + width > availableWidth) {
      rows.push([cell]);
      used = width;
    } else {
      current.push(cell);
      used += width;
    }
  }
  return rows;
}

/**
 * Packs `buttons` into at most `maxRows` rows of `availableWidth`. When they do not all fit, the
 * trailing rows are dropped and an overflow cell is packed IN PLACE of the last buttons that
 * would have fit — reserving the marker's own width rather than letting it push the row over the
 * pane edge. The dropped commands stay reachable by typing `/`, which is why disclosing the
 * count is sufficient and truncating in silence is not.
 */
export function commandBarLayout(
  buttons: readonly CommandButton[],
  availableWidth: number,
  maxRows: number,
): CommandBarLayout {
  if (buttons.length === 0) return { rows: [], hiddenCount: 0 };
  if (maxRows <= 0) return { rows: [], hiddenCount: buttons.length };
  const cells: CommandBarCell[] = buttons.map((button) => ({
    kind: "button" as const,
    label: button.label,
    button,
  }));
  const full = packCommandBarRows(cells, availableWidth);
  if (full.length <= maxRows) return { rows: full, hiddenCount: 0 };
  // Overflow: shrink the visible set until the buttons AND the marker fit the row budget.
  for (let shown = cells.length - 1; shown > 0; shown--) {
    const kept = cells.slice(0, shown);
    const hidden = cells.length - shown;
    const rows = packCommandBarRows([...kept, overflowCell(hidden)], availableWidth);
    if (rows.length <= maxRows) return { rows, hiddenCount: hidden };
  }
  // Even one button plus the marker does not fit: disclose everything as hidden.
  return { rows: [[overflowCell(cells.length)]], hiddenCount: cells.length };
}
