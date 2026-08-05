# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production-shaped tests for chunked_download.py against a real local
HTTP/1.1 Range server bound to 127.0.0.1 (see _range_fixture.py) -- no
external network. Covers: clean chunked fetch, resume after interruption
without refetching completed bytes, Range-unsupported refusal, digest
mismatch refusal (whole-file and corrupted-resume variants), budget-exceeded
refusal, and disk-margin refusal, plus a few extra fail-closed edges
(ETag flip, total-size flip, resume/URL mismatch, orphaned partial)."""
from __future__ import annotations

import collections
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chunked_download as bulk  # noqa: E402
import receipt as rcpt  # noqa: E402
from _range_fixture import flaky_opener, start_server, stop_server  # noqa: E402

_FakeUsage = collections.namedtuple("usage", ["total", "used", "free"])


def _payload(n: int) -> bytes:
    return bytes((i * 37 + 11) % 256 for i in range(n))


class ChunkedFetchServerTestCase(unittest.TestCase):
    """Base class: spins up one fixture server per test, always torn down."""

    def _serve(self, payload: bytes, **attrs):
        server, thread, url, handler_cls = start_server(payload, **attrs)
        self.addCleanup(stop_server, server, thread)
        return url, handler_cls


class CleanChunkedFetchTests(ChunkedFetchServerTestCase):
    def test_clean_chunked_fetch_multiple_chunks(self):
        payload = _payload(1000)
        url, handler_cls = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            result = bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)

            self.assertEqual(dest_file.read_bytes(), payload)
            self.assertEqual(result.sha256, hashlib.sha256(payload).hexdigest())
            self.assertEqual(result.total_bytes, len(payload))
            self.assertFalse(result.resumed)

            expected_chunk_count = -(-len(payload) // 128)  # ceil div
            self.assertEqual(len(result.chunks), expected_chunk_count)

            covered = 0
            for i, c in enumerate(result.chunks):
                self.assertEqual(c.index, i)
                self.assertEqual(c.start, covered)
                self.assertEqual(c.sha256, hashlib.sha256(payload[c.start : c.end + 1]).hexdigest())
                covered = c.end + 1
            self.assertEqual(covered, len(payload))

            # sidecars are cleaned up on success
            self.assertFalse(dest_file.with_name(dest_file.name + ".partial").exists())
            self.assertFalse(dest_file.with_name(dest_file.name + ".bulkstate.json").exists())

    def test_clean_fetch_with_matching_expected_sha256(self):
        payload = _payload(300)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            result = bulk.fetch_chunked(
                url, dest_file, budget_bytes=10_000, chunk_size=64,
                expected_sha256=hashlib.sha256(payload).hexdigest(),
            )
            self.assertEqual(dest_file.read_bytes(), payload)


class ResumeTests(ChunkedFetchServerTestCase):
    def test_resume_after_interruption_does_not_refetch_completed_chunks(self):
        payload = _payload(1000)  # 8 chunks of 128 (last one 104 bytes)
        url, handler_cls = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"

            with self.assertRaises(ConnectionError):
                bulk.fetch_chunked(
                    url, dest_file, budget_bytes=10_000, chunk_size=128,
                    opener=flaky_opener(fail_after=2),
                )

            state_path = dest_file.with_name(dest_file.name + ".bulkstate.json")
            self.assertTrue(state_path.is_file())
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state["chunks"]), 2)
            self.assertEqual(len(handler_cls.request_log), 2)

            result = bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)

            self.assertTrue(result.resumed)
            self.assertEqual(dest_file.read_bytes(), payload)
            self.assertEqual(result.sha256, hashlib.sha256(payload).hexdigest())
            self.assertFalse(state_path.exists())

            total_chunks = -(-len(payload) // 128)
            self.assertEqual(len(handler_cls.request_log), total_chunks)
            # The two chunks completed before interruption must never be re-requested.
            self.assertEqual(handler_cls.request_log[0], "bytes=0-127")
            self.assertEqual(handler_cls.request_log[1], "bytes=128-255")
            self.assertEqual(handler_cls.request_log[2], "bytes=256-383")

    def test_resume_with_corrupted_partial_bytes_is_refused(self):
        payload = _payload(1000)
        url, handler_cls = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(ConnectionError):
                bulk.fetch_chunked(
                    url, dest_file, budget_bytes=10_000, chunk_size=128,
                    opener=flaky_opener(fail_after=2),
                )

            partial_path = dest_file.with_name(dest_file.name + ".partial")
            data = bytearray(partial_path.read_bytes())
            data[0] ^= 0xFF
            partial_path.write_bytes(bytes(data))

            with self.assertRaises(bulk.ChunkDigestMismatchError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)

    def test_resume_url_mismatch_is_refused(self):
        payload = _payload(500)
        url, handler_cls = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(ConnectionError):
                bulk.fetch_chunked(
                    url, dest_file, budget_bytes=10_000, chunk_size=128,
                    opener=flaky_opener(fail_after=1),
                )
            with self.assertRaises(bulk.ResumeStateMismatchError):
                bulk.fetch_chunked(url + "?different=1", dest_file, budget_bytes=10_000, chunk_size=128)

    def test_orphaned_partial_without_state_is_refused(self):
        payload = _payload(500)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            partial_path = dest_file.with_name(dest_file.name + ".partial")
            partial_path.write_bytes(b"leftover-from-somewhere")
            with self.assertRaises(bulk.ResumeStateMismatchError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)


class RangeUnsupportedTests(ChunkedFetchServerTestCase):
    def test_range_unsupported_is_refused_and_writes_nothing(self):
        payload = b"x" * 500
        url, _ = self._serve(payload, ignore_range=True)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.RangeNotSupportedError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)
            self.assertFalse(dest_file.exists())
            self.assertFalse(dest_file.with_name(dest_file.name + ".partial").exists())
            self.assertFalse(dest_file.with_name(dest_file.name + ".bulkstate.json").exists())


class DigestMismatchTests(ChunkedFetchServerTestCase):
    def test_whole_file_sha256_mismatch_is_refused(self):
        payload = _payload(500)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.WholeFileDigestMismatchError):
                bulk.fetch_chunked(
                    url, dest_file, budget_bytes=10_000, chunk_size=128, expected_sha256="0" * 64
                )
            self.assertFalse(dest_file.exists())
            self.assertFalse(dest_file.with_name(dest_file.name + ".partial").exists())
            self.assertFalse(dest_file.with_name(dest_file.name + ".bulkstate.json").exists())


class BudgetExceededTests(ChunkedFetchServerTestCase):
    def test_budget_exceeded_is_refused_before_any_bytes_written(self):
        payload = b"z" * 5000
        url, handler_cls = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.BudgetExceededError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=1000, chunk_size=128)
            self.assertFalse(dest_file.with_name(dest_file.name + ".partial").exists())
            self.assertFalse(dest_file.exists())
            # Exactly one request (chunk 0) was needed to learn the remote size.
            self.assertEqual(len(handler_cls.request_log), 1)


class DiskMarginTests(unittest.TestCase):
    def test_disk_margin_refusal_happens_before_any_network_call(self):
        def _tiny_free(_path):
            return _FakeUsage(total=10**12, used=10**12 - 100, free=100)

        def _opener_must_not_be_called(request, timeout=60):
            raise AssertionError("network call made despite insufficient disk margin")

        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.DiskMarginError):
                bulk.fetch_chunked(
                    "http://127.0.0.1:1/unused", dest_file,
                    budget_bytes=1_000_000, chunk_size=128,
                    disk_usage_fn=_tiny_free, opener=_opener_must_not_be_called,
                )

    def test_disk_margin_sufficient_allows_network_call(self):
        # Sanity check on the seam itself: a generous fake free-space value must not
        # block the transfer (proves the refusal above is about the margin, not a
        # broken seam).
        def _huge_free(_path):
            return _FakeUsage(total=10**15, used=0, free=10**15)

        payload = b"ok" * 10
        server_url_holder = {}

        def _run():
            from _range_fixture import start_server, stop_server

            server, thread, url, _ = start_server(payload)
            try:
                with tempfile.TemporaryDirectory() as td:
                    dest_file = Path(td) / "out.bin"
                    result = bulk.fetch_chunked(
                        url, dest_file, budget_bytes=10_000, chunk_size=8, disk_usage_fn=_huge_free
                    )
                    self.assertEqual(dest_file.read_bytes(), payload)
                    self.assertEqual(result.total_bytes, len(payload))
            finally:
                stop_server(server, thread)

        _run()


class RemoteIdentityChangedTests(ChunkedFetchServerTestCase):
    def test_etag_flip_mid_transfer_is_refused(self):
        payload = _payload(1000)
        url, _ = self._serve(payload, flip_etag_after=1)  # flips starting on request 2
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.RemoteIdentityChangedError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)

    def test_total_size_change_mid_transfer_is_refused(self):
        payload = _payload(1000)
        shorter = _payload(400)
        url, _ = self._serve(payload, flip_payload_after=1, flipped_payload=shorter)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.RemoteIdentityChangedError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)


class TruncatedChunkTests(ChunkedFetchServerTestCase):
    def test_truncated_final_chunk_is_refused(self):
        payload = _payload(300)  # chunk_size=128 -> chunks of 128,128,44 (final)
        url, handler_cls = self._serve(payload, truncate_last_n_bytes=10)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.ChunkLengthMismatchError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)
            # The two full, non-final chunks were committed; the truncated final
            # chunk was not written to the partial file.
            partial_path = dest_file.with_name(dest_file.name + ".partial")
            self.assertEqual(partial_path.stat().st_size, 256)


class ContentRangeParsingTests(unittest.TestCase):
    def test_missing_content_range_is_range_not_supported(self):
        with self.assertRaises(bulk.RangeNotSupportedError):
            bulk._parse_content_range(None)

    def test_unknown_total_is_range_not_supported(self):
        with self.assertRaises(bulk.RangeNotSupportedError):
            bulk._parse_content_range("bytes 0-99/*")

    def test_well_formed_header_parses(self):
        self.assertEqual(bulk._parse_content_range("bytes 0-99/500"), (0, 99, 500))


if __name__ == "__main__":
    unittest.main()
