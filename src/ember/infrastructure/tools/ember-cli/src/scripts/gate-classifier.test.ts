// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// scripts/gate-classifier.test.ts — parser + verdict unit tests against real bun output shapes.
//
// The fixture strings below are verbatim (or, for the panic case, a receipted composite of two
// verbatim captures) from actual `bun test` runs recorded during this lane's work:
//   - GREEN_OUTPUT: services/activity-feed.test.ts alone, captured 2026-07-19.
//   - RED_OUTPUT: the full 209-file suite (2 known files excluded), captured 2026-07-19 --
//     the 16-failure run this lane triaged.
//   - TRUNCATED_OUTPUT: services/emberd-rpc.test.ts's header-only output from a killed/timed-out
//     invocation -- no summary ever printed.
//   - PANIC_AFTER_SUMMARY_OUTPUT: the clean 4-pass/0-fail summary this lane captured for
//     screens/repl-slash-dropdown.test.ts, followed by the exact panic signature recorded in
//     BUNPANIC_TRIAGE.md (bun.report hash 1700fc11iDsgogC+1tmG+nvB62/xhBq92rhB__u40kyCA0eNrzzCtJLcpLzFFILC5OLSrJzM9TSEvMzCktSgUAiSkKPg,
//     bun 1.3.12) -- reconstructed because the cure means this exact combination no longer occurs
//     live, but the shape (summary block, THEN the panic lines) is exactly what was receipted
//     pre-cure.

import { describe, expect, test } from "bun:test";
import { parseSummary, verdict } from "./gate-classifier.ts";

const GREEN_OUTPUT = `bun test v1.3.12 (700fc117)

 71 pass
 0 fail
 148 expect() calls
Ran 71 tests across 1 file. [38.47s]`;

const RED_OUTPUT = `bun test v1.3.12 (700fc117)

 3460 pass
 1 skip
 16 fail
 7097 expect() calls
Ran 3477 tests across 209 files. [81.02s]`;

const TRUNCATED_OUTPUT = `bun test v1.3.12 (700fc117)`;

const PANIC_AFTER_SUMMARY_OUTPUT = `bun test v1.3.12 (700fc117)

screens\\repl-slash-dropdown.test.ts:
[liveness-heartbeat] writing heartbeat to X:\\work\\ember\\tools\\ember-cli\\state\\cockpit-heartbeat.json (repo root X:\\work\\ember)

 4 pass
 0 fail
 11 expect() calls
Ran 4 tests across 1 file. [231.00ms]
panic(main thread): Internal assertion failure
oh no: Bun has crashed. This indicates a bug in Bun, not your code.
https://bun.report/1.3.12/et1700fc11iDsgogC+1tmG+nvB62/xhBq92rhB__u40kyCA0eNrzzCtJLcpLzFFILC5OLSrJzM9TSEvMzCktSgUAiSkKPg`;

describe("parseSummary — real bun output shapes", () => {
  test("green: full pass/fail/ran shape parses", () => {
    expect(parseSummary(GREEN_OUTPUT)).toEqual({ hasSummary: true, passCount: 71, failCount: 0 });
  });

  test("red: full shape with a skip line and nonzero fail parses (skip line doesn't break it)", () => {
    expect(parseSummary(RED_OUTPUT)).toEqual({ hasSummary: true, passCount: 3460, failCount: 16 });
  });

  test("truncated: header only, no summary at all -> hasSummary false", () => {
    expect(parseSummary(TRUNCATED_OUTPUT)).toEqual({ hasSummary: false, passCount: null, failCount: null });
  });

  test("panic-after-summary: the summary block before the panic still parses as a real summary", () => {
    expect(parseSummary(PANIC_AFTER_SUMMARY_OUTPUT)).toEqual({ hasSummary: true, passCount: 4, failCount: 0 });
  });

  test("P2: a fail+ran line without a pass line is NOT a complete summary", () => {
    const partial = `bun test v1.3.12 (700fc117)\n\n 0 fail\nRan 3 tests across 1 file. [10.00ms]`;
    expect(parseSummary(partial)).toEqual({ hasSummary: false, passCount: null, failCount: null });
  });

  test("P2: a pass+ran line without a fail line is NOT a complete summary", () => {
    const partial = `bun test v1.3.12 (700fc117)\n\n 3 pass\nRan 3 tests across 1 file. [10.00ms]`;
    expect(parseSummary(partial)).toEqual({ hasSummary: false, passCount: null, failCount: null });
  });

  test("P2: pass+fail without the trailing Ran line is NOT a complete summary", () => {
    const partial = `bun test v1.3.12 (700fc117)\n\n 3 pass\n 0 fail\n`;
    expect(parseSummary(partial)).toEqual({ hasSummary: false, passCount: null, failCount: null });
  });

  test("noncontiguous summary-like lines cannot be spliced into a clean result", () => {
    const mixed = `bun test v1.3.12 (700fc117)

 3 pass
arbitrary child output between summary lines
 0 fail
 3 expect() calls
Ran 3 tests across 1 file. [10.00ms]`;
    expect(parseSummary(mixed)).toEqual({ hasSummary: false, passCount: null, failCount: null });
  });

  test("the last complete summary block is authoritative when output contains nested runs", () => {
    const nested = `${GREEN_OUTPUT}

nested command finished; outer run follows

 8 pass
 2 fail
 19 expect() calls
Ran 10 tests across 2 files. [20.00ms]`;
    expect(parseSummary(nested)).toEqual({ hasSummary: true, passCount: 8, failCount: 2 });
  });

  test("summary counts must reconcile with the reported number of tests", () => {
    const inconsistent = `bun test v1.3.12 (700fc117)

 9 pass
 0 fail
 9 expect() calls
Ran 10 tests across 1 file. [10.00ms]`;
    expect(parseSummary(inconsistent)).toEqual({ hasSummary: false, passCount: null, failCount: null });
  });
});

describe("verdict — decision table", () => {
  test("timeout is always RED, regardless of quarantine status", () => {
    const input = { timedOut: true, exitCode: null, hasSummary: false, failCount: null };
    expect(verdict(input, false)).toBe("RED");
    expect(verdict(input, true)).toBe("RED");
  });

  test("missing summary (crash pre-summary, not a timeout) is always RED", () => {
    const input = { timedOut: false, exitCode: 2, hasSummary: false, failCount: null };
    expect(verdict(input, false)).toBe("RED");
    expect(verdict(input, true)).toBe("RED");
  });

  test("nonzero fail count is always RED, regardless of quarantine status", () => {
    const input = { timedOut: false, exitCode: 1, hasSummary: true, failCount: 16 };
    expect(verdict(input, false)).toBe("RED");
    expect(verdict(input, true)).toBe("RED");
  });

  test("clean summary + exit 0 is GREEN", () => {
    const input = { timedOut: false, exitCode: 0, hasSummary: true, failCount: 0 };
    expect(verdict(input, false)).toBe("GREEN");
  });

  test("clean summary + nonzero exit, file IS quarantined -> QUARANTINE-PASS", () => {
    const input = { timedOut: false, exitCode: 7, hasSummary: true, failCount: 0 };
    expect(verdict(input, true)).toBe("QUARANTINE-PASS");
  });

  // P1-1 recurrence regression: the reviewer's exact required case. Feeds the classifier a
  // clean-summary-then-nonzero-exit result (the panic shape) for a file that is NOT on the
  // quarantine list, and asserts RED. This is what protects against the empty quarantine.md's
  // whole point being silently defeated by some future re-listing, AND against a genuine future
  // recurrence of the panic in any currently-unlisted file being waved through as green-ish.
  test("P1-1 recurrence regression: clean summary + nonzero exit, file is UNLISTED -> RED, never QUARANTINE-PASS", () => {
    const input = { timedOut: false, exitCode: 7, hasSummary: true, failCount: 0 };
    expect(verdict(input, false)).toBe("RED");
  });
});
