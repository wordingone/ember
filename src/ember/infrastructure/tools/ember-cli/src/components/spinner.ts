// spinner.ts — animated spinner row for the "thinking" / in-progress state.
// Bundle: components/spinner.ts (line 322229)

import React, { useState } from "react";
import { Box, Text } from "../ink/components.ts";
import { useInterval } from "../ink/hooks.ts";

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

/** Base spinner frame set (forward pass). */
export const SPINNER_FRAMES_BASE: string[] = ["\xB7", "✢", "✳", "✶", "✻", "✽"];

/** Full frame set: base + reversed (ping-pong). */
export const SPINNER_FRAMES: string[] = [
  ...SPINNER_FRAMES_BASE,
  ...[...SPINNER_FRAMES_BASE].reverse(),
];

/** Ghostty-safe variant: replaces U+273D (✽) with ASCII "*". */
export const SPINNER_FRAMES_GHOSTTY: string[] = SPINNER_FRAMES.map(
  f => f === "✽" ? "*" : f,
);

export const SPINNER_FRAME_MS    = 120;
export const ANIMATION_LOOP_MS   = 50;
export const REDUCED_MOTION_GLYPH = "●"; // ●

export const SHIMMER_DELAY_MS    = 3000;
export const SHIMMER_PERIOD_MS   = 2000;
export const STALL_THRESHOLD_MS  = 3000;
export const STALL_FADE_START_MS = 3000;
export const STALL_FADE_END_MS   = 5000;

// ---------------------------------------------------------------------------
// Module-level globals (mirror bundle __esm init block)
// ---------------------------------------------------------------------------

export const SHIMMER_COLOR_LO = { r: 153, g: 153, b: 153 };
export const SHIMMER_COLOR_HI = { r: 185, g: 185, b: 185 };

let _prefersReducedMotion = false;
let _isGhostty            = false;

export function setPrefersReducedMotion(v: boolean): void { _prefersReducedMotion = v; }
export function setIsGhostty(v: boolean): void            { _isGhostty = v; }

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function getSpinnerFrames(): string[] {
  return _isGhostty ? SPINNER_FRAMES_GHOSTTY : SPINNER_FRAMES;
}

export function spinnerFrame(elapsedMs: number, frames: string[]): string {
  const idx = Math.floor(elapsedMs / SPINNER_FRAME_MS) % frames.length;
  return frames[idx] ?? frames[0] ?? "\xB7";
}

export function tokenStep(gap: number): number {
  if (gap < 3)  return 3;
  if (gap < 50) return 8;
  return 50;
}

export function advanceTokenCounter(displayCount: number, realCount: number): number {
  if (displayCount >= realCount) return realCount;
  return Math.min(displayCount + tokenStep(realCount - displayCount), realCount);
}

export function computeStallIntensity(
  msSinceLastToken: number,
  hasActiveTools:   boolean,
  leaderIsIdle:     boolean,
): number {
  if (hasActiveTools || leaderIsIdle)       return 0;
  if (msSinceLastToken < STALL_THRESHOLD_MS) return 0;
  const fadeMs = msSinceLastToken - STALL_FADE_START_MS;
  const range  = STALL_FADE_END_MS - STALL_FADE_START_MS;
  return Math.max(0, Math.min(1, fadeMs / range));
}

export interface RGB { r: number; g: number; b: number; }

export function interpolateRGB(a: RGB, b: RGB, t: number): RGB {
  return {
    r: Math.round(a.r + (b.r - a.r) * t),
    g: Math.round(a.g + (b.g - a.g) * t),
    b: Math.round(a.b + (b.b - a.b) * t),
  };
}

export function rgbToHex(c: RGB): string {
  return `#${c.r.toString(16).padStart(2, "0")}${c.g.toString(16).padStart(2, "0")}${c.b.toString(16).padStart(2, "0")}`;
}

export function thinkingShimmerColor(startedAtMs: number, nowMs: number): RGB | null {
  const elapsed = nowMs - startedAtMs;
  if (elapsed < SHIMMER_DELAY_MS) return null;
  const t    = ((elapsed - SHIMMER_DELAY_MS) % SHIMMER_PERIOD_MS) / SHIMMER_PERIOD_MS;
  const sine = (Math.sin(t * 2 * Math.PI) + 1) / 2;
  return interpolateRGB(SHIMMER_COLOR_LO, SHIMMER_COLOR_HI, sine);
}

export function renderSpinnerRow(
  elapsedMs:      number,
  reducedMotion:  boolean,
  frames:         string[],
  startedAtMs:    number,
  realTokenCount: number,
): React.ReactElement {
  if (reducedMotion) {
    const dimmed = Math.floor(elapsedMs / 2000) % 2 === 1;
    return React.createElement(Text, { dimColor: dimmed }, REDUCED_MOTION_GLYPH);
  }

  const glyph      = spinnerFrame(elapsedMs, frames);
  const shimmer    = thinkingShimmerColor(startedAtMs, startedAtMs + elapsedMs);
  const displayTok = advanceTokenCounter(0, realTokenCount);

  return React.createElement(
    Box, { flexDirection: "row" },
    React.createElement(Text, null, glyph),
    shimmer
      ? React.createElement(Text, { color: rgbToHex(shimmer) }, " Thinking…")
      : null,
    realTokenCount > 0
      ? React.createElement(Text, { dimColor: true }, ` ${displayTok}`)
      : null,
  );
}

// ---------------------------------------------------------------------------
// SpinnerAnimationRow — stateful animated component
// ---------------------------------------------------------------------------

export interface SpinnerAnimationRowProps {
  elapsedMs:         number;
  realTokenCount?:   number;
  startedAtMs?:      number;
  hasActiveTools?:   boolean;
  leaderIsIdle?:     boolean;
  msSinceLastToken?: number;
}

export function SpinnerAnimationRow(props: SpinnerAnimationRowProps): React.ReactElement {
  const {
    elapsedMs,
    realTokenCount   = 0,
    startedAtMs      = 0,
    hasActiveTools   = false,
    leaderIsIdle     = false,
  } = props;

  const [, setTick] = useState(0);
  useInterval(() => setTick(t => t + 1), ANIMATION_LOOP_MS);

  // stall intensity computed; reserved for future visual feedback path
  computeStallIntensity(props.msSinceLastToken ?? 0, hasActiveTools, leaderIsIdle);

  return renderSpinnerRow(
    elapsedMs,
    _prefersReducedMotion,
    getSpinnerFrames(),
    startedAtMs,
    realTokenCount,
  );
}
