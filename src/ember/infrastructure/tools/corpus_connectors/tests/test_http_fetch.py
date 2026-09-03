# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mocked test for http_fetch.py -- no network. Fakes the urlopen call."""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import http_fetch
from src.ember.infrastructure.tools.corpus_connectors import receipt as rcpt


class _FakeResp:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, size=-1):
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener_for(payload: bytes):
    def _opener(request, timeout=60):
        return _FakeResp(payload)

    return _opener


class HttpFetchMockedTests(unittest.TestCase):
    def test_fetch_with_supplied_license_writes_receipt(self):
        payload = b"textbook contents"
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "httpdata"
            args = http_fetch.build_parser().parse_args(
                [
                    "https://example.org/book.pdf",
                    "--license", "CC-BY-4.0",
                    "--license-evidence", "site footer states CC BY 4.0",
                    "--dest", str(dest),
                ]
            )
            receipt_path = http_fetch.fetch(args, opener=_opener_for(payload))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "http")
            self.assertEqual(data["license"], "CC-BY-4.0")
            self.assertEqual(data["files"][0]["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertTrue((dest / "book.pdf").is_file())

    def test_fetch_without_license_is_unverified_and_blocked_by_default(self):
        payload = b"textbook contents"
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "httpdata"
            args = http_fetch.build_parser().parse_args(
                ["https://example.org/book.pdf", "--dest", str(dest)]
            )
            with self.assertRaises(rcpt.UnverifiedLicenseError):
                http_fetch.fetch(args, opener=_opener_for(payload))

    def test_fetch_without_license_allowed_when_flagged(self):
        payload = b"textbook contents"
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "httpdata"
            args = http_fetch.build_parser().parse_args(
                ["https://example.org/book.pdf", "--dest", str(dest), "--allow-unverified-license"]
            )
            receipt_path = http_fetch.fetch(args, opener=_opener_for(payload))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["license"], rcpt.UNVERIFIED)

    def test_sha256_mismatch_is_blocked(self):
        payload = b"textbook contents"
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "httpdata"
            args = http_fetch.build_parser().parse_args(
                [
                    "https://example.org/book.pdf",
                    "--license", "CC0-1.0",
                    "--license-evidence", "test",
                    "--sha256", "0" * 64,
                    "--dest", str(dest),
                ]
            )
            with self.assertRaises(rcpt.HashMismatchError):
                http_fetch.fetch(args, opener=_opener_for(payload))
            self.assertFalse((dest / "book.pdf").exists())

    def test_license_and_evidence_must_be_supplied_together(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "httpdata"
            args = http_fetch.build_parser().parse_args(
                ["https://example.org/book.pdf", "--license", "CC0-1.0", "--dest", str(dest)]
            )
            with self.assertRaises(rcpt.BlockedError):
                http_fetch.fetch(args, opener=_opener_for(b"x"))


if __name__ == "__main__":
    unittest.main()
