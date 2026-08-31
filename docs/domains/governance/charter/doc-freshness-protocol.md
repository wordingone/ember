# Documentation Freshness Protocol

**Purpose:** Enforce that public-facing documentation in the ember repository remains accurate, reachable, and up-to-date.

**Enforcement:** Every pull request and every push to master runs two deterministic named gates:
`scripts/check_docs_freshness.py --front-door` and
`scripts/gen_readme_status.py --check --generated-status`. The unscoped commands remain local
full-audit tools and retain their branch-inventory, claims-index, and wall-age checks.

## What the checker verifies

The `scripts/check_docs_freshness.py` script enforces four categories of correctness:

### 1. Front-door path references resolve
Every path candidate in `README.md` and `docs/authority/CONTINUITY.md`, whether backticked or
plain prose, must match the exact case of a path returned by `git ls-files`. An untracked local
file cannot mask a defect. Example:

```markdown
Run `src/ember/governance/scripts/receipt_check.py --all` to validate receipts.
```

The checker verifies that `src/ember/governance/scripts/receipt_check.py` is tracked with exact case. Its frozen prose
grammar covers `.py`, `.md`, `.json`, `.txt`, `.sh`, `.yml`, `.yaml`, `.toml`, and `.ps1`.

**Defect class:** `broken_path_reference`

### 2. scripts/ inventory is complete
The `scripts/README.md` file contains a taxonomy of the 400+ scripts under `scripts/`. Every Python file at `scripts/*.py` must appear in the inventory table.

**Defect class:** `incomplete_inventory`

**When to fix:** If you add a new `scripts/SOMETHING.py`:
- Add it to the appropriate prefix-family section in `scripts/README.md`
- If it's a new prefix family, add a new row to the census table with count and description

### 3. Claims index is regenerable
The `receipts/CLAIMS.md` and `receipts/INDEX.jsonl` files are generated from `receipts/**/*.json` by `src/ember/governance/scripts/build_claims_index.py`. These files must exist and be regenerable without error.

**When the index goes stale:** After adding new receipts, run:
```bash
python src/ember/governance/scripts/build_claims_index.py
```

**Defect class:** `missing_claims_index`

### 4. CONTINUITY state marker is recent
`docs/authority/CONTINUITY.md` contains the machine-readable marker
`<!-- state-as-of: YYYY-MM-DD -->`. The full audit requires it to be at most one day old. The
deterministic merge gate checks placement and uniqueness without consulting wall-clock time.

**When to update:** Before opening a PR, refresh the marker:
```markdown
<!-- state-as-of: 2026-07-06 -->
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

Both scoped checks run before merge and again on master:

```bash
python scripts/check_docs_freshness.py --front-door
python scripts/gen_readme_status.py --check --generated-status
# Exits 0 if clean, 1 if defects found
```

**No auto-fix:** The checker reports defects as text; there is no `--fix` mode that auto-edits docs. Repair is the author's responsibility.

## Debt ledger and deferral

If a PR encounters debt outside the deterministic front-door scope, the author may:

1. File an issue describing the defect
2. Reference that issue in the PR body as "docs debt: #NNN"
3. Keep the debt out of the scoped surfaces; there is no pre-existing-defect bypass in either gate

**Example PR body:**
```
## Description
Adds 3 new scripts for the C14 experiment suite.

## Docs debt
- #999: Update scripts/README.md inventory to include all C14 scripts (deferred, see issue)
```

**Note:** New defects introduced by a PR (e.g., adding a script but not documenting it) must be fixed in the same PR.

## Protocol for docs that can't be regenerated

The front-door grammar has exactly four exclusions: URL spans, the
`EMBER_CONSERVATION_V1` header, angle/path-to placeholders, and a line carrying the explicit
allow-unresolved pragma. There is no directory-wide research exemption.

Example:
```markdown
<!-- docs-freshness: allow-unresolved -->
## My Experiment

Ran on a local data corpus at `/mnt/local/...`
```

Every pragma use is enumerated in the scoped gate output and requires review.

## Escalation

If the checker detects a defect that requires architectural change (e.g., the documented script no longer exists and should be deleted, not restored), escalate via GitHub issue referencing the defect receipt.

## See also

- `scripts/check_docs_freshness.py` — the implementation
- `src/ember/governance/scripts/build_claims_index.py` — regenerates receipts index
- `scripts/README.md` — scripts taxonomy
- `README.md` — repository structure and reproduction guide
