# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mocked test for arxiv_fetch.py -- no network. Fakes the Atom API + PDF fetch."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import arxiv_fetch
import receipt as rcpt

ATOM_CC = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>An Example CC Paper</title>
    <updated>2023-01-01T00:00:00Z</updated>
    <arxiv:license>http://creativecommons.org/licenses/by/4.0/</arxiv:license>
  </entry>
</feed>
"""

ATOM_PERPETUAL = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00002v1</id>
    <title>An Example Perpetual-License Paper</title>
    <updated>2023-01-02T00:00:00Z</updated>
    <arxiv:license>http://arxiv.org/licenses/nonexclusive-distrib/1.0/</arxiv:license>
  </entry>
</feed>
"""


ATOM_TWO_CC = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00003v1</id>
    <title>Second CC Paper</title>
    <updated>2023-01-03T00:00:00Z</updated>
    <arxiv:license>http://creativecommons.org/licenses/by/4.0/</arxiv:license>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2301.00004v1</id>
    <title>Third CC Paper</title>
    <updated>2023-01-04T00:00:00Z</updated>
    <arxiv:license>http://creativecommons.org/licenses/by/4.0/</arxiv:license>
  </entry>
</feed>
"""


class _FakeResp:
    def __init__(self, data: bytes, headers: dict = None, status: int = 200):
        self._buf = io.BytesIO(data)
        self.headers = headers or {}
        self.status = status

    def read(self, size=-1):
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener_for(atom_bytes: bytes, pdf_bytes: bytes = b"%PDF-fake-content"):
    def _opener(request, timeout=60):
        url = request.full_url
        if "export.arxiv.org/api/query" in url:
            return _FakeResp(atom_bytes)
        return _FakeResp(pdf_bytes)

    return _opener


def _opener_with_sizes(atom_bytes: bytes, sizes_by_id: dict, body: bytes = b"fake-tarball-bytes", body_by_id: dict = None):
    """Mocked opener for budget-walk tests: HEAD requests return Content-Length
    from sizes_by_id (keyed by arxiv id; a missing/None entry means "no
    Content-Length header", exercising the streamed running-budget fallback).
    GET requests return body_by_id[id] if given, else the shared `body`."""

    def _opener(request, timeout=60):
        url = request.full_url
        if "export.arxiv.org/api/query" in url:
            return _FakeResp(atom_bytes)
        arxiv_id = url.rstrip("/").rsplit("/", 1)[-1]
        stripped_id = arxiv_fetch._strip_version(arxiv_id)
        size = sizes_by_id.get(stripped_id)
        if request.get_method() == "HEAD":
            headers = {"Content-Length": str(size)} if size is not None else {}
            return _FakeResp(b"", headers=headers)
        get_body = (body_by_id or {}).get(stripped_id, body)
        return _FakeResp(get_body)

    return _opener


class ArxivFetchMockedTests(unittest.TestCase):
    def setUp(self):
        # Neutralize the real <=1req/3s politeness sleep for the test suite;
        # arxiv_fetch itself still sleeps in production use.
        patcher = patch.object(arxiv_fetch.time, "sleep", lambda *_a, **_kw: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_meta_mode_writes_receipt_with_per_paper_license_notes(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--ids", "2301.00001", "--what", "meta", "--dest", str(dest)]
            )
            receipt_path = arxiv_fetch.fetch(args, opener=_opener_for(ATOM_CC))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "arxiv")
            self.assertIn("2301.00001", data["notes"])
            self.assertEqual(len(data["files"]), 1)
            meta_file = dest / data["files"][0]["path"]
            entries = json.loads(meta_file.read_text(encoding="utf-8"))
            self.assertEqual(entries[0]["license"], "http://creativecommons.org/licenses/by/4.0/")

    def test_pdf_mode_downloads_only_cc_licensed_papers(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--ids", "2301.00001", "--what", "pdf", "--dest", str(dest)]
            )
            receipt_path = arxiv_fetch.fetch(args, opener=_opener_for(ATOM_CC))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["files"]), 1)
            self.assertTrue(data["license"].startswith("http://creativecommons.org"))

    def test_pdf_mode_blocks_when_all_papers_are_arxiv_perpetual(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--ids", "2301.00002", "--what", "pdf", "--dest", str(dest)]
            )
            with self.assertRaises(rcpt.BlockedError):
                arxiv_fetch.fetch(args, opener=_opener_for(ATOM_PERPETUAL))

    def test_pdf_mode_widened_filter_allows_perpetual_license_papers(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--ids", "2301.00002", "--what", "pdf", "--dest", str(dest), "--license-filter", "all"]
            )
            receipt_path = arxiv_fetch.fetch(args, opener=_opener_for(ATOM_PERPETUAL))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["files"]), 1)
            self.assertEqual(data["license"], arxiv_fetch.ARXIV_PERPETUAL_LABEL)

    def test_paper_list_reads_ids_skips_blank_and_comment_lines(self):
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("# harvested set\n2301.00001\n\n  \n# trailing comment\n", encoding="utf-8")
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--paper-list", str(list_path), "--what", "meta", "--dest", str(dest)]
            )
            receipt_path = arxiv_fetch.fetch(args, opener=_opener_for(ATOM_CC))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "arxiv")
            self.assertIn("paper-list:ids.txt", data["source_id"])
            self.assertIn("2301.00001", data["notes"])

    def test_paper_list_routes_through_query_by_ids(self):
        # same id-batching/query mechanism as --ids -- assert read_paper_list's
        # output feeds query_by_ids by checking the same license resolution
        # (arxiv:license Atom element) that only query_by_ids exercises.
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("2301.00002\n", encoding="utf-8")
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--paper-list", str(list_path), "--what", "pdf", "--dest", str(dest), "--license-filter", "all"]
            )
            receipt_path = arxiv_fetch.fetch(args, opener=_opener_for(ATOM_PERPETUAL))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["license"], arxiv_fetch.ARXIV_PERPETUAL_LABEL)

    def test_paper_list_and_ids_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("2301.00001\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                arxiv_fetch.build_parser().parse_args(
                    ["--paper-list", str(list_path), "--ids", "2301.00001"]
                )

    def test_paper_list_empty_file_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("# only comments\n\n", encoding="utf-8")
            with self.assertRaises(rcpt.BlockedError):
                arxiv_fetch.read_paper_list(list_path)

    def test_budget_bytes_stops_before_a_candidate_that_would_exceed_it(self):
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("2301.00003\n2301.00004\n", encoding="utf-8")
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--paper-list", str(list_path), "--what", "source", "--dest", str(dest), "--budget-bytes", "150"]
            )
            opener = _opener_with_sizes(ATOM_TWO_CC, {"2301.00003": 100, "2301.00004": 100})
            receipt_path = arxiv_fetch.fetch(args, opener=opener)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            # 100 fits under 150; 100+100=200 would exceed -- rank-fidelity stop
            # after the first candidate, no skip to a smaller later one.
            self.assertEqual(len(data["files"]), 1)
            self.assertIn("2301.00003", data["notes"])
            self.assertNotIn("2301.00004=", data["notes"])
            self.assertIn("selected=1", data["notes"])
            self.assertIn("budget_walk_manifest=", data["notes"])

    def test_budget_bytes_honors_paper_list_declared_order_not_api_response_order(self):
        with tempfile.TemporaryDirectory() as td:
            # declared order puts 2301.00004 FIRST -- API response order (fixed
            # in ATOM_TWO_CC) puts 2301.00003 first; the walk must follow the file.
            list_path = Path(td) / "ids.txt"
            list_path.write_text("2301.00004\n2301.00003\n", encoding="utf-8")
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--paper-list", str(list_path), "--what", "source", "--dest", str(dest), "--budget-bytes", "150"]
            )
            opener = _opener_with_sizes(ATOM_TWO_CC, {"2301.00003": 100, "2301.00004": 100})
            receipt_path = arxiv_fetch.fetch(args, opener=opener)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["files"]), 1)
            self.assertIn("2301.00004", data["notes"])
            self.assertNotIn("2301.00003=", data["notes"])

    def test_budget_bytes_writes_sidecar_walk_manifest_not_bloated_receipt_notes(self):
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("2301.00003\n2301.00004\n", encoding="utf-8")
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--paper-list", str(list_path), "--what", "source", "--dest", str(dest), "--budget-bytes", "10000"]
            )
            opener = _opener_with_sizes(ATOM_TWO_CC, {"2301.00003": 100, "2301.00004": 100})
            receipt_path = arxiv_fetch.fetch(args, opener=opener)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["files"]), 2)
            manifest_rel = data["notes"].split("budget_walk_manifest=")[1].strip()
            manifest_path = dest / manifest_rel
            self.assertTrue(manifest_path.exists())
            walk = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(walk["selected_count"], 2)
            self.assertEqual(len(walk["walk"]), 2)
            # bounded: receipt notes stays short regardless of candidate count
            self.assertLess(len(data["notes"]), 1000)

    def test_budget_bytes_requires_paper_list(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--ids", "2301.00001", "--what", "pdf", "--dest", str(dest), "--budget-bytes", "1000"]
            )
            with self.assertRaises(rcpt.BlockedError):
                arxiv_fetch.fetch(args, opener=_opener_for(ATOM_CC))

    def test_budget_bytes_unknown_size_streams_under_running_budget_check(self):
        # 2301.00003 has no discoverable Content-Length -- fail-closed rule:
        # stream it under a running budget check (max_bytes = remaining budget)
        # instead of stopping blind. The fake GET body is small enough to fit,
        # so it must be SELECTED (not skipped, not stopped) and the walk
        # continues on to the next candidate.
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("2301.00003\n2301.00004\n", encoding="utf-8")
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--paper-list", str(list_path), "--what", "source", "--dest", str(dest), "--budget-bytes", "10000"]
            )
            opener = _opener_with_sizes(ATOM_TWO_CC, {"2301.00004": 100}, body_by_id={"2301.00003": b"x" * 18})
            receipt_path = arxiv_fetch.fetch(args, opener=opener)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["files"]), 2)
            self.assertIn("selected=2 (via_head=1, via_stream=1)", data["notes"])
            manifest_rel = data["notes"].split("budget_walk_manifest=")[1].strip()
            walk = json.loads((dest / manifest_rel).read_text(encoding="utf-8"))
            first, second = walk["walk"]
            self.assertEqual(first["size_source"], "streamed")
            self.assertEqual(first["bytes"], 18)
            self.assertEqual(second["size_source"], "head")

    def test_budget_bytes_unknown_size_streamed_download_exceeding_budget_aborts_no_skip(self):
        # Same missing-Content-Length case, but now the streamed body itself
        # exceeds the remaining budget -- download_url must abort mid-stream
        # (DownloadTooLargeError) and the walk must STOP there, never skip
        # ahead to 2301.00004 even though it would fit on its own.
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("2301.00003\n2301.00004\n", encoding="utf-8")
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--paper-list", str(list_path), "--what", "source", "--dest", str(dest), "--budget-bytes", "10"]
            )
            opener = _opener_with_sizes(ATOM_TWO_CC, {"2301.00004": 5}, body_by_id={"2301.00003": b"x" * 500})
            with self.assertRaises(rcpt.BlockedError):
                arxiv_fetch.fetch(args, opener=opener)
            # no partial/leftover file for the aborted stream
            self.assertFalse(any((dest).glob("*2301.00003*")))

    def test_budget_bytes_streamed_candidate_not_redownloaded_in_fetch_loop(self):
        # A streamed-under-budget candidate is already on disk from the walk --
        # the main download loop must reuse that file, not re-request it (which
        # would also hit download_url's own collision check on the file it just wrote).
        # 2301.00003 streams at 18 bytes; the remaining budget (20-18=2) is too
        # small for 2301.00004's declared 50-byte size, so exactly one file is
        # selected -- letting this assert both "no re-download" and "no skip".
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("2301.00003\n2301.00004\n", encoding="utf-8")
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                ["--paper-list", str(list_path), "--what", "source", "--dest", str(dest), "--budget-bytes", "20"]
            )
            opener = _opener_with_sizes(ATOM_TWO_CC, {"2301.00004": 50}, body_by_id={"2301.00003": b"x" * 18})
            receipt_path = arxiv_fetch.fetch(args, opener=opener)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["files"]), 1)
            self.assertEqual(data["files"][0]["bytes"], 18)

    def test_license_override_fills_gap_when_live_check_is_unverified(self):
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("2301.00002\n", encoding="utf-8")
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                [
                    "--paper-list", str(list_path), "--what", "source", "--dest", str(dest),
                    "--license-filter", "all",
                    "--license-override", "http://creativecommons.org/licenses/by/4.0/",
                    "--license-override-evidence", "OAI-PMH bulk harvest <license> element, exact-SPDX match",
                ]
            )
            # ATOM_PERPETUAL's own arxiv:license is the arXiv perpetual label
            # (resolved, not UNVERIFIED) -- override must NOT touch a live check
            # that actually resolved to something.
            receipt_path = arxiv_fetch.fetch(args, opener=_opener_for(ATOM_PERPETUAL))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["license"], arxiv_fetch.ARXIV_PERPETUAL_LABEL)

    def test_license_override_applies_when_live_check_returns_unverified(self):
        atom_unverified = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00005v1</id>
    <title>No License Element Paper</title>
    <updated>2023-01-05T00:00:00Z</updated>
  </entry>
</feed>
"""
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "ids.txt"
            list_path.write_text("2301.00005\n", encoding="utf-8")
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                [
                    "--paper-list", str(list_path), "--what", "source", "--dest", str(dest),
                    "--license-filter", "all",
                    "--license-override", "http://creativecommons.org/licenses/by/4.0/",
                    "--license-override-evidence", "OAI-PMH bulk harvest <license> element, exact-SPDX match",
                ]
            )
            receipt_path = arxiv_fetch.fetch(args, opener=_opener_for(atom_unverified))
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(data["license"], "http://creativecommons.org/licenses/by/4.0/")
            self.assertIn("OAI-PMH bulk harvest", data["license_evidence"])
            # basis tag distinguishes override-filled from live-resolved admission --
            # a live-resolved CC-BY-4.0 paper would share the identical URL string,
            # so the (override)/(live) tag is the only thing telling them apart.
            self.assertIn("2301.00005v1=http://creativecommons.org/licenses/by/4.0/(override)", data["notes"])

    def test_license_override_requires_evidence_paired(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "arxivdata"
            args = arxiv_fetch.build_parser().parse_args(
                [
                    "--ids", "2301.00001", "--what", "pdf", "--dest", str(dest),
                    "--license-override", "http://creativecommons.org/licenses/by/4.0/",
                ]
            )
            with self.assertRaises(rcpt.BlockedError):
                arxiv_fetch.fetch(args, opener=_opener_for(ATOM_CC))

    def test_main_blocked_line_on_no_eligible_papers(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "arxivdata"
            argv = ["--ids", "2301.00002", "--what", "pdf", "--dest", str(dest)]
            args = arxiv_fetch.build_parser().parse_args(argv)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = rcpt.run_cli(lambda: arxiv_fetch.fetch(args, opener=_opener_for(ATOM_PERPETUAL)))
            self.assertEqual(code, 1)
            self.assertTrue(buf.getvalue().strip().startswith("BLOCKED"))


if __name__ == "__main__":
    unittest.main()
