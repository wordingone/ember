// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// repo-root.test.ts — unit tests for the deterministic repo-root resolver (issue #172).

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  resolveEmberRepoRoot,
  resolveEmberSourceRoot,
  CanonicalRootError,
} from "./repo-root.ts";

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

describe("source-byte authority in a linked worktree", () => {
  test("source resolution preserves the selected worktree while state resolution converges on main", async () => {
    const { mainRoot, worktreeRoot } = makeMainAndWorktree();
    const options = {
      envRepoRoot: worktreeRoot,
      startDir: scratchDir,
      execPath: path.join(scratchDir, "nowhere", "bin.exe"),
    };
    expect(resolveEmberSourceRoot(options)).toBe(path.resolve(worktreeRoot));
    expect(resolveEmberRepoRoot(options)).toBe(path.resolve(mainRoot));
  });
});

describe("root-authority consumer wiring", () => {
  test("every production consumer keeps its explicit source-or-state disposition", () => {
    const srcRoot = path.resolve(import.meta.dir, "..");
    const read = (relativePath: string): string =>
      fs.readFileSync(path.join(srcRoot, relativePath), "utf8");

    const exactCheckoutConsumers = [
      "commands/train.ts",
      "commands/benchmark.ts",
      "commands/model.ts",
      "components/spine-panel.ts",
      "entrypoints/process-entry.ts",
    ];
    for (const relativePath of exactCheckoutConsumers) {
      const source = read(relativePath);
      expect(source).toContain("import { resolveEmberSourceRootOrCwd }");
      expect(source).not.toContain("import { resolveEmberRepoRootOrCwd }");
    }

    const canonicalStateConsumers = [
      "hardening/hardening-receipts.ts",
      "services/activity-feed.ts",
      "services/brain-server-supervisor.ts",
      "services/github-receipts.ts",
      "services/goal-persistence.ts",
      "services/goal-receipts.ts",
      "services/operator-receipts.ts",
      "services/outage-banner-poller.ts",
    ];
    for (const relativePath of canonicalStateConsumers) {
      const source = read(relativePath);
      expect(source).toContain("import { resolveEmberRepoRootOrCwd }");
      expect(source).not.toContain("import { resolveEmberSourceRootOrCwd }");
    }

    const custody = read("commands/custody.ts");
    expect(custody).toContain("resolveEmberSourceRootOrCwd");
    expect(custody).toContain("resolveEmberRepoRootOrCwd");
    expect(custody).toContain("/custody identity");
    expect(custody).toContain("/custody");
  });
});
// ---------------------------------------------------------------------------------------
// PR954 round 2 — strict resolver: a marker-valid standalone root with NO .git at all is
// accepted as-is (git-less deployment / plain copy). Every OTHER `.git`-FILE shape that
// fails to fully resolve to a marker-valid main checkout now THROWS a typed
// CanonicalRootError instead of silently falling back to the (possibly wrong) worktree
// root -- the old canonicalizeThroughWorktree swallowed unreadable/malformed/unsupported
// gitdir shapes and returned `root`, which is exactly the silent divergence issue #666
// exists to kill.
// ---------------------------------------------------------------------------------------

describe("PR954 round 2 — strict resolver: typed throws on malformed/unreadable/unsupported .git FILE shapes", () => {
  test("standalone root with no .git at all is accepted (git-less deployment)", () => {
    const root = path.join(scratchDir, "standalone-repo");
    fs.mkdirSync(root, { recursive: true });
    makeRepoMarker(root);
    expect(fs.existsSync(path.join(root, ".git"))).toBe(false);

    const resolved = resolveEmberRepoRoot({
      startDir: root,
      execPath: path.join(scratchDir, "nowhere", "bin.exe"),
    });
    expect(resolved).toBe(path.resolve(root));
  });

  test("`.git` FILE with a gitdir: line that isn't the worktrees/<name> shape (e.g. a submodule) throws CanonicalRootError, never silently returns the root", () => {
    const root = path.join(scratchDir, "submodule-like");
    fs.mkdirSync(root, { recursive: true });
    makeRepoMarker(root);
    const modulesDir = path.join(scratchDir, "parent-repo", ".git", "modules", "sub");
    fs.mkdirSync(modulesDir, { recursive: true });
    fs.writeFileSync(path.join(root, ".git"), `gitdir: ${modulesDir}\n`);

    expect(() =>
      resolveEmberRepoRoot({
        startDir: root,
        envRepoRoot: "",
        execPath: path.join(scratchDir, "nowhere", "bin.exe"),
      }),
    ).toThrow(CanonicalRootError);
  });

  test("`.git` FILE with content that does not match the `gitdir:` shape at all throws CanonicalRootError", () => {
    const root = path.join(scratchDir, "malformed-gitfile");
    fs.mkdirSync(root, { recursive: true });
    makeRepoMarker(root);
    fs.writeFileSync(path.join(root, ".git"), "not a gitdir pointer at all\n");

    expect(() =>
      resolveEmberRepoRoot({
        startDir: root,
        envRepoRoot: "",
        execPath: path.join(scratchDir, "nowhere", "bin.exe"),
      }),
    ).toThrow(CanonicalRootError);
  });

  test("resolveEmberRepoRoot's existing worktree->non-marker-main throw is still CanonicalRootError (typed, not a bare Error)", () => {
    const { mainRoot, worktreeRoot } = makeMainAndWorktree();
    fs.rmSync(path.join(mainRoot, "GOAL.md"));
    expect(() =>
      resolveEmberRepoRoot({ startDir: worktreeRoot, envRepoRoot: "", execPath: path.join(scratchDir, "nowhere", "bin.exe") }),
    ).toThrow(CanonicalRootError);
  });
});

// ---------------------------------------------------------------------------------------
// PR954 round 3 — reviewer reject on round 2: an exact single-record parser (a junk-
// prefixed or otherwise multi-line `.git` FILE must reject, not validate against whichever
// line happens to match `gitdir:`) and a dangling-target check (the resolved
// `<main>/.git/worktrees/<name>` directory must actually exist).
// ---------------------------------------------------------------------------------------

describe("PR954 round 3 — exact single-record .git FILE parser", () => {
  test("junk-prefixed content (a valid gitdir: line preceded by garbage) is REJECTED, not silently matched", () => {
    // Main root VALIDATES and the worktrees/lane target EXISTS, so the only possible
    // cause of a throw here is the exact-single-record parser rejecting the junk prefix
    // -- isolates this from the "main doesn't validate" / "dangling target" throw paths.
    const mainRoot = path.join(scratchDir, "main-for-junk");
    const worktreesDir = path.join(mainRoot, ".git", "worktrees", "lane");
    fs.mkdirSync(worktreesDir, { recursive: true });
    makeRepoMarker(mainRoot);

    const root = path.join(scratchDir, "junk-prefixed");
    fs.mkdirSync(root, { recursive: true });
    makeRepoMarker(root);
    fs.writeFileSync(root + "/.git", `junk\ngitdir: ${worktreesDir}\n`);

    expect(() =>
      resolveEmberRepoRoot({
        startDir: root,
        envRepoRoot: "",
        execPath: path.join(scratchDir, "nowhere", "bin.exe"),
      }),
    ).toThrow(CanonicalRootError);
  });

  test("a trailing junk line AFTER the gitdir: record is also REJECTED", () => {
    const mainRoot = path.join(scratchDir, "main-for-junk2");
    const worktreesDir = path.join(mainRoot, ".git", "worktrees", "lane");
    fs.mkdirSync(worktreesDir, { recursive: true });
    makeRepoMarker(mainRoot);

    const root = path.join(scratchDir, "junk-suffixed");
    fs.mkdirSync(root, { recursive: true });
    makeRepoMarker(root);
    fs.writeFileSync(root + "/.git", `gitdir: ${worktreesDir}\nextra junk\n`);

    expect(() =>
      resolveEmberRepoRoot({
        startDir: root,
        envRepoRoot: "",
        execPath: path.join(scratchDir, "nowhere", "bin.exe"),
      }),
    ).toThrow(CanonicalRootError);
  });

  test("a single gitdir: record with exactly one trailing newline is ACCEPTED (the common on-disk shape)", () => {
    const mainRoot = path.join(scratchDir, "single-record-main");
    const worktreesDir = path.join(mainRoot, ".git", "worktrees", "lane");
    fs.mkdirSync(worktreesDir, { recursive: true });
    makeRepoMarker(mainRoot);
    const worktreeRoot = path.join(scratchDir, "single-record-wt");
    fs.mkdirSync(worktreeRoot, { recursive: true });
    makeRepoMarker(worktreeRoot);
    fs.writeFileSync(path.join(worktreeRoot, ".git"), `gitdir: ${worktreesDir}\n`);

    const resolved = resolveEmberRepoRoot({
      startDir: worktreeRoot,
      envRepoRoot: "",
      execPath: path.join(scratchDir, "nowhere", "bin.exe"),
    });
    expect(resolved).toBe(path.resolve(mainRoot));
  });

  test("a single gitdir: record with NO trailing newline is also ACCEPTED", () => {
    const mainRoot = path.join(scratchDir, "no-newline-main");
    const worktreesDir = path.join(mainRoot, ".git", "worktrees", "lane");
    fs.mkdirSync(worktreesDir, { recursive: true });
    makeRepoMarker(mainRoot);
    const worktreeRoot = path.join(scratchDir, "no-newline-wt");
    fs.mkdirSync(worktreeRoot, { recursive: true });
    makeRepoMarker(worktreeRoot);
    fs.writeFileSync(path.join(worktreeRoot, ".git"), `gitdir: ${worktreesDir}`);

    const resolved = resolveEmberRepoRoot({
      startDir: worktreeRoot,
      envRepoRoot: "",
      execPath: path.join(scratchDir, "nowhere", "bin.exe"),
    });
    expect(resolved).toBe(path.resolve(mainRoot));
  });
});

describe("PR954 round 3 — dangling worktree gitdir target", () => {
  test("a gitdir: pointer whose target directory does not exist on disk is REJECTED (dangling pointer)", () => {
    const mainRoot = path.join(scratchDir, "dangling-main");
    fs.mkdirSync(mainRoot, { recursive: true });
    makeRepoMarker(mainRoot);
    // Deliberately do NOT create <mainRoot>/.git/worktrees/lane -- the pointer target
    // must not exist for this test.
    const danglingTarget = path.join(mainRoot, ".git", "worktrees", "lane");
    expect(fs.existsSync(danglingTarget)).toBe(false);

    const worktreeRoot = path.join(scratchDir, "dangling-wt");
    fs.mkdirSync(worktreeRoot, { recursive: true });
    makeRepoMarker(worktreeRoot);
    fs.writeFileSync(path.join(worktreeRoot, ".git"), `gitdir: ${danglingTarget}\n`);

    expect(() =>
      resolveEmberRepoRoot({
        startDir: worktreeRoot,
        envRepoRoot: "",
        execPath: path.join(scratchDir, "nowhere", "bin.exe"),
      }),
    ).toThrow(CanonicalRootError);
  });

  test("a gitdir: pointer whose target exists but is a FILE, not a directory, is also REJECTED", () => {
    const mainRoot = path.join(scratchDir, "file-target-main");
    fs.mkdirSync(path.join(mainRoot, ".git"), { recursive: true });
    makeRepoMarker(mainRoot);
    const fileTarget = path.join(mainRoot, ".git", "worktrees-lane-file");
    fs.writeFileSync(fileTarget, "not a directory");

    const worktreeRoot = path.join(scratchDir, "file-target-wt");
    fs.mkdirSync(worktreeRoot, { recursive: true });
    makeRepoMarker(worktreeRoot);
    // Shape the pointer as <main>/.git/worktrees/<name> textually so the regex still
    // matches the worktree shape, but point it at a path where "worktrees/<name>" itself
    // resolves to a FILE (not a directory) -- exercises the isDirectory() check, not just
    // existsSync().
    const fakeWorktreesDir = path.join(mainRoot, ".git", "worktrees");
    fs.mkdirSync(fakeWorktreesDir, { recursive: true });
    const fileNotDir = path.join(fakeWorktreesDir, "lane");
    fs.writeFileSync(fileNotDir, "not a directory");
    fs.writeFileSync(path.join(worktreeRoot, ".git"), `gitdir: ${fileNotDir}\n`);

    expect(() =>
      resolveEmberRepoRoot({
        startDir: worktreeRoot,
        envRepoRoot: "",
        execPath: path.join(scratchDir, "nowhere", "bin.exe"),
      }),
    ).toThrow(CanonicalRootError);
  });
});
