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
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "issue2105_heldout_image.py"
SPEC = importlib.util.spec_from_file_location("issue2105_heldout_image", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def make_inputs(monkeypatch: pytest.MonkeyPatch) -> tuple[bytes, bytes, bytes, dict[tuple[str, str, str], bytes]]:
    license_raw = b"license\n"
    custody_raw = canonical({
        "upstream_url": "https://example.test/MMMU.git",
        "split": {"eligible_id_set_sha256": MODULE.PROTECTED_ITEM_SET_SHA256},
    })
    license_sha = hashlib.sha256(license_raw).hexdigest()
    custody_sha = hashlib.sha256(custody_raw).hexdigest()
    selected = []
    payloads = {}
    for index in range(64):
        raw = f"image-{index}".encode()
        digest = hashlib.sha256(raw).hexdigest()
        row = {
            "byte_count": len(raw),
            "exact_sha256": digest,
            "image_column": "image_1",
            "row_id": f"validation_Subject_{index}",
            "source_path": f"validation_Subject_{index}_1.png",
            "source_revision": MODULE.MMMU_REVISION,
            "source_split": "validation",
            "subject": "Subject",
        }
        selected.append(row)
        payloads[("Subject", row["row_id"], "image_1")] = raw
    selected.sort(key=lambda row: row["exact_sha256"])
    census = {
        "schema_version": MODULE.CENSUS_SCHEMA,
        "result": "PASS",
        "source": {
            "name": "MMMU",
            "revision": MODULE.MMMU_REVISION,
            "split": "validation",
            "custody_manifest_sha256": custody_sha,
            "item_set_sha256": MODULE.PROTECTED_ITEM_SET_SHA256,
            "license_sha256": license_sha,
        },
        "catalog": {"admitted_train_image_object_count": 1755},
        "parquet_file_count": 30,
        "image_occurrence_count": 982,
        "unique_image_count": 959,
        "train_overlap_count": 0,
        "selection_rule": MODULE.SELECTION_RULE,
        "selected_count": 64,
        "selected": selected,
    }
    census["selected_set_sha256"] = hashlib.sha256(canonical(selected)).hexdigest()
    census["self_sha256"] = hashlib.sha256(canonical(census)).hexdigest()
    census_raw = json.dumps(census, sort_keys=True, indent=2).encode() + b"\n"
    monkeypatch.setattr(MODULE, "CENSUS_RAW_SHA256", hashlib.sha256(census_raw).hexdigest())
    monkeypatch.setattr(MODULE, "CENSUS_SELF_SHA256", census["self_sha256"])
    monkeypatch.setattr(MODULE, "SELECTED_SET_SHA256", census["selected_set_sha256"])
    monkeypatch.setattr(MODULE, "LICENSE_SHA256", license_sha)
    monkeypatch.setattr(MODULE, "CUSTODY_MANIFEST_SHA256", custody_sha)
    return census_raw, license_raw, custody_raw, payloads


def test_admission_plan_binds_exact_64_and_never_reads_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    census_raw, license_raw, custody_raw, payloads = make_inputs(monkeypatch)
    plan = MODULE.build_admission_plan(
        census_raw=census_raw,
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
        admitted_train_image_hashes=set(),
        payloads_by_origin=payloads,
    )
    assert plan["selected_count"] == 64
    assert plan["selected_set_sha256"] == MODULE.SELECTED_SET_SHA256
    assert len(plan["files"]) == 64
    assert all(set(row) == {"path", "bytes", "sha256", "source"} for row in plan["files"])
    assert all(set(row["source"]) == {"subject", "row_id", "image_column"} for row in plan["files"])


def test_admission_plan_planted_train_overlap_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    census_raw, license_raw, custody_raw, payloads = make_inputs(monkeypatch)
    planted = {next(iter(payloads.values()))}
    planted_hashes = {hashlib.sha256(value).hexdigest() for value in planted}
    with pytest.raises(ValueError, match="TRAIN_HELDOUT_IMAGE_OVERLAP_REFUSED"):
        MODULE.build_admission_plan(
            census_raw=census_raw,
            license_raw=license_raw,
            custody_manifest_raw=custody_raw,
            admitted_train_image_hashes=planted_hashes,
            payloads_by_origin=payloads,
        )


def test_admission_plan_refuses_payload_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    census_raw, license_raw, custody_raw, payloads = make_inputs(monkeypatch)
    first = next(iter(payloads))
    payloads[first] = b"drift"
    with pytest.raises(ValueError, match="SELECTED_IMAGE_PAYLOAD_DRIFT_REFUSED"):
        MODULE.build_admission_plan(
            census_raw=census_raw,
            license_raw=license_raw,
            custody_manifest_raw=custody_raw,
            admitted_train_image_hashes=set(),
            payloads_by_origin=payloads,
        )


def test_contract_is_image_only_and_binds_membership_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    census_raw, license_raw, custody_raw, payloads = make_inputs(monkeypatch)
    plan = MODULE.build_admission_plan(
        census_raw=census_raw,
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
        admitted_train_image_hashes=set(),
        payloads_by_origin=payloads,
    )
    contract = MODULE.build_image_only_contract(plan, connector_receipt_raw=b"connector")
    assert contract["task_class"] == "adapter_totality"
    assert contract["task"]["id"] == "EXACT_IMAGE_PAYLOAD_SHA256_IDENTITY"
    assert contract["task"]["consumes"] == ["image_payload_bytes"]
    assert contract["task"]["forbidden_inputs"] == ["mmmu_question", "mmmu_answer", "mmmu_options"]
    assert len(contract["frozen_items"]) == 64
    body = dict(contract)
    claimed = body.pop("self_sha256")
    assert claimed == hashlib.sha256(canonical(body)).hexdigest()


def test_admission_artifacts_are_content_addressed_self_hashed_and_no_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    census_raw, license_raw, custody_raw, payloads = make_inputs(monkeypatch)
    plan = MODULE.build_admission_plan(
        census_raw=census_raw,
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
        admitted_train_image_hashes=set(),
        payloads_by_origin=payloads,
    )
    root = tmp_path / "custody"
    connector_path = tmp_path / "connector.json"
    admission_path = tmp_path / "admission.json"
    connector_raw, admission_raw = MODULE.write_admission_artifacts(
        plan=plan,
        payloads_by_origin=payloads,
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
        output_root=root,
        connector_receipt_path=connector_path,
        admission_receipt_path=admission_path,
        fetched_at="2026-09-04T17:00:00Z",
    )
    connector = json.loads(connector_raw)
    admission = json.loads(admission_raw)
    assert len(connector["files"]) == 64
    assert all((root / row["path"]).read_bytes() for row in connector["files"])
    assert admission["connector_receipt_raw_sha256"] == hashlib.sha256(connector_raw).hexdigest()
    body = dict(admission)
    claimed = body.pop("self_sha256")
    assert claimed == hashlib.sha256(canonical(body)).hexdigest()
    with pytest.raises(ValueError, match="NO_OVERWRITE_REFUSED"):
        MODULE.write_admission_artifacts(
            plan=plan,
            payloads_by_origin=payloads,
            license_raw=license_raw,
            custody_manifest_raw=custody_raw,
            output_root=root,
            connector_receipt_path=connector_path,
            admission_receipt_path=admission_path,
            fetched_at="2026-09-04T17:00:00Z",
        )
    spec = json.loads(MODULE.build_projection_spec(
        connector_receipt_path=connector_path,
        connector_receipt_raw=connector_raw,
        admission_receipt_path=admission_path,
        admission_receipt_raw=admission_raw,
        census_path=tmp_path / "census.json",
        custody_manifest_path=tmp_path / "custody.json",
        license_path=tmp_path / "LICENSE",
        tokenizer_sha256="a" * 64,
        created_at_ms=0,
    ))
    row = spec["rows"][0]
    assert row["source_id"] == "candidate-image-heldout-0"
    assert row["split"] == "heldout"
    assert row["domain"] == "image"
    assert row["expected_receipt_sha256"] == hashlib.sha256(connector_raw).hexdigest()
    assert len(row["supporting_receipts"]) == 4


def test_contract_binds_exact_catalog_membership_set(monkeypatch: pytest.MonkeyPatch) -> None:
    census_raw, license_raw, custody_raw, payloads = make_inputs(monkeypatch)
    plan = MODULE.build_admission_plan(
        census_raw=census_raw,
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
        admitted_train_image_hashes=set(),
        payloads_by_origin=payloads,
    )
    dataset_id = "dataset:issue1581-bulk-heldout:" + "a" * 64
    records = [{"kind": "dataset_version", "id": dataset_id, "state": "admitted"}]
    edges = []
    for row in plan["files"]:
        membership_id = f"membership:mmmu-validation-heldout-image-64:{row['sha256']}"
        records.append({
            "kind": "membership", "id": membership_id, "split": "heldout",
            "domain": "image", "admission_state": "admitted",
        })
        edges.extend([
            {"kind": "version_membership", "from_id": dataset_id, "to_id": membership_id},
            {"kind": "membership_object", "from_id": membership_id,
             "to_id": f"sha256:{row['sha256']}"},
        ])
    catalog_raw = canonical({"records": records, "edges": edges})
    contract = MODULE.build_image_only_contract(
        plan,
        connector_receipt_raw=b"connector",
        catalog_export_raw=catalog_raw,
        dataset_id=dataset_id,
    )
    assert contract["catalog_binding"]["dataset_id"] == dataset_id
    assert contract["catalog_binding"]["membership_count"] == 64
    edges.pop()
    with pytest.raises(ValueError, match="IMAGE_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED"):
        MODULE.build_image_only_contract(
            plan,
            connector_receipt_raw=b"connector",
            catalog_export_raw=canonical({"records": records, "edges": edges}),
            dataset_id=dataset_id,
        )
