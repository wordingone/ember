# Documentation Freshness Protocol

**Purpose:** Enforce that public-facing documentation in the ember repository remains accurate, reachable, and up-to-date.

**Enforcement:** Every PR touching `scripts/`, `configs/`, or top-level command-line interfaces must pass the freshness check before merge. The check runs as a local merge-gate.

## What the checker verifies

The `scripts/check_docs_freshness.py` script enforces four categories of correctness:

### 1. Backtick path references resolve
Every path quoted in backticks in `README.md` and `docs/**/*.md` must exist in the repository tree. Example:

```markdown
Run `scripts/receipt_check.py --all` to validate receipts.
```

The checker verifies that `scripts/receipt_check.py` exists.

**Defect class:** `broken_path_reference`

### 2. scripts/ inventory is complete
The `scripts/README.md` file contains a taxonomy of the 400+ scripts under `scripts/`. Every Python file at `scripts/*.py` must appear in the inventory table.

**Defect class:** `incomplete_inventory`

**When to fix:** If you add a new `scripts/SOMETHING.py`:
- Add it to the appropriate prefix-family section in `scripts/README.md`
- If it's a new prefix family, add a new row to the census table with count and description

### 3. Claims index is regenerable
The `receipts/CLAIMS.md` and `receipts/INDEX.jsonl` files are generated from `receipts/**/*.json` by `scripts/build_claims_index.py`. These files must exist and be regenerable without error.

**When the index goes stale:** After adding new receipts, run:
```bash
python scripts/build_claims_index.py
```

**Defect class:** `missing_claims_index`

### 4. README state marker is recent
The README.md header contains a machine-readable marker: `<!-- state-as-of: YYYY-MM-DD -->`. This marker must be ≤ 1 day old (e.g., if today is 2026-07-06, the marker must be 2026-07-05 or later).

**When to update:** Before opening a PR, refresh the marker:
```markdown
<!-- state-as-of: 2026-07-06 | board-receipt: ... -->
```

**Defect class:** `stale_state_marker`

## Running the check locally

```bash
# Quick check (exit 0 if clean, 1 if defects)
python scripts/check_docs_freshness.py

# See defects as markdown report
python scripts/check_docs_freshness.py --fix-report

# Run selftests (verify checker logic)
python scripts/check_docs_freshness.py --selftest
```

## Merge-gate integration

The check runs before merge on every PR:

```bash
python scripts/check_docs_freshness.py
# Exits 0 if clean, 1 if defects found
```

**No auto-fix:** The checker reports defects as text; there is no `--fix` mode that auto-edits docs. Repair is the author's responsibility.

## Debt ledger and deferral

If a PR introduces a docs defect but the defect is not in the PR's scope, the author may:

1. File an issue describing the defect
2. Reference that issue in the PR body as "docs debt: #NNN"
3. The merge-gate passes if the defect is pre-existing (not introduced by the PR)

**Example PR body:**
```
## Description
Adds 3 new scripts for the C14 experiment suite.

## Docs debt
- #999: Update scripts/README.md inventory to include all C14 scripts (deferred, see issue)
```

**Note:** New defects introduced by a PR (e.g., adding a script but not documenting it) must be fixed in the same PR.

## Protocol for docs that can't be regenerated

Some documents (e.g., internal notes, research artifacts) may be genuinely out-of-tree and not indexed. These should:

1. Live in `docs/research/` or similar subdirectories (not `docs/`)
2. Be exempted from the reachability check by their directory name
3. Be marked with a comment if they reference files that may not exist in the public repo

Example:
```markdown
<!-- internal: references local benchmark data not committed to public repo -->
## My Experiment

Ran on a local data corpus at `/mnt/local/...`
```

The checker exempts `docs/research/` from reachability enforcement.

## Escalation

If the checker detects a defect that requires architectural change (e.g., the documented script no longer exists and should be deleted, not restored), escalate via GitHub issue referencing the defect receipt.

## See also

- `scripts/check_docs_freshness.py` — the implementation
- `scripts/build_claims_index.py` — regenerates receipts index
- `scripts/README.md` — scripts taxonomy
- `README.md` — repository structure and reproduction guide
