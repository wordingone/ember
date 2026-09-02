// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// border-glyphs — the terminal-primitive glyph sets for each Box borderStyle name.
// Lives in ink/ (not components/design-system.ts) because border glyph SELECTION is a rendering
// primitive, not an app design token -- mirrors how termio.ts/rendering-pipeline.ts already own
// their own low-level concerns without importing the higher components/ layer. The EMBER_ASCII
// check is the one exception: it is read directly here (not passed down), matching how every
// OTHER Step-B ascii-fallback surface (fireball, status-bar) already degrades under the same env
// var, and it lets all ~29 existing borderStyle call sites become ascii-safe for free.

export type BorderStyleName =
  | "single" | "double" | "round" | "bold" | "singleDouble" | "doubleSingle" | "classic";

export interface BorderGlyphSet {
  topLeft: string; topRight: string; bottomLeft: string; bottomRight: string;
  horizontal: string; vertical: string;
}

const ASCII_SET: BorderGlyphSet = {
  topLeft: "+", topRight: "+", bottomLeft: "+", bottomRight: "+",
  horizontal: "-", vertical: "|",
};

// cli-boxes-compatible glyph sets -- these are the same border-style names/looks Ink itself
// exposes, so existing call sites (several of which already pass "classic"/"round" expecting a
// specific look) get exactly the shape they were authored for.
const BORDER_SETS: Record<BorderStyleName, BorderGlyphSet> = {
  single:       { topLeft: "┌", topRight: "┐", bottomLeft: "└", bottomRight: "┘", horizontal: "─", vertical: "│" },
  double:       { topLeft: "╔", topRight: "╗", bottomLeft: "╚", bottomRight: "╝", horizontal: "═", vertical: "║" },
  round:        { topLeft: "╭", topRight: "╮", bottomLeft: "╰", bottomRight: "╯", horizontal: "─", vertical: "│" },
  bold:         { topLeft: "┏", topRight: "┓", bottomLeft: "┗", bottomRight: "┛", horizontal: "━", vertical: "┃" },
  singleDouble: { topLeft: "╓", topRight: "╖", bottomLeft: "╙", bottomRight: "╜", horizontal: "─", vertical: "║" },
  doubleSingle: { topLeft: "╒", topRight: "╕", bottomLeft: "╘", bottomRight: "╛", horizontal: "═", vertical: "│" },
  classic:      ASCII_SET,
};

/** True when EMBER_ASCII=1 -- read directly (ink/ is below components/design-system.ts and must
 * not import it); matches the existing asciiModeEnabled() semantics exactly. */
function borderAsciiModeEnabled(): boolean {
  return process.env["EMBER_ASCII"] === "1";
}

/** Resolves the glyph set to paint for a given borderStyle, honoring the global ascii fallback. */
export function resolveBorderGlyphs(styleName: BorderStyleName): BorderGlyphSet {
  if (borderAsciiModeEnabled()) return ASCII_SET;
  return BORDER_SETS[styleName] ?? BORDER_SETS.single;
}
