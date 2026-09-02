# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for regen_bloated_manifest.py against a synthetic old-shape (pre-4075d25)
receipt + manifest.jsonl fixture -- no real network, no real corpus data."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import regen_bloated_manifest as regen  # noqa: E402
from tools.corpus_connectors import receipt as rcpt  # noqa: E402

REPO_ID = "example-org/example-repo"
SHA = "cafef00d" * 5  # 40 hex chars, fake but sha-shaped
FILES = [
    {"path": "a.lean", "sha256": "1" * 64, "declared_size_bytes": 10},
    {"path": "b.lean", "sha256": "2" * 64, "declared_size_bytes": 20},
    {"path": "sub/c.lean", "sha256": "3" * 64, "declared_size_bytes": 30},
]


def _build_old_shape_fixture(dest_root: Path) -> None:
    """Reproduce exactly what pre-4075d25 lean_fetch.py wrote: a single
    _manifests/*.json receipt whose notes field is the old inline-JSON blob,
    and a manifest.jsonl with one row per file, every row's
    human_provenance_basis carrying a full copy of that same blob."""
    dest_root.mkdir(parents=True, exist_ok=True)
    manifests_dir = dest_root / "_manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)

    old_notes_dict = {
        "full_tree_file_count": len(FILES),
        "partition_count": 1,
        "partition_index": 0,
        "partition_selected_count": len(FILES),
        "files_fetched": len(FILES),
        "budget_bytes": None,
        "files": FILES,
    }
    old_notes = json.dumps(old_notes_dict, sort_keys=True)

    fetched_at = "2026-08-14T18:00:00Z"
    top_level_files = [
        {"path": f["path"], "bytes": f["declared_size_bytes"], "sha256": f["sha256"]} for f in FILES
    ]
    receipt_dict = {
        "schema": rcpt.SCHEMA_NAME,
        "source": "lean-github",
        "source_id": f"{REPO_ID}@{SHA}#partition-0-of-1",
        "canonical_url": f"https://github.com/{REPO_ID}/tree/{SHA}",
        "license": "MIT",
        "license_evidence": "test fixture",
        "revision": SHA,
        "files": top_level_files,
        "total_bytes": sum(f["bytes"] for f in top_level_files),
        "sha256_manifest": "unused-in-test",
        "fetched_at": fetched_at,
        "connector": {"name": "lean_fetch", "version": "v1"},
        "l3_statement": rcpt.L3_STATEMENT,
        "dest_root": str(dest_root),
        "notes": old_notes,
    }
    key = rcpt.safe_key(receipt_dict["source_id"])
    (manifests_dir / f"20260814T180000Z-{key}.json").write_text(
        json.dumps(receipt_dict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest_rows = [
        {
            "source_url": receipt_dict["canonical_url"],
            "sha256": f["sha256"],
            "bytes": f["declared_size_bytes"],
            "license": receipt_dict["license"],
            "human_provenance_basis": old_notes,  # the O(n^2) bug: full blob, once per row
            "fetched_ts": fetched_at,
            "selection_rule": receipt_dict["source_id"],
        }
        for f in FILES
    ]
    with (dest_root / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for row in manifest_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


class RegenBloatedManifestTests(unittest.TestCase):
    def test_dry_run_verifies_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            dest_root = Path(td) / "dest"
            _build_old_shape_fixture(dest_root)
            old_size = (dest_root / "manifest.jsonl").stat().st_size

            regen.regenerate(dest_root, dry_run=True)

            self.assertEqual((dest_root / "manifest.jsonl").stat().st_size, old_size)
            self.assertFalse((dest_root / "manifest.jsonl.bloated-pre-1753.bak").exists())
            self.assertEqual(len(list((dest_root / "_manifests").glob("*.files.json"))), 0)

    def test_regenerate_shrinks_manifest_and_preserves_every_row(self):
        with tempfile.TemporaryDirectory() as td:
            dest_root = Path(td) / "dest"
            _build_old_shape_fixture(dest_root)
            old_bytes = (dest_root / "manifest.jsonl").read_text(encoding="utf-8")
            old_rows = [json.loads(line) for line in old_bytes.splitlines() if line.strip()]

            regen.regenerate(dest_root, dry_run=False)

            backup_path = dest_root / "manifest.jsonl.bloated-pre-1753.bak"
            self.assertTrue(backup_path.exists())
            self.assertEqual(backup_path.read_text(encoding="utf-8"), old_bytes)

            new_rows = [
                json.loads(line)
                for line in (dest_root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(new_rows), len(FILES))

            old_identities = sorted(regen._row_identity(r) for r in old_rows)
            new_identities = sorted(regen._row_identity(r) for r in new_rows)
            self.assertEqual(old_identities, new_identities)

            # The fix: every row's notes is now a flat, bounded string --
            # not a duplicated per-file JSON blob -- and identical across rows
            # regardless of file count (the O(n^2) growth is gone).
            notes_lengths = {len(r["human_provenance_basis"]) for r in new_rows}
            self.assertEqual(len(notes_lengths), 1)
            for r in new_rows:
                self.assertIn("disjoint-partition GitHub tree fetch", r["human_provenance_basis"])
                self.assertIn("file_manifest=_manifests/", r["human_provenance_basis"])
                self.assertNotIn(FILES[0]["sha256"], r["human_provenance_basis"])

            new_manifest_size = (dest_root / "manifest.jsonl").stat().st_size
            self.assertLess(new_manifest_size, len(old_bytes))

            sibling_files = list((dest_root / "_manifests").glob("*.files.json"))
            self.assertEqual(len(sibling_files), 1)
            sibling_data = json.loads(sibling_files[0].read_text(encoding="utf-8"))
            self.assertEqual(sibling_data["files_fetched"], len(FILES))
            self.assertEqual(
                sorted(f["sha256"] for f in sibling_data["files"]), sorted(f["sha256"] for f in FILES)
            )

    def test_regenerate_refuses_when_backup_already_exists(self):
        with tempfile.TemporaryDirectory() as td:
            dest_root = Path(td) / "dest"
            _build_old_shape_fixture(dest_root)
            (dest_root / "manifest.jsonl.bloated-pre-1753.bak").write_text("stale", encoding="utf-8")

            with self.assertRaises(SystemExit):
                regen.regenerate(dest_root, dry_run=False)

            # Original manifest.jsonl must be untouched by the refused run.
            rows = [
                json.loads(line)
                for line in (dest_root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(rows), len(FILES))


if __name__ == "__main__":
    unittest.main()
