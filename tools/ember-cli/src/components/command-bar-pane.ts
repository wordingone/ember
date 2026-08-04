// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// components/command-bar-pane.ts — the clickable equivalent of every registered slash command.
//
// Before this pane, only the LIVE RUN controls ([START] [PAUSE] [RESUME] [RESTART]) were
// mouse-reachable; every other operation in the registry was keyboard-only through the prompt.
// This renders one button per registered command, straight off `services/command-buttons.ts`'s
// registry-derived model, using the same visual affordance the run controls established:
// green = available, gray = unavailable, inverse = hovered, `[...]` = clickable.
//
// Since #1399 this pane is mounted INSIDE the live-run pane, directly under those four run
// controls, and its buttons are captioned group blocks (`launch` / `inspect` / `govern` / `more`)
// with plain labels — `[verify]`, not `[/verify]`. It renders wherever it is mounted; the choice
// of home belongs to components/operator-surface-pane.ts, and nothing here assumes one.
//
// Two invariants this component exists to hold:
//
//  1. It never enumerates commands itself. It receives `RegistryCommand[]` and renders whatever
//     is in it. A newly registered command therefore gains its button with zero edits here.
//  2. Its click handlers produce an activation and hand it to the caller. It owns no dispatch
//     path, no composer state, and no focus state, so a click cannot take keyboard focus away
//     from the prompt — the buttons are equivalents of typing, never a replacement for it.

import React from "react";
import { Box, Text } from "../ink/components.ts";
import type { RegistryCommand } from "../types/command-types.ts";
import {
  buildCommandButtons,
  commandBarPages,
  commandButtonActivation,
  resolveCommandBarPage,
  type CommandButton,
  type CommandButtonActivation,
} from "../services/command-buttons.ts";

export interface CommandBarPaneProps {
  /** The live registry. Every entry gets a button; this component never FILTERS it. Since #1399
   *  the buttons are laid out in group order rather than raw registry order — a presentation
   *  regrouping applied by `groupCommandButtons`, under which every command still appears exactly
   *  once, including commands no group claims. */
  commands: readonly RegistryCommand[];
  /** Total columns the bar may occupy. */
  width: number;
  /** Row budget per page. Commands beyond it move to the next page, never out of reach. */
  maxRows?: number;
  /** Name of the command currently under the pointer, for the hover highlight. */
  hoveredCommand?: string;
  onHoverCommand?: (name: string | undefined) => void;
  /** Which page of buttons to show. Out-of-range values are wrapped, never clamped to an empty
   *  bar, so a stale index from a resize or a registry change can only ever land on a real page. */
  page?: number;
  /** The page a click on the pager means. Absent -> the pager is not rendered clickable, which
   *  is the state this component exists to make impossible in production. */
  onPageChange?: (page: number) => void;
  /** Receives what the click MEANS; the caller performs it through its own prompt paths. */
  onActivate?: (activation: CommandButtonActivation, button: CommandButton) => void;
  /** One-line feedback row (a rejected activation's reason, or the argument hint after a
   *  prefill). Absent -> no row is spent on it. */
  notice?: string;
}

export const DEFAULT_COMMAND_BAR_MAX_ROWS = 2;

/**
 * Row budget for a terminal `rows` tall.
 *
 * Raised at every tier by #1399: the bar no longer competes with the TRANSCRIPT — it lives in the
 * live-run pane, where it competes with telemetry charts that already disclose their own hidden
 * count and shrink gracefully. It also now spends a row per group caption, so the pre-#1399
 * budget of 1–3 rows would have turned a four-group layout into pure paging at every size.
 */
export function commandBarMaxRows(terminalRows: number): number {
  if (terminalRows >= 40) return 6;
  if (terminalRows >= 30) return 5;
  if (terminalRows >= 24) return 4;
  return DEFAULT_COMMAND_BAR_MAX_ROWS;
}

export function CommandBarPane(props: CommandBarPaneProps): React.ReactElement | null {
  const { commands, width, hoveredCommand, onHoverCommand, onActivate, onPageChange, notice } = props;
  const maxRows = props.maxRows ?? DEFAULT_COMMAND_BAR_MAX_ROWS;
  const buttons = buildCommandButtons(commands);
  if (buttons.length === 0) return null;
  // Same content-budget discipline the operator surface uses: every line is bounded against the
  // TRUE inner width, so nothing can reach the enclosing overflow:"hidden" box wider than its
  // budget and get raw-clipped without a marker.
  const innerWidth = Math.max(1, width);
  const pages = commandBarPages(buttons, innerWidth, maxRows);
  if (pages.length === 0) return null;
  const pageIndex = resolveCommandBarPage(props.page ?? 0, pages.length);
  const page = pages[pageIndex]!;

  const renderCell = (
    cell: (typeof page.rows)[number][number],
    key: string,
  ): React.ReactElement => {
    if (cell.kind === "group") {
      // A caption, deliberately NOT a click target: it names the group, and giving it a handler
      // would make a third thing that looks clickable and dispatches nothing.
      return React.createElement(
        Box,
        { key, flexShrink: 0, paddingRight: 1 },
        React.createElement(
          Text,
          { dimColor: true, bold: true, wrap: "truncate-end" },
          cell.label,
        ),
      );
    }
    if (cell.kind === "overflow") {
      // The pager is a BUTTON, not a caption. Clicking it advances a page and wraps at the end,
      // so every command the bar cannot show at this width is still a bounded number of clicks
      // away. Rendered in the same green/`[...]` affordance as the commands themselves, because
      // it is exactly as clickable as they are.
      return React.createElement(
        Box,
        {
          key,
          flexShrink: 0,
          paddingRight: 1,
          onClick: onPageChange ? () => onPageChange(pageIndex + 1) : undefined,
        },
        React.createElement(
          Text,
          { color: onPageChange ? "green" : undefined, dimColor: !onPageChange, wrap: "truncate-end" },
          cell.label,
        ),
      );
    }
    const button = cell.button;
    const hovered = hoveredCommand === button.name;
    return React.createElement(
      Box,
      {
        key,
        flexShrink: 0,
        paddingRight: 1,
        // Disabled buttons keep their handler on purpose: the activation comes back `rejected`
        // with a named reason, so a click on an unavailable command SAYS why instead of being
        // indistinguishable from a dead pixel.
        onClick: onActivate
          ? () => onActivate(commandButtonActivation(button), button)
          : undefined,
        onMouseEnter: onHoverCommand ? () => onHoverCommand(button.name) : undefined,
        onMouseLeave: onHoverCommand ? () => onHoverCommand(undefined) : undefined,
      },
      React.createElement(
        Text,
        {
          color: button.enabled ? "green" : "gray",
          bold: hovered,
          inverse: hovered,
          wrap: "truncate-end",
        },
        cell.label,
      ),
    );
  };

  return React.createElement(
    Box,
    {
      flexDirection: "column",
      width: innerWidth,
      flexShrink: 0,
      overflow: "hidden",
    },
    ...page.rows.map((row, rowIndex) =>
      React.createElement(
        Box,
        { key: `command-bar-row-${rowIndex}`, flexDirection: "row", height: 1, flexShrink: 0 },
        ...row.map((cell, cellIndex) =>
          renderCell(cell, `command-bar-cell-${rowIndex}-${cellIndex}`),
        ),
      ),
    ),
    notice
      ? React.createElement(
          Box,
          { key: "command-bar-notice", height: 1, flexShrink: 0 },
          React.createElement(
            Text,
            { color: "yellow", wrap: "truncate-end" },
            notice.length <= innerWidth ? notice : `${notice.slice(0, Math.max(0, innerWidth - 1))}…`,
          ),
        )
      : null,
  );
}
