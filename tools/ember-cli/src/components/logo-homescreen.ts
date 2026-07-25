// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

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
import type { RegistryCommand } from "../types/command-types.ts";
import { buildSpineRows, renderSpineBlock } from "./spine-first-screen.ts";
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
 * further-reduced budget below to leave room for its fixed " · Local" suffix on the same row).
 * This is a CEILING, not a fixed allowance — see identityTextWidth below (legibility bar,
 * 2026-07-26): at narrow terminal widths the identity column claims less than this, and every
 * caller used to clip against the ceiling regardless, so clipToWidth reported "fits" for a cwd
 * path shorter than 40 chars while the actual on-screen column was narrower still — the outer
 * renderer then silently hard-clipped it with no marker at all. */
const LEFT_TEXT_WIDTH = 40;

/** The identity block's actual usable text width at a given terminal width — never wider than
 * LEFT_TEXT_WIDTH, and never wider than what the terminal can actually show once the fireball
 * raster + gutter share the same row (identityLines sit beside FIREBALL_GUTTER, not the full
 * viewport). Floors at 8 so a pathological tiny terminal still gets *something* legible rather
 * than a zero-width budget. */
function identityTextWidth(viewportWidth: number): number {
  return Math.max(8, Math.min(LEFT_TEXT_WIDTH, viewportWidth - 4));
}

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
  /** #433: formatted board condition-transition events ("board: C(-1) GREEN->RED (27 red / 8
   * green)"), newest first, from services/board-ts-poller.ts's live poll. Optional so existing
   * callers without any detected transitions yet still render, just without this section. */
  recentTransitions?: Array<{ text: string; color?: string }>;
  /** #447: one-shot cockpit self-restart event ("cockpit: relaunched after 26m gap (pid P1 ->
   * P2)"), computed once at mount from the previous session's liveness-heartbeat row (see
   * screens/repl.ts). Absent on a normal boot (no prior heartbeat, or no meaningful gap) -- an
   * "an hour of real organism work rendered as idleness" incident is exactly what this answers:
   * the pane's own downtime is now a visible fact, not silence. */
  cockpitRestartEvent?: { text: string; color?: string };
  /** #447: live-state strip -- GPU state (VRAM + compute classification), the newest active
   * training/inference run's phase, and the last-receipt-landing age. Each line is pre-formatted
   * upstream by its own poller (services/gpu-state-poller.ts, services/run-progress-scanner.ts,
   * services/receipt-landing-poller.ts) -- this component only ever renders strings, never
   * re-derives the formatting. Any absent field renders nothing, same never-fabricate discipline
   * as boardTs/topAttention below. */
  liveTelemetry?: {
    gpu?: { text: string; color?: string };
    activeRun?: { text: string; color?: string };
    lastReceipt?: { text: string; color?: string };
  };
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

/** Shortens a filesystem path to its last two segments with a leading ellipsis marker once the
 *  full path doesn't fit `budget` — the tail of a path (its deepest directories) is what actually
 *  identifies which tree/worktree is active, so this drops the FRONT and keeps the back, same
 *  direction shortenDataRootForDisplay below already uses for the "Data:" line. Legibility bar
 *  (2026-07-26): "paths truncate from the left with a marker, consistently everywhere" — before
 *  this, the cwd line had no path-aware shortening at all and relied on clipToWidth's generic
 *  word-boundary clip (which drops the TAIL, the wrong end for a path). Short paths that already
 *  fit are returned untouched. */
export function shortenPathForDisplay(fullPath: string, budget: number): string {
  if ([...fullPath].length <= budget) return fullPath;
  const sep = fullPath.includes("\\") ? "\\" : "/";
  const segments = fullPath.split(/[\\/]/).filter((s) => s.length > 0);
  if (segments.length <= 2) return fullPath;
  return `…${sep}${segments.slice(-2).join(sep)}`;
}

/** #303 narrow-viewport fix: `Data: <path>` collapsed to a bare "Data:…" at LEFT_TEXT_WIDTH --
 * clipToWidth's word-boundary clip finds the ONE space in the "Data: " label itself (a filesystem
 * path has no spaces at all) and cuts everything after it, same failure class as the #447 `run:`
 * line's narrow-viewport collapse. Fix: when the full `Data: <path>` label doesn't fit, shorten
 * the PATH to its last two segments with a leading ellipsis (still identifies which tree/worktree
 * is active -- the #303 comment's actual purpose, "a disconnected cockpit is immediately
 * self-evident") *before* clipToWidth ever sees it; clipToWidth remains the final safety net for
 * pathological cases. Short paths that already fit are returned untouched -- never lossy when
 * there's room to show the real path in full. */
export function shortenDataRootForDisplay(fullPath: string, budget: number): string {
  const fullLabel = `Data: ${fullPath}`;
  if ([...fullLabel].length <= budget) return fullPath;
  const sep = fullPath.includes("\\") ? "\\" : "/";
  const segments = fullPath.split(/[\\/]/).filter((s) => s.length > 0);
  if (segments.length <= 2) return fullPath;
  return `…${sep}${segments.slice(-2).join(sep)}`;
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
  // #447: cockpit self-restart -- "was this pane just resurrected" is the most orienting fact a
  // fresh session can show, so it renders right after the clock and BEFORE the board-data early
  // return below (it doesn't depend on board data at all -- it's a fact about the pane itself).
  if (boardSummary?.cockpitRestartEvent) entries.push(boardSummary.cockpitRestartEvent);
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
  // #447: live-state strip -- GPU/active-run/last-receipt-age, grouped with the board-state
  // lines above (all "what's true right now") and ahead of the discrete event/attention lines
  // below (all "what just happened" / "what needs looking at"). Any absent field renders nothing.
  if (boardSummary.liveTelemetry) {
    const { gpu, activeRun, lastReceipt } = boardSummary.liveTelemetry;
    if (gpu) entries.push(gpu);
    if (activeRun) entries.push(activeRun);
    if (lastReceipt) entries.push(lastReceipt);
  }
  // #433: condition-transition events ("board: C(-1) GREEN->RED (...)") -- what just CHANGED --
  // ahead of topAttention's static "what's currently not-GREEN" snapshot below.
  if (boardSummary.recentTransitions) {
    for (const entry of boardSummary.recentTransitions) entries.push(entry);
  }
  for (const line of boardSummary.topAttention) entries.push({ text: line });
  return entries;
}

// ---------------------------------------------------------------------------
// Homescreen — root welcome/status composite
// ---------------------------------------------------------------------------

/** Path comparison for the launch-root disclosure. Windows gives us backslashes from one source
 *  and forward slashes from another for the same directory, and case differs on drive letters, so
 *  a raw string compare would fire the disclosure on two spellings of one path — a warning that
 *  cries wolf is worse than no warning. Trailing separators are stripped for the same reason. */
export function samePathForDisplay(a: string, b: string): boolean {
  const norm = (p: string) =>
    p.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  return norm(a) === norm(b);
}

/** Change 3: say so, once, plainly, when state is bound somewhere other than where you launched.
 *  Renders nothing when the two agree or when the caller did not supply a launch directory —
 *  silence here means "no discrepancy", which is the only reading that stays honest as callers
 *  are wired up one at a time. */
export function rootDisclosure(
  canonicalRoot: string | undefined,
  launchDir: string | undefined,
): React.ReactElement | null {
  if (!canonicalRoot || !launchDir) return null;
  if (samePathForDisplay(canonicalRoot, launchDir)) return null;
  return React.createElement(
    Text,
    { key: "root-disclosure", dimColor: true },
    clipToWidth(
      `State is bound to ${canonicalRoot}, not the directory you launched from`,
      LEFT_TEXT_WIDTH,
    ),
  );
}

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
  /** Live command registry, for the spine block. Omitted or empty -> six BLOCKED rows, which is
   *  the honest reading: nothing was proven drivable. It never shrinks to fewer rows. */
  spineCommands?: readonly RegistryCommand[] | null;
  /** The directory the operator actually launched from, when it differs from the canonical repo
   *  root the cockpit binds its state to. Change 3 of the spine-on-first-screen spec: the binding
   *  itself is deliberate (utils/repo-root.ts canonicalizeThroughWorktree, issue #666 — "refusing
   *  to bind state paths to a worktree root the watchdog will never poll") and stays. What was
   *  wrong is that the operator was never told: header, data line and watchdog tail all showed the
   *  canonical path, and the one console line that said so scrolled away before the first frame
   *  settled. Undefined, or equal to the canonical root, renders nothing. */
  launchDir?:     string;
}

/** D4: the fireball's raster lines interleaved 1:1 with the identity block's own text lines
 * (wordmark+version, tagline, model+Local, cwd) -- each terminal row pairs one fireball line with
 * one identity line, instead of a plain side-by-side row that would let the taller of the two
 * dangle empty space below the shorter. Row count is the max of the two lists (not just the
 * fireball's), so degraded (EMBER_ASCII / non-color) single-line fireball output never silently
 * drops the tagline/model/cwd rows -- only the color-art rendering shrinks, identity content never
 * does. */
function renderIdentityBlock(state: LogoState, fireballTick: number, viewportWidth: number = 80): React.ReactElement {
  const ascii = process.env["EMBER_ASCII"] === "1";
  const fireballLines = renderFireballLines("panel", "idle", fireballTick, { ascii, color: !ascii });
  const version2 = state.version ?? "0.0.0";
  const textWidth = identityTextWidth(viewportWidth);

  const identityLines: Array<React.ReactElement | null> = [
    React.createElement(
      Box, { key: "l0", flexDirection: "row" },
      React.createElement(
        Text, { bold: true, color: color("identity", "fg", "dark") }, "ember",
      ),
      React.createElement(Text, { dimColor: true }, `  v${version2}`),
    ),
    React.createElement(
      Text, { key: "l1", dimColor: true }, clipToWidth(IDENTITY_TAGLINE, textWidth),
    ),
    state.model
      ? React.createElement(
          Box, { key: "l2", flexDirection: "row" },
          React.createElement(
            Text, null, clipToWidth(state.model, Math.max(1, textWidth - 8)),
          ),
          // B4 W1: mock1's real truecolor accent, never the dim ANSI-16 "green" literal.
          React.createElement(Text, { color: LOCAL_ACCENT_COLOR }, " \xB7 Local"),
        )
      : null,
    state.cwd
      ? React.createElement(
          Text, { key: "l3", dimColor: true },
          clipToWidth(shortenPathForDisplay(state.cwd, textWidth), textWidth),
        )
      : null,
    // #303: visible data-root indicator — a disconnected cockpit is immediately self-evident.
    state.dataRoot
      ? React.createElement(
          Text, { key: "l4", dimColor: true },
          clipToWidth(`Data: ${shortenDataRootForDisplay(state.dataRoot, textWidth)}`, textWidth),
        )
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
  spineCommands,
  launchDir,
}: HomescreenProps): React.ReactElement {
  // D4: one outer titled panel wraps the whole hero -- replaces WelcomeV2's own border entirely
  // (the B2 root cause: a child border wider than its parent leftCol clipped in row-flex mode).
  const panelIsRow  = viewportWidth >= LEFT_PANEL_MAX_WIDTH * 2;
  // R4b (frame geometry, state/operator-pass-2026-07-26.md W2 -- corrected root cause): the
  // homescreen panel's RIGHT border edge (both corners and every vertical side cell) was missing
  // entirely whenever this screen renders beside a right-hand panel (repl.ts's operator-surface
  // pane, mainColumnWidth around 50-60) -- not a content/border row collision at all. leftCol was
  // ALWAYS given the fixed LEFT_COL_WIDTH (58, sized for the wide row-flex case), even in "stacked"
  // (column) mode where leftCol and rightCol stack vertically and each should claim the FULL
  // available content width, exactly like rightColWidth already does dynamically via its own
  // `stacked` branch. So panelWidth's `Math.max(LEFT_COL_WIDTH, rcWidth) + 2` floor came out to
  // 60 at a real 53-wide viewport -- 7 columns wider than the panel's parent ever had to give it --
  // and every downstream write past column 52 (including the closing round corner glyphs and every
  // right-edge vertical bar) silently fell outside the render pipeline's clipRect. Stacked mode's
  // leftCol now claims the SAME dynamic content width as rightCol (viewportWidth - 2, i.e. what
  // rightColWidth already returns for its own `stacked` branch); row mode is unchanged (leftCol
  // keeps the fixed LEFT_COL_WIDTH share it was designed for). identityTextWidth() already clips
  // leftCol's own text well below either width (viewportWidth - 4, floor 8), so narrowing leftCol's
  // BOX width in stacked mode loses no content that wasn't already text-clipped.
  const rcWidth      = rightColWidth(viewportWidth);
  const leftColWidth = panelIsRow ? LEFT_COL_WIDTH : Math.max(1, viewportWidth - 2);

  const leftCol = React.createElement(
    Box, { key: "left", flexDirection: "column", width: leftColWidth },
    rootDisclosure(state.dataRoot, launchDir),
    state.updateAvailable
      ? React.createElement(
          Text, { key: "update", dimColor: true },
          `Update available: v${state.updateAvailable} (run /update)`,
        )
      : null,
    renderIdentityBlock(state, fireballTick, viewportWidth),
  );

  // Change 1 of the spine-on-first-screen spec. The previous entries were
  //   "Run /init to create an EMBER.md file with instructions for Ember"
  //   `Try "what changed on the board today?"`
  // Both are coding-assistant affordances. On a first launch they spent the most valuable real
  // estate on the screen teaching a workflow that is not the spine, while custody, model,
  // checkpoint, benchmark and train appeared nowhere at all. These name the spine instead, in the
  // operator's words, and point at the block below rather than at an internal noun.
  // Changes 1 and 2 of the spine-on-first-screen spec, merged into ONE feed rather than two.
  //
  // The previous entries here were
  //   "Run /init to create an EMBER.md file with instructions for Ember"
  //   `Try "what changed on the board today?"`
  // Both are coding-assistant affordances, and on a first launch they spent the most valuable real
  // estate on the screen teaching a workflow that is not the spine, while custody, model,
  // checkpoint, benchmark and train appeared nowhere at all.
  //
  // Why merged: adding a separate six-row block BELOW the tips box pushed the panel past the
  // bottom of an 80x20 terminal and the border's lower corners went off-screen —
  // homescreen-border-clip.test.ts caught it. The honest response was not to relax that guard; a
  // clipped panel is a real defect for a real operator on a real terminal. It was to notice that
  // once the tips box's only remaining job is to point at the spine, the tips box and the spine
  // block are the same thing. So the onboarding feed IS the spine now: net four lines rather than
  // eight, and the first screen's teaching space finally teaches the product.
  const onboardingFeed: Feed = {
    title:   "Spine — what Ember can be driven to do",
    entries: renderSpineBlock(buildSpineRows(spineCommands), rightColWidth(viewportWidth))
      .map((text) => ({ text })),
    // No footer. It said "type any command shown", which the title already implies and each row
    // demonstrates — and it cost the one row that put the panel at 21 in an 80x20 terminal, which
    // pushed the bottom border off-screen. Measured, not guessed: bottom-border row 21, budget 20.
    //
    // MARGIN WARNING for whoever adds the next line here. The panel now lands at exactly 20 rows
    // at 80x20. There is no slack. One more entry in this feed OR in the recent-activity feed
    // clips the border again, and the failure surfaces as a corner-painting test rather than as
    // anything that mentions height. If you need another line, take one back from somewhere in the
    // same column — do not assume there is room.
  };
  const recentFeed: Feed = {
    title:   "Recent activity",
    entries: recentFeedEntries(boardSummary, nowMs),
    footer:  "/resume for more",
  };

  const rightCol = React.createElement(
    Box, { key: "right", flexDirection: "column", width: rcWidth },
    React.createElement(FeedComponent, { key: "onboarding", feed: onboardingFeed, width: rcWidth }),
    React.createElement(FeedComponent, { key: "recent",     feed: recentFeed,     width: rcWidth }),
  );

  const panelWidth  = panelIsRow
    ? LEFT_COL_WIDTH + rcWidth + 2
    : Math.max(leftColWidth, rcWidth) + 2;
  // R4b (frame geometry, state/operator-pass-2026-07-26.md W2): this panel had no `overflow`
  // declared, so when its own flexShrink allocation from the caller's column layout (repl.ts's
  // "banner" wrapper) came in SHORTER than the panel's natural content height, the panel sized
  // its OWN border to the shrunk height while its children (leftCol/rightCol Text lines) kept
  // laying out every natural row uncapped -- the last content row and the panel's own bottom
  // border then landed on the SAME frame row, the closing corner overwriting into content
  // instead of getting its own row. `overflow:"hidden"` is the same fix already applied to every
  // OTHER box in this codebase that must render a clean border under a shrunk allocation
  // (operator-surface-pane.ts's own body Box, repl.ts's row/column wrappers): content beyond the
  // panel's own interior is clipped, never painted onto the border.
  const panel = React.createElement(
    Box,
    {
      key:           "panel",
      flexDirection: panelIsRow ? "row" : "column",
      width:         panelWidth,
      borderStyle:   "round",
      borderColor:   color("identity", "fg", "dark"),
      borderTitle:   "ember",
      overflow:      "hidden",
    },
    leftCol,
    rightCol,
    React.createElement(ChannelsNotice, { key: "channels", state, flags }),
  );

  return React.createElement(Box, { flexDirection: "column" }, panel);
}
