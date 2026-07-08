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
  formatWatchdogLine,
  startActivityFeed,
  getActivityFeedState,
  RECEIPT_RETRY_DELAY_MS,
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
});
