# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Mocked tests for lean_fetch.py -- no real network. Verifies the
manifest-order partition split is disjoint and exhaustive, matching the
constraint (relayed by the research lead) that domain A train-1 and domain G
train-2's ProofNet slots must never pull identical content."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lean_fetch
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


REPO = "hoskinson-center/proofnet"
SHA = "deadbeef" * 5  # 40 hex chars, fake but sha-shaped
TREE_FILES = [
    {"path": "src/a.lean", "type": "blob", "size": 10},
    {"path": "src/b.lean", "type": "blob", "size": 10},
    {"path": "src/c.lean", "type": "blob", "size": 10},
    {"path": "src/d.lean", "type": "blob", "size": 10},
    {"path": "src/e.lean", "type": "blob", "size": 10},
    {"path": "README.md", "type": "blob", "size": 5},
    {"path": "src", "type": "tree"},  # a directory entry -- must be excluded, not counted as a file
]


class _DispatchOpener:
    def __init__(self):
        self.requested_urls = []

    def __call__(self, request, timeout=60):
        url = request.full_url
        self.requested_urls.append(url)
        if url == f"https://api.github.com/repos/{REPO}":
            return _FakeResp(json.dumps({"default_branch": "master"}).encode("utf-8"))
        if url == f"https://api.github.com/repos/{REPO}/commits/master":
            return _FakeResp(json.dumps({"sha": SHA}).encode("utf-8"))
        if url == f"https://api.github.com/repos/{REPO}/git/trees/{SHA}?recursive=1":
            return _FakeResp(json.dumps({"tree": TREE_FILES, "truncated": False}).encode("utf-8"))
        if url.startswith(f"https://raw.githubusercontent.com/{REPO}/{SHA}/"):
            return _FakeResp(b"lean file contents for " + url.encode("utf-8"))
        raise AssertionError(f"unexpected URL requested: {url}")


def _fetched_paths(receipt_path: Path) -> list:
    data = json.loads(receipt_path.read_text(encoding="utf-8"))
    return sorted(f["path"] for f in data["files"])


class LeanFetchDisjointTests(unittest.TestCase):
    def test_two_partitions_are_disjoint_and_exhaustive(self):
        with tempfile.TemporaryDirectory() as td:
            dest0 = Path(td) / "p0"
            args0 = lean_fetch.build_parser().parse_args(
                [
                    REPO, "--partition-count", "2", "--partition-index", "0",
                    "--license", "MIT", "--license-evidence", "test",
                    "--dest", str(dest0),
                ]
            )
            receipt0 = lean_fetch.fetch(args0, opener=_DispatchOpener())
            paths0 = _fetched_paths(receipt0)

            dest1 = Path(td) / "p1"
            args1 = lean_fetch.build_parser().parse_args(
                [
                    REPO, "--partition-count", "2", "--partition-index", "1",
                    "--license", "MIT", "--license-evidence", "test",
                    "--dest", str(dest1),
                ]
            )
            receipt1 = lean_fetch.fetch(args1, opener=_DispatchOpener())
            paths1 = _fetched_paths(receipt1)

            self.assertEqual(set(paths0) & set(paths1), set())
            all_blob_paths = sorted(item["path"] for item in TREE_FILES if item["type"] == "blob")
            self.assertEqual(sorted(paths0 + paths1), all_blob_paths)

    def test_directory_entries_excluded_from_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "p0"
            args = lean_fetch.build_parser().parse_args(
                [
                    REPO, "--partition-count", "1", "--partition-index", "0",
                    "--license", "MIT", "--license-evidence", "test",
                    "--dest", str(dest),
                ]
            )
            receipt_path = lean_fetch.fetch(args, opener=_DispatchOpener())
            paths = _fetched_paths(receipt_path)
            self.assertNotIn("src", paths)
            self.assertEqual(len(paths), 6)  # all blobs, single partition

    def test_partition_index_out_of_range_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "p0"
            args = lean_fetch.build_parser().parse_args(
                [
                    REPO, "--partition-count", "2", "--partition-index", "2",
                    "--license", "MIT", "--license-evidence", "test",
                    "--dest", str(dest),
                ]
            )
            with self.assertRaises(rcpt.BlockedError):
                lean_fetch.fetch(args, opener=_DispatchOpener())

    def test_license_and_evidence_must_be_supplied_together(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "p0"
            args = lean_fetch.build_parser().parse_args(
                [REPO, "--license", "MIT", "--dest", str(dest)]
            )
            with self.assertRaises(rcpt.BlockedError):
                lean_fetch.fetch(args, opener=_DispatchOpener())

    def test_notes_stays_bounded_and_references_a_sibling_file_manifest(self):
        """receipt.notes must never embed the full per-file list inline --
        receipt.py's to_manifest_row() copies notes into every manifest.jsonl
        row (one row per file), so an inline per-file list duplicates itself
        once per row (O(n^2) growth). The full per-file record must exist
        exactly once, in a sibling _manifests/*.files.json, referenced from
        notes by relative path."""
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "p0"
            args = lean_fetch.build_parser().parse_args(
                [
                    REPO, "--partition-count", "1", "--partition-index", "0",
                    "--license", "MIT", "--license-evidence", "test",
                    "--dest", str(dest),
                ]
            )
            receipt_path = lean_fetch.fetch(args, opener=_DispatchOpener())
            data = json.loads(receipt_path.read_text(encoding="utf-8"))

            self.assertNotIn("declared_size_bytes", data["notes"])
            self.assertNotIn('"files"', data["notes"])
            self.assertIn("file_manifest=", data["notes"])
            self.assertLess(len(data["notes"]), 400)

            manifests_dir = dest / "_manifests"
            file_manifest_paths = list(manifests_dir.glob("*.files.json"))
            self.assertEqual(len(file_manifest_paths), 1)
            file_manifest = json.loads(file_manifest_paths[0].read_text(encoding="utf-8"))
            self.assertEqual(file_manifest["files_fetched"], 6)
            self.assertEqual(len(file_manifest["files"]), 6)
            self.assertEqual(
                {f["path"] for f in file_manifest["files"]},
                {item["path"] for item in TREE_FILES if item["type"] == "blob"},
            )

    def test_manifest_jsonl_row_size_does_not_grow_with_file_count(self):
        """The regression this fixes: before this change, every
        manifest.jsonl row's human_provenance_basis carried the full
        per-file list (one growing blob duplicated once per row, O(n^2)
        total size). After the fix, every row's human_provenance_basis is
        bounded regardless of how many files the fetch contained -- confirmed
        here by fetching partitions of different sizes (1 file vs 6 files)
        and checking the per-row basis length does not scale with file
        count."""
        with tempfile.TemporaryDirectory() as td:
            small_dest = Path(td) / "small"
            small_args = lean_fetch.build_parser().parse_args(
                [
                    REPO, "--partition-count", "6", "--partition-index", "0",
                    "--license", "MIT", "--license-evidence", "test",
                    "--dest", str(small_dest),
                ]
            )
            lean_fetch.fetch(small_args, opener=_DispatchOpener())
            small_rows = [
                json.loads(line)
                for line in (small_dest / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
            ]

            big_dest = Path(td) / "big"
            big_args = lean_fetch.build_parser().parse_args(
                [
                    REPO, "--partition-count", "1", "--partition-index", "0",
                    "--license", "MIT", "--license-evidence", "test",
                    "--dest", str(big_dest),
                ]
            )
            lean_fetch.fetch(big_args, opener=_DispatchOpener())
            big_rows = [
                json.loads(line)
                for line in (big_dest / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(len(small_rows), 1)
            self.assertEqual(len(big_rows), 6)
            small_basis_len = len(small_rows[0]["human_provenance_basis"])
            big_basis_len = max(len(r["human_provenance_basis"]) for r in big_rows)
            # Bounded, not proportional to file count -- a pre-fix basis for the
            # 6-file partition would have been roughly 6x the 1-file partition's.
            self.assertLess(abs(big_basis_len - small_basis_len), 50)

    def test_budget_bytes_stops_before_a_file_that_would_exceed_it(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "p0"
            args = lean_fetch.build_parser().parse_args(
                [
                    REPO, "--partition-count", "1", "--partition-index", "0",
                    "--budget-bytes", "15",  # README.md(5) + src/a.lean(10) = 15 exactly; src/b.lean would exceed
                    "--license", "MIT", "--license-evidence", "test",
                    "--dest", str(dest),
                ]
            )
            receipt_path = lean_fetch.fetch(args, opener=_DispatchOpener())
            paths = _fetched_paths(receipt_path)
            self.assertEqual(paths, ["README.md", "src/a.lean"])


if __name__ == "__main__":
    unittest.main()
