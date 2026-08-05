// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// core/watch-loop.test.ts — unit coverage for the `--watch [--interval N]` ambient mode's
// argument parsing and refresh-cycle/SIGINT lifecycle (gh issue #34, C-OBS). Runs entirely
// in-process: unlike commands/world-state.test.ts, nothing here touches core/ember-world-state.ts's
// module-level GOALFORGE_ROOT const (every function under test takes goalforgeRoot/deps as
// explicit parameters), so there is no frozen-at-import-time env problem and no need for the
// spawned-subprocess driver pattern -- these are real production functions exercised with
// injected IO, not mocked modules.
//
// The execution-BINDING proof that `ember --watch` on the real CLI argv actually reaches this
// module's real render path (not just that this module works in isolation) lives in
// entrypoints/process-entry.test.ts, which spawns a real subprocess against a fixture goalforge
// root -- the same reason commands/world-state.test.ts uses a subprocess for its own binding
// proof.

import { describe, it, expect } from "bun:test";
import {
  parseWatchArgs,
  runWatchCycle,
  runAmbientWatch,
  DEFAULT_WATCH_INTERVAL_MS,
  realSleep,
} from "./watch-loop.ts";
import { renderMonitorPanel } from "./monitor-render.ts";
import { renderReceiptsTail } from "./watch-render.ts";
import type { EmberWorldState, Claim } from "./ember-world-state.ts";
import type { ReceiptStat } from "./watch-render.ts";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function fixtureClaim(id: string, detail: string): Claim {
  return { id, label: id, detail, evidence: { path: "fixture", sha256: "0".repeat(64) } };
}

function fixtureState(boardTs: string): EmberWorldState {
  return {
    ts: "2026-07-25T00:00:00.000Z",
    monitor: {
      boardTs,
      total: 2,
      green: 1,
      red: 1,
      pctComplete: 50,
      conditions: [
        fixtureClaim("board.C1", "GREEN: fine"),
        fixtureClaim("board.C2", "RED: broken"),
      ],
    },
    understand: { goalTitle: "Fixture", topology: [] },
    interact: { ledgerRows: [] },
    sources: {
      goal: { path: "GOAL.md", sha256: "0".repeat(64) },
      ledger: { path: "docs/ledgers/ember-debt-ledger.md", sha256: "0".repeat(64) },
      board: { path: "receipts-totality/fixture.json", sha256: "0".repeat(64) },
    },
  };
}

const FIXTURE_RECEIPTS: ReceiptStat[] = [{ path: "receipts/r1.json", mtimeMs: 1000 }];

// ---------------------------------------------------------------------------
// parseWatchArgs — hostile-input battery (feeds each malformed case; every one fails CLOSED,
// naming the argument, never silently substituting a wrong interval and starting the loop anyway)
// ---------------------------------------------------------------------------

describe("parseWatchArgs", () => {
  it("is disabled when --watch is absent", () => {
    expect(parseWatchArgs(["node", "ember"])).toEqual({
      enabled: false,
      intervalMs: DEFAULT_WATCH_INTERVAL_MS,
    });
  });

  it("enables with the default interval when --watch has no --interval", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch"]);
    expect(parsed.enabled).toBe(true);
    expect(parsed.intervalMs).toBe(DEFAULT_WATCH_INTERVAL_MS);
    expect(parsed.error).toBeUndefined();
  });

  it("accepts a valid --interval in seconds (space form)", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch", "--interval", "10"]);
    expect(parsed.enabled).toBe(true);
    expect(parsed.intervalMs).toBe(10_000);
    expect(parsed.error).toBeUndefined();
  });

  it("accepts a valid --interval=N form", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch", "--interval=3"]);
    expect(parsed.intervalMs).toBe(3000);
    expect(parsed.error).toBeUndefined();
  });

  it("fails closed: --interval with a missing value", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch", "--interval"]);
    expect(parsed.error).toContain("--interval");
    expect(parsed.error).toContain("requires a value");
    expect(parsed.intervalMs).toBe(DEFAULT_WATCH_INTERVAL_MS);
  });

  it("fails closed: --interval followed by another flag (no value supplied)", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch", "--interval", "--foo"]);
    expect(parsed.error).toContain("requires a value");
  });

  it("fails closed: --interval non-numeric", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch", "--interval", "abc"]);
    expect(parsed.error).toContain('"abc"');
    expect(parsed.error).toContain("--interval");
  });

  it("fails closed: --interval zero", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch", "--interval", "0"]);
    expect(parsed.error).toContain("greater than 0");
  });

  it("fails closed: --interval negative", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch", "--interval", "-5"]);
    expect(parsed.error).toContain("greater than 0");
  });

  it("fails closed: --interval absurdly large", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch", "--interval", "999999999"]);
    expect(parsed.error).toContain("at most");
  });

  it("fails closed: --interval=NaN-shaped string via = form", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch", "--interval=", ]);
    expect(parsed.error).toContain("requires a value");
  });

  it("fails closed: --interval Infinity", () => {
    const parsed = parseWatchArgs(["node", "ember", "--watch", "--interval", "Infinity"]);
    expect(parsed.error).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// runWatchCycle — real render path, fresh state per cycle, refresh-error resilience
// ---------------------------------------------------------------------------

describe("runWatchCycle", () => {
  it("renders through the REAL renderMonitorPanel/renderReceiptsTail (not a stub)", async () => {
    let buildCalls = 0;
    const result = await runWatchCycle({
      buildState: async () => {
        buildCalls++;
        return fixtureState("2026-07-25T00:00:00.000Z");
      },
      findReceipts: async () => FIXTURE_RECEIPTS,
      renderPanel: renderMonitorPanel,
      renderTail: renderReceiptsTail,
      goalforgeRoot: "/fixture/root",
      colorEnabled: false,
      width: 80,
      now: () => Date.parse("2026-07-25T00:00:01.000Z"),
    });
    expect(buildCalls).toBe(1);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("unreachable");
    // Real renderMonitorPanel output: bordered panel with both conditions present.
    expect(result.lines.join("\n")).toContain("C1");
    expect(result.lines.join("\n")).toContain("C2");
    expect(result.lines.join("\n")).toContain("50%");
    // Real renderReceiptsTail output.
    expect(result.lines.join("\n")).toContain("receipts/r1.json");
  });

  it("passes goalforgeRoot through to buildState/findReceipts on every call (no caching)", async () => {
    const roots: string[] = [];
    await runWatchCycle({
      buildState: async (opts) => {
        roots.push(opts?.goalforgeRoot ?? "");
        return fixtureState("t");
      },
      findReceipts: async (root) => {
        roots.push(root);
        return [];
      },
      renderPanel: renderMonitorPanel,
      renderTail: renderReceiptsTail,
      goalforgeRoot: "/specific/root",
      colorEnabled: false,
      width: 80,
      now: () => 0,
    });
    expect(roots).toEqual(["/specific/root", "/specific/root"]);
  });

  it("degrades to {ok:false, error} instead of throwing when buildState fails", async () => {
    const result = await runWatchCycle({
      buildState: async () => {
        throw new Error("no board receipt found under fixture/root");
      },
      findReceipts: async () => [],
      renderPanel: renderMonitorPanel,
      renderTail: renderReceiptsTail,
      goalforgeRoot: "/fixture/root",
      colorEnabled: false,
      width: 80,
      now: () => 0,
    });
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("unreachable");
    expect(result.error).toContain("no board receipt found");
  });

  it("degrades to {ok:false, error} when a non-Error is thrown", async () => {
    const result = await runWatchCycle({
      buildState: async () => {
        // eslint-disable-next-line @typescript-eslint/no-throw-literal
        throw "raw string failure";
      },
      findReceipts: async () => [],
      renderPanel: renderMonitorPanel,
      renderTail: renderReceiptsTail,
      goalforgeRoot: "/fixture/root",
      colorEnabled: false,
      width: 80,
      now: () => 0,
    });
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("unreachable");
    expect(result.error).toBe("raw string failure");
  });
});

// ---------------------------------------------------------------------------
// runAmbientWatch — repeat lifecycle, refresh-error resilience across cycles, SIGINT termination
// ---------------------------------------------------------------------------

describe("runAmbientWatch", () => {
  it("fresh state every cycle: buildState is called once per cycle, never cached across cycles", async () => {
    let buildCalls = 0;
    const written: string[] = [];
    const result = await runAmbientWatch({
      goalforgeRoot: "/fixture/root",
      intervalMs: 1,
      colorEnabled: false,
      width: 80,
      write: (t) => written.push(t),
      now: () => 0,
      sleep: async () => {}, // instant -- no real timer in a unit test
      registerSigint: () => () => {}, // never fires; maxCycles ends the loop
      buildState: async () => {
        buildCalls++;
        return fixtureState(`cycle-${buildCalls}`);
      },
      findReceipts: async () => FIXTURE_RECEIPTS,
      renderPanel: renderMonitorPanel,
      renderTail: renderReceiptsTail,
      maxCycles: 3,
    });
    expect(buildCalls).toBe(3);
    expect(result.cycles).toBe(3);
    expect(result.stoppedBySignal).toBe(false);
    expect(written.length).toBe(3);
    // Each written cycle carries ITS OWN boardTs -- proof no cycle reused a prior snapshot.
    expect(written[0]).toContain("cycle-1");
  });

  it("refresh-error resilience: a failed cycle is reported but the loop continues to the next one", async () => {
    let calls = 0;
    const written: string[] = [];
    const result = await runAmbientWatch({
      goalforgeRoot: "/fixture/root",
      intervalMs: 1,
      colorEnabled: false,
      width: 80,
      write: (t) => written.push(t),
      now: () => 0,
      sleep: async () => {},
      registerSigint: () => () => {},
      buildState: async () => {
        calls++;
        if (calls === 2) throw new Error("transient refresh failure");
        return fixtureState(`cycle-${calls}`);
      },
      findReceipts: async () => FIXTURE_RECEIPTS,
      renderPanel: renderMonitorPanel,
      renderTail: renderReceiptsTail,
      maxCycles: 3,
    });
    expect(result.cycles).toBe(3); // the loop did NOT crash/stop on the bad 2nd cycle
    expect(written[0]).toContain("cycle-1");
    expect(written[1]).toContain("[watch] refresh error: transient refresh failure");
    expect(written[2]).toContain("cycle-3"); // recovered on the very next cycle
  });

  it("clean SIGINT lifecycle: registered handler aborts the loop and is unregistered exactly once", async () => {
    let unregisterCalls = 0;
    let sigintHandler: (() => void) | undefined;
    const written: string[] = [];
    const resultPromise = runAmbientWatch({
      goalforgeRoot: "/fixture/root",
      intervalMs: 50,
      colorEnabled: false,
      width: 80,
      write: (t) => written.push(t),
      now: () => 0,
      sleep: (ms, signal) => realSleep(ms, signal), // real abortable sleep -- proves SIGINT
      // interrupts a wait in progress rather than only being checked between cycles.
      registerSigint: (handler) => {
        sigintHandler = handler;
        return () => {
          unregisterCalls++;
        };
      },
      buildState: async () => fixtureState("cycle"),
      findReceipts: async () => FIXTURE_RECEIPTS,
      renderPanel: renderMonitorPanel,
      renderTail: renderReceiptsTail,
      // No maxCycles: only the (simulated) signal ends this loop.
    });
    // Let the first cycle render and enter its sleep, then fire "SIGINT" mid-sleep.
    await new Promise((r) => setTimeout(r, 10));
    expect(written.length).toBe(1); // exactly one cycle rendered before the signal
    expect(sigintHandler).toBeDefined();
    sigintHandler!();
    const result = await resultPromise;
    expect(result.stoppedBySignal).toBe(true);
    expect(result.cycles).toBe(1); // aborted mid-sleep, never started a second cycle
    expect(unregisterCalls).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// realSleep — the production abortable sleep primitive
// ---------------------------------------------------------------------------

describe("realSleep", () => {
  it("resolves immediately when the signal is already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const start = Date.now();
    await realSleep(10_000, controller.signal);
    expect(Date.now() - start).toBeLessThan(1000); // did not wait out the 10s
  });

  it("resolves early when aborted mid-wait", async () => {
    const controller = new AbortController();
    const start = Date.now();
    setTimeout(() => controller.abort(), 5);
    await realSleep(10_000, controller.signal);
    expect(Date.now() - start).toBeLessThan(1000);
  });
});
