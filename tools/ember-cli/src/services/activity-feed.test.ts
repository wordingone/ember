// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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
  formatWatchdogFallbackLine,
  isExcludedReceiptPath,
  formatBulkMaterializationLine,
  isGoalSessionRelativePath,
  formatGoalReceiptLine,
  startActivityFeed,
  getActivityFeedState,
  RECEIPT_RETRY_DELAY_MS,
  MAX_TAIL_LINES_PER_TICK,
  BoundedSet,
  MAX_TRACKED_PATHS,
  MAX_GOAL_TAIL_STATES,
  boundRecordKeys,
  setBoundedMapEntry,
  createSingleFlightRunner,
  type ActivityFeedHandle,
  type WatchdogRow,
} from "./activity-feed.ts";
import type { GoalReceiptRow } from "./goal-receipts.ts";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}


describe("issue #756 bounded activity-feed bookkeeping", () => {
  it("declares the production bookkeeping capacities", () => {
    expect(MAX_TRACKED_PATHS).toBe(5000);
    expect(MAX_GOAL_TAIL_STATES).toBe(50);
  });

  it("evicts oldest dedupe keys while retaining the newest bounded window", () => {
    const keys = new BoundedSet<string>(2);
    keys.add("one");
    keys.add("two");
    keys.add("three");

    expect(keys.size).toBe(2);
    expect(keys.has("one")).toBe(false);
    expect(keys.has("two")).toBe(true);
    expect(keys.has("three")).toBe(true);
  });

  it("bounds durable watermark and goal-tail maps by oldest insertion", () => {
    const watermark: Record<string, unknown> = { one: 1, two: 2, three: 3 };
    boundRecordKeys(watermark, 2);
    expect(watermark).toEqual({ two: 2, three: 3 });

    const tails = new Map<string, number>();
    setBoundedMapEntry(tails, "one", 1, 2);
    setBoundedMapEntry(tails, "two", 2, 2);
    setBoundedMapEntry(tails, "three", 3, 2);
    expect([...tails.entries()]).toEqual([["two", 2], ["three", 3]]);
  });

  it("does not begin an overlapping tail tick until the in-flight tick settles", async () => {
    const runSingleFlight = createSingleFlightRunner();
    let release!: () => void;
    const first = new Promise<void>((resolve) => { release = resolve; });
    let runs = 0;

    expect(runSingleFlight(async () => { runs += 1; await first; })).toBe(true);
    expect(runSingleFlight(async () => { runs += 1; })).toBe(false);
    expect(runs).toBe(1);

    release();
    await sleep(0);
    expect(runSingleFlight(async () => { runs += 1; })).toBe(true);
    await sleep(0);
    expect(runs).toBe(2);
  });
});
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

  // issue #616: a real kill-receipt row whose match_rule verifiably names the serving process
  // (liveness-watchdog.ps1's own Write-KillReceiptRow call on the server watchdog's kill path) is
  // the ONLY shape allowed to render as a "server" event -- and the actor comes from the row's
  // own `script` field, never a hardcoded "watchdog".
  it("formats a real server kill-receipt row (script + match_rule name llama-server.exe)", () => {
    const text = formatWatchdogLine({
      ts: "2026-07-05T03:11:00Z",
      script: "liveness-watchdog",
      pids: [9001],
      match_rule:
        "cmdline-verified via Get-CimInstance Win32_Process: Name=llama-server.exe, CommandLine contains <path>/llama-server.exe",
      reason: "consecutive /health failures (3) at http://127.0.0.1:8080/health",
      survivors_expected: "none",
    });
    expect(text).toBe(
      "server killed by liveness-watchdog (consecutive /health failures (3) at http://127.0.0.1:8080/health)",
    );
  });

  // issue #616 regression: the exact three rows from the 2026-07-10 cockpit-relaunch incident
  // (shared vigil kill-receipts ledger, lines 65204-65206; local path prefixes redacted to
  // <path> per the repo's no-local-paths landing rule). None of these kill the server
  // -- match_rule names the OLD cockpit binary and the OLD watchdog powershell host -- so none
  // may ever render as "server killed by watchdog". The pre-fix code fabricated exactly that line
  // for all three (any row with a `pids` array matched unconditionally).
  it("never renders 'server killed' for the 2026-07-10 cockpit-relaunch incident rows (regression)", () => {
    const incidentRows: WatchdogRow[] = [
      {
        ts: "2026-07-10T00:26:14Z",
        script: "cockpitrelaunch",
        pids: [41244],
        match_rule:
          "cmdline ember-cockpit-7fbf4ef.exe verified via Get-Process Path field == <path>/ember-cockpit-7fbf4ef.exe",
        survivors_expected:
          "none; hwnd 1968534 tab owner is WindowsTerminal PID 22824 (shared, hosts other founder/CC windows) -- NOT touched by this kill, only the child process 41244 dies",
      },
      {
        ts: "2026-07-10T00:31:02Z",
        script: "cockpitrelaunch",
        pids: [36980],
        match_rule:
          "watchdog powershell.exe verified via Win32_Process CommandLine liveness-watchdog.ps1 -LauncherBatPath launch-cockpit-gpu-free.bat; stopping to repoint LauncherBatPath to normal-mode instrumented launcher before it fires another GPU-free auto-restart",
        survivors_expected: "none for this PID; will relaunch same script (liveness-watchdog.ps1)",
      },
      {
        ts: "2026-07-10T00:31:20Z",
        script: "cockpitrelaunch",
        pids: [35796],
        match_rule:
          "cmdline <path>/ember-cockpit-7fbf4ef.exe verified via Win32_Process CommandLine; this is the watchdog auto-restart resurrection of the stale GPU-free binary",
        survivors_expected:
          "none; parent cmd/node shim (PID 40024 and ancestors) is a one-shot launcher wrapper, expected to have already exited or die with no further children",
      },
    ];
    for (const row of incidentRows) {
      const text = formatWatchdogLine(row);
      expect(text).toBeNull(); // falls through to the caller's verbatim fallback, never a paraphrase
      expect(text).not.toBe("server killed by watchdog (reason unavailable)");
    }
  });

  it("returns null (unmappable) for a kill-receipt row missing a script actor", () => {
    // no `script` field at all -- cannot name WHO acted, so no confident attribution is possible.
    expect(formatWatchdogLine({ pids: [111], reason: "health-check failed" })).toBeNull();
  });

  it("returns null (unmappable) for a kill-receipt row whose match_rule names a non-server process", () => {
    const text = formatWatchdogLine({
      script: "somefounder",
      pids: [222],
      match_rule: "cmdline notepad.exe verified via Get-Process",
      reason: "stray window cleanup",
    });
    expect(text).toBeNull();
  });

  it("returns null for an unrecognized shape", () => {
    expect(formatWatchdogLine({ foo: "bar" })).toBeNull();
  });
});

describe("formatWatchdogFallbackLine", () => {
  it("renders the row's raw line verbatim, never a paraphrase", () => {
    const rawLine = JSON.stringify({
      ts: "2026-07-10T00:26:14Z",
      script: "cockpitrelaunch",
      pids: [41244],
      match_rule: "cmdline ember-cockpit-7fbf4ef.exe verified via Get-Process",
    });
    const text = formatWatchdogFallbackLine(rawLine);
    expect(text).toContain(rawLine);
    expect(text).not.toContain("killed by watchdog");
    expect(text).not.toContain("server");
  });
});

// ---------------------------------------------------------------------------
// Goal-organ receipt rows (ember issue #211 §7 delta 4)
// ---------------------------------------------------------------------------

describe("isGoalSessionRelativePath", () => {
  it("matches a goal-sessions jsonl path with forward slashes", () => {
    expect(isGoalSessionRelativePath("goal-sessions/session-20260709T000000Z.jsonl")).toBe(true);
  });
  it("matches a goal-sessions jsonl path with backslashes (Windows watch callback)", () => {
    expect(isGoalSessionRelativePath("goal-sessions\\session-20260709T000000Z.jsonl")).toBe(true);
  });
  it("rejects an ordinary receipt path", () => {
    expect(isGoalSessionRelativePath("acceptance/r1.json")).toBe(false);
  });
  it("rejects a non-jsonl file even if it sits in goal-sessions", () => {
    expect(isGoalSessionRelativePath("goal-sessions/session-x.json")).toBe(false);
  });
  it("requires an exact path-segment match, never a substring", () => {
    expect(isGoalSessionRelativePath("goal-sessions-similar/x.jsonl")).toBe(false);
  });
});

describe("formatGoalReceiptLine", () => {
  function row(overrides: Partial<GoalReceiptRow> = {}): GoalReceiptRow {
    return { ts: "2026-07-09T00:00:00.000Z", event: "created", ...overrides };
  }

  it("formats a created row with the truncated objective", () => {
    const text = formatGoalReceiptLine(row({ event: "created", detail: { objective: "ship the thing" } }));
    expect(text).toBe('goal created: "ship the thing"');
  });

  it("truncates a long objective", () => {
    const long = "x".repeat(120);
    const text = formatGoalReceiptLine(row({ event: "created", detail: { objective: long } }));
    expect(text?.length).toBeLessThan(long.length);
    expect(text).toContain("…");
  });

  it("formats a status_changed row with from -> to and an optional reason", () => {
    const text = formatGoalReceiptLine(
      row({ event: "status_changed", detail: { from: "Active", to: "Blocked", reason: "same blocker x3" } }),
    );
    expect(text).toBe("goal status: Active -> Blocked (same blocker x3)");
  });

  it("omits the reason suffix when absent", () => {
    const text = formatGoalReceiptLine(row({ event: "status_changed", detail: { from: "Active", to: "Complete" } }));
    expect(text).toBe("goal status: Active -> Complete");
  });

  it("formats objective_edited and cleared as fixed one-liners", () => {
    expect(formatGoalReceiptLine(row({ event: "objective_edited" }))).toBe("goal objective edited");
    expect(formatGoalReceiptLine(row({ event: "cleared" }))).toBe("goal cleared");
  });

  it("formats continuation_fired distinctly for continue vs budget_wrapup", () => {
    const continueText = formatGoalReceiptLine(row({ event: "continuation_fired", detail: { kind: "continue" } }));
    const wrapupText = formatGoalReceiptLine(
      row({ event: "continuation_fired", detail: { kind: "budget_wrapup" } }),
    );
    expect(continueText).toContain("autonomous turn");
    expect(wrapupText).toContain("budget wrap-up");
  });

  it("excludes continuation_skipped and usage_recorded from the visible feed", () => {
    expect(formatGoalReceiptLine(row({ event: "continuation_skipped" }))).toBeNull();
    expect(formatGoalReceiptLine(row({ event: "usage_recorded" }))).toBeNull();
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

      // #616: the full real row shape liveness-watchdog.ps1's Write-KillReceiptRow emits on the
      // server kill path -- actor in `script`, serving binary named in `match_rule`.
      fs.appendFileSync(
        killReceiptsPath,
        JSON.stringify({
          ts: new Date().toISOString(),
          script: "liveness-watchdog",
          pids: [111],
          match_rule: "cmdline-verified via Get-CimInstance Win32_Process: Name=llama-server.exe",
          reason: "health-check failed",
          survivors_expected: "none",
        }) + "\n",
      );

      await sleep(1300);
      const state = getActivityFeedState();
      const found = state.recentLines.find((l) => l.source === "watchdog" && l.text.includes("killed"));
      expect(found).toBeDefined();
      expect(found?.text).toBe("server killed by liveness-watchdog (health-check failed)");
    },
    8000,
  );

  // issue #616 bar 3/4: an unmappable kill-receipt row (real 2026-07-10 incident row -- names a
  // cockpit binary, not the server) falls through the ENGINE verbatim, never as a paraphrase.
  it(
    "renders an unmappable kill-receipt row verbatim through the tail-poll path (#616)",
    async () => {
      const killReceiptsPath = path.join(scratchDir, "kill-receipts.jsonl");
      const watchdogStatePath = path.join(scratchDir, "watchdog-state.json");
      fs.writeFileSync(watchdogStatePath, JSON.stringify({ kill_receipts_path: killReceiptsPath }));
      fs.writeFileSync(killReceiptsPath, "");

      const deps = baseDeps({ watchdogStatePath });
      handle = startActivityFeed(deps);
      await sleep(400);

      const incidentRow = JSON.stringify({
        ts: "2026-07-10T00:26:14Z",
        script: "cockpitrelaunch",
        pids: [41244],
        match_rule: "cmdline ember-cockpit-7fbf4ef.exe verified via Get-Process Path field",
        survivors_expected: "none; only the child process 41244 dies",
      });
      fs.appendFileSync(killReceiptsPath, incidentRow + "\n");

      await sleep(1300);
      const state = getActivityFeedState();
      const found = state.recentLines.find((l) => l.source === "watchdog");
      expect(found).toBeDefined();
      expect(found?.text).toContain(incidentRow); // verbatim passthrough of the row itself
      expect(found?.text).not.toContain("killed by watchdog");
      expect(state.recentLines.some((l) => l.text.includes("server killed"))).toBe(false);
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

  // #576: MAX_TAIL_LINES_PER_TICK remains defense-in-depth for a large LIVE append even though
  // completed rows present before boot are now baselined and never replayed.
  it(
    "collapses a tail-poll burst over the cap into one summary line instead of N individual ones",
    async () => {
      const deps = baseDeps();
      const lineCount = MAX_TAIL_LINES_PER_TICK + 5;
      const rows = Array.from({ length: lineCount }, (_, i) =>
        JSON.stringify({ ts: new Date().toISOString(), target: "cockpit", event: "relaunch", relaunchPid: i }),
      );
      handle = startActivityFeed(deps);
      fs.writeFileSync(deps.restartLogPath, rows.join("\n") + "\n");
      await sleep(1300); // first tail-poll tick sees this live append after boot

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
      handle = startActivityFeed(deps);
      fs.writeFileSync(deps.restartLogPath, rows.join("\n") + "\n");
      await sleep(1300);

      const state = getActivityFeedState();
      const watchdogLines = state.recentLines.filter((l) => l.source === "watchdog");
      expect(watchdogLines.length).toBe(lineCount);
      expect(watchdogLines.some((l) => l.text.includes("collapsed"))).toBe(false);
    },
    8000,
  );

  it(
    "baselines the restart log at boot and never replays completed rows after a cockpit restart",
    async () => {
      const deps = baseDeps();
      const historicalRow = JSON.stringify({
        ts: new Date().toISOString(),
        target: "cockpit",
        event: "relaunch",
        relaunchPid: 10,
      });
      fs.writeFileSync(deps.restartLogPath, historicalRow + "\n");

      handle = startActivityFeed(deps);
      await sleep(1300);
      expect(getActivityFeedState().recentLines.filter((line) => line.source === "watchdog")).toEqual([]);

      const firstLiveRow = JSON.stringify({
        ts: new Date().toISOString(),
        target: "cockpit",
        event: "relaunch",
        relaunchPid: 11,
      });
      fs.appendFileSync(deps.restartLogPath, firstLiveRow + "\n");
      await sleep(1300);
      expect(getActivityFeedState().recentLines.filter((line) => line.source === "watchdog")).toHaveLength(1);

      handle.stop();
      handle = startActivityFeed(deps);
      await sleep(1300);
      expect(getActivityFeedState().recentLines.filter((line) => line.source === "watchdog")).toEqual([]);

      const secondLiveRow = JSON.stringify({
        ts: new Date().toISOString(),
        target: "cockpit",
        event: "relaunch",
        relaunchPid: 12,
      });
      fs.appendFileSync(deps.restartLogPath, secondLiveRow + "\n");
      await sleep(1300);

      const watchdogLines = getActivityFeedState().recentLines.filter((line) => line.source === "watchdog");
      expect(watchdogLines).toHaveLength(1);
      expect(watchdogLines[0]?.text).toContain("12");
      expect(watchdogLines[0]?.text).not.toContain("10");
      expect(watchdogLines[0]?.text).not.toContain("11");
    },
    10000,
  );

  it(
    "baselines a resolved kill-receipts log and renders only rows appended after boot",
    async () => {
      const killReceiptsPath = path.join(scratchDir, "kill-receipts-baseline.jsonl");
      const deps = baseDeps();
      fs.writeFileSync(killReceiptsPath, JSON.stringify({ pids: [100] }) + "\n");
      fs.writeFileSync(deps.watchdogStatePath, JSON.stringify({ kill_receipts_path: killReceiptsPath }));

      handle = startActivityFeed(deps);
      await sleep(1300);
      expect(getActivityFeedState().recentLines.filter((line) => line.source === "watchdog")).toEqual([]);

      fs.appendFileSync(killReceiptsPath, JSON.stringify({ pids: [101], reason: "test-live-row" }) + "\n");
      await sleep(1300);

      const watchdogLines = getActivityFeedState().recentLines.filter((line) => line.source === "watchdog");
      expect(watchdogLines).toHaveLength(1);
      expect(watchdogLines[0]?.text).toContain("test-live-row");
      expect(watchdogLines[0]?.text).not.toContain("reason unavailable");
    },
    8000,
  );

  it(
    "writes a tail-poll diagnostic log row per tick, capped or not",
    async () => {
      const tailPollDebugLogPath = path.join(scratchDir, "tailpoll-debug.jsonl");
      const deps = baseDeps({ tailPollDebugLogPath });
      handle = startActivityFeed(deps);
      fs.appendFileSync(
        deps.restartLogPath,
        JSON.stringify({ ts: new Date().toISOString(), target: "cockpit", event: "relaunch", relaunchPid: 1 }) + "\n",
      );
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

  // issue #1045 (operator report, 2026-07-24: 4.9GB working set correlated with the 871-row
  // watchdog restart-log): pollTail used to `readFile(filePath)` -- the WHOLE file, every tick,
  // forever -- even though only the bytes past byteOffset were ever new. This regression appends
  // a large live batch after boot, then proves the following tick allocates only its small delta.
  it(
    "a later tick reads only the new delta, never the whole (large) file again",
    async () => {
      const tailPollDebugLogPath = path.join(scratchDir, "tailpoll-bounded-debug.jsonl");
      const deps = baseDeps({ tailPollDebugLogPath });

      handle = startActivityFeed(deps);

      // Append a LARGE live batch (~200KB) after boot; the first tick consumes that batch.
      const paddingRow = JSON.stringify({
        ts: new Date().toISOString(),
        target: "cockpit",
        event: "relaunch",
        relaunchPid: 0,
        pad: "x".repeat(180),
      });
      const paddingLines = Array.from({ length: 1000 }, () => paddingRow); // ~200KB
      fs.writeFileSync(deps.restartLogPath, paddingLines.join("\n") + "\n");
      const fileSizeAfterSeed = fs.statSync(deps.restartLogPath).size;
      expect(fileSizeAfterSeed).toBeGreaterThan(150_000);

      await sleep(1300); // first tick: consumes the ~200KB live append

      // A single small append -- the real-world "one more watchdog row landed" case.
      const smallRow = JSON.stringify({
        ts: new Date().toISOString(),
        target: "cockpit",
        event: "relaunch",
        relaunchPid: 1,
      });
      fs.appendFileSync(deps.restartLogPath, smallRow + "\n");
      const fileSizeAfterAppend = fs.statSync(deps.restartLogPath).size;

      await sleep(1300); // second tick: should see ONLY the appended delta

      const raw = fs.readFileSync(tailPollDebugLogPath, "utf-8");
      const ticks = raw
        .split("\n")
        .filter((l) => l.trim().length > 0)
        .map((l) => JSON.parse(l) as Record<string, unknown>)
        .filter((r) => r["event"] === "pollTail" && r["file"] === "restart-log");

      // Exactly two ticks observed real bytes: the large live append, then the small append.
      expect(ticks.length).toBe(2);
      const secondTick = ticks[1] as { bytesRead: number };
      // Bounded by the append's real size, with generous headroom -- NOT anywhere near the
      // full (now ~200KB+) file size. This is the line that fails on pre-fix master.
      expect(secondTick.bytesRead).toBeLessThan(1000);
      expect(secondTick.bytesRead).toBeLessThan(fileSizeAfterAppend - fileSizeAfterSeed + 500);
    },
    8000,
  );
});

// ---------------------------------------------------------------------------
// Goal-organ session tail-poll — ember issue #211 §7 delta 4 ("goal receipts feed the
// board"). Unlike every other engine test above, this file is a GROWING JSONL log appended
// to repeatedly across a session (services/goal-receipts.ts), never a one-shot-parsed `.json`
// receipt -- these tests exist specifically to prove the tail-poll path (not the
// queueForRender/watermark path) is what picks it up, and that it keeps picking up FURTHER
// appends to the SAME file, not just its first line.
// ---------------------------------------------------------------------------

describe("startActivityFeed — goal-session tail-poll (real fs)", () => {
  let scratchDir: string;
  let handle: ActivityFeedHandle | null = null;

  beforeEach(() => {
    scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-activity-feed-goal-"));
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

  function goalRow(overrides: Partial<GoalReceiptRow> = {}): string {
    return JSON.stringify({ ts: new Date().toISOString(), goalId: "g1", ...overrides } as GoalReceiptRow);
  }

  it(
    "discovers a new goal-sessions file created after boot and renders its first row",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300); // let the recursive watcher arm

      const goalSessionsDir = path.join(deps.receiptsDir, "goal-sessions");
      fs.mkdirSync(goalSessionsDir, { recursive: true });
      const sessionFile = path.join(goalSessionsDir, "session-20260709T000000Z.jsonl");
      fs.writeFileSync(
        sessionFile,
        goalRow({ event: "created", detail: { objective: "write progress.txt in three steps" } }) + "\n",
      );

      await sleep(1300);
      const state = getActivityFeedState();
      const found = state.recentLines.find((l) => l.source === "goal");
      expect(found).toBeDefined();
      expect(found?.text).toContain("goal created");
      expect(found?.text).toContain("write progress.txt in three steps");
      expect(found?.path).toBe(sessionFile);

      const ledgerRaw = fs.readFileSync(deps.ledgerPath, "utf-8");
      expect(ledgerRaw).toContain("\"source\":\"goal\"");
    },
    8000,
  );

  it(
    "keeps rendering further appends to the SAME growing session file (not just the first line)",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300);

      const goalSessionsDir = path.join(deps.receiptsDir, "goal-sessions");
      fs.mkdirSync(goalSessionsDir, { recursive: true });
      const sessionFile = path.join(goalSessionsDir, "session-20260709T000001Z.jsonl");
      fs.writeFileSync(sessionFile, goalRow({ event: "created", detail: { objective: "obj" } }) + "\n");

      await sleep(1300);
      let state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.source === "goal" && l.text.includes("goal created"))).toBe(true);

      fs.appendFileSync(
        sessionFile,
        goalRow({ event: "continuation_fired", detail: { kind: "continue" } }) + "\n",
      );

      await sleep(1300);
      state = getActivityFeedState();
      expect(
        state.recentLines.some((l) => l.source === "goal" && l.text.includes("goal continuation fired")),
      ).toBe(true);

      fs.appendFileSync(
        sessionFile,
        goalRow({ event: "status_changed", detail: { from: "Active", to: "Complete" } }) + "\n",
      );

      await sleep(1300);
      state = getActivityFeedState();
      expect(
        state.recentLines.some((l) => l.source === "goal" && l.text.includes("Active -> Complete")),
      ).toBe(true);
    },
    12000,
  );

  it(
    "never renders a line for usage_recorded or continuation_skipped rows (excluded by design)",
    async () => {
      const deps = baseDeps();
      handle = startActivityFeed(deps);
      await sleep(300);

      const goalSessionsDir = path.join(deps.receiptsDir, "goal-sessions");
      fs.mkdirSync(goalSessionsDir, { recursive: true });
      const sessionFile = path.join(goalSessionsDir, "session-20260709T000002Z.jsonl");
      fs.writeFileSync(
        sessionFile,
        [
          goalRow({ event: "usage_recorded", detail: { usage: { tokensUsed: 10 } } }),
          goalRow({ event: "continuation_skipped", detail: { reason: "queued_user_input" } }),
        ].join("\n") + "\n",
      );

      await sleep(1300);
      const state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.source === "goal")).toBe(false);
    },
    8000,
  );

  it(
    "never crashes and never renders anything when no goal has ever been created this session",
    async () => {
      const deps = baseDeps();
      expect(() => {
        handle = startActivityFeed(deps);
      }).not.toThrow();
      await sleep(1300);
      const state = getActivityFeedState();
      expect(state.recentLines.some((l) => l.source === "goal")).toBe(false);
    },
    5000,
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
    "HEADLESS CAPTURE: a harness run renders normally but publishes NO watermark, so the operator's next cockpit still sees the receipts",
    async () => {
      // A capture harness drives the real compiled binary, and screens/repl.ts mounts this engine
      // unconditionally with DEFAULT deps -- so before this guard the harness stamped the
      // watermark at the main repo root, and the operator's next cockpit read that map and
      // suppressed replay. The receipts were "rendered" to a PTY nobody was reading.
      const deps = baseDeps();
      handle = startActivityFeed({ ...deps, env: { EMBER_CLI_HEADLESS_CAPTURE: "1" } });
      await sleep(300);

      const dir = path.join(deps.receiptsDir, "acceptance");
      fs.mkdirSync(dir, { recursive: true });
      const filePath = path.join(dir, "harness-seen.json");
      fs.writeFileSync(filePath, JSON.stringify({ verdict: "GREEN" }));

      await sleep(1200);
      // It still RENDERS -- suppression is about publishing, not about crippling the instrument,
      // and a harness that stopped rendering could not measure what it was built to measure.
      expect(getActivityFeedState().recentLines.some((l) => l.text.includes("harness-seen.json"))).toBe(true);
      // ...but nothing was published for anyone else to act on.
      expect(fs.existsSync(deps.watermarkPath)).toBe(false);

      // The load-bearing consequence, asserted through the real consumer rather than inferred
      // from the absent file: a fresh cockpit-mode engine on the same watermark path renders the
      // receipt, because no prior run claimed to have shown it.
      handle?.stop();
      handle = startActivityFeed(deps);
      await sleep(300);
      fs.writeFileSync(filePath, JSON.stringify({ verdict: "GREEN", touched: true }));
      await sleep(1200);
      expect(getActivityFeedState().recentLines.some((l) => l.text.includes("harness-seen.json"))).toBe(true);
    },
    12000,
  );

  it(
    "a value that is not exactly \"1\" leaves the engine publishing normally",
    async () => {
      // Fail-safe direction, same as the heartbeat guard: silently suppressing on a garbled value
      // would take a real cockpit's watermark away and reintroduce the replay flood the watermark
      // exists to stop.
      const deps = baseDeps();
      handle = startActivityFeed({ ...deps, env: { EMBER_CLI_HEADLESS_CAPTURE: "true" } });
      await sleep(300);

      const dir = path.join(deps.receiptsDir, "acceptance");
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, "cockpit-seen.json"), JSON.stringify({ verdict: "GREEN" }));

      await sleep(1200);
      expect(fs.existsSync(deps.watermarkPath)).toBe(true);
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
