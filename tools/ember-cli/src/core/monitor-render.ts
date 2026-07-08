// core/monitor-render.ts — pure rendering helpers for the cockpit `monitor` surface.
//
// Originally extracted out of core/ember-world-state-repl.ts (a standalone proof-pack REPL that
// no longer exists -- its logic was folded into commands/world-state.ts's /cockpit command) so
// the sort/color/truncation rules are unit-testable without a readline/REPL harness. Every
// function here is pure: given an EmberWorldState (or a Claim[]/string), it returns data or
// strings -- no I/O, no process.stdout, no console.log. The caller (commands/world-state.ts's
// /cockpit command) decides whether color is enabled and does the actual printing.
//
// Status is not a separate field on Claim (Claim is shared by monitor/understand/interact and
// stays untouched) -- the adapter always formats a monitor condition's detail as
// "${status}: ${reason}" (core/ember-world-state.ts), so splitStatusAndReason parses it back out
// on the first ": " rather than adding a new field to the shared Claim shape.

import type { Claim, EmberWorldState, BoardConditionTransition } from "./ember-world-state.ts";
import { formatReceiptAge, isReceiptStale } from "./receipt-age.ts";
import { color as tokenColor } from "../components/design-system.ts";

// ---------------------------------------------------------------------------
// ANSI color codes
// ---------------------------------------------------------------------------

export const ANSI = {
  reset: "\x1b[0m",
  green: "\x1b[32m",
  red: "\x1b[31m",
  yellow: "\x1b[33m",
  cyan: "\x1b[36m",
  dim: "\x1b[2m",
} as const;

/** Whether ANSI color should be emitted: a real TTY and NO_COLOR unset (checked by the caller). */
export function colorEnabledFor(isTTY: boolean | undefined, env: Record<string, string | undefined>): boolean {
  return Boolean(isTTY) && !env.NO_COLOR;
}

// ---------------------------------------------------------------------------
// Status parsing
// ---------------------------------------------------------------------------

export interface StatusReason {
  status: string;
  reason: string;
}

/** Splits a Claim.detail of the form "STATUS: reason text..." on the FIRST ": ". */
export function splitStatusAndReason(detail: string): StatusReason {
  const idx = detail.indexOf(": ");
  if (idx === -1) return { status: "", reason: detail };
  return { status: detail.slice(0, idx), reason: detail.slice(idx + 2) };
}

/** True for the literal "GREEN" status only -- everything else (RED, any AUDIT-* variant, or an
 * unrecognized status) is treated as not-green for sorting and coloring purposes. */
export function isGreenStatus(status: string): boolean {
  return status === "GREEN";
}

export interface StatusGlyph {
  glyph: string; // fixed 3-char width so the CONDITION column stays aligned
  color: string; // ANSI code, or "" for no color (unknown status, rendered plain)
}

export function statusGlyph(status: string): StatusGlyph {
  if (status === "GREEN") return { glyph: "[G]", color: ANSI.green };
  if (status === "RED") return { glyph: "[R]", color: ANSI.red };
  if (status.startsWith("AUDIT-")) return { glyph: "[A]", color: ANSI.yellow };
  return { glyph: "[?]", color: "" };
}

// ---------------------------------------------------------------------------
// Truncation
// ---------------------------------------------------------------------------

const HARD_LIMIT = 110;
const SENTENCE_MIN = 40;

/**
 * Sentence-aware truncation: leaves `reason` untouched if it already fits within HARD_LIMIT.
 * Otherwise looks for the first ". " at or past SENTENCE_MIN chars in and cuts there (inclusive
 * of the period, no ellipsis -- it's a real sentence boundary) as long as that cut point is still
 * within HARD_LIMIT; if no such sentence break exists (or it lands past HARD_LIMIT), falls back
 * to a hard cut at HARD_LIMIT chars with an ellipsis. Truncation always happens on the raw text
 * before any ANSI wrapping is applied by the caller, so it can never land mid-escape-code.
 */
export interface TruncateReasonOptions {
  /** When true, the hard-cut fallback breaks at the last word boundary that fits instead of
   * slicing mid-token (B7 gate ask, 2026-07-03: the welcome-screen attention feed truncated mid-
   * word into a raw fragment). Default false preserves the original behavior for existing callers
   * (the full /monitor panel), so this is opt-in, not a change to truncateReason's default. */
  wordSafeFallback?: boolean;
}

export function truncateReason(
  reason: string,
  hardLimit: number = HARD_LIMIT,
  sentenceMin: number = SENTENCE_MIN,
  opts: TruncateReasonOptions = {},
): string {
  const text = reason.trim();
  if (text.length <= hardLimit) return text;
  const periodIdx = text.indexOf(". ", sentenceMin);
  if (periodIdx !== -1 && periodIdx + 1 <= hardLimit) {
    return text.slice(0, periodIdx + 1);
  }
  if (opts.wordSafeFallback) {
    return truncateAtWordBoundary(text, hardLimit);
  }
  return `${text.slice(0, hardLimit).trimEnd()}…`;
}

/** Cuts `text` at the last space at or before `limit`, so the result never ends mid-word. Falls
 * back to a plain hard cut (same as the non-word-safe path) when no usable space exists in the
 * budget (e.g. a single unbroken token) -- showing as much content as the budget allows still
 * beats an near-empty result. */
function truncateAtWordBoundary(text: string, limit: number): string {
  const slice = text.slice(0, limit);
  const lastSpace = slice.lastIndexOf(" ");
  const cut = lastSpace > 0 ? slice.slice(0, lastSpace) : slice;
  return `${cut.trimEnd()}…`;
}

// ---------------------------------------------------------------------------
// Sorting -- not-GREEN rows first, GREEN rows last; stable within each group
// ---------------------------------------------------------------------------

/**
 * Returns a NEW array (never mutates the input) ordered not-GREEN-first, GREEN-last, stable
 * within each group. This is the single source of truth for "monitor" display order -- both the
 * rendered list and the evidence/act index resolver for the "monitor" surface must use this same
 * function so a printed `[n]` always resolves to the row the operator is looking at.
 */
export function sortMonitorConditions(claims: Claim[]): Claim[] {
  return claims
    .map((claim, originalIndex) => ({ claim, originalIndex }))
    .sort((a, b) => {
      const aGreen = isGreenStatus(splitStatusAndReason(a.claim.detail).status) ? 1 : 0;
      const bGreen = isGreenStatus(splitStatusAndReason(b.claim.detail).status) ? 1 : 0;
      if (aGreen !== bGreen) return aGreen - bGreen;
      return a.originalIndex - b.originalIndex;
    })
    .map(({ claim }) => claim);
}

// ---------------------------------------------------------------------------
// Condition name (from Claim.id, e.g. "board.C-SCALE" -> "C-SCALE")
// ---------------------------------------------------------------------------

export function conditionName(claim: Claim): string {
  return claim.id.replace(/^board\./, "");
}

// ---------------------------------------------------------------------------
// Top-attention lines (B7 item 2: welcome-screen ambient board snapshot)
// ---------------------------------------------------------------------------

/** Compact per-line char budget for a welcome-screen attention entry -- shorter than the full
 * `monitor` panel's own truncateReason limit, since this sits in a narrow feed column, not a
 * full-width panel row. */
const ATTENTION_LINE_REASON_LIMIT = 60;

/** Escapes a string for safe embedding inside a RegExp source. */
function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * B7 gate ask (operator regrade 2026-07-03): rendered verbatim as "C0: AUDIT-INCIDENT —
 * AUDIT-INCIDENT C0: 4 Ember loop receipt(s) cited in window >…" -- the reason string ITSELF
 * begins with "<STATUS> <ID>: ", the same label the caller already prepends, so it appeared
 * twice. Strips that leading "^<STATUS>\s+<ID>:?\s*" from `reason`, using the ACTUAL status/id
 * values for this condition (not a hardcoded pattern), so it generalizes to any status/id pair
 * that happens to restate itself in the reason text. A no-op when the reason doesn't carry it.
 */
export function stripRedundantStatusIdPrefix(reason: string, status: string, id: string): string {
  const re = new RegExp(`^${escapeRegex(status)}\\s+${escapeRegex(id)}:?\\s*`);
  return reason.replace(re, "");
}

/** Markers where a reason string crosses over from a human-readable clause into raw shell/path
 * internals (a redirect fragment, an arrow followed by a path, or a bare drive-letter path). Only
 * the EARLIEST match across all markers matters -- everything from that point on is dropped. */
const RAW_INTERNALS_MARKERS: RegExp[] = [
  / >&/,               // shell redirect fragment, e.g. "... >&2 B:\..."
  / -> [A-Za-z]:\\/,    // arrow followed by a drive-letter path
  / [A-Za-z]:\\/,       // bare drive-letter path
];

/**
 * B7 gate ask: the C0 line truncated into "window >…" -- the cut landed mid-way into a raw
 * shell/path fragment (">&<local-exec-root>/tools/ember-cli/scr…" class content) instead of
 * stopping before it. Drops everything from the first raw-internals marker onward, so the
 * welcome surface shows only the human clause -- this runs BEFORE truncation, not as a
 * truncation strategy, since the raw fragment should never appear even if the human clause
 * alone fits the budget.
 */
export function stripRawInternals(reason: string): string {
  let cutIdx = reason.length;
  for (const marker of RAW_INTERNALS_MARKERS) {
    const m = marker.exec(reason);
    if (m && m.index < cutIdx) cutIdx = m.index;
  }
  return reason.slice(0, cutIdx).trimEnd();
}

/**
 * Up to `max` short "<condition>: <status> — <reason>" lines for the not-GREEN conditions only,
 * in the same not-green-first, original-relative-order as sortMonitorConditions -- used to give
 * a fresh/empty session's "Recent activity" feed real substance (the actual top attention rows)
 * instead of a static "No recent activity" placeholder. Returns [] when every condition is GREEN
 * or the list is empty -- never fabricates attention that isn't there.
 *
 * Reason processing pipeline (B7 gate asks, 2026-07-03): strip a redundant self-restated
 * "<STATUS> <ID>: " prefix, drop raw shell/path internals, THEN truncate at a word boundary
 * (never mid-token) if what remains still overflows the line budget.
 */
export function buildTopAttentionLines(conditions: Claim[], max: number): string[] {
  return sortMonitorConditions(conditions)
    .filter((c) => !isGreenStatus(splitStatusAndReason(c.detail).status))
    .slice(0, max)
    .map((c) => {
      const { status, reason } = splitStatusAndReason(c.detail);
      const id = conditionName(c);
      const deduped = stripRedundantStatusIdPrefix(reason, status, id);
      const cleaned = stripRawInternals(deduped);
      const formatted = truncateReason(cleaned, ATTENTION_LINE_REASON_LIMIT, SENTENCE_MIN, { wordSafeFallback: true });
      return `${id}: ${status} — ${formatted}`;
    });
}

// ---------------------------------------------------------------------------
// Board condition transition events (issue #433: GREEN<->RED flips as activity events)
// ---------------------------------------------------------------------------

/**
 * Formats one board condition transition (ember-world-state.ts's diffBoardConditions) as a
 * "Recent activity" feed line, e.g. "board: C(-1) GREEN->RED (27 red / 8 green)" -- the literal
 * example format from issue #433. `counts` is the NEW receipt's totals (the board state AFTER
 * this transition), matching how the welcome-screen badge already reports green/total elsewhere.
 * Colors the line red when the condition just went RED, green when it just went GREEN, and plain
 * for any other status (e.g. an AUDIT-* variant) -- the same statusGlyph color convention used
 * for the full /monitor panel above.
 */
export function formatBoardTransitionEvent(
  transition: BoardConditionTransition,
  counts: { green: number; red: number },
): { text: string; color?: string } {
  const text = `board: ${transition.condition} ${transition.from}->${transition.to} (${counts.red} red / ${counts.green} green)`;
  if (transition.to === "RED") return { text, color: "red" };
  if (transition.to === "GREEN") return { text, color: "green" };
  return { text };
}

// ---------------------------------------------------------------------------
// Full monitor render
// ---------------------------------------------------------------------------

export interface MonitorRenderOptions {
  colorEnabled: boolean;
}

/**
 * Renders the full `monitor` output as an array of lines: a 2-line header, one aligned line per
 * condition (not-GREEN first, then GREEN), and a dim footer pointing at `evidence monitor <n>`.
 */
export function renderMonitor(state: EmberWorldState, opts: MonitorRenderOptions): string[] {
  const { colorEnabled } = opts;
  const sorted = sortMonitorConditions(state.monitor.conditions);
  const total = state.monitor.green + state.monitor.red; // STATE-condition denominator (excludes
  // the standing PROCESS-INVARIANT rows, which never carry GREEN/RED and never enter this count).
  const incidentCount = sorted.filter(
    (c) => splitStatusAndReason(c.detail).status === "AUDIT-INCIDENT",
  ).length;
  const notGreenCount = sorted.filter(
    (c) => !isGreenStatus(splitStatusAndReason(c.detail).status),
  ).length;

  const pctStr = `${state.monitor.pctComplete}%`;
  const header1 = `board ts=${state.monitor.boardTs}  —  ${state.monitor.green}/${total} GREEN (${pctStr})`;
  const header2 = `${incidentCount} audit incident${incidentCount === 1 ? "" : "s"}  ·  ${notGreenCount} of ${sorted.length} rows below need attention`;

  const condWidth = sorted.reduce((max, c) => Math.max(max, conditionName(c).length), 0);

  const rows = sorted.map((claim, idx) => renderConditionLine(idx, claim, condWidth, colorEnabled));

  const footer = colorEnabled
    ? `${ANSI.dim}full forensics: evidence monitor <n>${ANSI.reset}`
    : "full forensics: evidence monitor <n>";

  return [header1, header2, ...rows, footer];
}

function renderConditionLine(idx: number, claim: Claim, condWidth: number, colorEnabled: boolean): string {
  const { status, reason } = splitStatusAndReason(claim.detail);
  const { glyph, color } = statusGlyph(status);
  const truncated = truncateReason(reason);
  const idxStr = `[${idx}]`;
  const condStr = conditionName(claim).padEnd(condWidth);

  if (!colorEnabled) {
    return `${idxStr} ${glyph} ${condStr} ${truncated}`;
  }
  const coloredGlyph = color ? `${color}${glyph}${ANSI.reset}` : glyph;
  const coloredReason = `${ANSI.dim}${truncated}${ANSI.reset}`;
  return `${idxStr} ${coloredGlyph} ${condStr} ${coloredReason}`;
}

// ---------------------------------------------------------------------------
// renderMonitorPanel — bordered-panel wrapper (increment 6 step B)
// ---------------------------------------------------------------------------

/** Converts a "#RRGGBB" hex string (the design-system identity token) to a 24-bit ANSI SGR
 * foreground escape. Local to this file since monitor-render.ts stays framework-independent
 * (raw ANSI strings, no Ink import) while design-system.ts is Ink-native (named/hex color
 * strings consumed by the Text component's own resolver, not raw escapes). */
function hexToAnsi24(hex: string): string {
  const clean = hex.replace(/^#/, "");
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return `\x1b[38;2;${r};${g};${b}m`;
}

export interface MonitorPanelOptions extends MonitorRenderOptions {
  width: number;
  boardTs?: string;  // ISO8601 timestamp of the board receipt
  nowMs?: number;    // Current time in ms, for testing receipt age
}
/**
 * Wraps renderMonitor()'s existing (unchanged, still-tested) lines in a round-cornered bordered
 * panel using the Observatory identity color for the border -- the Step-A mockup3 visual
 * container (state/design-mockups/cockpit-board-training-strip.mockup.ansi.txt) applied to the
 * /cockpit board surface. B4 W3: a content line wider than the available inner width (width - 4)
 * is ellipsis-truncated (ANSI-safe, see truncateAnsiLineToWidth) rather than left whole -- an
 * earlier version deliberately left overlong lines wider than the panel, but that just moved the
 * ragged mid-word cut from here to whatever renders outside the panel (the terminal viewport);
 * mockup3's own rows always fit, so every rendered row must too.
 */
export function renderMonitorPanel(state: EmberWorldState, opts: MonitorPanelOptions): string[] {
  const { colorEnabled, width, boardTs, nowMs } = opts;
  const inner = renderMonitor(state, { colorEnabled });
  const borderColor = hexToAnsi24(tokenColor("identity", "fg", "dark"));
  const warningColor = ANSI.red; // Red for stale badge
  const h = "─".repeat(Math.max(0, width - 2));
  const innerWidth = Math.max(0, width - 4);

  const top    = colorEnabled ? `${borderColor}╭${h}╮${ANSI.reset}` : `╭${h}╮`;
  const bottom = colorEnabled ? `${borderColor}╰${h}╯${ANSI.reset}` : `╰${h}╯`;

  // Build the header line with receipt age if boardTs is provided
  let headerLine = "";
  if (boardTs) {
    const age = formatReceiptAge(boardTs, nowMs);
    const stale = isReceiptStale(boardTs, nowMs);
    const badge = stale ? `${warningColor}STALE${ANSI.reset}` : "board";
    headerLine = `${badge}: ${age}`;
    
    // Ensure the header fits within the inner width
    const headerWidth = visiblePanelWidth(headerLine);
    if (headerWidth > innerWidth) {
      // Truncate the header if it's too long
      headerLine = truncateAnsiLineToWidth(headerLine, innerWidth);
    }
  }

  // Build the body lines with padding
  const bodyLines: string[] = [];
  
  // Add header line if present
  if (headerLine) {
    const contentWidth = visiblePanelWidth(headerLine);
    const padWidth = Math.max(0, innerWidth - contentWidth);
    const padded = `${headerLine}${" ".repeat(padWidth)}`;
    if (!colorEnabled) {
      bodyLines.push(`│ ${padded} │`);
    } else {
      bodyLines.push(`${borderColor}│${ANSI.reset} ${padded} ${borderColor}│${ANSI.reset}`);
    }
  }

  // Add condition lines
  for (const rawLine of inner) {
    const line = visiblePanelWidth(rawLine) > innerWidth
      ? truncateAnsiLineToWidth(rawLine, innerWidth)
      : rawLine;
    const contentWidth = visiblePanelWidth(line);
    const padWidth = Math.max(0, innerWidth - contentWidth);
    const padded = `${line}${" ".repeat(padWidth)}`;
    if (!colorEnabled) {
      bodyLines.push(`│ ${padded} │`);
    } else {
      bodyLines.push(`${borderColor}│${ANSI.reset} ${padded} ${borderColor}│${ANSI.reset}`);
    }
  }

  return [top, ...bodyLines, bottom];
}

/** Visible-cell width of a string: strips ANSI SGR escapes first, then counts Unicode codepoints
 * (not UTF-16 code units) so glyphs are measured by their real 1-cell terminal width, matching the
 * @xterm/headless verification done during the Step-A mockup pass. */
export function visiblePanelWidth(s: string): number {
  const stripped = s.replace(/\x1b\[[0-9;]*m/g, "");
  return [...stripped].length;
}

/**
 * B4 W3: ANSI-aware ellipsis truncation for a colored monitor-board row. renderMonitorPanel used
 * to leave an overlong line whole ("the bordered row then simply runs wider than `width`"), on
 * the theory that never cutting content mid-character was safer than a naive slice -- but a row
 * left wider than the panel just gets clipped raggedly mid-word by whatever sits outside (the
 * transcript/terminal viewport), which is worse, not safer (mockup3's own rows always fit).
 * Walks the string counting only VISIBLE cells (skipping over \x1b[...m sequences entirely so an
 * escape is never split), stops at maxWidth-1 visible cells, appends an ellipsis, and always
 * emits a trailing reset so a color span cut mid-span can never bleed into the padding/border
 * that follows (same discipline as D1's ANSI-truncation fix in message-renderers.ts).
 */
export function truncateAnsiLineToWidth(line: string, maxWidth: number): string {
  if (maxWidth <= 0) return "";
  if (visiblePanelWidth(line) <= maxWidth) return line;
  if (maxWidth === 1) return "…";

  const budget = maxWidth - 1; // reserve one cell for the ellipsis
  let out = "";
  let visible = 0;
  let sawEscape = false;
  let i = 0;
  while (i < line.length && visible < budget) {
    if (line[i] === "\x1b" && line[i + 1] === "[") {
      const end = line.indexOf("m", i);
      if (end !== -1) {
        out += line.slice(i, end + 1);
        sawEscape = true;
        i = end + 1;
        continue;
      }
    }
    out += line[i];
    visible++;
    i++;
  }
  return sawEscape ? `${out}…${ANSI.reset}` : `${out}…`;
}
