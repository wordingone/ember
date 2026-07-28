<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->
# Branch inventory

`scripts/branch_inventory.py` is the standing, read-only inventory for local
Ember branch and registered-worktree tips that are not ancestors of public
`origin/master`.

Capture:

```powershell
python -B scripts/branch_inventory.py capture `
  --repo . `
  --master refs/remotes/origin/master `
  --output receipts/branch-inventory/branch-inventory-current.json `
  --continuity CONTINUITY.md
```

The receipt enumerates every qualifying `refs/heads/*` tip and every qualifying
detached registered worktree tip. Branch, worktree, and file identities are
represented by kind plus SHA-256 so tracked evidence cannot disclose operator or
legacy names; they remain deterministically matchable against a live local ref and
`master...tip` scan. File lists are deduplicated into content-addressed file sets. Every
listed file inherits a fail-closed `PARK` disposition unless a complete,
reviewed override explicitly assigns `LAND` or `RETIRE`; empty comparisons are
recorded as `RETIRE`. `LAND` is only a classification: it never merges or
publishes a branch.

Runtime artifacts that must remain untracked can be bound without committing
their bytes:

```powershell
python -B scripts/branch_inventory.py capture ... `
  --artifact "operator-label=<path-to-private-receipt>"
```

Only the label and SHA-256 enter the receipt. Capture performs no Git mutation,
force push, merge, branch deletion, or worktree retirement.

`scripts/gen_readme_status.py` verifies the receipt, its generated
`CONTINUITY.md` table, and the seven-day freshness bound before any continuity
refresh. A missing, tampered, or stale inventory therefore stops the refresh.

Standalone verification:

```powershell
python -B scripts/branch_inventory.py check `
  --manifest receipts/branch-inventory/branch-inventory-current.json `
  --continuity CONTINUITY.md `
  --max-age-days 7
```
