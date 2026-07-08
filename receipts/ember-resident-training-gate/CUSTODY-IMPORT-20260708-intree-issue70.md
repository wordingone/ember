# Custody Import: resident-training-gate-20260704T065507Z-intree-issue70.json

## Recovered from orphaned lineage

**Commit:** fa73765
**Path:** receipts/ember-resident-training-gate/resident-training-gate-20260704T065507Z-intree-issue70.json

**Extraction command:**
```bash
git show fa73765:receipts/ember-resident-training-gate/resident-training-gate-20260704T065507Z-intree-issue70.json
```

**Original file SHA256 (unredacted, from git object):** `2cbf3ab2e3d37b5b471c20d0610d9f5d9e3a462a7f5101cb35dde072dd1fec9d`

**Redacted file SHA256:** `21841a3eae9992470b7c44b7ed1bee84a2998bb51159b19286bb32c40c2727f7`

**Redaction applied:**
- `<REDACTED_GOALFORGE_PATH>` (27 occurrences of organization goalforge tree)
- `<REDACTED_PATH>` (8 occurrences of organization research state directory)
- Training stage identifier redacted in 2 occurrences
- **Total lines changed:** 37
- **Structural fields preserved:** ts, verdict, resident_training_gate_status, component_status, and all test_c0 join keys remain byte-identical to original per #461 precedent

**Issue:** #468 (https://github.com/wordingone/ember/issues/468)

**Repo-reachability:** Commit fa73765 is reachable from goalforge lineage (origin/goalforge/definitive-goal-20260701) but NOT from public remote (wordingone/ember). Unredacted original exists only in orphaned lineage, not publicly exposed.

## Custody statement

This import recovers the second gate receipt that authorized the second loop run of 2026-07-04 (23:51Z), redacted per precedent #461 to remove machine paths from pre-redaction-era metadata and training harness logs. The receipt is content-verified against test_c0's criteria: verdict RESIDENT_TRAINING_GATE_PASS, status PASS, all components PASS. This import carries **NO other claim from the orphaned goalforge lineage**, in particular none of the board-percentage claims or overstatement-era data associated with commit fa73765. The custody boundary is exactly this file: the authorization receipt for the 23:51Z loop run.
