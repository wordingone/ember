# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""tests/test_remint_hashes.py — offline coverage for scripts/hf_custody/remint_hashes.py.

Covers the per-row STOP rule: a row only gets reminted if its size-only
recompute confirms the existing content_hash; a mismatch leaves that row
byte-for-byte untouched and reported, never guessed at.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hf_custody import remint_hashes, sync  # noqa: E402


def _write_dataset_dir(root: Path, files: dict[str, bytes]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)


def test_matching_row_is_reminted(tmp_path: Path):
    root = tmp_path / "dataset-a"
    _write_dataset_dir(root, {"x.txt": b"hello\n"})
    census_hash = sync.compute_sizeonly_manifest(root)
    content_hash = sync.compute_filelist_manifest(root)["combined_sha256"]

    row = {
        "local_canonical_path": str(root),
        "disposition": "UPLOAD_ALLOWED",
        "content_hash": census_hash,
        "hash_method": "sha256_filelist_manifest",
        "hash_status": "complete",
        "unrelated_field": "kept as-is",
    }
    updated, results = remint_hashes.remint_rows([(1, row)])

    assert len(updated) == 1
    new_row = updated[0]
    assert new_row["content_hash"] == content_hash
    assert new_row["content_hash_sizeonly_census"] == census_hash
    assert new_row["hash_method"] == sync.SUPPORTED_HASH_METHOD
    assert "hash_remint" in new_row
    assert new_row["unrelated_field"] == "kept as-is"

    assert results[0]["action"] == "REMINTED"
    assert results[0]["sizeonly_match"] is True
    assert results[0]["new_content_hash"] == content_hash


def test_mismatched_row_is_left_completely_untouched(tmp_path: Path):
    root = tmp_path / "dataset-b"
    _write_dataset_dir(root, {"y.txt": b"world\n"})

    row = {
        "local_canonical_path": str(root),
        "disposition": "UPLOAD_ALLOWED",
        "content_hash": "0" * 64,  # deliberately wrong — does not match size-only recompute
        "hash_method": "sha256_filelist_manifest",
        "hash_status": "complete",
    }
    original_row_copy = dict(row)
    updated, results = remint_hashes.remint_rows([(1, row)])

    assert updated[0] == original_row_copy  # byte-for-byte unchanged
    assert "content_hash_sizeonly_census" not in updated[0]
    assert "hash_remint" not in updated[0]

    assert results[0]["action"] == "SKIPPED_NO_SIZEONLY_MATCH"
    assert results[0]["sizeonly_match"] is False


def test_non_eligible_rows_are_never_touched(tmp_path: Path):
    row = {
        "local_canonical_path": "/does/not/matter",
        "disposition": "REQUIRES_OPERATOR_REVIEW",
        "disposition_reason": "pending",
    }
    updated, results = remint_hashes.remint_rows([(1, row)])
    assert updated == [row]
    assert results == []  # non-eligible rows produce no per-row result at all


def test_write_inventory_roundtrip_preserves_all_rows(tmp_path: Path):
    rows = [
        {"a": 1, "disposition": "EXCLUDED"},
        {"a": 2, "disposition": "UPLOAD_ALLOWED", "content_hash": "x"},
    ]
    out_path = tmp_path / "inventory.jsonl"
    remint_hashes.write_inventory(out_path, rows)

    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(l) for l in lines] == rows
    # LF only, no CRLF
    raw = out_path.read_bytes()
    assert b"\r\n" not in raw


def test_main_dry_run_does_not_modify_inventory_file(tmp_path: Path, capsys):
    root = tmp_path / "dataset-c"
    _write_dataset_dir(root, {"z.txt": b"z\n"})
    census_hash = sync.compute_sizeonly_manifest(root)

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        json.dumps({
            "local_canonical_path": str(root),
            "disposition": "UPLOAD_ALLOWED",
            "content_hash": census_hash,
            "hash_method": "sha256_filelist_manifest",
            "hash_status": "complete",
        }) + "\n",
        encoding="utf-8",
    )
    original_bytes = inv_path.read_bytes()

    rc = remint_hashes.main(["--inventory", str(inv_path)])  # no --write
    assert rc == 0
    assert inv_path.read_bytes() == original_bytes  # untouched in dry-run

    receipts = list(tmp_path.glob("remint-receipt-*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["rows_reminted"] == 1


def test_main_write_flag_rewrites_inventory(tmp_path: Path):
    root = tmp_path / "dataset-d"
    _write_dataset_dir(root, {"w.txt": b"w\n"})
    census_hash = sync.compute_sizeonly_manifest(root)
    content_hash = sync.compute_filelist_manifest(root)["combined_sha256"]

    inv_path = tmp_path / "inventory.jsonl"
    inv_path.write_text(
        json.dumps({
            "local_canonical_path": str(root),
            "disposition": "UPLOAD_ALLOWED",
            "content_hash": census_hash,
            "hash_method": "sha256_filelist_manifest",
            "hash_status": "complete",
        }) + "\n",
        encoding="utf-8",
    )

    rc = remint_hashes.main(["--inventory", str(inv_path), "--write"])
    assert rc == 0

    rows = sync.load_inventory(inv_path)
    assert len(rows) == 1
    _, row = rows[0]
    assert row["content_hash"] == content_hash
    assert row["content_hash_sizeonly_census"] == census_hash
    assert row["hash_method"] == sync.SUPPORTED_HASH_METHOD
