# Writer Stamping Integration — Genesis Mechanization

This document describes how writers (checkpoint manifests, receipt emitters) integrate the invariant stamping mechanism post-genesis.

## Integration Points

### 1. Checkpoint Manifest Writers

Any script that writes checkpoint manifests must call `stamp()` before writing:

```python
from scripts.lib.invariant import stamp

# Before writing manifest
manifest = {
    "model_id": "cbase-grow-rung",
    "step": 730,
    "weights_sha256": "...",
    # ... other manifest fields
}

# Stamp the manifest (fails closed on hash mismatch)
stamped_manifest = stamp(manifest, repo_root=".")

# Write the stamped manifest
with open(f"receipts/manifest-{ts}.json", "w") as f:
    json.dump(stamped_manifest, f)
```

Writers affected:
- `scripts/timeshare_pretrain.py` (checkpoint step records)
- `scripts/cbase_grow_rung.py` (growth checkpoint manifests)
- `scripts/checkpoint_freeze.py` (any checkpoint freeze records)

### 2. Receipt Writers

Receipt emitters (board runners, experiment harnesses) must stamp receipts before writing:

```python
from scripts.lib.invariant import stamp

# Build receipt
receipt = {
    "ticket": "exp-123",
    "ts": datetime.utcnow().isoformat() + "Z",
    "experiment": "growth-efficiency",
    "metrics": {...},
    # ... other receipt fields
}

# Stamp (adds invariant_sha256 field)
stamped_receipt = stamp(receipt, repo_root=".")

# Write
with open(f"receipts/{timestamp}.json", "w") as f:
    json.dump(stamped_receipt, f)
```

Writers affected:
- `scripts/ember_totality/ember_totality_spec.py` (board run receipts)
- `scripts/run_*.py` (any experiment runner that writes receipts)

### 3. Receipt Validation (receipt_check.py)

The `receipt_check.py` validator must extend to enforce invariant stamping:

Post-genesis (after the first genesis receipt is in `receipts/genesis/`):
- Read the genesis timestamp from the genesis receipt
- For any receipt post-dating the genesis timestamp:
  - REQUIRED: `invariant_sha256` field must be present
  - REQUIRED: value must match `INVARIANT_SHA256` constant from `scripts/lib/invariant.py`
  - FAILURE: exit non-zero with `invalid_unstamped_receipt` token

Pre-genesis (before genesis timestamp):
- No invariant checking (those are history)

### 4. Board Receipt Chain Link (ember_totality_spec.py)

The board runner must add two new fields to its totality receipt:

```python
receipt = {
    # ... existing fields
    "prev_totality_receipt_sha256": "<hash of prior board receipt>",
    "constitutional_invariant": {
        "invariant_sha256": "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6",
        "status": "stamped",
        "genesis_ts": "2026-07-06T00:00:00Z",
        "errata_sha256": None,  # None until INVARIANT-ERRATA.md is written
        "errata_length": 0
    }
}

# Then stamp the whole receipt
from scripts.lib.invariant import stamp
stamped_receipt = stamp(receipt, repo_root=".")
```

The chain link (`prev_totality_receipt_sha256`) enables the F4 FORK-TEST requirement (unbroken board receipt chain from genesis).

## Enforcement Timeline

1. **Genesis commit** (this PR):
   - INVARIANT.md + stamp()/verify() mechanism
   - C-INV probe ready to check
   - receipts/incidents/ disclosure ledger seeded
   - Integration points documented (this file)

2. **Post-merge** (step 3, board run):
   - receipt_check.py extended with post-genesis invariant checking
   - Writers updated to call stamp() before writing
   - Board receipt gain chain-link fields
   - First genesis totality receipt written with all three fields

3. **Subsequent board runs** (step 4+):
   - All receipts stamped + chained
   - C-INV probe enforces stamping on every run
   - Incidents ledger audited for unresolved violations

## Test Plan (for post-genesis PRs)

1. Unit test: stamp() on a dict with invariant_sha256 field
2. Unit test: stamp() fails on mismatched hash
3. Integration test: receipt_check.py enforces invariant on post-genesis receipts
4. Integration test: Board runner produces chained receipt with constitutional_invariant block
5. C-INV probe: GREEN on full board run with all stamped receipts
