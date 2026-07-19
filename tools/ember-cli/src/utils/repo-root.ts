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

/** PR954 round 2: the typed error the strict canonical-root resolver throws for every
 *  malformed/unreadable/unsupported `.git` FILE shape, and for a worktree whose main
 *  checkout does not validate. Named + typed (never a bare Error) so a caller that must
 *  degrade instead of crash (the heartbeat writer's inert-writer contract) can catch
 *  precisely this failure class rather than swallowing unrelated bugs. */
export class CanonicalRootError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CanonicalRootError";
  }
}

/** Issue #666 / PR954 round 2 — a git WORKTREE checkout carries the marker files too
 *  (GOAL.md + tools/ember-cli are regular checked-out files), so a marker walk started
 *  inside a worktree validates the WORKTREE root — and state paths derived from it (the
 *  liveness heartbeat) silently diverge from a watchdog anchored at the main checkout.
 *  This canonicalizes any marker-validated root through the worktree's `.git` FILE
 *  (`gitdir: <main>/.git/worktrees/<name>`) to the main checkout root, so every launch
 *  location converges on ONE root.
 *
 *  Strict contract (round 2 repair of the reviewer's reject): a marker-valid standalone
 *  root with NO `.git` at all is accepted as-is (git-less deployment / plain copy — the
 *  ONLY case that returns a root unequal to a validated main checkout without a `.git`
 *  FILE). Every OTHER shape that fails to fully resolve to a marker-valid main checkout —
 *  an unreadable `.git` FILE, one whose content doesn't match `gitdir:` at all, one whose
 *  gitdir doesn't match the `<main>/.git/worktrees/<name>` shape (e.g. a submodule), or a
 *  worktree pointer whose resolved main checkout fails the marker check — THROWS a typed
 *  CanonicalRootError. The old behavior silently returned `root` (the worktree root) for
 *  unreadable/malformed/unsupported shapes, which is exactly the silent divergence issue
 *  #666 exists to kill: a caller must never bind state paths to an unverified root. */
function canonicalizeThroughWorktree(root: string): string {
  const dotGit = path.join(root, ".git");
  let stat: fs.Stats;
  try {
    stat = fs.statSync(dotGit);
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === "ENOENT") return root; // no .git at all — standalone/git-less deployment.
    throw new CanonicalRootError(
      `Could not stat ${dotGit} while canonicalizing repo root ${root}: ` +
        `${err instanceof Error ? err.message : String(err)} (issue #666 strict resolver).`,
    );
  }
  if (stat.isDirectory()) return root; // main checkout.

  let raw: string;
  try {
    raw = fs.readFileSync(dotGit, "utf8");
  } catch (err) {
    throw new CanonicalRootError(
      `.git file at ${dotGit} exists but could not be read: ` +
        `${err instanceof Error ? err.message : String(err)}. Refusing to bind state paths ` +
        "to an unverified root (issue #666 strict resolver).",
    );
  }
  const m = raw.match(/^gitdir:\s*(.+?)\s*$/m);
  if (!m) {
    throw new CanonicalRootError(
      `.git file at ${dotGit} does not contain a gitdir: pointer (malformed or unsupported ` +
        ".git file shape). Refusing to bind state paths to an unverified root (issue #666 " +
        "strict resolver).",
    );
  }
  const gitdir = m[1]!;
  // <main>/.git/worktrees/<name> -> <main>. A gitdir of any other shape (e.g. a
  // submodule's .git/modules path) is unsupported by this resolver.
  const resolvedGitdir = path.resolve(root, gitdir);
  const wtMatch = resolvedGitdir.match(/^(.*)[\\/]\.git[\\/]worktrees[\\/][^\\/]+$/);
  if (!wtMatch) {
    throw new CanonicalRootError(
      `.git file at ${dotGit} points to ${resolvedGitdir}, which is not a ` +
        "<main>/.git/worktrees/<name> path (unsupported gitdir shape, e.g. a submodule). " +
        "Refusing to bind state paths to an unverified root (issue #666 strict resolver).",
    );
  }
  const mainRoot = path.resolve(wtMatch[1]!);
  if (!isRepoRoot(mainRoot)) {
    throw new CanonicalRootError(
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
