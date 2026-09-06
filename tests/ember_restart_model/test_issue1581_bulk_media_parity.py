# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bulk-route media parity for #1581 declaration rows: a frozen closed media-class table,
content-first classification for table classes, receipt-bound predecessor bindings, and
the host-executable classes kept refused. Mirrors the train-partition route's shape."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

import catalog_admission as catalog_admission_module  # noqa: E402
from catalog_admission import (  # noqa: E402
    build_bulk_predecessor_media_bindings,
    project_catalog_spec,
)
from catalog_admission import main as catalog_main  # noqa: E402
from domain_manifest import (  # noqa: E402
    _bulk_media_type,
    _connector_media_type,
    load_bulk_domain_connector_receipt,
)

TOKENIZER = "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_connector(root: Path, *, source: str, files: list[tuple[str, bytes]]) -> tuple[Path, str]:
    rows = []
    for name, raw in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        rows.append({"path": name, "bytes": len(raw), "sha256": sha256(raw)})
    payload = {
        "canonical_url": f"https://example.test/{source}",
        "connector": {"name": "fixture", "version": "v1"},
        "fetched_at": "2026-09-06T00:00:00Z",
        "files": rows,
        "license": "CC-BY-4.0",
        "schema": "corpus-connector-receipt-v1",
        "sha256_manifest": sha256("\n".join(sorted(row["sha256"] for row in rows)).encode()),
        "source": "fixture",
        "source_id": source,
        "total_bytes": sum(row["bytes"] for row in rows),
        "dest_root": str(root),
    }
    path = root / "connector.json"
    path.write_bytes(canonical(payload))
    return path, sha256(path.read_bytes())


def bulk_row(receipt_path: Path, receipt_sha: str, source_id: str, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "receipt_path": str(receipt_path),
        "expected_receipt_sha256": receipt_sha,
        "source_id": source_id,
        "expected_source_selector": source_id,
        "expected_license_text_sha256": sha256(b"CC-BY-4.0"),
        "domain": "formal_logic",
        "split": "heldout",
        "supporting_receipts": [],
    }
    row.update(extra)
    return row


def spec_bytes(rows: list[dict[str, object]]) -> bytes:
    return canonical(
        {
            "schema_version": "ember-issue1581-catalog-projection-spec-v1",
            "tokenizer_sha256": TOKENIZER,
            "created_at_ms": 1,
            "rows": rows,
        }
    )


def projected_media_types(manifest_raw: bytes) -> dict[str, str]:
    manifest = json.loads(manifest_raw)
    return {
        record["sha256"]: record["media_type"]
        for record in manifest["records"]
        if record.get("kind") == "immutable_object"
    }


def test_bulk_media_table_is_frozen_goal_bound_and_excludes_host_executables() -> None:
    table = catalog_admission_module._load_bulk_media_type_table()
    assert table["schema_version"] == "ember-issue1581-bulk-connector-media-types-v1"
    assert table["goal_id"] == "EMBER-02" and table["workstream_id"] == "EMBER-02B"
    assert table["class_count"] == len(table["classes"]) == 60
    assert {".bin", ".dll", ".exe", ".lib", ".so"} <= set(table["excluded_classes"])
    assert not set(table["excluded_classes"]) & set(table["classes"])
    for key in table["classes"]:
        with pytest.raises(ValueError, match="unsupported media type"):
            _connector_media_type(PurePosixPath(f"fixture{key}"))


def test_bulk_media_table_self_hash_and_schema_are_enforced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    good = json.loads(catalog_admission_module._BULK_MEDIA_TYPE_TABLE.read_bytes())
    tampered = dict(good)
    tampered["classes"] = dict(good["classes"])
    tampered["classes"][".exe"] = {"media_type": "application/octet-stream", "count": 1, "example": "x.exe", "reason": "x"}
    path = tmp_path / "table.json"
    path.write_bytes(canonical(tampered))
    monkeypatch.setattr(catalog_admission_module, "_BULK_MEDIA_TYPE_TABLE", path)
    with pytest.raises(ValueError, match="BULK_PROJECTION_MEDIA_TABLE_SELF_HASH_REFUSED"):
        catalog_admission_module._load_bulk_media_type_table()
    body = {key: value for key, value in tampered.items() if key != "self_sha256"}
    body["class_count"] = len(body["classes"])
    body["file_count"] = sum(row["count"] for row in body["classes"].values())
    body["self_sha256"] = sha256(canonical(body))
    path.write_bytes(canonical(body))
    with pytest.raises(ValueError, match="BULK_PROJECTION_MEDIA_TABLE_SCHEMA_REFUSED"):
        catalog_admission_module._load_bulk_media_type_table()


def test_projection_admits_table_classes_content_first_and_refuses_executables(tmp_path: Path) -> None:
    files = [
        ("Archive.lean", b"theorem t : True := trivial\n"),
        ("data/image.raw", PNG),
        ("data/blob.dat", b"\x00\x01\x02\xff\xfe"),
        (".pre-commit-config.yaml", b"repos: []\n"),
        ("notes.md", b"# markdown\n"),
    ]
    receipt_path, receipt_sha = write_connector(tmp_path / "ok", source="candidate-formal_logic-heldout-9", files=files)
    manifest = project_catalog_spec(
        spec_raw=spec_bytes([bulk_row(receipt_path, receipt_sha, "candidate-formal_logic-heldout-9")])
    )
    by_sha = projected_media_types(manifest)
    raw_by_name = dict(files)
    assert by_sha[sha256(raw_by_name["Archive.lean"])] == "text/plain; charset=utf-8"
    assert by_sha[sha256(raw_by_name["data/image.raw"])] == "image/png"
    assert by_sha[sha256(raw_by_name["data/blob.dat"])] == "application/octet-stream"
    assert by_sha[sha256(raw_by_name[".pre-commit-config.yaml"])] == "text/plain; charset=utf-8"
    assert by_sha[sha256(raw_by_name["notes.md"])] == "text/markdown; charset=utf-8"

    for name in ("payload.bin", "freeglut.dll", "freeglut.lib", "tool.exe", "lib.so", "unknown.zzz"):
        bad_path, bad_sha = write_connector(tmp_path / name.replace(".", "_"), source="candidate-formal_logic-heldout-9", files=[(name, b"x")])
        with pytest.raises(ValueError, match="BULK_PROJECTION_MEDIA_CLASS_UNMAPPED"):
            project_catalog_spec(spec_raw=spec_bytes([bulk_row(bad_path, bad_sha, "candidate-formal_logic-heldout-9")]))


def test_direct_loader_without_table_keeps_the_closed_mapper(tmp_path: Path) -> None:
    receipt_path, receipt_sha = write_connector(tmp_path / "direct", source="candidate-formal_logic-heldout-9", files=[("Archive.lean", b"x\n")])
    with pytest.raises(ValueError, match="unsupported media type"):
        load_bulk_domain_connector_receipt(
            receipt_path=receipt_path,
            expected_receipt_sha256=receipt_sha,
            source_id="candidate-formal_logic-heldout-9",
            expected_source_selector="candidate-formal_logic-heldout-9",
            expected_license_text_sha256=sha256(b"CC-BY-4.0"),
            domain="formal_logic",
            split="heldout",
        )


def test_predecessor_binding_governs_and_is_receipt_bound(tmp_path: Path) -> None:
    license_bytes = b"%PDF-1.4 license text\n"
    files = [("LICENSE.md", license_bytes), ("README.md", b"# readme\n")]
    receipt_path, receipt_sha = write_connector(tmp_path / "pred", source="candidate-formal_logic-heldout-9", files=files)
    export = {
        "schema_version": "fixture",
        "edges": [],
        "records": [
            {"kind": "immutable_object", "id": f"sha256:{sha256(license_bytes)}", "sha256": sha256(license_bytes), "media_type": "application/pdf", "byte_count": len(license_bytes)},
            {"kind": "immutable_object", "id": "sha256:" + "0" * 64, "sha256": "0" * 64, "media_type": "text/plain; charset=utf-8", "byte_count": 1},
        ],
    }
    export_raw = canonical(export)
    bindings_raw = build_bulk_predecessor_media_bindings(catalog_export_raw=export_raw, connector_receipt_raw=receipt_path.read_bytes())
    bindings = json.loads(bindings_raw)
    assert bindings["binding_count"] == 1
    assert bindings["media_types_by_object_id"] == {f"sha256:{sha256(license_bytes)}": "application/pdf"}
    assert bindings["connector_receipt_sha256"] == receipt_sha
    assert bindings["predecessor_catalog_export_sha256"] == sha256(export_raw)
    body = {key: value for key, value in bindings.items() if key != "self_sha256"}
    assert bindings["self_sha256"] == sha256(canonical(body))

    bindings_path = tmp_path / "bindings.json"
    bindings_path.write_bytes(bindings_raw)
    pin = {"path": str(bindings_path), "sha256": sha256(bindings_raw)}
    manifest = project_catalog_spec(
        spec_raw=spec_bytes([bulk_row(receipt_path, receipt_sha, "candidate-formal_logic-heldout-9", predecessor_media_bindings=pin)])
    )
    by_sha = projected_media_types(manifest)
    assert by_sha[sha256(license_bytes)] == "application/pdf"
    assert by_sha[sha256(b"# readme\n")] == "text/markdown; charset=utf-8"

    # Without the pin the mapper decides: same object, markdown -- the overlap this route exists to cure.
    plain = project_catalog_spec(spec_raw=spec_bytes([bulk_row(receipt_path, receipt_sha, "candidate-formal_logic-heldout-9")]))
    assert projected_media_types(plain)[sha256(license_bytes)] == "text/markdown; charset=utf-8"

    # Bindings emitted for a different receipt are refused for this row.
    other_path, other_sha = write_connector(tmp_path / "other", source="candidate-formal_logic-heldout-9", files=files)
    with pytest.raises(ValueError, match="BULK_PREDECESSOR_MEDIA_BINDINGS_RECEIPT_MISMATCH"):
        project_catalog_spec(spec_raw=spec_bytes([bulk_row(other_path, other_sha, "candidate-formal_logic-heldout-9", predecessor_media_bindings=pin)]))

    # A tampered bindings body under a matching pin is refused on its self hash; a drifted pin on its bytes.
    tampered = dict(bindings)
    tampered["media_types_by_object_id"] = {f"sha256:{sha256(license_bytes)}": "text/plain; charset=utf-8"}
    tampered_raw = canonical(tampered)
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_bytes(tampered_raw)
    with pytest.raises(ValueError, match="BULK_PREDECESSOR_MEDIA_BINDINGS_SELF_HASH_REFUSED"):
        project_catalog_spec(
            spec_raw=spec_bytes([bulk_row(receipt_path, receipt_sha, "candidate-formal_logic-heldout-9", predecessor_media_bindings={"path": str(tampered_path), "sha256": sha256(tampered_raw)})])
        )
    with pytest.raises(ValueError, match="BULK_PREDECESSOR_MEDIA_BINDINGS_HASH_DRIFT"):
        project_catalog_spec(
            spec_raw=spec_bytes([bulk_row(receipt_path, receipt_sha, "candidate-formal_logic-heldout-9", predecessor_media_bindings={"path": str(tampered_path), "sha256": sha256(bindings_raw)})])
        )


def test_bulk_media_type_precedence_unit() -> None:
    table = {"classes": {".dat": {"media_type": "application/octet-stream"}}}
    physical = Path(__file__)
    digest = sha256(physical.read_bytes())
    assert _bulk_media_type(PurePosixPath("x.dat"), digest, physical, table, {f"sha256:{digest}": "image/gif"}) == "image/gif"
    assert _bulk_media_type(PurePosixPath("x.dat"), digest, physical, table, None) == "text/plain; charset=utf-8"
    assert _bulk_media_type(PurePosixPath("x.py"), digest, physical, table, None) == "text/x-python; charset=utf-8"
    with pytest.raises(ValueError, match="BULK_PROJECTION_MEDIA_CLASS_UNMAPPED:.zzz:x.zzz"):
        _bulk_media_type(PurePosixPath("x.zzz"), digest, physical, table, None)
    with pytest.raises(ValueError, match="unsupported media type"):
        _bulk_media_type(PurePosixPath("x.zzz"), digest, physical, None, None)


def test_cli_emits_bindings_file(tmp_path: Path) -> None:
    receipt_path, _ = write_connector(tmp_path / "cli", source="candidate-formal_logic-heldout-9", files=[("a.txt", b"a\n")])
    export_path = tmp_path / "export.json"
    object_id = "sha256:" + sha256(b"a\n")
    export_path.write_bytes(canonical({"records": [{"kind": "immutable_object", "id": object_id, "media_type": "text/plain; charset=utf-8"}]}))
    out = tmp_path / "bindings.json"
    assert catalog_main(["bulk-predecessor-media-bindings", "--catalog-export", str(export_path), "--connector-receipt", str(receipt_path), "--output", str(out)]) == 0
    emitted = json.loads(out.read_bytes())
    assert emitted["schema_version"] == "ember-issue1581-bulk-predecessor-media-types-v1"
    assert emitted["binding_count"] == 1


# --- #2168: declared bulk exclusions (host-executable classes, train-overlap objects) ---

EXE = b"MZ\x90\x00host payload\n"
LEAN = b"theorem t : True := trivial\n"


def _exclusion_row(receipt_path, receipt_sha, **declared):
    return bulk_row(receipt_path, receipt_sha, "candidate-formal_logic-heldout-9", **declared)


def test_declared_class_exclusion_drops_host_executables_and_keeps_the_projection(tmp_path: Path) -> None:
    files = [("Archive.lean", LEAN), ("bin/tool.exe", EXE), ("bin/helper.dll", EXE)]
    receipt_path, receipt_sha = write_connector(tmp_path / "c", source="candidate-formal_logic-heldout-9", files=files)
    # undeclared, the host-executable class is still the refusal it has always been
    with pytest.raises(ValueError, match="BULK_PROJECTION_MEDIA_CLASS_UNMAPPED"):
        project_catalog_spec(spec_raw=spec_bytes([_exclusion_row(receipt_path, receipt_sha)]))
    records: list[dict] = []
    manifest = project_catalog_spec(
        spec_raw=spec_bytes([_exclusion_row(receipt_path, receipt_sha, excluded_media_classes=[".exe", ".dll"])]),
        exclusion_records=records,
    )
    assert list(projected_media_types(manifest)) == [sha256(LEAN)]
    assert len(records) == 1
    record = records[0]
    assert record["excluded_count"] == 2
    assert record["projected_count"] == 1
    assert record["connector_file_count"] == 3
    assert record["projected_count"] + record["excluded_count"] == record["connector_file_count"]
    assert {item["reason"] for item in record["items"]} == {"HOST_EXECUTABLE_CLASS"}
    assert sorted(item["path"] for item in record["items"]) == ["bin/helper.dll", "bin/tool.exe"]


def test_declared_object_exclusion_drops_a_named_sha_as_train_overlap(tmp_path: Path) -> None:
    overlap = b"# markdown that also lives in train\n"
    files = [("Archive.lean", LEAN), ("notes.md", overlap)]
    receipt_path, receipt_sha = write_connector(tmp_path / "c", source="candidate-formal_logic-heldout-9", files=files)
    records: list[dict] = []
    manifest = project_catalog_spec(
        spec_raw=spec_bytes([_exclusion_row(receipt_path, receipt_sha, excluded_object_sha256s=[sha256(overlap)])]),
        exclusion_records=records,
    )
    assert list(projected_media_types(manifest)) == [sha256(LEAN)]
    assert [item["reason"] for item in records[0]["items"]] == ["TRAIN_OVERLAP_OBJECT"]
    assert records[0]["items"][0]["sha256"] == sha256(overlap)
    assert records[0]["reason_counts"]["TRAIN_OVERLAP_OBJECT"] == 1


def test_bulk_exclusion_planted_negatives(tmp_path: Path) -> None:
    files = [("Archive.lean", LEAN), ("bin/tool.exe", EXE)]
    receipt_path, receipt_sha = write_connector(tmp_path / "c", source="candidate-formal_logic-heldout-9", files=files)

    # 1. a declared object sha that matches no file in the connector
    absent = "0" * 64
    with pytest.raises(ValueError, match=f"BULK_EXCLUSION_UNMATCHED:{absent}"):
        project_catalog_spec(spec_raw=spec_bytes([
            _exclusion_row(receipt_path, receipt_sha, excluded_media_classes=[".exe"], excluded_object_sha256s=[absent])
        ]))

    # 2. an exclusion set that would project nothing at all
    with pytest.raises(ValueError, match="BULK_EXCLUSION_EMPTY_PROJECTION"):
        project_catalog_spec(spec_raw=spec_bytes([
            _exclusion_row(
                receipt_path, receipt_sha,
                excluded_media_classes=[".exe"], excluded_object_sha256s=[sha256(LEAN)],
            )
        ]))

    # 3. a class the frozen table does not list as excludable
    with pytest.raises(ValueError, match="BULK_EXCLUSION_CLASS_NOT_EXCLUDABLE:.pdf"):
        project_catalog_spec(spec_raw=spec_bytes([
            _exclusion_row(receipt_path, receipt_sha, excluded_media_classes=[".pdf"])
        ]))

    # 4. a malformed digest, and a duplicated declaration
    with pytest.raises(ValueError, match="BULK_EXCLUSION_SHA_MALFORMED"):
        project_catalog_spec(spec_raw=spec_bytes([
            _exclusion_row(receipt_path, receipt_sha, excluded_object_sha256s=["not-a-sha"])
        ]))
    with pytest.raises(ValueError, match="BULK_EXCLUSION_DECLARATION_DUPLICATE"):
        project_catalog_spec(spec_raw=spec_bytes([
            _exclusion_row(receipt_path, receipt_sha, excluded_media_classes=[".exe", ".exe"])
        ]))


def test_exclusions_are_refused_on_the_train_partition_route() -> None:
    # the exclusion keys are a bulk-route declaration only; the partition route has its own
    # heldout accounting and must not gain a second, undeclared way to drop rows
    row = {key: "x" for key in catalog_admission_module._TRAIN_PARTITION_PROJECTION_ROW_FIELDS}
    row["excluded_media_classes"] = [".exe"]
    with pytest.raises(ValueError, match="BULK_EXCLUSION_ROUTE_REFUSED"):
        project_catalog_spec(spec_raw=spec_bytes([row]))


def test_exclusion_receipt_round_trips_and_refuses_a_tampered_body(tmp_path: Path) -> None:
    files = [("Archive.lean", LEAN), ("bin/tool.exe", EXE)]
    receipt_path, receipt_sha = write_connector(tmp_path / "c", source="candidate-formal_logic-heldout-9", files=files)
    records: list[dict] = []
    project_catalog_spec(
        spec_raw=spec_bytes([_exclusion_row(receipt_path, receipt_sha, excluded_media_classes=[".exe"])]),
        exclusion_records=records,
    )
    raw = catalog_admission_module.build_projection_exclusion_receipt(records)
    verified = catalog_admission_module.verify_projection_exclusion_receipt(raw)
    assert verified["excluded_count"] == 1
    assert verified["self_sha256"] == json.loads(raw)["self_sha256"]

    tampered = json.loads(raw)
    tampered["excluded_count"] = 2
    with pytest.raises(ValueError, match="BULK_EXCLUSION_RECEIPT_SELF_HASH_REFUSED"):
        catalog_admission_module.verify_projection_exclusion_receipt(canonical(tampered))

    # a body whose count invariant does not hold, re-self-hashed so only the invariant fails
    broken = json.loads(raw)
    broken.pop("self_sha256")
    broken["projected_count"] = 99
    broken["self_sha256"] = sha256(canonical(broken))
    with pytest.raises(ValueError, match="BULK_EXCLUSION_RECEIPT_SCHEMA_REFUSED"):
        catalog_admission_module.verify_projection_exclusion_receipt(canonical(broken))

    with pytest.raises(ValueError, match="BULK_EXCLUSION_RECEIPT_SINGLE_ROW_REQUIRED"):
        catalog_admission_module.build_projection_exclusion_receipt(records + records)
