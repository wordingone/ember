from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from courtlistener_custody import (
    ANNOTATION_SCHEMA,
    build_content_annotation,
    prose_gap_projection,
    validate_content_annotation,
    write_content_annotation,
)


def _manifest_row(name: str, payload: bytes) -> dict[str, object]:
    import hashlib

    return {
        "source_url": f"https://example.test/bulk-data/{name}",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "license": "public domain",
        "human_provenance_basis": "court-authored opinions",
        "fetched_ts": "2026-07-06T17:14:00Z",
        "selection_rule": "federal courts opinion-clusters bulk set",
    }


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "courtlistener"
    root.mkdir(parents=True)
    payload = (
        b"id,date_created,case_name,syllabus,headnotes,summary,disposition\n"
        b"1,2026-01-01,Example,,,,\n"
    )
    data = root / "opinion-clusters.csv"
    data.write_bytes(payload)
    manifest = root / "manifest.jsonl"
    manifest.write_text(json.dumps(_manifest_row(data.name, payload)) + "\n", encoding="utf-8")
    return root, manifest


def test_courtlistener_annotation_is_closed_deterministic_and_excludes_metadata_bytes(tmp_path: Path) -> None:
    root, manifest = _write_fixture(tmp_path)

    first = build_content_annotation(manifest, root, sample_rows=8)
    second = build_content_annotation(manifest, root, sample_rows=8)

    assert first == second
    assert first["schema_version"] == ANNOTATION_SCHEMA
    assert first["result"] == "CONTENT_CLASSIFIED"
    assert first["prose_gap_admission"] == "NOT_ADMITTED"
    assert first["projection"]["raw_bytes"] == (root / "opinion-clusters.csv").stat().st_size
    assert first["projection"]["eligible_prose_bytes"] == 0
    assert first["files"][0]["content_class"] == "METADATA_ONLY_NO_PROSE_OBSERVED"
    assert prose_gap_projection(first) == {"eligible_prose_bytes": 0, "eligible_sources": []}


def test_courtlistener_annotation_round_trips_and_rejects_l4_or_file_drift(tmp_path: Path) -> None:
    root, manifest = _write_fixture(tmp_path)
    annotation = build_content_annotation(manifest, root)
    annotation_path = root / "content-annotation-v1.json"
    annotation_path.write_text(json.dumps(annotation, sort_keys=True) + "\n", encoding="utf-8")

    assert validate_content_annotation(annotation_path, manifest, root) == annotation

    forged = json.loads(annotation_path.read_text(encoding="utf-8"))
    forged["files"][0]["bytes"] += 1
    forged["annotation_sha256"] = __import__("hashlib").sha256(
        (json.dumps({k: v for k, v in forged.items() if k != "annotation_sha256"}, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    annotation_path.write_text(json.dumps(forged, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="annotation file projection"):
        validate_content_annotation(annotation_path, manifest, root)


def test_courtlistener_annotation_rejects_manifest_row_with_unknown_or_missing_fields(tmp_path: Path) -> None:
    root, manifest = _write_fixture(tmp_path)
    rows = [json.loads(manifest.read_text(encoding="utf-8"))]
    rows[0]["unexpected"] = "caller-authored"
    manifest.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest row schema"):
        build_content_annotation(manifest, root)


def test_courtlistener_annotation_writer_is_atomic_and_refuses_overwrite(tmp_path: Path) -> None:
    root, manifest = _write_fixture(tmp_path)
    output = root / "content-annotation-v1.json"
    assert write_content_annotation(manifest, root, output, sample_rows=8) == output
    with pytest.raises(ValueError, match="already exists"):
        write_content_annotation(manifest, root, output, sample_rows=8)
    assert not list(root.glob("*.tmp"))


def test_courtlistener_annotation_accepts_legacy_blank_csv_header_columns(tmp_path: Path) -> None:
    root = tmp_path / "courtlistener"
    root.mkdir()
    payload = b"id,,case_name\n1,,Example\n"
    data = root / "legacy.csv"
    data.write_bytes(payload)
    manifest = root / "manifest.jsonl"
    manifest.write_text(json.dumps(_manifest_row(data.name, payload)) + "\n", encoding="utf-8")

    annotation = build_content_annotation(manifest, root, sample_rows=2)
    assert annotation["files"][0]["content_class"] == "STRUCTURED_METADATA"


def test_courtlistener_annotation_rejects_traversal_duplicate_and_malformed_rows(tmp_path: Path) -> None:
    root, manifest = _write_fixture(tmp_path)
    row = json.loads(manifest.read_text(encoding="utf-8"))
    row["source_url"] = "https://example.test/bulk-data/../opinion-clusters.csv"
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="basename"):
        build_content_annotation(manifest, root)

    duplicate_root, duplicate_manifest = _write_fixture(tmp_path / "duplicate")
    duplicate_row = json.loads(duplicate_manifest.read_text(encoding="utf-8"))
    duplicate_manifest.write_text("\n".join(json.dumps(item) for item in [duplicate_row, duplicate_row]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        build_content_annotation(duplicate_manifest, duplicate_root)

    other_root, other_manifest = _write_fixture(tmp_path / "other")
    annotation = build_content_annotation(other_manifest, other_root)
    annotation["files"][0] = "not-a-row"
    annotation_path = other_root / "malformed-annotation.json"
    annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
    third_root, third_manifest = _write_fixture(tmp_path / "third")
    with pytest.raises(ValueError, match="file row"):
        validate_content_annotation(annotation_path, third_manifest, third_root)


def test_courtlistener_annotation_writer_keeps_output_inside_custody_root(tmp_path: Path) -> None:
    root, manifest = _write_fixture(tmp_path)
    with pytest.raises(ValueError, match="custody root"):
        write_content_annotation(manifest, root, tmp_path / "outside.json")
