// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// scripts/gate-classifier.ts — the pure classification core of test-gate.ts, factored out so it
// can be unit-tested against real bun-output shapes without spawning any process. See
// BUNPANIC_TRIAGE.md for why a naive exit-code check is untrustworthy: a Bun-internal teardown
// panic can fire AFTER a run's own summary already printed "0 fail", and a plain
// `bun test && echo pass` cannot tell that apart from a genuine failure.

export interface RunSummary {
  hasSummary: boolean;
  passCount: number | null;
  failCount: number | null;
}

export interface ClassifyInput {
  timedOut: boolean;
  exitCode: number | null;
  hasSummary: boolean;
  failCount: number | null;
}

export type Verdict = "RED" | "GREEN" | "QUARANTINE-PASS";

/**
 * Parses a bun test run's combined stdout+stderr for its summary block. A summary is only
 * trustworthy when the complete expected shape is present: a "N pass" line, an "N fail" line,
 * AND the trailing "Ran N tests across M files" line, in the form bun actually prints them
 * (order: pass, optional "N skip", fail, "N expect() calls", "Ran ..."). Any partial subset --
 * e.g. a "fail" line without the "Ran..." line, which a panic mid-summary-print could produce --
 * must not be read as a clean result.
 */
export function parseSummary(output: string): RunSummary {
  const passMatch = output.match(/^\s*(\d+)\s+pass\s*$/m);
  const failMatch = output.match(/^\s*(\d+)\s+fail\s*$/m);
  const ranMatch = output.match(/Ran\s+\d+\s+tests?\s+across\s+\d+\s+files?/);
  if (!passMatch || !failMatch || !ranMatch) {
    return { hasSummary: false, passCount: null, failCount: null };
  }
  return {
    hasSummary: true,
    passCount: Number(passMatch[1]),
    failCount: Number(failMatch[1]),
  };
}

/**
 * Classifies one run. `quarantined` must reflect whether the file is currently on the
 * quarantine list -- an empty list (the post-cure default) means nothing is ever quarantined, so
 * a clean-summary-then-nonzero-exit run for any file is RED, never QUARANTINE-PASS. This is the
 * load-bearing regression: the list existing does not itself grant amnesty -- only explicit
 * membership does, and membership defaults to none.
 */
export function verdict(input: ClassifyInput, quarantined: boolean): Verdict {
  if (input.timedOut) return "RED";
  if (!input.hasSummary) return "RED";
  if ((input.failCount ?? 1) > 0) return "RED";
  if (input.exitCode === 0) return "GREEN";
  // fail === 0, exit code non-zero -- the post-summary-panic shape. Only spendable if the file
  // is on the quarantine list; otherwise this is a NEW gate-worthy defect, full stop.
  return quarantined ? "QUARANTINE-PASS" : "RED";
}
