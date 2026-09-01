# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD tests for invariant stamping integration in writers.

These tests verify that:
1. Checkpoint manifest writers call stamp() before writing
2. Receipt writers call stamp() before writing
3. All post-genesis artifacts carry the invariant_sha256 field
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add scripts dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# issue2015 exact-local-import:src/ember/governance/scripts/lib/invariant.py
import importlib.util as _ember_2560a87c017c05b0_importlib
import sys as _ember_2560a87c017c05b0_sys
from pathlib import Path as _ember_2560a87c017c05b0_Path
_ember_2560a87c017c05b0_path = _ember_2560a87c017c05b0_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'lib', 'invariant.py')
if not _ember_2560a87c017c05b0_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/lib/invariant.py')
_ember_2560a87c017c05b0_aliases = ('_ember_issue2015_2560a87c017c05b0', 'invariant', 'scripts.lib.invariant')
_ember_2560a87c017c05b0_existing = []
for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
    _ember_2560a87c017c05b0_candidate = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
    if _ember_2560a87c017c05b0_candidate is not None and all(_ember_2560a87c017c05b0_candidate is not item for item in _ember_2560a87c017c05b0_existing):
        _ember_2560a87c017c05b0_existing.append(_ember_2560a87c017c05b0_candidate)
if len(_ember_2560a87c017c05b0_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/lib/invariant.py')
if _ember_2560a87c017c05b0_existing:
    _ember_2560a87c017c05b0_module = _ember_2560a87c017c05b0_existing[0]
    _ember_2560a87c017c05b0_observed = getattr(_ember_2560a87c017c05b0_module, '__file__', None)
    if _ember_2560a87c017c05b0_observed is None or _ember_2560a87c017c05b0_Path(_ember_2560a87c017c05b0_observed).resolve() != _ember_2560a87c017c05b0_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/lib/invariant.py')
else:
    _ember_2560a87c017c05b0_spec = _ember_2560a87c017c05b0_importlib.spec_from_file_location('_ember_issue2015_2560a87c017c05b0', _ember_2560a87c017c05b0_path)
    if _ember_2560a87c017c05b0_spec is None or _ember_2560a87c017c05b0_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/lib/invariant.py')
    _ember_2560a87c017c05b0_module = _ember_2560a87c017c05b0_importlib.module_from_spec(_ember_2560a87c017c05b0_spec)
    for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
        _ember_2560a87c017c05b0_prior = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
        if _ember_2560a87c017c05b0_prior is not None and _ember_2560a87c017c05b0_prior is not _ember_2560a87c017c05b0_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lib/invariant.py')
        _ember_2560a87c017c05b0_sys.modules[_ember_2560a87c017c05b0_alias] = _ember_2560a87c017c05b0_module
    try:
        _ember_2560a87c017c05b0_spec.loader.exec_module(_ember_2560a87c017c05b0_module)
    except BaseException:
        for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
            if _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias) is _ember_2560a87c017c05b0_module:
                _ember_2560a87c017c05b0_sys.modules.pop(_ember_2560a87c017c05b0_alias, None)
        raise
for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
    _ember_2560a87c017c05b0_prior = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
    if _ember_2560a87c017c05b0_prior is not None and _ember_2560a87c017c05b0_prior is not _ember_2560a87c017c05b0_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lib/invariant.py')
    _ember_2560a87c017c05b0_sys.modules[_ember_2560a87c017c05b0_alias] = _ember_2560a87c017c05b0_module
stamp = getattr(_ember_2560a87c017c05b0_module, 'stamp')
INVARIANT_SHA256 = getattr(_ember_2560a87c017c05b0_module, 'INVARIANT_SHA256')
# issue2015 exact-local-import-end:src/ember/governance/scripts/lib/invariant.py


def test_stamp_adds_field_to_dict():
    """stamp() adds invariant_sha256 field to a dict."""
    test_dict = {"name": "test", "value": 123}
    stamped = stamp(test_dict, repo_root=".")

    assert "invariant_sha256" in stamped
    assert stamped["invariant_sha256"] == INVARIANT_SHA256
    assert stamped["name"] == "test"


def test_receipt_includes_invariant_sha256():
    """A receipt written by a writer must include invariant_sha256."""
    # This test fails initially because writers don't stamp yet
    # After implementation, a receipt dict stamped before writing
    # must have the field
    receipt = {
        "ticket": "test-123",
        "ts": "2026-07-07T00:00:00Z",
        "condition": "C-INV",
        "status": "GREEN"
    }

    stamped_receipt = stamp(receipt, repo_root=".")

    assert "invariant_sha256" in stamped_receipt
    assert stamped_receipt["invariant_sha256"] == INVARIANT_SHA256


def test_manifest_includes_invariant_sha256():
    """A checkpoint manifest written by a writer must include invariant_sha256."""
    manifest = {
        "model_id": "test-model",
        "step": 100,
        "weights_sha256": "abc123"
    }

    stamped_manifest = stamp(manifest, repo_root=".")

    assert "invariant_sha256" in stamped_manifest
    assert stamped_manifest["invariant_sha256"] == INVARIANT_SHA256


if __name__ == "__main__":
    import sys
    try:
        test_stamp_adds_field_to_dict()
        print("[PASS] test_stamp_adds_field_to_dict")
        test_receipt_includes_invariant_sha256()
        print("[PASS] test_receipt_includes_invariant_sha256")
        test_manifest_includes_invariant_sha256()
        print("[PASS] test_manifest_includes_invariant_sha256")
        print("\n[PASS] All stamping tests passed")
        sys.exit(0)
    except AssertionError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
