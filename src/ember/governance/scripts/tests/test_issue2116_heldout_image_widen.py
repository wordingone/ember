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
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "issue2116_heldout_image_widen.py"
SPEC = importlib.util.spec_from_file_location("issue2116_heldout_image_widen", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def make_by_hash(monkeypatch: pytest.MonkeyPatch, count: int = 256) -> dict[str, dict]:
    """Build a synthetic unique-image pool whose first 64 rows (sorted by sha) reproduce the
    module's frozen PREDECESSOR_SELECTED_SET_SHA256, by freezing that constant to match the
    synthetic fixture instead of the real #2105 value (same technique test_issue2105 uses for
    CENSUS_RAW_SHA256/SELECTED_SET_SHA256: the module under test is monkeypatched to the
    fixture's own derived identity, so the drift assertion is exercised honestly)."""

    by_hash: dict[str, dict] = {}
    for index in range(count):
        raw = f"image-{index}".encode()
        digest = sha(raw)
        by_hash[digest] = {
            "subject": "Subject",
            "row_id": f"validation_Subject_{index}",
            "image_column": "image_1",
            "byte_count": len(raw),
            "exact_sha256": digest,
            "source_path": MODULE.source_path_for(f"validation_Subject_{index}", "image_1"),
            "source_revision": MODULE.MMMU_REVISION,
            "source_split": "validation",
        }
    ordered = sorted(by_hash.values(), key=lambda row: row["exact_sha256"])
    predecessor_sha = sha(canonical(ordered[: MODULE.EXPECTED_PREDECESSOR_COUNT]))
    monkeypatch.setattr(MODULE, "PREDECESSOR_SELECTED_SET_SHA256", predecessor_sha)
    monkeypatch.setattr(MODULE, "EXPECTED_UNIQUE_COUNT", count)
    monkeypatch.setattr(MODULE, "EXPECTED_SELECTED_COUNT", 256)
    return by_hash


def make_inputs(monkeypatch: pytest.MonkeyPatch) -> tuple[dict, bytes, bytes]:
    by_hash = make_by_hash(monkeypatch, count=256)
    license_raw = b"license\n"
    custody_raw = canonical({"upstream_url": "https://example.test/MMMU.git"})
    monkeypatch.setattr(MODULE, "LICENSE_SHA256", sha(license_raw))
    monkeypatch.setattr(MODULE, "CUSTODY_MANIFEST_SHA256", sha(custody_raw))
    return by_hash, license_raw, custody_raw


def payloads_for(by_hash: dict[str, dict], selected: list[dict]) -> dict[tuple[str, str, str], bytes]:
    # Recover the original raw bytes: fixture rows are named "image-{index}" and row_id encodes index.
    payloads = {}
    for row in selected:
        index = row["row_id"].rsplit("_", 1)[-1]
        raw = f"image-{index}".encode()
        assert sha(raw) == row["exact_sha256"]
        payloads[(row["subject"], row["row_id"], row["image_column"])] = raw
    return payloads


def test_census_selects_256_and_reproduces_predecessor_64(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    census = MODULE.build_census(
        by_hash=by_hash,
        occurrence_count=len(by_hash),
        parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
        admitted_train_object_hashes=set(),
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
    )
    assert census["result"] == "PASS"
    assert census["selected_count"] == 256
    assert len(census["selected"]) == 256
    predecessor = sha(canonical(census["selected"][:64]))
    assert predecessor == MODULE.PREDECESSOR_SELECTED_SET_SHA256
    assert census["train_overlap_count"] == 0
    body = dict(census)
    claimed = body.pop("self_sha256")
    assert claimed == sha(canonical(body))
    MODULE.verify_census(census)


def test_census_refuses_on_unique_count_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    # Unique count no longer matches EXPECTED_UNIQUE_COUNT once one row is dropped.
    dropped_key = next(iter(by_hash))
    del by_hash[dropped_key]
    with pytest.raises(ValueError, match="CENSUS_UNIQUE_COUNT_DRIFT_REFUSED"):
        MODULE.build_census(
            by_hash=by_hash,
            occurrence_count=len(by_hash),
            parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
            admitted_train_object_hashes=set(),
            license_raw=license_raw,
            custody_manifest_raw=custody_raw,
        )


def test_census_refuses_on_predecessor_selected_set_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    monkeypatch.setattr(MODULE, "PREDECESSOR_SELECTED_SET_SHA256", "f" * 64)
    with pytest.raises(ValueError, match="PREDECESSOR_SELECTED_SET_DRIFT_REFUSED"):
        MODULE.build_census(
            by_hash=by_hash,
            occurrence_count=len(by_hash),
            parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
            admitted_train_object_hashes=set(),
            license_raw=license_raw,
            custody_manifest_raw=custody_raw,
        )


def test_census_excludes_train_hashes_and_reports_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    # 300 unique candidates so excluding one still leaves >= 256 for selection; the
    # exclusion shifts every later hash into the first-64 window, which no longer
    # reproduces the frozen predecessor set — the correct refusal names the shift, not a
    # totality shortfall.
    by_hash = make_by_hash(monkeypatch, count=300)
    license_raw = b"license\n"
    custody_raw = canonical({"upstream_url": "https://example.test/MMMU.git"})
    monkeypatch.setattr(MODULE, "LICENSE_SHA256", sha(license_raw))
    monkeypatch.setattr(MODULE, "CUSTODY_MANIFEST_SHA256", sha(custody_raw))
    ordered = sorted(by_hash, key=lambda k: k)
    planted_train = {ordered[0]}

    baseline = MODULE.build_census(
        by_hash=by_hash, occurrence_count=len(by_hash),
        parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
        admitted_train_object_hashes=set(), license_raw=license_raw,
        custody_manifest_raw=custody_raw,
    )
    assert baseline["train_overlap_count"] == 0

    with pytest.raises(ValueError, match="PREDECESSOR_SELECTED_SET_DRIFT_REFUSED"):
        MODULE.build_census(
            by_hash=by_hash,
            occurrence_count=len(by_hash),
            parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
            admitted_train_object_hashes=planted_train,
            license_raw=license_raw,
            custody_manifest_raw=custody_raw,
        )


def test_census_refuses_on_license_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, _license_raw, custody_raw = make_inputs(monkeypatch)
    with pytest.raises(ValueError, match="LICENSE_SHA256_DRIFT_REFUSED"):
        MODULE.build_census(
            by_hash=by_hash,
            occurrence_count=len(by_hash),
            parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
            admitted_train_object_hashes=set(),
            license_raw=b"different license",
            custody_manifest_raw=custody_raw,
        )


def test_census_refuses_on_parquet_file_count_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    with pytest.raises(ValueError, match="MMMU_PARQUET_FILE_COUNT_REFUSED"):
        MODULE.build_census(
            by_hash=by_hash,
            occurrence_count=len(by_hash),
            parquet_file_count=29,
            admitted_train_object_hashes=set(),
            license_raw=license_raw,
            custody_manifest_raw=custody_raw,
        )


def test_admission_plan_binds_exact_256_and_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    census = MODULE.build_census(
        by_hash=by_hash,
        occurrence_count=len(by_hash),
        parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
        admitted_train_object_hashes=set(),
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
    )
    payloads = payloads_for(by_hash, census["selected"])
    plan = MODULE.build_admission_plan(
        census=census, admitted_train_object_hashes=set(), payloads_by_origin=payloads,
    )
    assert plan["selected_count"] == 256
    assert len(plan["files"]) == 256
    assert plan["predecessor_selected_set_sha256"] == MODULE.PREDECESSOR_SELECTED_SET_SHA256
    assert all(set(row) == {"path", "bytes", "sha256", "source"} for row in plan["files"])


def test_admission_plan_refuses_planted_train_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    census = MODULE.build_census(
        by_hash=by_hash,
        occurrence_count=len(by_hash),
        parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
        admitted_train_object_hashes=set(),
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
    )
    payloads = payloads_for(by_hash, census["selected"])
    planted = {census["selected"][0]["exact_sha256"]}
    with pytest.raises(ValueError, match="TRAIN_HELDOUT_IMAGE_OVERLAP_REFUSED"):
        MODULE.build_admission_plan(
            census=census, admitted_train_object_hashes=planted, payloads_by_origin=payloads,
        )


def test_admission_plan_refuses_payload_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    census = MODULE.build_census(
        by_hash=by_hash,
        occurrence_count=len(by_hash),
        parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
        admitted_train_object_hashes=set(),
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
    )
    payloads = payloads_for(by_hash, census["selected"])
    first = next(iter(payloads))
    payloads[first] = b"drift"
    with pytest.raises(ValueError, match="SELECTED_IMAGE_PAYLOAD_DRIFT_REFUSED"):
        MODULE.build_admission_plan(
            census=census, admitted_train_object_hashes=set(), payloads_by_origin=payloads,
        )


def test_contract_is_image_widen_v2_totality_256(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    census = MODULE.build_census(
        by_hash=by_hash,
        occurrence_count=len(by_hash),
        parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
        admitted_train_object_hashes=set(),
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
    )
    payloads = payloads_for(by_hash, census["selected"])
    plan = MODULE.build_admission_plan(
        census=census, admitted_train_object_hashes=set(), payloads_by_origin=payloads,
    )
    contract = MODULE.build_image_widen_contract(plan, connector_receipt_raw=b"connector")
    assert contract["schema_version"] == "ember-protected-image-contract-v2"
    assert contract["task"]["id"] == "EXACT_IMAGE_PAYLOAD_SHA256_IDENTITY"
    assert contract["task"]["forbidden_inputs"] == ["mmmu_question", "mmmu_answer", "mmmu_options"]
    assert contract["totality"] == {"expected": 256, "observed": 256, "complete": True}
    assert len(contract["frozen_items"]) == 256
    body = dict(contract)
    claimed = body.pop("self_sha256")
    assert claimed == sha(canonical(body))


def test_contract_catalog_binding_totality_and_train_overlap_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    census = MODULE.build_census(
        by_hash=by_hash,
        occurrence_count=len(by_hash),
        parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
        admitted_train_object_hashes=set(),
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
    )
    payloads = payloads_for(by_hash, census["selected"])
    plan = MODULE.build_admission_plan(
        census=census, admitted_train_object_hashes=set(), payloads_by_origin=payloads,
    )
    dataset_id = "dataset:issue2116-image-widen:" + "a" * 64
    records = [{"kind": "dataset_version", "id": dataset_id, "state": "admitted"}]
    edges = []
    for row in plan["files"]:
        membership_id = f"membership:mmmu-validation-heldout-image-256:{row['sha256']}"
        records.append({
            "kind": "membership", "id": membership_id, "split": "heldout",
            "domain": "image", "admission_state": "admitted",
        })
        edges.extend([
            {"kind": "version_membership", "from_id": dataset_id, "to_id": membership_id},
            {"kind": "membership_object", "from_id": membership_id, "to_id": f"sha256:{row['sha256']}"},
        ])
    catalog_raw = canonical({"records": records, "edges": edges})
    contract = MODULE.build_image_widen_contract(
        plan, connector_receipt_raw=b"connector", catalog_export_raw=catalog_raw, dataset_id=dataset_id,
    )
    assert contract["catalog_binding"]["membership_count"] == 256
    assert contract["catalog_binding"]["train_exclusion"]["overlap_count"] == 0

    # Planted negative: one of the 256 objects also carries an admitted TRAIN membership
    # elsewhere in the export -> post-import intersection audit must refuse.
    poisoned_object = f"sha256:{plan['files'][0]['sha256']}"
    train_membership_id = "membership:some-train-row:poison"
    records.append({
        "kind": "membership", "id": train_membership_id, "split": "train",
        "domain": "image", "admission_state": "admitted",
    })
    edges.append({"kind": "membership_object", "from_id": train_membership_id, "to_id": poisoned_object})
    poisoned_catalog_raw = canonical({"records": records, "edges": edges})
    with pytest.raises(ValueError, match="IMAGE_TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED"):
        MODULE.build_image_widen_contract(
            plan, connector_receipt_raw=b"connector",
            catalog_export_raw=poisoned_catalog_raw, dataset_id=dataset_id,
        )

    # Planted negative: dropping one membership_object edge breaks totality coverage.
    edges_missing_one = [e for e in edges if not (
        e.get("kind") == "membership_object" and e.get("to_id") == f"sha256:{plan['files'][1]['sha256']}"
    )]
    with pytest.raises(ValueError, match="IMAGE_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED"):
        MODULE.build_image_widen_contract(
            plan, connector_receipt_raw=b"connector",
            catalog_export_raw=canonical({"records": records, "edges": edges_missing_one}),
            dataset_id=dataset_id,
        )


def test_admission_artifacts_are_content_addressed_self_hashed_and_no_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    census = MODULE.build_census(
        by_hash=by_hash,
        occurrence_count=len(by_hash),
        parquet_file_count=MODULE.EXPECTED_PARQUET_FILE_COUNT,
        admitted_train_object_hashes=set(),
        license_raw=license_raw,
        custody_manifest_raw=custody_raw,
    )
    payloads = payloads_for(by_hash, census["selected"])
    plan = MODULE.build_admission_plan(
        census=census, admitted_train_object_hashes=set(), payloads_by_origin=payloads,
    )
    root = tmp_path / "custody"
    connector_path = tmp_path / "connector.json"
    admission_path = tmp_path / "admission.json"
    connector_raw, admission_raw = MODULE.write_admission_artifacts(
        plan=plan, payloads_by_origin=payloads, license_raw=license_raw,
        custody_manifest_raw=custody_raw, output_root=root,
        connector_receipt_path=connector_path, admission_receipt_path=admission_path,
        fetched_at="2026-09-05T00:00:00Z",
    )
    connector = json.loads(connector_raw)
    admission = json.loads(admission_raw)
    assert len(connector["files"]) == 256
    assert all((root / row["path"]).read_bytes() for row in connector["files"])
    assert admission["connector_receipt_raw_sha256"] == sha(connector_raw)
    body = dict(admission)
    claimed = body.pop("self_sha256")
    assert claimed == sha(canonical(body))
    with pytest.raises(ValueError, match="NO_OVERWRITE_REFUSED"):
        MODULE.write_admission_artifacts(
            plan=plan, payloads_by_origin=payloads, license_raw=license_raw,
            custody_manifest_raw=custody_raw, output_root=root,
            connector_receipt_path=connector_path, admission_receipt_path=admission_path,
            fetched_at="2026-09-05T00:00:00Z",
        )
    census_path = tmp_path / "census.json"
    census_raw = json.dumps(census, sort_keys=True, indent=2).encode() + b"\n"
    census_path.write_bytes(census_raw)
    spec = json.loads(MODULE.build_projection_spec(
        connector_receipt_path=connector_path, connector_receipt_raw=connector_raw,
        admission_receipt_path=admission_path, admission_receipt_raw=admission_raw,
        census_path=census_path, census_raw=census_raw,
        custody_manifest_path=tmp_path / "custody.json", license_path=tmp_path / "LICENSE",
        tokenizer_sha256="a" * 64, created_at_ms=0,
    ))
    row = spec["rows"][0]
    assert row["source_id"] == "candidate-image-heldout-widen-0"
    assert row["split"] == "heldout"
    assert row["domain"] == "image"
    assert row["expected_receipt_sha256"] == sha(connector_raw)
    assert len(row["supporting_receipts"]) == 4


def test_second_source_census_is_census_only_and_refuses_train_overlap() -> None:
    hashes = {sha(f"second-{i}".encode()) for i in range(10)}
    census = MODULE.build_second_source_census(
        source_id="candidate-second-image-source-0",
        license_raw=b"license text\n",
        revision="deadbeef",
        unique_hashes=hashes,
        admitted_train_object_hashes=set(),
    )
    assert census["schema_version"] == "ember-issue2116-second-source-census-v1"
    assert census["admission"] == "census_only; no custody created"
    assert census["unique_hash_count"] == 10
    body = dict(census)
    claimed = body.pop("self_sha256")
    assert claimed == sha(canonical(body))

    poisoned_train = {next(iter(hashes))}
    with pytest.raises(ValueError, match="SECOND_SOURCE_TRAIN_INTERSECTION_REFUSED"):
        MODULE.build_second_source_census(
            source_id="candidate-second-image-source-0", license_raw=b"license text\n",
            revision="deadbeef", unique_hashes=hashes,
            admitted_train_object_hashes=poisoned_train,
        )


def test_determinism_two_builds_are_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    by_hash, license_raw, custody_raw = make_inputs(monkeypatch)
    kwargs = {
        "by_hash": by_hash, "occurrence_count": len(by_hash),
        "parquet_file_count": MODULE.EXPECTED_PARQUET_FILE_COUNT,
        "admitted_train_object_hashes": set(), "license_raw": license_raw,
        "custody_manifest_raw": custody_raw,
    }
    census_a = MODULE.build_census(**kwargs)
    census_b = MODULE.build_census(**kwargs)
    assert canonical(census_a) == canonical(census_b)
    payloads = payloads_for(by_hash, census_a["selected"])
    plan_a = MODULE.build_admission_plan(census=census_a, admitted_train_object_hashes=set(), payloads_by_origin=payloads)
    plan_b = MODULE.build_admission_plan(census=census_b, admitted_train_object_hashes=set(), payloads_by_origin=payloads)
    assert canonical(plan_a) == canonical(plan_b)
    contract_a = MODULE.build_image_widen_contract(plan_a, connector_receipt_raw=b"connector")
    contract_b = MODULE.build_image_widen_contract(plan_b, connector_receipt_raw=b"connector")
    assert canonical(contract_a) == canonical(contract_b)
