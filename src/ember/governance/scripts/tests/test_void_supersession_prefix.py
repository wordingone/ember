#!/usr/bin/env python3
"""Regression tests for fail-closed VOID SHA-256 prefix supersession."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


TOTALITY_DIR = Path(__file__).resolve().parents[1] / "ember_totality"
if str(TOTALITY_DIR) not in sys.path:
    sys.path.insert(0, str(TOTALITY_DIR))

SPEC = importlib.util.spec_from_file_location(
    "void_supersession_prefix_subject",
    TOTALITY_DIR / "void_supersession.py",
)
assert SPEC is not None and SPEC.loader is not None
SUBJECT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SUBJECT
SPEC.loader.exec_module(SUBJECT)


class VoidSupersessionPrefixTests(unittest.TestCase):
    def _fixture(self, digest_ref: str, target_hashes: list[str]):
        root = Path(tempfile.mkdtemp())
        basename = "superseded-claim.json"
        decisive = []
        hashes_by_path: dict[str, str] = {}

        for index, target_hash in enumerate(target_hashes):
            path = root / "receipts" / f"family-{index}" / basename
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"verdict": "PASS_CLASS_FAKE", "index": index}
            path.write_text(json.dumps(payload), encoding="utf-8")
            decisive.append((str(path), payload, json.dumps(payload)))
            hashes_by_path[str(path)] = target_hash

        void_path = root / "receipts" / "superseding-VOID.json"
        void_path.parent.mkdir(parents=True, exist_ok=True)
        void_payload = {
            "verdict": "VOID",
            "supersedes": [{"filename": basename, "sha256": digest_ref}],
        }
        void_path.write_text(json.dumps(void_payload), encoding="utf-8")
        decisive.append((str(void_path), void_payload, json.dumps(void_payload)))
        hashes_by_path[str(void_path)] = "f" * 64

        original_sha256_file = SUBJECT.sha256_file
        SUBJECT.sha256_file = hashes_by_path.__getitem__
        self.addCleanup(setattr, SUBJECT, "sha256_file", original_sha256_file)
        return root, decisive

    def test_unique_16_hex_prefix_excludes_exactly_one_target(self) -> None:
        prefix = "0123456789abcdef"
        target_hash = prefix + ("a" * 48)
        root, decisive = self._fixture(prefix, [target_hash])

        kept, excluded = SUBJECT.partition_superseded(decisive, str(root))

        self.assertEqual(1, len(excluded))
        self.assertEqual(target_hash, excluded[0]["sha256"])
        self.assertEqual(prefix, excluded[0]["matched_sha256"])
        self.assertEqual("unambiguous_prefix", excluded[0]["sha256_match_kind"])
        self.assertEqual(["VOID"], [row[1]["verdict"] for row in kept])

    def test_ambiguous_prefix_excludes_nothing(self) -> None:
        prefix = "0123456789abcdef"
        root, decisive = self._fixture(
            prefix,
            [prefix + ("a" * 48), prefix + ("b" * 48)],
        )

        kept, excluded = SUBJECT.partition_superseded(decisive, str(root))

        self.assertEqual([], excluded)
        self.assertEqual(3, len(kept))

    def test_short_and_nonhex_prefixes_exclude_nothing(self) -> None:
        target_hash = "0123456789abcdef" + ("a" * 48)
        for invalid_ref in ("0123456789abcde", "0123456789abcdeg"):
            with self.subTest(invalid_ref=invalid_ref):
                root, decisive = self._fixture(invalid_ref, [target_hash])
                kept, excluded = SUBJECT.partition_superseded(decisive, str(root))
                self.assertEqual([], excluded)
                self.assertEqual(2, len(kept))

    def test_full_sha_match_remains_exact(self) -> None:
        target_hash = "a" * 64
        root, decisive = self._fixture(target_hash, [target_hash])

        kept, excluded = SUBJECT.partition_superseded(decisive, str(root))

        self.assertEqual(1, len(excluded))
        self.assertEqual(target_hash, excluded[0]["matched_sha256"])
        self.assertEqual("full", excluded[0]["sha256_match_kind"])
        self.assertEqual(["VOID"], [row[1]["verdict"] for row in kept])


if __name__ == "__main__":
    unittest.main()
