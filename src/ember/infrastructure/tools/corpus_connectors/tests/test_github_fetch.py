# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mocked tests for github_fetch.py -- no real network. Fakes urlopen via a
URL-dispatching fake opener (search API pages + per-repo tarball downloads)."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import github_fetch
from tools.corpus_connectors import receipt as rcpt
import spdx_gate


class _FakeResp:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, size=-1):
        return self._buf.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _search_item(full_name, stars, size_kb, spdx_id=None, default_branch="main"):
    license_obj = {"spdx_id": spdx_id} if spdx_id is not None else None
    return {
        "full_name": full_name,
        "html_url": f"https://github.com/{full_name}",
        "stargazers_count": stars,
        "size": size_kb,
        "default_branch": default_branch,
        "license": license_obj,
    }


class _DispatchOpener:
    """Fake opener routing GitHub search-API pages and tarball downloads by
    URL, recording every URL it was asked to open (so a test can assert a
    below-budget-cutoff repo was never even requested)."""

    def __init__(self, search_pages, tarballs):
        self._search_pages = search_pages  # dict: page number -> payload
        self._tarballs = tarballs  # dict: url -> bytes
        self.requested_urls = []

    def __call__(self, request, timeout=60):
        url = request.full_url
        self.requested_urls.append(url)
        if "/search/repositories" in url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            page = int(qs.get("page", ["1"])[0])
            payload = self._search_pages.get(page, {"items": []})
            return _FakeResp(json.dumps(payload).encode("utf-8"))
        if url in self._tarballs:
            return _FakeResp(self._tarballs[url])
        raise AssertionError(f"unexpected URL requested: {url}")


class GithubFetchMockedTests(unittest.TestCase):
    def test_deterministic_order_license_filter_and_budget_stop(self):
        items = [
            _search_item("owner/high-star-no-license", 900, size_kb=10, spdx_id=None),
            _search_item("owner/high-star-noassertion", 800, size_kb=10, spdx_id="NOASSERTION"),
            _search_item("owner/high-star-gpl", 700, size_kb=10, spdx_id="GPL-3.0"),
            _search_item("owner/bbb-tie", 500, size_kb=100, spdx_id="MIT"),
            _search_item("owner/aaa-tie", 500, size_kb=100, spdx_id="MIT"),
            _search_item("owner/low-star-too-big", 100, size_kb=1_000_000, spdx_id="Apache-2.0"),
        ]
        gzip_magic = b"\x1f\x8b" + b"x" * 30
        tarballs = {
            "https://github.com/owner/aaa-tie/archive/refs/heads/main.tar.gz": gzip_magic + b"AAA",
            "https://github.com/owner/bbb-tie/archive/refs/heads/main.tar.gz": gzip_magic + b"BBB",
        }
        opener = _DispatchOpener({1: {"items": items}}, tarballs)
        budget = (100 * 1024) * 2  # exactly two tied 100KB repos, nothing more

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "gh"
            args = github_fetch.build_parser().parse_args(
                ["cuda", "--budget-bytes", str(budget), "--dest", str(dest)]
            )
            receipt_path = github_fetch.fetch(args, opener=opener)
            data = json.loads(receipt_path.read_text(encoding="utf-8"))

            self.assertEqual(data["source"], "github")
            self.assertEqual(len(data["files"]), 2)
            notes = json.loads(data["notes"])
            selected_names = [r["full_name"] for r in notes["selected"]]
            self.assertEqual(selected_names, ["owner/aaa-tie", "owner/bbb-tie"])  # star tie broken by name
            self.assertEqual(notes["excluded_for_license"], 3)
            self.assertEqual(data["license"], "MIT")

        # the too-big, lowest-ranked repo must never even be requested
        self.assertFalse(any("low-star-too-big" in u for u in opener.requested_urls))

    def test_no_eligible_repos_is_blocked(self):
        items = [
            _search_item("owner/no-license", 500, size_kb=10, spdx_id=None),
            _search_item("owner/bad-license", 400, size_kb=10, spdx_id="GPL-3.0"),
        ]
        opener = _DispatchOpener({1: {"items": items}}, {})
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "gh"
            args = github_fetch.build_parser().parse_args(
                ["cuda", "--budget-bytes", str(10 * 1024 * 1024), "--dest", str(dest)]
            )
            with self.assertRaises(rcpt.BlockedError):
                github_fetch.fetch(args, opener=opener)

    def test_pagination_stops_when_page_short_of_per_page(self):
        page1 = [_search_item(f"owner/repo{i}", 100 - i, size_kb=1, spdx_id="MIT") for i in range(2)]
        page2 = [_search_item("owner/repo-last", 50, size_kb=1, spdx_id="MIT")]
        opener = _DispatchOpener({1: {"items": page1}, 2: {"items": page2}}, {})
        items = github_fetch._collect_candidates("cuda", max_candidates=50, per_page=2, token=None, opener=opener)
        self.assertEqual(len(items), 3)
        # page 3 must never be requested: only two search calls made
        search_calls = [u for u in opener.requested_urls if "/search/repositories" in u]
        self.assertEqual(len(search_calls), 2)

    def test_content_type_mismatch_is_blocked_and_cleans_up(self):
        items = [_search_item("owner/soft-404", 500, size_kb=10, spdx_id="MIT")]
        # server answers the .tar.gz URL with an HTML error page instead of gzip bytes
        tarballs = {
            "https://github.com/owner/soft-404/archive/refs/heads/main.tar.gz": b"<html>not found</html>",
        }
        opener = _DispatchOpener({1: {"items": items}}, tarballs)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "gh"
            args = github_fetch.build_parser().parse_args(
                ["cuda", "--budget-bytes", str(10 * 1024 * 1024), "--dest", str(dest)]
            )
            with self.assertRaises(rcpt.ContentTypeMismatchError):
                github_fetch.fetch(args, opener=opener)
            self.assertFalse((dest / "owner-soft-404.tar.gz").exists())

    def test_admission_authority_is_bound_live_not_copied(self):
        """github_fetch.py must hold no license identifiers of its own -- it
        reads spdx_gate.allowed_licenses() at call time, so widening/narrowing
        that live authority set moves this connector's admission decision
        with no edit here. Proven by monkeypatching the authority and
        observing the connector's own behavior flip accordingly."""
        self.assertFalse(
            hasattr(github_fetch, "ALLOWED_LICENSES"),
            "github_fetch.py must not hold its own copy of the admission allow-list",
        )

        items = [
            _search_item("owner/real-world-mit", 100, size_kb=10, spdx_id="MIT"),
            _search_item("owner/custom-license", 50, size_kb=10, spdx_id="FAKE-LICENSE-1.0"),
        ]
        tarballs = {
            "https://github.com/owner/custom-license/archive/refs/heads/main.tar.gz": b"\x1f\x8bxx" + b"CUSTOM",
        }
        opener = _DispatchOpener({1: {"items": items}}, tarballs)

        original = spdx_gate.allowed_licenses
        spdx_gate.allowed_licenses = lambda: frozenset({"FAKE-LICENSE-1.0"})  # excludes MIT, admits the fake one
        try:
            with tempfile.TemporaryDirectory() as td:
                dest = Path(td) / "gh"
                args = github_fetch.build_parser().parse_args(
                    ["cuda", "--budget-bytes", str(10 * 1024 * 1024), "--dest", str(dest)]
                )
                receipt_path = github_fetch.fetch(args, opener=opener)
                data = json.loads(receipt_path.read_text(encoding="utf-8"))
                notes = json.loads(data["notes"])
                selected_names = [r["full_name"] for r in notes["selected"]]
                self.assertEqual(selected_names, ["owner/custom-license"])
                self.assertEqual(data["license"], "FAKE-LICENSE-1.0")
        finally:
            spdx_gate.allowed_licenses = original


if __name__ == "__main__":
    unittest.main()
