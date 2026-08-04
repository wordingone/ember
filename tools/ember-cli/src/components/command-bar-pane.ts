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
  commandBarLayout,
  commandButtonActivation,
  type CommandButton,
  type CommandButtonActivation,
} from "../services/command-buttons.ts";

export interface CommandBarPaneProps {
  /** The live registry. Rendered as-is; this component never filters or reorders it. */
  commands: readonly RegistryCommand[];
  /** Total columns the bar may occupy. */
  width: number;
  /** Row budget. Rows beyond it are traded for an explicit `+N more` disclosure. */
  maxRows?: number;
  /** Name of the command currently under the pointer, for the hover highlight. */
  hoveredCommand?: string;
  onHoverCommand?: (name: string | undefined) => void;
  /** Receives what the click MEANS; the caller performs it through its own prompt paths. */
  onActivate?: (activation: CommandButtonActivation, button: CommandButton) => void;
  /** One-line feedback row (a rejected activation's reason, or the argument hint after a
   *  prefill). Absent -> no row is spent on it. */
  notice?: string;
}

export const DEFAULT_COMMAND_BAR_MAX_ROWS = 2;

/**
 * Row budget for a terminal `rows` tall. The bar is chrome competing with the transcript, so it
 * only widens its footprint when there is genuine height to spend, and never takes more than one
 * row on a short terminal.
 */
export function commandBarMaxRows(terminalRows: number): number {
  if (terminalRows >= 40) return 3;
  if (terminalRows >= 24) return DEFAULT_COMMAND_BAR_MAX_ROWS;
  return 1;
}

export function CommandBarPane(props: CommandBarPaneProps): React.ReactElement | null {
  const { commands, width, hoveredCommand, onHoverCommand, onActivate, notice } = props;
  const maxRows = props.maxRows ?? DEFAULT_COMMAND_BAR_MAX_ROWS;
  const buttons = buildCommandButtons(commands);
  if (buttons.length === 0) return null;
  // Same content-budget discipline the operator surface uses: every line is bounded against the
  // TRUE inner width, so nothing can reach the enclosing overflow:"hidden" box wider than its
  // budget and get raw-clipped without a marker.
  const innerWidth = Math.max(1, width);
  const layout = commandBarLayout(buttons, innerWidth, maxRows);

  const renderCell = (
    cell: (typeof layout.rows)[number][number],
    key: string,
  ): React.ReactElement => {
    if (cell.kind === "overflow") {
      return React.createElement(
        Box,
        { key, flexShrink: 0, paddingRight: 1 },
        React.createElement(Text, { dimColor: true, wrap: "truncate-end" }, cell.label),
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
    ...layout.rows.map((row, rowIndex) =>
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
