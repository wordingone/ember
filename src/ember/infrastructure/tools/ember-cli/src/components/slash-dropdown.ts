// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// components/slash-dropdown.ts — the slash-command completion dropdown's rendering (issue b22
// item 1, ledgered since b14 as ember-cli-slash-dropdown). Exemplar: the field's own "/" menu
// convention (Claude Code, Crush) per field-ux-map §8b/§9 — thin box-drawing border + negative
// space (never a heavy frame), one interactive accent color (cyan, "primary" — the same token
// already used for the interaction/code accent elsewhere, never a new invented color), and color
// always paired with a marker glyph, never color alone (§9's documented anti-pattern). All
// selection/filter state is computed upstream by services/slash-dropdown.ts; this component is a
// pure function of its props, matching Fireball's pattern (components/fireball.ts) of a
// dependency-free render given fully-derived state.

import React from "react";
import type { RegistryCommand } from "../types/command-types.ts";
import { Box, Text } from "../ink/components.ts";
import { color, PANEL_BORDER_STYLE } from "./design-system.ts";
import { truncateWithEllipsis, slashDropdownDescriptionWidth } from "../../../../../../../tools/ember-cli/src/services/slash-dropdown.ts";

export interface SlashDropdownProps {
  /** Already filtered + capped to the visible slice (services/slash-dropdown.ts's
   * computeSlashDropdownDisplay) — this component does no filtering/capping of its own. */
  commands: RegistryCommand[];
  /** Already clamped into [0, commands.length-1] (or 0 for an empty list). */
  selectedIndex: number;
  /** Count of matches beyond the visible cap, rendered as a trailing "+N more" line when > 0. */
  overflowCount: number;
  /** Total terminal width available to the panel -- the same measurement PromptInput already
   * receives (`width: terminalCols` in repl.ts). Required, not optional: a caller that forgets to
   * pass the live width is exactly how the b22 gate's hard-clip wince happened in the first
   * place, so there's no silent fallback here to re-create that failure mode. Used to derive how
   * much room each row's description has left (b23) so long descriptions truncate with an
   * ellipsis instead of being cut off by the terminal buffer with no signal anything was cut. */
  width: number;
}

/** Selected marker glyph — the same prompt-caret language already used elsewhere (❯), so the
 * dropdown's own "this row is active" language matches the rest of the chrome instead of
 * inventing a second vocabulary. */
const SELECTED_MARKER = "❯ ";
const UNSELECTED_MARKER = "  ";

export function SlashDropdown({ commands, selectedIndex, overflowCount, width }: SlashDropdownProps): React.ReactElement {
  return React.createElement(
    Box,
    {
      flexDirection: "column",
      borderStyle: PANEL_BORDER_STYLE,
      borderColor: color("muted", "fg"),
      paddingX: 1,
      // 2026-07-25 operability finding (state/operability-finding-palette-renders-broken):
      // this Box had no flexShrink (defaults to 1, layout-engine.ts) and no overflow, so when
      // total sibling content (banner + transcript + prompt + status) exceeded the terminal's
      // row budget, the real CSS flex-shrink pass (layout-engine.ts's weighted-deficit
      // algorithm, B6 W4') proportionally compressed THIS box's own computed height right
      // alongside the transcript -- and with no overflow:"hidden" declared, its entry rows
      // painted straight past its own (now too-short) bounds into the next sibling's territory
      // (the real prompt row), instead of clipping cleanly the way overflow-clip.test.ts's W4
      // fix already proved for a tall transcript child. flexShrink:0 removes this box from the
      // deficit pool entirely (matching the same protection banner/prompt/status already carry,
      // per #561), so the caller's own `commands`/`overflowCount` slice -- already computed
      // upstream from the ACTUAL available rows -- is what determines how much is shown, never
      // an unpredictable layout squeeze; overflow:"hidden" stays as the defensive backstop
      // (matching the W4 precedent) in case some other future contention still shrinks it.
      flexShrink: 0,
      overflow: "hidden",
    },
    ...commands.map((cmd, i) => {
      const selected = i === selectedIndex;
      // b23: derive the description budget fresh from the CURRENT width on every render (never
      // cached) -- this is what makes the ellipsis survive a live resize (b14 reflow path): the
      // caller re-renders with a new `width` on every resize event, so this recomputes right along
      // with it, exactly like PromptInput's own width-driven wrapping already does.
      const descWidth = slashDropdownDescriptionWidth(width, cmd.name);
      const description = truncateWithEllipsis(cmd.description, descWidth);
      return React.createElement(
        Box,
        { key: cmd.name, flexDirection: "row" },
        React.createElement(
          Text,
          { color: selected ? color("primary", "fg") : undefined, bold: selected },
          `${selected ? SELECTED_MARKER : UNSELECTED_MARKER}/${cmd.name}`,
        ),
        React.createElement(Text, { color: color("muted", "fg") }, `  ${description}`),
      );
    }),
    overflowCount > 0
      ? React.createElement(
          Box,
          { key: "__overflow", flexDirection: "row" },
          React.createElement(Text, { color: color("muted", "fg"), dimColor: true }, `${UNSELECTED_MARKER}+${overflowCount} more`),
        )
      : null,
  );
}
