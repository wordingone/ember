// core/ember-world-state.test.ts — regression coverage for the monitor.pctComplete field-read
// bug: the adapter previously read summary.pct_complete (which does not exist on a real
// totality-board receipt) and always defaulted to 0, while the real value lives nested at
// summary.completion_math.pct_complete. Builds a fixture goalforge root (GOAL.md, debt ledger,
// one board receipt) and points buildEmberWorldState() at it via EMBER_GOALFORGE_ROOT override.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import { tmpdir } from "os";
import { join } from "path";
import { mkdir, writeFile, rm } from "fs/promises";
import {
  buildEmberWorldState,
  peekNewestBoardReceiptFilename,
  pollForNewerBoardTs,
} from "./ember-world-state.ts";

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

// ---------------------------------------------------------------------------
// #420: cockpit live-badge poll -- peekNewestBoardReceiptFilename / pollForNewerBoardTs
// ---------------------------------------------------------------------------

async function makeBoardOnlyRoot(): Promise<string> {
  const root = join(tmpdir(), `ember-world-state-poll-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const boardDir = join(root, "scripts", "ember_totality", "receipts-totality");
  await mkdir(boardDir, { recursive: true });
  return root;
}

function boardDirOf(root: string): string {
  return join(root, "scripts", "ember_totality", "receipts-totality");
}

async function writeReceipt(root: string, filename: string, ts: string): Promise<void> {
  const receipt = {
    ts,
    rows: [{ condition: "C1", status: "GREEN", reason: "fine" }],
    summary: { total: 1, green: 1, red: 0 },
  };
  await writeFile(join(boardDirOf(root), filename), JSON.stringify(receipt));
}

describe("peekNewestBoardReceiptFilename", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it("returns null when the board dir does not exist", async () => {
    root = join(tmpdir(), `ember-world-state-poll-missing-${Date.now()}`);
    expect(await peekNewestBoardReceiptFilename(root)).toBeNull();
  });

  it("returns null when the board dir exists but is empty", async () => {
    root = await makeBoardOnlyRoot();
    expect(await peekNewestBoardReceiptFilename(root)).toBeNull();
  });

  it("returns the lexicographically newest filename without needing valid JSON content (proves no parse happens)", async () => {
    root = await makeBoardOnlyRoot();
    await writeReceipt(root, "ember-totality-20260703T120000Z.json", "20260703T120000Z");
    // Genuinely invalid JSON -- if peek ever parsed this file, it would throw.
    await writeFile(join(boardDirOf(root), "ember-totality-20260704T120000Z.json"), "{not valid json");

    const filename = await peekNewestBoardReceiptFilename(root);
    expect(filename).toBe("ember-totality-20260704T120000Z.json");
  });
});

describe("pollForNewerBoardTs", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it("fails open (returns null) when the board dir does not exist", async () => {
    root = join(tmpdir(), `ember-world-state-poll-missing-${Date.now()}`);
    expect(await pollForNewerBoardTs(root, undefined)).toBeNull();
  });

  it("returns the newest receipt's ts + filename on the very first poll (lastKnownFilename undefined)", async () => {
    root = await makeBoardOnlyRoot();
    await writeReceipt(root, "ember-totality-20260703T120000Z.json", "20260703T120000Z");

    const result = await pollForNewerBoardTs(root, undefined);
    expect(result).toEqual({ filename: "ember-totality-20260703T120000Z.json", boardTs: "20260703T120000Z" });
  });

  it("returns null (no update) when the newest filename matches lastKnownFilename, WITHOUT parsing it", async () => {
    root = await makeBoardOnlyRoot();
    const filename = "ember-totality-20260703T120000Z.json";
    // Genuinely invalid JSON -- a real parse attempt would reject the promise; the null result
    // below only happens if pollForNewerBoardTs skipped reading/parsing the file entirely because
    // the filename comparison short-circuited first (the #420 "no JSON parse per tick" contract).
    await writeFile(join(boardDirOf(root), filename), "{not valid json");

    const result = await pollForNewerBoardTs(root, filename);
    expect(result).toBeNull();
  });

  it("detects a newer receipt landing mid-session and returns its ts + filename -- the exact shape screens/repl.ts's long-lived poll loop calls on every tick, no remount ever involved", async () => {
    root = await makeBoardOnlyRoot();
    await writeReceipt(root, "ember-totality-20260703T120000Z.json", "20260703T120000Z");

    // First tick: baseline established (mirrors the poller hook's cheap-seed step).
    const seedFilename = await peekNewestBoardReceiptFilename(root);
    expect(seedFilename).toBe("ember-totality-20260703T120000Z.json");

    // Nothing new yet -- subsequent ticks against the seeded filename find no change.
    expect(await pollForNewerBoardTs(root, seedFilename ?? undefined)).toBeNull();

    // A new board run lands mid-session (newer receipt file appears in the same directory).
    await writeReceipt(root, "ember-totality-20260703T130000Z.json", "20260703T130000Z");

    const result = await pollForNewerBoardTs(root, seedFilename ?? undefined);
    expect(result).toEqual({ filename: "ember-totality-20260703T130000Z.json", boardTs: "20260703T130000Z" });
  });
});
