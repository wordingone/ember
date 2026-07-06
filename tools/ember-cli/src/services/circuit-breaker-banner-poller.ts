// services/circuit-breaker-banner-poller.ts — issue #239: polls the
// in-process circuit-breaker singleton (session-init.ts's
// getCircuitBreakerState) and projects it into status-bar.ts's
// DegradedBannerState shape for StatusLine's `degraded` prop.
//
// Unlike model-metrics-poller.ts (which polls a Prometheus endpoint over
// HTTP), the circuit-breaker state lives in this same process -- there is no
// network round trip, just a cheap synchronous read on an interval, so the
// operator's degraded banner updates (attempt count, probe countdown)
// without waiting on the model server at all, even while it is unreachable.

import { useState, useEffect } from "react";
import { getCircuitBreakerState } from "../entrypoints/session-init.ts";
import { describeDegradedBanner } from "./model-circuit-breaker.ts";
import type { DegradedBannerState } from "../components/status-bar.ts";

/** Poll cadence for the degraded banner's countdown display. */
export const DEFAULT_BANNER_POLL_INTERVAL_MS = 1_000;

const INACTIVE_BANNER: DegradedBannerState = { active: false };

/**
 * Reads the current circuit-breaker state and projects it into the
 * DegradedBannerState status-bar.ts renders. Returns {active:false} both
 * when no guarded client has ever been wired (getCircuitBreakerState()
 * returns null) and when the circuit is simply closed/healthy.
 */
export function readDegradedBannerState(now: number = Date.now()): DegradedBannerState {
  const state = getCircuitBreakerState();
  if (!state) return INACTIVE_BANNER;
  const banner = describeDegradedBanner(state, now);
  if (!banner) return INACTIVE_BANNER;
  return banner;
}

/**
 * Polls the in-process circuit breaker at `intervalMs` cadence. Returns
 * {active:false} whenever the circuit is closed (or has never been wired),
 * and the live banner fields (endpoint, last status/reason, attempt count,
 * next-probe countdown) whenever it is open or half-open probing.
 */
export function useCircuitBreakerBanner(
  intervalMs: number = DEFAULT_BANNER_POLL_INTERVAL_MS,
): DegradedBannerState {
  const [banner, setBanner] = useState<DegradedBannerState>(() => readDegradedBannerState());

  useEffect(() => {
    let active = true;
    const poll = (): void => {
      if (active) setBanner(readDegradedBannerState());
    };
    poll(); // immediate first read
    const id = setInterval(poll, intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [intervalMs]);

  return banner;
}
