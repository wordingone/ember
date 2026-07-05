// core/ember-world-state.test.ts — regression coverage for the monitor.pctComplete field-read
// bug: the adapter previously read summary.pct_complete (which does not exist on a real
// totality-board receipt) and always defaulted to 0, while the real value lives nested at
// summary.completion_math.pct_complete. Builds a fixture goalforge root (GOAL.md, debt ledger,
// one board receipt) and points buildEmberWorldState() at it via EMBER_GOALFORGE_ROOT override.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import { tmpdir } from "os";
import { join } from "path";
import { mkdir, writeFile, rm } from "fs/promises";
import { buildEmberWorldState } from "./ember-world-state.ts";

const FIXTURE_GOAL = "# Fixture Goal\n\n## Topology Heading One\n\nbody text\n";
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

async function makeFixtureRoot(receiptSummary: Record<string, unknown>): Promise<string> {
  const root = join(tmpdir(), `ember-world-state-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const boardDir = join(root, "scripts", "ember_totality", "receipts-totality");
  await mkdir(boardDir, { recursive: true });
  await mkdir(join(root, "docs"), { recursive: true });
  await writeFile(join(root, "GOAL.md"), FIXTURE_GOAL);
  await writeFile(join(root, "docs", "ember-debt-ledger.md"), FIXTURE_LEDGER);
  const receipt = {
    ts: "20260703T120000Z",
    rows: [
      { condition: "C1", status: "GREEN", reason: "fine" },
      { condition: "C2", status: "RED", reason: "broken" },
    ],
    summary: receiptSummary,
  };
  // Lexicographically newest filename (findNewestBoardReceipt sorts and takes the last).
  await writeFile(join(boardDir, "ember-totality-20260703T120000Z.json"), JSON.stringify(receipt));
  return root;
}

describe("buildEmberWorldState: monitor.pctComplete field-read fix", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it("reads pct_complete from summary.completion_math.pct_complete (the real receipt shape)", async () => {
    root = await makeFixtureRoot({
      total: 2,
      green: 1,
      red: 1,
      completion_math: { pct_complete: 73.3 },
    });
    const state = await buildEmberWorldState({ goalforgeRoot: root });
    expect(state.monitor.pctComplete).toBe(73.3);
  });

  it("falls back to flat summary.pct_complete when completion_math is absent", async () => {
    root = await makeFixtureRoot({ total: 2, green: 1, red: 1, pct_complete: 50 });
    const state = await buildEmberWorldState({ goalforgeRoot: root });
    expect(state.monitor.pctComplete).toBe(50);
  });

  it("prefers completion_math.pct_complete over a flat summary.pct_complete when both are present", async () => {
    root = await makeFixtureRoot({
      total: 2,
      green: 1,
      red: 1,
      pct_complete: 999, // stale/wrong flat value -- completion_math is the real one
      completion_math: { pct_complete: 73.3 },
    });
    const state = await buildEmberWorldState({ goalforgeRoot: root });
    expect(state.monitor.pctComplete).toBe(73.3);
  });

  it("defaults to 0 only when neither location has a value (previous, now-fixed-elsewhere behavior)", async () => {
    root = await makeFixtureRoot({ total: 2, green: 1, red: 1 });
    const state = await buildEmberWorldState({ goalforgeRoot: root });
    expect(state.monitor.pctComplete).toBe(0);
  });
});
