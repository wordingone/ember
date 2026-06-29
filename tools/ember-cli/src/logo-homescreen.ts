// logo-homescreen.ts — root-level re-export + extended exports for the
// homescreen: upsell panels, animated clawd, channels notice, feed builders.

// Re-export everything from the committed components version.
export {
  LEFT_PANEL_MAX_WIDTH,
  CONDENSED_LOGO_MIN,
  WELCOME_THRESHOLD,
  condensedLogoWidth,
  shouldShowFullLogo,
  channelsNoticePhase,
  LogoV2,
  WelcomeV2,
  ChannelsNotice,
  Homescreen,
  FeedComponent,
} from "./components/logo-homescreen.ts";
export type {
  LogoState,
  ChannelsPhase,
  LogoV2Props,
  WelcomeV2Props,
  HomescreenProps,
  ChannelsNoticeProps,
} from "./components/logo-homescreen.ts";
export type { FeatureFlags } from "./components/design-system.ts";

import React from "react";
import { Box, Text } from "./ink/components.ts";
import type { FeatureFlags } from "./components/design-system.ts";

// ---------------------------------------------------------------------------
// Additional constants (AC1/AC3/AC8/AC9/AC10)
// ---------------------------------------------------------------------------

export const GUEST_PASSES_WIDTH     = 48;
export const GUEST_PASSES_COUNT     = 3;
export const GUEST_PASSES_UPSELL_CAP = 3;
export const OVERAGE_PROMO_CAP      = 3;
export const MODEL_UPGRADE_NOTICE_CAP = 6;
export const VOICE_NOTICE_CAP       = 5;
export const DESKTOP_UPSELL_CAP     = 3;
export const CLAWD_WIDTH            = 9;
export const CLAWD_FRAME_MS         = 60;

// ---------------------------------------------------------------------------
// HomescreenState type (used by several show-guards)
// ---------------------------------------------------------------------------

export interface HomescreenState {
  voiceNoticeSeenCount?:    number;
  modelUpgradeSeenCount?:   number;
  isModelUpgradeEnabled?:   boolean;
  guestPassesSeenCount?:    number;
  hasVisitedPasses?:        boolean;
  overagePromoSeenCount?:   number;
  desktopUpsellSeenCount?:  number;
  platform?:                string;
  channelsAuth?:            boolean;
  channelsBlocked?:         boolean;
}

// ---------------------------------------------------------------------------
// AC3: createGuestPassesFeed
// ---------------------------------------------------------------------------

export interface FeedEntry { text: string; }
export interface Feed { title: string; entries: FeedEntry[]; footer?: string; }

export function createGuestPassesFeed(): Feed {
  const entries: FeedEntry[] = Array.from({ length: GUEST_PASSES_COUNT }, (_, i) =>
    ({ text: `Guest pass ${i + 1}: invite a friend with /invite` }),
  );
  return { title: "Guest passes", entries };
}

// ---------------------------------------------------------------------------
// AC11: createRecentActivityFeed / createWhatsNewFeed
// ---------------------------------------------------------------------------

export function createRecentActivityFeed(entries: FeedEntry[]): Feed {
  return { title: "Recent activity", entries, footer: "/resume for more" };
}

export function createWhatsNewFeed(entries: FeedEntry[]): Feed {
  return { title: "What's new", entries, footer: "/release-notes for more" };
}

// ---------------------------------------------------------------------------
// AC4: shouldShowGuestPassesUpsell
// ---------------------------------------------------------------------------

export function shouldShowGuestPassesUpsell(
  state: { hasVisitedPasses?: boolean; guestPassesSeenCount?: number },
): boolean {
  if (state.hasVisitedPasses) return false;
  const count = state.guestPassesSeenCount ?? 0;
  return count < GUEST_PASSES_UPSELL_CAP;
}

// ---------------------------------------------------------------------------
// AC5/AC6: shouldShowModelUpgradeNotice / shouldShowVoiceModeNotice
// ---------------------------------------------------------------------------

export function shouldShowModelUpgradeNotice(
  state: HomescreenState,
): boolean {
  if (!state.isModelUpgradeEnabled) return false;
  const count = state.modelUpgradeSeenCount ?? 0;
  return count < MODEL_UPGRADE_NOTICE_CAP;
}

export function shouldShowVoiceModeNotice(
  state: HomescreenState,
  flags: FeatureFlags,
): boolean {
  if (!flags["VOICE_MODE"]) return false;
  // Mutual exclusion: if model upgrade notice would show, suppress voice
  if (shouldShowModelUpgradeNotice(state)) return false;
  const count = state.voiceNoticeSeenCount ?? 0;
  return count < VOICE_NOTICE_CAP;
}

// ---------------------------------------------------------------------------
// AC7: shouldShowDesktopUpsell
// ---------------------------------------------------------------------------

export function shouldShowDesktopUpsell(
  state: HomescreenState,
  flags: FeatureFlags,
): boolean {
  if (!flags["enableStartupDialog"]) return false;
  if (state.platform === "linux")    return false;
  const count = state.desktopUpsellSeenCount ?? 0;
  return count < DESKTOP_UPSELL_CAP;
}

// ---------------------------------------------------------------------------
// AC9: shouldShowOveragePromoUpsell
// ---------------------------------------------------------------------------

export function shouldShowOveragePromoUpsell(
  state: { overagePromoSeenCount?: number },
): boolean {
  const count = state.overagePromoSeenCount ?? 0;
  return count < OVERAGE_PROMO_CAP;
}

// ---------------------------------------------------------------------------
// CondensedLogo component
// ---------------------------------------------------------------------------

export interface CondensedLogoProps {
  viewportWidth?: number;
}

export function CondensedLogo(props: CondensedLogoProps): React.ReactElement {
  return React.createElement(
    Text, { bold: true, color: "cyan" },
    "ember",
  );
}

// ---------------------------------------------------------------------------
// GuestPassesUpsell component
// ---------------------------------------------------------------------------

export interface GuestPassesUpsellProps {
  hasVisitedPasses?:    boolean;
  guestPassesSeenCount?: number;
  onVisit?:             () => void;
}

export function GuestPassesUpsell(
  props: GuestPassesUpsellProps,
): React.ReactElement | null {
  if (!shouldShowGuestPassesUpsell(props)) return null;
  const feed = createGuestPassesFeed();
  return React.createElement(
    Box, { flexDirection: "column" },
    React.createElement(Text, { bold: true }, feed.title),
    ...feed.entries.map((e, i) =>
      React.createElement(Text, { key: String(i) }, e.text),
    ),
  );
}

// ---------------------------------------------------------------------------
// OverageCreditUpsell component (AC9)
// ---------------------------------------------------------------------------

export interface OverageCreditUpsellProps {
  persistent:     boolean;
  promoSeenCount: number;
  onDismiss?:     () => void;
}

export function OverageCreditUpsell(
  props: OverageCreditUpsellProps,
): React.ReactElement | null {
  if (!props.persistent && !shouldShowOveragePromoUpsell({ overagePromoSeenCount: props.promoSeenCount })) {
    return null;
  }
  return React.createElement(
    Box, { flexDirection: "column", borderStyle: "single", borderColor: "yellow", padding: 1 },
    React.createElement(Text, { bold: true, color: "yellow" }, "Add credits"),
  );
}

// ---------------------------------------------------------------------------
// AnimatedClawd component (AC10)
// ---------------------------------------------------------------------------

export const CLAWD_PROGRAMS: Record<string, string[]> = {
  JUMP_WAVE:    ["(  ･ω･  )", "( ／  ﾖ  )", "( \\  ﾖ  )", "(  ･ω･  )"],
  LOOK_AROUND:  ["(  ･ω･  )", "( ･ω･  )", "(  ･ω･ )", "(  ･ω･  )"],
};

export interface AnimatedClawdProps {
  program:  keyof typeof CLAWD_PROGRAMS | string;
  tick?:    number;
}

export function AnimatedClawd(props: AnimatedClawdProps): React.ReactElement {
  const frames = CLAWD_PROGRAMS[props.program] ?? CLAWD_PROGRAMS.LOOK_AROUND!;
  const frame  = frames[(props.tick ?? 0) % frames.length]!;
  return React.createElement(Text, null, frame);
}
