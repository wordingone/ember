# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for bulk_fetch.py -- the CLI glue between chunked_download.py and the
shared receipt/manifest core. Uses the same local Range-server fixture as
test_chunked_download.py (no network); license gating and the run_cli
BLOCKED/RECEIPT contract are exercised the same way test_http_fetch.py
exercises http_fetch.py."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_fetch  # noqa: E402
import chunked_download as bulk  # noqa: E402
import receipt as rcpt  # noqa: E402
from _range_fixture import start_server, stop_server  # noqa: E402


def _payload(n: int) -> bytes:
    return bytes((i * 53 + 7) % 256 for i in range(n))


class BulkFetchServerTestCase(unittest.TestCase):
    def _serve(self, payload: bytes, **attrs):
        server, thread, url, handler_cls = start_server(payload, **attrs)
        self.addCleanup(stop_server, server, thread)
        return url, handler_cls


class ReceiptAndChunkManifestTests(BulkFetchServerTestCase):
    def test_fetch_with_supplied_license_writes_receipt_and_chunk_manifest(self):
        payload = _payload(1000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "bulkdata"
            args = bulk_fetch.build_parser().parse_args(
                [
                    url,
                    "--budget-bytes", "10000",
                    "--chunk-size-bytes", "128",
                    "--license", "CC-BY-SA-4.0",
                    "--license-evidence", "dump site footer states CC BY-SA 4.0",
                    "--dest", str(dest),
                ]
            )
            receipt_path = bulk_fetch.fetch(args)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))

            self.assertEqual(data["schema"], "corpus-connector-receipt-v1")
            self.assertEqual(data["source"], "http-bulk")
            self.assertEqual(data["license"], "CC-BY-SA-4.0")
            self.assertEqual(data["files"][0]["bytes"], len(payload))
            self.assertEqual(data["files"][0]["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertIn("chunk_manifest=", data["notes"])
            self.assertIn("resumed=no", data["notes"])
            self.assertEqual(data["retry_attempts"], 0)
            self.assertEqual(data["retry_events"], [])

            dest_filename = Path(data["files"][0]["path"]).name
            self.assertEqual((dest / dest_filename).read_bytes(), payload)

            manifests_dir = dest / "_manifests"
            chunk_manifest_paths = list(manifests_dir.glob("*.chunks.json"))
            self.assertEqual(len(chunk_manifest_paths), 1)
            chunk_data = json.loads(chunk_manifest_paths[0].read_text(encoding="utf-8"))
            self.assertEqual(chunk_data["schema"], "corpus-bulk-chunk-manifest-v1")
            self.assertEqual(chunk_data["total_bytes"], len(payload))
            self.assertEqual(len(chunk_data["chunks"]), -(-len(payload) // 128))
            self.assertEqual(chunk_data["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(chunk_data["retry_attempts"], 0)
            self.assertEqual(chunk_data["retry_events"], [])

            # manifest.jsonl compatibility row was appended too
            manifest_jsonl = (dest / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(manifest_jsonl), 1)
            row = json.loads(manifest_jsonl[0])
            self.assertEqual(row["license"], "CC-BY-SA-4.0")

    def test_transient_retry_fields_are_written_to_receipt(self):
        payload = _payload(100)
        url, _ = self._serve(payload)
        calls = {"n": 0}

        def opener(request, timeout=60):
            if calls["n"] == 0:
                calls["n"] += 1
                raise urllib.error.HTTPError(
                    request.full_url, 503, "temporary", {}, None
                )
            return urllib.request.urlopen(request, timeout=timeout)

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "bulkdata"
            args = bulk_fetch.build_parser().parse_args(
                [
                    url,
                    "--budget-bytes", "10000",
                    "--chunk-size-bytes", "128",
                    "--max-retries", "1",
                    "--retry-backoff-seconds", "0",
                    "--allow-unverified-license",
                    "--dest", str(dest),
                ]
            )
            receipt_path = bulk_fetch.fetch(args, opener=opener)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))

        self.assertEqual(data["retry_attempts"], 1)
        self.assertEqual(data["retry_events"], [{"attempt": 1, "chunk_index": 0, "status": "http_503"}])

    def test_fetch_without_license_is_unverified_and_blocked_by_default(self):
        payload = _payload(200)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "bulkdata"
            args = bulk_fetch.build_parser().parse_args(
                [url, "--budget-bytes", "10000", "--dest", str(dest)]
            )
            with self.assertRaises(rcpt.UnverifiedLicenseError):
                bulk_fetch.fetch(args)

    def test_fetch_without_license_allowed_when_flagged(self):
        payload = _payload(200)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "bulkdata"
            args = bulk_fetch.build_parser().parse_args(
                [url, "--budget-bytes", "10000", "--dest", str(dest), "--allow-unverified-license"]
            )
            receipt_path = bulk_fetch.fetch(args)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["license"], rcpt.UNVERIFIED)

    def test_license_and_evidence_must_be_supplied_together(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "bulkdata"
            args = bulk_fetch.build_parser().parse_args(
                [
                    "http://127.0.0.1:1/unused",
                    "--budget-bytes", "10000",
                    "--license", "CC0-1.0",
                    "--dest", str(dest),
                ]
            )
            with self.assertRaises(rcpt.BlockedError):
                bulk_fetch.fetch(args)


class StreamingTransportTests(BulkFetchServerTestCase):
    """--transport streaming routes through chunked_download.fetch_streaming
    instead of fetch_chunked; --transport range (the default, unspecified)
    stays on the original resumable path -- both asserted here so a
    regression in the branch itself (not just fetch_streaming in isolation)
    would be caught."""

    def test_transport_streaming_writes_receipt_with_streaming_notes(self):
        payload = _payload(2000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "bulkdata"
            args = bulk_fetch.build_parser().parse_args(
                [
                    url,
                    "--budget-bytes", "10000",
                    "--transport", "streaming",
                    "--allow-unverified-license",
                    "--dest", str(dest),
                ]
            )
            receipt_path = bulk_fetch.fetch(args)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))

            self.assertEqual(data["files"][0]["bytes"], len(payload))
            self.assertEqual(data["files"][0]["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertIn("streaming (non-Range)", data["notes"])
            self.assertIn("chunk_manifest=", data["notes"])

            dest_filename = Path(data["files"][0]["path"]).name
            self.assertEqual((dest / dest_filename).read_bytes(), payload)

            manifests_dir = dest / "_manifests"
            chunk_manifest_paths = list(manifests_dir.glob("*.chunks.json"))
            self.assertEqual(len(chunk_manifest_paths), 1)
            chunk_data = json.loads(chunk_manifest_paths[0].read_text(encoding="utf-8"))
            self.assertEqual(chunk_data["chunks"], [])
            self.assertEqual(chunk_data["sha256"], hashlib.sha256(payload).hexdigest())

    def test_transport_omitted_defaults_to_range_unchanged(self):
        payload = _payload(1000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "bulkdata"
            args = bulk_fetch.build_parser().parse_args(
                [
                    url,
                    "--budget-bytes", "10000",
                    "--chunk-size-bytes", "128",
                    "--allow-unverified-license",
                    "--dest", str(dest),
                ]
            )
            self.assertEqual(args.transport, "range")
            receipt_path = bulk_fetch.fetch(args)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertIn("resumable chunked-bulk transfer", data["notes"])
            self.assertNotIn("streaming (non-Range)", data["notes"])

    def test_transport_streaming_still_enforces_budget(self):
        payload = _payload(5000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "bulkdata"
            args = bulk_fetch.build_parser().parse_args(
                [
                    url,
                    "--budget-bytes", "1000",
                    "--transport", "streaming",
                    "--allow-unverified-license",
                    "--dest", str(dest),
                ]
            )
            with self.assertRaises(bulk.BudgetExceededError):
                bulk_fetch.fetch(args)


class RunCliIntegrationTests(BulkFetchServerTestCase):
    """Exercises the full main()-shaped path through rcpt.run_cli, matching
    the BLOCKED/RECEIPT single-line contract every connector CLI honors."""

    def _capture(self, fn):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rcpt.run_cli(fn)
        return code, buf.getvalue().strip()

    def test_budget_exceeded_surfaces_as_blocked_line(self):
        payload = b"a" * 5000
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "bulkdata"
            args = bulk_fetch.build_parser().parse_args(
                [
                    url, "--budget-bytes", "1000", "--chunk-size-bytes", "128",
                    "--allow-unverified-license", "--dest", str(dest),
                ]
            )
            code, out = self._capture(lambda: bulk_fetch.fetch(args))
            self.assertEqual(code, 1)
            self.assertTrue(out.startswith("BLOCKED"))
            self.assertIn("budget", out.lower())

    def test_dest_collision_is_blocked(self):
        payload = _payload(50)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "bulkdata"
            args = bulk_fetch.build_parser().parse_args(
                [
                    url, "--budget-bytes", "10000", "--chunk-size-bytes", "16",
                    "--allow-unverified-license", "--dest", str(dest),
                ]
            )
            receipt_path = bulk_fetch.fetch(args)
            self.assertTrue(receipt_path.is_file())

            code, out = self._capture(lambda: bulk_fetch.fetch(args))
            self.assertEqual(code, 1)
            self.assertTrue(out.startswith("BLOCKED"))


if __name__ == "__main__":
    unittest.main()
