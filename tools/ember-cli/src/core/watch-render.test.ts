// core/watch-render.test.ts — coverage for the `--watch` ambient observatory mode's pure/small-I/O
// helpers: arg parsing, age formatting, newest-receipts scan+tail, and the single-cycle composer
// (runWatchCycle) exercised directly (not via a timer or a spawned process).

import { describe, it, expect, afterEach } from "bun:test";
import { tmpdir } from "os";
import { join } from "path";
import { mkdir, writeFile, rm, utimes } from "fs/promises";
import {
  parseWatchArgs,
  DEFAULT_INTERVAL_SEC,
  MIN_INTERVAL_SEC,
  formatAge,
  renderWatchHeader,
  renderRefreshError,
  renderReceiptsTail,
  findNewestReceipts,
  runWatchCycle,
} from "./watch-render.ts";

// ---------------------------------------------------------------------------
// parseWatchArgs
// ---------------------------------------------------------------------------

describe("parseWatchArgs", () => {
  it("watch is false and interval defaults to 30 when --watch is absent", () => {
    expect(parseWatchArgs([])).toEqual({ watch: false, intervalSec: DEFAULT_INTERVAL_SEC });
  });

  it("watch is true when --watch is present, interval still defaults to 30", () => {
    expect(parseWatchArgs(["--watch"])).toEqual({ watch: true, intervalSec: 30 });
  });

  it("honors an explicit --interval override", () => {
    expect(parseWatchArgs(["--watch", "--interval", "45"])).toEqual({ watch: true, intervalSec: 45 });
  });

  it("floors any requested interval below MIN_INTERVAL_SEC to the floor", () => {
    expect(parseWatchArgs(["--watch", "--interval", "1"]).intervalSec).toBe(MIN_INTERVAL_SEC);
    expect(parseWatchArgs(["--watch", "--interval", "0"]).intervalSec).toBe(MIN_INTERVAL_SEC);
    expect(parseWatchArgs(["--watch", "--interval", "-5"]).intervalSec).toBe(MIN_INTERVAL_SEC);
  });

  it("an interval at exactly the floor is left unchanged", () => {
    expect(parseWatchArgs(["--watch", "--interval", "5"]).intervalSec).toBe(5);
  });

  it("an unparsable --interval value falls back to the default (still floored)", () => {
    expect(parseWatchArgs(["--watch", "--interval", "notanumber"]).intervalSec).toBe(DEFAULT_INTERVAL_SEC);
  });

  it("a --interval with no following value falls back to the default", () => {
    expect(parseWatchArgs(["--watch", "--interval"]).intervalSec).toBe(DEFAULT_INTERVAL_SEC);
  });
});

// ---------------------------------------------------------------------------
// formatAge
// ---------------------------------------------------------------------------

describe("formatAge", () => {
  it("formats sub-minute durations in seconds", () => {
    expect(formatAge(0)).toBe("0s ago");
    expect(formatAge(12_000)).toBe("12s ago");
    expect(formatAge(59_000)).toBe("59s ago");
  });

  it("formats sub-hour durations in minutes", () => {
    expect(formatAge(60_000)).toBe("1m ago");
    expect(formatAge(4 * 60_000)).toBe("4m ago");
    expect(formatAge(59 * 60_000)).toBe("59m ago");
  });

  it("formats sub-day durations in hours", () => {
    expect(formatAge(60 * 60_000)).toBe("1h ago");
    expect(formatAge(23 * 60 * 60_000)).toBe("23h ago");
  });

  it("formats durations of a day or more in days", () => {
    expect(formatAge(24 * 60 * 60_000)).toBe("1d ago");
    expect(formatAge(3 * 24 * 60 * 60_000)).toBe("3d ago");
  });

  it("clamps negative durations (clock skew) to 0s ago rather than throwing", () => {
    expect(formatAge(-500)).toBe("0s ago");
  });
});

// ---------------------------------------------------------------------------
// renderWatchHeader / renderRefreshError
// ---------------------------------------------------------------------------

describe("renderWatchHeader / renderRefreshError", () => {
  it("header contains the fixed title and the interval", () => {
    const line = renderWatchHeader(new Date("2026-07-03T12:00:00Z"), 30);
    expect(line).toContain("EMBER OBSERVATORY");
    expect(line).toContain("refresh 30s");
  });

  it("error line names the reason and the retry interval", () => {
    const line = renderRefreshError("ENOENT", 5);
    expect(line).toBe("refresh failed (ENOENT), retrying in 5s");
  });
});

// ---------------------------------------------------------------------------
// renderReceiptsTail
// ---------------------------------------------------------------------------

describe("renderReceiptsTail", () => {
  it("renders one line per receipt as '<path> (<age>)'", () => {
    const lines = renderReceiptsTail(
      [
        { path: "receipts/a.json", mtimeMs: 0 },
        { path: "receipts/b.json", mtimeMs: 60_000 },
      ],
      120_000,
    );
    expect(lines).toEqual(["receipts/a.json (2m ago)", "receipts/b.json (1m ago)"]);
  });

  it("renders a placeholder line when there are no receipts", () => {
    expect(renderReceiptsTail([], Date.now())).toEqual(["no receipts found"]);
  });
});

// ---------------------------------------------------------------------------
// findNewestReceipts (fixture-based, controlled mtimes)
// ---------------------------------------------------------------------------

describe("findNewestReceipts", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it("returns the newest N files (nested included) sorted newest-first by mtime", async () => {
    root = join(tmpdir(), `watch-receipts-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    const receiptsDir = join(root, "receipts");
    const nestedDir = join(receiptsDir, "nested");
    await mkdir(nestedDir, { recursive: true });

    const files: Array<{ path: string; ageSec: number }> = [
      { path: join(receiptsDir, "oldest.json"), ageSec: 300 },
      { path: join(receiptsDir, "middle.json"), ageSec: 200 },
      { path: join(nestedDir, "newest.json"), ageSec: 10 },
      { path: join(nestedDir, "second-newest.json"), ageSec: 100 },
    ];
    const now = new Date();
    for (const f of files) {
      await writeFile(f.path, "{}");
      const mtime = new Date(now.getTime() - f.ageSec * 1000);
      await utimes(f.path, mtime, mtime);
    }

    const result = await findNewestReceipts(root, 3);
    expect(result).toHaveLength(3);
    expect(result[0]!.path).toBe("receipts/nested/newest.json");
    expect(result[1]!.path).toBe("receipts/nested/second-newest.json");
    expect(result[2]!.path).toBe("receipts/middle.json");
  });

  it("returns [] (never throws) when the receipts directory does not exist", async () => {
    root = join(tmpdir(), `watch-receipts-missing-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    const result = await findNewestReceipts(root, 3);
    expect(result).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// runWatchCycle (the exported single-cycle function -- no timer, no subprocess)
// ---------------------------------------------------------------------------

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

async function makeFixtureRoot(): Promise<string> {
  const root = join(tmpdir(), `watch-cycle-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  const boardDir = join(root, "scripts", "ember_totality", "receipts-totality");
  const receiptsDir = join(root, "receipts");
  await mkdir(boardDir, { recursive: true });
  await mkdir(join(root, "docs"), { recursive: true });
  await mkdir(receiptsDir, { recursive: true });
  await writeFile(join(root, "GOAL.md"), FIXTURE_GOAL);
  await writeFile(join(root, "docs", "ember-debt-ledger.md"), FIXTURE_LEDGER);
  const receipt = {
    ts: "20260703T120000Z",
    rows: [
      { condition: "C1", status: "GREEN", reason: "fine" },
      { condition: "C2", status: "RED", reason: "broken" },
    ],
    summary: { total: 2, green: 1, red: 1, completion_math: { pct_complete: 50 } },
  };
  await writeFile(join(boardDir, "ember-totality-20260703T120000Z.json"), JSON.stringify(receipt));
  await writeFile(join(receiptsDir, "some-receipt.json"), "{}");
  return root;
}

describe("runWatchCycle", () => {
  let root: string;

  afterEach(async () => {
    if (root) await rm(root, { recursive: true, force: true });
  });

  it("non-TTY: emits a separator line, the OBSERVATORY header, the monitor board, and a receipts tail", async () => {
    root = await makeFixtureRoot();
    const lines = await runWatchCycle({
      intervalSec: 5,
      isTTY: false,
      colorEnabled: false,
      goalforgeRoot: root,
      now: new Date("2026-07-03T12:05:00Z"),
    });

    expect(lines[0]).toBe("----------------------------------------");
    expect(lines[1]).toContain("EMBER OBSERVATORY");
    expect(lines[1]).toContain("refresh 5s");
    // Monitor board content somewhere in the middle -- C1/C2 rows from the fixture receipt.
    const joined = lines.join("\n");
    expect(joined).toContain("C1");
    expect(joined).toContain("C2");
    // Receipts tail is the final line(s) -- the one fixture receipt we wrote.
    expect(lines[lines.length - 1]).toContain("some-receipt.json");
    expect(lines[lines.length - 1]).toContain("ago)");
  });

  it("TTY: the first line is the ANSI clear-screen sequence, not the plain separator", async () => {
    root = await makeFixtureRoot();
    const lines = await runWatchCycle({
      intervalSec: 5,
      isTTY: true,
      colorEnabled: false,
      goalforgeRoot: root,
    });
    expect(lines[0]).toBe("\x1b[2J\x1b[H");
  });

  it("refresh-error resilience: a nonexistent goalforge root renders a one-line error, never throws", async () => {
    const missingRoot = join(tmpdir(), `watch-cycle-missing-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    const lines = await runWatchCycle({
      intervalSec: 7,
      isTTY: false,
      colorEnabled: false,
      goalforgeRoot: missingRoot,
    });
    // Separator line, then exactly one error line -- no header/board/tail on failure.
    expect(lines).toHaveLength(2);
    expect(lines[1]).toContain("refresh failed");
    expect(lines[1]).toContain("retrying in 7s");
  });
});
