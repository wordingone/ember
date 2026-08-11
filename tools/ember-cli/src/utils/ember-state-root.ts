// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// ember-state-root.ts — the ONE TypeScript resolution point for cockpit-mutable state
// (issue #1330), and the writer-side guard that keeps it out of every censused root.
//
// The completion verifier certifies the local execution tree by TOTALITY: it censuses and
// fingerprints every file, tracked and untracked, so any resident writer produces
// list-vs-hash contradictions and a red receipt. That totality is load-bearing (it caught
// the run15 stale-cockpit contamination) and must never be weakened with path exclusions.
// The cure is on the writer side: the cockpit's mutable state lives OUTSIDE every root the
// census reads, so the cockpit can stay up during verification instead of being quiesced.
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
//   2. `<EMBER_HOME>/cockpit-state/<repoStateKey(root)>` when EMBER_HOME is explicit.
//   3. the governed B: cockpit-state parent on Windows, keeping receipts and the
//      Bun cache off the C: operating-reserve volume (#1317). POSIX direct/dev launches
//      retain the user config-home fallback. The per-root key keeps checkouts disjoint.
//
// The default's key derivation is mirrored by Get-EmberStateRootKey in
// scripts/launch-ember-cli.ps1, AND by _repo_state_key in scripts/cockpit_watchdog.py (#413:
// the renderer-heartbeat reader needs the same default the writer resolves to, since nothing
// exports EMBER_STATE_ROOT into the watchdog's own launch environment). Three
// implementations, not two — TS, PowerShell, Python — all pinned to the same fixture vectors
// (ember-state-root.test.ts / tests/test_ember_root_launcher.py /
// scripts/tests/test_cockpit_watchdog.py's KEY_PARITY_VECTORS) so none can drift apart
// unnoticed. A fourth consumer needing this default belongs in this shared-vectors pattern
// too, never a hand-rolled join.
//
// GUARD (writer-side, fail-closed). A verifier-only refusal detects the regression at the
// NEXT census; by then the run is already red. So every resolution is validated here,
// before any write, and an unusable root throws rather than silently landing state
// somewhere censused. Two ways a root is unusable:
//   (a) it is inside the checkout — the original defect;
//   (b) it sits under EMBER_NAMED_ROOT_PARENT in a directory whose name matches the
//       census's `ember-named-root-discovery` patterns. This is the non-obvious one:
//       moving `.ember/` to a sibling named `ember-cockpit-state` would be discovered by
//       that scan and byte-hashed anyway, so the relocation would buy nothing. Use a
//       directory name outside those patterns — `cockpit-state` is the sanctioned one.

import { isAbsolute, join, posix, resolve, sep, win32 } from "node:path";
import { getEmberConfigHomeDir } from "./env-detection.ts";

/** The legacy in-tree directory name. Retained ONLY so residue detection and the
 *  skill-directory write triggers can still recognize a pre-relocation path; it is never
 *  used to build a write target. */
export const IN_TREE_STATE_DIR_NAME = ".ember";

/** Directory name for the external state root. Chosen to match none of
 *  CENSUS_DISCOVERY_NAME_PATTERNS — see the guard note above. */
export const SANCTIONED_STATE_DIR_NAME = "cockpit-state";

/** Mirrors `ember-named-root-discovery`.name_patterns in
 *  manifests/ember-01-custody/root-spec.json. The census fnmatches these (casefolded)
 *  against the immediate children of EMBER_NAMED_ROOT_PARENT and byte-hashes every match,
 *  so a state root landing in one is censused wherever else it sits. */
export const CENSUS_DISCOVERY_NAME_PATTERNS: readonly string[] = [
  "ember*",
  "wt-stab480-bench594-scratch",
];

/** Thrown when a resolved state root would be read by a census. Named so a caller that
 *  must degrade rather than crash can catch precisely this class. */
export class EmberStateRootError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EmberStateRootError";
  }
}

function matchesDiscoveryPattern(name: string): boolean {
  const folded = name.toLowerCase();
  return CENSUS_DISCOVERY_NAME_PATTERNS.some((pattern) => {
    const body = pattern
      .toLowerCase()
      .replace(/[.+^${}()|[\]\\]/g, "\\$&")
      .replace(/\*/g, ".*")
      .replace(/\?/g, ".");
    return new RegExp(`^${body}$`).test(folded);
  });
}

function isSameOrInside(candidate: string, container: string): boolean {
  const a = candidate.toLowerCase();
  const b = container.toLowerCase().replace(/[\\/]+$/, "");
  return a === b || a.startsWith(b + sep);
}

/** Fail-closed validation of a resolved state root. Exported so the launcher-equivalent
 *  check and the tests exercise the same predicate the writers do. */
export function assertStateRootIsWritable(stateRoot: string, checkoutRoot: string): void {
  const resolved = resolve(stateRoot);
  const checkout = resolve(checkoutRoot);

  if (isSameOrInside(resolved, checkout)) {
    throw new EmberStateRootError(
      `cockpit state root '${resolved}' is inside the checkout '${checkout}'. The ` +
        `completion verifier censuses that tree in full, so state written there reds the ` +
        `run. Point EMBER_STATE_ROOT at a directory outside it.`,
    );
  }

  const namedRootParent = process.env["EMBER_NAMED_ROOT_PARENT"];
  if (namedRootParent === undefined || namedRootParent.trim().length === 0) return;

  const parent = resolve(namedRootParent.trim());
  if (!isSameOrInside(resolved, parent)) return;
  if (resolved.toLowerCase() === parent.toLowerCase()) return;

  const child = resolved.slice(parent.length).split(sep).filter(Boolean)[0];
  if (child === undefined || !matchesDiscoveryPattern(child)) return;

  throw new EmberStateRootError(
    `cockpit state root '${resolved}' sits under the census named-root parent in ` +
      `'${child}', whose name matches a root-discovery pattern ` +
      `(${CENSUS_DISCOVERY_NAME_PATTERNS.join(", ")}). The census discovers and ` +
      `byte-hashes that directory, so relocating there buys nothing. Use a directory ` +
      `named '${SANCTIONED_STATE_DIR_NAME}', or another name outside those patterns.`,
  );
}

/** Filesystem-safe, case-stable key for a checkout root. Lowercased because Windows paths
 *  are case-insensitive: two spellings of one checkout must key to one state directory. */
export function repoStateKey(root: string): string {
  const key = resolve(root)
    .replace(/[\\/]+$/, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (key.length === 0) {
    throw new EmberStateRootError(`cannot derive a state key from root '${root}'`);
  }
  return key;
}

/** Parent for implicit cockpit state. Explicit EMBER_HOME remains authoritative; only
 * the Windows fallback changes from the C: user profile to the governed B: volume. */
export function defaultEmberStateParent(
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
  configHome?: string,
): string {
  const explicitHome = env["EMBER_HOME"]?.trim();
  const pathApi = platform === "win32" ? win32 : posix;
  if (explicitHome) return pathApi.resolve(explicitHome);
  if (platform === "win32") return win32.join("B:" + win32.sep, "M");
  return configHome ?? getEmberConfigHomeDir();
}

/** Absolute root of all cockpit-mutable state for `root`. Never inside a censused root —
 *  validated on every call, because this is the last point before a write. */
export function emberStateRoot(root: string): string {
  const override = process.env["EMBER_STATE_ROOT"];
  const resolved =
    override !== undefined && override.trim().length > 0
      ? resolve(override.trim())
      : join(defaultEmberStateParent(), SANCTIONED_STATE_DIR_NAME, repoStateKey(root));
  assertStateRootIsWritable(resolved, root);
  return resolved;
}

/** Path to a named piece of cockpit state under `root`'s external state root. */
export function emberStatePath(root: string, ...segments: string[]): string {
  return join(emberStateRoot(root), ...segments);
}

/** True when `filePath` is cockpit state: under the resolved external root, or carrying a
 *  legacy in-tree `.ember` path segment. Both arms are needed — the external root is where
 *  state lives now, and the legacy segment still identifies state on a machine that has not
 *  been migrated yet (and in the `~/.ember` user config home, which never moves).
 *  Never throws: a caller deciding whether to fire a skill-dir trigger must not crash
 *  because the state root happens to be misconfigured. */
export function isUnderEmberState(filePath: string, root?: string): boolean {
  const segment = `${sep}${IN_TREE_STATE_DIR_NAME}${sep}`;
  const normalized = filePath.replace(/\//g, sep);
  if (normalized.includes(segment)) return true;
  if (!isAbsolute(normalized)) return false;
  try {
    const stateRoot = emberStateRoot(root ?? process.cwd());
    const prefix = stateRoot.endsWith(sep) ? stateRoot : stateRoot + sep;
    return normalized.toLowerCase().startsWith(prefix.toLowerCase());
  } catch {
    return false;
  }
}
