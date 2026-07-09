// services/activity-feed.test.ts — issue #485 rung 1: pure formatter tests + real-fs engine
// tests (fixture receipts, debounce, outage marker lifecycle, watchdog tail-poll, ledger
// append). No fabricated/mocked "activity" — every engine test writes a real fixture file and
// asserts on the engine's actual observed reaction.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  classNameFromPath,
  extractVerdict,
  formatReceiptLine,
  formatPlaceholderLine,
  formatUnparsableLine,
  formatBoardLine,
  parseOutageMarker,
  classifyOutageTransition,
  computeEffectiveMarker,
  formatWatchdogLine,
  isExcludedReceiptPath,
  formatBulkMaterializationLine,
  startActivityFeed,
  getActivityFeedState,
  RECEIPT_RETRY_DELAY_MS,
  MAX_TAIL_LINES_PER_TICK,
  type ActivityFeedHandle,
} from "./activity-feed.ts";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Pure formatters
// ---------------------------------------------------------------------------

describe("classNameFromPath", () => {
  it("returns the immediate parent directory basename", () => {
    expect(classNameFromPath("/repo/receipts/acceptance/foo.json")).toBe("acceptance");
  });
});

describe("extractVerdict", () => {
  it("returns the verdict string when present", () => {
    expect(extractVerdict({ verdict: "GREEN" })).toBe("GREEN");
  });
  it("returns undefined when absent", () => {
    expect(extractVerdict({ other: 1 })).toBeUndefined();
  });
  it("never throws on non-object input", () => {
    expect(extractVerdict(null)).toBeUndefined();
    expect(extractVerdict("string")).toBeUndefined();
    expect(extractVerdict(42)).toBeUndefined();
  });
});

describe("formatReceiptLine", () => {
  it("includes class, filename, and verdict when present", () => {
    const text = formatReceiptLine("/repo/receipts/acceptance/foo.json", { verdict: "GREEN" });
    expect(text).toBe("receipt landed [acceptance] foo.json — GREEN");
  });
  it("omits the verdict suffix when absent", () => {
    const text = formatReceiptLine("/repo/receipts/acceptance/foo.json", { other: 1 });
    expect(text).toBe("receipt landed [acceptance] foo.json");
  });
});

describe("formatPlaceholderLine / formatUnparsableLine", () => {
  it("placeholder names the file", () => {
    expect(formatPlaceholderLine("/x/foo.json")).toBe("(receipt landing…) foo.json");
  });
  it("unparsable names the file", () => {
    expect(formatUnparsableLine("/x/foo.json")).toBe("(receipt unparsable) foo.json");
  });
});

describe("isExcludedReceiptPath", () => {
  it("excludes paths under known non-organic trees", () => {
    expect(isExcludedReceiptPath("/repo/receipts/fixture/acceptance/r1.json")).toBe(true);
    expect(isExcludedReceiptPath("/repo/.avir/plugins/marketplaces/x.json")).toBe(true);
    expect(isExcludedReceiptPath("C:\\repo\\.claude-plugin\\y.json")).toBe(true);
    expect(isExcludedReceiptPath("/repo/node_modules/pkg/z.json")).toBe(true);
  });
  it("does not exclude an ordinary organic receipt path", () => {
    expect(isExcludedReceiptPath("/repo/receipts/acceptance/r1.json")).toBe(false);
  });
});

describe("formatBulkMaterializationLine", () => {
  it("summarizes a count, never lists individual files", () => {
    const text = formatBulkMaterializationLine(["/a.json", "/b.json", "/c.json"]);
    expect(text).toContain("3 receipts");
    expect(text).not.toContain("a.json");
  });
});

describe("formatBoardLine", () => {
  it("counts GREEN/RED/other rows", () => {
    const parsed = { rows: [{ status: "GREEN" }, { status: "GREEN" }, { status: "RED" }, { status: "YELLOW" }] };
    const text = formatBoardLine("/x/board1.json", parsed);
    expect(text).toBe("totality board rendered: 2 GREEN / 1 RED / 1 other (board1.json)");
  });
  it("returns null when rows is missing or not an array", () => {
    expect(formatBoardLine("/x/y.json", {})).toBeNull();
    expect(formatBoardLine("/x/y.json", null)).toBeNull();
    expect(formatBoardLine("/x/y.json", { rows: "nope" })).toBeNull();
  });
});

describe("parseOutageMarker", () => {
  const valid = {
    owner: "jun",
    reason: "probe",
    target: "server",
    started: "2026-07-08T00:00:00Z",
    expires: "2026-07-08T01:00:00Z",
    kill_receipt_ref: "ref-1",
  };
  it("parses a fully-populated marker", () => {
    expect(parseOutageMarker(JSON.stringify(valid))).toEqual(valid);
  });
  it("rejects invalid JSON", () => {
    expect(parseOutageMarker("{ not json")).toBeNull();
  });
  it("rejects a marker missing kill_receipt_ref (never partially honored)", () => {
    const { kill_receipt_ref, ...rest } = valid;
    void kill_receipt_ref;
    expect(parseOutageMarker(JSON.stringify(rest))).toBeNull();
  });
  it("rejects a marker with a blank field", () => {
    expect(parseOutageMarker(JSON.stringify({ ...valid, owner: "" }))).toBeNull();
  });
});

describe("classifyOutageTransition", () => {
  const marker = {
    owner: "jun",
    reason: "probe",
    target: "server",
    started: "2026-07-08T00:00:00Z",
    expires: "2026-07-08T01:00:00Z",
    kill_receipt_ref: "ref-1",
  };
  const nowMs = Date.parse("2026-07-08T00:30:00Z");

  it("reports 'opened' when a marker newly appears", () => {
    const result = classifyOutageTransition(null, marker, nowMs);
    expect(result.transition).toBe("opened");
    expect(result.text).toContain("opened");
    expect(result.effective).toEqual(marker);
  });

  it("reports 'closed' when a previously-effective marker disappears", () => {
    const result = classifyOutageTransition(marker, null, nowMs);
    expect(result.transition).toBe("closed");
    expect(result.text).toContain("closed");
    expect(result.effective).toBeNull();
  });

  it("reports 'none' when nothing changed", () => {
    expect(classifyOutageTransition(null, null, nowMs).transition).toBe("none");
    expect(classifyOutageTransition(marker, marker, nowMs).transition).toBe("none");
  });

  it("treats an expired marker as absent (closed), never extending silently", () => {
    const expiredNow = Date.parse("2026-07-08T02:00:00Z"); // past `expires`
    const result = classifyOutageTransition(marker, marker, expiredNow);
    expect(result.transition).toBe("closed");
    expect(result.effective).toBeNull();
  });
});

describe("computeEffectiveMarker — issue #475: shared expiry check (banner + transition detection)", () => {
  const marker = {
    owner: "jun",
    reason: "probe",
    target: "server",
    started: "2026-07-08T00:00:00Z",
    expires: "2026-07-08T01:00:00Z",
    kill_receipt_ref: "ref-1",
  };

  it("returns null for a null marker", () => {
    expect(computeEffectiveMarker(null, Date.parse("2026-07-08T00:30:00Z"))).toBeNull();
  });

  it("returns the marker unchanged while unexpired", () => {
    const nowMs = Date.parse("2026-07-08T00:30:00Z");
    expect(computeEffectiveMarker(marker, nowMs)).toEqual(marker);
  });

  it("returns null once expires has passed", () => {
    const nowMs = Date.parse("2026-07-08T02:00:00Z");
    expect(computeEffectiveMarker(marker, nowMs)).toBeNull();
  });

  it("treats exactly-at-expires as expired (<=, matching classifyOutageTransition)", () => {
    const atExpiry = Date.parse(marker.expires);
    expect(computeEffectiveMarker(marker, atExpiry)).toBeNull();
  });
});

describe("formatWatchdogLine", () => {
  it("formats a relaunch restart-log row", () => {
    const text = formatWatchdogLine({ target: "cockpit", event: "relaunch", relaunchPid: 4242 });
    expect(text).toBe("cockpit was down, restarted (pid 4242)");
  });
  it("formats a crashloop-backoff row", () => {
    const text = formatWatchdogLine({ target: "server", event: "crashloop-backoff" });
    expect(text).toContain("crashlooping");
  });
  it("formats a marker-overrun row", () => {
    const text = formatWatchdogLine({ target: "cockpit", event: "marker-overrun", owner: "jun" });
    expect(text).toContain("overran");
    expect(text).toContain("jun");
  });
  it("formats a kill-receipt row (no 'event' field, has pids/reason)", () => {
    const text = formatWatchdogLine({ pids: [111], reason: "health-check failed" });
    expect(text).toBe("server killed by watchdog (health-check failed)");
  });
  it("returns null for an unrecognized shape", () => {
    expect(formatWatchdogLine({ foo: "bar" })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Engine — real filesystem, real fs.watch, real timers
// ---------------------------------------------------------------------------

describe("startActivityFeed — engine (real fs)", () => {
  let scratchDir: string;
  let handle: ActivityFeedHandle | null = null;

  beforeEach(() => {
    scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-activity-feed-"));
    fs.mkdirSync(path.join(scratchDir, "receipts"), { recursive: true });
    fs.mkdirSync(path.join(scratchDir, "totality"), { recursive: true });
  });

  afterEach(() => {
    handle?.stop();
    handle = null;
    fs.rmSync(scratchDir, { recursive: true, force: true });
  });

  function baseDeps(overrides: Record<string, string> = {}) {
    return {
      receiptsDir: path.join(scratchDir, "receipts"),
      totalityDir: path.join(scratchDir, "totality"),
      outageMarkerPath: path.join(scratchDir, "planned-outage.json"),
      restartLogPath: path.join(scratchDir, "restart-log.jsonl"),
      watchdogStatePath: path.join(scratchDir, "watchdog-state.json"),
      ledgerPath: path.join(scratchDir, "ledger.jsonl"),
      ...overrides,
    };
  }

  it(
    "renders a line for a new well-formed receipt file and appends the ledger",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300); // let the recursive watcher arm

      const dir = path.join(deps.receiptsDir, "acceptance");
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, "r1.json"), JSON.stringify({ verdict: "GREEN" }));

      await sleep(1200);

      const state = getActivityFeedState();
      const found = state.recentLines.find((l) => l.text.includes("r1.json"));
      expect(found).toBeDefined();
      expect(found?.text).toContain("[acceptance]");
      expect(found?.text).toContain("GREEN");
      expect(found?.source).toBe("receipt");
      expect(found?.path).toContain("r1.json");

      const ledgerRaw = fs.readFileSync(deps.ledgerPath, "utf-8");
      expect(ledgerRaw).toContain("r1.json");
      expect(ledgerRaw).toContain("\"source\":\"receipt\"");
    },
    8000,
  );

  it(
    "debounces a partially-written file: placeholder line then the final parsed line",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300);

      const filePath = path.join(deps.receiptsDir, "partial.json");
      fs.writeFileSync(filePath, "{ this is not valid json");

      await sleep(250);
      let state = getActivityFeedState();
      expect(
        state.recentLines.some((l) => l.text.includes("receipt landing…") && l.text.includes("partial.json")),
      ).toBe(true);

      fs.writeFileSync(filePath, JSON.stringify({ verdict: "RED" }));

      await sleep(RECEIPT_RETRY_DELAY_MS + 500);
      state = getActivityFeedState();
      expect(
        state.recentLines.some(
          (l) => l.text.includes("receipt landed") && l.text.includes("partial.json") && l.text.includes("RED"),
        ),
      ).toBe(true);
    },
    8000,
  );

  it(
    "renders a board line for a new totality receipt",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300);

      fs.writeFileSync(
        path.join(deps.totalityDir, "board1.json"),
        JSON.stringify({ rows: [{ status: "GREEN" }, { status: "GREEN" }, { status: "RED" }] }),
      );

      await sleep(1200);
      const state = getActivityFeedState();
      const found = state.recentLines.find((l) => l.source === "board");
      expect(found).toBeDefined();
      expect(found?.text).toContain("2 GREEN");
      expect(found?.text).toContain("1 RED");
    },
    8000,
  );

  it(
    "renders outage-opened then outage-closed lines across the marker lifecycle",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);

      const future = new Date(Date.now() + 60_000).toISOString();
      fs.writeFileSync(
        deps.outageMarkerPath,
        JSON.stringify({
          owner: "tester",
          reason: "probe",
          target: "server",
          started: new Date().toISOString(),
          expires: future,
          kill_receipt_ref: "ref-1",
        }),
      );

      await sleep(1300);
      let state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.source === "outage" && l.text.includes("opened"))).toBe(true);

      fs.rmSync(deps.outageMarkerPath);
      await sleep(1300);

      state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.source === "outage" && l.text.includes("closed"))).toBe(true);
    },
    8000,
  );

  it(
    "#475: a BOM-prefixed marker file (PowerShell -Encoding utf8 default) still opens the outage",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);

      const future = new Date(Date.now() + 60_000).toISOString();
      const bomPrefixed =
        "﻿" +
        JSON.stringify({
          owner: "tester",
          reason: "probe",
          target: "server",
          started: new Date().toISOString(),
          expires: future,
          kill_receipt_ref: "ref-1",
        });
      fs.writeFileSync(deps.outageMarkerPath, bomPrefixed, "utf-8");

      await sleep(1300);
      const state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.source === "outage" && l.text.includes("opened"))).toBe(true);
    },
    8000,
  );

  it(
    "renders a watchdog line from a new restart-log row",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300);

      fs.appendFileSync(
        deps.restartLogPath,
        JSON.stringify({ ts: new Date().toISOString(), target: "cockpit", event: "relaunch", relaunchPid: 4242 }) +
          "\n",
      );

      await sleep(1300);
      const state = getActivityFeedState();
      const found = state.recentLines.find((l) => l.source === "watchdog");
      expect(found).toBeDefined();
      expect(found?.text).toContain("cockpit");
      expect(found?.text).toContain("4242");
    },
    8000,
  );

  it(
    "resolves kill_receipts_path from watchdog-state.json and tails kill-receipt rows",
    async () => {
      const killReceiptsPath = path.join(scratchDir, "kill-receipts.jsonl");
      const watchdogStatePath = path.join(scratchDir, "watchdog-state.json");
      fs.writeFileSync(watchdogStatePath, JSON.stringify({ kill_receipts_path: killReceiptsPath }));
      fs.writeFileSync(killReceiptsPath, "");

      const deps = baseDeps({ watchdogStatePath });
      handle = startActivityFeed(deps);
      await sleep(400); // let the async kill_receipts_path resolution complete

      fs.appendFileSync(
        killReceiptsPath,
        JSON.stringify({ ts: new Date().toISOString(), pids: [111], reason: "health-check failed" }) + "\n",
      );

      await sleep(1300);
      const state = getActivityFeedState();
      const found = state.recentLines.find((l) => l.source === "watchdog" && l.text.includes("killed"));
      expect(found).toBeDefined();
      expect(found?.text).toContain("health-check failed");
    },
    8000,
  );

  it(
    "never crashes when the receipts dir does not exist yet",
    async () => {
      const deps = baseDeps({ receiptsDir: path.join(scratchDir, "does-not-exist") });
      expect(() => {
        handle = startActivityFeed(deps);
      }).not.toThrow();
      await sleep(200);
      expect(getActivityFeedState().recentLines).toEqual([]);
    },
    5000,
  );

  // #576: MAX_TAIL_LINES_PER_TICK containment. Seeding the restart-log file BEFORE
  // startActivityFeed() runs reproduces the real trigger (freshTailState() starts every process
  // boot at byte offset 0, so the first tick after boot always sees the file's full current
  // content at once) -- this is the same "boot replay" mechanism the natural experiment in
  // issue #576 confirmed live.
  it(
    "collapses a tail-poll burst over the cap into one summary line instead of N individual ones",
    async () => {
      const deps = baseDeps();
      const lineCount = MAX_TAIL_LINES_PER_TICK + 5;
      const rows = Array.from({ length: lineCount }, (_, i) =>
        JSON.stringify({ ts: new Date().toISOString(), target: "cockpit", event: "relaunch", relaunchPid: i }),
      );
      fs.writeFileSync(deps.restartLogPath, rows.join("\n") + "\n");

      handle = startActivityFeed(deps);
      await sleep(1300); // first tail-poll tick fires ~TAIL_POLL_INTERVAL_MS after boot

      const state = getActivityFeedState();
      const watchdogLines = state.recentLines.filter((l) => l.source === "watchdog");
      expect(watchdogLines.length).toBe(1);
      expect(watchdogLines[0]?.text).toContain(`${lineCount} watchdog events collapsed`);
      expect(watchdogLines[0]?.text).toContain("tail-poll anomaly");

      // never one individual per-row line for this tick — the cap must suppress ALL of them,
      // not just the ones past the threshold.
      expect(state.recentLines.some((l) => l.text.includes("relaunchPid"))).toBe(false);
    },
    8000,
  );

  it(
    "still renders individual lines when a batch lands exactly at the cap (no false-positive collapse)",
    async () => {
      const deps = baseDeps();
      const lineCount = MAX_TAIL_LINES_PER_TICK; // at the threshold, not over it
      const rows = Array.from({ length: lineCount }, (_, i) =>
        JSON.stringify({ ts: new Date().toISOString(), target: "cockpit", event: "relaunch", relaunchPid: i }),
      );
      fs.writeFileSync(deps.restartLogPath, rows.join("\n") + "\n");

      handle = startActivityFeed(deps);
      await sleep(1300);

      const state = getActivityFeedState();
      const watchdogLines = state.recentLines.filter((l) => l.source === "watchdog");
      expect(watchdogLines.length).toBe(lineCount);
      expect(watchdogLines.some((l) => l.text.includes("collapsed"))).toBe(false);
    },
    8000,
  );

  it(
    "writes a tail-poll diagnostic log row per tick, capped or not",
    async () => {
      const tailPollDebugLogPath = path.join(scratchDir, "tailpoll-debug.jsonl");
      const deps = baseDeps({ tailPollDebugLogPath });
      fs.appendFileSync(
        deps.restartLogPath,
        JSON.stringify({ ts: new Date().toISOString(), target: "cockpit", event: "relaunch", relaunchPid: 1 }) + "\n",
      );

      handle = startActivityFeed(deps);
      await sleep(1300);

      const raw = fs.readFileSync(tailPollDebugLogPath, "utf-8");
      const rows = raw
        .split("\n")
        .filter((l) => l.trim().length > 0)
        .map((l) => JSON.parse(l) as Record<string, unknown>);

      expect(rows.some((r) => r["event"] === "startActivityFeed")).toBe(true);
      expect(rows.some((r) => r["event"] === "freshTailState" && r["file"] === "restart-log")).toBe(true);
      const tick = rows.find((r) => r["event"] === "pollTail" && r["file"] === "restart-log");
      expect(tick).toBeDefined();
      expect(tick).toHaveProperty("lineCount");
      expect(tick).toHaveProperty("capped", false);
      expect(tick).toHaveProperty("byteOffsetBefore");
      expect(tick).toHaveProperty("byteOffsetAfter");
    },
    8000,
  );
});

// ---------------------------------------------------------------------------
// P0-B — watermark, exclusion, burst-coalescing (issue #561 companion fix: the flood source)
// ---------------------------------------------------------------------------

describe("startActivityFeed — P0-B watermark/exclusion/coalescing (real fs)", () => {
  let scratchDir: string;
  let handle: ActivityFeedHandle | null = null;

  beforeEach(() => {
    scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-activity-feed-p0b-"));
    fs.mkdirSync(path.join(scratchDir, "receipts"), { recursive: true });
    fs.mkdirSync(path.join(scratchDir, "totality"), { recursive: true });
  });

  afterEach(() => {
    handle?.stop();
    handle = null;
    fs.rmSync(scratchDir, { recursive: true, force: true });
  });

  function baseDeps(overrides: Record<string, string> = {}) {
    return {
      receiptsDir: path.join(scratchDir, "receipts"),
      totalityDir: path.join(scratchDir, "totality"),
      outageMarkerPath: path.join(scratchDir, "planned-outage.json"),
      restartLogPath: path.join(scratchDir, "restart-log.jsonl"),
      watchdogStatePath: path.join(scratchDir, "watchdog-state.json"),
      ledgerPath: path.join(scratchDir, "ledger.jsonl"),
      watermarkPath: path.join(scratchDir, "watermark.json"),
      ...overrides,
    };
  }

  it(
    "excludes receipts under a known non-organic path segment -- never rendered, sibling organic receipt still is",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300);

      const excludedDir = path.join(deps.receiptsDir, "fixture", "acceptance");
      fs.mkdirSync(excludedDir, { recursive: true });
      fs.writeFileSync(path.join(excludedDir, "r1.json"), JSON.stringify({ verdict: "GREEN" }));

      const organicDir = path.join(deps.receiptsDir, "acceptance");
      fs.mkdirSync(organicDir, { recursive: true });
      fs.writeFileSync(path.join(organicDir, "r2.json"), JSON.stringify({ verdict: "GREEN" }));

      await sleep(1200);
      const state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.text.includes("r1.json"))).toBe(false);
      expect(state.recentLines.some((l) => l.text.includes("r2.json"))).toBe(true);
    },
    8000,
  );

  it(
    "coalesces a burst of simultaneously-materialized files into one summarized line, not N individual lines",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300);

      const dir = path.join(deps.receiptsDir, "bulk");
      fs.mkdirSync(dir, { recursive: true });
      const N = 6;
      for (let i = 0; i < N; i++) {
        fs.writeFileSync(path.join(dir, `r${i}.json`), JSON.stringify({ verdict: "GREEN" }));
      }

      await sleep(1200);
      const state = getActivityFeedState();

      const individualLines = state.recentLines.filter(
        (l) => l.text.includes("receipt landed") && /r\d\.json/.test(l.text),
      );
      expect(individualLines.length).toBe(0);

      const summary = state.recentLines.find((l) => l.text.includes("materialized at once"));
      expect(summary).toBeDefined();
      expect(summary?.text).toContain(`${N} receipts`);
    },
    8000,
  );

  it(
    "never replays a file re-materialized with byte-identical content across a restart (the git-checkout / restart-flood shape)",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300);

      const dir = path.join(deps.receiptsDir, "acceptance");
      fs.mkdirSync(dir, { recursive: true });
      const filePath = path.join(dir, "persisted.json");
      const content = JSON.stringify({ verdict: "GREEN" });
      fs.writeFileSync(filePath, content);

      await sleep(1200); // let it fully render and settle its watermark entry (mtime + content hash)
      let state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.text.includes("persisted.json"))).toBe(true);

      const watermarkRaw = fs.readFileSync(deps.watermarkPath, "utf-8");
      const watermark = JSON.parse(watermarkRaw) as Record<string, { mtimeMs: number; hash: string }>;
      expect(typeof watermark[filePath]?.hash).toBe("string");
      expect(watermark[filePath]!.hash.length).toBeGreaterThan(0);

      // Simulate a process restart against the SAME watermark file/receipts dir, THEN a real
      // re-write of byte-identical content -- exactly what `git checkout` does to an already-
      // rendered receipt on every landing PR merge (content unchanged, mtime freshly re-stamped
      // to checkout-time). A fresh engine sharing this watermark must not replay it: mtime alone
      // would call this "new", so the content-hash fallback is what has to catch it.
      handle?.stop();
      handle = startActivityFeed(deps);
      await sleep(300);

      fs.writeFileSync(filePath, content); // same bytes, genuinely fresh mtime from a real write

      await sleep(1200);
      state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.text.includes("persisted.json"))).toBe(false);

      // Prove the restarted engine is genuinely alive/watching (not silently dead) -- a fresh,
      // never-before-seen receipt must still render normally.
      fs.writeFileSync(path.join(dir, "fresh-after-restart.json"), JSON.stringify({ verdict: "GREEN" }));
      await sleep(1200);
      state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.text.includes("fresh-after-restart.json"))).toBe(true);
    },
    12000,
  );

  it(
    "still re-renders when a previously-settled path's content genuinely changes (the hash fallback never over-suppresses)",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300);

      const dir = path.join(deps.receiptsDir, "acceptance");
      fs.mkdirSync(dir, { recursive: true });
      const filePath = path.join(dir, "changed.json");
      fs.writeFileSync(filePath, JSON.stringify({ verdict: "GREEN" }));

      await sleep(1200);
      let state = getActivityFeedState();
      expect(
        state.recentLines.some((l) => l.text.includes("changed.json") && l.text.includes("GREEN")),
      ).toBe(true);

      handle?.stop();
      handle = startActivityFeed(deps);
      await sleep(300);

      fs.writeFileSync(filePath, JSON.stringify({ verdict: "RED" })); // genuinely different content

      await sleep(1200);
      state = getActivityFeedState();
      expect(
        state.recentLines.some((l) => l.text.includes("changed.json") && l.text.includes("RED")),
      ).toBe(true);
    },
    12000,
  );

  it(
    "the seven pre-existing engine behaviors are unaffected by the watermark/exclusion/coalescing layer",
    async () => {
      // Narrow smoke check (the full pre-existing suite above is the real regression gate) --
      // confirms a single well-formed receipt still renders promptly through the new gate.
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300);

      const dir = path.join(deps.receiptsDir, "acceptance");
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, "smoke.json"), JSON.stringify({ verdict: "GREEN" }));

      await sleep(1200);
      const state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.text.includes("smoke.json"))).toBe(true);
    },
    8000,
  );
});
