// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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

/**
 * What the turn is doing right now when it is not just thinking (blind test S24: a long command
 * ran under a spinner that said "Thinking… 6m 29s"). A tool call that is running names itself,
 * counts its own time, and shows the last line it printed; a call waiting for approval says so.
 */
export interface SpinnerActivity {
  /** "Running Bash: ping -t 127.0.0.1" / "Waiting for approval: Bash(...)". */
  label: string;
  /** Time on THIS activity (the tool's own run time), not on the whole turn. */
  elapsedMs: number;
  /** The last line of output the running tool printed, if it streams any. */
  tail?: string;
}

/** The spinner label for a running tool call: "Running Bash: <short command>". */
export function runningToolLabel(toolName: string, summary: string, maxSummary = 60): string {
  const short = summary.length > maxSummary ? summary.slice(0, maxSummary - 1) + "…" : summary;
  return short ? `Running ${toolName}: ${short}` : `Running ${toolName}`;
}

/** A tool call the query loop is executing right now, as the screen tracks it. */
export interface ActiveToolCall {
  toolName: string;
  summary:  string;
  startedAt: number;
  tail:     string;
}

/**
 * What the spinner should say. A pending approval wins (nothing is running while the user is
 * asked), then the most recently started tool call that is still running; otherwise null and the
 * spinner stays on "Thinking…".
 */
export function pickSpinnerActivity(
  active: Iterable<ActiveToolCall>,
  approval: { summary: string; since: number } | null,
  now: number,
): SpinnerActivity | undefined {
  if (approval) {
    return { label: `Waiting for your approval: ${approval.summary}`, elapsedMs: Math.max(0, now - approval.since) };
  }
  let newest: ActiveToolCall | undefined;
  for (const call of active) if (!newest || call.startedAt >= newest.startedAt) newest = call;
  if (!newest) return undefined;
  return {
    label: runningToolLabel(newest.toolName, newest.summary),
    elapsedMs: Math.max(0, now - newest.startedAt),
    ...(newest.tail ? { tail: newest.tail } : {}),
  };
}

/** The dim second row under the spinner: what the running tool last printed, cut to `width`. */
export function formatSpinnerTail(tail: string, width: number): string {
  const room = Math.max(8, width - 4);
  const one = tail.replace(/\s+/g, " ").trim();
  return "  ⎿ " + (one.length > room ? one.slice(0, room - 1) + "…" : one);
}

/** The activity label cut so glyph + label + time + hint stay on ONE row of `width` cells. */
export function fitActivityLabel(activity: SpinnerActivity, width?: number): string {
  if (width === undefined) return activity.label;
  const suffix = ` ${formatSpinnerElapsed(activity.elapsedMs)} · Esc to interrupt`;
  const room = Math.max(12, width - 2 - suffix.length - 1);
  return activity.label.length > room ? activity.label.slice(0, room - 1) + "…" : activity.label;
}

export function renderSpinnerRow(
  elapsedMs:      number,
  reducedMotion:  boolean,
  frames:         string[],
  startedAtMs:    number,
  realTokenCount: number,
  activity?:      SpinnerActivity,
  width?:         number,
): React.ReactElement {
  if (reducedMotion) {
    const dimmed = Math.floor(elapsedMs / 2000) % 2 === 1;
    const glyph = React.createElement(Text, { dimColor: dimmed }, REDUCED_MOTION_GLYPH);
    return activity
      ? React.createElement(Box, { flexDirection: "row" }, glyph,
          React.createElement(Text, null, ` ${fitActivityLabel(activity, width)}`),
          React.createElement(Text, { dimColor: true }, ` ${formatSpinnerElapsed(activity.elapsedMs)} · Esc to interrupt`))
      : glyph;
  }

  const glyph      = spinnerFrame(elapsedMs, frames);
  const shimmer    = thinkingShimmerColor(startedAtMs, startedAtMs + elapsedMs);
  const displayTok = advanceTokenCounter(0, realTokenCount);

  if (activity) {
    const row = React.createElement(
      Box, { flexDirection: "row" },
      React.createElement(Text, null, glyph),
      React.createElement(Text, shimmer ? { color: rgbToHex(shimmer) } : null, ` ${fitActivityLabel(activity, width)}`),
      React.createElement(Text, { dimColor: true }, ` ${formatSpinnerElapsed(activity.elapsedMs)} · Esc to interrupt`),
    );
    if (!activity.tail) return row;
    return React.createElement(
      Box, { flexDirection: "column" },
      row,
      React.createElement(Text, { dimColor: true }, formatSpinnerTail(activity.tail, width ?? 80)),
    );
  }

  return React.createElement(
    Box, { flexDirection: "row" },
    React.createElement(Text, null, glyph),
    shimmer
      ? React.createElement(Text, { color: rgbToHex(shimmer) }, " Thinking…")
      : null,
    realTokenCount > 0
      ? React.createElement(Text, { dimColor: true }, ` ${displayTok}`)
      : null,
    // A wait the user can measure, and how to leave it.
    elapsedMs >= 1000
      ? React.createElement(Text, { dimColor: true }, ` ${formatSpinnerElapsed(elapsedMs)} · Esc to interrupt`)
      : null,
  );
}

/** "7s", "1m 05s". */
export function formatSpinnerElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
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
  /** A running tool call / pending approval; replaces "Thinking…" while it lasts. */
  activity?:         SpinnerActivity;
  /** Width the row may use; bounds the output-tail row. */
  width?:            number;
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
    props.activity,
    props.width,
  );
}
