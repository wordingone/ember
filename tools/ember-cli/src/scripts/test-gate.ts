#!/usr/bin/env bun
// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// scripts/test-gate.ts — a trustworthy `bun test` gate for tools/ember-cli/src.
//
// Problem this solves (see BUNPANIC_TRIAGE.md): a plain `bun test` can exit non-zero for two
// unrelated reasons that must be told apart:
//   1. A genuine test failure (fail > 0) — always RED.
//   2. A Bun-internal teardown assertion that fires AFTER the run summary has already printed
//      "N pass / 0 fail" — the tests themselves passed; Bun's own process-exit path panicked.
//      Bun says this is a bug in Bun, not in our code (bun.report link in the panic output).
// A naive `bun test && echo pass` treats both cases as red, which either hides a real regression
// behind "it's just the Bun bug" folklore, or blocks merges on a Bun bug we can't fix upstream.
//
// This gate runs the quarantined files in their own one-file-per-process invocations, so a
// teardown panic in one can never contaminate another file's result, then classifies every run
// (quarantined or not) purely from its printed summary line — never from exit code alone:
//   - no summary line printed (crashed/timed out before "Ran N tests...") -> RED, no exceptions.
//   - summary line printed with fail > 0                                  -> RED, no exceptions.
//   - summary line printed with fail === 0, exit code 0                   -> GREEN.
//   - summary line printed with fail === 0, exit code !== 0, AND the file
//     is on the quarantine list                                          -> QUARANTINE-PASS
//     (logged loudly, does not fail the gate).
//   - summary line printed with fail === 0, exit code !== 0, NOT quarantined
//     -> RED (an un-quarantined file must never get the panic's benefit of the doubt).
//
// Usage: bun run scripts/test-gate.ts [--timeout-ms=30000]

import { QUARANTINE } from "./quarantine-list.ts";

const SRC_ROOT = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

interface RunResult {
  label: string;
  exitCode: number | null;
  timedOut: boolean;
  hasSummary: boolean;
  passCount: number | null;
  failCount: number | null;
  tail: string;
}

function parseSummary(output: string): Pick<RunResult, "hasSummary" | "passCount" | "failCount"> {
  const failMatch = output.match(/^\s*(\d+)\s+fail\s*$/m);
  const passMatch = output.match(/^\s*(\d+)\s+pass\s*$/m);
  const ranMatch = output.match(/Ran\s+\d+\s+tests?\s+across\s+\d+\s+files?/);
  if (!failMatch || !ranMatch) {
    // A summary is only trustworthy if BOTH the "N fail" line and the trailing "Ran N tests
    // across M files" line printed -- a panic mid-summary (rare, but possible) could print one
    // without the other, and that partial state must not be read as a clean pass.
    return { hasSummary: false, passCount: null, failCount: null };
  }
  return {
    hasSummary: true,
    passCount: passMatch ? Number(passMatch[1]) : null,
    failCount: Number(failMatch[1]),
  };
}

async function runOne(args: string[], label: string, timeoutMs: number): Promise<RunResult> {
  const proc = Bun.spawn(["bun", "test", ...args], {
    cwd: SRC_ROOT,
    stdout: "pipe",
    stderr: "pipe",
  });

  let timedOut = false;
  const killer = setTimeout(() => {
    timedOut = true;
    proc.kill();
  }, timeoutMs);

  const [stdout, stderr] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ]);
  const exitCode = await proc.exited;
  clearTimeout(killer);

  const combined = stdout + "\n" + stderr;
  const summary = parseSummary(combined);
  return {
    label,
    exitCode: timedOut ? null : exitCode,
    timedOut,
    ...summary,
    tail: combined.trim().split("\n").slice(-6).join("\n"),
  };
}

function verdict(r: RunResult, quarantined: boolean): "RED" | "GREEN" | "QUARANTINE-PASS" {
  if (r.timedOut) return "RED";
  if (!r.hasSummary) return "RED";
  if ((r.failCount ?? 1) > 0) return "RED";
  if (r.exitCode === 0) return "GREEN";
  // fail === 0, exit code non-zero (the post-summary panic shape) -- only spendable if the
  // file is on the quarantine list; otherwise this is a NEW gate-worthy defect.
  return quarantined ? "QUARANTINE-PASS" : "RED";
}

async function main(): Promise<void> {
  const timeoutArg = process.argv.find((a) => a.startsWith("--timeout-ms="));
  const timeoutMs = timeoutArg ? Number(timeoutArg.split("=")[1]) : 30_000;

  for (const file of QUARANTINE) {
    const exists = await Bun.file(`${SRC_ROOT}/${file}`).exists();
    if (!exists) {
      console.error(`test-gate: quarantine list names a file that no longer exists: ${file}`);
      process.exitCode = 1;
      return;
    }
  }

  const results: Array<{ result: RunResult; quarantined: boolean; verdict: string }> = [];

  // Exclude quarantined files via bun test's own discovery + --path-ignore-patterns, rather than
  // enumerating every test file as a CLI arg -- with 380+ files that arg list exceeds the Windows
  // command-line length limit ("The command line is too long"). IMPORTANT: bun does NOT support a
  // comma-separated pattern list here (verified: "--path-ignore-patterns=a,b" silently excludes
  // NEITHER -- file count stayed unchanged); it takes exactly one glob per flag occurrence, so the
  // flag must be repeated once per quarantined file.
  const ignoreArgs = QUARANTINE.map((f) => `--path-ignore-patterns=**/${f.split("/").pop()}`);
  console.log("test-gate: main suite (quarantine excluded via repeated --path-ignore-patterns)");
  const mainResult = await runOne(
    ignoreArgs,
    "main-suite",
    Math.max(timeoutMs * 20, 300_000),
  );
  results.push({ result: mainResult, quarantined: false, verdict: verdict(mainResult, false) });

  for (const file of QUARANTINE) {
    console.log(`test-gate: quarantined file, own process: ${file}`);
    const r = await runOne([file], file, timeoutMs);
    results.push({ result: r, quarantined: true, verdict: verdict(r, true) });
  }

  let red = false;
  for (const { result, verdict: v } of results) {
    console.log(`\n=== ${result.label}: ${v} ===`);
    console.log(`  exitCode=${result.exitCode} timedOut=${result.timedOut} hasSummary=${result.hasSummary} pass=${result.passCount} fail=${result.failCount}`);
    console.log(result.tail.split("\n").map((l) => `  | ${l}`).join("\n"));
    if (v === "RED") red = true;
  }

  console.log(`\ntest-gate: overall = ${red ? "RED" : "GREEN"}`);
  process.exitCode = red ? 1 : 0;
}

await main();
