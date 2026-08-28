<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Receipt conventions

## Path hygiene

Receipt writers emit forward-slash repository-relative paths for files under
the repository root. A drive-rooted path outside the repository is represented
as `local:<basename>`; its host directory is never persisted. Named
sensitive-root placeholders remain permitted only where a more specific
checked-in receipt contract requires them. `tools/repo-guard.sh` enforces this
contract through its `[paths]` and `[path-frags]` gates.

`scripts/redact_local_paths.py` is a first-landing safety tool, not a historical
rewriter. It accepts explicit JSON file names only, reports per-file replacement
counts, and refuses files already tracked at the selected base unless the
operator supplies a reasoned `--first-landing-override`. `--check` reports
violations without modifying bytes. Already-landed receipts remain append-only;
the utility must not be applied to historical evidence in place.
