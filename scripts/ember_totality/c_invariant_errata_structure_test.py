#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c_invariant_errata_structure_test.py -- regression for
test_c_invariant.py's check_errata_structure() repoint (gh issue #625, frozen
spec point 3: repoint from the never-created INVARIANT-ERRATA.md to the REAL
docs/ledgers/receipt-errata.jsonl, validating append-only + row schema + no
post-cutoff row).

The append-only git-history check itself is untouched logic (already
sandbox-verified per _errata_append_only_violation's own docstring) -- this
file proves what point 3 actually changed: (a) the probe now reads the real
file at all, (b) row schema is enforced, (c) a post-cutoff discovered_ts row
is rejected.

Five branches, four via a disposable tempdir (monkeypatching
test_c_invariant.ERRATA_FILE for the duration, restored after):
  1. file absent               -> GREEN (honest-absent)
  2. file present, empty       -> GREEN (honest-empty)
  3. row missing a required field -> RED (schema violation)
  4. row's discovered_ts is AFTER the hard cutoff -> RED (cutoff violation)
  5. the tracked annex exactly covers every current pre-cutoff violation

Run: python c_invariant_errata_structure_test.py
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
_ember_a3cfd3f0311b99ed_path = _ember_a3cfd3f0311b99ed_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'ember_totality', 'test_c_invariant.py')
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
import receipt_errata_scan as scanner  # noqa: E402

VALID_ROW = {
    "defect": "missing-invariant-stamp",
    "discovered_ts": "2026-07-10T00:08:35Z",  # == ERRATA_CUTOFF_TS, inclusive
    "discovery_source": "test fixture",
    "disposition": "historical-pre-hardening",
    "note": "fixture row for c_invariant_errata_structure_test",
    "receipt_path": "receipts/does-not-need-to-exist-for-this-check.json",
}


def _with_errata_file(tmp_root: Path, content: str | None):
    """Context-manager-free swap of m.ERRATA_FILE for one call; caller must
    restore. Returns the swapped path."""
    ef = tmp_root / "docs" / "ledgers" / "receipt-errata.jsonl"
    ef.parent.mkdir(parents=True, exist_ok=True)
    if content is not None:
        ef.write_text(content, encoding="utf-8")
    return ef


def test_absent_file_is_honest_green() -> None:
    with tempfile.TemporaryDirectory() as td:
        ef = Path(td) / "docs" / "ledgers" / "receipt-errata.jsonl"  # never created
        prior = m.ERRATA_FILE
        m.ERRATA_FILE = ef
        try:
            ok, reason = m.check_errata_structure()
        finally:
            m.ERRATA_FILE = prior
        assert ok is True, f"absent errata file should be honest-GREEN, got {reason!r}"
        print(f"ok   absent file -> GREEN ({reason})")


def test_empty_file_is_honest_green() -> None:
    with tempfile.TemporaryDirectory() as td:
        ef = _with_errata_file(Path(td), "")
        prior = m.ERRATA_FILE
        m.ERRATA_FILE = ef
        try:
            ok, reason = m.check_errata_structure()
        finally:
            m.ERRATA_FILE = prior
        assert ok is True, f"empty errata file should be honest-GREEN, got {reason!r}"
        print(f"ok   empty file -> GREEN ({reason})")


def test_missing_field_is_red() -> None:
    bad_row = dict(VALID_ROW)
    del bad_row["disposition"]
    with tempfile.TemporaryDirectory() as td:
        ef = _with_errata_file(Path(td), json.dumps(bad_row) + "\n")
        prior = m.ERRATA_FILE
        m.ERRATA_FILE = ef
        try:
            ok, reason = m.check_errata_structure()
        finally:
            m.ERRATA_FILE = prior
        assert ok is False, "a row missing a required field must be RED"
        assert "schema violation" in reason
        print(f"ok   missing required field -> RED ({reason})")


def test_post_cutoff_discovered_ts_is_red() -> None:
    bad_row = dict(VALID_ROW)
    bad_row["discovered_ts"] = "2026-07-10T00:08:36Z"  # 1s AFTER the cutoff
    with tempfile.TemporaryDirectory() as td:
        ef = _with_errata_file(Path(td), json.dumps(bad_row) + "\n")
        prior = m.ERRATA_FILE
        m.ERRATA_FILE = ef
        try:
            ok, reason = m.check_errata_structure()
        finally:
            m.ERRATA_FILE = prior
        assert ok is False, "a row whose discovered_ts postdates the hard cutoff must be RED"
        assert "after the hard cutoff" in reason
        print(f"ok   post-cutoff discovered_ts -> RED ({reason})")


def test_real_repo_errata_file_is_clean() -> None:
    """Sanity: the probe's default ERRATA_FILE (the real, live
    docs/ledgers/receipt-errata.jsonl, 101 append-only historical rows) passes structurally
    -- proves the repoint didn't retroactively invalidate the existing annex."""
    ok, reason = m.check_errata_structure()
    assert ok is True, f"the real, landed docs/ledgers/receipt-errata.jsonl must pass structurally, got {reason!r}"
    print(f"ok   real repo docs/ledgers/receipt-errata.jsonl -> GREEN ({reason})")


def test_real_repo_annex_covers_complete_pre_cutoff_scan() -> None:
    """Every currently tracked pre-cutoff violation must be represented.

    This catches the exact #612 tail defect where receipts landed after the
    original mechanical population but carried pre-hardening timestamps.
    Future post-cutoff violations remain deliberately outside the annex and
    continue to RED through check_stamped_receipts().
    """
    cutoff_epoch = m._parse_receipt_ts(scanner.HARDENING_CUTOFF_TS)
    expected_rows, _ = scanner.build_rows(scanner.scan_violations(), cutoff_epoch)
    expected = {row["receipt_path"] for row in expected_rows}
    actual = {
        json.loads(line)["receipt_path"]
        for line in m.ERRATA_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert actual == expected, (
        "tracked historical annex differs from the complete mechanical "
        f"pre-cutoff scan: missing={sorted(expected - actual)!r}, "
        f"extra={sorted(actual - expected)!r}"
    )
    print(f"ok   tracked annex covers complete pre-cutoff scan ({len(actual)} rows)")


def main() -> int:
    test_absent_file_is_honest_green()
    test_empty_file_is_honest_green()
    test_missing_field_is_red()
    test_post_cutoff_discovered_ts_is_red()
    test_real_repo_errata_file_is_clean()
    test_real_repo_annex_covers_complete_pre_cutoff_scan()
    print("PASS c_invariant_errata_structure_test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
