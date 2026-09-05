# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "issue2130_heldout_image_text.py"
SPEC = importlib.util.spec_from_file_location("issue2130_heldout_image_text", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _row(item_id: str, images: dict[str, bytes], question_type: str = "multiple-choice") -> dict:
    row = {
        "id": item_id,
        "question": f"What is shown in <image 1> for {item_id}?",
        "options": "['alpha', 'beta', 'gamma']",
        "question_type": question_type,
    }
    for column in MODULE.IMAGE_COLUMNS:
        row[column] = None
    for column, raw in images.items():
        row[column] = {"bytes": raw, "path": f"{item_id}-{column}.png"}
    return row


SHARED = b"png-shared-between-two-items"
ROWS = {
    "Art": [
        _row("validation_Art_1", {"image_1": b"png-art-1"}),
        _row("validation_Art_2", {"image_1": SHARED, "image_2": b"png-art-2b"}),
        _row("validation_Art_3", {"image_1": b"png-open"}, question_type="open"),
    ],
    "Math": [
        _row("validation_Math_1", {"image_1": SHARED}),
    ],
}
LICENSE_RAW = b"Apache License fixture\n"
CUSTODY_RAW = None  # bound in make_inputs


def make_inputs(monkeypatch: pytest.MonkeyPatch) -> tuple[list[dict], bytes, bytes, set[str]]:
    items = MODULE.items_from_rows(ROWS)
    ids = [item["id"] for item in items]
    item_set = MODULE.id_set_sha256(ids)
    custody_raw = json.dumps({
        "upstream_url": "https://example.test/mmmu",
        "split": {"eligible_id_set_sha256": item_set},
    }).encode()
    monkeypatch.setattr(MODULE, "EXPECTED_ITEM_COUNT", len(ids))
    monkeypatch.setattr(MODULE, "EXPECTED_PARQUET_FILE_COUNT", 2)
    monkeypatch.setattr(MODULE, "PROTECTED_ITEM_SET_SHA256", item_set)
    monkeypatch.setattr(MODULE, "LICENSE_SHA256", sha(LICENSE_RAW))
    monkeypatch.setattr(MODULE, "CUSTODY_MANIFEST_SHA256", sha(custody_raw))
    monkeypatch.setattr(MODULE, "EXPECTED_ADMITTED_HELDOUT_IMAGE_COUNT", 1)
    already = {sha(SHARED)}
    return items, custody_raw, LICENSE_RAW, already


def _census(monkeypatch: pytest.MonkeyPatch, train: set[str] | None = None):
    items, custody_raw, license_raw, already = make_inputs(monkeypatch)
    census = MODULE.build_census(
        items=items,
        parquet_file_count=2,
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
        admitted_train_object_hashes=train or set(),
        admitted_heldout_image_hashes=already,
    )
    return items, custody_raw, license_raw, already, census


def test_items_from_rows_projects_multiple_choice_items_and_canonical_text() -> None:
    items = MODULE.items_from_rows(ROWS)
    assert [item["id"] for item in items] == ["validation_Art_1", "validation_Art_2", "validation_Math_1"]
    art2 = items[1]
    assert [image["column"] for image in art2["images"]] == ["image_1", "image_2"]
    text = json.loads(art2["text_payload"])
    assert set(text) == {"id", "question", "options"}
    assert text["options"] == ["alpha", "beta", "gamma"]
    assert art2["text_payload"].endswith(b"\n")
    assert b"answer" not in art2["text_payload"]
    with pytest.raises(ValueError, match="ITEM_OPTIONS_SHAPE_REFUSED"):
        MODULE.items_from_rows({"X": [_row("validation_X_1", {"image_1": b"p"}) | {"options": "not a list"}]})
    with pytest.raises(ValueError, match="ITEM_WITHOUT_IMAGE_REFUSED"):
        MODULE.items_from_rows({"X": [_row("validation_X_1", {})]})


def test_census_binds_the_frozen_id_set_and_records_the_union_without_readmission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items, _custody, _license, already, census = _census(monkeypatch)
    assert census["eligible_item_count"] == 3
    assert census["unique_image_object_count"] == 3
    assert census["already_admitted_image_object_count"] == 1
    assert census["new_image_object_count"] == 2
    assert census["item_text_object_count"] == 3
    assert census["train_intersection"] == {"executed": True, "admitted_train_object_count": 0, "count": 0}
    referenced = sorted(set(census["image_objects"]) | {i["item_text_object"]["sha256"] for i in census["items"]})
    assert census["referenced_object_count"] == 6
    assert census["referenced_object_set_sha256"] == sha(canonical(referenced))
    admitted = sorted(set(referenced) - already)
    assert census["admitted_object_set_sha256"] == sha(canonical(admitted))
    body = dict(census)
    assert body.pop("self_sha256") == sha(canonical(body))
    art2 = next(item for item in census["items"] if item["item_id"] == "validation_Art_2")
    source = next(item for item in items if item["id"] == "validation_Art_2")
    assert art2["gold_item_sha256"] == sha(SHARED + b"png-art-2b" + source["text_payload"])
    MODULE.verify_census(census)
    # An id set that is not the frozen one refuses before any object is counted.
    monkeypatch.setattr(MODULE, "PROTECTED_ITEM_SET_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="PROTECTED_ITEM_SET_SHA256_DRIFT_REFUSED"):
        MODULE.build_census(
            items=items, parquet_file_count=2, license_raw=_license, custody_manifest_raw=_custody,
            admitted_train_object_hashes=set(), admitted_heldout_image_hashes=already,
        )


def test_planted_train_hash_refuses_the_census(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match=f"TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:{sha(SHARED)}"):
        _census(monkeypatch, train={sha(SHARED)})
    items = MODULE.items_from_rows(ROWS)
    text_digest = items[0]["text_sha256"]
    with pytest.raises(ValueError, match=f"TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:{text_digest}"):
        _census(monkeypatch, train={text_digest})


def _synthetic_export(census: dict, dataset_ids: list[str], *, drop_one: bool = False) -> bytes:
    records = [{"kind": "dataset_version", "id": d, "state": "admitted"} for d in dataset_ids]
    edges = []
    objects = [("image", digest) for digest in census["image_objects"]]
    objects += [("text", item["item_text_object"]["sha256"]) for item in census["items"]]
    if drop_one:
        objects = objects[:-1]
    for index, (domain, digest) in enumerate(objects):
        dataset = dataset_ids[0] if domain == "image" else dataset_ids[-1]
        membership = f"membership:{domain}:{digest}"
        records.append({
            "kind": "membership", "id": membership, "split": "heldout",
            "domain": domain, "admission_state": "admitted",
        })
        edges.append({"kind": "version_membership", "from_id": dataset, "to_id": membership})
        edges.append({"kind": "membership_object", "from_id": membership, "to_id": f"sha256:{digest}", "ordinal": index})
    return json.dumps({"records": records, "edges": edges}).encode()


def test_artifacts_projection_and_contract_bind_the_referenced_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    items, custody_raw, license_raw, already, census = _census(monkeypatch)
    payloads = MODULE.payloads_from_items(items)
    plan = MODULE.build_admission_plan(
        census, payloads_by_sha=payloads, admitted_heldout_image_hashes=already
    )
    assert plan["admitted_object_count"] == 5
    assert [row["file_count"] for row in plan["rows"]] == [2, 3]
    assert all(row["path"].startswith("objects/") and row["path"].endswith(".png") for row in plan["image_files"])
    assert all(row["path"].startswith("items/") and row["path"].endswith(".json") for row in plan["text_files"])
    with pytest.raises(ValueError, match="SELECTED_IMAGE_PAYLOAD_DRIFT_REFUSED"):
        MODULE.build_admission_plan(
            census, payloads_by_sha={**payloads, sha(b"png-art-1"): b"tampered"},
            admitted_heldout_image_hashes=already,
        )

    custody = tmp_path / "custody"
    image_connector = tmp_path / "connector-images.json"
    text_connector = tmp_path / "connector-items.json"
    admission = tmp_path / "admission.json"
    image_raw, text_raw, admission_raw = MODULE.write_admission_artifacts(
        plan=plan, payloads_by_sha=payloads, license_raw=license_raw, custody_manifest_raw=custody_raw,
        output_root=custody, image_connector_path=image_connector, text_connector_path=text_connector,
        admission_receipt_path=admission, fetched_at="2026-09-05T10:00:00Z",
    )
    for raw, source_id, count in ((image_raw, MODULE.IMAGE_SOURCE_ID, 2), (text_raw, MODULE.TEXT_SOURCE_ID, 3)):
        connector = json.loads(raw)
        assert connector["schema"] == "corpus-connector-receipt-v1"
        assert connector["source_id"] == source_id
        assert len(connector["files"]) == count
        for row in connector["files"]:
            physical = Path(connector["dest_root"]) / row["path"]
            assert sha(physical.read_bytes()) == row["sha256"]
            assert physical.stat().st_size == row["bytes"]
    receipt = json.loads(admission_raw)
    assert receipt["image_connector_receipt_raw_sha256"] == sha(image_raw)
    assert receipt["text_connector_receipt_raw_sha256"] == sha(text_raw)
    with pytest.raises(ValueError, match="NO_OVERWRITE_REFUSED"):
        MODULE.write_admission_artifacts(
            plan=plan, payloads_by_sha=payloads, license_raw=license_raw, custody_manifest_raw=custody_raw,
            output_root=custody, image_connector_path=image_connector, text_connector_path=text_connector,
            admission_receipt_path=admission, fetched_at="2026-09-05T10:00:00Z",
        )

    census_path = tmp_path / "census.json"
    census_raw = json.dumps(census, sort_keys=True).encode()
    census_path.write_bytes(census_raw)
    custody_path = tmp_path / "custody.json"
    custody_path.write_bytes(custody_raw)
    license_path = tmp_path / "LICENSE"
    license_path.write_bytes(license_raw)
    spec = json.loads(MODULE.build_projection_spec(
        image_connector_path=image_connector, image_connector_raw=image_raw,
        text_connector_path=text_connector, text_connector_raw=text_raw,
        admission_receipt_path=admission, admission_receipt_raw=admission_raw,
        census_path=census_path, census_raw=census_raw, custody_manifest_path=custody_path,
        license_path=license_path, tokenizer_sha256="ab" * 32, created_at_ms=1,
    ))
    assert [row["domain"] for row in spec["rows"]] == ["image", "text"]
    assert [row["expected_source_selector"] for row in spec["rows"]] == [MODULE.IMAGE_SOURCE_ID, MODULE.TEXT_SOURCE_ID]
    assert all(row["split"] == "heldout" for row in spec["rows"])
    assert spec["rows"][0]["expected_receipt_sha256"] == sha(image_raw)

    predecessor_raw = json.dumps({
        "schema": "corpus-connector-receipt-v1",
        "source_id": MODULE.PREDECESSOR_IMAGE_SOURCE_ID,
        "dest_root": str(tmp_path),
        "files": [{"path": "shared.png", "bytes": len(SHARED), "sha256": sha(SHARED)}],
    }).encode()
    dataset_ids = ["dataset:images", "dataset:items"]
    contract = MODULE.build_image_text_contract(
        census, image_connector_raw=image_raw, text_connector_raw=text_raw,
        predecessor_connector_raw=predecessor_raw,
        catalog_export_raw=_synthetic_export(census, dataset_ids), dataset_ids=dataset_ids,
    )
    assert contract["schema_version"] == MODULE.CONTRACT_SCHEMA
    assert contract["task"]["id"] == MODULE.TASK_ID
    assert contract["task"]["forbidden_inputs"] == ["mmmu_answer_dictionary", "prediction_custody"]
    assert contract["totality"] == {"expected": 3, "observed": 3, "complete": True}
    assert contract["source"]["connector_receipt_raw_sha256s"] == sorted([sha(image_raw), sha(text_raw), sha(predecessor_raw)])
    assert contract["source"]["answer_dictionary_access"] == "identity_only; never_read"
    assert contract["catalog_binding"]["referenced_object_count"] == 6
    assert contract["catalog_binding"]["membership_count"] == 6
    frozen = {item["item_id"]: item for item in contract["frozen_items"]}
    assert frozen["validation_Art_2"]["gold_item_sha256"] == census["items"][1]["gold_item_sha256"]
    assert set(frozen["validation_Art_2"]["item_text_object"]) == {"sha256", "byte_count", "media_type"}
    body = dict(contract)
    assert body.pop("self_sha256") == sha(canonical(body))

    # Deliberate reds: a membership export short by one object refuses totality;
    # a predecessor receipt that does not cover the already-admitted set refuses.
    with pytest.raises(ValueError, match="IMAGE_TEXT_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED"):
        MODULE.build_image_text_contract(
            census, image_connector_raw=image_raw, text_connector_raw=text_raw,
            predecessor_connector_raw=predecessor_raw,
            catalog_export_raw=_synthetic_export(census, dataset_ids, drop_one=True), dataset_ids=dataset_ids,
        )
    with pytest.raises(ValueError, match="IMAGE_TEXT_PREDECESSOR_COVERAGE_REFUSED"):
        MODULE.build_image_text_contract(
            census, image_connector_raw=image_raw, text_connector_raw=text_raw,
            predecessor_connector_raw=predecessor_raw.replace(sha(SHARED).encode(), ("f" * 64).encode()),
        )
