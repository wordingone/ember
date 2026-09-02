#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Unit tests for compute_working_set() (docs/domains/governance/authority/GOVERNANCE.md §9 / issue #488).

Covers:
- The field appears on a real repo root with plausible (internally
  consistent, non-negative) values.
- gh unavailability / a bad root degrades to None fields, never raises.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO_ROOT)

# issue2015 exact-local-import:src/ember/governance/scripts/ember_totality/ember_totality_spec.py
import importlib.util as _ember_a8376424dcb1abdf_importlib
import sys as _ember_a8376424dcb1abdf_sys
from pathlib import Path as _ember_a8376424dcb1abdf_Path
_ember_a8376424dcb1abdf_path = _ember_a8376424dcb1abdf_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'governance', 'scripts', 'ember_totality', 'ember_totality_spec.py')
if not _ember_a8376424dcb1abdf_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
_ember_a8376424dcb1abdf_aliases = ('_ember_issue2015_a8376424dcb1abdf', 'ember_totality_spec', 'scripts.ember_totality.ember_totality_spec')
_ember_a8376424dcb1abdf_existing = []
for _ember_a8376424dcb1abdf_alias in _ember_a8376424dcb1abdf_aliases:
    _ember_a8376424dcb1abdf_candidate = _ember_a8376424dcb1abdf_sys.modules.get(_ember_a8376424dcb1abdf_alias)
    if _ember_a8376424dcb1abdf_candidate is not None and all(_ember_a8376424dcb1abdf_candidate is not item for item in _ember_a8376424dcb1abdf_existing):
        _ember_a8376424dcb1abdf_existing.append(_ember_a8376424dcb1abdf_candidate)
if len(_ember_a8376424dcb1abdf_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
if _ember_a8376424dcb1abdf_existing:
    _ember_a8376424dcb1abdf_module = _ember_a8376424dcb1abdf_existing[0]
    _ember_a8376424dcb1abdf_observed = getattr(_ember_a8376424dcb1abdf_module, '__file__', None)
    if _ember_a8376424dcb1abdf_observed is None or _ember_a8376424dcb1abdf_Path(_ember_a8376424dcb1abdf_observed).resolve() != _ember_a8376424dcb1abdf_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
else:
    _ember_a8376424dcb1abdf_spec = _ember_a8376424dcb1abdf_importlib.spec_from_file_location('_ember_issue2015_a8376424dcb1abdf', _ember_a8376424dcb1abdf_path)
    if _ember_a8376424dcb1abdf_spec is None or _ember_a8376424dcb1abdf_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
    _ember_a8376424dcb1abdf_module = _ember_a8376424dcb1abdf_importlib.module_from_spec(_ember_a8376424dcb1abdf_spec)
    for _ember_a8376424dcb1abdf_alias in _ember_a8376424dcb1abdf_aliases:
        _ember_a8376424dcb1abdf_prior = _ember_a8376424dcb1abdf_sys.modules.get(_ember_a8376424dcb1abdf_alias)
        if _ember_a8376424dcb1abdf_prior is not None and _ember_a8376424dcb1abdf_prior is not _ember_a8376424dcb1abdf_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
        _ember_a8376424dcb1abdf_sys.modules[_ember_a8376424dcb1abdf_alias] = _ember_a8376424dcb1abdf_module
    try:
        _ember_a8376424dcb1abdf_spec.loader.exec_module(_ember_a8376424dcb1abdf_module)
    except BaseException:
        for _ember_a8376424dcb1abdf_alias in _ember_a8376424dcb1abdf_aliases:
            if _ember_a8376424dcb1abdf_sys.modules.get(_ember_a8376424dcb1abdf_alias) is _ember_a8376424dcb1abdf_module:
                _ember_a8376424dcb1abdf_sys.modules.pop(_ember_a8376424dcb1abdf_alias, None)
        raise
for _ember_a8376424dcb1abdf_alias in _ember_a8376424dcb1abdf_aliases:
    _ember_a8376424dcb1abdf_prior = _ember_a8376424dcb1abdf_sys.modules.get(_ember_a8376424dcb1abdf_alias)
    if _ember_a8376424dcb1abdf_prior is not None and _ember_a8376424dcb1abdf_prior is not _ember_a8376424dcb1abdf_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
    _ember_a8376424dcb1abdf_sys.modules[_ember_a8376424dcb1abdf_alias] = _ember_a8376424dcb1abdf_module
compute_working_set = getattr(_ember_a8376424dcb1abdf_module, 'compute_working_set')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_totality/ember_totality_spec.py


class TestWorkingSet(unittest.TestCase):
    """Unit tests for the repo hygiene working-set metric."""

    def test_shape_and_plausible_values_on_real_repo(self):
        """Against the real repo root, every key is present and plausible."""
        ws = compute_working_set(REPO_ROOT)

        expected_keys = {
            "tracked_files",
            "docs_files",
            "scripts_files",
            "tracked_receipts",
            "untracked_receipts_on_disk",
            "open_issues_count",
        }
        self.assertEqual(set(ws.keys()), expected_keys)

        # git is available in this environment, so the git-derived counts
        # must be real non-negative ints, not None.
        for key in ("tracked_files", "docs_files", "scripts_files",
                    "tracked_receipts", "untracked_receipts_on_disk"):
            self.assertIsInstance(ws[key], int, f"{key} should be an int")
            self.assertGreaterEqual(ws[key], 0, f"{key} should be >= 0")

        # Internal plausibility: subset counts never exceed the total.
        self.assertLessEqual(ws["docs_files"], ws["tracked_files"])
        self.assertLessEqual(ws["scripts_files"], ws["tracked_files"])
        self.assertLessEqual(ws["tracked_receipts"], ws["tracked_files"])

        # This repo really has docs/ and scripts/ trees with files in them.
        self.assertGreater(ws["docs_files"], 0)
        self.assertGreater(ws["scripts_files"], 0)

        # open_issues_count is gh-dependent: either a non-negative int, or
        # None (gh not installed / no network / repo not recognized).
        self.assertTrue(
            ws["open_issues_count"] is None or
            (isinstance(ws["open_issues_count"], int) and ws["open_issues_count"] >= 0)
        )

    def test_bad_root_degrades_to_none_without_raising(self):
        """A nonexistent root never raises; git-derived fields fall back to None."""
        bogus_root = os.path.join(REPO_ROOT, "no-such-dir-for-working-set-test")
        ws = compute_working_set(bogus_root)

        self.assertIsNone(ws["tracked_files"])
        self.assertIsNone(ws["docs_files"])
        self.assertIsNone(ws["scripts_files"])
        self.assertIsNone(ws["tracked_receipts"])
        self.assertIsNone(ws["untracked_receipts_on_disk"])
        # gh's own repo resolution is independent of this bogus root, so
        # open_issues_count is only constrained to the same int-or-None shape.
        self.assertTrue(
            ws["open_issues_count"] is None or isinstance(ws["open_issues_count"], int)
        )

    def test_default_repo_root_when_omitted(self):
        """Omitting repo_root falls back to REPO_ROOT and still returns the shape."""
        ws = compute_working_set()
        self.assertIsInstance(ws["tracked_files"], int)
        self.assertGreater(ws["tracked_files"], 0)


if __name__ == "__main__":
    unittest.main()
