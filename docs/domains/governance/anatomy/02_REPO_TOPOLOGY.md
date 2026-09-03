# 02 — Repository Topology

## Top-level layout

- `GOAL.md`, `INVARIANT.md`, `STATE.md`, `README.md` — governing/status docs at repo root.
- `docs/` — specs, protocols, research notes, and this anatomy set (`docs/domains/governance/anatomy/`).
- `scripts/` — the vast majority of Ember's Python surface: training entry
  points (`ember_*.py`), the totality board (`scripts/ember_totality/`),
  receipt tooling (`receipt_check.py`, `receipt_write.py`), the resource
  governor (`governor.py`), and the worktree lifecycle manager
  (`worktree_lifecycle.py`).
- `src/ember/infrastructure/tools/ember-cli/` — the TypeScript CLI/cockpit (Node/TS project with its
  own `src/core/`, `src/commands/`, `src/components/`).
- `receipts/` — the append-mostly evidence tree; every claim-bearing artifact
  lands here (see 10_RECEIPTS_PROVENANCE.md).
- `tests/` — pytest suites, organized by subsystem (`tests/ember_restart/`,
  `tests/ember_01_identity/`, etc.).
- `configs/` — frozen JSON training/run configs (`ember-restart-3b.json`,
  `v0-pretrain-config.json`, `v1-pretrain-config.json`, and others).

## Worktree discipline

Ember worktrees are created ONLY via `python src/ember/governance/scripts/worktree_lifecycle.py
create --path <name-or-path> --branch <branch> --owner <name> --purpose "<text>"
--expires <date> --start-point origin/master` (`src/ember/governance/scripts/worktree_lifecycle.py`). A
bare name is rooted on the governed B: volume under `M/ember-wt` (or
`EMBER_WORKTREE_ROOT`); an explicit C:-volume destination fails closed unless the operator supplies
`--allow-c-drive`. B: is the default work-product, worktree, and tool-cache
volume. C: is reserved for the operating system and the runner's 150 GiB
admission floor. `audit --strict` mechanically reports every registered
worktree still resolving onto C: (`c_drive_registration`): a managed row
reached C: without a recorded `--allow-c-drive` override is an error (it
predates the refusal, or bypassed it some other way); a legacy/unregistered
row is backlog, drained by the issue's inventory waves rather than failing
the default gate; an explicitly overridden managed row is the one shape the
operator already declared on purpose and is not re-reported.

The tool maintains a state file (`ember-worktree-lifecycle.json`) and lock
(`ember-worktree-lifecycle.lock`) tracking every managed worktree; `audit`
reports drift, `reconcile --path <path>` clears a registered row whose
worktree directory is gone. Ad-hoc `git worktree add` bypasses this registry
and can trip the repo-guard's `UNMANAGED_WORKTREE` check for OTHER
contributors' commits (observed directly during this doc set's own
authoring session — a stray unmanaged worktree at a temp path blocked an
unrelated commit until it was retired by its owner).

## Repo-guard hooks

Commits and pushes run a `repo-guard` check (invoked by pre-commit/pre-push
hooks) that enforces, among other things: LF-only line endings, UTF-8
encoding with no BOM, no absolute local paths or path fragments in tracked
content, no operator names in tracked file content (hashed denylist), exactly
one `GOAL.md`, `STATE.md` under a line cap, changed-receipt schema validation
(`receipt_check.py --file`), and authority conservation
(`verify_authority_conservation.py`). A failing repo-guard blocks the commit
or push outright — it is not advisory.

## Current gaps

No board condition tracks "repo topology" directly; this doc exists so a new
contributor (human or agent) can orient before reading the subsystem-specific
docs that follow.
