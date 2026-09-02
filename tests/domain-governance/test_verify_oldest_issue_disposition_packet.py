# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""End-to-end raw-byte replay for the task-015 packet."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_build_oldest_issue_decisions import _classifications
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
PacketError = getattr(_ember_366a9bf8189d4fa2_module, 'PacketError')
build_capture = getattr(_ember_366a9bf8189d4fa2_module, 'build_capture')
build_packet = getattr(_ember_366a9bf8189d4fa2_module, 'build_packet')
# issue2015 exact-local-import-end:src/ember/governance/scripts/oldest_issue_disposition.py
# issue2015 exact-local-import:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py
import importlib.util as _ember_e1908f060d71f822_importlib
import sys as _ember_e1908f060d71f822_sys
from pathlib import Path as _ember_e1908f060d71f822_Path
_ember_e1908f060d71f822_path = _ember_e1908f060d71f822_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'verify_oldest_issue_disposition_packet.py')
if not _ember_e1908f060d71f822_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
_ember_e1908f060d71f822_aliases = ('_ember_issue2015_e1908f060d71f822', 'scripts.verify_oldest_issue_disposition_packet', 'src.ember.governance.scripts.verify_oldest_issue_disposition_packet', 'verify_oldest_issue_disposition_packet')
_ember_e1908f060d71f822_existing = []
for _ember_e1908f060d71f822_alias in _ember_e1908f060d71f822_aliases:
    _ember_e1908f060d71f822_candidate = _ember_e1908f060d71f822_sys.modules.get(_ember_e1908f060d71f822_alias)
    if _ember_e1908f060d71f822_candidate is not None and all(_ember_e1908f060d71f822_candidate is not item for item in _ember_e1908f060d71f822_existing):
        _ember_e1908f060d71f822_existing.append(_ember_e1908f060d71f822_candidate)
if len(_ember_e1908f060d71f822_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
if _ember_e1908f060d71f822_existing:
    _ember_e1908f060d71f822_module = _ember_e1908f060d71f822_existing[0]
    _ember_e1908f060d71f822_observed = getattr(_ember_e1908f060d71f822_module, '__file__', None)
    if _ember_e1908f060d71f822_observed is None or _ember_e1908f060d71f822_Path(_ember_e1908f060d71f822_observed).resolve() != _ember_e1908f060d71f822_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
else:
    _ember_e1908f060d71f822_spec = _ember_e1908f060d71f822_importlib.spec_from_file_location('_ember_issue2015_e1908f060d71f822', _ember_e1908f060d71f822_path)
    if _ember_e1908f060d71f822_spec is None or _ember_e1908f060d71f822_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
    _ember_e1908f060d71f822_module = _ember_e1908f060d71f822_importlib.module_from_spec(_ember_e1908f060d71f822_spec)
    for _ember_e1908f060d71f822_alias in _ember_e1908f060d71f822_aliases:
        _ember_e1908f060d71f822_prior = _ember_e1908f060d71f822_sys.modules.get(_ember_e1908f060d71f822_alias)
        if _ember_e1908f060d71f822_prior is not None and _ember_e1908f060d71f822_prior is not _ember_e1908f060d71f822_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
        _ember_e1908f060d71f822_sys.modules[_ember_e1908f060d71f822_alias] = _ember_e1908f060d71f822_module
    try:
        _ember_e1908f060d71f822_spec.loader.exec_module(_ember_e1908f060d71f822_module)
    except BaseException:
        for _ember_e1908f060d71f822_alias in _ember_e1908f060d71f822_aliases:
            if _ember_e1908f060d71f822_sys.modules.get(_ember_e1908f060d71f822_alias) is _ember_e1908f060d71f822_module:
                _ember_e1908f060d71f822_sys.modules.pop(_ember_e1908f060d71f822_alias, None)
        raise
for _ember_e1908f060d71f822_alias in _ember_e1908f060d71f822_aliases:
    _ember_e1908f060d71f822_prior = _ember_e1908f060d71f822_sys.modules.get(_ember_e1908f060d71f822_alias)
    if _ember_e1908f060d71f822_prior is not None and _ember_e1908f060d71f822_prior is not _ember_e1908f060d71f822_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py')
    _ember_e1908f060d71f822_sys.modules[_ember_e1908f060d71f822_alias] = _ember_e1908f060d71f822_module
verify_replay = getattr(_ember_e1908f060d71f822_module, 'verify_replay')
write_raw_bundle = getattr(_ember_e1908f060d71f822_module, 'write_raw_bundle')
# issue2015 exact-local-import-end:src/ember/governance/scripts/verify_oldest_issue_disposition_packet.py


class VerifyOldestIssueDispositionPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.temporary_root = Path(temporary.name)
        self.raw_root = self.temporary_root / "raw"
        self.raw_root.mkdir()
        _raw_capture(self.raw_root)
        self.raw_bundle = self.temporary_root / "raw.json"
        write_raw_bundle(self.raw_root, self.raw_bundle)
        self.capture = build_capture(
            self.raw_root,
            master_sha=MASTER,
            captured_at="2026-07-25T00:00:00Z",
        )
        self.classifications = _classifications(self.capture)
        decisions = build_decisions(
            self.capture,
            self.classifications,
        )
        self.packet = build_packet(self.capture, decisions)

    def test_exact_raw_sources_reproduce_full_packet(self) -> None:
        replayed = verify_replay(
            self.packet,
            raw_bundle=self.raw_bundle,
            classifications_value=self.classifications,
            expected_master=MASTER,
        )
        self.assertEqual(replayed["packet_sha256"], self.packet["packet_sha256"])

    def test_cursor_bound_raw_sources_reproduce_partial_batch(self) -> None:
        cursor_root = self.temporary_root / "cursor-raw"
        cursor_root.mkdir()
        _raw_capture(cursor_root, include_all_comments=True)
        for number in range(1, 11):
            (cursor_root / f"comments-{number}-pre.json").unlink()
            (cursor_root / f"comments-{number}-post.json").unlink()
        cursor_bundle = self.temporary_root / "cursor-raw.json"
        write_raw_bundle(cursor_root, cursor_bundle)
        capture = build_capture(
            cursor_root,
            master_sha=MASTER,
            captured_at="2026-07-25T00:00:00Z",
            after_created_at="2026-01-10T00:00:00Z",
            after_issue_number=10,
        )
        classifications = _classifications(capture)
        packet = build_packet(
            capture,
            build_decisions(capture, classifications),
        )
        replayed = verify_replay(
            packet,
            raw_bundle=cursor_bundle,
            classifications_value=classifications,
            expected_master=MASTER,
        )
        self.assertEqual(replayed["capture"]["cursor"], capture["cursor"])
        self.assertEqual(len(replayed["receipts"]), 11)
    def test_missing_extra_or_tampered_raw_source_fails(self) -> None:
        missing = self.raw_root / "comments-1-pre.json"
        original = missing.read_bytes()
        missing.unlink()
        with self.assertRaisesRegex(PacketError, "file set mismatch"):
            verify_replay(
                self.packet,
                raw_root=self.raw_root,
                classifications_value=self.classifications,
                expected_master=MASTER,
            )
        missing.write_bytes(original)

        extra = self.raw_root / "unbounded.json"
        extra.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(PacketError, "file set mismatch"):
            verify_replay(
                self.packet,
                raw_root=self.raw_root,
                classifications_value=self.classifications,
                expected_master=MASTER,
            )
        extra.unlink()

        nested = self.raw_root / "nested"
        nested.mkdir()
        with self.assertRaisesRegex(PacketError, "non_files"):
            verify_replay(
                self.packet,
                raw_root=self.raw_root,
                classifications_value=self.classifications,
                expected_master=MASTER,
            )
        nested.rmdir()

        changed = self.raw_root / "comments-1-post.json"
        changed.write_text("[[]]", encoding="utf-8")
        with self.assertRaises(PacketError):
            verify_replay(
                self.packet,
                raw_root=self.raw_root,
                classifications_value=self.classifications,
                expected_master=MASTER,
            )

    def test_classification_or_packet_substitution_fails(self) -> None:
        classifications = copy.deepcopy(self.classifications)
        classifications["rows"][0]["unbound_description"] = "substituted"
        with self.assertRaisesRegex(PacketError, "do not reproduce packet"):
            verify_replay(
                self.packet,
                raw_bundle=self.raw_bundle,
                classifications_value=classifications,
                expected_master=MASTER,
            )

        packet = copy.deepcopy(self.packet)
        packet["master_sha"] = "b" * 40
        with self.assertRaises(PacketError):
            verify_replay(
                packet,
                raw_bundle=self.raw_bundle,
                classifications_value=self.classifications,
                expected_master=MASTER,
            )

    def test_bundle_extra_or_source_tamper_fails(self) -> None:
        extra_root = self.temporary_root / "extra"
        extra_root.mkdir()
        for source in self.raw_root.iterdir():
            (extra_root / source.name).write_bytes(source.read_bytes())
        (extra_root / "extra.json").write_text("{}", encoding="utf-8")
        extra_bundle = self.temporary_root / "extra.json"
        write_raw_bundle(extra_root, extra_bundle)
        with self.assertRaisesRegex(PacketError, "bundle entry set mismatch"):
            verify_replay(
                self.packet,
                raw_bundle=extra_bundle,
                classifications_value=self.classifications,
                expected_master=MASTER,
            )

        (extra_root / "extra.json").unlink()
        (extra_root / "comments-1-post.json").write_text("[[]]", encoding="utf-8")
        tampered_bundle = self.temporary_root / "tampered.json"
        write_raw_bundle(extra_root, tampered_bundle)
        with self.assertRaises(PacketError):
            verify_replay(
                self.packet,
                raw_bundle=tampered_bundle,
                classifications_value=self.classifications,
                expected_master=MASTER,
            )
