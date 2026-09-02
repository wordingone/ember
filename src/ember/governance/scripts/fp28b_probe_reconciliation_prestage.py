# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fp28b_probe_reconciliation_prestage.py — Row 3 pre-stage: seed23 coverage eval
alongside 1B checkpoint (#208).

DECISION (fp-28b reconciliation):
  - checkpoint_probe keeps its own frozen set (sha 105fd370...) for trajectory
    comparability with prior checkpoints. Do NOT change checkpoint_probe.
  - fp28_v0_coverage.py uses the canonical seed23 set (sha 91170123...) which
    was committed at #207. This eval RIDES the 1B checkpoint as a SEPARATE
    eval pass (not as a replacement for checkpoint_probe).

WHY TWO SETS DIVERGED:
  Both use fp23.GENERATOR_SEED=23. checkpoint_probe._build_probe_set() cycles
  L1_OPS in a different draw loop than fp28_v0_coverage.materialize_probe_set().
  The resulting probe tasks differ, hence different sha256.

DEPLOYMENT PLAN (fires when 1B checkpoint arrives, ~step 244k):
  Step A: run checkpoint_probe.py (produces 105fd370 set receipt) — unchanged.
  Step B: run a separate probe eval over the seed23 set (91170123) and feed
          that eval receipt to fp28_v0_coverage.py --emit — discharges fp-26(b).
  The two receipts are independent; both commit in the same 1B PR.

--selftest : verify probe set on disk matches live materializer (no drift) +
             compute both shas and confirm they differ as expected.
--emit     : write the pre-stage decision receipt to receipts/.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "nck"))

# issue2015 exact-local-import:src/ember/governance/scripts/fp28_v0_coverage.py
import importlib.util as _ember_0fe497804b6560b7_importlib
import sys as _ember_0fe497804b6560b7_sys
from pathlib import Path as _ember_0fe497804b6560b7_Path
_ember_0fe497804b6560b7_path = _ember_0fe497804b6560b7_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'fp28_v0_coverage.py')
if not _ember_0fe497804b6560b7_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/fp28_v0_coverage.py')
_ember_0fe497804b6560b7_aliases = ('_ember_issue2015_0fe497804b6560b7', 'fp28_v0_coverage', 'scripts.fp28_v0_coverage')
_ember_0fe497804b6560b7_existing = []
for _ember_0fe497804b6560b7_alias in _ember_0fe497804b6560b7_aliases:
    _ember_0fe497804b6560b7_candidate = _ember_0fe497804b6560b7_sys.modules.get(_ember_0fe497804b6560b7_alias)
    if _ember_0fe497804b6560b7_candidate is not None and all(_ember_0fe497804b6560b7_candidate is not item for item in _ember_0fe497804b6560b7_existing):
        _ember_0fe497804b6560b7_existing.append(_ember_0fe497804b6560b7_candidate)
if len(_ember_0fe497804b6560b7_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/fp28_v0_coverage.py')
if _ember_0fe497804b6560b7_existing:
    _ember_0fe497804b6560b7_module = _ember_0fe497804b6560b7_existing[0]
    _ember_0fe497804b6560b7_observed = getattr(_ember_0fe497804b6560b7_module, '__file__', None)
    if _ember_0fe497804b6560b7_observed is None or _ember_0fe497804b6560b7_Path(_ember_0fe497804b6560b7_observed).resolve() != _ember_0fe497804b6560b7_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/fp28_v0_coverage.py')
else:
    _ember_0fe497804b6560b7_spec = _ember_0fe497804b6560b7_importlib.spec_from_file_location('_ember_issue2015_0fe497804b6560b7', _ember_0fe497804b6560b7_path)
    if _ember_0fe497804b6560b7_spec is None or _ember_0fe497804b6560b7_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/fp28_v0_coverage.py')
    _ember_0fe497804b6560b7_module = _ember_0fe497804b6560b7_importlib.module_from_spec(_ember_0fe497804b6560b7_spec)
    for _ember_0fe497804b6560b7_alias in _ember_0fe497804b6560b7_aliases:
        _ember_0fe497804b6560b7_prior = _ember_0fe497804b6560b7_sys.modules.get(_ember_0fe497804b6560b7_alias)
        if _ember_0fe497804b6560b7_prior is not None and _ember_0fe497804b6560b7_prior is not _ember_0fe497804b6560b7_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp28_v0_coverage.py')
        _ember_0fe497804b6560b7_sys.modules[_ember_0fe497804b6560b7_alias] = _ember_0fe497804b6560b7_module
    try:
        _ember_0fe497804b6560b7_spec.loader.exec_module(_ember_0fe497804b6560b7_module)
    except BaseException:
        for _ember_0fe497804b6560b7_alias in _ember_0fe497804b6560b7_aliases:
            if _ember_0fe497804b6560b7_sys.modules.get(_ember_0fe497804b6560b7_alias) is _ember_0fe497804b6560b7_module:
                _ember_0fe497804b6560b7_sys.modules.pop(_ember_0fe497804b6560b7_alias, None)
        raise
for _ember_0fe497804b6560b7_alias in _ember_0fe497804b6560b7_aliases:
    _ember_0fe497804b6560b7_prior = _ember_0fe497804b6560b7_sys.modules.get(_ember_0fe497804b6560b7_alias)
    if _ember_0fe497804b6560b7_prior is not None and _ember_0fe497804b6560b7_prior is not _ember_0fe497804b6560b7_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp28_v0_coverage.py')
    _ember_0fe497804b6560b7_sys.modules[_ember_0fe497804b6560b7_alias] = _ember_0fe497804b6560b7_module
fp28 = _ember_0fe497804b6560b7_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/fp28_v0_coverage.py
import checkpoint_probe as cp
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_check.py
import importlib.util as _ember_2ad73f5df12b45ee_importlib
import sys as _ember_2ad73f5df12b45ee_sys
from pathlib import Path as _ember_2ad73f5df12b45ee_Path
_ember_2ad73f5df12b45ee_path = _ember_2ad73f5df12b45ee_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_check.py')
if not _ember_2ad73f5df12b45ee_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_check.py')
_ember_2ad73f5df12b45ee_aliases = ('_ember_issue2015_2ad73f5df12b45ee', 'receipt_check', 'scripts.receipt_check')
_ember_2ad73f5df12b45ee_existing = []
for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
    _ember_2ad73f5df12b45ee_candidate = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
    if _ember_2ad73f5df12b45ee_candidate is not None and all(_ember_2ad73f5df12b45ee_candidate is not item for item in _ember_2ad73f5df12b45ee_existing):
        _ember_2ad73f5df12b45ee_existing.append(_ember_2ad73f5df12b45ee_candidate)
if len(_ember_2ad73f5df12b45ee_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_check.py')
if _ember_2ad73f5df12b45ee_existing:
    _ember_2ad73f5df12b45ee_module = _ember_2ad73f5df12b45ee_existing[0]
    _ember_2ad73f5df12b45ee_observed = getattr(_ember_2ad73f5df12b45ee_module, '__file__', None)
    if _ember_2ad73f5df12b45ee_observed is None or _ember_2ad73f5df12b45ee_Path(_ember_2ad73f5df12b45ee_observed).resolve() != _ember_2ad73f5df12b45ee_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_check.py')
else:
    _ember_2ad73f5df12b45ee_spec = _ember_2ad73f5df12b45ee_importlib.spec_from_file_location('_ember_issue2015_2ad73f5df12b45ee', _ember_2ad73f5df12b45ee_path)
    if _ember_2ad73f5df12b45ee_spec is None or _ember_2ad73f5df12b45ee_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_check.py')
    _ember_2ad73f5df12b45ee_module = _ember_2ad73f5df12b45ee_importlib.module_from_spec(_ember_2ad73f5df12b45ee_spec)
    for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
        _ember_2ad73f5df12b45ee_prior = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
        if _ember_2ad73f5df12b45ee_prior is not None and _ember_2ad73f5df12b45ee_prior is not _ember_2ad73f5df12b45ee_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_check.py')
        _ember_2ad73f5df12b45ee_sys.modules[_ember_2ad73f5df12b45ee_alias] = _ember_2ad73f5df12b45ee_module
    try:
        _ember_2ad73f5df12b45ee_spec.loader.exec_module(_ember_2ad73f5df12b45ee_module)
    except BaseException:
        for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
            if _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias) is _ember_2ad73f5df12b45ee_module:
                _ember_2ad73f5df12b45ee_sys.modules.pop(_ember_2ad73f5df12b45ee_alias, None)
        raise
for _ember_2ad73f5df12b45ee_alias in _ember_2ad73f5df12b45ee_aliases:
    _ember_2ad73f5df12b45ee_prior = _ember_2ad73f5df12b45ee_sys.modules.get(_ember_2ad73f5df12b45ee_alias)
    if _ember_2ad73f5df12b45ee_prior is not None and _ember_2ad73f5df12b45ee_prior is not _ember_2ad73f5df12b45ee_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_check.py')
    _ember_2ad73f5df12b45ee_sys.modules[_ember_2ad73f5df12b45ee_alias] = _ember_2ad73f5df12b45ee_module
validate_receipt = getattr(_ember_2ad73f5df12b45ee_module, 'validate_receipt')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_check.py

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"


def _probe_set_sha_from_disk():
    path = os.path.join(NC, fp28.PROBE_SET_PATH)
    if not os.path.exists(path):
        return None, "MISSING"
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data).hexdigest(), data


def run_reconciliation_check():
    """Verify shas, drift check, produce findings. Returns (info_dict, errors)."""
    errors = []
    info = {}

    # Seed23 set (fp28)
    on_disk_sha, on_disk_bytes = _probe_set_sha_from_disk()
    if on_disk_sha is None:
        errors.append(f"l1-probe-set-seed23.json not on disk: {on_disk_bytes}")
        return info, errors

    live = fp28.materialize_probe_set()
    live_bytes = fp28._canon_bytes(live)
    live_sha = fp28.probe_set_sha(live)

    info["seed23_on_disk_sha256"] = on_disk_sha
    info["seed23_live_sha256"] = live_sha
    info["seed23_drift"] = on_disk_sha != live_sha

    if info["seed23_drift"]:
        errors.append(
            f"DRIFT: on-disk seed23 sha ({on_disk_sha[:16]}...) != "
            f"live materializer ({live_sha[:16]}...)"
        )
    else:
        info["seed23_sha_prefix"] = on_disk_sha[:16]

    # checkpoint_probe set
    cp_tasks = cp._build_probe_set()
    cp_sha = cp._probe_set_sha256(cp_tasks)
    info["checkpoint_probe_sha256"] = cp_sha
    info["checkpoint_probe_sha_prefix"] = cp_sha[:16]

    # Confirm they differ (expected)
    info["sets_differ"] = (on_disk_sha != cp_sha)
    if not info["sets_differ"]:
        errors.append(
            "UNEXPECTED: seed23 and checkpoint_probe sets are identical "
            "(reconciliation decision assumed they differ)"
        )

    info["n_seed23_tasks"] = len(live["instances"])
    info["n_checkpoint_probe_tasks"] = len(cp_tasks)

    return info, errors


def _selftest():
    info, errors = run_reconciliation_check()
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        raise SystemExit("FP28B_RECONCILIATION_PRESTAGE: checks failed")
    print("FP28B_RECONCILIATION_PRESTAGE_SELFTEST_PASS")
    for k, v in sorted(info.items()):
        print(f"  {k}: {v}")


def _emit():
    info, errors = run_reconciliation_check()
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        raise SystemExit("FP28B_RECONCILIATION_PRESTAGE: checks failed — not writing receipt")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP28B-PROBE-RECONCILIATION-PRESTAGE",
        "ts": ts,
        "issue": 208,
        "decision": (
            "checkpoint_probe keeps frozen set 105fd370... for trajectory "
            "comparability. fp28_v0_coverage.py seed23 set (91170123...) "
            "runs as a SEPARATE eval pass at 1B checkpoint."
        ),
        "deployment_plan": [
            "Step A: checkpoint_probe.py at 1B — produces 105fd370 receipt (unchanged).",
            "Step B: separate probe eval over seed23 set → feed receipt to "
            "fp28_v0_coverage.py --emit → discharges fp-26(b) coverage obligation.",
            "Both receipts commit in the same 1B PR. Independent — no dependency.",
        ],
        "seed23_probe_set": {
            "path": fp28.PROBE_SET_PATH,
            "sha256": info["seed23_on_disk_sha256"],
            "sha_prefix": info.get("seed23_sha_prefix", info["seed23_on_disk_sha256"][:16]),
            "drift": info["seed23_drift"],
            "n_tasks": info["n_seed23_tasks"],
        },
        "checkpoint_probe_set": {
            "sha_prefix": info["checkpoint_probe_sha_prefix"],
            "sha256": info["checkpoint_probe_sha256"],
            "n_tasks": info["n_checkpoint_probe_tasks"],
            "policy": "UNCHANGED — trajectory comparability requires consistency",
        },
        "sets_differ": info["sets_differ"],
        "root_cause_of_divergence": (
            "Both use fp23.GENERATOR_SEED=23 but checkpoint_probe._build_probe_set() "
            "cycles L1_OPS in a different draw loop than fp28_v0_coverage."
            "materialize_probe_set(), producing different tasks."
        ),
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }

    findings = validate_receipt(receipt)
    if findings:
        raise SystemExit(f"receipt_check FAIL on pre-stage receipt: {findings}")

    out = os.path.join(NC, "receipts", f"fp28b-probe-reconciliation-prestage-{ts}.json")
    checked_write(out, receipt)
    print("FP28B_RECONCILIATION_PRESTAGE_SELFTEST_PASS")
    for k, v in sorted(info.items()):
        print(f"  {k}: {v}")
    print(f"\nRECEIPT: {out}")


def main():
    ap = argparse.ArgumentParser(
        description="fp28b probe reconciliation pre-stage (#208)"
    )
    ap.add_argument("--selftest", action="store_true",
                    help="verify probe set shas and drift")
    ap.add_argument("--emit", action="store_true",
                    help="selftest + write pre-stage receipt to receipts/")
    args = ap.parse_args()

    if not (args.selftest or args.emit):
        print(
            "FP28B_RECONCILIATION_PRESTAGE_STAGED\n"
            "  --selftest: verify probe set sha + drift check\n"
            "  --emit: selftest + write decision receipt"
        )
        return

    if args.selftest and not args.emit:
        _selftest()
    else:
        _emit()


if __name__ == "__main__":
    main()
