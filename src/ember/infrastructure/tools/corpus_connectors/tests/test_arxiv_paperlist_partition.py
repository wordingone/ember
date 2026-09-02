# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for arxiv_paperlist_partition.py -- no network, fixture OAI pages only."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import arxiv_paperlist_partition as partition


def _oai_page(records: list[tuple[str, str | None]]) -> bytes:
    """records: list of (id, license_url_or_None)."""
    body = []
    for arxiv_id, license_url in records:
        license_el = f"<license>{license_url}</license>" if license_url else ""
        body.append(
            f"""<record>
  <header><identifier>oai:arXiv.org:{arxiv_id}</identifier><datestamp>2026-01-01</datestamp></header>
  <metadata><arXiv xmlns="http://arxiv.org/OAI/arXiv/">
    <id>{arxiv_id}</id>
    <created>2026-01-01</created>
    <title>Fixture paper {arxiv_id}</title>
    {license_el}
  </arXiv></metadata>
</record>"""
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2026-01-01T00:00:00Z</responseDate>
  <ListRecords>
    {"".join(body)}
  </ListRecords>
</OAI-PMH>
""".encode("utf-8")


CC_BY_4_0 = partition.EXACT_CC_BY_4_0


class PartitionTests(unittest.TestCase):
    def test_exact_license_filter_admits_only_cc_by_4_0(self):
        with tempfile.TemporaryDirectory() as td:
            pages = Path(td) / "pages"
            pages.mkdir()
            (pages / "000000.xml").write_bytes(
                _oai_page(
                    [
                        ("2601.00001", CC_BY_4_0),
                        ("2601.00002", "http://creativecommons.org/licenses/by-sa/4.0/"),
                        ("2601.00003", "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"),
                        ("2601.00004", None),
                        ("2601.00005", CC_BY_4_0),
                    ]
                )
            )
            ids = partition.collect_exact_cc_by_4_0_ids(pages)
            self.assertEqual(sorted(ids), ["2601.00001", "2601.00005"])

    def test_partition_is_deterministic_mod_2_of_sha256(self):
        ids = ["2601.00001", "2601.00002", "2601.00003", "2601.00004"]
        train2, heldout = partition.partition(ids)
        for c in train2:
            digest = hashlib.sha256(c.arxiv_id.encode("utf-8")).hexdigest()
            self.assertEqual(int(digest, 16) % 2, 0)
        for c in heldout:
            digest = hashlib.sha256(c.arxiv_id.encode("utf-8")).hexdigest()
            self.assertEqual(int(digest, 16) % 2, 1)
        self.assertEqual(len(train2) + len(heldout), len(ids))

    def test_train2_ordering_is_ascending_hex_digest(self):
        with tempfile.TemporaryDirectory() as td:
            pages = Path(td) / "pages"
            pages.mkdir()
            ids = [f"2601.{i:05d}" for i in range(50)]
            (pages / "000000.xml").write_bytes(_oai_page([(i, CC_BY_4_0) for i in ids]))
            collected = partition.collect_exact_cc_by_4_0_ids(pages)
            train2, _heldout = partition.partition(collected)
            digests = [c.digest_hex for c in train2]
            self.assertEqual(digests, sorted(digests))

    def test_duplicate_id_across_pages_raises(self):
        with tempfile.TemporaryDirectory() as td:
            pages = Path(td) / "pages"
            pages.mkdir()
            (pages / "000000.xml").write_bytes(_oai_page([("2601.00001", CC_BY_4_0)]))
            (pages / "000001.xml").write_bytes(_oai_page([("2601.00001", CC_BY_4_0)]))
            with self.assertRaises(ValueError):
                partition.collect_exact_cc_by_4_0_ids(pages)

    def test_version_suffixed_id_raises(self):
        with tempfile.TemporaryDirectory() as td:
            pages = Path(td) / "pages"
            pages.mkdir()
            (pages / "000000.xml").write_bytes(_oai_page([("2601.00001v2", CC_BY_4_0)]))
            with self.assertRaises(ValueError):
                partition.collect_exact_cc_by_4_0_ids(pages)

    def test_write_outputs_and_manifest_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            pages_dir = Path(td) / "pages"
            out_dir = Path(td) / "out"
            pages_dir.mkdir()
            ids = [f"2601.{i:05d}" for i in range(20)]
            (pages_dir / "000000.xml").write_bytes(_oai_page([(i, CC_BY_4_0) for i in ids]))
            collected = partition.collect_exact_cc_by_4_0_ids(pages_dir)
            train2, heldout = partition.partition(collected)
            train2_path, heldout_path, manifest_path = partition.write_outputs(
                out_dir, "fixture", pages_dir, "heldout label for test", train2, heldout
            )
            train2_lines = train2_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(train2_lines), len(train2))
            self.assertEqual(train2_lines, [c.arxiv_id for c in train2])
            heldout_lines = heldout_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(heldout_lines), len(heldout))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"]["residue_0_train2"], len(train2))
            self.assertEqual(manifest["counts"]["residue_1_heldout"], len(heldout))
            self.assertEqual(manifest["counts"]["total_exact_cc_by_4_0"], len(ids))
            self.assertEqual(manifest["hash_primitive"]["residue_1"], "heldout label for test")

    def test_main_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            pages_dir = Path(td) / "pages"
            out_dir = Path(td) / "out"
            pages_dir.mkdir()
            ids = [f"2601.{i:05d}" for i in range(10)]
            (pages_dir / "000000.xml").write_bytes(_oai_page([(i, CC_BY_4_0) for i in ids]))
            rc = partition.main(
                [
                    "--pages-dir", str(pages_dir),
                    "--set-name", "fixture",
                    "--out-dir", str(out_dir),
                    "--heldout-label", "test heldout",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "train2-paper-list.txt").exists())
            self.assertTrue((out_dir / "heldout-id-list.txt").exists())
            self.assertTrue((out_dir / "partition-manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
