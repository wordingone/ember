// logo-homescreen.ts — welcome/homescreen layout: logo, greeting, feeds, channels notice.
// Bundle: components/logo-homescreen.ts (line 321680)

import React from "react";
import { Box, Text } from "../ink/components.ts";
import type { FeatureFlags } from "./design-system.ts";

// ---------------------------------------------------------------------------
// Constants (spec — preserve exactly)
// ---------------------------------------------------------------------------

export const LEFT_PANEL_MAX_WIDTH = 50;
export const CONDENSED_LOGO_MIN   = 20;
export const WELCOME_THRESHOLD    = 58;

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
}

export interface FeedEntry { text: string; }

export interface Feed {
  title:   string;
  entries: FeedEntry[];
  footer?: string;
}

export type ChannelsPhase = "disabled" | "no-auth" | "policy-blocked" | "listening";

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function condensedLogoWidth(viewportWidth: number): number {
  return Math.max(CONDENSED_LOGO_MIN, viewportWidth - 15);
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

// ---------------------------------------------------------------------------
// LogoV2 — condensed or full logo text
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
      Text, { key: "logo", bold: true, color: "cyan" },
      useFull ? "ember (full)" : "ember",
    ),
  );
}

// ---------------------------------------------------------------------------
// WelcomeV2 — bordered greeting box
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

  return React.createElement(
    Box,
    { flexDirection: "column", borderStyle, width: compact ? undefined : WELCOME_THRESHOLD },
    React.createElement(Text, { key: "greeting", bold: true }, greeting),
  );
}

// ---------------------------------------------------------------------------
// FeedComponent — titled list with optional footer line
// ---------------------------------------------------------------------------

export interface FeedComponentProps {
  feed:   Feed;
  width?: number;
}

export function FeedComponent({ feed, width }: FeedComponentProps): React.ReactElement {
  return React.createElement(
    Box, { flexDirection: "column", width },
    React.createElement(Text, { key: "title", bold: true }, feed.title),
    ...feed.entries.map((e, i) =>
      React.createElement(Text, { key: String(i) }, e.text),
    ),
    feed.footer
      ? React.createElement(Text, { key: "footer", dimColor: true }, feed.footer)
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
// Homescreen — root welcome/status composite
// ---------------------------------------------------------------------------

export interface HomescreenProps {
  state:          LogoState;
  flags?:         FeatureFlags;
  viewportWidth?: number;
}

export function Homescreen({
  state,
  flags         = {},
  viewportWidth = 80,
}: HomescreenProps): React.ReactElement {
  const version2 = state.version ?? "0.0.0";

  const leftCol = React.createElement(
    Box, { key: "left", flexDirection: "column", width: LEFT_PANEL_MAX_WIDTH },
    React.createElement(Text, { key: "version", dimColor: true }, `Ember CLI v${version2}`),
    React.createElement(WelcomeV2, { key: "welcome", viewportWidth }),
    React.createElement(LogoV2,    { key: "logo",    viewportWidth, state }),
    state.model
      ? React.createElement(Text, { key: "model" }, `${state.model} \xB7 Local`)
      : null,
    state.cwd
      ? React.createElement(Text, { key: "cwd", dimColor: true }, state.cwd)
      : null,
  );

  const onboardingFeed: Feed = {
    title:   "Tips for getting started",
    entries: [{ text: "Run /init to create an EMBER.md file with instructions for Ember" }],
  };
  const recentFeed: Feed = {
    title:   "Recent activity",
    entries: [{ text: "No recent activity" }],
    footer:  "/resume for more",
  };

  const rightCol = React.createElement(
    Box, { key: "right", flexDirection: "column" },
    React.createElement(FeedComponent, { key: "onboarding", feed: onboardingFeed }),
    React.createElement(FeedComponent, { key: "recent",     feed: recentFeed }),
  );

  if (viewportWidth < LEFT_PANEL_MAX_WIDTH * 2) {
    return React.createElement(
      Box, { flexDirection: "column" },
      leftCol,
      rightCol,
      React.createElement(ChannelsNotice, { key: "channels", state, flags }),
    );
  }

  return React.createElement(
    Box, { flexDirection: "row" },
    leftCol,
    rightCol,
    React.createElement(ChannelsNotice, { key: "channels", state, flags }),
  );
}
