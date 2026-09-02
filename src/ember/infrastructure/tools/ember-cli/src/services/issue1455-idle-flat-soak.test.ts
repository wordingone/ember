// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// issue1455-idle-flat-soak.test.ts — closing regression test for issue #1455 (cockpit idle
// commit/RSS leak). Pins the DELIVERED state, not a zero-growth ideal: three overnight soak legs
// (75min and 2hr real-exe runs, see the issue's delivered-state verdict and leg-6 comment
// 5280457769) established that the catastrophic runaway (the original incident: a resource-
// exhaustion-detector event at ~69GB commit) is cured, but a small residual native-private-region
// growth remains (~1.4-1.6 GiB/hr, fragmenting across many small/medium regions per leg 6's
// region-census attribution, not a JS-managed-heap leak and not a few large arenas). This test
// guards against the RUNAWAY CLASS returning — it is not a promise of zero growth, and it is
// deliberately loose relative to the measured residual so ordinary run-to-run variance never
// flakes it.
//
// WINDOW / CEILING / SETTLE calibration (not judgment calls — see the PR body for the full
// window-distribution table computed by slicing leg 6's real 150-sample soak into every possible
// window):
//   - 60s settle before the measured window starts: leg 6's own "early vs settled" windows
//     differed by <1% in every window length tested, so this catches almost nothing in the
//     calibration data itself — kept anyway as cheap insurance against a real spawn-adjacent
//     JIT/allocator transient that leg 6's own first sample (already ~3-23s post-spawn) may not
//     fully represent.
//   - 5-minute RSS fit window: at 3 minutes, leg 6's historical max slope (2.220 GiB/hr) sat only
//     ~13% below a 2.5 GiB/hr ceiling — thin margin, real flake risk on a slightly noisier future
//     run. At 5 minutes the historical max drops to 1.845 GiB/hr, ~35% margin under the same
//     ceiling, while staying well under ci-nightly's ~10-minute tolerance for this class of run.
//   - RSS ceiling 2.5 GiB/hr: comfortable margin over every measured cured-state window at 5min,
//     and still two-to-three orders of magnitude below the original runaway class (measured
//     5-7.5 GiB/hr before the cure) — this bounds the defect class returning, not the residual.
//   - JS-heap floor delta, not a slope: bun:jsc's heapSize() rides a GC sawtooth 15-60 MiB wide
//     with a ~92s median cycle (leg 6), so any slope fit inside a 3-5min window is dominated by
//     GC phase, not trend — confirmed empirically: a per-cycle-minima slope fit at 3min windows
//     across leg 6's data ranged -307 to +654 MiB/hr, unusably noisy. Forcing a full GC
//     (bun:jsc fullGC()) and reading heapSize() immediately after, once at window start and once
//     at window end, removes the sawtooth entirely — leg 6's own local-GC-minima trend over the
//     full 76min run was -0.277 MiB/hr (R2=0.001, flat), supporting that a floor-to-floor delta
//     reads true instead of phase noise.
//   - JS-heap ceiling +/-20 MiB (absolute, not a rate — two points don't support a slope):
//     implied detection floor is a JS-side leak slower than ~240 MiB/hr (20 MiB / 5min) passes
//     this test undetected. That is intentional for this test's stated purpose — it guards the
//     GiB/hr-scale runaway class, not sub-GiB/hr JS-side drift — and is stated here so a future
//     reader does not mistake this ceiling for a general JS-heap-leak detector.

import { describe, expect, test } from "bun:test";
import { runIdleSoak } from "./issue1455-idle-soak-harness.ts";
import { linearFit } from "./ols-fit.ts";

const MIB = 1024 ** 2;
const GIB = 1024 ** 3;
const HOUR_MS = 3_600_000;

const SETTLE_MS = 60_000;
const WINDOW_MS = 5 * 60_000;
const SAMPLE_INTERVAL_MS = 15_000;

const RSS_CEILING_GIB_PER_HOUR = 2.5;
const JS_HEAP_FLOOR_DELTA_CEILING_BYTES = 20 * MIB;

describe("issue #1455 delivered-state regression (cured runaway, bounded residual)", () => {
  test(
    "RSS growth stays under the runaway-class ceiling and the JS-managed heap floor stays flat",
    async () => {
      const result = await runIdleSoak({
        settleMs: SETTLE_MS,
        durationMs: WINDOW_MS,
        sampleIntervalMs: SAMPLE_INTERVAL_MS,
      });

      expect(result.rssSamples.length).toBeGreaterThanOrEqual(2);

      const fit = linearFit(result.rssSamples.map((s) => ({ x: s.t, y: s.rss })));
      const rssSlopeGibPerHour = (fit.slope * HOUR_MS) / GIB;

      const jsHeapFloorDeltaBytes = result.jsHeapFloorEndBytes - result.jsHeapFloorStartBytes;

      console.log(
        `issue1455 idle-flat soak: n=${result.rssSamples.length} ` +
          `rssSlope=${rssSlopeGibPerHour.toFixed(3)} GiB/hr (R2=${fit.r2.toFixed(3)}) ` +
          `jsHeapFloorDelta=${(jsHeapFloorDeltaBytes / MIB).toFixed(2)} MiB ` +
          `(start=${(result.jsHeapFloorStartBytes / MIB).toFixed(2)} end=${(result.jsHeapFloorEndBytes / MIB).toFixed(2)})`,
      );

      expect(rssSlopeGibPerHour).toBeLessThan(RSS_CEILING_GIB_PER_HOUR);
      expect(Math.abs(jsHeapFloorDeltaBytes)).toBeLessThan(JS_HEAP_FLOOR_DELTA_CEILING_BYTES);
    },
    // Spawn + ready-wait + settle + the measured window, with slack for CI scheduling jitter.
    10 * 60_000,
  );
});
