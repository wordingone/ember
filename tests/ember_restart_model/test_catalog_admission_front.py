# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""RED-first contract for the #1581 bulk catalog-admission consumer."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from catalog_admission import (
    build_consumer_catalog_fragment,
    build_dataset_catalog_manifest,
    finalize_catalog_admission,
    project_catalog_spec,
    revalidate_e_matrix_catalog_bindings,
    write_new,
)
from catalog_admission import (
    main as catalog_main,
)
from domain_manifest import load_bulk_domain_connector_receipt
from input_identity import (
    InputIdentityError,
    resolve_catalog_training_datasets,
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def write_connector(
    root: Path, *, source: str, domain: str, files: list[tuple[str, bytes]]
) -> tuple[Path, str]:
    rows = []
    for name, raw in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        rows.append({"path": name, "bytes": len(raw), "sha256": sha256(raw)})
    payload = {
        "canonical_url": f"https://example.test/{source}",
        "connector": {"name": "fixture", "version": "v1"},
        "fetched_at": "2026-08-28T00:00:00Z",
        "files": rows,
        "license": "CC-BY-4.0",
        "schema": "corpus-connector-receipt-v1",
        "sha256_manifest": sha256(
            "\n".join(sorted(row["sha256"] for row in rows)).encode()
        ),
        "source": "fixture",
        "source_id": source,
        "total_bytes": sum(row["bytes"] for row in rows),
        "dest_root": str(root),
    }
    path = root / f"{domain}-connector.json"
    path.write_bytes(canonical(payload))
    return path, sha256(path.read_bytes())


def import_receipt(
    *,
    manifest_raw: bytes,
    canonical_export: bytes,
    inserted_records: int,
    inserted_edges: int,
) -> bytes:
    value = {
        "schema_version": "ember-data-catalog-import-receipt-v1",
        "result": "PASS",
        "source_commit": "1" * 40,
        "ember_lab_source_sha256": "2" * 64,
        "ember_lab_binary_sha256": "3" * 64,
        "input_manifest_raw_sha256": sha256(manifest_raw),
        "canonical_manifest_sha256": sha256(manifest_raw),
        "canonical_export_sha256": sha256(canonical_export),
        "inserted_records": inserted_records,
        "inserted_edges": inserted_edges,
    }
    value["self_sha256"] = sha256(canonical(value))
    return canonical(value)


@pytest.mark.parametrize("substituted_leg", ["projection", "consumer"])
def test_finalizer_refuses_projection_or_consumer_manifest_substitution(
    substituted_leg: str,
) -> None:
    projection = canonical({"projection": "bound"})
    consumer = canonical({"consumer": "bound"})
    export = canonical(
        {
            "schema_version": "ember-data-catalog-manifest-v1",
            "records": [],
            "edges": [],
        }
    )
    first_receipt = import_receipt(
        manifest_raw=projection,
        canonical_export=export,
        inserted_records=1,
        inserted_edges=1,
    )
    replay_receipt = import_receipt(
        manifest_raw=projection,
        canonical_export=export,
        inserted_records=0,
        inserted_edges=0,
    )
    consumer_receipt = import_receipt(
        manifest_raw=consumer,
        canonical_export=export,
        inserted_records=1,
        inserted_edges=1,
    )
    supplied_projection = (
        canonical({"projection": "substituted"})
        if substituted_leg == "projection"
        else projection
    )
    supplied_consumer = (
        canonical({"consumer": "substituted"})
        if substituted_leg == "consumer"
        else consumer
    )

    with pytest.raises(ValueError, match="input manifest"):
        finalize_catalog_admission(
            projection_manifest_raw=supplied_projection,
            first_import_receipt_raw=first_receipt,
            replay_import_receipt_raw=replay_receipt,
            first_catalog_export_raw=export,
            replay_catalog_export_raw=export,
            consumer_fragment_raw=supplied_consumer,
            consumer_import_receipt_raw=consumer_receipt,
            final_catalog_export_raw=export,
            e_matrix_packet_raw=canonical({"rows": []}),
            e_matrix_revalidation_raw=canonical({}),
            expected_dataset_id="dataset:substitution-probe",
        )


def test_projects_two_bulk_rows_into_one_path_free_admitted_train_dataset(
    tmp_path: Path,
) -> None:
    row1_path, row1_sha = write_connector(
        tmp_path,
        source="candidate-mathematics-train-1",
        domain="mathematics",
        files=[("a.pdf", b"pdf-a"), ("b.pdf", b"pdf-b")],
    )
    row3_path, row3_sha = write_connector(
        tmp_path,
        source="candidate-statistics-train-1",
        domain="statistics",
        files=[("c.pdf", b"pdf-c")],
    )
    rows = [
        load_bulk_domain_connector_receipt(
            receipt_path=row1_path,
            expected_receipt_sha256=row1_sha,
            source_id="candidate-mathematics-train-1",
            expected_source_selector="candidate-mathematics-train-1",
            expected_license_text_sha256=sha256(b"CC-BY-4.0"),
            domain="mathematics",
            split="train",
        ),
        load_bulk_domain_connector_receipt(
            receipt_path=row3_path,
            expected_receipt_sha256=row3_sha,
            source_id="candidate-statistics-train-1",
            expected_source_selector="candidate-statistics-train-1",
            expected_license_text_sha256=sha256(b"CC-BY-4.0"),
            domain="statistics",
            split="train",
        ),
    ]
    manifest_raw = build_dataset_catalog_manifest(
        rows=rows,
        tokenizer_sha256="4" * 64,
        created_at_ms=1,
    )
    manifest = json.loads(manifest_raw)
    assert manifest["schema_version"] == "ember-data-catalog-manifest-v1"
    assert b":\\" not in manifest_raw and b"B:/" not in manifest_raw
    datasets = [row for row in manifest["records"] if row["kind"] == "dataset_version"]
    memberships = [row for row in manifest["records"] if row["kind"] == "membership"]
    assert len(datasets) == 1 and datasets[0]["state"] == "admitted"
    assert len(memberships) == 3
    assert {row["domain"] for row in memberships} == {"mathematics", "statistics"}
    assert {row["split"] for row in memberships} == {"train"}
    assert {row["admission_state"] for row in memberships} == {"admitted"}


def test_projects_one_heldout_slot_without_mislabeling_it_as_train(
    tmp_path: Path,
) -> None:
    connector_path, connector_sha = write_connector(
        tmp_path,
        source="candidate-mathematics-heldout-0",
        domain="mathematics",
        files=[("heldout.pdf.txt", b"heldout text")],
    )
    row = load_bulk_domain_connector_receipt(
        receipt_path=connector_path,
        expected_receipt_sha256=connector_sha,
        source_id="candidate-mathematics-heldout-0",
        expected_source_selector="candidate-mathematics-heldout-0",
        expected_license_text_sha256=sha256(b"CC-BY-4.0"),
        domain="mathematics",
        split="heldout",
    )
    manifest_raw = build_dataset_catalog_manifest(
        rows=[row], tokenizer_sha256="4" * 64, created_at_ms=1
    )
    manifest = json.loads(manifest_raw)
    dataset = next(row for row in manifest["records"] if row["kind"] == "dataset_version")
    memberships = [row for row in manifest["records"] if row["kind"] == "membership"]
    assert dataset["id"].startswith("dataset:issue1581-bulk-heldout:")
    assert dataset["name"] == "issue1581-bulk-heldout-front"
    assert {row["split"] for row in memberships} == {"heldout"}
    objects = [row for row in manifest["records"] if row["kind"] == "immutable_object"]
    assert {row["media_type"] for row in objects} == {"text/plain; charset=utf-8"}

    mislabeled = dict(row)
    mislabeled["split"] = "train"
    with pytest.raises(ValueError, match="source identity split"):
        build_dataset_catalog_manifest(
            rows=[mislabeled], tokenizer_sha256="4" * 64, created_at_ms=1
        )

    first_receipt = import_receipt(
        manifest_raw=manifest_raw,
        canonical_export=manifest_raw,
        inserted_records=len(manifest["records"]),
        inserted_edges=len(manifest["edges"]),
    )
    e_matrix = canonical(
        {
            "schema_version": "ember-issue1581-slot-e-matrix-definition-v1",
            "rows": [
                {
                    "row_id": "candidate-mathematics-heldout-0",
                    "state": "ABSENT",
                }
            ],
        }
    )
    consumer_fragment = build_consumer_catalog_fragment(
        catalog_export_raw=manifest_raw,
        first_import_receipt_raw=first_receipt,
        dataset_id=dataset["id"],
        e_matrix_packet_raw=e_matrix,
        source_commit="1" * 40,
        model_sha256="5" * 64,
        checkpoint_sha256="6" * 64,
        tokenizer_sha256="4" * 64,
        config_sha256="7" * 64,
        evaluator_sha256="8" * 64,
    )
    combined = json.loads(manifest_raw)
    fragment = json.loads(consumer_fragment)
    combined["records"].extend(fragment["records"])
    combined["edges"].extend(fragment["edges"])
    shared_object_id = next(
        row["id"] for row in combined["records"] if row["kind"] == "immutable_object"
    )
    combined["records"].append(
        {
            "kind": "source",
            "id": "source:unrelated-mathematics-heldout-9",
            "license_verdict": "accepted",
        }
    )
    combined["edges"].append(
        {
            "kind": "source_object",
            "from_kind": "source",
            "from_id": "source:unrelated-mathematics-heldout-9",
            "to_kind": "immutable_object",
            "to_id": shared_object_id,
            "ordinal": 0,
            "payload": {},
        }
    )
    combined_raw = canonical(combined)
    consumer_receipt = import_receipt(
        manifest_raw=consumer_fragment,
        canonical_export=combined_raw,
        inserted_records=len(fragment["records"]),
        inserted_edges=len(fragment["edges"]),
    )
    resolved = resolve_catalog_training_datasets(
        catalog_export_raw=combined_raw,
        dataset_import_receipt_raw=first_receipt,
        consumer_import_receipt_raw=consumer_receipt,
        expected_dataset_id=dataset["id"],
        expected_split="heldout",
    )
    assert resolved["split"] == "heldout"
    assert resolved["source_ids"] == ["candidate-mathematics-heldout-0"]
    assert resolved["protected_eval_item_admission"] is False
    revalidation = revalidate_e_matrix_catalog_bindings(
        e_matrix_packet_raw=e_matrix, resolved_identity=resolved
    )
    row = revalidation["rows"][0]
    assert row["row_id"] == "candidate-mathematics-heldout-0"
    assert row["state"] == "PRESENT"
    assert row["catalog_dataset_binding"] == "PRESENT"
    assert row["catalog_dataset_split"] == "heldout"
    assert "catalog_train_dataset_binding" not in row
    assert row["protected"] is False
    assert row["protected_eval_admission_satisfied"] is False

    wrong_slot = canonical(
        {
            "schema_version": "ember-issue1581-slot-e-matrix-definition-v1",
            "rows": [{"row_id": "candidate-mathematics-heldout-1", "state": "ABSENT"}],
        }
    )
    with pytest.raises(ValueError, match="slot row does not match"):
        revalidate_e_matrix_catalog_bindings(
            e_matrix_packet_raw=wrong_slot, resolved_identity=resolved
        )

    multi_row = canonical(
        {
            "schema_version": "ember-issue1581-slot-e-matrix-definition-v1",
            "rows": [
                {"row_id": "candidate-mathematics-heldout-0", "state": "ABSENT"},
                {"row_id": "candidate-mathematics-heldout-1", "state": "ABSENT"},
            ],
        }
    )
    with pytest.raises(ValueError, match="exactly one absent slot row"):
        revalidate_e_matrix_catalog_bindings(
            e_matrix_packet_raw=multi_row, resolved_identity=resolved
        )

    replay_receipt = import_receipt(
        manifest_raw=manifest_raw,
        canonical_export=manifest_raw,
        inserted_records=0,
        inserted_edges=0,
    )
    terminal = json.loads(
        finalize_catalog_admission(
            projection_manifest_raw=manifest_raw,
            first_import_receipt_raw=first_receipt,
            replay_import_receipt_raw=replay_receipt,
            first_catalog_export_raw=manifest_raw,
            replay_catalog_export_raw=manifest_raw,
            consumer_fragment_raw=consumer_fragment,
            consumer_import_receipt_raw=consumer_receipt,
            final_catalog_export_raw=combined_raw,
            e_matrix_packet_raw=e_matrix,
            e_matrix_revalidation_raw=canonical(revalidation),
            expected_dataset_id=dataset["id"],
        )
    )
    assert terminal["result"] == "PASS"
    assert terminal["protected_eval_item_admission"] is False


def test_consumer_reopens_only_catalog_derived_train_identity_and_preserves_eval_isolation(
    tmp_path: Path,
) -> None:
    connector_path, connector_sha = write_connector(
        tmp_path,
        source="candidate-mathematics-train-1",
        domain="mathematics",
        files=[("a.pdf", b"pdf-a")],
    )
    row = load_bulk_domain_connector_receipt(
        receipt_path=connector_path,
        expected_receipt_sha256=connector_sha,
        source_id="candidate-mathematics-train-1",
        expected_source_selector="candidate-mathematics-train-1",
        expected_license_text_sha256=sha256(b"CC-BY-4.0"),
        domain="mathematics",
        split="train",
    )
    dataset_manifest = build_dataset_catalog_manifest(
        rows=[row], tokenizer_sha256="4" * 64, created_at_ms=1
    )
    dataset_export = dataset_manifest
    first_receipt = import_receipt(
        manifest_raw=dataset_manifest,
        canonical_export=dataset_export,
        inserted_records=len(json.loads(dataset_manifest)["records"]),
        inserted_edges=len(json.loads(dataset_manifest)["edges"]),
    )
    dataset_id = next(
        item["id"]
        for item in json.loads(dataset_export)["records"]
        if item["kind"] == "dataset_version"
    )
    e_matrix = canonical(
        {
            "schema_version": "ember-e-matrix-definition-v1",
            "rows": [
                {
                    "row_id": "E-MATRIX-IMAGE-TEXT",
                    "state": "PARTIAL",
                    "missing_predicates": [
                        "MISSING_1581_ADMISSION_BINDING_FOR_MMMU_ITEMS"
                    ],
                }
            ],
        }
    )
    consumer_fragment = build_consumer_catalog_fragment(
        catalog_export_raw=dataset_export,
        first_import_receipt_raw=first_receipt,
        dataset_id=dataset_id,
        e_matrix_packet_raw=e_matrix,
        source_commit="1" * 40,
        model_sha256="5" * 64,
        checkpoint_sha256="6" * 64,
        tokenizer_sha256="4" * 64,
        config_sha256="7" * 64,
        evaluator_sha256="8" * 64,
    )
    combined = json.loads(dataset_export)
    fragment = json.loads(consumer_fragment)
    combined["records"].extend(fragment["records"])
    combined["edges"].extend(fragment["edges"])
    combined_raw = canonical(combined)
    second_receipt = import_receipt(
        manifest_raw=consumer_fragment,
        canonical_export=combined_raw,
        inserted_records=len(fragment["records"]),
        inserted_edges=len(fragment["edges"]),
    )

    resolved = resolve_catalog_training_datasets(
        catalog_export_raw=combined_raw,
        dataset_import_receipt_raw=first_receipt,
        consumer_import_receipt_raw=second_receipt,
        expected_dataset_id=dataset_id,
    )
    assert resolved["dataset_id"] == dataset_id
    assert resolved["split"] == "train"
    assert resolved["protected_eval_item_admission"] is False
    assert resolved["object_count"] == 1

    historical = json.loads(combined_raw)
    historical_dataset_id = "dataset:historical:" + "9" * 64
    historical_consumer_id = "attempt:historical:" + "a" * 64
    historical["records"].extend(
        [
            {
                **next(
                    item
                    for item in historical["records"]
                    if item["kind"] == "dataset_version"
                ),
                "id": historical_dataset_id,
            },
            {
                **next(
                    item
                    for item in historical["records"]
                    if item["kind"] == "consumer_attempt"
                ),
                "id": historical_consumer_id,
                "run_attempt_id": historical_consumer_id,
            },
        ]
    )
    historical["edges"].append(
        {
            "kind": "consumer_dataset",
            "from_kind": "consumer_attempt",
            "from_id": historical_consumer_id,
            "to_kind": "dataset_version",
            "to_id": historical_dataset_id,
            "ordinal": 0,
            "payload": {},
        }
    )
    historical_raw = canonical(historical)
    historical_receipt = import_receipt(
        manifest_raw=consumer_fragment,
        canonical_export=historical_raw,
        inserted_records=2,
        inserted_edges=1,
    )
    historical_resolved = resolve_catalog_training_datasets(
        catalog_export_raw=historical_raw,
        dataset_import_receipt_raw=first_receipt,
        consumer_import_receipt_raw=historical_receipt,
        expected_dataset_id=dataset_id,
    )
    assert historical_resolved["dataset_id"] == dataset_id

    duplicate = json.loads(historical_raw)
    duplicate_consumer_id = "attempt:duplicate:" + "b" * 64
    duplicate["records"].append(
        {
            **next(
                item
                for item in duplicate["records"]
                if item["kind"] == "consumer_attempt"
            ),
            "id": duplicate_consumer_id,
            "run_attempt_id": duplicate_consumer_id,
        }
    )
    duplicate["edges"].append(
        {
            "kind": "consumer_dataset",
            "from_kind": "consumer_attempt",
            "from_id": duplicate_consumer_id,
            "to_kind": "dataset_version",
            "to_id": dataset_id,
            "ordinal": 0,
            "payload": {},
        }
    )
    duplicate_raw = canonical(duplicate)
    duplicate_receipt = import_receipt(
        manifest_raw=consumer_fragment,
        canonical_export=duplicate_raw,
        inserted_records=1,
        inserted_edges=1,
    )
    with pytest.raises(InputIdentityError, match="catalog_dataset_substitution"):
        resolve_catalog_training_datasets(
            catalog_export_raw=duplicate_raw,
            dataset_import_receipt_raw=first_receipt,
            consumer_import_receipt_raw=duplicate_receipt,
            expected_dataset_id=dataset_id,
        )

    revalidation = revalidate_e_matrix_catalog_bindings(
        e_matrix_packet_raw=e_matrix, resolved_identity=resolved
    )
    assert revalidation["rows"][0]["catalog_train_dataset_binding"] == "PRESENT"
    assert revalidation["rows"][0]["protected_eval_admission_satisfied"] is False
    assert revalidation["rows"][0]["state"] == "PARTIAL"
    assert revalidation["rows"][0]["missing_predicates"] == [
        "MISSING_1581_ADMISSION_BINDING_FOR_MMMU_ITEMS"
    ]

    replay_receipt = import_receipt(
        manifest_raw=dataset_manifest,
        canonical_export=dataset_export,
        inserted_records=0,
        inserted_edges=0,
    )
    revalidation_raw = canonical(revalidation)
    terminal_raw = finalize_catalog_admission(
        projection_manifest_raw=dataset_manifest,
        first_import_receipt_raw=first_receipt,
        replay_import_receipt_raw=replay_receipt,
        first_catalog_export_raw=dataset_export,
        replay_catalog_export_raw=dataset_export,
        consumer_fragment_raw=consumer_fragment,
        consumer_import_receipt_raw=second_receipt,
        final_catalog_export_raw=combined_raw,
        e_matrix_packet_raw=e_matrix,
        e_matrix_revalidation_raw=revalidation_raw,
        expected_dataset_id=dataset_id,
    )
    terminal = json.loads(terminal_raw)
    claimed_terminal_self = terminal.pop("self_sha256")
    assert claimed_terminal_self == sha256(canonical(terminal))
    assert terminal["result"] == "PASS"
    assert terminal["object_count"] == 1

    tampered = json.loads(second_receipt)
    tampered["canonical_export_sha256"] = "f" * 64
    with pytest.raises(InputIdentityError, match="catalog_receipt_drift"):
        resolve_catalog_training_datasets(
            catalog_export_raw=combined_raw,
            dataset_import_receipt_raw=first_receipt,
            consumer_import_receipt_raw=canonical(tampered),
            expected_dataset_id=dataset_id,
        )
    with pytest.raises(InputIdentityError, match="catalog_dataset_substitution"):
        resolve_catalog_training_datasets(
            catalog_export_raw=combined_raw,
            dataset_import_receipt_raw=first_receipt,
            consumer_import_receipt_raw=second_receipt,
            expected_dataset_id="dataset:caller-substitution",
        )

    unrelated_first_receipt = import_receipt(
        manifest_raw=canonical({"unrelated": True}),
        canonical_export=canonical({"unrelated": True}),
        inserted_records=0,
        inserted_edges=0,
    )
    with pytest.raises(InputIdentityError, match="catalog_receipt_drift"):
        resolve_catalog_training_datasets(
            catalog_export_raw=combined_raw,
            dataset_import_receipt_raw=unrelated_first_receipt,
            consumer_import_receipt_raw=second_receipt,
            expected_dataset_id=dataset_id,
        )

    missing_membership_edge = json.loads(combined_raw)
    missing_membership_edge["edges"] = [
        edge
        for edge in missing_membership_edge["edges"]
        if edge["kind"] != "membership_object"
    ]
    broken_export = canonical(missing_membership_edge)
    broken_receipt = import_receipt(
        manifest_raw=consumer_fragment,
        canonical_export=broken_export,
        inserted_records=0,
        inserted_edges=0,
    )
    with pytest.raises(InputIdentityError, match="catalog_dataset_substitution"):
        resolve_catalog_training_datasets(
            catalog_export_raw=broken_export,
            dataset_import_receipt_raw=first_receipt,
            consumer_import_receipt_raw=broken_receipt,
            expected_dataset_id=dataset_id,
        )


def test_bulk_connector_projection_reopens_files_and_refuses_authority_drift(
    tmp_path: Path,
) -> None:
    connector_path, connector_sha = write_connector(
        tmp_path,
        source="candidate-mathematics-train-1",
        domain="mathematics",
        files=[("a.pdf", b"pdf-a")],
    )
    common = {
        "receipt_path": connector_path,
        "expected_receipt_sha256": connector_sha,
        "source_id": "candidate-mathematics-train-1",
        "expected_source_selector": "candidate-mathematics-train-1",
        "expected_license_text_sha256": sha256(b"CC-BY-4.0"),
        "domain": "mathematics",
        "split": "train",
    }

    (tmp_path / "a.pdf").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="physical file"):
        load_bulk_domain_connector_receipt(**common)

    (tmp_path / "a.pdf").write_bytes(b"pdf-a")
    with pytest.raises(ValueError, match="source selector"):
        load_bulk_domain_connector_receipt(
            **{**common, "expected_source_selector": "caller-substitution"}
        )
    with pytest.raises(ValueError, match="license"):
        load_bulk_domain_connector_receipt(
            **{**common, "expected_license_text_sha256": "f" * 64}
        )

    payload = json.loads(connector_path.read_bytes())
    payload["sha256_manifest"] = "f" * 64
    connector_path.write_bytes(canonical(payload))
    with pytest.raises(ValueError, match="manifest hash"):
        load_bulk_domain_connector_receipt(
            **{
                **common,
                "expected_receipt_sha256": sha256(connector_path.read_bytes()),
            }
        )

    payload["sha256_manifest"] = sha256(payload["files"][0]["sha256"].encode())
    payload["files"][0]["path"] = "C:/caller-escape.pdf"
    connector_path.write_bytes(canonical(payload))
    with pytest.raises(ValueError, match="unsafe"):
        load_bulk_domain_connector_receipt(
            **{
                **common,
                "expected_receipt_sha256": sha256(connector_path.read_bytes()),
            }
        )


def test_projection_spec_is_closed_path_free_and_outputs_refuse_overwrite(
    tmp_path: Path,
) -> None:
    connector_path, connector_sha = write_connector(
        tmp_path,
        source="candidate-statistics-train-1",
        domain="statistics",
        files=[("c.pdf", b"pdf-c")],
    )
    supporting_receipt = tmp_path / "acquisition-terminal.json"
    supporting_receipt.write_bytes(canonical({"result": "PASS"}))
    spec = canonical(
        {
            "schema_version": "ember-issue1581-catalog-projection-spec-v1",
            "tokenizer_sha256": "4" * 64,
            "created_at_ms": 1,
            "rows": [
                {
                    "receipt_path": str(connector_path),
                    "expected_receipt_sha256": connector_sha,
                    "source_id": "candidate-statistics-train-1",
                    "expected_source_selector": "candidate-statistics-train-1",
                    "expected_license_text_sha256": sha256(b"CC-BY-4.0"),
                    "domain": "statistics",
                    "split": "train",
                    "supporting_receipts": [
                        {
                            "path": str(supporting_receipt),
                            "sha256": sha256(supporting_receipt.read_bytes()),
                        }
                    ],
                }
            ],
        }
    )
    manifest_raw = project_catalog_spec(spec_raw=spec)
    assert str(tmp_path).encode() not in manifest_raw

    wrong_supporting_type = json.loads(spec)
    wrong_supporting_type["rows"][0]["supporting_receipts"] = {}
    with pytest.raises(TypeError, match="supporting receipt authority must be a list"):
        project_catalog_spec(spec_raw=canonical(wrong_supporting_type))

    spec_path = tmp_path / "projection-spec.json"
    spec_path.write_bytes(spec)
    output = tmp_path / "projection.json"
    assert (
        catalog_main(["project", "--spec", str(spec_path), "--output", str(output)])
        == 0
    )
    assert (
        catalog_main(["project", "--spec", str(spec_path), "--output", str(output)])
        == 2
    )
    assert output.read_bytes() == manifest_raw

    direct_output = tmp_path / "direct-projection.json"
    write_new(direct_output, manifest_raw)
    with pytest.raises(FileExistsError):
        write_new(direct_output, b"replacement")
