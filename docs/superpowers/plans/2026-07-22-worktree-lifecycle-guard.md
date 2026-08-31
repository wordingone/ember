# Worktree Lifecycle Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent renewed Ember worktree accumulation while preserving safe isolation and all unmerged evidence.

**Architecture:** A standard-library Python CLI owns repository-local lifecycle state in the Git common directory and serializes create/retire operations with an exclusive lock. Existing Git hooks call its audit command before the repository guard, so unmanaged additions or budget violations cannot commit or push.

**Tech Stack:** Python 3.10+, Git CLI, pytest, existing POSIX Git hooks.

## Global Constraints

- Never force-remove or recursively delete a worktree.
- Never retire dirty state.
- Archive every detached head before retirement.
- Keep machine paths and lifecycle state out of public commits.
- Target at most 12 registered worktrees; legacy counts ratchet downward without rebounding.

---

### Task 1: Lifecycle state, audit, and install

**Files:**
- Create: `src/ember/governance/scripts/worktree_lifecycle.py`
- Create: `tests/test_worktree_lifecycle.py`

**Interfaces:**
- Produces: CLI commands `install`, `audit`, `create`, and `retire`.
- Persists: `<git-common-dir>/ember-worktree-lifecycle.json` and an adjacent lock file.

- [ ] Write real-repository tests for initialization, malformed state, unmanaged raw additions, expired leases, and downward ratcheting.
- [ ] Run `python -m pytest -q tests/test_worktree_lifecycle.py` and confirm failures are caused by the missing CLI.
- [ ] Implement porcelain parsing, canonical path identity, atomic JSON state, locking, install, and audit.
- [ ] Re-run the focused tests and confirm the audit/install cases pass.

### Task 2: Safe create and retire

**Files:**
- Modify: `src/ember/governance/scripts/worktree_lifecycle.py`
- Modify: `tests/test_worktree_lifecycle.py`

**Interfaces:**
- `create --path PATH --branch BRANCH --owner OWNER --purpose PURPOSE --expires YYYY-MM-DD [--start-point REF]`
- `retire --path PATH`

- [ ] Add failing tests for ceiling refusal, managed creation, dirty retirement refusal, named-branch retention, detached archival, and state ratcheting.
- [ ] Run the focused suite and confirm the new behavioral tests fail for the intended missing behavior.
- [ ] Implement create/rollback and clean Git-aware retirement with detached archive refs.
- [ ] Re-run the focused suite and confirm all lifecycle tests pass.

### Task 3: Hook and policy integration

**Files:**
- Modify: `.githooks/pre-commit`
- Modify: `.githooks/pre-push`
- Modify: `AGENTS.md`
- Modify: `tests/test_worktree_lifecycle.py`

**Interfaces:**
- Hooks invoke `python "$ROOT/src/ember/governance/scripts/worktree_lifecycle.py" audit --quiet` before existing guards.
- `AGENTS.md` names the lifecycle CLI as the only permitted Ember worktree create/retire path.

- [ ] Add a failing source-level test requiring both hook invocations and the operative policy text.
- [ ] Run the focused suite and confirm the wiring test fails.
- [ ] Add the hook calls and concise policy rule.
- [ ] Run focused lifecycle and merge-gate suites.

### Task 4: Live installation and bypass probe

**Files:**
- Local only: `<git-common-dir>/ember-worktree-lifecycle.json`

- [ ] Run `install` against the live common repository and verify the current legacy ceiling.
- [ ] Create one disposable raw worktree and prove `audit` rejects it as unmanaged.
- [ ] Remove the disposable worktree using Git-aware removal and prove `audit --ratchet` passes.
- [ ] Run repository guard, diff checks, and clean-clone focused tests.
- [ ] Publish and land through guarded review, verify exact public master, retire this implementation worktree, then run final live audit so the ceiling ratchets down.
