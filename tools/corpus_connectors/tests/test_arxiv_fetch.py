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


class _FakeResp:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

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
