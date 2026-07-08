// logo-homescreen.ts — welcome/homescreen layout: logo, greeting, feeds, channels notice.
// Bundle: components/logo-homescreen.ts (line 321680)
//
// D4 reconstruction (ember #168): commit 5f1b7e5 (#160) landed the flame-era test battery
// (logo-homescreen.test.ts, homescreen-border-clip.test.ts, homescreen-fireball-live-tick.test.ts,
// homescreen-mock1-parity.test.ts) against a rewritten Homescreen that never itself landed. This
// rebuilds that module against those four files as the binding spec -- each file's own docstrings
// (B2/B3/B4/B5/B7/D3/D4 increments) carry the provenance of every requirement below; the tests are
// authoritative over this file's comments if the two ever disagree.
//
// The single outer titled panel (D4) replaces the old per-WelcomeV2 border entirely -- that was
// the root cause of the B2 corner-clip bug (WelcomeV2's own width exceeded its parent leftCol's
// width in row-flex mode). WelcomeV2/LogoV2 remain exported and unit-tested standalone, but
// Homescreen no longer nests them: its D4 composition needs the wordmark/tagline/model/cwd text
// reachable by a plain recursive walk over `.props.children` (the direct-call introspection
// technique every D4 test uses), which only works through Box/Text leaves, not through a further
// custom component that would need re-invoking to see inside (FeedComponent is the one exception
// callers already re-invoke explicitly, same as this file's own tests do).

import React from "react";
import { Box, Text, RawAnsi } from "../ink/components.ts";
import { color, type FeatureFlags } from "./design-system.ts";
import { renderFireballLines, FIREBALL_IDLE_POSE_FRAME } from "./fireball.ts";
import { formatReceiptAge, isReceiptStale } from "../core/receipt-age.ts";

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

export const LEFT_PANEL_MAX_WIDTH = 50;
export const CONDENSED_LOGO_MIN   = 20;
export const WELCOME_THRESHOLD    = 58;

/** D4 (team-lead: "perfect -- keep it verbatim"). */
export const IDENTITY_TAGLINE = "inference + training, on this machine";
/** D4: ember-native onboarding hint, replacing the generic-agent phrasing team-lead flagged. */
const NATIVE_HINT = `Try "what changed on the board today?"`;
/** Column gap between the fireball raster and the identity text beside it. */
const FIREBALL_GUTTER = "   ";
/** B4 W1: mock1's real truecolor accent for "Local" -- never the dim ANSI-16 "green" literal. */
const LOCAL_ACCENT_COLOR = "#4EC9A3";
/** Safe text budget for the identity block's variable-length lines (tagline/cwd; model gets a
 * further-reduced budget below to leave room for its fixed " · Local" suffix on the same row). */
const LEFT_TEXT_WIDTH = 40;

/** The identity block's actual column claim in row-flex layout -- matches rightColWidth's own
 * leftCol-share assumption exactly (Math.max(LEFT_PANEL_MAX_WIDTH, WELCOME_THRESHOLD)), so leftCol
 * + rightCol always sum to the panel's content width with no gap and no overlap. */
const LEFT_COL_WIDTH = Math.max(LEFT_PANEL_MAX_WIDTH, WELCOME_THRESHOLD);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LogoState {
  releaseNotesVisible?: boolean;
  onboardingActive?:    boolean;
  forceFullLogo?:       boolean;
  channelsAuth?:        boolean;
  channelsBlocked?:     boolean;
  model?:               string;
  cwd?:                 string;
  version?:             string;
  /** Standard CLI version-nudge row -- only rendered when a newer version is actually known. */
  updateAvailable?:     string;
  /** Data root path indicator (issue #303: visible indicator of which tree's data is being read). */
  dataRoot?:            string;
}

export interface FeedEntry {
  text:   string;
  /** Ink `<Text color>` value (e.g. "red") -- optional, plain entries carry none. */
  color?: string;
}

export interface Feed {
  title:   string;
  entries: FeedEntry[];
  footer?: string;
}

export type ChannelsPhase = "disabled" | "no-auth" | "policy-blocked" | "listening";

/** Real board substance for the recent-activity feed (B7 item 2: kill the void -- never a fake
 * placeholder, only ever what's actually been fetched). */
export interface BoardSummary {
  green:        number;
  total:        number;
  pctComplete:  number;
  topAttention: string[];
  /** ISO8601/receipt-format timestamp of the board receipt this summary was built from -- optional
   * so existing callers (and older serialized messages, see screens/repl.ts's Homescreen
   * boardSummary handoff) without it still render, just without the age badge below. */
  boardTs?:     string;
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function condensedLogoWidth(viewportWidth: number): number {
  return Math.max(CONDENSED_LOGO_MIN, viewportWidth - 15);
}

/** #413 (cockpit liveness): HH:MM:SS local time, formatted fresh at call time -- `nowMs` defaults
 *  to Date.now() (never memoized), so every genuine re-render shows the real current second. A
 *  dead process (a terminal pane surviving on a frozen last frame after the binary exited) freezes
 *  this exact text forever -- that is the entire detection mechanism: the clock only advances
 *  because screens/repl.ts's unconditional per-second tick keeps forcing real render cycles. */
export function formatWallClock(nowMs: number = Date.now()): string {
  const d = new Date(nowMs);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function shouldShowFullLogo(state: LogoState): boolean {
  return !!(state.releaseNotesVisible || state.onboardingActive || state.forceFullLogo);
}

export function channelsNoticePhase(state: LogoState, flags: FeatureFlags): ChannelsPhase {
  if (!flags.KAIROS || !flags.KAIROS_CHANNELS) return "disabled";
  if (!state.channelsAuth)                      return "no-auth";
  if (state.channelsBlocked)                    return "policy-blocked";
  return "listening";
}

/** Word-boundary-aware clip (issue #44 / §8g item 1): never severs mid-word -- cuts back to the
 * last whitespace boundary within budget, falling back to a raw codepoint clip only when a single
 * word alone exceeds the whole width (never empty, never throws). */
export function clipToWidth(text: string, width: number): string {
  if (width <= 0) return "";
  const chars = [...text];
  if (chars.length <= width) return text;
  if (width === 1) return "…";

  const budget = chars.slice(0, width - 1);
  let lastSpace = -1;
  for (let i = budget.length - 1; i >= 0; i--) {
    if (/\s/.test(budget[i]!)) { lastSpace = i; break; }
  }
  if (lastSpace > 0) return budget.slice(0, lastSpace).join("") + "…";
  return budget.join("") + "…";
}

/** B5 W6: the right column's available content width -- the full panel content width when
 * stacked (rightCol isn't sharing a row with leftCol), or the remainder after leftCol claims its
 * share when row-flex. Panel content width already accounts for the outer titled panel's own
 * 1-cell border on each side (2 total). Never returns less than 1. */
export function rightColWidth(viewportWidth: number): number {
  const panelContentWidth = Math.max(1, viewportWidth - 2);
  const stacked = viewportWidth < LEFT_PANEL_MAX_WIDTH * 2;
  return stacked ? panelContentWidth : Math.max(1, panelContentWidth - LEFT_COL_WIDTH);
}

// ---------------------------------------------------------------------------
// LogoV2 — condensed or full logo text (standalone; Homescreen's own D4 wordmark
// row is now inlined directly -- see the module docstring for why).
// ---------------------------------------------------------------------------

export interface LogoV2Props {
  viewportWidth: number;
  state:         LogoState;
}

export function LogoV2({ viewportWidth, state }: LogoV2Props): React.ReactElement {
  const useFull = shouldShowFullLogo(state);
  const width   = useFull ? LEFT_PANEL_MAX_WIDTH : condensedLogoWidth(viewportWidth);

  return React.createElement(
    Box, { flexDirection: "column", width },
    React.createElement(
      Text, { key: "logo", bold: true, color: color("identity", "fg", "dark") },
      useFull ? "ember (full)" : "ember",
    ),
  );
}

// ---------------------------------------------------------------------------
// WelcomeV2 — bordered greeting box (standalone; see LogoV2's note above)
// ---------------------------------------------------------------------------

export interface WelcomeV2Props {
  greeting?:      string;
  theme?:         string;
  viewportWidth?: number;
}

export function WelcomeV2({
  greeting      = "Welcome back!",
  theme         = "dark",
  viewportWidth = 80,
}: WelcomeV2Props): React.ReactElement {
  const compact     = viewportWidth < WELCOME_THRESHOLD;
  const borderStyle = (
    theme === "apple-terminal" ? "classic" :
    theme === "light"          ? "single"  :
    "round"
  ) as "classic" | "single" | "round";
  const resolvedTheme = theme === "light" ? "light" : "dark";

  return React.createElement(
    Box,
    {
      flexDirection: "column",
      borderStyle,
      borderColor: color("identity", "fg", resolvedTheme),
      width: compact ? undefined : WELCOME_THRESHOLD,
    },
    React.createElement(Text, { key: "greeting", bold: true }, greeting),
  );
}

// ---------------------------------------------------------------------------
// FeedComponent — titled list with an exact-width underline rule and optional
// footer line, all clipped to the caller's available width (B5 W6).
// ---------------------------------------------------------------------------

function titleUnderline(title: string): string {
  return "─".repeat([...title].length);
}

export interface FeedComponentProps {
  feed:   Feed;
  width?: number;
}

export function FeedComponent({ feed, width }: FeedComponentProps): React.ReactElement {
  const clip = (s: string): string => (width === undefined ? s : clipToWidth(s, width));

  return React.createElement(
    Box, { flexDirection: "column", width },
    React.createElement(Text, { key: "title", bold: true }, feed.title),
    React.createElement(Text, { key: "underline", dimColor: true }, titleUnderline(feed.title)),
    ...feed.entries.map((e, i) =>
      React.createElement(Text, { key: String(i), color: e.color }, clip(e.text)),
    ),
    feed.footer
      ? React.createElement(Text, { key: "footer", dimColor: true }, clip(feed.footer))
      : null,
  );
}

// ---------------------------------------------------------------------------
// ChannelsNotice — auth/policy/listening state indicator
// ---------------------------------------------------------------------------

export interface ChannelsNoticeProps {
  state: LogoState;
  flags: FeatureFlags;
}

export function ChannelsNotice({ state, flags }: ChannelsNoticeProps): React.ReactElement | null {
  const phase = channelsNoticePhase(state, flags);
  if (phase === "disabled") return null;

  const labels: Record<Exclude<ChannelsPhase, "disabled">, string> = {
    "no-auth":        "Channels: not authenticated",
    "policy-blocked": "Channels: blocked by org policy",
    "listening":      "Channels: listening",
  };

  return React.createElement(
    Box, { flexDirection: "row" },
    React.createElement(
      Text, { key: "msg", color: phase === "listening" ? "green" : "yellow" },
      labels[phase as Exclude<ChannelsPhase, "disabled">],
    ),
  );
}

// ---------------------------------------------------------------------------
// Recent-activity feed content (B7 item 2: kill the void -- real board substance
// when available, the honest placeholder when not; never fabricates either way)
// ---------------------------------------------------------------------------

/** #404/#405: the boot-screen board line now carries the same receipt-age badge as the /cockpit
 * (/board) path -- "board: <age>" when fresh, red "STALE: <age>" past receipt-age.ts's threshold --
 * built from the SAME formatReceiptAge/isReceiptStale primitives so the semantics never drift
 * between the two surfaces. Silent (no badge line) when boardSummary carries no boardTs, matching
 * this function's existing never-fabricate posture. */
function recentFeedEntries(boardSummary?: BoardSummary, nowMs: number = Date.now()): FeedEntry[] {
  // #413: liveness clock -- always the first line, regardless of whether board data has loaded
  // yet (liveness must be visible from the very first frame, never gated on board data arriving).
  // Same style token as the line below it: plain text, no color -- "no new colors" per spec.
  const entries: FeedEntry[] = [{ text: `clock: ${formatWallClock(nowMs)}` }];
  if (!boardSummary) {
    entries.push({ text: "No recent activity" });
    return entries;
  }
  entries.push(
    { text: `${boardSummary.green}/${boardSummary.total} GREEN (${boardSummary.pctComplete}%)` },
  );
  if (boardSummary.boardTs) {
    const stale = isReceiptStale(boardSummary.boardTs, nowMs);
    const age = formatReceiptAge(boardSummary.boardTs, nowMs);
    entries.push(
      stale ? { text: `STALE: ${age}`, color: "red" } : { text: `board: ${age}` },
    );
  }
  for (const line of boardSummary.topAttention) entries.push({ text: line });
  return entries;
}

// ---------------------------------------------------------------------------
// Homescreen — root welcome/status composite
// ---------------------------------------------------------------------------

export interface HomescreenProps {
  state:          LogoState;
  flags?:         FeatureFlags;
  viewportWidth?: number;
  /** Live animation clock for the identity block's Fireball (b14 item 2 reframe): the welcome
   * screen no longer freezes at a static pose -- the caller's own tick (the same clock driving the
   * bottom-chrome fireball) threads straight through. Defaults to 0 for callers that don't yet
   * carry a tick (e.g. the current screens/repl.ts welcome-message call site). */
  fireballTick?:  number;
  /** Real board substance for the recent-activity feed; omitted -> the honest placeholder. */
  boardSummary?:  BoardSummary;
  /** #413: liveness-clock input, current wall-clock ms. Defaults to Date.now() at call time
   *  (never memoized) -- tests pass a fixed value for determinism; real callers never need to. */
  nowMs?:         number;
}

/** D4: the fireball's raster lines interleaved 1:1 with the identity block's own text lines
 * (wordmark+version, tagline, model+Local, cwd) -- each terminal row pairs one fireball line with
 * one identity line, instead of a plain side-by-side row that would let the taller of the two
 * dangle empty space below the shorter. Row count is the max of the two lists (not just the
 * fireball's), so degraded (EMBER_ASCII / non-color) single-line fireball output never silently
 * drops the tagline/model/cwd rows -- only the color-art rendering shrinks, identity content never
 * does. */
function renderIdentityBlock(state: LogoState, fireballTick: number): React.ReactElement {
  const ascii = process.env["EMBER_ASCII"] === "1";
  const fireballLines = renderFireballLines("panel", "idle", fireballTick, { ascii, color: !ascii });
  const version2 = state.version ?? "0.0.0";

  const identityLines: Array<React.ReactElement | null> = [
    React.createElement(
      Box, { key: "l0", flexDirection: "row" },
      React.createElement(
        Text, { bold: true, color: color("identity", "fg", "dark") }, "ember",
      ),
      React.createElement(Text, { dimColor: true }, `  v${version2}`),
    ),
    React.createElement(
      Text, { key: "l1", dimColor: true }, clipToWidth(IDENTITY_TAGLINE, LEFT_TEXT_WIDTH),
    ),
    state.model
      ? React.createElement(
          Box, { key: "l2", flexDirection: "row" },
          React.createElement(
            Text, null, clipToWidth(state.model, Math.max(1, LEFT_TEXT_WIDTH - 8)),
          ),
          // B4 W1: mock1's real truecolor accent, never the dim ANSI-16 "green" literal.
          React.createElement(Text, { color: LOCAL_ACCENT_COLOR }, " \xB7 Local"),
        )
      : null,
    state.cwd
      ? React.createElement(Text, { key: "l3", dimColor: true }, clipToWidth(state.cwd, LEFT_TEXT_WIDTH))
      : null,
    // #303: visible data-root indicator — a disconnected cockpit is immediately self-evident.
    state.dataRoot
      ? React.createElement(Text, { key: "l4", dimColor: true }, clipToWidth(`Data: ${state.dataRoot}`, LEFT_TEXT_WIDTH))
      : null,
  ];

  const rowCount = Math.max(fireballLines.length, identityLines.length);
  const rows = Array.from({ length: rowCount }, (_, i) =>
    React.createElement(
      Box, { key: `row${i}`, flexDirection: "row" },
      React.createElement(RawAnsi, null, fireballLines[i] ?? ""),
      React.createElement(Text, null, FIREBALL_GUTTER),
      identityLines[i] ?? null,
    ),
  );

  return React.createElement(Box, { flexDirection: "column" }, ...rows);
}

export function Homescreen({
  state,
  flags         = {},
  viewportWidth = 80,
  fireballTick  = FIREBALL_IDLE_POSE_FRAME,
  boardSummary,
  nowMs         = Date.now(),
}: HomescreenProps): React.ReactElement {
  const leftCol = React.createElement(
    Box, { key: "left", flexDirection: "column", width: LEFT_COL_WIDTH },
    state.updateAvailable
      ? React.createElement(
          Text, { key: "update", dimColor: true },
          `Update available: v${state.updateAvailable} (run /update)`,
        )
      : null,
    renderIdentityBlock(state, fireballTick),
  );

  const onboardingFeed: Feed = {
    title:   "Tips for getting started",
    entries: [
      { text: "Run /init to create an EMBER.md file with instructions for Ember" },
      { text: NATIVE_HINT },
    ],
  };
  const recentFeed: Feed = {
    title:   "Recent activity",
    entries: recentFeedEntries(boardSummary, nowMs),
    footer:  "/resume for more",
  };

  const rcWidth = rightColWidth(viewportWidth);
  const rightCol = React.createElement(
    Box, { key: "right", flexDirection: "column", width: rcWidth },
    React.createElement(FeedComponent, { key: "onboarding", feed: onboardingFeed, width: rcWidth }),
    React.createElement(FeedComponent, { key: "recent",     feed: recentFeed,     width: rcWidth }),
  );

  // D4: one outer titled panel wraps the whole hero -- replaces WelcomeV2's own border entirely
  // (the B2 root cause: a child border wider than its parent leftCol clipped in row-flex mode).
  const panelIsRow  = viewportWidth >= LEFT_PANEL_MAX_WIDTH * 2;
  const panelWidth  = panelIsRow
    ? LEFT_COL_WIDTH + rcWidth + 2
    : Math.max(LEFT_COL_WIDTH, rcWidth) + 2;
  const panel = React.createElement(
    Box,
    {
      key:           "panel",
      flexDirection: panelIsRow ? "row" : "column",
      width:         panelWidth,
      borderStyle:   "round",
      borderColor:   color("identity", "fg", "dark"),
      borderTitle:   "ember",
    },
    leftCol,
    rightCol,
    React.createElement(ChannelsNotice, { key: "channels", state, flags }),
  );

  return React.createElement(Box, { flexDirection: "column" }, panel);
}
