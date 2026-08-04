// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/verify-watch.integration.test.ts — the ONE non-mocked test in this node.
//
// Every other /verify test injects a subprocess runner, which is why a whole class of
// defect stayed invisible: the pipeline created its pinned worktree with `--branch`, but
// verify_ember01_completion.py runs its executable legs (and computes `ok`) only when the
// checkout is clean AND DETACHED. A mocked verifier answers 0 either way, so a run that
// could never have gone green looked green in the suite. This test therefore uses the
// REAL scripts/worktree_lifecycle.py against a REAL throwaway git repository, and asks
// the REAL verifier probe (verify_ember01_completion.inspect_checkout) what it sees.
//
// Nothing here touches the ember repository: the repo under test is created fresh in a
// temp directory per run, and only `scripts/` is read from the checkout.

import { describe, it, expect, beforeAll, afterAll } from "bun:test";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const REPO_ROOT = path.resolve(import.meta.dir, "../../../..");
const LIFECYCLE = path.join(REPO_ROOT, "scripts", "worktree_lifecycle.py");
const PYTHON = process.env["EMBER_PYTHON_BIN"] ?? "python";

/** Real git + real python startup per step; bun's 5s default is a stopwatch on the
 *  machine, not a statement about the code under test. */
const REAL_SUBPROCESS_TIMEOUT_MS = 120_000;

let tmpRoot: string;
let repo: string;

function run(executable: string, args: string[], cwd: string) {
  const result = spawnSync(executable, args, {
    cwd,
    encoding: "utf8",
    // PYTHONDONTWRITEBYTECODE: never leave __pycache__ inside a tree under test.
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  });
  return {
    status: result.status,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

function git(args: string[], cwd: string) {
  return run("git", args, cwd);
}

function lifecycle(args: string[]) {
  return run(PYTHON, ["-B", LIFECYCLE, "--repo", repo, ...args], repo);
}

beforeAll(() => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "verify-wt-integration-"));
  repo = path.join(tmpRoot, "repo");
  fs.mkdirSync(repo);
  git(["init", "-b", "master"], repo);
  git(["config", "user.name", "Ember Test"], repo);
  git(["config", "user.email", "ember@example.invalid"], repo);
  fs.writeFileSync(path.join(repo, "seed.txt"), "seed\n");
  git(["add", "seed.txt"], repo);
  git(["commit", "-m", "seed"], repo);
  expect(lifecycle(["install", "--target", "3"]).status).toBe(0);
});

afterAll(() => {
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

describe("pinned verification worktree (real lifecycle script, real git, real verifier probe)", () => {
  it("is created DETACHED, so the verifier's own checkout probe can pass -- #1371 B1", () => {
    const worktree = path.join(tmpRoot, "verify-wt");
    const head = git(["rev-parse", "HEAD"], repo).stdout.trim();

    const created = lifecycle([
      "create",
      "--path", worktree,
      "--detach",
      "--owner", "ember-cli-verify",
      "--purpose", "verify dispatch integration",
      "--expires", "2999-01-01",
      "--start-point", head,
    ]);
    expect(created.status).toBe(0);
    const payload = JSON.parse(created.stdout) as Record<string, unknown>;
    expect(payload["status"]).toBe("CREATED");
    expect(payload["detached"]).toBe(true);
    expect(payload["branch"]).toBeNull();

    // Git's own answer: symbolic-ref fails on a detached HEAD. This is the exact call
    // verify_ember01_completion.inspect_checkout makes.
    expect(git(["symbolic-ref", "--quiet", "HEAD"], worktree).status).not.toBe(0);

    // The verifier's answer, asked of the real function rather than re-implemented here.
    const probe = run(
      PYTHON,
      [
        "-B", "-c",
        [
          "import json, sys",
          `sys.path.insert(0, ${JSON.stringify(path.join(REPO_ROOT, "scripts"))})`,
          "from pathlib import Path",
          "from verify_ember01_completion import inspect_checkout",
          `print(json.dumps(inspect_checkout(Path(${JSON.stringify(worktree)}))))`,
        ].join("\n"),
      ],
      repo,
    );
    expect(probe.status).toBe(0);
    const checkout = JSON.parse(probe.stdout) as Record<string, unknown>;
    expect(checkout["detached"]).toBe(true);
    expect(checkout["clean"]).toBe(true);
    expect(checkout["head"]).toBe(head);
    // clean AND detached is the gate at verify_ember01_completion.py's executable-leg
    // branch; with a branch-attached worktree this pair is unreachable and all nine legs
    // come back UNRESOLVED.
    expect(checkout["clean"] === true && checkout["detached"] === true).toBe(true);

    // #1371 N4: no refs/heads/verify/* accrues per run. The attached mode left one behind
    // permanently, on a shared repository surface, for every verification ever run.
    const refs = git(["for-each-ref", "--format=%(refname)", "refs/heads/"], repo).stdout.trim();
    expect(refs).toBe("refs/heads/master");

    // Retire takes the archive-ref path for a detached row, preserving the head without
    // a permanent branch.
    const retired = lifecycle(["retire", "--path", worktree]);
    expect(retired.status).toBe(0);
    const retirePayload = JSON.parse(retired.stdout) as Record<string, unknown>;
    expect(retirePayload["archive_ref"]).toBeTruthy();
    expect(git(["rev-parse", String(retirePayload["archive_ref"])], repo).stdout.trim()).toBe(head);
    expect(fs.existsSync(worktree)).toBe(false);
  }, REAL_SUBPROCESS_TIMEOUT_MS);

  it("can still be given back when a killed leg left the verifier's scratch behind -- #1371 N3", () => {
    const worktree = path.join(tmpRoot, "verify-wt-dirty");
    const head = git(["rev-parse", "HEAD"], repo).stdout.trim();
    expect(
      lifecycle([
        "create",
        "--path", worktree,
        "--detach",
        "--owner", "ember-cli-verify",
        "--purpose", "verify dispatch integration dirty",
        "--expires", "2999-01-01",
        "--start-point", head,
      ]).status,
    ).toBe(0);

    // Exactly what a timeout leaves: the verifier's own scratch, never cleaned up because
    // the python process was killed before its unlink ran.
    fs.writeFileSync(path.join(worktree, ".ember01-verify-custody.tmp.json"), "{}");

    // Plain retire refuses -- the fail-closed behaviour stays fail-closed.
    const plain = lifecycle(["retire", "--path", worktree]);
    expect(plain.status).not.toBe(0);
    expect(plain.stderr).toContain("DIRTY_WORKTREE");

    // Another owner cannot force it. The owner match IS the safety property.
    const wrongOwner = lifecycle([
      "retire", "--path", worktree, "--force-owner", "someone-else",
    ]);
    expect(wrongOwner.status).not.toBe(0);
    expect(fs.existsSync(worktree)).toBe(true);

    const forced = lifecycle([
      "retire", "--path", worktree, "--force-owner", "ember-cli-verify",
    ]);
    expect(forced.status).toBe(0);
    expect((JSON.parse(forced.stdout) as Record<string, unknown>)["forced"]).toBe(true);
    expect(fs.existsSync(worktree)).toBe(false);
  }, REAL_SUBPROCESS_TIMEOUT_MS);
});
