// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/instruction-files.test.ts -- discovery order of EMBER.md / AGENTS.md / CLAUDE.md.

import { afterEach, describe, expect, it } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { discoverInstructionFiles, findProjectRoot, projectDirChain } from "./instruction-files.ts";

const made: string[] = [];
function scratch(): string {
  const d = mkdtempSync(join(tmpdir(), "ember-instr-"));
  made.push(d);
  return d;
}
afterEach(() => {
  for (const d of made.splice(0)) rmSync(d, { recursive: true, force: true });
});

function put(path: string, text = "x"): void {
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, text);
}

describe("instruction file discovery", () => {
  it("lists the user file first, then the repo root down to the cwd", () => {
    const root = scratch();
    const home = scratch();
    mkdirSync(join(root, ".git"));
    put(join(home, "EMBER.md"));
    put(join(root, "AGENTS.md"));
    put(join(root, "EMBER.md"));
    put(join(root, "pkg", "CLAUDE.md"));
    put(join(root, "pkg", "app", "EMBER.md"));
    const found = discoverInstructionFiles({ cwd: join(root, "pkg", "app"), home });
    expect(found.map((f) => f.path)).toEqual([
      join(home, "EMBER.md"),
      join(root, "EMBER.md"),
      join(root, "AGENTS.md"),
      join(root, "pkg", "CLAUDE.md"),
      join(root, "pkg", "app", "EMBER.md"),
    ]);
    expect(found.map((f) => f.scope)).toEqual(["user", "project", "project", "project", "project"]);
  });

  it("does not look above the repository root", () => {
    const outer = scratch();
    const home = scratch();
    put(join(outer, "EMBER.md"));
    mkdirSync(join(outer, "repo", ".git"), { recursive: true });
    put(join(outer, "repo", "AGENTS.md"));
    const found = discoverInstructionFiles({ cwd: join(outer, "repo"), home });
    expect(found.map((f) => f.path)).toEqual([join(outer, "repo", "AGENTS.md")]);
  });

  it("outside a repository only the cwd is searched", () => {
    const home = scratch();
    const dir = scratch();
    put(join(dir, "EMBER.md"));
    mkdirSync(join(dir, "sub"));
    expect(projectDirChain(join(dir, "sub")).length).toBe(1);
    const found = discoverInstructionFiles({ cwd: join(dir, "sub"), home });
    expect(found).toEqual([]);
  });

  it("treats a .git file (linked worktree) as a repository root", () => {
    const root = scratch();
    writeFileSync(join(root, ".git"), "gitdir: elsewhere");
    mkdirSync(join(root, "a"));
    expect(findProjectRoot(join(root, "a"))).toBe(root);
  });

  it("ignores a directory named like an instruction file", () => {
    const home = scratch();
    const dir = scratch();
    mkdirSync(join(dir, "EMBER.md"));
    expect(discoverInstructionFiles({ cwd: dir, home })).toEqual([]);
  });
});
