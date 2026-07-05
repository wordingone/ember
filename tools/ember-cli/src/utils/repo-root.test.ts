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
