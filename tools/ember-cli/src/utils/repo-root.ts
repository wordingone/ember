// repo-root.ts — resolves the ember repository root from a deterministic anchor that
// survives `bun build --compile` (issue #172: under a compiled binary, import.meta.url
// resolves to a virtual bunfs path, so a relative parent-walk from it lands at the drive
// root instead of the repo — never use import.meta.url for this purpose).
//
// Resolution order:
//   1. EMBER_REPO_ROOT env var, if set and it validates against the marker.
//   2. Upward walk from a start directory (defaults to process.cwd()) looking for the
//      marker.
//   3. Upward walk from the running binary's own location
//      (path.dirname(process.execPath)) — this is what makes the launch cwd irrelevant:
//      the exe file itself doesn't move just because you `cd` elsewhere before running it.
//
// Marker = a directory containing BOTH GOAL.md and tools/ember-cli. Chosen over a bare
// `.git` check: it survives a git-less deployment of the repo (e.g. a plain copy/archive),
// and it can't false-positive match some unrelated ancestor .git repo the exe happens to
// be nested under.
//
// Fails CLOSED (throws) if no candidate validates, naming EMBER_REPO_ROOT — this module
// never silently returns a wrong root (e.g. the drive root). Callers that must never crash
// (operator-receipts' fail-open contract, the interactive TUI boot) catch this explicitly
// and degrade per their own policy; this is the one shared resolver, not two.

import fs from "node:fs";
import path from "node:path";

function isRepoRoot(candidate: string): boolean {
  return (
    fs.existsSync(path.join(candidate, "GOAL.md")) &&
    fs.existsSync(path.join(candidate, "tools", "ember-cli"))
  );
}

function walkUpForMarker(startDir: string): string | null {
  let dir = path.resolve(startDir);
  for (;;) {
    if (isRepoRoot(dir)) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

export interface ResolveEmberRepoRootOptions {
  /** Overrides the cwd-walk start directory — tests point this at a scratch tree. */
  startDir?: string;
  /** Overrides process.execPath — tests point this at a scratch tree. */
  execPath?: string;
  /** Overrides the EMBER_REPO_ROOT env var lookup — tests inject a value directly instead
   *  of mutating process.env. */
  envRepoRoot?: string;
}

/**
 * Resolves the ember repo root via the priority order documented above. Throws a
 * descriptive error (naming EMBER_REPO_ROOT) if no candidate validates.
 */
export function resolveEmberRepoRoot(options: ResolveEmberRepoRootOptions = {}): string {
  const envValue = options.envRepoRoot ?? process.env["EMBER_REPO_ROOT"];
  if (envValue) {
    const resolvedEnv = path.resolve(envValue);
    if (isRepoRoot(resolvedEnv)) return resolvedEnv;
    // Invalid EMBER_REPO_ROOT is rejected, not trusted blindly — fall through to
    // discovery rather than anchoring on a directory that isn't actually the repo.
  }

  const fromCwd = walkUpForMarker(options.startDir ?? process.cwd());
  if (fromCwd) return fromCwd;

  const fromExe = walkUpForMarker(path.dirname(options.execPath ?? process.execPath));
  if (fromExe) return fromExe;

  throw new Error(
    "Could not resolve the ember repo root (no directory containing GOAL.md + " +
      "tools/ember-cli found via cwd or the running binary's location). " +
      "Set EMBER_REPO_ROOT to the repo path.",
  );
}

/**
 * Same resolution as resolveEmberRepoRoot(), but never throws — callers that must not
 * crash (operator-receipts' fail-open contract, the interactive TUI boot) use this
 * instead of hand-rolling their own try/catch around the strict resolver. Falls back to
 * process.cwd() (today's behavior) on any resolution failure, after a loud console.warn
 * naming the failure — this is "fail open, never silent", not "fail open, silently wrong".
 */
export function resolveEmberRepoRootOrCwd(
  options: ResolveEmberRepoRootOptions = {},
  warnPrefix = "[repo-root]",
): string {
  try {
    return resolveEmberRepoRoot(options);
  } catch (err) {
    console.warn(
      `${warnPrefix} repo root resolution failed, falling back to cwd: ${err instanceof Error ? err.message : String(err)}`,
    );
    return options.startDir ?? process.cwd();
  }
}
