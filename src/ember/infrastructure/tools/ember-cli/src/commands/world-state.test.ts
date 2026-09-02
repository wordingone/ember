// commands/world-state.test.ts — the not-yet-live /cockpit command surface's "monitor" turn now
// shares core/monitor-render.ts with the standalone REPL proof-pack (same pct fix, same
// not-green-first sort, same evidence-index consistency) instead of its own separate raw dump.
//
// Runs a tiny driver script in a SPAWNED node subprocess against a fixture goalforge root (env
// override) rather than importing commands/world-state.ts in-process: bun:test's mock.module()
// mutates the shared module registry for the rest of the whole test PROCESS (verified empirically
// -- it corrupted core/ember-world-state.test.ts's real buildEmberWorldState() calls when both
// ran together), and core/ember-world-state.ts's GOALFORGE_ROOT is a module-level const frozen
// from process.env at first import, so an in-process env override after another file has already
// imported it is too late. A subprocess sidesteps both problems with a fresh module registry.

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, it, expect, afterEach } from "bun:test";
import { tmpdir } from "os";
import { join } from "path";
import { pathToFileURL } from "url";
import { mkdir, writeFile, rm } from "fs/promises";
import { createWorldStateCommand } from "../../../../../../../tools/ember-cli/src/commands/world-state.ts";
import { DEFAULT_STALE_THRESHOLD_MS } from "../core/receipt-age.ts";

const SRC_DIR = join(import.meta.dir, ".."); // tools/ember-cli/src (parent of commands/)

// #412: the fixture receipt's "ts" is a fixed calendar timestamp, so any test that lets the
// /cockpit turn call the REAL Date.now() drifts further stale every day this suite runs (it had
// already crossed the staleness threshold twice -- once at 30min, again at 2h -- each time
// silently shifting renderMonitorPanel's line count by inserting a badge line the affected test
// didn't account for). Fixed here for good: "now" is mocked to a point derived from
// DEFAULT_STALE_THRESHOLD_MS (never a raw literal) that is comfortably fresh relative to the
// fixture, so the test's behavior can never again depend on which day it happens to run.
const FIXTURE_RECEIPT_MS = Date.UTC(2026, 6, 3, 12, 0, 0); // matches FIXTURE receipt's ts below
const FRESH_OFFSET_MS = Math.floor(DEFAULT_STALE_THRESHOLD_MS / 24); // a small, threshold-scaled margin -- comfortably inside the cadence window at any threshold value
const FIXTURE_NOW_MS = FIXTURE_RECEIPT_MS + FRESH_OFFSET_MS;

const FIXTURE_GOAL = "# Fixture Goal\n\n## Topology Heading One\n\nbody\n";
const FIXTURE_LEDGER = [
  "## Current Blocker Packet",
  "",
  "1. **Blocker A:** something blocking",
  "",
  "## Active Rows",
  "",
  "| ID | Class | Debt | X | Y | Status |",
  "| --- | --- | --- | --- | --- | --- |",
  "| DEBT-001 | cls | some debt | a | b | open |",
  "",
].join("\n");

async function makeFixtureRoot(): Promise<string> {
  const root = join(
    tmpdir(),
    `ember-cockpit-cmd-test-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  );
  const boardDir = join(root, "scripts", "ember_totality", "receipts-totality");
  await mkdir(boardDir, { recursive: true });
  await mkdir(join(root, "docs", "ledgers"), { recursive: true });
  await writeFile(join(root, "docs/domains/governance/authority/GOAL.md"), FIXTURE_GOAL);
  await writeFile(join(root, "docs", "ledgers", "ember-debt-ledger.md"), FIXTURE_LEDGER);
  const receipt = {
    ts: "20260703T120000Z",
    rows: [
      { condition: "C1", status: "GREEN", reason: "fine" },
      { condition: "C2", status: "RED", reason: "broken" },
      { condition: "C3", status: "AUDIT-OK", reason: "audit fine" },
    ],
    summary: { total: 3, green: 1, red: 1, completion_math: { pct_complete: 73.3 } },
  };
  await writeFile(join(boardDir, "ember-totality-20260703T120000Z.json"), JSON.stringify(receipt));
  return root;
}

/** Runs `monitor`, `evidence monitor 0`, and an out-of-bounds `evidence monitor 3` through the
 * real runWorldStateTurn, in a fresh node subprocess (fresh module registry -- no risk to any
 * other test file's imports). */
async function runCockpitTurns(
  goalforgeRoot: string,
  nowMs: number = FIXTURE_NOW_MS,
): Promise<{ monitor: string; evidence0: string; evidenceOOB: string; act0: string }> {
  const specifier = pathToFileURL(join(SRC_DIR, "commands", "world-state.ts")).href;
  const driverScript = [
    // Mocked now, injected before world-state.ts is even imported -- never the subprocess's real
    // Date.now() (#412). world-state.ts reads Date.now() fresh at call time, so this global
    // override is picked up by every runWorldStateTurn() call below.
    `Date.now = () => ${nowMs};`,
    `const { runWorldStateTurn } = await import(${JSON.stringify(specifier)});`,
    `const monitor = await runWorldStateTurn("monitor");`,
    `const evidence0 = await runWorldStateTurn("evidence monitor 0");`,
    `const evidenceOOB = await runWorldStateTurn("evidence monitor 3");`,
    `const act0 = await runWorldStateTurn("act monitor 0");`,
    `process.stdout.write(JSON.stringify({ monitor, evidence0, evidenceOOB, act0 }));`,
  ].join("\n");
  const driverPath = join(goalforgeRoot, "driver.mjs");
  await writeFile(driverPath, driverScript);

  const proc = Bun.spawn({
    cmd: ["node", driverPath],
    cwd: SRC_DIR,
    env: {
      ...process.env,
      EMBER_GOALFORGE_ROOT: goalforgeRoot,
      EMBER_COBS_ENCOUNTER_LOG: join(goalforgeRoot, "encounters.jsonl"),
    },
    stdout: "pipe",
    stderr: "pipe",
  });
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  if (exitCode !== 0) throw new Error(`driver failed (exit ${exitCode}): ${stderr}`);
  return JSON.parse(stdout);
}

describe("/cockpit monitor turn shares core/monitor-render.ts with the REPL", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it(
    "carries the pct fix through (73.3%, not 0) and renders not-GREEN rows before GREEN rows",
    async () => {
      root = await makeFixtureRoot();
      const { monitor } = await runCockpitTurns(root);
      expect(monitor).toContain("73.3%");
      const lines = monitor.split("\n");
      // Panel border is always first -- that's a real structural invariant, not a fragile index.
      expect(lines[0]).toContain("╭");
      // Row ORDER, asserted by CONTENT rather than a fixed index (#412): any line the panel
      // inserts above the rows (the receipt-age badge line added by #392, or any future header)
      // must never break this test again the way it broke twice already. not-green group (C2
      // RED, C3 AUDIT-OK, original relative order) renders before the GREEN group (C1) -- same
      // rule as the standalone REPL, now inside renderMonitorPanel()'s bordered container.
      const c2Idx = lines.findIndex((l) => l.includes("C2"));
      const c3Idx = lines.findIndex((l) => l.includes("C3"));
      const c1Idx = lines.findIndex((l) => l.includes("C1"));
      expect(c2Idx).toBeGreaterThan(-1);
      expect(c3Idx).toBeGreaterThan(c2Idx);
      expect(c1Idx).toBeGreaterThan(c3Idx);
    },
    20000,
  );

  it(
    "evidence monitor <n> indexes against the sorted (3-row) array, not a stale/wrong-length one",
    async () => {
      root = await makeFixtureRoot();
      const { evidence0, evidenceOOB } = await runCockpitTurns(root);
      // index 0 resolves fine (there are 3 sorted rows: C2, C3, C1) -- every condition claim
      // shares the SAME per-file evidence ref in this adapter, so this checks resolution succeeds
      // rather than which condition it names; the row-order claim itself is covered above.
      expect(evidence0).toContain("EVIDENCE PATH:");
      expect(evidence0).toContain("receipts-totality");
      // index 3 is out of bounds for a 3-element sorted array (0,1,2) -- if the surface were
      // still indexing against some other/unsorted collection this bound could silently differ.
      expect(evidenceOOB).toContain("no claim at monitor 3");
    },
    20000,
  );

  it(
    "refuses an action offer when the displayed board lacks current-tree provenance",
    async () => {
      root = await makeFixtureRoot();
      const { act0 } = await runCockpitTurns(root);
      expect(act0).toContain("ACTION REFUSED");
      expect(act0).toContain("board receipt has no closed run-tree provenance");
      expect(act0).not.toContain("type \"confirm");
    },
    20000,
  );

  it("/cockpit is also reachable as /board (and the existing /world, /cobs aliases)", () => {
    // Static factory-object check -- createWorldStateCommand() does no I/O until .execute() runs,
    // so this is safe to check in-process (no subprocess needed, no GOALFORGE_ROOT env concern).
    const cmd = createWorldStateCommand();
    expect(cmd.name).toBe("cockpit");
    expect(cmd.aliases).toContain("board");
    expect(cmd.aliases).toContain("world");
    expect(cmd.aliases).toContain("cobs");
  });

  it(
    "monitor appends the newest-3-receipts tail (increment-5 fold-in, reusing watch-render.ts)",
    async () => {
      root = await makeFixtureRoot();
      await mkdir(join(root, "receipts"), { recursive: true });
      await writeFile(join(root, "receipts", "some-receipt.json"), "{}");
      const { monitor } = await runCockpitTurns(root);
      expect(monitor).toContain("some-receipt.json");
      expect(monitor).toContain("ago)");
    },
    20000,
  );

  it(
    "monitor rebuilds a FRESH snapshot every invocation -- a second call sees a newer board receipt, not a frozen first-call cache",
    async () => {
      root = await makeFixtureRoot();
      const specifier = pathToFileURL(join(SRC_DIR, "commands", "world-state.ts")).href;
      const boardDir = join(root, "scripts", "ember_totality", "receipts-totality");
      // A lexicographically-later filename than the fixture's own 20260703T120000Z receipt --
      // findNewestBoardReceipt() picks the newest by filename sort, so this becomes "current"
      // the moment it exists on disk, with no cache invalidation needed on the reader's side.
      const secondReceiptMs = FIXTURE_RECEIPT_MS + 60 * 60 * 1000; // matches ts "20260703T130000Z" below
      const secondReceipt = {
        ts: "20260703T130000Z",
        rows: [{ condition: "C9", status: "GREEN", reason: "fixed after monitor #1" }],
        summary: { total: 1, green: 1, red: 0, completion_math: { pct_complete: 100 } },
      };
      // One fixed mocked now for the whole subprocess (#412): comfortably after the SECOND
      // receipt, by the same threshold-scaled margin -- at that point the first receipt (~65min
      // old) and the second (~5min old) are both fresh under DEFAULT_STALE_THRESHOLD_MS, so
      // neither `monitor` call in this test depends on real wall-clock time.
      const mockedNowMs = secondReceiptMs + FRESH_OFFSET_MS;
      const driverScript = [
        `import { writeFile } from "fs/promises";`,
        `Date.now = () => ${mockedNowMs};`,
        `const { runWorldStateTurn } = await import(${JSON.stringify(specifier)});`,
        `const first = await runWorldStateTurn("monitor");`,
        `await writeFile(${JSON.stringify(join(boardDir, "ember-totality-20260703T130000Z.json"))}, ${JSON.stringify(JSON.stringify(secondReceipt))});`,
        `const second = await runWorldStateTurn("monitor");`,
        `process.stdout.write(JSON.stringify({ first, second }));`,
      ].join("\n");
      const driverPath = join(root, "driver-fresh.mjs");
      await writeFile(driverPath, driverScript);
      const proc = Bun.spawn({
        cmd: ["node", driverPath],
        cwd: SRC_DIR,
        env: { ...process.env, EMBER_GOALFORGE_ROOT: root, EMBER_COBS_ENCOUNTER_LOG: join(root, "encounters.jsonl") },
        stdout: "pipe",
        stderr: "pipe",
      });
      const [stdout, stderr, exitCode] = await Promise.all([
        new Response(proc.stdout).text(),
        new Response(proc.stderr).text(),
        proc.exited,
      ]);
      if (exitCode !== 0) throw new Error(`driver failed (exit ${exitCode}): ${stderr}`);
      const { first, second } = JSON.parse(stdout);
      expect(first).toContain("73.3%");
      expect(first).not.toContain("C9"); // C9 doesn't exist yet at the time of the first call
      expect(second).toContain("100%");
      expect(second).toContain("C9");
    },
    20000,
  );
});
