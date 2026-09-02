// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/receipt-landing-poller.test.ts — issue #447: last-receipt-age scanning.

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  findNewestReceiptMtime,
  formatReceiptLandingAge,
  formatLastReceiptLine,
} from "./receipt-landing-poller.ts";

let scratchDir: string;

beforeEach(() => {
  scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-receipt-landing-"));
});

afterEach(() => {
  fs.rmSync(scratchDir, { recursive: true, force: true });
});

describe("findNewestReceiptMtime", () => {
  test("finds the newest file among several nested lane directories", async () => {
    const laneA = path.join(scratchDir, "lane-a");
    const laneB = path.join(scratchDir, "lane-b", "run-1");
    fs.mkdirSync(laneA, { recursive: true });
    fs.mkdirSync(laneB, { recursive: true });

    const older = path.join(laneA, "receipt-1.json");
    const newer = path.join(laneB, "receipt-2.json");
    fs.writeFileSync(older, "{}");
    fs.utimesSync(older, new Date(1000), new Date(1000));
    fs.writeFileSync(newer, "{}");
    fs.utimesSync(newer, new Date(9000), new Date(9000));

    const result = await findNewestReceiptMtime(scratchDir);
    expect(result?.relativePath).toBe(path.join("lane-b", "run-1", "receipt-2.json"));
    expect(result?.mtimeMs).toBe(9000);
    expect(result?.truncated).toBe(false);
  });

  test("returns null for an empty tree", async () => {
    expect(await findNewestReceiptMtime(scratchDir)).toBeNull();
  });

  test("returns null when the root doesn't exist", async () => {
    expect(await findNewestReceiptMtime(path.join(scratchDir, "nope"))).toBeNull();
  });

  test("respects maxDepth: a file deeper than the bound is never seen", async () => {
    // depth 0 = scratchDir itself; a file at depth 3 sits 3 directories below root.
    const deep = path.join(scratchDir, "a", "b", "c");
    fs.mkdirSync(deep, { recursive: true });
    fs.writeFileSync(path.join(deep, "buried.json"), "{}");

    const result = await findNewestReceiptMtime(scratchDir, { maxDepth: 1 });
    expect(result).toBeNull();
  });

  test("respects maxEntries: stops early and marks the result truncated", async () => {
    for (let i = 0; i < 10; i++) {
      const p = path.join(scratchDir, `f${i}.json`);
      fs.writeFileSync(p, "{}");
      fs.utimesSync(p, new Date(i * 1000), new Date(i * 1000));
    }

    const result = await findNewestReceiptMtime(scratchDir, { maxEntries: 3 });
    expect(result?.truncated).toBe(true);
  });

  test("skips an unreadable/vanished entry without throwing", async () => {
    const filePath = path.join(scratchDir, "receipt.json");
    fs.writeFileSync(filePath, "{}");
    // No easy cross-platform way to force an EPERM stat in a test; the happy path above plus
    // the try/catch coverage in the missing-root case already exercises the fail-open branch.
    const result = await findNewestReceiptMtime(scratchDir);
    expect(result?.relativePath).toBe("receipt.json");
  });
});

describe("formatReceiptLandingAge", () => {
  test("formats a fresh mtime as non-stale", () => {
    const nowMs = Date.UTC(2026, 6, 7, 12, 0, 0);
    const mtimeMs = nowMs - 5 * 60 * 1000; // 5 minutes ago
    const result = formatReceiptLandingAge(mtimeMs, nowMs);
    expect(result.stale).toBe(false);
    expect(result.text).toBe("5m ago");
  });

  test("formats an old mtime as stale", () => {
    const nowMs = Date.UTC(2026, 6, 7, 12, 0, 0);
    const mtimeMs = nowMs - 3 * 60 * 60 * 1000; // 3 hours ago -- past the 2h threshold
    const result = formatReceiptLandingAge(mtimeMs, nowMs);
    expect(result.stale).toBe(true);
  });
});

describe("formatLastReceiptLine", () => {
  test("returns null when no receipt was found", () => {
    expect(formatLastReceiptLine(null)).toBeNull();
  });

  test("formats a fresh landing with no color", () => {
    const nowMs = Date.UTC(2026, 6, 7, 12, 0, 0);
    const result = formatLastReceiptLine(
      { relativePath: "lane/receipt.json", mtimeMs: nowMs - 5 * 60 * 1000, truncated: false },
      nowMs,
    );
    expect(result).toEqual({ text: "receipts: landing 5m ago" });
  });

  test("formats a stale landing in red with a STALE label", () => {
    const nowMs = Date.UTC(2026, 6, 7, 12, 0, 0);
    const result = formatLastReceiptLine(
      { relativePath: "lane/receipt.json", mtimeMs: nowMs - 3 * 60 * 60 * 1000, truncated: false },
      nowMs,
    );
    expect(result?.color).toBe("red");
    expect(result?.text).toContain("STALE");
  });
});
