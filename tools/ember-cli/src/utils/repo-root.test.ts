// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// repo-root.test.ts — unit tests for the deterministic repo-root resolver (issue #172).

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { resolveEmberRepoRoot } from "./repo-root.ts";

let scratchDir: string;

function makeRepoMarker(root: string): void {
  fs.writeFileSync(path.join(root, "GOAL.md"), "# fixture goal\n");
  fs.mkdirSync(path.join(root, "tools", "ember-cli"), { recursive: true });
}

beforeEach(() => {
  scratchDir = fs.mkdtempSync(path.join(os.tmpdir(), "ember-repo-root-"));
});

afterEach(() => {
  fs.rmSync(scratchDir, { recursive: true, force: true });
});

describe("resolveEmberRepoRoot", () => {
  test("EMBER_REPO_ROOT env override wins over cwd/exe discovery", () => {
    const realRoot = path.join(scratchDir, "real-repo");
    fs.mkdirSync(realRoot, { recursive: true });
    makeRepoMarker(realRoot);

    // A decoy cwd that would ALSO resolve, so a passing test proves the env path was
    // actually taken, not merely that some resolution succeeded.
    const decoyRoot = path.join(scratchDir, "decoy-repo");
    const decoyNested = path.join(decoyRoot, "nested", "deep");
    fs.mkdirSync(decoyNested, { recursive: true });
    makeRepoMarker(decoyRoot);

    const resolved = resolveEmberRepoRoot({
      envRepoRoot: realRoot,
      startDir: decoyNested,
      execPath: path.join(scratchDir, "nowhere", "ember.exe"),
    });

    expect(resolved).toBe(realRoot);
  });

  test("cwd upward walk finds the repo root from a nested directory", () => {
    const root = path.join(scratchDir, "repo");
    const nested = path.join(root, "tools", "ember-cli", "src", "utils");
    fs.mkdirSync(nested, { recursive: true });
    makeRepoMarker(root);

    const resolved = resolveEmberRepoRoot({
      startDir: nested,
      execPath: path.join(scratchDir, "nowhere", "ember.exe"),
    });

    expect(resolved).toBe(root);
  });

  test("invalid EMBER_REPO_ROOT is rejected, not trusted — falls through to cwd discovery", () => {
    const root = path.join(scratchDir, "repo");
    fs.mkdirSync(root, { recursive: true });
    makeRepoMarker(root);

    const bogusEnv = path.join(scratchDir, "not-a-repo");
    fs.mkdirSync(bogusEnv, { recursive: true });

    const resolved = resolveEmberRepoRoot({
      envRepoRoot: bogusEnv,
      startDir: root,
      execPath: path.join(scratchDir, "nowhere", "ember.exe"),
    });

    expect(resolved).toBe(root);
  });

  test("execPath-relative walk finds the repo root regardless of an unrelated launch cwd", () => {
    const root = path.join(scratchDir, "repo");
    const exeDir = path.join(root, "tools", "ember-cli");
    fs.mkdirSync(exeDir, { recursive: true });
    makeRepoMarker(root);

    const arbitraryCwd = path.join(scratchDir, "some-unrelated-launch-dir");
    fs.mkdirSync(arbitraryCwd, { recursive: true });

    const resolved = resolveEmberRepoRoot({
      startDir: arbitraryCwd,
      execPath: path.join(exeDir, "ember.exe"),
    });

    expect(resolved).toBe(root);
  });

  test("no-marker case fails closed with an error naming EMBER_REPO_ROOT", () => {
    const arbitraryCwd = path.join(scratchDir, "no-repo-here");
    fs.mkdirSync(arbitraryCwd, { recursive: true });

    expect(() =>
      resolveEmberRepoRoot({
        startDir: arbitraryCwd,
        execPath: path.join(scratchDir, "also-nowhere", "ember.exe"),
      }),
    ).toThrow(/EMBER_REPO_ROOT/);
  });
});

// ---------------------------------------------------------------------------------------
// Issue #666 — worktree divergence: a git WORKTREE checkout carries the marker files, so
// the cwd walk validates the worktree root; a watchdog anchored at the main checkout then
// polls a heartbeat file nobody writes. The cure: every resolved candidate is
// canonicalized through the worktree's `.git` gitdir pointer to the main checkout root,
// so writer and watchdog converge on ONE root regardless of launch location.
// ---------------------------------------------------------------------------------------

/** Builds a main checkout + a linked-worktree-shaped checkout under scratchDir. The
 *  worktree carries the real on-disk shape `git worktree add` produces: marker files, plus
 *  a `.git` FILE containing `gitdir: <main>/.git/worktrees/<name>`. */
function makeMainAndWorktree(): { mainRoot: string; worktreeRoot: string } {
  const mainRoot = path.join(scratchDir, "main-checkout");
  fs.mkdirSync(path.join(mainRoot, ".git", "worktrees", "lane"), { recursive: true });
  makeRepoMarker(mainRoot);

  const worktreeRoot = path.join(scratchDir, "wt", "lane");
  fs.mkdirSync(worktreeRoot, { recursive: true });
  makeRepoMarker(worktreeRoot);
  fs.writeFileSync(
    path.join(worktreeRoot, ".git"),
    `gitdir: ${path.join(mainRoot, ".git", "worktrees", "lane")}\n`,
  );
  return { mainRoot, worktreeRoot };
}

describe("issue #666 — worktree-vs-main-checkout convergence", () => {
  test("divergence premise: worktree root and main root are different directories, and both carry the marker", () => {
    const { mainRoot, worktreeRoot } = makeMainAndWorktree();
    expect(worktreeRoot).not.toBe(mainRoot);
    expect(fs.existsSync(path.join(worktreeRoot, "GOAL.md"))).toBe(true);
    expect(fs.existsSync(path.join(mainRoot, "GOAL.md"))).toBe(true);
  });

  test("cwd inside a worktree resolves to the MAIN checkout root (the old behavior returned the worktree root)", () => {
    const { mainRoot, worktreeRoot } = makeMainAndWorktree();
    const deepCwd = path.join(worktreeRoot, "tools", "ember-cli");
    const resolved = resolveEmberRepoRoot({ startDir: deepCwd, envRepoRoot: "", execPath: path.join(scratchDir, "nowhere", "bin.exe") });
    expect(resolved).toBe(path.resolve(mainRoot));
  });

  test("writer-in-worktree and watchdog-in-main resolve the SAME root", () => {
    const { mainRoot, worktreeRoot } = makeMainAndWorktree();
    const writerRoot = resolveEmberRepoRoot({ startDir: worktreeRoot, envRepoRoot: "", execPath: path.join(scratchDir, "nowhere", "bin.exe") });
    const watchdogRoot = resolveEmberRepoRoot({ startDir: mainRoot, envRepoRoot: "", execPath: path.join(scratchDir, "nowhere", "bin.exe") });
    expect(writerRoot).toBe(watchdogRoot);
  });

  test("EMBER_REPO_ROOT pointed at a worktree is canonicalized to the main checkout too", () => {
    const { mainRoot, worktreeRoot } = makeMainAndWorktree();
    const resolved = resolveEmberRepoRoot({ envRepoRoot: worktreeRoot, startDir: scratchDir, execPath: path.join(scratchDir, "nowhere", "bin.exe") });
    expect(resolved).toBe(path.resolve(mainRoot));
  });

  test("a worktree whose gitdir pointer resolves to a NON-marker main tree throws (refuse loudly, never silently diverge)", () => {
    const { mainRoot, worktreeRoot } = makeMainAndWorktree();
    // Break the main checkout's marker: canonicalization now has no valid target.
    fs.rmSync(path.join(mainRoot, "GOAL.md"));
    expect(() =>
      resolveEmberRepoRoot({ startDir: worktreeRoot, envRepoRoot: "", execPath: path.join(scratchDir, "nowhere", "bin.exe") }),
    ).toThrow(/worktree/i);
  });

  test("a plain main checkout (`.git` is a directory) is returned unchanged", () => {
    const { mainRoot } = makeMainAndWorktree();
    const resolved = resolveEmberRepoRoot({ startDir: mainRoot, envRepoRoot: "", execPath: path.join(scratchDir, "nowhere", "bin.exe") });
    expect(resolved).toBe(path.resolve(mainRoot));
  });
});
