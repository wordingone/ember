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
export type ColorKey      = "error" | "success" | "warning" | "info" | "pending" | "loading" | "primary" | "muted";

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
