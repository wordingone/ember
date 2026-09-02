// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// scripts/test-gate.e2e.test.ts — end-to-end proof that the CHECKED-IN `bun run test:gate`
// command (package.json's "test:gate" script, wired to this same scripts/test-gate.ts) correctly
// reds out on the four failure shapes a naive `bun test` conflates or misses:
//   1. a genuine test failure (nonzero fail count, summary present)
//   2. a crash before any summary prints (missing summary, not a timeout)
//   3. a hang (missing summary via the gate's own timeout + kill)
//   4. a clean summary followed by a nonzero exit, for a file NOT on the quarantine list
//      (the exact panic shape from BUNPANIC_TRIAGE.md, reproduced synthetically here since the
//      real teardown bug is cured and no longer reproduces live)
//
// Fixtures are generated into a fresh OS temp directory per run (never checked into the repo --
// a permanently-failing/hanging *.test.ts file living under tools/ember-cli/src would corrupt
// every real `bun test` / `bun run test:gate` invocation against the actual suite). The gate is
// pointed at that temp directory via the GATE_SRC_ROOT/GATE_QUARANTINE_JSON test-only overrides
// documented at the top of test-gate.ts, but the SPAWNED COMMAND is exactly `bun run test:gate`
// -- the real checked-in entrypoint, not a re-implementation of its logic.

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { drainAvailable } from "./drain-stream.ts";

const EMBER_CLI_SRC = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

let fixtureDir: string;

beforeAll(() => {
  fixtureDir = mkdtempSync(join(tmpdir(), "gate-e2e-"));

  writeFileSync(
    join(fixtureDir, "fail-nonzero.test.ts"),
    `import { expect, test } from "bun:test";\n` +
    `test("deliberately fails", () => {\n  expect(1).toBe(2);\n});\n`,
  );

  writeFileSync(
    join(fixtureDir, "missing-summary-crash.test.ts"),
    `process.exit(2);\n`,
  );

  writeFileSync(
    join(fixtureDir, "timeout-hang.test.ts"),
    `import { test } from "bun:test";\n` +
    `test("never resolves", async () => {\n  await new Promise(() => {});\n});\n`,
  );

  // NOT quarantined below -- this is the P1-1-adjacent case: a clean-summary/nonzero-exit run
  // for a file the gate has never heard of.
  writeFileSync(
    join(fixtureDir, "panic-after-summary-unadmitted.test.ts"),
    `import { afterAll, expect, test } from "bun:test";\n` +
    `test("passes cleanly", () => {\n  expect(1).toBe(1);\n});\n` +
    `afterAll(() => {\n  process.exitCode = 7;\n});\n`,
  );
});

afterAll(async () => {
  // timeout-hang.test.ts is deliberately never-resolving; the process that ran it gets killed
  // (that's the point), but bun's own "killed N dangling process" warning during these runs
  // indicates the OS process isn't always fully torn down afterward -- it can hold a lock on the
  // fixture directory well past any reasonable retry budget (observed: still EBUSY after 10s of
  // 300ms-interval retries). Cleanup is hygiene, not part of what this file verifies: retry with
  // a real budget, but degrade to a warning rather than fail the whole suite over an OS-level
  // handle this process doesn't control. The OS temp directory is reclaimed on its own schedule
  // regardless.
  const deadline = Date.now() + 8_000;
  for (;;) {
    try {
      rmSync(fixtureDir, { recursive: true, force: true });
      return;
    } catch (err) {
      if (Date.now() >= deadline) {
        console.warn(`test-gate.e2e.test.ts: could not remove ${fixtureDir} (${(err as Error).message}); leaving it for the OS temp-dir reaper`);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
  }
}, 12_000);

interface GateRunOutcome {
  exitCode: number | null;
  stdout: string;
}

async function runGate(quarantine: string[]): Promise<GateRunOutcome> {
  const proc = Bun.spawn(
    [process.execPath, "run", "test:gate", "--timeout-ms=5000"],
    {
      cwd: EMBER_CLI_SRC,
      env: {
        ...process.env,
        GATE_SRC_ROOT: fixtureDir,
        GATE_QUARANTINE_JSON: JSON.stringify(quarantine),
      },
      stdout: "pipe",
      stderr: "pipe",
    },
  );
  // Same fix as test-gate.ts's own use of drainAvailable (see drain-stream.ts's comment): a
  // killed quarantined child three levels down (timeout-hang.test.ts, killed by test-gate.ts,
  // spawned by THIS e2e test's own `bun run test:gate`) can leave this level's stdout/stderr
  // streams unable to signal close too, even once `bun run test:gate` has itself force-exited.
  const exitCode = await proc.exited;
  const [stdout, stderr] = await Promise.all([
    drainAvailable(proc.stdout, 1_000),
    drainAvailable(proc.stderr, 1_000),
  ]);
  return { exitCode, stdout: stdout + stderr };
}

describe("bun run test:gate — end to end against generated fixtures", () => {
  // The 3 always-RED-regardless-of-quarantine-status fixtures are listed so the gate isolates
  // each into its own one-file process (mirroring the real quarantine mechanism's per-file
  // loop); their OWN verdict does not depend on being listed, since timeout/missing-summary/
  // fail-count all short-circuit to RED before the quarantine branch is ever reached. The 4th
  // fixture, panic-after-summary-unadmitted.test.ts, is deliberately left OFF this list so it
  // flows through the main-suite leg unquarantined.
  const quarantineForThisRun = [
    "fail-nonzero.test.ts",
    "missing-summary-crash.test.ts",
    "timeout-hang.test.ts",
  ];

  test(
    "reds out on all four shapes and exits nonzero overall",
    async () => {
      const { exitCode, stdout } = await runGate(quarantineForThisRun);

      expect(exitCode).not.toBe(0);
      expect(stdout).toContain("test-gate: overall = RED");

      // 1. genuine failure
      expect(stdout).toMatch(/=== fail-nonzero\.test\.ts: RED ===/);
      expect(stdout).toMatch(/fail=1/);

      // 2. missing summary, not a timeout (process.exit(2) before any test runs)
      expect(stdout).toMatch(/=== missing-summary-crash\.test\.ts: RED ===/);
      expect(stdout).toMatch(/hasSummary=false/);

      // 3. hang, killed by the gate's own timeout
      expect(stdout).toMatch(/=== timeout-hang\.test\.ts: RED ===/);
      expect(stdout).toMatch(/timedOut=true/);

      // 4. clean summary + nonzero exit, unadmitted file -> RED, never QUARANTINE-PASS
      expect(stdout).toMatch(/=== main-suite: RED ===/);
      expect(stdout).not.toContain("QUARANTINE-PASS");
    },
    20_000,
  );

  test(
    "the same panic shape IS spendable once a file is actually on the list (contrast case)",
    async () => {
      const { stdout } = await runGate([
        "fail-nonzero.test.ts",
        "missing-summary-crash.test.ts",
        "timeout-hang.test.ts",
        "panic-after-summary-unadmitted.test.ts",
      ]);

      expect(stdout).toMatch(/=== panic-after-summary-unadmitted\.test\.ts: QUARANTINE-PASS ===/);
    },
    20_000,
  );
});
