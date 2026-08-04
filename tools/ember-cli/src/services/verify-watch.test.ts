// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/verify-watch.test.ts — unit tests for the /verify pipeline singleton.
//
// The subprocess runner is fully injected: no real gh, python, or git subprocess ever
// runs. Each test writes the receipt file itself where the real
// verify_ember01_completion.py would, mirroring how the real process reports its result
// back to the cli. #1371: every test's mock runner now also answers `git rev-parse HEAD`
// and `worktree_lifecycle.py create`/`retire`, since the pipeline always runs those
// around the three original legs.

import { describe, it, expect, beforeEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  startVerifyRun,
  getVerifyState,
  _setVerifyStateForTest,
  _buildTreeKillCommand,
  _parseReapedPids,
  resolveVerifyTimeoutMs,
  DEFAULT_VERIFY_TIMEOUT_MINUTES,
  DEFAULT_VERIFY_TIMEOUT_MS,
  type EnvBindingReport,
  type EnvBindingStatus,
  type VerifyProcessResult,
} from "./verify-watch.ts";

function readRunReceipt(jobDir: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(path.join(jobDir, "receipt.json"), "utf8")) as Record<string, unknown>;
}

const PINNED_COMMIT = "a".repeat(40);

function envSet(name: string, value = `/path/${name}`): EnvBindingStatus {
  return { envVar: name, set: true, value };
}
function envUnset(name: string): EnvBindingStatus {
  return { envVar: name, set: false };
}

function baseEnvBindings(overrides: Partial<EnvBindingReport> = {}): EnvBindingReport {
  return {
    selection: envSet("EMBER_VERIFY_SELECTION"),
    identityManifest: envSet("EMBER_VERIFY_IDENTITY_MANIFEST"),
    checkpointManifest: envSet("EMBER_VERIFY_CHECKPOINT_MANIFEST"),
    modelConfig: envSet("EMBER_VERIFY_MODEL_CONFIG"),
    unresolvedLegLines: [],
    ...overrides,
  };
}

function tmpJobDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "verify-watch-test-"));
}

async function waitForSettled(timeoutMs = 2000): Promise<void> {
  const start = Date.now();
  while (getVerifyState()?.status === "running") {
    if (Date.now() - start > timeoutMs) throw new Error("waitForSettled timed out");
    await new Promise((r) => setTimeout(r, 5));
  }
}

/** Base mock runner: answers `git rev-parse HEAD` and both worktree_lifecycle.py
 *  subcommands with a synthetic managed worktree at a deterministic path, records every
 *  call, and lets the caller supply the three original-pipeline leg behaviors. */
function mockRunner(opts: {
  worktreePath: string;
  calls: { executable: string; args: string[] }[];
  onGh?: (args: string[]) => Promise<VerifyProcessResult> | VerifyProcessResult;
  onIssueCensus?: (args: string[]) => Promise<VerifyProcessResult> | VerifyProcessResult;
  onVerifier?: (args: string[]) => Promise<VerifyProcessResult> | VerifyProcessResult;
  onRetire?: (args: string[]) => Promise<VerifyProcessResult> | VerifyProcessResult;
}) {
  return async (executable: string, args: string[]): Promise<VerifyProcessResult> => {
    opts.calls.push({ executable, args });
    if (executable === "git" && args[0] === "rev-parse") {
      return { status: 0, stdout: `${PINNED_COMMIT}\n`, stderr: "" };
    }
    if (args.includes("scripts/worktree_lifecycle.py") && args.includes("create")) {
      return {
        status: 0,
        stdout: JSON.stringify({ status: "CREATED", path: opts.worktreePath, branch: "verify/job" }),
        stderr: "",
      };
    }
    if (args.includes("scripts/worktree_lifecycle.py") && args.includes("retire")) {
      if (opts.onRetire) return opts.onRetire(args);
      return { status: 0, stdout: JSON.stringify({ status: "RETIRED", path: opts.worktreePath }), stderr: "" };
    }
    if (executable === "gh") {
      if (opts.onGh) return opts.onGh(args);
      return { status: 0, stdout: "[]", stderr: "" };
    }
    if (args.includes("scripts/ember_01_custody/issue_census.py")) {
      if (opts.onIssueCensus) return opts.onIssueCensus(args);
      return { status: 0, stdout: "", stderr: "" };
    }
    if (args.includes("scripts/verify_ember01_completion.py")) {
      if (opts.onVerifier) return opts.onVerifier(args);
      return { status: 0, stdout: "", stderr: "" };
    }
    throw new Error(`unexpected call in test: ${executable} ${args.join(" ")}`);
  };
}

beforeEach(() => {
  _setVerifyStateForTest(null);
});

describe("startVerifyRun", () => {
  it("creates a pinned managed worktree BEFORE any repo-scoped leg, then targets every repo-scoped leg at it (never repoRoot) -- #1371", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-1");
    const calls: { executable: string; args: string[] }[] = [];

    const runProcess = mockRunner({
      worktreePath,
      calls,
      onVerifier: (args) => {
        const receiptPath = args[args.indexOf("--receipt") + 1]!;
        fs.writeFileSync(
          receiptPath,
          JSON.stringify({
            ok: true,
            legs: { "1": { status: "resolved-true", title: "custody root census (operator-machine roots)" } },
          }),
        );
        return { status: 0, stdout: "ok", stderr: "" };
      },
    });

    const initial = startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-1",
      envBindings: baseEnvBindings(),
      bindings: ["public-repository=/x"],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      runProcess,
    });
    expect(initial.status).toBe("running");
    expect(initial.phase).toBe("preparing-worktree");

    await waitForSettled();

    const final = getVerifyState()!;
    expect(final.status).toBe("done");
    expect(final.phase).toBe("done");
    expect(final.pinnedCommit).toBe(PINNED_COMMIT);
    expect(final.worktreePath).toBe(worktreePath);
    expect(final.receiptSummary?.ok).toBe(true);
    expect(final.receiptSummary?.legs["1"]?.status).toBe("resolved-true");

    // Ordering: rev-parse -> create -> gh -> issue_census -> verifier -> retire.
    expect(calls[0]!.executable).toBe("git");
    expect(calls[1]!.args).toContain("scripts/worktree_lifecycle.py");
    expect(calls[1]!.args).toContain("create");
    expect(calls[1]!.args[calls[1]!.args.indexOf("--start-point") + 1]).toBe(PINNED_COMMIT);
    expect(calls[2]!.executable).toBe("gh");
    const issueCensusArgs = calls[3]!.args;
    expect(issueCensusArgs).toContain("scripts/ember_01_custody/issue_census.py");
    // #1371: repo-scoped legs read the PINNED WORKTREE, never "/repo".
    expect(issueCensusArgs[issueCensusArgs.indexOf("--repo-root") + 1]).toBe(worktreePath);

    const verifierArgs = calls[4]!.args;
    expect(verifierArgs).toContain("--run-custody");
    expect(verifierArgs).toContain("--run-seat");
    expect(verifierArgs[verifierArgs.indexOf("--root") + 1]).toBe(worktreePath);
    const bindingIndex = verifierArgs.indexOf("--binding");
    expect(verifierArgs[bindingIndex + 1]).toBe("public-repository=/x");

    const retireArgs = calls[5]!.args;
    expect(retireArgs).toContain("scripts/worktree_lifecycle.py");
    expect(retireArgs).toContain("retire");
    expect(retireArgs[retireArgs.indexOf("--path") + 1]).toBe(worktreePath);
  });

  it("omits --identity-manifest/--checkpoint-manifest/--model-config when those env vars are unset, never substituting a default", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-2");
    const calls: { executable: string; args: string[] }[] = [];
    let verifierArgs: string[] = [];

    const runProcess = mockRunner({
      worktreePath,
      calls,
      onVerifier: (args) => {
        verifierArgs = args;
        const receiptPath = args[args.indexOf("--receipt") + 1]!;
        fs.writeFileSync(receiptPath, JSON.stringify({ ok: false, legs: {} }));
        return { status: 1, stdout: "", stderr: "" };
      },
    });

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-2",
      envBindings: baseEnvBindings({
        identityManifest: envUnset("EMBER_VERIFY_IDENTITY_MANIFEST"),
        checkpointManifest: envUnset("EMBER_VERIFY_CHECKPOINT_MANIFEST"),
        modelConfig: envUnset("EMBER_VERIFY_MODEL_CONFIG"),
      }),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      runProcess,
    });

    await waitForSettled();
    expect(verifierArgs).not.toContain("--identity-manifest");
    expect(verifierArgs).not.toContain("--checkpoint-manifest");
    expect(verifierArgs).not.toContain("--model-config");
    // verifier exit 1 is a COMPLETED run (not-ok), never treated as an infra failure.
    expect(getVerifyState()?.status).toBe("done");
    expect(getVerifyState()?.receiptSummary?.ok).toBe(false);
    // The worktree is still retired after a completed-but-not-ok run.
    expect(calls.some((c) => c.args.includes("retire"))).toBe(true);
  });

  it("fails the job when gh issue-list exits non-zero, and never invokes the later legs -- but the worktree is still retired", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-3");
    const calls: { executable: string; args: string[] }[] = [];

    const runProcess = mockRunner({
      worktreePath,
      calls,
      onGh: () => ({ status: 1, stdout: "", stderr: "gh: rate limited" }),
    });

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-3",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      runProcess,
    });

    await waitForSettled();
    const final = getVerifyState()!;
    expect(final.status).toBe("failed");
    expect(final.phase).toBe("fetching-issues");
    expect(final.error).toContain("gh: rate limited");
    expect(calls.some((c) => c.args.includes("scripts/ember_01_custody/issue_census.py"))).toBe(false);
    expect(calls.some((c) => c.args.includes("scripts/verify_ember01_completion.py"))).toBe(false);
    // A failure mid-pipeline still retires the worktree it already created -- never a leak
    // on the ordinary failure path.
    expect(calls.some((c) => c.args.includes("retire"))).toBe(true);
  });

  it("fails the job when the verifier itself crashes (exit code outside {0,1}), and still retires the worktree", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-4");
    const calls: { executable: string; args: string[] }[] = [];

    const runProcess = mockRunner({
      worktreePath,
      calls,
      onVerifier: () => ({ status: 127, stdout: "", stderr: "python: command not found" }),
    });

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-4",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      runProcess,
    });

    await waitForSettled();
    const final = getVerifyState()!;
    expect(final.status).toBe("failed");
    expect(final.phase).toBe("verifying");
    expect(final.error).toContain("command not found");
    expect(calls.some((c) => c.args.includes("retire"))).toBe(true);
  });

  it("fails at phase preparing-worktree, before any repo-scoped leg runs, when the managed worktree cannot be created (e.g. WORKTREE_CEILING)", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-5");
    const calls: { executable: string; args: string[] }[] = [];

    const runProcess = async (executable: string, args: string[]): Promise<VerifyProcessResult> => {
      calls.push({ executable, args });
      if (executable === "git") return { status: 0, stdout: `${PINNED_COMMIT}\n`, stderr: "" };
      if (args.includes("create")) {
        return { status: 2, stdout: "", stderr: "WORKTREE_CEILING: live=6 ceiling=6" };
      }
      throw new Error(`unexpected call: ${executable} ${args.join(" ")}`);
    };

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-5",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      worktreeRoot: worktreePath,
      runProcess,
    });

    await waitForSettled();
    const final = getVerifyState()!;
    expect(final.status).toBe("failed");
    expect(final.phase).toBe("preparing-worktree");
    expect(final.error).toContain("WORKTREE_CEILING");
    expect(final.worktreePath).toBeUndefined();
    // gh never ran -- development-affecting legs never start without a pinned worktree.
    expect(calls.some((c) => c.executable === "gh")).toBe(false);
  });

  it("does not fail the run when worktree retirement itself fails -- discloses worktreeRetireError instead", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-6");
    const calls: { executable: string; args: string[] }[] = [];

    const runProcess = mockRunner({
      worktreePath,
      calls,
      onVerifier: (args) => {
        const receiptPath = args[args.indexOf("--receipt") + 1]!;
        fs.writeFileSync(receiptPath, JSON.stringify({ ok: true, legs: {} }));
        return { status: 0, stdout: "", stderr: "" };
      },
      onRetire: () => ({ status: 2, stdout: "", stderr: "DIRTY_WORKTREE: leftover scratch file" }),
    });

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-6",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      runProcess,
    });

    await waitForSettled();
    const final = getVerifyState()!;
    // The run's verdict (ok/not-ok) is about the pinned commit, not worktree cleanup.
    expect(final.status).toBe("done");
    expect(final.receiptSummary?.ok).toBe(true);
    expect(final.worktreeRetireError).toContain("DIRTY_WORKTREE");
  });
});

// ---------------------------------------------------------------------------
// #1371 cure a — configurable pipeline timeout, default sized to a MEASURED census
// ---------------------------------------------------------------------------

describe("resolveVerifyTimeoutMs", () => {
  it("defaults to at least 180 minutes -- the 20-minute cap killed a healthy run whose census leg alone measured ~95 min", () => {
    expect(DEFAULT_VERIFY_TIMEOUT_MINUTES).toBeGreaterThanOrEqual(180);
    expect(resolveVerifyTimeoutMs({})).toBe(DEFAULT_VERIFY_TIMEOUT_MS);
  });

  it("honours EMBER_VERIFY_TIMEOUT_MINUTES", () => {
    expect(resolveVerifyTimeoutMs({ EMBER_VERIFY_TIMEOUT_MINUTES: "240" })).toBe(240 * 60_000);
  });

  it("falls back to the default on a malformed or non-positive value, never to 'no timeout'", () => {
    expect(resolveVerifyTimeoutMs({ EMBER_VERIFY_TIMEOUT_MINUTES: "soon" })).toBe(DEFAULT_VERIFY_TIMEOUT_MS);
    expect(resolveVerifyTimeoutMs({ EMBER_VERIFY_TIMEOUT_MINUTES: "0" })).toBe(DEFAULT_VERIFY_TIMEOUT_MS);
    expect(resolveVerifyTimeoutMs({ EMBER_VERIFY_TIMEOUT_MINUTES: "-5" })).toBe(DEFAULT_VERIFY_TIMEOUT_MS);
  });

  it("passes the resolved timeout down to every leg's runner", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-timeout-arg");
    const calls: { executable: string; args: string[] }[] = [];
    const seenTimeouts: (number | undefined)[] = [];
    const inner = mockRunner({
      worktreePath,
      calls,
      onVerifier: (args) => {
        fs.writeFileSync(args[args.indexOf("--receipt") + 1]!, JSON.stringify({ ok: true, legs: {} }));
        return { status: 0, stdout: "", stderr: "" };
      },
    });

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-timeout-arg",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      env: { EMBER_VERIFY_TIMEOUT_MINUTES: "45" },
      runProcess: (executable, args, cwd, timeoutMs) => {
        seenTimeouts.push(timeoutMs);
        return inner(executable, args, cwd);
      },
    });

    await waitForSettled();
    expect(seenTimeouts.length).toBeGreaterThan(0);
    expect(seenTimeouts.every((t) => t === 45 * 60_000)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// #1371 cure b — the timeout reaps the whole descendant tree, not just the child
// ---------------------------------------------------------------------------

describe("tree reap on timeout", () => {
  it("kills the descendant TREE on Windows, not just the direct child (the orphaned census grandchild ran 84 min past its parent)", () => {
    const cmd = _buildTreeKillCommand(4242, "win32");
    expect(cmd.executable).toBe("taskkill");
    expect(cmd.args).toEqual(["/PID", "4242", "/T", "/F"]);
    // /T is the tree flag; without it the grandchild survives. Assert it explicitly so a
    // future edit cannot quietly drop it back to a single-process kill.
    expect(cmd.args).toContain("/T");
  });

  it("reaps descendants on posix too", () => {
    const cmd = _buildTreeKillCommand(99, "linux");
    expect(cmd.executable).toBe("pkill");
    expect(cmd.args).toContain("-P");
    expect(cmd.args).toContain("99");
  });

  it("records every PID taskkill reports, always including the root even on unparseable output", () => {
    const parsed = _parseReapedPids(
      "SUCCESS: The process with PID 4242 has been terminated.\n" +
        "SUCCESS: The process with PID 5150 (child process of PID 4242) has been terminated.\n",
      4242,
    );
    expect(parsed).toContain(4242);
    expect(parsed).toContain(5150);
    expect(_parseReapedPids("", 7)).toEqual([7]);
  });
});

// ---------------------------------------------------------------------------
// #1371 cure c — a terminal state without a receipt is impossible
// ---------------------------------------------------------------------------

describe("run receipt", () => {
  it("writes receipt.json ON TIMEOUT with ok:false, failure_kind timeout, phase, timings and reaped PIDs -- the 2026-08-04 run wrote nothing at all", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-timeout");
    const calls: { executable: string; args: string[] }[] = [];

    const runProcess = mockRunner({
      worktreePath,
      calls,
      onIssueCensus: () => ({
        status: null,
        timedOut: true,
        reapedPids: [4242, 5150],
        stdout: "",
        stderr: "[verify: timed out]",
      }),
    });

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-timeout",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      timeoutMs: 60_000,
      runProcess,
    });

    await waitForSettled();
    const final = getVerifyState()!;
    expect(final.status).toBe("failed");
    expect(final.failureKind).toBe("timeout");
    expect(final.reapedPids).toEqual([4242, 5150]);

    const receipt = readRunReceipt(jobDir);
    expect(receipt["ok"]).toBe(false);
    expect(receipt["failure_kind"]).toBe("timeout");
    expect(receipt["phase"]).toBe("issue-census");
    expect(receipt["reaped_pids"]).toEqual([4242, 5150]);
    expect(receipt["pinned_commit"]).toBe(PINNED_COMMIT);
    expect(receipt["timeout_ms"]).toBe(60_000);
    expect(Object.keys(receipt["leg_timings_ms"] as object)).toContain("issue-census");
    // The verifier never ran, so there is no verifier receipt -- said explicitly rather
    // than pointing at a path that is not on disk.
    expect(receipt["verifier_receipt_path"]).toBeNull();
    // Even a timed-out run gives the worktree back.
    expect(calls.some((c) => c.args.includes("retire"))).toBe(true);
  });

  it("writes receipt.json when the worktree cannot even be created -- the earliest terminal state still leaves evidence", async () => {
    const jobDir = tmpJobDir();
    const runProcess = async (executable: string, args: string[]): Promise<VerifyProcessResult> => {
      if (executable === "git") return { status: 0, stdout: `${PINNED_COMMIT}\n`, stderr: "" };
      if (args.includes("create")) return { status: 2, stdout: "", stderr: "WORKTREE_CEILING: live=6 ceiling=6" };
      throw new Error(`unexpected call: ${executable} ${args.join(" ")}`);
    };

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-nowt",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      runProcess,
    });

    await waitForSettled();
    const receipt = readRunReceipt(jobDir);
    expect(receipt["ok"]).toBe(false);
    expect(receipt["failure_kind"]).toBe("worktree-create");
    expect(receipt["phase"]).toBe("preparing-worktree");
    expect(receipt["worktree_path"]).toBeNull();
    expect(receipt["error"]).toContain("WORKTREE_CEILING");
  });

  it("writes receipt.json on a GREEN run, carrying the verifier's leg vector and pointing at the verifier's own receipt", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-green");
    const calls: { executable: string; args: string[] }[] = [];

    const runProcess = mockRunner({
      worktreePath,
      calls,
      onVerifier: (args) => {
        fs.writeFileSync(
          args[args.indexOf("--receipt") + 1]!,
          JSON.stringify({ ok: true, legs: { "1": { status: "resolved-true", title: "custody root census" } } }),
        );
        return { status: 0, stdout: "green", stderr: "" };
      },
    });

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-green",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      runProcess,
    });

    await waitForSettled();
    const receipt = readRunReceipt(jobDir);
    expect(receipt["ok"]).toBe(true);
    expect(receipt["status"]).toBe("done");
    expect(receipt["failure_kind"]).toBeNull();
    expect(receipt["verifier_receipt_path"]).toContain("verifier-receipt.json");
    expect((receipt["legs"] as Record<string, { status: string }>)["1"]!.status).toBe("resolved-true");
    // The run receipt and the verifier receipt are separate files -- the verifier can
    // never overwrite the run-level one, and its absence can never be mistaken for a
    // missing run receipt.
    expect(fs.existsSync(path.join(jobDir, "verifier-receipt.json"))).toBe(true);
  });

  it("writes receipt.json with ok:false and failure_kind verifier-not-ok on a RED but completed run", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-red");
    const calls: { executable: string; args: string[] }[] = [];

    const runProcess = mockRunner({
      worktreePath,
      calls,
      onVerifier: (args) => {
        fs.writeFileSync(
          args[args.indexOf("--receipt") + 1]!,
          JSON.stringify({ ok: false, legs: { "1": { status: "resolved-false", title: "custody root census" } } }),
        );
        return { status: 1, stdout: "red", stderr: "" };
      },
    });

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-red",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      runProcess,
    });

    await waitForSettled();
    const receipt = readRunReceipt(jobDir);
    // The PIPELINE succeeded; the repository did not verify. Both facts are on the record.
    expect(receipt["status"]).toBe("done");
    expect(receipt["ok"]).toBe(false);
    expect(receipt["failure_kind"]).toBe("verifier-not-ok");
  });

  it("writes receipt.json when an infra leg (gh) fails", async () => {
    const jobDir = tmpJobDir();
    const worktreePath = path.join(os.tmpdir(), "verify-wt-job-ghfail");
    const calls: { executable: string; args: string[] }[] = [];

    startVerifyRun({
      repoRoot: "/repo",
      jobDir,
      jobId: "job-ghfail",
      envBindings: baseEnvBindings(),
      bindings: [],
      pythonBin: "python",
      ghBin: "gh",
      gitBin: "git",
      runProcess: mockRunner({
        worktreePath,
        calls,
        onGh: () => ({ status: 1, stdout: "", stderr: "gh: rate limited" }),
      }),
    });

    await waitForSettled();
    const receipt = readRunReceipt(jobDir);
    expect(receipt["ok"]).toBe(false);
    expect(receipt["failure_kind"]).toBe("gh");
    expect(receipt["phase"]).toBe("fetching-issues");
    expect(receipt["duration_ms"]).toBeGreaterThanOrEqual(0);
  });
});
