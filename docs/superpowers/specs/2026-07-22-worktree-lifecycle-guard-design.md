# Worktree Lifecycle Guard Design

## Outcome

Ember keeps isolated worktrees, but their count can no longer grow without custody. A local, repository-scoped lifecycle state records the one-time legacy set, managed worktrees, a ratcheting ceiling, and a target ceiling of 12. Removing worktrees lowers the ceiling; it never rises automatically.

## Safety boundary

- Retirement uses `git worktree remove` without `--force`; recursive filesystem deletion is forbidden.
- Dirty worktrees are never retired automatically.
- Every detached head receives an archive ref before retirement.
- The main worktree, non-worktree directories, datasets, SDKs, mirrors, and backups are outside the retirement command.
- State is local under the Git common directory; absolute machine paths never enter public commits.

## Components

`scripts/worktree_lifecycle.py` provides four commands:

- `install`: atomically snapshots the existing worktrees as the legacy set and sets `ceiling = max(current_count, 12)`.
- `audit`: fails when count exceeds the ceiling, a new worktree is neither legacy nor managed, a managed lease expires, or registered/live state diverges. With `--ratchet`, it lowers the ceiling after verified removals.
- `create`: under an exclusive lock, requires owner, purpose, expiry, path, and branch; refuses creation at the ceiling; invokes Git; then atomically records custody. Failure after Git creation rolls the worktree back.
- `retire`: under the same lock, revalidates exact repository membership and cleanliness, archives detached heads, invokes Git-aware removal, updates custody, and ratchets the ceiling.

The pre-commit and pre-push hooks run quiet audit before the existing repository guard. This catches raw `git worktree add` bypasses locally without modifying Codex configuration or global Git behavior.

## Failure behavior

All mutations are fail-closed. Lock contention, malformed state, path mismatch, dirty state, expired custody, ceiling violations, and Git errors return nonzero with no forced cleanup. State writes use replace-on-success semantics.

## Verification

Unit tests use temporary real Git repositories and prove install, raw-add rejection, ceiling enforcement, managed creation, dirty-retirement rejection, detached-head archival, ratcheting, and hook wiring. A live install/audit is then run against `<operator-ember-repo>`; a disposable raw worktree must be rejected by audit and removed before final verification.
