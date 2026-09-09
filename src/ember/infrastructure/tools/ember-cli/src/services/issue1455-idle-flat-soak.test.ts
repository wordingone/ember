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
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, delimiter, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { linearFit } from "./ols-fit.ts";

// Exercise the real launch caller; intercept only the PTY boundary in an isolated
// child so no terminal or soak starts and module mocks cannot affect other tests.
for (const outsideCheckout of [false, true]) {
  test(`idle soak uses its source checkout (${outsideCheckout ? "spaced checkout and foreign roots" : "local cwd"})`, () => {
    if (process.platform !== "win32") return;
    const scratch = mkdtempSync(join(tmpdir(), "ember-idle-path-test-"));
    try {
      let expectedSource = resolve(import.meta.dir, "..");
      let expectedRepo = resolve(expectedSource, "..", "..", "..", "..", "..", "..");
      if (outsideCheckout) {
        expectedRepo = join(scratch, "checkout with spaces");
        expectedSource = join(expectedRepo, "src", "ember", "infrastructure", "tools", "ember-cli", "src");
        mkdirSync(join(expectedSource, "services"), { recursive: true });
        mkdirSync(join(expectedSource, "cli"));
        mkdirSync(join(expectedSource, "entrypoints"));
        for (const name of ["issue1455-idle-soak-harness.ts", "headless-capture.ts"]) {
          copyFileSync(join(import.meta.dir, name), join(expectedSource, "services", name));
        }
        copyFileSync(join(import.meta.dir, "..", "cli", "ready-sentinel.ts"), join(expectedSource, "cli", "ready-sentinel.ts"));
        writeFileSync(join(expectedSource, "entrypoints", "main.ts"), 'throw new Error("fixture entrypoint must not execute");');
        const initialized = spawnSync("git", ["init", "--quiet", expectedRepo], { encoding: "utf8", windowsHide: true, timeout: 5_000 });
        expect(initialized.status).toBe(0);
      }
      const harness = pathToFileURL(join(expectedSource, "services", "issue1455-idle-soak-harness.ts")).href;
      const code = `
        import { mock } from "bun:test";
        import { existsSync, rmSync } from "node:fs";
        import { basename, dirname, join, resolve } from "node:path";
        import { tmpdir } from "node:os";
        let observed;
        mock.module("node-pty", () => ({ spawn(executable, args, options) {
          const home = resolve(options.env.EMBER_HOME);
          if (dirname(home) !== resolve(tmpdir()) || !basename(home).startsWith("issue1455-idle-soak-")) {
            throw new Error("unexpected fixture custody");
          }
          observed = { cwd: options.cwd, args,
            entryExists: existsSync(join(options.cwd, args.at(-1))),
            headless: options.env.EMBER_CLI_HEADLESS_CAPTURE,
            repoRoot: options.env.EMBER_REPO_ROOT, sourceRoot: options.env.EMBER_SOURCE_ROOT };
          rmSync(home, { recursive: true, force: true });
          throw new Error("idle-path-boundary-observed");
        }}));
        const { runIdleSoak } = await import(${JSON.stringify(harness)});
        try {
          await runIdleSoak({ settleMs: 0, durationMs: 0, sampleIntervalMs: 1 });
          throw new Error("PTY boundary was not observed");
        } catch (error) {
          if (error.message !== "idle-path-boundary-observed") throw error;
        }
        console.log(JSON.stringify(observed));
      `;
      const result = spawnSync(process.execPath, ["-e", code], {
        cwd: outsideCheckout ? scratch : expectedSource,
        env: { ...process.env,
          PATH: `${dirname(process.execPath)}${delimiter}${process.env.PATH ?? ""}`,
          ...(outsideCheckout ? { EMBER_REPO_ROOT: scratch, EMBER_SOURCE_ROOT: scratch } : {}),
          EMBER_CLI_HEADLESS_CAPTURE: "0" },
        encoding: "utf8", windowsHide: true, timeout: 15_000,
      });
      expect(result.error).toBeUndefined();
      expect(result.status).toBe(0);
      expect(result.stderr).toBe("");
      const observed = JSON.parse(result.stdout);
      expect(resolve(observed.cwd)).toBe(expectedSource);
      expect(observed.args[1]).toBe("./entrypoints/main.ts");
      expect(observed.entryExists).toBe(true);
      expect(observed.headless).toBe("1");
      expect(resolve(observed.repoRoot)).toBe(expectedRepo);
      expect(observed.sourceRoot).toBe(observed.repoRoot);
    } finally {
      if (dirname(resolve(scratch)) !== resolve(tmpdir()) || !basename(scratch).startsWith("ember-idle-path-test-")) {
        throw new Error("unexpected fixture cleanup path");
      }
      rmSync(scratch, { recursive: true, force: true });
    }
  });
}

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
      const { runIdleSoak } = await import("./issue1455-idle-soak-harness.ts");
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
