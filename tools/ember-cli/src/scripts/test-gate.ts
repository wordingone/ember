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
// (quarantined or not) purely from its printed summary line — never from exit code alone. See
// gate-classifier.ts's verdict() for the exact decision table (unit-tested there, including the
// P1-1 recurrence regression: an unlisted file with a clean-summary-then-nonzero-exit run must
// be RED, never QUARANTINE-PASS).
//
// Usage: bun run scripts/test-gate.ts [--timeout-ms=30000]
//
// Test-only overrides (set by scripts/test-gate.e2e.test.ts, never by a real invocation):
//   GATE_SRC_ROOT       — run against this directory instead of the real repo tree.
//   GATE_QUARANTINE_JSON — a JSON string array replacing the real quarantine-list.ts contents.

import { QUARANTINE as REAL_QUARANTINE } from "./quarantine-list.ts";
import { parseSummary, verdict, type ClassifyInput } from "./gate-classifier.ts";
import { drainAvailable } from "./drain-stream.ts";

// Forward-slashed, always -- verified empirically (2026-07-19) that Bun.spawn's executable-path
// resolution on Windows breaks specifically when `cwd` is a backslash-style path (ENOENT from
// uv_spawn on an exe that demonstrably exists at that exact path), regardless of drive letter or
// whether the exe itself is given bare ("bun") or fully qualified. import.meta.url already
// yields forward slashes, so this only bites when GATE_SRC_ROOT is supplied externally (e.g. the
// e2e test's mkdtempSync()/tmpdir(), which return backslash paths on Windows).
const SRC_ROOT = (
  process.env["GATE_SRC_ROOT"]
  ?? new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")
).replaceAll("\\", "/");

const QUARANTINE: readonly string[] = process.env["GATE_QUARANTINE_JSON"]
  ? (JSON.parse(process.env["GATE_QUARANTINE_JSON"]) as string[])
  : REAL_QUARANTINE;

interface RunResult extends ClassifyInput {
  label: string;
  tail: string;
}

const DRAIN_IDLE_MS = 1_000;

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

  // Wait for the actual process exit FIRST, then drain -- draining concurrently with a hung
  // child risks the classic pipe-buffer deadlock (child blocks writing once the OS pipe fills,
  // because nothing not-yet-called is reading); waiting on `proc.exited` costs nothing extra in
  // the normal case since the streams close at essentially the same moment the process does.
  const exitCode = await proc.exited;
  clearTimeout(killer);

  const [stdout, stderr] = await Promise.all([
    drainAvailable(proc.stdout, DRAIN_IDLE_MS),
    drainAvailable(proc.stderr, DRAIN_IDLE_MS),
  ]);

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

if (import.meta.main) {
  await main();
  // A killed quarantined child can leave a dangling OS handle behind even after its own process
  // has exited (see drainWithGrace's comment) -- that can keep bun's own event loop alive
  // indefinitely waiting for a handle that will never close. process.exitCode is already set
  // correctly above; force the actual exit rather than let a foreign process's leftover handle
  // hang this one.
  process.exit(process.exitCode ?? 0);
}
