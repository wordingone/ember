# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fp_verdict_chain_rehearsal.py — end-to-end dress rehearsal for the 2B verdict chain.

Drives synthetic probe receipts through the full fp24 -> fp29 -> fp36
pipeline to prove wiring is correct BEFORE the real 1B checkpoint
(~step 244k, ~1 day) materializes. Covers all verdict/gate branches.

Chains exercised:
  A. 2B PASS          fp24 PASS -> fp29 PASS-THROUGH
  B. 2B RETRY + 4B KILL, synthesis absent  -> fp29 KILL-REFUSED-UNRECEIPTED
  C. 4B KILL, synthesis malformed          -> fp29 KILL-REFUSED-MALFORMED
  D. 4B KILL, synthesis valid              -> fp29 KILL-VALID
  E. 2B RETRY + 4B late-onset PASS        -> fp29 PASS-THROUGH
  F. fp36_consistency pre-data guard       -> FP36_CONSISTENCY_PASS

`--selftest`: exercises all branches, asserts outcomes, prints
  FP_VERDICT_CHAIN_REHEARSAL_SELFTEST_PASS.
`--emit`: runs selftest + writes dress rehearsal receipt to receipts/.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# issue2015 exact-local-import:src/ember/governance/scripts/fp24_verdict.py
import importlib.util as _ember_fb70764d2afdfc4d_importlib
import sys as _ember_fb70764d2afdfc4d_sys
from pathlib import Path as _ember_fb70764d2afdfc4d_Path
_ember_fb70764d2afdfc4d_path = _ember_fb70764d2afdfc4d_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'fp24_verdict.py')
if not _ember_fb70764d2afdfc4d_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/fp24_verdict.py')
_ember_fb70764d2afdfc4d_aliases = ('_ember_issue2015_fb70764d2afdfc4d', 'fp24_verdict', 'scripts.fp24_verdict')
_ember_fb70764d2afdfc4d_existing = []
for _ember_fb70764d2afdfc4d_alias in _ember_fb70764d2afdfc4d_aliases:
    _ember_fb70764d2afdfc4d_candidate = _ember_fb70764d2afdfc4d_sys.modules.get(_ember_fb70764d2afdfc4d_alias)
    if _ember_fb70764d2afdfc4d_candidate is not None and all(_ember_fb70764d2afdfc4d_candidate is not item for item in _ember_fb70764d2afdfc4d_existing):
        _ember_fb70764d2afdfc4d_existing.append(_ember_fb70764d2afdfc4d_candidate)
if len(_ember_fb70764d2afdfc4d_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/fp24_verdict.py')
if _ember_fb70764d2afdfc4d_existing:
    _ember_fb70764d2afdfc4d_module = _ember_fb70764d2afdfc4d_existing[0]
    _ember_fb70764d2afdfc4d_observed = getattr(_ember_fb70764d2afdfc4d_module, '__file__', None)
    if _ember_fb70764d2afdfc4d_observed is None or _ember_fb70764d2afdfc4d_Path(_ember_fb70764d2afdfc4d_observed).resolve() != _ember_fb70764d2afdfc4d_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/fp24_verdict.py')
else:
    _ember_fb70764d2afdfc4d_spec = _ember_fb70764d2afdfc4d_importlib.spec_from_file_location('_ember_issue2015_fb70764d2afdfc4d', _ember_fb70764d2afdfc4d_path)
    if _ember_fb70764d2afdfc4d_spec is None or _ember_fb70764d2afdfc4d_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/fp24_verdict.py')
    _ember_fb70764d2afdfc4d_module = _ember_fb70764d2afdfc4d_importlib.module_from_spec(_ember_fb70764d2afdfc4d_spec)
    for _ember_fb70764d2afdfc4d_alias in _ember_fb70764d2afdfc4d_aliases:
        _ember_fb70764d2afdfc4d_prior = _ember_fb70764d2afdfc4d_sys.modules.get(_ember_fb70764d2afdfc4d_alias)
        if _ember_fb70764d2afdfc4d_prior is not None and _ember_fb70764d2afdfc4d_prior is not _ember_fb70764d2afdfc4d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp24_verdict.py')
        _ember_fb70764d2afdfc4d_sys.modules[_ember_fb70764d2afdfc4d_alias] = _ember_fb70764d2afdfc4d_module
    try:
        _ember_fb70764d2afdfc4d_spec.loader.exec_module(_ember_fb70764d2afdfc4d_module)
    except BaseException:
        for _ember_fb70764d2afdfc4d_alias in _ember_fb70764d2afdfc4d_aliases:
            if _ember_fb70764d2afdfc4d_sys.modules.get(_ember_fb70764d2afdfc4d_alias) is _ember_fb70764d2afdfc4d_module:
                _ember_fb70764d2afdfc4d_sys.modules.pop(_ember_fb70764d2afdfc4d_alias, None)
        raise
for _ember_fb70764d2afdfc4d_alias in _ember_fb70764d2afdfc4d_aliases:
    _ember_fb70764d2afdfc4d_prior = _ember_fb70764d2afdfc4d_sys.modules.get(_ember_fb70764d2afdfc4d_alias)
    if _ember_fb70764d2afdfc4d_prior is not None and _ember_fb70764d2afdfc4d_prior is not _ember_fb70764d2afdfc4d_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp24_verdict.py')
    _ember_fb70764d2afdfc4d_sys.modules[_ember_fb70764d2afdfc4d_alias] = _ember_fb70764d2afdfc4d_module
fp24 = _ember_fb70764d2afdfc4d_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/fp24_verdict.py                        # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/fp29_kill_synthesis_gate.py
import importlib.util as _ember_5d95172bf57f935c_importlib
import sys as _ember_5d95172bf57f935c_sys
from pathlib import Path as _ember_5d95172bf57f935c_Path
_ember_5d95172bf57f935c_path = _ember_5d95172bf57f935c_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'fp29_kill_synthesis_gate.py')
if not _ember_5d95172bf57f935c_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/fp29_kill_synthesis_gate.py')
_ember_5d95172bf57f935c_aliases = ('_ember_issue2015_5d95172bf57f935c', 'fp29_kill_synthesis_gate', 'scripts.fp29_kill_synthesis_gate')
_ember_5d95172bf57f935c_existing = []
for _ember_5d95172bf57f935c_alias in _ember_5d95172bf57f935c_aliases:
    _ember_5d95172bf57f935c_candidate = _ember_5d95172bf57f935c_sys.modules.get(_ember_5d95172bf57f935c_alias)
    if _ember_5d95172bf57f935c_candidate is not None and all(_ember_5d95172bf57f935c_candidate is not item for item in _ember_5d95172bf57f935c_existing):
        _ember_5d95172bf57f935c_existing.append(_ember_5d95172bf57f935c_candidate)
if len(_ember_5d95172bf57f935c_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/fp29_kill_synthesis_gate.py')
if _ember_5d95172bf57f935c_existing:
    _ember_5d95172bf57f935c_module = _ember_5d95172bf57f935c_existing[0]
    _ember_5d95172bf57f935c_observed = getattr(_ember_5d95172bf57f935c_module, '__file__', None)
    if _ember_5d95172bf57f935c_observed is None or _ember_5d95172bf57f935c_Path(_ember_5d95172bf57f935c_observed).resolve() != _ember_5d95172bf57f935c_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/fp29_kill_synthesis_gate.py')
else:
    _ember_5d95172bf57f935c_spec = _ember_5d95172bf57f935c_importlib.spec_from_file_location('_ember_issue2015_5d95172bf57f935c', _ember_5d95172bf57f935c_path)
    if _ember_5d95172bf57f935c_spec is None or _ember_5d95172bf57f935c_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/fp29_kill_synthesis_gate.py')
    _ember_5d95172bf57f935c_module = _ember_5d95172bf57f935c_importlib.module_from_spec(_ember_5d95172bf57f935c_spec)
    for _ember_5d95172bf57f935c_alias in _ember_5d95172bf57f935c_aliases:
        _ember_5d95172bf57f935c_prior = _ember_5d95172bf57f935c_sys.modules.get(_ember_5d95172bf57f935c_alias)
        if _ember_5d95172bf57f935c_prior is not None and _ember_5d95172bf57f935c_prior is not _ember_5d95172bf57f935c_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp29_kill_synthesis_gate.py')
        _ember_5d95172bf57f935c_sys.modules[_ember_5d95172bf57f935c_alias] = _ember_5d95172bf57f935c_module
    try:
        _ember_5d95172bf57f935c_spec.loader.exec_module(_ember_5d95172bf57f935c_module)
    except BaseException:
        for _ember_5d95172bf57f935c_alias in _ember_5d95172bf57f935c_aliases:
            if _ember_5d95172bf57f935c_sys.modules.get(_ember_5d95172bf57f935c_alias) is _ember_5d95172bf57f935c_module:
                _ember_5d95172bf57f935c_sys.modules.pop(_ember_5d95172bf57f935c_alias, None)
        raise
for _ember_5d95172bf57f935c_alias in _ember_5d95172bf57f935c_aliases:
    _ember_5d95172bf57f935c_prior = _ember_5d95172bf57f935c_sys.modules.get(_ember_5d95172bf57f935c_alias)
    if _ember_5d95172bf57f935c_prior is not None and _ember_5d95172bf57f935c_prior is not _ember_5d95172bf57f935c_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp29_kill_synthesis_gate.py')
    _ember_5d95172bf57f935c_sys.modules[_ember_5d95172bf57f935c_alias] = _ember_5d95172bf57f935c_module
fp29gate = _ember_5d95172bf57f935c_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/fp29_kill_synthesis_gate.py        # noqa: E402
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
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py            # noqa: E402
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
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_check.py         # noqa: E402

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

_FAKE_SHA40 = "a" * 40
_FAKE_SHA64 = "b" * 64
_FAKE_CORPUS_SHA = "c" * 64
_FAKE_PROBE_SET_SHA = "d" * 64


def _probe_receipt(checkpoint_tokens, l1_verified, l1_minutes, step=244000):
    """Minimal well-formed fp23-schema probe receipt for dress rehearsal."""
    return {
        "ticket": f"DRESS-REHEARSAL-PROBE-{checkpoint_tokens // 1_000_000_000}B-SYNTHETIC",
        "ts": "20260612T000000Z",
        "checkpoint_tokens": checkpoint_tokens,
        "step": step,
        "tokenizer_sha256": _FAKE_SHA64,
        "corpus_manifest_sha256": _FAKE_CORPUS_SHA,
        "adapter_none_assert": True,
        "pacing": "timed",
        "governor": "fp23-timed",
        "probe_seed": 23,
        "probe_set_sha256": _FAKE_PROBE_SET_SHA,
        "l1_verified_episodes": l1_verified,
        "l1_governed_minutes": l1_minutes,
        "l1_tasks_any_verified": max(0, l1_verified),
        "l1_tasks_total": 100,
        "l2_verified_episodes": 0,
        "mbpp43_verified_samples": 0,
        "protocol_sha": _FAKE_SHA40,
        "harness_sha": _FAKE_SHA40,
        "sha_convention": SHA_CONVENTION,
    }


def _synthesis_receipt_valid(manifest_sha):
    return {
        "ticket": "CURRICULUM-SYNTHESIS-2B4B",
        "ts": "20260612T000000Z",
        "window": "2B->4B",
        "episodes_generated": 120,
        "bucket_range_assert": True,
        "ops_in_grammar_assert": True,
        "probe_buckets_untouched_assert": True,
        "ingestion_manifest_sha256": "e" * 64,
        "episodes_manifest_sha256": manifest_sha,
        "sha_convention": SHA_CONVENTION,
    }


def _synthesis_receipt_malformed():
    return {
        "ticket": "CURRICULUM-SYNTHESIS-2B4B",
        "ts": "20260612T000000Z",
        # window missing intentionally
        "episodes_generated": 0,  # invalid: must be > 0
        "bucket_range_assert": True,
        "ops_in_grammar_assert": True,
        "probe_buckets_untouched_assert": True,
        "ingestion_manifest_sha256": "f" * 64,
        "episodes_manifest_sha256": "g" * 64,
        "sha_convention": SHA_CONVENTION,
    }


# ---------------------------------------------------------------------------
# Rehearsal
# ---------------------------------------------------------------------------

def _manifest_sha_from_fp29_dryrun():
    """Read episodes_manifest_sha256 from the fp29 dry-run receipt if present."""
    import glob
    pattern = os.path.join(NC, "receipts", "fp29-curriculum-dryrun-*.json")
    hits = sorted(glob.glob(pattern))
    if not hits:
        return "0" * 64
    with open(hits[-1]) as f:
        r = json.load(f)
    return r.get("episodes_manifest_sha256", "0" * 64)


def run_rehearsal():
    """Run all chains. Returns (outcomes_dict, errors_list).

    errors_list is empty on full success; each entry names the failing check.
    """
    errors = []
    outcomes = {}

    manifest_sha = _manifest_sha_from_fp29_dryrun()

    # ---- Chain A: 2B PASS ------------------------------------------------
    probe_2b_pass = _probe_receipt(2_000_000_000, l1_verified=30, l1_minutes=20.0)
    v_a = fp24.run_verdict("2B", probe_2b_pass)
    outcomes["A_2B_PASS_verdict"] = v_a.get("verdict")
    if v_a.get("verdict") != "PASS":
        errors.append(f"Chain A: expected PASS, got {v_a.get('verdict')!r} ({v_a})")
    gate_a = fp29gate.validate_kill(v_a)
    outcomes["A_fp29_gate"] = gate_a.get("gate")
    if gate_a.get("gate") != "PASS-THROUGH":
        errors.append(f"Chain A: fp29 gate expected PASS-THROUGH, got {gate_a.get('gate')!r}")

    # ---- Chain B: 2B RETRY -> 4B KILL, no synthesis ----------------------
    probe_2b_fail = _probe_receipt(2_000_000_000, l1_verified=5, l1_minutes=20.0)
    v_b_2b = fp24.run_verdict("2B", probe_2b_fail)
    outcomes["B_2B_RETRY_verdict"] = v_b_2b.get("verdict")
    if v_b_2b.get("verdict") != "RETRY-AT-4B":
        errors.append(f"Chain B: expected RETRY-AT-4B, got {v_b_2b.get('verdict')!r}")

    probe_4b_kill = _probe_receipt(4_000_000_000, l1_verified=5, l1_minutes=20.0)
    # run_verdict expects prior_2b_verdict as the verdict STRING, not the full dict
    # (main() extracts via pv.get("result", pv).get("verdict") from the receipt file)
    v_b_4b = fp24.run_verdict("4B", probe_4b_kill, prior_2b_verdict=v_b_2b.get("verdict"))
    outcomes["B_4B_KILL_verdict"] = v_b_4b.get("verdict")
    if v_b_4b.get("verdict") != "KILL":
        errors.append(f"Chain B: expected KILL, got {v_b_4b.get('verdict')!r}")

    gate_b = fp29gate.validate_kill(v_b_4b, synthesis_receipt=None)
    outcomes["B_fp29_gate"] = gate_b.get("gate")
    if gate_b.get("gate") != "KILL-REFUSED-SYNTHESIS-UNRECEIPTED":
        errors.append(f"Chain B: expected KILL-REFUSED-SYNTHESIS-UNRECEIPTED, "
                      f"got {gate_b.get('gate')!r}")

    # ---- Chain C: 4B KILL, synthesis malformed ----------------------------
    sr_bad = _synthesis_receipt_malformed()
    gate_c = fp29gate.validate_kill(v_b_4b, synthesis_receipt=sr_bad)
    outcomes["C_fp29_gate"] = gate_c.get("gate")
    if gate_c.get("gate") != "KILL-REFUSED-SYNTHESIS-MALFORMED":
        errors.append(f"Chain C: expected KILL-REFUSED-SYNTHESIS-MALFORMED, "
                      f"got {gate_c.get('gate')!r}")

    # ---- Chain D: 4B KILL, synthesis valid --------------------------------
    sr_good = _synthesis_receipt_valid(manifest_sha)
    gate_d = fp29gate.validate_kill(v_b_4b, synthesis_receipt=sr_good)
    outcomes["D_fp29_gate"] = gate_d.get("gate")
    if gate_d.get("gate") != "KILL-VALID":
        errors.append(f"Chain D: expected KILL-VALID, got {gate_d.get('gate')!r}")

    # ---- Chain E: 2B RETRY -> 4B late-onset PASS -------------------------
    probe_4b_pass = _probe_receipt(4_000_000_000, l1_verified=30, l1_minutes=20.0)
    v_e_4b = fp24.run_verdict("4B", probe_4b_pass, prior_2b_verdict=v_b_2b.get("verdict"))
    outcomes["E_4B_LATE_PASS_verdict"] = v_e_4b.get("verdict")
    if v_e_4b.get("verdict") != "PASS":
        errors.append(f"Chain E: expected late-onset PASS, got {v_e_4b.get('verdict')!r}")
    gate_e = fp29gate.validate_kill(v_e_4b)
    outcomes["E_fp29_gate"] = gate_e.get("gate")
    if gate_e.get("gate") != "PASS-THROUGH":
        errors.append(f"Chain E: fp29 gate expected PASS-THROUGH, got {gate_e.get('gate')!r}")

    # ---- Chain F: fp36_consistency pre-data guard -------------------------
    script = os.path.join(HERE, "fp36_consistency.py")
    result = subprocess.run(
        [sys.executable, script],
        capture_output=True, text=True, cwd=NC
    )
    fp36_ok = result.returncode == 0 and "FP36_CONSISTENCY_PASS" in result.stdout
    outcomes["F_fp36_consistency"] = "PASS" if fp36_ok else "FAIL"
    if not fp36_ok:
        errors.append(f"Chain F: fp36_consistency failed: {result.stdout.strip()} "
                      f"/ {result.stderr.strip()}")

    return outcomes, errors


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _selftest():
    outcomes, errors = run_rehearsal()
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        raise SystemExit("FP_VERDICT_CHAIN_REHEARSAL: wiring breaks found")
    print("FP_VERDICT_CHAIN_REHEARSAL_SELFTEST_PASS")
    for k, v in sorted(outcomes.items()):
        print(f"  {k}: {v}")


def main():
    ap = argparse.ArgumentParser(
        description="fp verdict-chain dress rehearsal — 2B->4B end-to-end wiring check"
    )
    ap.add_argument("--selftest", action="store_true",
                    help="run all chains, assert outcomes")
    ap.add_argument("--emit", action="store_true",
                    help="run selftest + write rehearsal receipt to receipts/")
    args = ap.parse_args()

    if not (args.selftest or args.emit):
        print(
            "FP_VERDICT_CHAIN_REHEARSAL_STAGED\n"
            "  --selftest: exercise all verdict/gate branches\n"
            "  --emit: selftest + write receipt"
        )
        return

    outcomes, errors = run_rehearsal()
    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        raise SystemExit("FP_VERDICT_CHAIN_REHEARSAL: wiring breaks found")

    print("FP_VERDICT_CHAIN_REHEARSAL_SELFTEST_PASS")
    for k, v in sorted(outcomes.items()):
        print(f"  {k}: {v}")

    if args.emit:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        receipt = {
            "ticket": "FP-VERDICT-CHAIN-REHEARSAL",
            "ts": ts,
            "chains_exercised": list(sorted(outcomes.keys())),
            "outcomes": outcomes,
            "errors": errors,
            "all_chains_pass": not errors,
            "fp36_consistency": outcomes.get("F_fp36_consistency"),
            "manifest_sha_used": _manifest_sha_from_fp29_dryrun(),
            "wiring_breaks": len(errors),
            "note": (
                "Dress rehearsal for 2B verdict chain (fp24 -> fp29 -> fp36). "
                "Synthetic probe receipts cover all verdict/gate branches. "
                "No GPU. No real checkpoint consumed. "
                "Executed before real 1B checkpoint (~step 244k). "
                "WIRING-GUIDANCE: run_verdict() prior_2b_verdict arg is a "
                "verdict STRING ('RETRY-AT-4B'), not the full dict — "
                "callers using a prior verdict dict must extract "
                ".get('verdict') or .get('result',{}).get('verdict') first "
                "(as main() does via pv.get('result',pv).get('verdict'))."
            ),
            "sha_convention": SHA_CONVENTION,
            "no_gpu": True,
        }
        findings = validate_receipt(receipt)
        if findings:
            raise SystemExit(f"receipt_check FAIL on rehearsal receipt: {findings}")
        out = os.path.join(NC, "receipts", f"fp-verdict-chain-rehearsal-{ts}.json")
        checked_write(out, receipt)
        print(f"\nRECEIPT: {out}")


if __name__ == "__main__":
    main()
