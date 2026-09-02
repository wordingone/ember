# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for source-complete classification expansion."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_oldest_issue_disposition import MASTER, _raw_capture

# issue2015 exact-local-import:src/ember/governance/scripts/build_oldest_issue_decisions.py
import importlib.util as _ember_1447abc539a28d7d_importlib
import sys as _ember_1447abc539a28d7d_sys
from pathlib import Path as _ember_1447abc539a28d7d_Path
_ember_1447abc539a28d7d_path = _ember_1447abc539a28d7d_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'build_oldest_issue_decisions.py')
if not _ember_1447abc539a28d7d_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/build_oldest_issue_decisions.py')
_ember_1447abc539a28d7d_aliases = ('_ember_issue2015_1447abc539a28d7d', 'build_oldest_issue_decisions', 'scripts.build_oldest_issue_decisions', 'src.ember.governance.scripts.build_oldest_issue_decisions')
_ember_1447abc539a28d7d_existing = []
for _ember_1447abc539a28d7d_alias in _ember_1447abc539a28d7d_aliases:
    _ember_1447abc539a28d7d_candidate = _ember_1447abc539a28d7d_sys.modules.get(_ember_1447abc539a28d7d_alias)
    if _ember_1447abc539a28d7d_candidate is not None and all(_ember_1447abc539a28d7d_candidate is not item for item in _ember_1447abc539a28d7d_existing):
        _ember_1447abc539a28d7d_existing.append(_ember_1447abc539a28d7d_candidate)
if len(_ember_1447abc539a28d7d_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/build_oldest_issue_decisions.py')
if _ember_1447abc539a28d7d_existing:
    _ember_1447abc539a28d7d_module = _ember_1447abc539a28d7d_existing[0]
    _ember_1447abc539a28d7d_observed = getattr(_ember_1447abc539a28d7d_module, '__file__', None)
    if _ember_1447abc539a28d7d_observed is None or _ember_1447abc539a28d7d_Path(_ember_1447abc539a28d7d_observed).resolve() != _ember_1447abc539a28d7d_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/build_oldest_issue_decisions.py')
else:
    _ember_1447abc539a28d7d_spec = _ember_1447abc539a28d7d_importlib.spec_from_file_location('_ember_issue2015_1447abc539a28d7d', _ember_1447abc539a28d7d_path)
    if _ember_1447abc539a28d7d_spec is None or _ember_1447abc539a28d7d_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/build_oldest_issue_decisions.py')
    _ember_1447abc539a28d7d_module = _ember_1447abc539a28d7d_importlib.module_from_spec(_ember_1447abc539a28d7d_spec)
    for _ember_1447abc539a28d7d_alias in _ember_1447abc539a28d7d_aliases:
        _ember_1447abc539a28d7d_prior = _ember_1447abc539a28d7d_sys.modules.get(_ember_1447abc539a28d7d_alias)
        if _ember_1447abc539a28d7d_prior is not None and _ember_1447abc539a28d7d_prior is not _ember_1447abc539a28d7d_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/build_oldest_issue_decisions.py')
        _ember_1447abc539a28d7d_sys.modules[_ember_1447abc539a28d7d_alias] = _ember_1447abc539a28d7d_module
    try:
        _ember_1447abc539a28d7d_spec.loader.exec_module(_ember_1447abc539a28d7d_module)
    except BaseException:
        for _ember_1447abc539a28d7d_alias in _ember_1447abc539a28d7d_aliases:
            if _ember_1447abc539a28d7d_sys.modules.get(_ember_1447abc539a28d7d_alias) is _ember_1447abc539a28d7d_module:
                _ember_1447abc539a28d7d_sys.modules.pop(_ember_1447abc539a28d7d_alias, None)
        raise
for _ember_1447abc539a28d7d_alias in _ember_1447abc539a28d7d_aliases:
    _ember_1447abc539a28d7d_prior = _ember_1447abc539a28d7d_sys.modules.get(_ember_1447abc539a28d7d_alias)
    if _ember_1447abc539a28d7d_prior is not None and _ember_1447abc539a28d7d_prior is not _ember_1447abc539a28d7d_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/build_oldest_issue_decisions.py')
    _ember_1447abc539a28d7d_sys.modules[_ember_1447abc539a28d7d_alias] = _ember_1447abc539a28d7d_module
PacketError = getattr(_ember_1447abc539a28d7d_module, 'PacketError')
build_decisions = getattr(_ember_1447abc539a28d7d_module, 'build_decisions')
# issue2015 exact-local-import-end:src/ember/governance/scripts/build_oldest_issue_decisions.py
# issue2015 exact-local-import:src/ember/governance/scripts/oldest_issue_disposition.py
import importlib.util as _ember_366a9bf8189d4fa2_importlib
import sys as _ember_366a9bf8189d4fa2_sys
from pathlib import Path as _ember_366a9bf8189d4fa2_Path
_ember_366a9bf8189d4fa2_path = _ember_366a9bf8189d4fa2_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'oldest_issue_disposition.py')
if not _ember_366a9bf8189d4fa2_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/oldest_issue_disposition.py')
_ember_366a9bf8189d4fa2_aliases = ('_ember_issue2015_366a9bf8189d4fa2', 'oldest_issue_disposition', 'scripts.oldest_issue_disposition', 'src.ember.governance.scripts.oldest_issue_disposition')
_ember_366a9bf8189d4fa2_existing = []
for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
    _ember_366a9bf8189d4fa2_candidate = _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias)
    if _ember_366a9bf8189d4fa2_candidate is not None and all(_ember_366a9bf8189d4fa2_candidate is not item for item in _ember_366a9bf8189d4fa2_existing):
        _ember_366a9bf8189d4fa2_existing.append(_ember_366a9bf8189d4fa2_candidate)
if len(_ember_366a9bf8189d4fa2_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/oldest_issue_disposition.py')
if _ember_366a9bf8189d4fa2_existing:
    _ember_366a9bf8189d4fa2_module = _ember_366a9bf8189d4fa2_existing[0]
    _ember_366a9bf8189d4fa2_observed = getattr(_ember_366a9bf8189d4fa2_module, '__file__', None)
    if _ember_366a9bf8189d4fa2_observed is None or _ember_366a9bf8189d4fa2_Path(_ember_366a9bf8189d4fa2_observed).resolve() != _ember_366a9bf8189d4fa2_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/oldest_issue_disposition.py')
else:
    _ember_366a9bf8189d4fa2_spec = _ember_366a9bf8189d4fa2_importlib.spec_from_file_location('_ember_issue2015_366a9bf8189d4fa2', _ember_366a9bf8189d4fa2_path)
    if _ember_366a9bf8189d4fa2_spec is None or _ember_366a9bf8189d4fa2_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/oldest_issue_disposition.py')
    _ember_366a9bf8189d4fa2_module = _ember_366a9bf8189d4fa2_importlib.module_from_spec(_ember_366a9bf8189d4fa2_spec)
    for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
        _ember_366a9bf8189d4fa2_prior = _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias)
        if _ember_366a9bf8189d4fa2_prior is not None and _ember_366a9bf8189d4fa2_prior is not _ember_366a9bf8189d4fa2_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/oldest_issue_disposition.py')
        _ember_366a9bf8189d4fa2_sys.modules[_ember_366a9bf8189d4fa2_alias] = _ember_366a9bf8189d4fa2_module
    try:
        _ember_366a9bf8189d4fa2_spec.loader.exec_module(_ember_366a9bf8189d4fa2_module)
    except BaseException:
        for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
            if _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias) is _ember_366a9bf8189d4fa2_module:
                _ember_366a9bf8189d4fa2_sys.modules.pop(_ember_366a9bf8189d4fa2_alias, None)
        raise
for _ember_366a9bf8189d4fa2_alias in _ember_366a9bf8189d4fa2_aliases:
    _ember_366a9bf8189d4fa2_prior = _ember_366a9bf8189d4fa2_sys.modules.get(_ember_366a9bf8189d4fa2_alias)
    if _ember_366a9bf8189d4fa2_prior is not None and _ember_366a9bf8189d4fa2_prior is not _ember_366a9bf8189d4fa2_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/oldest_issue_disposition.py')
    _ember_366a9bf8189d4fa2_sys.modules[_ember_366a9bf8189d4fa2_alias] = _ember_366a9bf8189d4fa2_module
build_capture = getattr(_ember_366a9bf8189d4fa2_module, 'build_capture')
build_packet = getattr(_ember_366a9bf8189d4fa2_module, 'build_packet')
# issue2015 exact-local-import-end:src/ember/governance/scripts/oldest_issue_disposition.py


def _classifications(capture: dict) -> dict:
    return {
        "schema_version": "ember-oldest-issue-classifications-v1",
        "expected_issue_numbers": [
            issue["number"] for issue in capture["issues"]
        ],
        "rows": [
            {
                "issue_number": issue["number"],
                "disposition": "PARTIAL",
                "unbound_description": f"unbound {issue['number']}",
                "smallest_binding_action": f"bind {issue['number']}",
                "replacement_citation": None,
                "retained_lesson": None,
            }
            for issue in capture["issues"]
        ],
    }


class BuildOldestIssueDecisionsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        _raw_capture(root)
        self.capture = build_capture(
            root,
            master_sha=MASTER,
            captured_at="2026-07-25T00:00:00Z",
        )

    def test_expands_every_body_and_comment_source_once(self) -> None:
        decisions = build_decisions(
            self.capture,
            _classifications(self.capture),
        )
        packet = build_packet(self.capture, decisions)
        self.assertEqual(len(packet["receipts"]), 20)
        self.assertEqual(
            len(packet["receipts"][0]["source_clause_inventory"]),
            2,
        )

    def test_rejects_live_selection_drift_and_close_generation(self) -> None:
        classifications = _classifications(self.capture)
        classifications["expected_issue_numbers"][0] = 999
        with self.assertRaisesRegex(PacketError, "live selection"):
            build_decisions(self.capture, classifications)

        classifications = _classifications(self.capture)
        classifications["rows"][0]["disposition"] = "CLOSE"
        with self.assertRaisesRegex(PacketError, "cannot generate CLOSE"):
            build_decisions(self.capture, classifications)

    def test_rejects_missing_duplicate_or_incompatible_rows(self) -> None:
        classifications = _classifications(self.capture)
        classifications["rows"].pop()
        with self.assertRaisesRegex(PacketError, "selection"):
            build_decisions(self.capture, classifications)

        classifications = _classifications(self.capture)
        classifications["rows"][1]["issue_number"] = (
            classifications["rows"][0]["issue_number"]
        )
        with self.assertRaisesRegex(PacketError, "duplicate"):
            build_decisions(self.capture, classifications)

        classifications = _classifications(self.capture)
        classifications["rows"][0]["replacement_citation"] = "issue:1"
        with self.assertRaisesRegex(PacketError, "incompatible"):
            build_decisions(self.capture, classifications)

    def test_decision_builder_accepts_final_partial_batch(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        _raw_capture(root, issue_count=3)
        capture = build_capture(
            root,
            master_sha=MASTER,
            captured_at="2026-07-25T00:00:00Z",
        )
        decisions = build_decisions(capture, _classifications(capture))
        packet = build_packet(capture, decisions)
        self.assertEqual(len(decisions["rows"]), 3)
        self.assertEqual(len(packet["receipts"]), 3)
