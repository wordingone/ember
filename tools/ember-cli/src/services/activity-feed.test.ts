// services/activity-feed.test.ts — merged R0 activity feed (runs + receipts).

import { describe, it, expect } from "bun:test";
import { mkdtemp, writeFile, rm } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";
import { mergeActivityFeed, verifyRowsProvenance, type ActivityRow } from "./activity-feed.ts";
import type { ResolvedRunState } from "./runs-registry.ts";
import type { ReceiptEvent } from "./receipt-watch.ts";

async function withTempDir(fn: (dir: string) => Promise<void>): Promise<void> {
  const dir = await mkdtemp(join(tmpdir(), "activity-feed-test-"));
  try {
    await fn(dir);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function runState(overrides: Partial<ResolvedRunState> = {}): ResolvedRunState {
  return {
    run_id: "r1", ts: "2026-07-04T08:00:00Z", event: "started", milestone: "1-hour",
    status: "running", provenancePath: "a.log", provenanceResolves: true,
    ...overrides,
  };
}

describe("mergeActivityFeed", () => {
  it("returns [] when both sources are empty -- the honest 'no live activity' state", () => {
    expect(mergeActivityFeed([], [])).toEqual([]);
  });

  it("merges runs and receipts into one newest-first list", () => {
    const runs: ResolvedRunState[] = [runState({ ts: "2026-07-04T08:00:00Z" })];
    const receipts: ReceiptEvent[] = [
      { ts: "2026-07-04T09:00:00Z", path: "b.json", sizeBytes: 10, origin: "live" },
    ];
    const rows = mergeActivityFeed(runs, receipts);
    expect(rows.length).toBe(2);
    // Newest first: the receipt (09:00) before the run (08:00).
    expect(rows[0]!.kind).toBe("receipt");
    expect(rows[1]!.kind).toBe("run");
  });

  it("every row carries a non-empty provenancePath", () => {
    const runs: ResolvedRunState[] = [runState({ provenancePath: "the.log" })];
    const rows = mergeActivityFeed(runs, []);
    expect(rows[0]!.provenancePath).toBe("the.log");
  });

  it("a running row names the pid when known", () => {
    const runs: ResolvedRunState[] = [runState({ status: "running", pid: 42, milestone: "3-hour" })];
    const rows = mergeActivityFeed(runs, []);
    expect(rows[0]!.label).toContain("running");
    expect(rows[0]!.label).toContain("3-hour");
    expect(rows[0]!.label).toContain("42");
  });

  it("a completed row's label reflects the RE-DERIVED status, not the raw last event field", () => {
    const runs: ResolvedRunState[] = [runState({ event: "completed", status: "completed", milestone: "1-hour" })];
    const rows = mergeActivityFeed(runs, []);
    expect(rows[0]!.label).toContain("completed");
  });

  it("a failed row's label includes the return code when known", () => {
    const runs: ResolvedRunState[] = [runState({ status: "failed", returncode: 1, milestone: "1-hour" })];
    const rows = mergeActivityFeed(runs, []);
    expect(rows[0]!.label).toContain("failed");
    expect(rows[0]!.label).toContain("1");
  });

  it("an 'unknown' row (pid gone, no terminal event ever recorded) never fabricates a completed/failed verdict", () => {
    const runs: ResolvedRunState[] = [runState({ status: "unknown", milestone: "3-hour" })];
    const rows = mergeActivityFeed(runs, []);
    expect(rows[0]!.label).toContain("unknown");
    expect(rows[0]!.label).not.toContain("completed");
    expect(rows[0]!.label).not.toContain("failed");
  });

  it("team-lead ruling: a backfill-origin receipt is labeled 'recent (pre-session)' in its row, never plain 'receipt written'", () => {
    const receipts: ReceiptEvent[] = [
      { ts: "2026-07-04T09:00:00Z", path: "b.json", sizeBytes: 10, origin: "backfill" },
    ];
    const rows = mergeActivityFeed([], receipts);
    expect(rows[0]!.origin).toBe("backfill");
    expect(rows[0]!.label).toContain("pre-session");
    expect(rows[0]!.label).not.toContain("receipt written");
  });

  it("a live-origin receipt keeps the plain 'receipt written' label", () => {
    const receipts: ReceiptEvent[] = [
      { ts: "2026-07-04T09:00:00Z", path: "c.json", sizeBytes: 10, origin: "live" },
    ];
    const rows = mergeActivityFeed([], receipts);
    expect(rows[0]!.origin).toBe("live");
    expect(rows[0]!.label).toContain("receipt written");
    expect(rows[0]!.label).not.toContain("pre-session");
  });

  it("run rows never carry an origin field (the concept is receipt-only)", () => {
    const runs: ResolvedRunState[] = [runState()];
    const rows = mergeActivityFeed(runs, []);
    expect(rows[0]!.origin).toBeUndefined();
  });
});

describe("verifyRowsProvenance -- the R0 hard rail, re-checked live", () => {
  it("marks a row false when its provenance path does not resolve, even if the row claimed true", async () => {
    const rows: ActivityRow[] = [
      { kind: "receipt", ts: "t", label: "l", provenancePath: "Z:/nope/nope.json", provenanceResolves: true },
    ];
    const verified = await verifyRowsProvenance(rows);
    expect(verified[0]!.provenanceResolves).toBe(false);
  });

  it("marks a row true when its provenance path genuinely resolves on disk", async () => {
    await withTempDir(async (dir) => {
      const p = join(dir, "real.json");
      await writeFile(p, "{}", "utf-8");
      const rows: ActivityRow[] = [
        { kind: "receipt", ts: "t", label: "l", provenancePath: p, provenanceResolves: false },
      ];
      const verified = await verifyRowsProvenance(rows);
      expect(verified[0]!.provenanceResolves).toBe(true);
    });
  });

  it("filtering verified rows for provenanceResolves===true never includes an unresolvable path", async () => {
    await withTempDir(async (dir) => {
      const real = join(dir, "real.json");
      await writeFile(real, "{}", "utf-8");
      const rows: ActivityRow[] = [
        { kind: "receipt", ts: "t1", label: "real", provenancePath: real, provenanceResolves: true },
        { kind: "receipt", ts: "t2", label: "fake", provenancePath: join(dir, "fake.json"), provenanceResolves: true },
      ];
      const verified = await verifyRowsProvenance(rows);
      const onlyResolvable = verified.filter((r) => r.provenanceResolves);
      expect(onlyResolvable.length).toBe(1);
      expect(onlyResolvable[0]!.label).toBe("real");
    });
  });
});
