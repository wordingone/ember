# #1371 slice 2 — per-leg fingerprint cache + worktree-registry re-scoping (design sketch, not implemented)

Written during slice 1 (build-1371, phase A). Slice 1 lands the dedicated-pinned-worktree
dispatch + blocking-wording audit (clean — no blocking wording found in ember-cli source
or specs). This note is the file-ready starting point for slice 2 so #1371 stays open with
a concrete plan rather than a bare "TODO", per the operator's slicing instruction.

## Requirement 3 — per-leg fingerprint cache

Each of the nine legs in `verify_ember01_completion.py` needs a fingerprint key made of:

- verifier code identity: sha256 of the leg's own source file(s) at the pinned commit
  (e.g. leg 8 -> `src/ember/governance/scripts/verify_authority_conservation.py`; legs 1/2/6/9 ->
  `scripts/ember_01_custody/census.py` + `issue_census.py`; legs 3/4 ->
  `scripts/ember_01_identity/*.py`). Cheapest to get: `git show <pinned_commit>:<path> |
  sha256sum` inside the pinned worktree, no working-tree read needed.
- exact repository inputs: content hash of every file the leg reads, all already
  resolvable at the pinned commit via `git ls-tree`/`git show` (deterministic — the
  pinned worktree's whole POINT is that this never moves mid-run).
- external inputs: the issue-census snapshot hash (`snapshot_sha256`, already computed by
  `capture_issue_snapshot`) for leg 9; nothing external for legs 1-8 unless a future leg
  reads a registry.
- runtime identity: operator-machine ROOT binding paths + their own content hashes for
  legs 1/2/6/9 (these are NOT reproducible from the pinned commit — they are live machine
  state, so the cache key must include a hash of what was actually read, not just "the
  bindings string"); model_config/checkpoint_manifest/identity_manifest paths + hashes for
  legs 3/4; bun/python interpreter version strings if they affect leg 5/7 output
  (disclosed as part of the key, not hidden).

Cache store: a JSONL or per-key JSON file under the EXTERNAL state root (same rule as
receipts — never inside the checkout, never inside the pinned worktree, so the cache
itself is never part of what gets censused). Suggested path:
`emberStatePath(repoRoot, "verify-leg-cache", "<leg>-<fingerprint_sha256>.json")` holding
the prior leg's full `leg()` row (title/state/reason/evidence) plus
`cached_from_run_at_utc` and `cached_from_pinned_commit`.

Composed receipt disclosure: add a `provenance` field per leg
(`{"source": "cached", "cached_from_pinned_commit": "...", "cached_from_run_at_utc":
"..."}` or `{"source": "executed"}`), inside `leg_detail[<n>]`, matching the pattern
`census_snapshot_binding` already uses for point-in-time binding fields (evidence lives
INSIDE the leg row, never as a new top-level receipt key, because
`certified_train_launch.py` validates the receipt's top-level key set by exact equality —
see `closure_evidence_at`'s comment on the same constraint).

`verify_ember01_completion.py` is SHA-PINNED by the cond4 tamper battery's receipt (see
`scripts/verify_ember01_completion.py::cond4_tamper_battery`'s own evidence + whatever
receipt pins this file's hash — grep the repo for a receipt keyed on this path before
touching it, and follow the #1360 commit's three-field re-mint precedent in the SAME
commit that edits this file, not a follow-up).

## Requirement 5 residual — worktree-registry re-scoping

`manifests/ember-01-custody/root-spec.json`'s `registered-worktree-registry` /
`registered-worktree-material-registry` roots (scan modes `git_worktree_registry` /
`git_worktree_material_registry` in `scripts/ember_01_custody/census.py`) enumerate and
byte-hash EVERY worktree registered against whatever machine path they are bound to via
`/custody set` — which, on the operator's machine, includes worktrees under ACTIVE
development, not just the pinned verification worktree. `census.py` already does
final-state re-verification (`final_git_records` / `final_membership_records`) and
already fails a SPECIFIC artifact/root closed (`artifact_mutated_during_hash`,
`directory_snapshot_changed_during_scan`) rather than aborting the whole census — but
those failures currently propagate to ALL of legs 1/2/6/9 (`custody_legs()` returns one
state for all four from a single census.py exit code), not scoped to "this one worktree's
churn, other legs/roots unaffected" the way #1371 requirement 4 asks.

Two candidate fixes, either viable for slice 2, worth a real design pass before picking:

1. **Exclude the pinned verify-worktree's own root from those two scans** (the census
   would otherwise also hash ITS OWN target, which is redundant with legs 1-9 reading it
   directly) and add a `runtime_state_exclusions`-style declared exclusion for OTHER
   verify-worktrees (`ember-verify-worktrees/*`) so a second concurrent `/verify` run
   never contaminates this one — narrow, low-risk, but does not fix contamination from
   ordinary DEV worktrees.
2. **Make `custody_legs()` per-root granular**: split legs 1/2/6/9's single `census.py`
   invocation's contradiction list by which `root_id` produced each contradiction, and
   only fail the legs that root's `LEG_TITLES` actually covers when the census tool
   itself is restructured to report per-root pass/fail rather than one aggregate exit
   code. This is the structurally correct fix for requirement 4 ("fails THAT leg (named);
   other legs unaffected") but is a real `census.py` architecture change (its `main()` CLI
   currently returns one process exit code for the whole run) — sized as its own slice,
   not a quick patch alongside the fingerprint cache.

Recommendation for whoever picks up slice 2: do (1) first (cheap, kills the concrete
self-contamination case between two verify dispatches), file (2) as its own follow-on
issue rather than folding it into the same PR as the fingerprint cache — the two are
independent and (2) is the bigger one.
