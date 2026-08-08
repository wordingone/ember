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
import urllib.error
import urllib.request
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

    def _interrupt_after_two_chunks(self, url, td):
        """Shared setup for the resume-state-mismatch variants below: produces a
        genuine in_progress .bulkstate.json + .partial pair (2 of 8 chunks
        committed) via the same real interruption mechanism the clean resume
        test uses, so every mismatch test below starts from a state file that
        really was written by fetch_chunked, not a hand-authored fixture."""
        dest_file = Path(td) / "out.bin"
        with self.assertRaises(ConnectionError):
            bulk.fetch_chunked(
                url, dest_file, budget_bytes=10_000, chunk_size=128,
                opener=flaky_opener(fail_after=2),
            )
        state_path = dest_file.with_name(dest_file.name + ".bulkstate.json")
        self.assertTrue(state_path.is_file())
        return dest_file, state_path

    def test_resume_schema_mismatch_is_refused(self):
        payload = _payload(1000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file, state_path = self._interrupt_after_two_chunks(url, td)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["schema"] = "some-other-schema-v1"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(bulk.ResumeStateMismatchError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)

    def test_resume_chunk_size_mismatch_is_refused(self):
        payload = _payload(1000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file, _ = self._interrupt_after_two_chunks(url, td)
            with self.assertRaises(bulk.ResumeStateMismatchError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=256)

    def test_resume_budget_bytes_mismatch_is_refused(self):
        payload = _payload(1000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file, _ = self._interrupt_after_two_chunks(url, td)
            with self.assertRaises(bulk.ResumeStateMismatchError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=20_000, chunk_size=128)

    def test_resume_status_not_in_progress_is_refused(self):
        payload = _payload(1000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file, state_path = self._interrupt_after_two_chunks(url, td)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["status"] = "complete"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(bulk.ResumeStateMismatchError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)

    def test_resume_state_exists_but_partial_missing_is_refused(self):
        payload = _payload(1000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file, state_path = self._interrupt_after_two_chunks(url, td)
            partial_path = dest_file.with_name(dest_file.name + ".partial")
            self.assertTrue(partial_path.is_file())
            partial_path.write_bytes(b"")  # simulate the .partial having vanished/been
            partial_path.unlink()  # replaced out from under a stale state file
            with self.assertRaises(bulk.ResumeStateMismatchError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)


class PartialFileSizeMismatchTests(ChunkedFetchServerTestCase):
    """PartialFileSizeMismatchError has two raise sites in chunked_download.py:
    (1) resume-time, comparing the .partial file's actual on-disk size against
    what the loaded state's chunk list sums to, and (2) post-loop, comparing
    the fully-assembled .partial size against total_bytes. Site (1) is
    directly reachable by mutating the .partial file's length between two
    invocations -- both directions (shorter and longer) are covered below.
    Site (2) is now provably unreachable via any network response once
    _fetch_one_chunk's resp_end bounds (resp_start <= resp_end <= min(end,
    resp_total-1), resp_total pinned equal across every chunk) hold: those
    invariants force `start` to advance by exactly one chunk's worth every
    time and never overshoot, so the loop can only ever exit with
    start == total_bytes, which makes final_size == total_bytes a proven
    identity rather than something worth asserting against a live server.
    It remains in the code as defense-in-depth against a future bookkeeping
    regression (and is exercised implicitly: it was the exact line that
    caught the pre-fix Content-Range exploit in ContentRangeBoundExploitTests'
    predecessor repro, before the bound check below made it unreachable)."""

    def test_resume_refused_when_partial_is_longer_than_state_expects(self):
        payload = _payload(1000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(ConnectionError):
                bulk.fetch_chunked(
                    url, dest_file, budget_bytes=10_000, chunk_size=128,
                    opener=flaky_opener(fail_after=2),
                )
            partial_path = dest_file.with_name(dest_file.name + ".partial")
            with partial_path.open("ab") as fh:
                fh.write(b"extra-bytes-nobody-receipted")
            with self.assertRaises(bulk.PartialFileSizeMismatchError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)

    def test_resume_refused_when_partial_is_shorter_than_state_expects(self):
        payload = _payload(1000)
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(ConnectionError):
                bulk.fetch_chunked(
                    url, dest_file, budget_bytes=10_000, chunk_size=128,
                    opener=flaky_opener(fail_after=2),
                )
            partial_path = dest_file.with_name(dest_file.name + ".partial")
            truncated = partial_path.read_bytes()[:-10]
            partial_path.write_bytes(truncated)
            with self.assertRaises(bulk.PartialFileSizeMismatchError):
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

    def test_range_support_dropped_mid_transfer_is_refused(self):
        """Server honours Range correctly for the first 2 chunks, then silently
        starts ignoring it (200 + full body) from the 3rd request on -- the
        same "detect and refuse rather than silently restart" contract must
        hold mid-transfer, not just on the very first request."""
        payload = _payload(1000)
        url, handler_cls = self._serve(payload, ignore_range_after=2)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.RangeNotSupportedError):
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)
            self.assertEqual(len(handler_cls.request_log), 3)
            # the two genuinely-honoured chunks are still safely committed and
            # resumable once the server starts behaving again
            state_path = dest_file.with_name(dest_file.name + ".bulkstate.json")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state["chunks"]), 2)


class ContentRangeBoundExploitTests(ChunkedFetchServerTestCase):
    """Permanent regression coverage for the review finding on 37a95be:
    _fetch_one_chunk trusted the server-supplied Content-Range `end` with no
    bound against either the client's own requested end or the server's own
    claimed total, so a hostile (or merely broken) server answering a small
    requested range with a much larger Content-Range caused an unbounded
    read+write before the (real, but too-late) whole-file size check refused
    it. Ported from the reviewer's read-only loopback repro
    (verify_content_range_bound.py) into the project's own fixture style."""

    def test_oversized_content_range_is_refused_before_any_byte_is_read(self):
        # Exact reviewer scenario: client requests a 128-byte chunk against a
        # 2000-byte budget; server claims Content-Range bytes 0-4999/2000 (a
        # total that is itself within budget, but an end 39x the requested
        # chunk size) and actually sends a 5000-byte body.
        url, handler_cls = self._serve(
            b"", hostile_content_range=(0, 4999, 2000)
        )
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.RangeNotSupportedError) as ctx:
                bulk.fetch_chunked(url, dest_file, budget_bytes=2000, chunk_size=128)
            self.assertIn("exceeds the requested end", str(ctx.exception))
            self.assertEqual(handler_cls.request_log, ["bytes=0-127"])
            # The whole point of the fix: zero bytes read into the body before
            # refusing, so no .partial is ever created at all.
            self.assertFalse(dest_file.with_name(dest_file.name + ".partial").exists())
            self.assertFalse(dest_file.with_name(dest_file.name + ".bulkstate.json").exists())

    def test_content_range_end_at_or_beyond_its_own_total_is_refused(self):
        # Internally-inconsistent Content-Range: end == total (must be < total
        # for a valid 0-indexed byte range: a 100-byte resource is bytes 0-99,
        # never 0-100), while still respecting the client's requested end
        # (127, from chunk_size=128) so this isolates ONLY the end-vs-total
        # invariant, not the end-vs-requested-end one above.
        url, _ = self._serve(b"", hostile_content_range=(0, 100, 100))
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.RangeNotSupportedError) as ctx:
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)
            self.assertIn("not less than its own reported total", str(ctx.exception))

    def test_inverted_content_range_is_refused(self):
        # end < start: nonsensical range, must never compute a negative
        # expected_len and fall through to a confusing length-mismatch error.
        # Isolated to the 2nd chunk (a real, honest first chunk establishes
        # total_bytes=1000 and advances start to 100) so resp_start=100 in the
        # hostile reply genuinely matches the request and doesn't instead trip
        # the "wrong start" check above.
        payload = _payload(1000)
        url, _ = self._serve(
            payload, hostile_content_range_after=1, hostile_content_range=(100, 40, 1000)
        )
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.RangeNotSupportedError) as ctx:
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=100)
            self.assertIn("before its own start", str(ctx.exception))


class ChunkFetchErrorTests(ChunkedFetchServerTestCase):
    def test_unexpected_http_status_is_refused(self):
        url, handler_cls = self._serve(b"irrelevant", force_status=500)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.ChunkFetchError) as ctx:
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)
            self.assertIn("500", str(ctx.exception))
            self.assertFalse(dest_file.with_name(dest_file.name + ".partial").exists())

    def test_416_range_not_satisfiable_is_refused(self):
        url, _ = self._serve(b"irrelevant", force_status=416)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.ChunkFetchError) as ctx:
                bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)
            self.assertIn("416", str(ctx.exception))


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

    def test_total_bytes_exactly_equal_to_budget_succeeds(self):
        # Boundary: total_bytes == budget_bytes must succeed (the check is a
        # strict >, not >=) -- only "way over budget" was covered before.
        payload = b"e" * 2000
        url, _ = self._serve(payload)
        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            result = bulk.fetch_chunked(url, dest_file, budget_bytes=2000, chunk_size=128)
            self.assertEqual(result.total_bytes, 2000)
            self.assertEqual(dest_file.read_bytes(), payload)


class DiskMarginTests(ChunkedFetchServerTestCase):
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

    def test_disk_margin_refusal_mid_transfer_after_some_chunks_committed(self):
        # Simulates a volume that fills up partway through a multi-chunk transfer:
        # plenty of free space for the pre-loop check and the first 2 chunks' own
        # per-chunk re-checks, then insufficient starting with the 3rd chunk. Must
        # surface as a clean DiskMarginError (not a raw OSError from write()/
        # fsync() several chunks later), and must leave the .partial+state
        # resumable at exactly the last durably-committed chunk.
        payload = _payload(1000)
        url, handler_cls = self._serve(payload)
        calls = {"n": 0}

        def _shrinking_free(_path):
            calls["n"] += 1
            # call 1 = pre-loop check (context="budget_bytes"); calls 2 and 3 =
            # the per-chunk re-checks for chunks 0 and 1.
            if calls["n"] <= 3:
                return _FakeUsage(total=10**12, used=0, free=10**12)
            return _FakeUsage(total=10**12, used=10**12 - 10, free=10)

        with tempfile.TemporaryDirectory() as td:
            dest_file = Path(td) / "out.bin"
            with self.assertRaises(bulk.DiskMarginError):
                bulk.fetch_chunked(
                    url, dest_file, budget_bytes=10_000, chunk_size=128,
                    disk_usage_fn=_shrinking_free,
                )
            state_path = dest_file.with_name(dest_file.name + ".bulkstate.json")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state["chunks"]), 2)
            partial_path = dest_file.with_name(dest_file.name + ".partial")
            self.assertEqual(partial_path.stat().st_size, 256)
            # The 3rd chunk was fetched over the network before its margin
            # re-check ran (the check guards the write, not the fetch) and is
            # correctly not reflected in the committed state.
            self.assertEqual(len(handler_cls.request_log), 3)

            # Resumable once space frees back up.
            result = bulk.fetch_chunked(url, dest_file, budget_bytes=10_000, chunk_size=128)
            self.assertTrue(result.resumed)
            self.assertEqual(dest_file.read_bytes(), payload)


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


class RetryPolicyTests(ChunkedFetchServerTestCase):
    def test_transient_5xx_retries_with_backoff_and_records_attempts(self):
        payload = _payload(300)
        url, _ = self._serve(payload)
        calls = []
        sleeps = []

        def opener(request, timeout=60):
            if len(calls) < 2:
                calls.append("503")
                raise urllib.error.HTTPError(
                    request.full_url, 503, "temporary", {}, None
                )
            calls.append("ok")
            return urllib.request.urlopen(request, timeout=timeout)

        with tempfile.TemporaryDirectory() as td:
            result = bulk.fetch_chunked(
                url,
                Path(td) / "out.bin",
                budget_bytes=10_000,
                chunk_size=128,
                max_retries=2,
                backoff_base_seconds=0.25,
                sleep_fn=sleeps.append,
                opener=opener,
            )

        self.assertEqual(calls[:2], ["503", "503"])
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(sleeps, [0.25, 0.5])
        self.assertEqual(result.retry_attempts, 2)
        self.assertEqual([e["status"] for e in result.retry_events], ["http_503", "http_503"])

    def test_exhausted_transient_retries_leave_no_initial_partial(self):
        payload = _payload(100)
        url, _ = self._serve(payload)
        calls = []

        def opener(request, timeout=60):
            calls.append(request)
            raise urllib.error.HTTPError(
                request.full_url, 503, "temporary", {}, None
            )

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "out.bin"
            with self.assertRaises(bulk.ChunkFetchError):
                bulk.fetch_chunked(
                    url,
                    dest,
                    budget_bytes=10_000,
                    chunk_size=128,
                    max_retries=2,
                    sleep_fn=lambda _seconds: None,
                    opener=opener,
                )
            self.assertEqual(len(calls), 3)
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_name(dest.name + ".partial").exists())
            self.assertFalse(dest.with_name(dest.name + ".bulkstate.json").exists())

    def test_terminal_http_status_is_never_retried(self):
        payload = _payload(100)
        url, _ = self._serve(payload)
        calls = []

        def opener(request, timeout=60):
            calls.append(request)
            raise urllib.error.HTTPError(
                request.full_url, 416, "range refused", {}, None
            )

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(bulk.ChunkFetchError):
                bulk.fetch_chunked(
                    url,
                    Path(td) / "out.bin",
                    budget_bytes=10_000,
                    chunk_size=128,
                    max_retries=5,
                    sleep_fn=lambda _seconds: None,
                    opener=opener,
                )
        self.assertEqual(len(calls), 1)

    def test_connection_reset_and_timeout_are_transient(self):
        payload = _payload(100)
        url, _ = self._serve(payload)

        for transient, expected_status in (
            (ConnectionResetError("reset"), "connection_reset"),
            (TimeoutError("timeout"), "timeout"),
        ):
            calls = {"n": 0}

            def opener(request, timeout=60, transient=transient):
                if calls["n"] == 0:
                    calls["n"] += 1
                    raise transient
                return urllib.request.urlopen(request, timeout=timeout)

            with tempfile.TemporaryDirectory() as td:
                result = bulk.fetch_chunked(
                    url,
                    Path(td) / "out.bin",
                    budget_bytes=10_000,
                    chunk_size=128,
                    max_retries=1,
                    backoff_base_seconds=0,
                    sleep_fn=lambda _seconds: None,
                    opener=opener,
                )
            self.assertEqual(result.retry_attempts, 1)
            self.assertEqual(result.retry_events[0]["status"], expected_status)

    def test_retry_bound_applies_per_chunk_not_across_the_transfer(self):
        payload = _payload(300)
        url, _ = self._serve(payload)
        failed_ranges = set()

        def opener(request, timeout=60):
            range_header = request.headers["Range"]
            if range_header not in failed_ranges:
                failed_ranges.add(range_header)
                raise urllib.error.HTTPError(
                    request.full_url, 503, "temporary", {}, None
                )
            return urllib.request.urlopen(request, timeout=timeout)

        with tempfile.TemporaryDirectory() as td:
            result = bulk.fetch_chunked(
                url,
                Path(td) / "out.bin",
                budget_bytes=10_000,
                chunk_size=128,
                max_retries=1,
                backoff_base_seconds=0,
                sleep_fn=lambda _seconds: None,
                opener=opener,
            )

        self.assertEqual(result.retry_attempts, 3)
        self.assertEqual([e["chunk_index"] for e in result.retry_events], [0, 1, 2])

    def test_retry_controls_reject_negative_or_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "out.bin"
            with self.assertRaises(rcpt.BlockedError):
                bulk.fetch_chunked(
                    "http://127.0.0.1:1/unused",
                    dest,
                    budget_bytes=10_000,
                    max_retries=-1,
                )
            with self.assertRaises(rcpt.BlockedError):
                bulk.fetch_chunked(
                    "http://127.0.0.1:1/unused",
                    dest,
                    budget_bytes=10_000,
                    backoff_base_seconds=float("nan"),
                )


if __name__ == "__main__":
    unittest.main()
