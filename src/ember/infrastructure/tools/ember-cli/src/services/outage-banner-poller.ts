// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/outage-banner-poller.ts — issue #475: cockpit status banner for the frozen
// planned-outage.json marker contract (issue #464 comment 4918207339). The liveness
// watchdogs already honor a planned-outage window server-side (verified live: zero
// failure-counting across two outage windows) -- but the cockpit surface just shows the
// model offline with no explanation, indistinguishable from a crash to an operator glancing
// at the pane. This hook is the surface-side half.
//
// Follows circuit-breaker-banner-poller.ts's shape exactly: a thin setInterval/useState
// shell around pure, already-independently-tested logic. The marker parsing + expiry check
// are NOT reimplemented here -- they're the exact same primitives services/activity-feed.ts
// uses for its own "outage window opened/closed" activity-feed events
// (parseOutageMarker + computeEffectiveMarker), so this banner and that feed can never
// disagree about whether a marker is currently effective. Reads the SAME file at the SAME
// cadence activity-feed.ts already polls it at -- no new polling cost, no new file format.

import { useEffect, useState } from "react";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";
import { stripBom } from "../utils/file-operations.ts";
import { parseOutageMarker, computeEffectiveMarker } from "./activity-feed.ts";
import type { OutageBannerState } from "../components/status-bar.ts";

export type { OutageBannerState };

/** Poll cadence -- matches activity-feed.ts's OUTAGE_POLL_INTERVAL_MS so this banner reads
 *  the planned-outage.json marker at the SAME cadence already established for
 *  outage-transition detection; no additional polling cost beyond what already exists. */
export const DEFAULT_OUTAGE_BANNER_POLL_INTERVAL_MS = 1000;

const INACTIVE_BANNER: OutageBannerState = { active: false };

/**
 * Projects a raw marker-file read (possibly null on a missing/unreadable file, possibly
 * BOM-prefixed per #475's PowerShell caveat) into OutageBannerState. Exported standalone so
 * it's directly testable without touching the filesystem or a poll interval.
 */
export function projectOutageBanner(raw: string | null, nowMs: number): OutageBannerState {
  const parsed = raw ? parseOutageMarker(stripBom(raw)) : null;
  const effective = computeEffectiveMarker(parsed, nowMs);
  if (!effective) return INACTIVE_BANNER;
  return {
    active: true,
    owner: effective.owner,
    reason: effective.reason,
    expires: effective.expires,
  };
}

/**
 * Reads the marker file fresh and projects it. Never throws -- an absent, unreadable, or
 * malformed marker all project to exactly {active:false}, identical to a genuinely absent
 * marker (mirrors the watchdog's own Get-PlannedOutageMarker "never partially honored" rule).
 */
export async function readOutageBannerState(
  markerPath: string,
  nowMs: number = Date.now(),
): Promise<OutageBannerState> {
  let raw: string | null = null;
  try {
    raw = await readFile(markerPath, "utf-8");
  } catch {
    raw = null;
  }
  return projectOutageBanner(raw, nowMs);
}

/**
 * Polls tools/ember-cli/state/planned-outage.json at `intervalMs` cadence (default matches
 * the existing activity-feed outage poll -- see DEFAULT_OUTAGE_BANNER_POLL_INTERVAL_MS).
 * Returns {active:false} whenever the marker is absent, expired, or malformed; the live
 * fields (owner/reason/expires) whenever an unexpired, fully-valid marker is present.
 * Fails open: a read/parse error on any given tick never surfaces to the UI, it just keeps
 * (or reverts to) the last-known-good projection and retries next tick.
 */
export function useOutageBanner(
  intervalMs: number = DEFAULT_OUTAGE_BANNER_POLL_INTERVAL_MS,
  repoRoot?: string,
): OutageBannerState {
  const [banner, setBanner] = useState<OutageBannerState>(INACTIVE_BANNER);

  useEffect(() => {
    let active = true;
    const root = repoRoot ?? resolveEmberRepoRootOrCwd({}, "[outage-banner]");
    const markerPath = path.join(root, "tools", "ember-cli", "state", "planned-outage.json");

    const poll = async (): Promise<void> => {
      const next = await readOutageBannerState(markerPath);
      if (active) setBanner(next);
    };
    void poll(); // immediate first read -- no 1s blank window on cockpit boot
    const id = setInterval(() => void poll(), intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [intervalMs, repoRoot]);

  return banner;
}
