// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/instruction-files.ts -- finds the standing-instruction files for a working directory.
//
// Order is the order the model reads them: the user's $EMBER_HOME/EMBER.md first, then
// EMBER.md / AGENTS.md / CLAUDE.md in every directory from the repository root down to the
// cwd, so the file nearest the cwd comes last and wins a conflict. Shared by the system-prompt
// loader and by the compaction instructions reader.

import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";

export const INSTRUCTION_FILE_NAMES = ["EMBER.md", "AGENTS.md", "CLAUDE.md"] as const;

export interface InstructionFile {
  path: string;
  scope: "user" | "project";
}

export interface InstructionDiscoveryOpts {
  cwd: string;
  /** Defaults to the memoized EMBER_HOME / ~/.ember directory. */
  home?: string;
}

function isFile(path: string): boolean {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

/** Nearest ancestor of `cwd` (inclusive) that holds a `.git` entry; `cwd` itself when none does. */
export function findProjectRoot(cwd: string): string {
  let dir = resolve(cwd);
  for (;;) {
    if (existsSync(join(dir, ".git"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) return resolve(cwd);
    dir = parent;
  }
}

/** Directories from the project root down to `cwd`, root first. */
export function projectDirChain(cwd: string): string[] {
  const start = resolve(cwd);
  const root = findProjectRoot(start);
  const chain: string[] = [start];
  let dir = start;
  while (dir !== root) {
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
    chain.push(dir);
  }
  return chain.reverse();
}

export function discoverInstructionFiles(opts: InstructionDiscoveryOpts): InstructionFile[] {
  const home = opts.home ?? getEmberConfigHomeDir();
  const found: InstructionFile[] = [];
  const userFile = join(home, "EMBER.md");
  if (isFile(userFile)) found.push({ path: userFile, scope: "user" });
  for (const dir of projectDirChain(opts.cwd)) {
    for (const name of INSTRUCTION_FILE_NAMES) {
      const path = join(dir, name);
      if (isFile(path)) found.push({ path, scope: "project" });
    }
  }
  return found;
}

/** UTF-8 text of an instruction file, BOM stripped; null when unreadable. */
export function readInstructionText(path: string): string | null {
  try {
    return readFileSync(path, "utf-8").replace(/^﻿/, "");
  } catch {
    return null;
  }
}
