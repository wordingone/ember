// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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

/** Issue #666: a git WORKTREE checkout carries the marker files too (GOAL.md +
 *  tools/ember-cli are regular checked-out files), so a marker walk started inside a
 *  worktree validates the WORKTREE root — and state paths derived from it (the liveness
 *  heartbeat) silently diverge from a watchdog anchored at the main checkout. This
 *  canonicalizes any marker-validated root through the worktree's `.git` FILE
 *  (`gitdir: <main>/.git/worktrees/<name>`) to the main checkout root, so every launch
 *  location converges on ONE root. A worktree whose main checkout cannot be resolved or
 *  fails the marker check THROWS — writing state to a root the watchdog will never poll
 *  is exactly the silent divergence this exists to kill. */
function canonicalizeThroughWorktree(root: string): string {
  const dotGit = path.join(root, ".git");
  let stat: fs.Stats;
  try {
    stat = fs.statSync(dotGit);
  } catch {
    return root; // git-less deployment (plain copy/archive) — marker root stands as-is.
  }
  if (stat.isDirectory()) return root; // main checkout.

  let gitdir: string;
  try {
    const m = fs.readFileSync(dotGit, "utf8").match(/^gitdir:\s*(.+?)\s*$/m);
    if (!m) return root; // not the worktree pointer shape — leave it alone.
    gitdir = m[1]!;
  } catch {
    return root;
  }
  // <main>/.git/worktrees/<name> -> <main>. A gitdir of any other shape (e.g. a
  // submodule's .git/modules path) is not the worktree divergence — leave it alone.
  const resolvedGitdir = path.resolve(root, gitdir);
  const wtMatch = resolvedGitdir.match(/^(.*)[\\/]\.git[\\/]worktrees[\\/][^\\/]+$/);
  if (!wtMatch) return root;
  const mainRoot = path.resolve(wtMatch[1]!);
  if (!isRepoRoot(mainRoot)) {
    throw new Error(
      `Resolved root ${root} is a git worktree of ${mainRoot}, but that main checkout ` +
        "does not validate as the ember repo root (missing GOAL.md + tools/ember-cli). " +
        "Refusing to bind state paths to a worktree root the watchdog will never poll " +
        "(issue #666). Set EMBER_REPO_ROOT to the main checkout.",
    );
  }
  return mainRoot;
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
    if (isRepoRoot(resolvedEnv)) return canonicalizeThroughWorktree(resolvedEnv);
    // Invalid EMBER_REPO_ROOT is rejected, not trusted blindly — fall through to
    // discovery rather than anchoring on a directory that isn't actually the repo.
  }

  const fromCwd = walkUpForMarker(options.startDir ?? process.cwd());
  if (fromCwd) return canonicalizeThroughWorktree(fromCwd);

  const fromExe = walkUpForMarker(path.dirname(options.execPath ?? process.execPath));
  if (fromExe) return canonicalizeThroughWorktree(fromExe);

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
