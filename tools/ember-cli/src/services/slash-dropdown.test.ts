// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/slash-dropdown.test.ts — behavioral tests for the slash-command completion
// dropdown's pure logic (issue b22 item 1, ledgered since b14 as ember-cli-slash-dropdown).
// Exemplar: the field's own "/" menu convention (Claude Code, Crush) per field-ux-map §8b/§9 —
// a filterable list of available commands appears the moment "/" is typed, narrows as more
// characters are typed, and closes the instant the input stops looking like "still composing a
// command name" (a space, a non-slash first char, or an empty input). Kept pure and
// dependency-free (mirrors slash-dispatch.ts's own style) so the REPL wiring only has to call
// these functions from its existing useInput/render loop, never re-derive the logic inline.

import { describe, it, expect } from "bun:test";
import {
  shouldShowSlashDropdown,
  slashQueryFrom,
  filterSlashCommands,
  moveDropdownSelection,
  clampDropdownSelection,
  completeSlashSelection,
  computeSlashDropdownDisplay,
  SLASH_DROPDOWN_MAX_VISIBLE,
  truncateWithEllipsis,
  slashDropdownDescriptionWidth,
  computeSlashDropdownBudget,
  DROPDOWN_BORDER_ROWS,
} from "./slash-dropdown.ts";
import type { RegistryCommand } from "../types/command-types.ts";

function cmd(over: Partial<RegistryCommand> & { name: string }): RegistryCommand {
  return {
    description: over.description ?? `the ${over.name} command`,
    isEnabled: over.isEnabled ?? (() => true),
    execute: over.execute ?? (async () => ({ type: "message", message: `${over.name} default` })),
    ...over,
  };
}

describe("shouldShowSlashDropdown", () => {
  it("shows for a bare slash and a slash with a partial command name", () => {
    expect(shouldShowSlashDropdown("/")).toBe(true);
    expect(shouldShowSlashDropdown("/h")).toBe(true);
    expect(shouldShowSlashDropdown("/help")).toBe(true);
    expect(shouldShowSlashDropdown("/model-picker")).toBe(true);
  });
  it("hides once a space is typed -- the user is now composing args for a chosen command", () => {
    expect(shouldShowSlashDropdown("/help ")).toBe(false);
    expect(shouldShowSlashDropdown("/model load qwen")).toBe(false);
  });
  it("hides for ordinary (non-slash) input", () => {
    expect(shouldShowSlashDropdown("")).toBe(false);
    expect(shouldShowSlashDropdown("hello")).toBe(false);
    expect(shouldShowSlashDropdown("hello /not-at-start")).toBe(false);
  });
  it("hides for multi-line input (a pasted block starting with a slash is not a command)", () => {
    expect(shouldShowSlashDropdown("/help\nmore text")).toBe(false);
  });
});

describe("slashQueryFrom", () => {
  it("strips the leading slash", () => {
    expect(slashQueryFrom("/")).toBe("");
    expect(slashQueryFrom("/mod")).toBe("mod");
  });
});

describe("filterSlashCommands", () => {
  const commands = [
    cmd({ name: "help" }),
    cmd({ name: "model" }),
    cmd({ name: "model-picker", aliases: ["mp"] }),
    cmd({ name: "clear" }),
  ];

  it("empty query returns every command, in registry order", () => {
    expect(filterSlashCommands(commands, "")).toEqual(commands);
  });
  it("filters by case-insensitive name prefix", () => {
    expect(filterSlashCommands(commands, "mod").map((c) => c.name)).toEqual(["model", "model-picker"]);
    expect(filterSlashCommands(commands, "MOD").map((c) => c.name)).toEqual(["model", "model-picker"]);
  });
  it("also matches an alias prefix", () => {
    expect(filterSlashCommands(commands, "mp").map((c) => c.name)).toEqual(["model-picker"]);
  });
  it("returns an empty array when nothing matches", () => {
    expect(filterSlashCommands(commands, "zzz")).toEqual([]);
  });
});

describe("moveDropdownSelection", () => {
  it("moves within bounds", () => {
    expect(moveDropdownSelection(0, 3, 1)).toBe(1);
    expect(moveDropdownSelection(1, 3, 1)).toBe(2);
    expect(moveDropdownSelection(1, 3, -1)).toBe(0);
  });
  it("wraps past the last item back to the first, and past the first to the last", () => {
    expect(moveDropdownSelection(2, 3, 1)).toBe(0);
    expect(moveDropdownSelection(0, 3, -1)).toBe(2);
  });
  it("is safe against an empty list (never divides by zero, never throws)", () => {
    expect(moveDropdownSelection(0, 0, 1)).toBe(0);
    expect(moveDropdownSelection(0, 0, -1)).toBe(0);
  });
});

describe("clampDropdownSelection", () => {
  it("clamps into [0, length-1]", () => {
    expect(clampDropdownSelection(5, 3)).toBe(2);
    expect(clampDropdownSelection(-1, 3)).toBe(0);
    expect(clampDropdownSelection(1, 3)).toBe(1);
  });
  it("returns 0 for an empty list", () => {
    expect(clampDropdownSelection(4, 0)).toBe(0);
  });
});

describe("completeSlashSelection", () => {
  it("returns the full command text with a trailing space, ready for the user to type args", () => {
    expect(completeSlashSelection(cmd({ name: "model" }))).toBe("/model ");
    expect(completeSlashSelection(cmd({ name: "model-picker" }))).toBe("/model-picker ");
  });
});

describe("computeSlashDropdownDisplay", () => {
  const many = Array.from({ length: SLASH_DROPDOWN_MAX_VISIBLE + 3 }, (_, i) => cmd({ name: `cmd${i}` }));

  it("caps visible list at SLASH_DROPDOWN_MAX_VISIBLE and reports the overflow count", () => {
    const display = computeSlashDropdownDisplay(many, 0);
    expect(display.visible.length).toBe(SLASH_DROPDOWN_MAX_VISIBLE);
    expect(display.overflowCount).toBe(3);
  });
  it("passes through a short list with zero overflow", () => {
    const short = many.slice(0, 2);
    const display = computeSlashDropdownDisplay(short, 1);
    expect(display.visible).toEqual(short);
    expect(display.overflowCount).toBe(0);
    expect(display.selectedIndex).toBe(1);
  });
  it("clamps a stale selectedIndex into the (possibly truncated) visible range", () => {
    const display = computeSlashDropdownDisplay(many, 999);
    expect(display.selectedIndex).toBe(SLASH_DROPDOWN_MAX_VISIBLE - 1);
  });
  it("never throws on an empty match list", () => {
    const display = computeSlashDropdownDisplay([], 0);
    expect(display.visible).toEqual([]);
    expect(display.overflowCount).toBe(0);
    expect(display.selectedIndex).toBe(0);
  });
});

// b23: banked wince from the b22 gate -- descriptions that exceed the available row width must
// truncate with an ellipsis (matching the field exemplar) instead of hard-clipping at the pane's
// right edge (the /cockpit row's real description, "C-OBS observatory: MONITOR/UNDERSTAND/..." is
// the live repro at default width -- long enough to overflow an 80-col panel).
describe("truncateWithEllipsis", () => {
  it("returns the text unchanged when it fits exactly (no ellipsis on an exact fit)", () => {
    expect(truncateWithEllipsis("exactly ten", 11)).toBe("exactly ten");
  });
  it("returns the text unchanged when it's shorter than the available width", () => {
    expect(truncateWithEllipsis("short", 20)).toBe("short");
  });
  it("truncates and appends a single ellipsis character when the text overflows", () => {
    const result = truncateWithEllipsis("this description is far too long to fit", 10);
    expect(result.length).toBe(10);
    expect(result.endsWith("…")).toBe(true);
    expect(result).toBe("this desc…");
  });
  it("the real /cockpit description truncates cleanly at a realistic panel width", () => {
    const cockpitDesc =
      "C-OBS observatory: MONITOR/UNDERSTAND/INTERACT over the real GOAL/ledger/receipts world-state adapter, with click-to-evidence and a confirm-only encounter membrane";
    const result = truncateWithEllipsis(cockpitDesc, 40);
    expect(result.length).toBe(40);
    expect(result.endsWith("…")).toBe(true);
    // The clipped bug's failure mode: no ellipsis, an arbitrary mid-word cutoff with nothing
    // signaling more text exists. The fix must always signal truncation happened.
    expect(result).not.toBe(cockpitDesc.slice(0, 40));
  });
  it("degenerates safely for a 1-character budget (just the ellipsis, no source text)", () => {
    expect(truncateWithEllipsis("anything", 1)).toBe("…");
  });
  it("degenerates safely for a zero or negative budget (empty string, never throws/negative-slices)", () => {
    expect(truncateWithEllipsis("anything", 0)).toBe("");
    expect(truncateWithEllipsis("anything", -5)).toBe("");
  });
});

describe("slashDropdownDescriptionWidth", () => {
  it("subtracts border, padding, marker, slash, and gap from the panel width", () => {
    // panelWidth 80, name "model" (5 chars): reserved = 2(border)+2(paddingX)+2(marker)+1(/)+2(gap) = 9,
    // plus the name itself (5) = 14 reserved; 80-14 = 66.
    expect(slashDropdownDescriptionWidth(80, "model")).toBe(66);
  });
  it("shrinks as the command name gets longer (same panel width)", () => {
    const shortName = slashDropdownDescriptionWidth(80, "model");
    const longName  = slashDropdownDescriptionWidth(80, "model-picker-extended");
    expect(longName).toBeLessThan(shortName);
  });
  it("shrinks as the panel narrows -- this is what makes the ellipsis survive a resize (b14 reflow)", () => {
    const wide    = slashDropdownDescriptionWidth(120, "model");
    const narrow  = slashDropdownDescriptionWidth(40, "model");
    expect(narrow).toBeLessThan(wide);
  });
  it("never goes negative even when the name alone exceeds the panel width", () => {
    expect(slashDropdownDescriptionWidth(10, "an-extremely-long-command-name")).toBe(0);
  });
});

describe("computeSlashDropdownBudget — the exact no-room budget (2026-07-25 counterparty finding, second/third/fourth rounds)", () => {
  // Team-lead's own worked cases, reproduced as tests rather than trusted as prose -- each checks
  // both the resolved cap AND the exact-accounting invariant
  // (DROPDOWN_BORDER_ROWS + cap + indicator == contentBudget + DROPDOWN_BORDER_ROWS).
  it("contentBudget=3 (terminalRows=11, reserve=6, banner=0), 10 matches -> cap 2, exact accounting 5 against 5 available", () => {
    const b = computeSlashDropdownBudget(11, 6, 0, 10);
    expect(b.contentBudget).toBe(3);
    expect(b.cap).toBe(2);
    const requestedHeight = DROPDOWN_BORDER_ROWS + b.cap + (10 > b.cap ? 1 : 0);
    expect(requestedHeight).toBe(b.contentBudget + DROPDOWN_BORDER_ROWS);
  });

  it("contentBudget=1 (terminalRows=9, reserve=6, banner=0), 10 matches -> cap 0, the honest zero-visible render, exact accounting 3 against 3", () => {
    const b = computeSlashDropdownBudget(9, 6, 0, 10);
    expect(b.contentBudget).toBe(1);
    expect(b.cap).toBe(0);
    const requestedHeight = DROPDOWN_BORDER_ROWS + b.cap + (10 > b.cap ? 1 : 0);
    expect(requestedHeight).toBe(b.contentBudget + DROPDOWN_BORDER_ROWS);
    expect(b.showPanel).toBe(true); // contentBudget>=1: box still renders, just the indicator
  });

  it("contentBudget=8 (terminalRows=16, reserve=6, banner=0), 10 matches -> cap 7, exact accounting 10 against 10", () => {
    const b = computeSlashDropdownBudget(16, 6, 0, 10);
    expect(b.contentBudget).toBe(8);
    expect(b.cap).toBe(7);
    const requestedHeight = DROPDOWN_BORDER_ROWS + b.cap + (10 > b.cap ? 1 : 0);
    expect(requestedHeight).toBe(b.contentBudget + DROPDOWN_BORDER_ROWS);
  });

  it("contentBudget=8, exactly 8 matches (exact fit, no overflow) -> cap 8, no indicator reserved, exact accounting 10 against 10", () => {
    const b = computeSlashDropdownBudget(16, 6, 0, 8);
    expect(b.contentBudget).toBe(8);
    expect(b.cap).toBe(8);
    const requestedHeight = DROPDOWN_BORDER_ROWS + b.cap + (8 > b.cap ? 1 : 0);
    expect(requestedHeight).toBe(10);
    expect(b.contentBudget + DROPDOWN_BORDER_ROWS).toBe(10);
  });

  it("arithmetic-only: requested box height never exceeds the computed budget at a tight viewport that triggers overflow", () => {
    // 10 matches at a 20-row terminal, no banner -- deliberately picked to force overflow
    // (10 > SLASH_DROPDOWN_MAX_VISIBLE), the case where a naive budget (one that doesn't reserve
    // the indicator row) over-asks by exactly one row.
    const terminalRows = 20;
    const promptStatusReserve = 6;
    const bannerRows = 0;
    const matchCount = 10;
    const b = computeSlashDropdownBudget(terminalRows, promptStatusReserve, bannerRows, matchCount);
    const willOverflow = matchCount > b.cap;
    const requestedHeight = DROPDOWN_BORDER_ROWS + b.cap + (willOverflow ? 1 : 0);
    const available = terminalRows - promptStatusReserve - bannerRows;
    expect(requestedHeight).toBeLessThanOrEqual(available);
  });

  it("resolves to 0 -- not floored to 1 -- when the budget cannot fit even a single entry plus its indicator row", () => {
    // 8 total rows, no banner, 6 reserved for prompt/status leaves 2 for the dropdown's own
    // border alone -- zero left for any entry or the indicator row it would need once there's
    // overflow. A floor of 1 here would silently over-ask by exactly one row.
    const b = computeSlashDropdownBudget(8, 6, 0, 10);
    expect(b.cap).toBe(0);
  });

  it("does not reserve the indicator row when every match already fits (no overflow, no indicator to budget for)", () => {
    // Unlike the retired slashDropdownMaxVisible (a ceiling independent of matchCount),
    // computeSlashDropdownBudget's cap already incorporates matchCount directly -- 3 matches
    // against a generous budget resolves to cap=3, not the SLASH_DROPDOWN_MAX_VISIBLE ceiling.
    const b = computeSlashDropdownBudget(40, 6, 0, 3);
    expect(b.cap).toBe(3);
    // And downstream, the actual render only ever shows the 3 real matches, no phantom indicator.
    const commands = ["a", "b", "c"].map((name) => ({ name, description: "", isEnabled: () => true, execute: async () => ({ type: "message" as const, message: "" }) }));
    const display = computeSlashDropdownDisplay(commands, 0, b.cap);
    expect(display.visible.length).toBe(3);
    expect(display.overflowCount).toBe(0);
  });

  it("collapses the banner (collapseHomescreen=true) only when a full banner would leave less than 1 row of content budget, and never when there are no matches", () => {
    // terminalRows=20, reserve=6, banner=16 -> first-pass contentBudget = 20-6-2-16 = -4 < 1:
    // collapse triggers, recomputed contentBudget = 20-6-2-0 = 12.
    const withMatches = computeSlashDropdownBudget(20, 6, 16, 5);
    expect(withMatches.collapseHomescreen).toBe(true);
    expect(withMatches.contentBudget).toBe(12);

    // Same geometry but zero matches (dropdown not actually open on anything) -- must never
    // collapse the banner for a palette that isn't showing anything.
    const noMatches = computeSlashDropdownBudget(20, 6, 16, 0);
    expect(noMatches.collapseHomescreen).toBe(false);

    // A roomy terminal never needs to collapse even with a full banner.
    const roomy = computeSlashDropdownBudget(60, 6, 16, 5);
    expect(roomy.collapseHomescreen).toBe(false);
  });

  it("showPanel is false -- nothing renders, not even borders -- only when contentBudget stays below 1 after the collapse attempt (the disclosed residual)", () => {
    // Even with the banner collapsed (bannerRows passed as 0 directly, i.e. already the collapsed
    // case), reserve+borders alone exceed terminalRows: genuinely no room for anything.
    const b = computeSlashDropdownBudget(6, 6, 0, 10);
    expect(b.contentBudget).toBeLessThan(1);
    expect(b.showPanel).toBe(false);
    expect(b.cap).toBe(0);
  });
});
