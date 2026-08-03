// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// ember-state-root.ts — the ONE TypeScript resolution point for cockpit-mutable state
// (issue #1330).
//
// The completion verifier certifies the local execution tree by TOTALITY: it censuses and
// fingerprints every file, tracked and untracked, so any resident writer produces
// list-vs-hash contradictions and a red receipt. That totality is load-bearing (it caught
// the run15 stale-cockpit contamination) and must never be weakened with path exclusions.
// The cure is on the writer side: the cockpit's mutable state lives OUTSIDE the certified
// tree, so the cockpit can stay up during verification instead of being quiesced for it.
//
// Every call site that used to compute `join(root, ".ember", ...)` now calls
// `emberStatePath()`. No module may reconstruct that join itself — a single literal
// elsewhere silently reintroduces the class this module exists to kill, and
// repo-guard.sh's cockpit-state check only sees the directory once it is already resident.
//
// Resolution order:
//   1. `EMBER_STATE_ROOT` — used VERBATIM. scripts/launch-ember-cli.ps1 computes the root
//      and exports it into the cockpit child, so at runtime there is exactly one authority
//      for the location and every cwd inside a session collapses onto it.
//   2. `<EMBER_HOME>/cockpit-state/<repoStateKey(root)>` — the fallback for a direct/dev
//      invocation that did not come through the launcher. `EMBER_HOME` defaults to
//      `~/.ember` (utils/env-detection.ts), the same user-scoped config home the CLI
//      already owns; the per-root key keeps two checkouts from sharing one state dir.
//
// The default's key derivation is mirrored by Get-EmberStateRootKey in
// scripts/launch-ember-cli.ps1. Both sides are pinned to the same fixture vectors
// (ember-state-root.test.ts / tests/test_ember_root_launcher.py) so the two
// implementations cannot drift apart unnoticed.

import { isAbsolute, join, resolve, sep } from "node:path";
import { getEmberConfigHomeDir } from "./env-detection.ts";

/** The legacy in-tree directory name. Retained ONLY so residue detection and the
 *  skill-directory write triggers can still recognize a pre-relocation path; it is never
 *  used to build a write target. */
export const IN_TREE_STATE_DIR_NAME = ".ember";

/** Filesystem-safe, case-stable key for a checkout root. Lowercased because Windows paths
 *  are case-insensitive: two spellings of one checkout must key to one state directory. */
export function repoStateKey(root: string): string {
  const key = resolve(root)
    .replace(/[\\/]+$/, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (key.length === 0) {
    throw new Error(`[ember-state-root] cannot derive a state key from root '${root}'`);
  }
  return key;
}

/** Absolute root of all cockpit-mutable state for `root`. Never inside the certified tree. */
export function emberStateRoot(root: string): string {
  const override = process.env["EMBER_STATE_ROOT"];
  if (override !== undefined && override.trim().length > 0) {
    return resolve(override.trim());
  }
  return join(getEmberConfigHomeDir(), "cockpit-state", repoStateKey(root));
}

/** Path to a named piece of cockpit state under `root`'s external state root. */
export function emberStatePath(root: string, ...segments: string[]): string {
  return join(emberStateRoot(root), ...segments);
}

/** True when `filePath` is cockpit state: under the resolved external root, or carrying a
 *  legacy in-tree `.ember` path segment. Both arms are needed — the external root is where
 *  state lives now, and the legacy segment still identifies state on a machine that has not
 *  been migrated yet (and in the `~/.ember` user config home, which never moves). */
export function isUnderEmberState(filePath: string, root?: string): boolean {
  const segment = `${sep}${IN_TREE_STATE_DIR_NAME}${sep}`;
  const normalized = filePath.replace(/\//g, sep);
  if (normalized.includes(segment)) return true;
  if (!isAbsolute(normalized)) return false;
  const stateRoot = emberStateRoot(root ?? process.cwd());
  const prefix = stateRoot.endsWith(sep) ? stateRoot : stateRoot + sep;
  return normalized.toLowerCase().startsWith(prefix.toLowerCase());
}
