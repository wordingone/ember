// core/watch-render.test.ts — coverage for the receipts-tail helpers commands/world-state.ts's
// /cockpit "monitor" turn genuinely calls: age formatting, newest-receipts scan, and the tail
// renderer built from them.

import { describe, it, expect, afterEach } from "bun:test";
import { tmpdir } from "os";
import { join } from "path";
import { mkdir, writeFile, rm, utimes } from "fs/promises";
import { formatAge, renderReceiptsTail, findNewestReceipts } from "./watch-render.ts";

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
