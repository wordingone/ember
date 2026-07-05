// services/receipt-watch.test.ts — R0 receipt-directory watcher.
// Every case gets its own tempdir (hermetic fixtures, builder-protocol rule 4).

import { describe, it, expect, afterEach } from "bun:test";
import { mkdtemp, writeFile, mkdir, rm, utimes } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";
import {
  walkReceiptDir,
  diffReceiptScan,
  startReceiptWatch,
  getReceiptWatchState,
  resetReceiptWatchForTests,
  type WalkEntry,
} from "./receipt-watch.ts";

async function withTempDir(fn: (dir: string) => Promise<void>): Promise<void> {
  const dir = await mkdtemp(join(tmpdir(), "receipt-watch-test-"));
  try {
    await fn(dir);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

describe("walkReceiptDir", () => {
  it("finds .json files and ignores everything else", async () => {
    await withTempDir(async (dir) => {
      await writeFile(join(dir, "a.json"), "{}", "utf-8");
      await writeFile(join(dir, "notes.md"), "hi", "utf-8");
      const found = await walkReceiptDir(dir, 4, { remaining: 1000 });
      expect(found.length).toBe(1);
      expect(found[0]!.path.endsWith("a.json")).toBe(true);
    });
  });

  it("recurses into subdirectories up to maxDepth", async () => {
    await withTempDir(async (dir) => {
      const nested = join(dir, "sub1", "sub2");
      await mkdir(nested, { recursive: true });
      await writeFile(join(nested, "deep.json"), "{}", "utf-8");
      const found = await walkReceiptDir(dir, 4, { remaining: 1000 });
      expect(found.some((f) => f.path.endsWith("deep.json"))).toBe(true);
    });
  });

  it("does not recurse past maxDepth", async () => {
    await withTempDir(async (dir) => {
      const nested = join(dir, "a", "b", "c", "d", "e");
      await mkdir(nested, { recursive: true });
      await writeFile(join(nested, "toodeep.json"), "{}", "utf-8");
      const found = await walkReceiptDir(dir, 1, { remaining: 1000 });
      expect(found.some((f) => f.path.endsWith("toodeep.json"))).toBe(false);
    });
  });

  it("returns [] for a root that does not exist (never throws)", async () => {
    const found = await walkReceiptDir("Z:/definitely/not/a/real/path", 4, { remaining: 1000 });
    expect(found).toEqual([]);
  });

  it("respects a shared entry budget across calls", async () => {
    await withTempDir(async (dir) => {
      for (let i = 0; i < 10; i++) {
        await writeFile(join(dir, `r${i}.json`), "{}", "utf-8");
      }
      const budget = { remaining: 3 };
      const found = await walkReceiptDir(dir, 4, budget);
      expect(found.length).toBeLessThanOrEqual(3);
      expect(budget.remaining).toBe(0);
    });
  });
});

describe("diffReceiptScan — the anti-fixture core", () => {
  it("on the FIRST scan (bootstrapped=false), every file is recorded but NO events fire", () => {
    const found: WalkEntry[] = [
      { path: "/r/a.json", mtimeMs: 100, sizeBytes: 10 },
      { path: "/r/b.json", mtimeMs: 200, sizeBytes: 20 },
    ];
    const { events, nextSeen } = diffReceiptScan(found, new Map(), false);
    expect(events).toEqual([]);
    expect(nextSeen.size).toBe(2);
    expect(nextSeen.get("/r/a.json")).toBe(100);
  });

  it("on a LATER scan, a genuinely new file produces exactly one event", () => {
    const seen = new Map([["/r/a.json", 100]]);
    const found: WalkEntry[] = [
      { path: "/r/a.json", mtimeMs: 100, sizeBytes: 10 },
      { path: "/r/b.json", mtimeMs: 200, sizeBytes: 20 }, // new
    ];
    const { events, nextSeen } = diffReceiptScan(found, seen, true);
    expect(events.length).toBe(1);
    expect(events[0]!.path).toBe("/r/b.json");
    expect(nextSeen.get("/r/b.json")).toBe(200);
  });

  it("a changed mtime on a previously-seen file produces an event (receipt overwritten)", () => {
    const seen = new Map([["/r/a.json", 100]]);
    const found: WalkEntry[] = [{ path: "/r/a.json", mtimeMs: 150, sizeBytes: 99 }];
    const { events } = diffReceiptScan(found, seen, true);
    expect(events.length).toBe(1);
    expect(events[0]!.sizeBytes).toBe(99);
  });

  it("an unchanged file produces no event", () => {
    const seen = new Map([["/r/a.json", 100]]);
    const found: WalkEntry[] = [{ path: "/r/a.json", mtimeMs: 100, sizeBytes: 10 }];
    const { events } = diffReceiptScan(found, seen, true);
    expect(events).toEqual([]);
  });

  it("every event's ts derives from the file's own mtime, not wall-clock now", () => {
    const found: WalkEntry[] = [{ path: "/r/a.json", mtimeMs: 1234567890000, sizeBytes: 1 }];
    const { events } = diffReceiptScan(found, new Map(), true);
    expect(events[0]!.ts).toBe(new Date(1234567890000).toISOString());
  });

  it("a live (post-bootstrap) event's origin is always 'live', never 'backfill'", () => {
    const seen = new Map([["/r/a.json", 100]]);
    const found: WalkEntry[] = [{ path: "/r/a.json", mtimeMs: 200, sizeBytes: 5 }];
    const { events } = diffReceiptScan(found, seen, true);
    expect(events[0]!.origin).toBe("live");
  });
});

describe("diffReceiptScan — team-lead-ruled backfill window (bootstrap only)", () => {
  it("with backfillWindowMs omitted (defaults to 0), a pre-existing file produces no event -- byte-identical to the pre-ruling behavior", () => {
    const nowMs = 1_000_000;
    const found: WalkEntry[] = [{ path: "/r/a.json", mtimeMs: nowMs - 5_000, sizeBytes: 1 }];
    const { events } = diffReceiptScan(found, new Map(), false, { nowMs });
    expect(events).toEqual([]);
  });

  it("a pre-existing file within the window produces a backfill-origin event", () => {
    const nowMs = 1_000_000;
    const found: WalkEntry[] = [{ path: "/r/a.json", mtimeMs: nowMs - 5_000, sizeBytes: 1 }];
    const { events } = diffReceiptScan(found, new Map(), false, { nowMs, backfillWindowMs: 60_000 });
    expect(events.length).toBe(1);
    expect(events[0]!.origin).toBe("backfill");
    expect(events[0]!.path).toBe("/r/a.json");
  });

  it("a pre-existing file OLDER than the window produces no event, even with backfill enabled", () => {
    const nowMs = 1_000_000;
    const found: WalkEntry[] = [{ path: "/r/a.json", mtimeMs: nowMs - 120_000, sizeBytes: 1 }];
    const { events } = diffReceiptScan(found, new Map(), false, { nowMs, backfillWindowMs: 60_000 });
    expect(events).toEqual([]);
  });

  it("a file exactly at the window boundary is included (inclusive <=)", () => {
    const nowMs = 1_000_000;
    const found: WalkEntry[] = [{ path: "/r/a.json", mtimeMs: nowMs - 60_000, sizeBytes: 1 }];
    const { events } = diffReceiptScan(found, new Map(), false, { nowMs, backfillWindowMs: 60_000 });
    expect(events.length).toBe(1);
  });

  it("backfill only applies on the FIRST scan -- a genuinely new file on a LATER scan is 'live' even inside the window", () => {
    const nowMs = 1_000_000;
    const found: WalkEntry[] = [{ path: "/r/a.json", mtimeMs: nowMs - 1_000, sizeBytes: 1 }];
    const { events } = diffReceiptScan(found, new Map(), true, { nowMs, backfillWindowMs: 60_000 });
    expect(events[0]!.origin).toBe("live");
  });
});

describe("startReceiptWatch / getReceiptWatchState — integration (real fs, no fabricated rows)", () => {
  afterEach(() => {
    resetReceiptWatchForTests();
  });

  it("an empty/absent receipts dir yields an honest empty feed, never a synthetic row", async () => {
    await withTempDir(async (dir) => {
      const handle = startReceiptWatch({ dirs: [join(dir, "does-not-exist")], intervalMs: 50 });
      await new Promise((r) => setTimeout(r, 120));
      const state = getReceiptWatchState();
      expect(state.recentEvents).toEqual([]);
      handle.stop();
    });
  });

  it("a receipt written AFTER the watch starts is picked up as a real event with a resolvable path", async () => {
    await withTempDir(async (dir) => {
      const handle = startReceiptWatch({ dirs: [dir], intervalMs: 50 });
      // Let the bootstrap poll run first (establishes empty baseline).
      await new Promise((r) => setTimeout(r, 80));

      const newReceipt = join(dir, "fresh-receipt.json");
      await writeFile(newReceipt, JSON.stringify({ ticket: "TEST" }), "utf-8");
      // Ensure the new file's mtime is observably different from anything already scanned.
      const now = new Date();
      await utimes(newReceipt, now, now);

      await new Promise((r) => setTimeout(r, 150));
      const state = getReceiptWatchState();
      handle.stop();

      expect(state.recentEvents.some((e) => e.path === newReceipt)).toBe(true);
    });
  });

  it("with backfill explicitly disabled (backfillWindowMs:0), a pre-existing receipt is NOT reported on boot -- the original invariant, still available as an opt-out", async () => {
    await withTempDir(async (dir) => {
      const preexisting = join(dir, "old-receipt.json");
      await writeFile(preexisting, JSON.stringify({ ticket: "OLD" }), "utf-8");

      const handle = startReceiptWatch({ dirs: [dir], intervalMs: 50, backfillWindowMs: 0 });
      await new Promise((r) => setTimeout(r, 120));
      const state = getReceiptWatchState();
      handle.stop();

      expect(state.recentEvents.some((e) => e.path === preexisting)).toBe(false);
    });
  });

  it("team-lead ruling: a pre-existing receipt WITHIN the backfill window IS reported at boot, labeled origin:'backfill', never 'live'", async () => {
    await withTempDir(async (dir) => {
      const recent = join(dir, "recent-receipt.json");
      await writeFile(recent, JSON.stringify({ ticket: "RECENT" }), "utf-8");
      // Real, recent mtime (a few seconds old) -- well within any sane backfill window.

      const handle = startReceiptWatch({ dirs: [dir], intervalMs: 50, backfillWindowMs: 60_000 });
      await new Promise((r) => setTimeout(r, 120));
      const state = getReceiptWatchState();
      handle.stop();

      const ev = state.recentEvents.find((e) => e.path === recent);
      expect(ev).toBeDefined();
      expect(ev?.origin).toBe("backfill");
    });
  });

  it("a pre-existing receipt OLDER than the backfill window is still NOT reported (the window is bounded, not unlimited backfill)", async () => {
    await withTempDir(async (dir) => {
      const stale = join(dir, "stale-receipt.json");
      await writeFile(stale, JSON.stringify({ ticket: "STALE" }), "utf-8");
      const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000);
      await utimes(stale, twoDaysAgo, twoDaysAgo);

      // A short window (100ms) makes "older than the window" true immediately and
      // deterministically, without waiting on the real 24h default.
      const handle = startReceiptWatch({ dirs: [dir], intervalMs: 50, backfillWindowMs: 100 });
      await new Promise((r) => setTimeout(r, 120));
      const state = getReceiptWatchState();
      handle.stop();

      expect(state.recentEvents.some((e) => e.path === stale)).toBe(false);
    });
  });

  it("the default backfillWindowMs (when omitted entirely) is RECEIPT_BACKFILL_WINDOW_MS -- a recent pre-existing receipt is reported without the caller having to opt in", async () => {
    await withTempDir(async (dir) => {
      const recent = join(dir, "default-window-receipt.json");
      await writeFile(recent, JSON.stringify({ ticket: "DEFAULT" }), "utf-8");

      const handle = startReceiptWatch({ dirs: [dir], intervalMs: 50 }); // no backfillWindowMs override
      await new Promise((r) => setTimeout(r, 120));
      const state = getReceiptWatchState();
      handle.stop();

      const ev = state.recentEvents.find((e) => e.path === recent);
      expect(ev?.origin).toBe("backfill");
    });
  });
});
