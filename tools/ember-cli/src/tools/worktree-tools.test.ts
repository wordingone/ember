// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// worktree-tools.test.ts — the cockpit refuses to create git worktrees (issue #1330,
// repo guard #1009).
//
// These assert the operator-facing TEXT, not merely that something threw. A refusal an
// operator cannot act on is indistinguishable from a bug: it has to say why the cockpit
// will not do this, name the command that will, and hand over a concrete path.

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { join, sep } from "node:path";
import { buildWorktreeRefusal, gitOps } from "./worktree-tools.ts";

const SAVED_STATE_ROOT = process.env["EMBER_STATE_ROOT"];

beforeEach(() => {
  process.env["EMBER_STATE_ROOT"] = join("C:", "fixture", "cockpit-state");
});

afterEach(() => {
  if (SAVED_STATE_ROOT === undefined) delete process.env["EMBER_STATE_ROOT"];
  else process.env["EMBER_STATE_ROOT"] = SAVED_STATE_ROOT;
});

describe("cockpit worktree creation is refused", () => {
  const PATH = join("C:", "fixture", "cockpit-state", "worktrees", "wt-alpha");

  test("createWorktree rejects rather than registering a worktree", async () => {
    await expect(
      gitOps.createWorktree({ gitRoot: join("C:", "fixture", "ember"), path: PATH, branch: "worktree/wt-alpha" }),
    ).rejects.toThrow(/refused/i);
  });

  test("the refusal explains WHY, in terms of the census and the guard", () => {
    const text = buildWorktreeRefusal(PATH, "worktree/wt-alpha");
    // The load-bearing point: relocating the path does not remove it from the census,
    // because the worktree shares the repository's .git and stays registered.
    expect(text).toContain(".git");
    expect(text).toContain("registered");
    expect(text).toContain("census");
    expect(text).toContain("#1009");
  });

  test("the refusal names the sanctioned command and a concrete path", () => {
    const text = buildWorktreeRefusal(PATH, "worktree/wt-alpha");
    expect(text).toContain("python scripts/worktree_lifecycle.py create");
    expect(text).toContain("--owner");
    expect(text).toContain("--purpose");
    expect(text).toContain("--expires");
    expect(text).toContain(PATH);
    expect(text).toContain("worktree/wt-alpha");
  });

  test("the offered path is outside the checkout it belongs to", () => {
    const checkout = join("C:", "fixture", "ember");
    expect(PATH.startsWith(checkout + sep)).toBe(false);
    expect(buildWorktreeRefusal(PATH, "b")).toContain("outside this checkout");
  });
});
