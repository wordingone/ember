# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_launch_gate.py -- hermetic fixture tests for src/ember/governance/scripts/w2_heldout/launch_gate.py.

Real code (launch_gate.refuse_or_pass / assert_launch_allowed), synthetic-only
data (tempfile.TemporaryDirectory() per case, tiny made-up token rows) -- same
convention as the *_leg_test.py hermetic suites (disconfirmation_leg_test.py,
milestone_leg_test.py). No real corpus or real receipt is touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# issue2015 exact-local-import:src/ember/governance/scripts/w2_heldout/launch_gate.py
import importlib.util as _ember_010558b39c5df353_importlib
import sys as _ember_010558b39c5df353_sys
from pathlib import Path as _ember_010558b39c5df353_Path
_ember_010558b39c5df353_path = _ember_010558b39c5df353_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'governance', 'scripts', 'w2_heldout', 'launch_gate.py')
if not _ember_010558b39c5df353_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/w2_heldout/launch_gate.py')
_ember_010558b39c5df353_aliases = ('_ember_issue2015_010558b39c5df353', 'launch_gate', 'scripts.w2_heldout.launch_gate')
_ember_010558b39c5df353_existing = []
for _ember_010558b39c5df353_alias in _ember_010558b39c5df353_aliases:
    _ember_010558b39c5df353_candidate = _ember_010558b39c5df353_sys.modules.get(_ember_010558b39c5df353_alias)
    if _ember_010558b39c5df353_candidate is not None and all(_ember_010558b39c5df353_candidate is not item for item in _ember_010558b39c5df353_existing):
        _ember_010558b39c5df353_existing.append(_ember_010558b39c5df353_candidate)
if len(_ember_010558b39c5df353_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/w2_heldout/launch_gate.py')
if _ember_010558b39c5df353_existing:
    _ember_010558b39c5df353_module = _ember_010558b39c5df353_existing[0]
    _ember_010558b39c5df353_observed = getattr(_ember_010558b39c5df353_module, '__file__', None)
    if _ember_010558b39c5df353_observed is None or _ember_010558b39c5df353_Path(_ember_010558b39c5df353_observed).resolve() != _ember_010558b39c5df353_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/w2_heldout/launch_gate.py')
else:
    _ember_010558b39c5df353_spec = _ember_010558b39c5df353_importlib.spec_from_file_location('_ember_issue2015_010558b39c5df353', _ember_010558b39c5df353_path)
    if _ember_010558b39c5df353_spec is None or _ember_010558b39c5df353_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/w2_heldout/launch_gate.py')
    _ember_010558b39c5df353_module = _ember_010558b39c5df353_importlib.module_from_spec(_ember_010558b39c5df353_spec)
    for _ember_010558b39c5df353_alias in _ember_010558b39c5df353_aliases:
        _ember_010558b39c5df353_prior = _ember_010558b39c5df353_sys.modules.get(_ember_010558b39c5df353_alias)
        if _ember_010558b39c5df353_prior is not None and _ember_010558b39c5df353_prior is not _ember_010558b39c5df353_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w2_heldout/launch_gate.py')
        _ember_010558b39c5df353_sys.modules[_ember_010558b39c5df353_alias] = _ember_010558b39c5df353_module
    try:
        _ember_010558b39c5df353_spec.loader.exec_module(_ember_010558b39c5df353_module)
    except BaseException:
        for _ember_010558b39c5df353_alias in _ember_010558b39c5df353_aliases:
            if _ember_010558b39c5df353_sys.modules.get(_ember_010558b39c5df353_alias) is _ember_010558b39c5df353_module:
                _ember_010558b39c5df353_sys.modules.pop(_ember_010558b39c5df353_alias, None)
        raise
for _ember_010558b39c5df353_alias in _ember_010558b39c5df353_aliases:
    _ember_010558b39c5df353_prior = _ember_010558b39c5df353_sys.modules.get(_ember_010558b39c5df353_alias)
    if _ember_010558b39c5df353_prior is not None and _ember_010558b39c5df353_prior is not _ember_010558b39c5df353_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w2_heldout/launch_gate.py')
    _ember_010558b39c5df353_sys.modules[_ember_010558b39c5df353_alias] = _ember_010558b39c5df353_module
refuse_or_pass = getattr(_ember_010558b39c5df353_module, 'refuse_or_pass')
assert_launch_allowed = getattr(_ember_010558b39c5df353_module, 'assert_launch_allowed')
# issue2015 exact-local-import-end:src/ember/governance/scripts/w2_heldout/launch_gate.py  # noqa: E402


SEQ = 4
ROWS = np.array([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15]], dtype=np.int64)


def _row_sha(rows: np.ndarray, seq: int) -> str:
    xs, ys = rows[:, :seq], rows[:, 1:seq + 1]
    return hashlib.sha256(np.concatenate([xs, ys], axis=1).tobytes()).hexdigest()


def _write_receipt(path, **fields):
    base = {"pass": True, "seq": SEQ, "batch_sha256": _row_sha(ROWS, SEQ),
            "contamination_recheck": {"confirmed_non_self_matches": 0}}
    base.update(fields)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(base, fh)
    return path


def test_green_pinned_batch_matching_sha_zero_contamination_passes():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = _write_receipt(os.path.join(td, "receipt.json"))

        result = refuse_or_pass(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is True
        assert "ALLOWED" in result.reason


def test_red_tampered_batch_sha_mismatch_refuses():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = _write_receipt(os.path.join(td, "receipt.json"))

        # Tamper the batch file AFTER the receipt was pinned.
        np.save(batch_path, ROWS + 1)

        result = refuse_or_pass(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is False
        assert "sha256" in result.reason


def test_red_nonzero_contamination_recheck_refuses():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = _write_receipt(
            os.path.join(td, "receipt.json"),
            contamination_recheck={"confirmed_non_self_matches": 3})

        result = refuse_or_pass(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is False
        assert "confirmed_non_self_matches" in result.reason


def test_red_pass_field_false_refuses():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = _write_receipt(os.path.join(td, "receipt.json"), **{"pass": False})

        result = refuse_or_pass(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is False


def test_red_missing_receipt_refuses():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)

        result = refuse_or_pass(batch_path=batch_path,
                                 receipt_path=os.path.join(td, "does-not-exist.json"))

        assert result.allowed is False
        assert "does not exist" in result.reason


def test_red_missing_batch_file_refuses():
    with tempfile.TemporaryDirectory() as td:
        receipt_path = _write_receipt(os.path.join(td, "receipt.json"))

        result = refuse_or_pass(batch_path=os.path.join(td, "no-such-batch.npy"),
                                 receipt_path=receipt_path)

        assert result.allowed is False
        assert "batch file" in result.reason


def test_red_unparseable_receipt_json_refuses():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = os.path.join(td, "receipt.json")
        with open(receipt_path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")

        result = refuse_or_pass(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is False
        assert "unparseable" in result.reason or "unreadable" in result.reason


def test_newest_receipt_auto_discovery_picks_highest_ts():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_dir = os.path.join(td, "receipts")
        os.makedirs(receipt_dir)
        _write_receipt(os.path.join(receipt_dir, "w2-heldout-decontam-20260101T000000Z.json"),
                       **{"pass": False})
        _write_receipt(os.path.join(receipt_dir, "w2-heldout-decontam-20260704T235959Z.json"))

        result = refuse_or_pass(batch_path=batch_path, receipt_dir=receipt_dir)

        assert result.allowed is True
        assert result.receipt_path.endswith("20260704T235959Z.json")


def test_assert_launch_allowed_raises_systemexit_on_refusal():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        with pytest.raises(SystemExit, match="W2_LAUNCH_GATE_REFUSED"):
            assert_launch_allowed(batch_path=batch_path,
                                   receipt_path=os.path.join(td, "missing.json"))


def test_assert_launch_allowed_returns_result_on_pass():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = _write_receipt(os.path.join(td, "receipt.json"))

        result = assert_launch_allowed(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is True
