#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c_invariant_supersession_test.py -- LAUNDERING GUARD regression for
test_c_invariant.py's supersession mechanism (gh issue #625, frozen spec
point 2, acceptance criterion: "A regression test proving the laundering
guard: a supersession row pointing at a missing/unstamped/different-class
target does NOT count as coverage.").

Exercises _supersession_covers() and _load_supersessions() directly against
a disposable temp tree (monkeypatching test_c_invariant.ROOT for the
duration of each test, restored after) -- never the live repo's receipts/.

Four branches:
  1. new_path missing              -> NOT covered
  2. new_path exists, unstamped    -> NOT covered
  3. new_path exists, stamped, but a DIFFERENT leg/class than old -> NOT covered
  4. new_path exists, stamped, SAME leg/class as old              -> covered (positive control)

Run: python c_invariant_supersession_test.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# issue2015 exact-local-import:src/ember/governance/scripts/ember_totality/test_c_invariant.py
import importlib.util as _ember_a3cfd3f0311b99ed_importlib
import sys as _ember_a3cfd3f0311b99ed_sys
from pathlib import Path as _ember_a3cfd3f0311b99ed_Path
_ember_a3cfd3f0311b99ed_path = _ember_a3cfd3f0311b99ed_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'governance', 'scripts', 'ember_totality', 'test_c_invariant.py')
if not _ember_a3cfd3f0311b99ed_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_totality/test_c_invariant.py')
_ember_a3cfd3f0311b99ed_aliases = ('_ember_issue2015_a3cfd3f0311b99ed', 'scripts.ember_totality.test_c_invariant', 'test_c_invariant')
_ember_a3cfd3f0311b99ed_existing = []
for _ember_a3cfd3f0311b99ed_alias in _ember_a3cfd3f0311b99ed_aliases:
    _ember_a3cfd3f0311b99ed_candidate = _ember_a3cfd3f0311b99ed_sys.modules.get(_ember_a3cfd3f0311b99ed_alias)
    if _ember_a3cfd3f0311b99ed_candidate is not None and all(_ember_a3cfd3f0311b99ed_candidate is not item for item in _ember_a3cfd3f0311b99ed_existing):
        _ember_a3cfd3f0311b99ed_existing.append(_ember_a3cfd3f0311b99ed_candidate)
if len(_ember_a3cfd3f0311b99ed_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_totality/test_c_invariant.py')
if _ember_a3cfd3f0311b99ed_existing:
    _ember_a3cfd3f0311b99ed_module = _ember_a3cfd3f0311b99ed_existing[0]
    _ember_a3cfd3f0311b99ed_observed = getattr(_ember_a3cfd3f0311b99ed_module, '__file__', None)
    if _ember_a3cfd3f0311b99ed_observed is None or _ember_a3cfd3f0311b99ed_Path(_ember_a3cfd3f0311b99ed_observed).resolve() != _ember_a3cfd3f0311b99ed_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_totality/test_c_invariant.py')
else:
    _ember_a3cfd3f0311b99ed_spec = _ember_a3cfd3f0311b99ed_importlib.spec_from_file_location('_ember_issue2015_a3cfd3f0311b99ed', _ember_a3cfd3f0311b99ed_path)
    if _ember_a3cfd3f0311b99ed_spec is None or _ember_a3cfd3f0311b99ed_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_totality/test_c_invariant.py')
    _ember_a3cfd3f0311b99ed_module = _ember_a3cfd3f0311b99ed_importlib.module_from_spec(_ember_a3cfd3f0311b99ed_spec)
    for _ember_a3cfd3f0311b99ed_alias in _ember_a3cfd3f0311b99ed_aliases:
        _ember_a3cfd3f0311b99ed_prior = _ember_a3cfd3f0311b99ed_sys.modules.get(_ember_a3cfd3f0311b99ed_alias)
        if _ember_a3cfd3f0311b99ed_prior is not None and _ember_a3cfd3f0311b99ed_prior is not _ember_a3cfd3f0311b99ed_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_totality/test_c_invariant.py')
        _ember_a3cfd3f0311b99ed_sys.modules[_ember_a3cfd3f0311b99ed_alias] = _ember_a3cfd3f0311b99ed_module
    try:
        _ember_a3cfd3f0311b99ed_spec.loader.exec_module(_ember_a3cfd3f0311b99ed_module)
    except BaseException:
        for _ember_a3cfd3f0311b99ed_alias in _ember_a3cfd3f0311b99ed_aliases:
            if _ember_a3cfd3f0311b99ed_sys.modules.get(_ember_a3cfd3f0311b99ed_alias) is _ember_a3cfd3f0311b99ed_module:
                _ember_a3cfd3f0311b99ed_sys.modules.pop(_ember_a3cfd3f0311b99ed_alias, None)
        raise
for _ember_a3cfd3f0311b99ed_alias in _ember_a3cfd3f0311b99ed_aliases:
    _ember_a3cfd3f0311b99ed_prior = _ember_a3cfd3f0311b99ed_sys.modules.get(_ember_a3cfd3f0311b99ed_alias)
    if _ember_a3cfd3f0311b99ed_prior is not None and _ember_a3cfd3f0311b99ed_prior is not _ember_a3cfd3f0311b99ed_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_totality/test_c_invariant.py')
    _ember_a3cfd3f0311b99ed_sys.modules[_ember_a3cfd3f0311b99ed_alias] = _ember_a3cfd3f0311b99ed_module
m = _ember_a3cfd3f0311b99ed_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_totality/test_c_invariant.py  # noqa: E402

REAL_STAMP = m.INVARIANT_SHA256
WRONG_STAMP = "0" * 64


def _old_receipt() -> dict:
    return {
        "receipt_class": "IND-4",
        "leg": "customize",
        "ts": "20260710T003136Z",
        "invariant_sha256": None,
    }


def test_missing_new_path_not_covered() -> None:
    row = {"old_path": "receipts/x-old.json", "new_path": "receipts/x-new-MISSING.json",
           "reason": "test", "ts": "2026-07-10T17:00:00Z"}
    covered, reason = m._supersession_covers("receipts/x-old.json", _old_receipt(), row)
    assert covered is False, "a supersession row pointing at a nonexistent new_path must NOT count as coverage"
    assert reason and "does not exist" in reason
    print(f"ok   missing new_path -> NOT covered ({reason})")


def test_unstamped_new_path_not_covered(tmp_root: Path) -> None:
    new_rel = "receipts/x-new-unstamped.json"
    new_abs = tmp_root / new_rel
    new_abs.parent.mkdir(parents=True, exist_ok=True)
    new_abs.write_text(json.dumps({
        "receipt_class": "IND-4", "leg": "customize", "ts": "20260710T173000Z",
        "invariant_sha256": None,  # unstamped
    }), encoding="utf-8")

    row = {"old_path": "receipts/x-old.json", "new_path": new_rel,
           "reason": "test", "ts": "2026-07-10T17:00:00Z"}
    covered, reason = m._supersession_covers("receipts/x-old.json", _old_receipt(), row)
    assert covered is False, "a supersession row pointing at an UNSTAMPED new_path must NOT count as coverage"
    assert reason and "not correctly stamped" in reason
    print(f"ok   unstamped new_path -> NOT covered ({reason})")


def test_different_class_new_path_not_covered(tmp_root: Path) -> None:
    new_rel = "receipts/x-new-wrongclass.json"
    new_abs = tmp_root / new_rel
    new_abs.parent.mkdir(parents=True, exist_ok=True)
    new_abs.write_text(json.dumps({
        "receipt_class": "IND-5", "leg": "comprehend_v2",  # DIFFERENT leg class than old (IND-4:customize)
        "ts": "20260710T173000Z",
        "invariant_sha256": REAL_STAMP,
    }), encoding="utf-8")

    row = {"old_path": "receipts/x-old.json", "new_path": new_rel,
           "reason": "test", "ts": "2026-07-10T17:00:00Z"}
    covered, reason = m._supersession_covers("receipts/x-old.json", _old_receipt(), row)
    assert covered is False, "a supersession row pointing at a DIFFERENT leg class must NOT count as coverage"
    assert reason and "identity mismatch" in reason
    print(f"ok   different-class new_path -> NOT covered ({reason})")


def test_valid_same_class_stamped_is_covered(tmp_root: Path) -> None:
    new_rel = "receipts/x-new-valid.json"
    new_abs = tmp_root / new_rel
    new_abs.parent.mkdir(parents=True, exist_ok=True)
    new_abs.write_text(json.dumps({
        "receipt_class": "IND-4", "leg": "customize",  # SAME leg class as old
        "ts": "20260710T173000Z",
        "invariant_sha256": REAL_STAMP,
    }), encoding="utf-8")

    row = {"old_path": "receipts/x-old.json", "new_path": new_rel,
           "reason": "test", "ts": "2026-07-10T17:00:00Z"}
    covered, reason = m._supersession_covers("receipts/x-old.json", _old_receipt(), row)
    assert covered is True, f"a valid, same-class, correctly-stamped new_path SHOULD count as coverage; got reason={reason!r}"
    assert reason is None
    print("ok   valid same-class stamped new_path -> covered (positive control)")


def test_load_supersessions_skips_malformed_rows(tmp_root: Path) -> None:
    ss_file = tmp_root / "docs" / "ledgers" / "receipt-supersessions.jsonl"
    ss_file.parent.mkdir(parents=True, exist_ok=True)
    ss_file.write_text(
        "not json at all\n"
        + json.dumps({"old_path": "a", "new_path": "b", "reason": "r", "ts": "t"}) + "\n"
        + json.dumps({"old_path": "", "new_path": "b2"}) + "\n"  # empty old_path -- skipped
        + json.dumps({"old_path": "c"}) + "\n",  # missing new_path -- skipped
        encoding="utf-8",
    )
    prior = m.SUPERSESSIONS_FILE
    m.SUPERSESSIONS_FILE = ss_file
    try:
        supersessions, skipped = m._load_supersessions()
    finally:
        m.SUPERSESSIONS_FILE = prior
    assert supersessions == {"a": {"old_path": "a", "new_path": "b", "reason": "r", "ts": "t"}}
    assert len(skipped) == 3, f"expected 3 skipped rows, got {len(skipped)}: {skipped}"
    print(f"ok   _load_supersessions loads 1 valid row, skips 3 malformed ({skipped})")


def main() -> int:
    test_missing_new_path_not_covered()
    with tempfile.TemporaryDirectory() as td:
        tmp_root = Path(td)
        prior_root = m.ROOT
        m.ROOT = tmp_root
        try:
            test_unstamped_new_path_not_covered(tmp_root)
            test_different_class_new_path_not_covered(tmp_root)
            test_valid_same_class_stamped_is_covered(tmp_root)
        finally:
            m.ROOT = prior_root
        test_load_supersessions_skips_malformed_rows(tmp_root)
    print("PASS c_invariant_supersession_test (laundering guard: 3 rejection branches + 1 positive control)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
