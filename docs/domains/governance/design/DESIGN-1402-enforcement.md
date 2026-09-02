# DESIGN-1402: fixed-prior manifest verify-at-consumption (clause 2 of #1402)

Frozen design. The re-mint (clause 1) landed in this branch; this document freezes
the enforcement so the class dies at the next build slot instead of being re-derived.

## Defect being cured

Nothing on the launch path reads `manifests/ember-restart-3b/fixed-prior-manifest-v1.json`.
A rung receipt can therefore reference (by hash) a manifest whose pins no longer
reproduce against the checkout being launched — the receipt lies by reference.
Same class as #1394's input admission; same cure: verify at consumption, fail closed.

## Exact change

### 1. New function — `src/ember/governance/scripts/build_fixed_prior_manifest.py`

```python
def assert_fresh(manifest_path: Path = REPO_ROOT / MANIFEST_REL) -> dict:
    """Fail-closed freshness gate for launch-path consumers.

    Returns {"manifest_path": str, "manifest_sha256": sha256_file(manifest_path)}
    on success, so the caller binds the VERIFIED bytes' hash into its receipt.
    Raises FixedPriorDriftError (subclass of RuntimeError) listing every finding
    when verify() reports drift, a missing declared prior, or a failed probe.
    """
    ok, findings = verify(manifest_path)
    if not ok:
        raise FixedPriorDriftError(
            "FIXED_PRIOR_MANIFEST_STALE: re-mint via "
            "'python src/ember/governance/scripts/build_fixed_prior_manifest.py --write' at this "
            "checkout before launching; findings:\n" + "\n".join(findings))
    return {"manifest_path": str(MANIFEST_REL).replace("\\", "/"),
            "manifest_sha256": sha256_file(manifest_path)}
```

VERSION-probe policy: `verify()` already treats a changed-but-present toolchain
version as a finding; `assert_fresh` inherits that (a moved toolchain at launch IS
staleness — the run would execute under versions the declaration does not describe).

### 2. Consumption point A — `tools/ember-restart-3b/launch_packet.py`

Add preflight `preflight_fixed_prior(cfg, root)` to the existing preflight chain
(alongside `preflight_no_sub_3b` / `preflight_resource` / `preflight_storage` /
`preflight_clean_genesis`): import `assert_fresh` from
`src/ember/governance/scripts/build_fixed_prior_manifest.py` (via the existing `_ensure_tools_on_path`
/ sys.path mechanics, `root / "scripts"`), call it, and embed the returned
`fixed_prior` block in the packet. Any `FixedPriorDriftError` -> preflight FAIL,
packet not producible, so `certified_train_launch.py` (the ONLY path ember-cli
/train --execute may invoke) cannot proceed. Exit code: the preflight's standing
nonzero failure path; failure token in output: `FIXED_PRIOR_MANIFEST_STALE`.

### 3. Consumption point B — `tools/ember-restart-3b/production_rung.py`

`build_receipt()` gains a `fixed_prior_manifest` field:

```python
"fixed_prior_manifest": assert_fresh()  # {"manifest_path": ..., "manifest_sha256": ...}
```

and `verify_bound_rung()` / `verify_checked_in_production_rung()` recompute
`sha256_file(manifest_path)` and re-run `verify()` at read time, failing with
`ValueError("rung receipt references a fixed-prior manifest that does not "
"reproduce at this checkout")` on mismatch. This closes BOTH ends: the receipt
cannot be minted against stale pins, and a hand-edited receipt cannot smuggle a
stale reference past replay verification.

### 4. Tests (new `tests/ember_restart/test_fixed_prior_freshness.py`)

1. `assert_fresh` passes on a freshly `--write`-minted manifest (fixture repo or
   the real tree with a scratch copy).
2. Mutate one pinned file's declared sha256 in a copied manifest ->
   `FixedPriorDriftError` raised, message contains `FIXED_PRIOR_MANIFEST_STALE`
   and the drifted path.
3. Receipt round-trip: a receipt whose `fixed_prior_manifest.manifest_sha256`
   does not match the on-disk manifest bytes fails `verify_bound_rung`.
4. Selftest extension in the builder: `assert_fresh` on a deliberately wrong
   fake manifest raises (mirrors the existing verify() drift selftest case).

## Failure code summary

| Surface | Signal |
|---|---|
| `assert_fresh` | raises `FixedPriorDriftError` (RuntimeError subclass), message prefix `FIXED_PRIOR_MANIFEST_STALE`, all findings listed |
| launch packet preflight | preflight FAIL row, nonzero exit, no packet emitted |
| rung receipt mint | `build_receipt` propagates the raise; no receipt bytes written |
| rung receipt replay | `ValueError` from `verify_bound_rung` on hash/pin mismatch |

## Why fail-closed here and not a warning

The manifest's purpose field is the contract: "referenced by hash from every rung
receipt." A hash reference to unreproducible pins is exactly the falsified-receipt
class INVARIANT.md forbids. A warning would preserve the silent-drift channel #1402
names; the #1394 precedent (input admission fails closed at consumption) is the
repo's established pattern for this class.
