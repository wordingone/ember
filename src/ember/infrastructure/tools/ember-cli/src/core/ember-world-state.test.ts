// core/ember-world-state.test.ts — regression coverage for the monitor.pctComplete field-read
// bug: the adapter previously read summary.pct_complete (which does not exist on a real
// totality-board receipt) and always defaulted to 0, while the real value lives nested at
// summary.completion_math.pct_complete. Builds a fixture goalforge root (docs/domains/governance/authority/GOAL.md, debt ledger,
// one board receipt) and points buildEmberWorldState() at it via EMBER_GOALFORGE_ROOT override.

// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import { tmpdir } from "os";
import { join } from "path";
import { mkdir, writeFile, rm } from "fs/promises";
import {
  buildEmberWorldState,
  peekNewestBoardReceiptFilename,
  pollForNewerBoardTs,
  diffBoardConditions,
  requireBoardReceiptCommit,
  type BoardRow,
} from "../core/ember-world-state.ts";

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
  await mkdir(join(root, "docs", "ledgers"), { recursive: true });
  await mkdir(join(root, "docs", "authority"), { recursive: true });
  await writeFile(join(root, "docs/domains/governance/authority/GOAL.md"), FIXTURE_GOAL);
  await writeFile(join(root, "docs", "ledgers", "ember-debt-ledger.md"), FIXTURE_LEDGER);
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
    expect(result).toEqual({
      filename: "ember-totality-20260703T120000Z.json",
      boardTs: "20260703T120000Z",
      // #433: rows + green/red totals now ride along so a caller can diff conditions without a
      // second file read -- writeReceipt's fixture shape (one GREEN row, summary {total:1,green:1,red:0}).
      rows: [{ condition: "C1", status: "GREEN", reason: "fine" }],
      green: 1,
      red: 0,
    });
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
    expect(result).toEqual({
      filename: "ember-totality-20260703T130000Z.json",
      boardTs: "20260703T130000Z",
      rows: [{ condition: "C1", status: "GREEN", reason: "fine" }],
      green: 1,
      red: 0,
    });
  });
});

// ---------------------------------------------------------------------------
// #433: board condition transitions -- diffBoardConditions
// ---------------------------------------------------------------------------

describe("diffBoardConditions", () => {
  it("returns one transition per condition whose status changed, ignoring unchanged conditions", () => {
    const prevRows: BoardRow[] = [
      { condition: "C-GROW", status: "RED", reason: "was broken" },
      { condition: "C(-1)", status: "GREEN", reason: "was fine" },
      { condition: "C-STABLE", status: "GREEN", reason: "never moves" },
    ];
    const nextRows: BoardRow[] = [
      { condition: "C-GROW", status: "GREEN", reason: "now fine" },
      { condition: "C(-1)", status: "RED", reason: "now broken" },
      { condition: "C-STABLE", status: "GREEN", reason: "never moves" },
    ];

    const transitions = diffBoardConditions(prevRows, nextRows);

    expect(transitions).toEqual([
      { condition: "C-GROW", from: "RED", to: "GREEN" },
      { condition: "C(-1)", from: "GREEN", to: "RED" },
    ]);
  });

  it("emits no transitions when nothing changed", () => {
    const rows: BoardRow[] = [{ condition: "C1", status: "GREEN", reason: "fine" }];
    expect(diffBoardConditions(rows, rows)).toEqual([]);
  });

  it("boot suppression: an undefined prevRows baseline (no prior receipt this session) emits zero transitions, never a fake all-changed storm", () => {
    const nextRows: BoardRow[] = [
      { condition: "C1", status: "GREEN", reason: "fine" },
      { condition: "C2", status: "RED", reason: "broken" },
    ];
    expect(diffBoardConditions(undefined, nextRows)).toEqual([]);
  });

  it("boot suppression: an empty prevRows array likewise emits zero transitions", () => {
    const nextRows: BoardRow[] = [{ condition: "C1", status: "RED", reason: "broken" }];
    expect(diffBoardConditions([], nextRows)).toEqual([]);
  });

  it("a condition present in nextRows but absent from prevRows (newly added condition) is not a transition", () => {
    const prevRows: BoardRow[] = [{ condition: "C1", status: "GREEN", reason: "fine" }];
    const nextRows: BoardRow[] = [
      { condition: "C1", status: "GREEN", reason: "fine" },
      { condition: "C-NEW", status: "RED", reason: "brand new condition" },
    ];
    expect(diffBoardConditions(prevRows, nextRows)).toEqual([]);
  });

  it("fails open on malformed rows (missing condition/status) instead of throwing", () => {
    const prevRows = [
      { condition: "C1", status: "GREEN", reason: "fine" },
      { reason: "malformed, no condition or status" },
      null,
    ] as unknown as BoardRow[];
    const nextRows = [
      { condition: "C1", status: "RED", reason: "now broken" },
      { condition: "C2" } as unknown as BoardRow, // missing status
    ];
    expect(() => diffBoardConditions(prevRows, nextRows)).not.toThrow();
    expect(diffBoardConditions(prevRows, nextRows)).toEqual([
      { condition: "C1", from: "GREEN", to: "RED" },
    ]);
  });
});

describe("requireBoardReceiptCommit", () => {
  const source = "a".repeat(40);
  const required = "b".repeat(40);

  it("refuses a legacy board with no run-tree provenance", async () => {
    await expect(
      requireBoardReceiptCommit(
        { ts: "x", rows: [], summary: { total: 0, green: 0, red: 0 } },
        required,
        async () => true,
      ),
    ).rejects.toThrow("board receipt has no closed run-tree provenance");
  });

  it("accepts only when the required commit is an ancestor of the board source", async () => {
    const receipt = {
      ts: "x",
      rows: [],
      summary: { total: 0, green: 0, red: 0 },
      run_tree_provenance: {
        run_tree_sha: source,
        remote_master_sha: source,
        remote_master_source: "LS_REMOTE" as const,
        tree_is_stale: false,
        behind_by: 0,
        tree_dirty: [],
        stale_tree_override: false,
        provenance_status: "CURRENT_CLEAN" as const,
        publishable_as_current: true,
      },
    };
    let observed: [string, string] | undefined;
    const accepted = await requireBoardReceiptCommit(
      receipt,
      required,
      async (candidate, boardSource) => {
        observed = [candidate, boardSource];
        return true;
      },
    );
    expect(accepted).toBe(source);
    expect(observed).toEqual([required, source]);

    await expect(
      requireBoardReceiptCommit(receipt, required, async () => false),
    ).rejects.toThrow("board source predates required commit");

    await expect(
      requireBoardReceiptCommit(
        {
          run_tree_provenance: {
            ...receipt.run_tree_provenance,
            tree_is_stale: true,
          },
        },
        required,
        async () => true,
      ),
    ).rejects.toThrow("board receipt has no closed run-tree provenance");
  });
});
