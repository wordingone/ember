// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// ember-state-root.test.ts — the resolution point that keeps cockpit-mutable state out of
// the certified tree (issue #1330).
//
// KEY_PARITY_VECTORS is the shared contract with Get-EmberStateRootKey in
// scripts/launch-ember-cli.ps1: tests/test_ember_root_launcher.py drives the SAME inputs
// through the PowerShell side and asserts the SAME outputs. If either implementation
// drifts, one of the two suites goes red — the failure mode this pins is a launcher and a
// cockpit that silently disagree about where state lives.

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { isAbsolute, join, sep } from "node:path";
import {
  IN_TREE_STATE_DIR_NAME,
  emberStatePath,
  emberStateRoot,
  isUnderEmberState,
  repoStateKey,
} from "./ember-state-root.ts";
import { _resetConfigHomeMemo } from "./env-detection.ts";

/** [repo root, expected key] — mirrored verbatim in tests/test_ember_root_launcher.py. */
export const KEY_PARITY_VECTORS: ReadonlyArray<readonly [string, string]> = [
  ["C:\\fixture\\ember", "c-fixture-ember"],
  ["C:\\Fixture\\Ember\\", "c-fixture-ember"],
  ["C:\\fixture\\ember repo", "c-fixture-ember-repo"],
  ["C:\\fixture\\ember-wt\\wt-1330", "c-fixture-ember-wt-wt-1330"],
];

const SAVED_STATE_ROOT = process.env["EMBER_STATE_ROOT"];
const SAVED_EMBER_HOME = process.env["EMBER_HOME"];

function setEnv(name: string, value: string | undefined): void {
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
}

beforeEach(() => {
  delete process.env["EMBER_STATE_ROOT"];
  _resetConfigHomeMemo();
});

afterEach(() => {
  setEnv("EMBER_STATE_ROOT", SAVED_STATE_ROOT);
  setEnv("EMBER_HOME", SAVED_EMBER_HOME);
  _resetConfigHomeMemo();
});

describe("repoStateKey — cross-language parity", () => {
  for (const [root, expected] of KEY_PARITY_VECTORS) {
    test(`'${root}' keys to '${expected}'`, () => {
      expect(repoStateKey(root)).toBe(expected);
    });
  }

  test("a trailing separator and a case difference key to one directory", () => {
    // Windows paths are case-insensitive: two spellings of one checkout must not end up
    // with two divergent state directories.
    expect(repoStateKey("C:\\fixture\\ember\\")).toBe(repoStateKey("C:\\FIXTURE\\Ember"));
  });

  test("distinct checkouts never collide", () => {
    expect(repoStateKey("C:\\fixture\\ember")).not.toBe(repoStateKey("C:\\fixture\\ember2"));
  });
});

describe("emberStateRoot", () => {
  test("EMBER_STATE_ROOT is used verbatim — the launcher is the single authority", () => {
    process.env["EMBER_STATE_ROOT"] = join("C:", "cockpit-state");
    expect(emberStateRoot("C:\\fixture\\ember")).toBe(join("C:", "cockpit-state"));
  });

  test("every cwd in a session collapses onto the one exported root", () => {
    process.env["EMBER_STATE_ROOT"] = join("C:", "cockpit-state");
    expect(emberStateRoot("C:\\fixture\\ember\\tools")).toBe(
      emberStateRoot("C:\\fixture\\ember"),
    );
  });

  test("a blank EMBER_STATE_ROOT does not win — it falls through to the default", () => {
    process.env["EMBER_STATE_ROOT"] = "   ";
    process.env["EMBER_HOME"] = join("C:", "home", ".ember");
    _resetConfigHomeMemo();
    expect(emberStateRoot("C:\\fixture\\ember")).toBe(
      join("C:", "home", ".ember", "cockpit-state", "c-fixture-ember"),
    );
  });

  test("the default is per-checkout under EMBER_HOME, never inside the tree", () => {
    process.env["EMBER_HOME"] = join("C:", "home", ".ember");
    _resetConfigHomeMemo();
    const root = join("C:", "fixture", "ember");
    const resolved = emberStateRoot(root);
    expect(resolved).toBe(join("C:", "home", ".ember", "cockpit-state", repoStateKey(root)));
    expect(resolved.startsWith(root + sep)).toBe(false);
  });

  test("the resolved root is absolute and carries no in-tree segment", () => {
    process.env["EMBER_HOME"] = join("C:", "home", ".config-home");
    _resetConfigHomeMemo();
    const resolved = emberStateRoot(join("C:", "fixture", "ember"));
    expect(isAbsolute(resolved)).toBe(true);
    expect(resolved.split(sep)).not.toContain(IN_TREE_STATE_DIR_NAME);
  });
});

describe("emberStatePath", () => {
  test("joins segments under the resolved root", () => {
    process.env["EMBER_STATE_ROOT"] = join("C:", "cockpit-state");
    expect(emberStatePath("C:\\fixture\\ember", "goals", "sess-1.json")).toBe(
      join("C:", "cockpit-state", "goals", "sess-1.json"),
    );
  });

  test("no segment lands inside the checkout it belongs to", () => {
    process.env["EMBER_HOME"] = join("C:", "home", ".ember");
    _resetConfigHomeMemo();
    const root = join("C:", "fixture", "ember");
    for (const name of ["root-bindings.json", "settings.json", "kill-receipts.jsonl"]) {
      expect(emberStatePath(root, name).startsWith(root + sep)).toBe(false);
    }
  });
});

describe("isUnderEmberState", () => {
  test("recognizes a path under the resolved external root", () => {
    process.env["EMBER_STATE_ROOT"] = join("C:", "cockpit-state");
    expect(isUnderEmberState(join("C:", "cockpit-state", "skills", "a.md"), "C:\\fixture")).toBe(
      true,
    );
  });

  test("still recognizes a legacy in-tree segment on an unmigrated machine", () => {
    process.env["EMBER_STATE_ROOT"] = join("C:", "cockpit-state");
    expect(isUnderEmberState(join("C:", "fixture", ".ember", "skills", "a.md"))).toBe(true);
    expect(isUnderEmberState("C:/fixture/.ember/skills/a.md")).toBe(true);
  });

  test("an unrelated path is not cockpit state", () => {
    process.env["EMBER_STATE_ROOT"] = join("C:", "cockpit-state");
    expect(isUnderEmberState(join("C:", "fixture", "src", "a.ts"), "C:\\fixture")).toBe(false);
  });

  test("the state root itself is not 'under' itself — only its contents are", () => {
    process.env["EMBER_STATE_ROOT"] = join("C:", "cockpit-state");
    expect(isUnderEmberState(join("C:", "cockpit-state"), "C:\\fixture")).toBe(false);
  });
});
