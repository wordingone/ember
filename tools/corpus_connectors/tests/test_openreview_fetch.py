# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mocked test for openreview_fetch.py -- no network. Fakes the API v2 JSON response."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openreview_fetch
import receipt as rcpt


class _FakeResp:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, size=-1):
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _notes_payload(notes):
    return json.dumps({"notes": notes}).encode("utf-8")


def _opener_for(payload_bytes: bytes, pdf_bytes: bytes = b"%PDF-fake"):
    calls = {"n": 0}

    def _opener(request, timeout=60):
        calls["n"] += 1
        url = request.full_url
        if "api2.openreview.net/notes" in url:
            # First page returns the payload; any subsequent page (pagination
            # probe) returns an empty note list so the loop terminates.
            if calls["n"] == 1:
                return _FakeResp(payload_bytes)
            return _FakeResp(json.dumps({"notes": []}).encode("utf-8"))
        return _FakeResp(pdf_bytes)

    return _opener


ONE_LICENSED_NOTE = _notes_payload(
    [
        {
            "id": "note-abc",
            "content": {
                "title": {"value": "A Licensed Paper"},
                "license": {"value": "CC-BY-4.0"},
                "pdf": "/pdf/note-abc.pdf",
            },
        }
    ]
)

ONE_UNLICENSED_NOTE = _notes_payload(
    [
        {
            "id": "note-xyz",
            "content": {
                "title": {"value": "An Unlicensed Paper"},
                "pdf": "/pdf/note-xyz.pdf",
            },
        }
    ]
)


def _recording_opener_for(payload_bytes: bytes, pdf_bytes: bytes = b"%PDF-fake"):
    """Same pagination behavior as _opener_for, but also records every
    request's Authorization header (or its absence) so tests can assert on
    what the connector actually sent on the wire."""
    calls = {"n": 0}
    seen_auth_headers = []

    def _opener(request, timeout=60):
        calls["n"] += 1
        seen_auth_headers.append(request.headers.get("Authorization"))
        url = request.full_url
        if "api2.openreview.net/notes" in url:
            if calls["n"] == 1:
                return _FakeResp(payload_bytes)
            return _FakeResp(json.dumps({"notes": []}).encode("utf-8"))
        return _FakeResp(pdf_bytes)

    return _opener, seen_auth_headers


class OpenReviewFetchMockedTests(unittest.TestCase):
    def test_meta_mode_lists_notes_with_license_labels(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "ordata"
            args = openreview_fetch.build_parser().parse_args(
                ["--venue", "TEST.cc/2026/Conference", "--what", "meta", "--dest", str(dest)]
            )
            receipt_path = openreview_fetch.fetch(args, opener=_opener_for(ONE_LICENSED_NOTE))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "openreview")
            self.assertEqual(len(data["files"]), 1)
            meta_file = dest / data["files"][0]["path"]
            entries = json.loads(meta_file.read_text(encoding="utf-8"))
            self.assertEqual(entries[0]["license"], "CC-BY-4.0")

    def test_pdf_mode_fetches_license_clean_notes(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "ordata"
            args = openreview_fetch.build_parser().parse_args(
                ["--venue", "TEST.cc/2026/Conference", "--what", "pdf", "--dest", str(dest)]
            )
            receipt_path = openreview_fetch.fetch(args, opener=_opener_for(ONE_LICENSED_NOTE))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["license"], "CC-BY-4.0")
            self.assertEqual(len(data["files"]), 1)

    def test_pdf_mode_blocks_when_no_license_clean_notes(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "ordata"
            args = openreview_fetch.build_parser().parse_args(
                ["--venue", "TEST.cc/2026/Conference", "--what", "pdf", "--dest", str(dest)]
            )
            with self.assertRaises(rcpt.BlockedError):
                openreview_fetch.fetch(args, opener=_opener_for(ONE_UNLICENSED_NOTE))

    def test_no_token_sends_no_authorization_header_unchanged_default(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "ordata"
            args = openreview_fetch.build_parser().parse_args(
                ["--venue", "TEST.cc/2026/Conference", "--what", "meta", "--dest", str(dest)]
            )
            opener, seen_auth_headers = _recording_opener_for(ONE_LICENSED_NOTE)
            openreview_fetch.fetch(args, opener=opener)
            self.assertTrue(seen_auth_headers)
            self.assertTrue(all(h is None for h in seen_auth_headers))

    def test_cli_token_sends_bearer_authorization_header(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "ordata"
            args = openreview_fetch.build_parser().parse_args(
                [
                    "--venue", "TEST.cc/2026/Conference", "--what", "pdf",
                    "--dest", str(dest), "--token", "secret-cli-token",
                ]
            )
            opener, seen_auth_headers = _recording_opener_for(ONE_LICENSED_NOTE)
            openreview_fetch.fetch(args, opener=opener)
            self.assertTrue(seen_auth_headers)
            self.assertTrue(all(h == "Bearer secret-cli-token" for h in seen_auth_headers))

    def test_env_token_used_when_cli_flag_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "ordata"
            args = openreview_fetch.build_parser().parse_args(
                ["--venue", "TEST.cc/2026/Conference", "--what", "meta", "--dest", str(dest)]
            )
            opener, seen_auth_headers = _recording_opener_for(ONE_LICENSED_NOTE)
            with mock.patch.dict(os.environ, {"OPENREVIEW_TOKEN": "secret-env-token"}):
                openreview_fetch.fetch(args, opener=opener)
            self.assertTrue(all(h == "Bearer secret-env-token" for h in seen_auth_headers))

    def test_cli_token_wins_over_env_token(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "ordata"
            args = openreview_fetch.build_parser().parse_args(
                [
                    "--venue", "TEST.cc/2026/Conference", "--what", "meta",
                    "--dest", str(dest), "--token", "cli-wins",
                ]
            )
            opener, seen_auth_headers = _recording_opener_for(ONE_LICENSED_NOTE)
            with mock.patch.dict(os.environ, {"OPENREVIEW_TOKEN": "env-loses"}):
                openreview_fetch.fetch(args, opener=opener)
            self.assertTrue(all(h == "Bearer cli-wins" for h in seen_auth_headers))


if __name__ == "__main__":
    unittest.main()
