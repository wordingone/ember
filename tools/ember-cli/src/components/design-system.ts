// design-system.ts — theme/color design tokens and React context for the TUI.
// Bundle: components/design-system.ts (line 309052)

import React, { createContext, useContext, useState, useEffect } from "react";

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

export const VISIBLE_RESULTS  = 12;
export const DEBOUNCE_MS      = 100;
export const LARGE_FILE_BYTES = 1 * 1024 * 1024;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ThemeMode     = "dark" | "light" | "auto";
export type ResolvedTheme = "dark" | "light";
export type ColorRole     = "fg" | "bg";
export type ColorKey      =
  | "error" | "success" | "warning" | "info" | "pending" | "loading" | "primary" | "muted"
  // "identity" — the Observatory ember/coal lineage (state/design-mockups/*.html, operator-authored).
  // Reused deliberately (increment 6 step A GO verdict) rather than inventing a new palette: logo,
  // headings, panel borders. "primary" (cyan, already existed) is reused as the interaction/code
  // accent -- it is NOT duplicated under a new "accent" key.
  | "identity";

export interface ThemeEntry {
  fg: string;
  bg: string;
}

export interface ThemeContextValue {
  currentTheme: ResolvedTheme;
  mode:         ThemeMode;
}

export interface FeatureFlags {
  AUTO_THEME?:      boolean;
  KAIROS?:          boolean;
  KAIROS_CHANNELS?: boolean;
  KAIROS_BRIEF?:    boolean;
  [key: string]:    boolean | undefined;
}

// ---------------------------------------------------------------------------
// Contexts
// ---------------------------------------------------------------------------

export const ThemeContext = createContext<ThemeContextValue>({
  currentTheme: "dark",
  mode:         "dark",
});

export const IsInsideModalContext = createContext<boolean>(false);

export const TextHoverColorContext = createContext<string | undefined>(undefined);

// ---------------------------------------------------------------------------
// Theme palette (spec — preserve exactly)
// ---------------------------------------------------------------------------

export const THEME_PALETTE: Record<ColorKey, Record<ResolvedTheme, ThemeEntry>> = {
  error:   { dark: { fg: "red",    bg: "#3a0000" }, light: { fg: "red",    bg: "#ffe0e0" } },
  success: { dark: { fg: "green",  bg: "#003a00" }, light: { fg: "green",  bg: "#e0ffe0" } },
  warning: { dark: { fg: "yellow", bg: "#2a2000" }, light: { fg: "yellow", bg: "#fffae0" } },
  info:    { dark: { fg: "blue",   bg: "#001a3a" }, light: { fg: "blue",   bg: "#e0f0ff" } },
  pending: { dark: { fg: "gray",   bg: "#1a1a1a" }, light: { fg: "gray",   bg: "#f0f0f0" } },
  loading: { dark: { fg: "gray",   bg: "#1a1a1a" }, light: { fg: "gray",   bg: "#f0f0f0" } },
  primary: { dark: { fg: "cyan",   bg: "#002a2a" }, light: { fg: "cyan",   bg: "#e0ffff" } },
  muted:   { dark: { fg: "gray",   bg: "#111111" }, light: { fg: "gray",   bg: "#f8f8f8" } },
  // Ember-orange / coal lineage: identity mark, headings, panel borders.
  identity: { dark: { fg: "#FF7A3D", bg: "#2a0f00" }, light: { fg: "#C43410", bg: "#ffe8db" } },
};

export const COLOR_FALLBACK: ThemeEntry = { fg: "white", bg: "#000000" };

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function detectSystemTheme(): ResolvedTheme {
  return "dark";
}

export function resolveTheme(mode: ThemeMode, flags?: FeatureFlags): ResolvedTheme {
  if (mode === "light")     return "light";
  if (mode === "dark")      return "dark";
  if (flags?.AUTO_THEME)    return detectSystemTheme();
  return "dark";
}

export function color(key: ColorKey, role: ColorRole, theme: ResolvedTheme = "dark"): string {
  const row   = THEME_PALETTE[key];
  const entry = row ? row[theme] : COLOR_FALLBACK;
  return role === "fg" ? entry.fg : entry.bg;
}

// ---------------------------------------------------------------------------
// Panel border token
// ---------------------------------------------------------------------------

/** The one semantic border style every bordered panel uses (Step-A mockups: ╭─╮ round corners). */
export const PANEL_BORDER_STYLE = "round" as const;

// ---------------------------------------------------------------------------
// Glyph vocabulary (Step B) — unicode + ascii pair per named glyph, mirrors the
// EMBER_ASCII discipline already established in cognitive-mode.ts's GLYPH_TABLE.
// New Step-B surfaces (turn markers, observatory/board segment, tool-call log)
// read glyphs from here so ASCII fallback is centralized instead of re-invented
// per call site.
// ---------------------------------------------------------------------------

export interface GlyphEntry {
  unicode: string;
  ascii:   string;
}

export const UI_GLYPHS = {
  // Assistant turn marker in the transcript. Deliberately BMP-safe (U+25CF, a
  // single codepoint, not a surrogate-pair emoji) -- team-lead's Step-A note:
  // Cascadia-Mono-only rasters show emoji-class glyphs as boxes, and this
  // marker (unlike the already-shipped cognitive-mode 🔥) is not load-bearing.
  turnMarker: { unicode: "●", ascii: "*" },
  // Observatory board-count segment glyph ("⬢ 23/30 GREEN").
  boardHex:   { unicode: "⬢", ascii: "#" },
  // Tool-call log in-flight glyph ("bash⚙ running tests…").
  gear:       { unicode: "⚙", ascii: "~" },
} satisfies Record<string, GlyphEntry>;

export type GlyphKey = keyof typeof UI_GLYPHS;

/** True when EMBER_ASCII=1 -- the existing glyph-fallback flag (cognitive-mode.ts), read here so
 * every Step-B call site shares one definition of "ascii mode" instead of re-checking env itself. */
export function asciiModeEnabled(): boolean {
  return process.env["EMBER_ASCII"] === "1";
}

/** Returns the unicode or ascii form of a named glyph depending on asciiModeEnabled(). */
export function glyph(name: GlyphKey): string {
  const entry = UI_GLYPHS[name];
  return asciiModeEnabled() ? entry.ascii : entry.unicode;
}

/** True when EMBER_REDUCED_MOTION=1 -- suspends animated surfaces (the fireball's frame timer)
 * for accessibility/photosensitivity, independent of color/ascii mode (a colorless or ASCII
 * surface can still animate; this flag is the dedicated motion switch, mirroring the
 * EMBER_ASCII / NO_COLOR discipline above but as its own axis per
 * state/specs/ember-fireball-cognitive-mode.md's "respect reduced-motion" requirement). */
export function reducedMotionEnabled(): boolean {
  return process.env["EMBER_REDUCED_MOTION"] === "1";
}

// ---------------------------------------------------------------------------
// useTheme
// ---------------------------------------------------------------------------

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

// ---------------------------------------------------------------------------
// ThemeProvider
// ---------------------------------------------------------------------------

export interface ThemeProviderProps {
  mode?:     ThemeMode;
  flags?:    FeatureFlags;
  children?: React.ReactNode;
}

export function ThemeProvider({ mode = "dark", flags, children }: ThemeProviderProps): React.ReactElement {
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme(mode, flags));

  useEffect(() => {
    const next = resolveTheme(mode, flags);
    setResolved(next);
    if (mode === "auto" && flags?.AUTO_THEME) {
      const id = setInterval(() => setResolved(detectSystemTheme()), 5000);
      return () => clearInterval(id);
    }
    return;
  }, [mode, flags]);

  const value: ThemeContextValue = { currentTheme: resolved, mode };

  return React.createElement(ThemeContext.Provider, { value }, children);
}
