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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scripts.build_oldest_issue_decisions import build_decisions  # noqa: E402
from scripts.oldest_issue_disposition import (  # noqa: E402
    PacketError,
    build_capture,
    build_packet,
)
from scripts.verify_oldest_issue_disposition_packet import (  # noqa: E402
    verify_replay,
    write_raw_bundle,
)
from test_build_oldest_issue_decisions import _classifications  # noqa: E402
from test_oldest_issue_disposition import MASTER, _raw_capture  # noqa: E402


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
