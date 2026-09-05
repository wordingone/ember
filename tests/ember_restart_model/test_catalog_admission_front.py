# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""RED-first contract for the #1581 bulk catalog-admission consumer."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

import catalog_admission as catalog_admission_module
import input_identity as input_identity_module

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


def test_evaluation_consumer_cli_is_a_separate_command() -> None:
    with pytest.raises(SystemExit) as exit_info:
        catalog_main(["evaluation-consumer", "--help"])
    assert exit_info.value.code == 0


def test_training_consumer_bytes_remain_frozen_and_evaluation_refuses_train() -> None:
    manifest_raw = canonical(
        {
            "schema_version": "ember-data-catalog-manifest-v1",
            "records": [
                {
                    "kind": "dataset_version",
                    "id": "dataset:issue1581-bulk-train:" + "9" * 64,
                    "state": "admitted",
                }
            ],
            "edges": [],
        }
    )
    receipt = import_receipt(
        manifest_raw=manifest_raw,
        canonical_export=manifest_raw,
        inserted_records=1,
        inserted_edges=1,
    )
    arguments = {
        "catalog_export_raw": manifest_raw,
        "first_import_receipt_raw": receipt,
        "dataset_id": "dataset:issue1581-bulk-train:" + "9" * 64,
        "e_matrix_packet_raw": canonical({"schema_version": "fixture", "rows": []}),
        "source_commit": "1" * 40,
        "model_sha256": "5" * 64,
        "checkpoint_sha256": "6" * 64,
        "tokenizer_sha256": "4" * 64,
        "config_sha256": "7" * 64,
        "evaluator_sha256": "8" * 64,
    }
    train_fragment = build_consumer_catalog_fragment(**arguments)
    assert sha256(train_fragment) == (
        "9d3358e5c759a7e5c0d1ac5f3422d531fe6e60325ed2b2c77eac5106288586b8"
    )
    build_evaluation_consumer = getattr(
        catalog_admission_module, "build_evaluation_consumer_catalog_fragment"
    )
    with pytest.raises(ValueError, match="only heldout"):
        build_evaluation_consumer(**arguments)


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


def test_projection_deduplicates_repeated_same_source_object_memberships(
    tmp_path: Path,
) -> None:
    repeated_path, repeated_sha = write_connector(
        tmp_path / "repeated",
        source="candidate-mathematics-train-0",
        domain="mathematics",
        files=[
            ("a.pdf", b"same-payload"),
            ("b.pdf", b"same-payload"),
            ("c.pdf", b"distinct-payload"),
        ],
    )
    repeated_row = load_bulk_domain_connector_receipt(
        receipt_path=repeated_path,
        expected_receipt_sha256=repeated_sha,
        source_id="candidate-mathematics-train-0",
        expected_source_selector="candidate-mathematics-train-0",
        expected_license_text_sha256=sha256(b"CC-BY-4.0"),
        domain="mathematics",
        split="train",
    )
    shared_path, shared_sha = write_connector(
        tmp_path / "shared-across-sources",
        source="candidate-statistics-train-0",
        domain="statistics",
        files=[("shared.pdf", b"same-payload")],
    )
    shared_row = load_bulk_domain_connector_receipt(
        receipt_path=shared_path,
        expected_receipt_sha256=shared_sha,
        source_id="candidate-statistics-train-0",
        expected_source_selector="candidate-statistics-train-0",
        expected_license_text_sha256=sha256(b"CC-BY-4.0"),
        domain="statistics",
        split="train",
    )
    manifest = json.loads(
        build_dataset_catalog_manifest(
            rows=[repeated_row, shared_row],
            tokenizer_sha256="4" * 64,
            created_at_ms=1,
        )
    )

    record_identities = [(row["kind"], row["id"]) for row in manifest["records"]]
    edge_identities = [
        (
            row["kind"],
            row["from_kind"],
            row["from_id"],
            row["to_kind"],
            row["to_id"],
            row["ordinal"],
        )
        for row in manifest["edges"]
    ]
    assert len(record_identities) == len(set(record_identities))
    assert len(edge_identities) == len(set(edge_identities))
    memberships = [row for row in manifest["records"] if row["kind"] == "membership"]
    assert len(memberships) == 3
    assert len([row for row in manifest["records"] if row["kind"] == "immutable_object"]) == 2
    shared_digest = sha256(b"same-payload")
    assert {
        row["id"] for row in memberships if row["exact_sha256"] == shared_digest
    } == {
        f"membership:candidate-mathematics-train-0:{shared_digest}",
        f"membership:candidate-statistics-train-0:{shared_digest}",
    }

    unique_path, unique_sha = write_connector(
        tmp_path / "unique",
        source="candidate-mathematics-train-0",
        domain="mathematics",
        files=[("a.pdf", b"same-payload"), ("c.pdf", b"distinct-payload")],
    )
    unique_row = load_bulk_domain_connector_receipt(
        receipt_path=unique_path,
        expected_receipt_sha256=unique_sha,
        source_id="candidate-mathematics-train-0",
        expected_source_selector="candidate-mathematics-train-0",
        expected_license_text_sha256=sha256(b"CC-BY-4.0"),
        domain="mathematics",
        split="train",
    )
    unique_manifest = json.loads(
        build_dataset_catalog_manifest(
            rows=[unique_row, shared_row],
            tokenizer_sha256="4" * 64,
            created_at_ms=1,
        )
    )
    repeated_dataset_id = next(
        row["id"] for row in manifest["records"] if row["kind"] == "dataset_version"
    )
    unique_dataset_id = next(
        row["id"]
        for row in unique_manifest["records"]
        if row["kind"] == "dataset_version"
    )
    assert repeated_dataset_id != unique_dataset_id


def test_bulk_connector_projects_exact_supported_media_types_and_refuses_unknown(
    tmp_path: Path,
) -> None:
    known_root = tmp_path / "known"
    connector_path, connector_sha = write_connector(
        known_root,
        source="internlm/Lean-Workbook",
        domain="mathematics",
        files=[
            (".gitattributes", b"*.parquet filter=lfs"),
            (".gitignore", b"build/"),
            ("LICENSE", b"BSD-3-Clause"),
            ("Makefile", b"all:\n\ttrue"),
            ("LICENSE.code", b"MIT"),
            ("assets/diagram.odg", b"odg fixture"),
            ("assets/icon.ico", b"ico fixture"),
            ("assets/photo.jpg", b"jpeg fixture"),
            ("assets/screenshot.png", b"png fixture"),
            ("build/kernel.out", b"binary output fixture"),
            ("examples/hello_gpu_ref", b"binary executable fixture"),
            ("include/kernel.h", b"#pragma once"),
            ("scripts/build.bat", b"@echo off"),
            ("scripts/build.sh", b"#!/bin/sh"),
            ("scripts/helper.py", b"print('ok')"),
            ("src/kernel.cpp", b"int main() {}"),
            ("src/kernel.cu", b"__global__ void k() {}"),
            ("state/editor.swp", b"vim swap fixture"),
            ("style/site.css", b"body {}"),
            ("docs/guide.rst", b"Guide\n====="),
            ("workflow/sphinx.yml", b"name: sphinx"),
            ("data/train-00000-of-00020.json.gz", b"compressed json fixture"),
            ("lean_workbook.json", b"{}"),
            ("shard_00000000_processed.jsonl.zst", b"compressed ndjson fixture"),
            ("README.md", b"# Lean Workbook"),
            ("wkbk_1009.parquet", b"PAR1fixture"),
        ],
    )
    projected = load_bulk_domain_connector_receipt(
        receipt_path=connector_path,
        expected_receipt_sha256=connector_sha,
        source_id="candidate-mathematics-heldout-1",
        expected_source_selector="internlm/Lean-Workbook",
        expected_license_text_sha256=sha256(b"CC-BY-4.0"),
        domain="mathematics",
        split="heldout",
    )
    assert {row["path"]: row["media_type"] for row in projected["files"]} == {
        ".gitattributes": "text/plain; charset=utf-8",
        ".gitignore": "text/plain; charset=utf-8",
        "LICENSE": "text/plain; charset=utf-8",
        "LICENSE.code": "text/plain; charset=utf-8",
        "Makefile": "text/plain; charset=utf-8",
        "README.md": "text/markdown; charset=utf-8",
        "assets/diagram.odg": "application/vnd.oasis.opendocument.graphics",
        "assets/icon.ico": "image/x-icon",
        "assets/photo.jpg": "image/jpeg",
        "assets/screenshot.png": "image/png",
        "build/kernel.out": "application/octet-stream",
        "data/train-00000-of-00020.json.gz": "application/json+gzip",
        "docs/guide.rst": "text/x-rst; charset=utf-8",
        "examples/hello_gpu_ref": "application/octet-stream",
        "include/kernel.h": "text/x-c++hdr; charset=utf-8",
        "lean_workbook.json": "application/json",
        "scripts/build.bat": "text/x-msdos-batch; charset=utf-8",
        "scripts/build.sh": "application/x-sh; charset=utf-8",
        "scripts/helper.py": "text/x-python; charset=utf-8",
        "shard_00000000_processed.jsonl.zst": "application/x-ndjson+zstd",
        "src/kernel.cpp": "text/x-c++src; charset=utf-8",
        "src/kernel.cu": "text/x-cuda; charset=utf-8",
        "state/editor.swp": "application/x-vim-swap",
        "style/site.css": "text/css; charset=utf-8",
        "workflow/sphinx.yml": "application/yaml; charset=utf-8",
        "wkbk_1009.parquet": "application/vnd.apache.parquet",
    }

    unknown_root = tmp_path / "unknown"
    unknown_path, unknown_sha = write_connector(
        unknown_root,
        source="fixture/unknown",
        domain="mathematics",
        files=[("payload.bin", b"unsupported")],
    )
    with pytest.raises(ValueError, match="unsupported media type"):
        load_bulk_domain_connector_receipt(
            receipt_path=unknown_path,
            expected_receipt_sha256=unknown_sha,
            source_id="candidate-mathematics-heldout-2",
            expected_source_selector="fixture/unknown",
            expected_license_text_sha256=sha256(b"CC-BY-4.0"),
            domain="mathematics",
            split="heldout",
        )

    deceptive_root = tmp_path / "deceptive"
    deceptive_path, deceptive_sha = write_connector(
        deceptive_root,
        source="fixture/deceptive",
        domain="mathematics",
        files=[("payload.json.gz.exe", b"not gzip")],
    )
    with pytest.raises(ValueError, match="unsupported media type"):
        load_bulk_domain_connector_receipt(
            receipt_path=deceptive_path,
            expected_receipt_sha256=deceptive_sha,
            source_id="candidate-mathematics-heldout-2",
            expected_source_selector="fixture/deceptive",
            expected_license_text_sha256=sha256(b"CC-BY-4.0"),
            domain="mathematics",
            split="heldout",
        )


def test_projects_one_heldout_slot_without_mislabeling_it_as_train(
    tmp_path: Path,
) -> None:
    build_evaluation_consumer = getattr(
        catalog_admission_module, "build_evaluation_consumer_catalog_fragment", None
    )
    resolve_evaluation_dataset = getattr(
        input_identity_module, "resolve_catalog_evaluation_dataset", None
    )
    assert callable(build_evaluation_consumer) and callable(resolve_evaluation_dataset)
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
    consumer_fragment = build_evaluation_consumer(
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
    disguised = json.loads(manifest_raw)
    next(
        item for item in disguised["records"] if item["kind"] == "membership"
    )["split"] = "train"
    disguised_raw = canonical(disguised)
    disguised_receipt = import_receipt(
        manifest_raw=disguised_raw,
        canonical_export=disguised_raw,
        inserted_records=len(disguised["records"]),
        inserted_edges=len(disguised["edges"]),
    )
    with pytest.raises(ValueError, match="only heldout"):
        build_evaluation_consumer(
            **{
                "catalog_export_raw": disguised_raw,
                "first_import_receipt_raw": disguised_receipt,
                "dataset_id": dataset["id"],
            },
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
    assert {row["kind"] for row in fragment["records"]} <= {
        "consumer_attempt",
        "immutable_object",
        "protected_eval",
        "receipt",
    }
    assert {edge["kind"] for edge in fragment["edges"]} <= {
        "consumer_dataset",
        "consumer_evaluation",
        "consumer_receipt",
        "evaluation_object",
        "evaluation_receipt",
    }
    assert next(
        row for row in fragment["records"] if row["kind"] == "consumer_attempt"
    )["id"].startswith("attempt:issue1581-catalog-evaluation:")
    protected_eval = next(
        item for item in fragment["records"] if item["kind"] == "protected_eval"
    )
    assert protected_eval["ngram_ruling"] == "not_run"
    assert protected_eval["near_dup_ruling"] == "not_run"
    assert protected_eval["exclusion_reason"] is None
    assert protected_eval["overlap_state"] == "isolated"
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
    with pytest.raises(
        InputIdentityError,
        match="catalog_dataset_split_refused",
    ):
        resolve_catalog_training_datasets(
            catalog_export_raw=combined_raw,
            dataset_import_receipt_raw=first_receipt,
            consumer_import_receipt_raw=consumer_receipt,
            expected_dataset_id=dataset["id"],
            expected_split="heldout",
        )
    with pytest.raises(TypeError, match="_required_split"):
        resolve_catalog_training_datasets(
            catalog_export_raw=combined_raw,
            dataset_import_receipt_raw=first_receipt,
            consumer_import_receipt_raw=consumer_receipt,
            expected_dataset_id=dataset["id"],
            expected_split="heldout",
            _required_split="heldout",
            _dataset_edge_kind="evaluation_dataset",
            _attempt_record_kind="evaluation_attempt",
            _attempt_evaluation_edge_kind="evaluation_definition",
            _attempt_receipt_edge_kind="evaluation_import_receipt",
        )
    with pytest.raises(TypeError, match="_dataset_edge_kind"):
        resolve_evaluation_dataset(
            catalog_export_raw=combined_raw,
            dataset_import_receipt_raw=first_receipt,
            consumer_import_receipt_raw=consumer_receipt,
            expected_dataset_id=dataset["id"],
            expected_split="heldout",
            _dataset_edge_kind="consumer_dataset",
        )
    resolved = resolve_evaluation_dataset(
        catalog_export_raw=combined_raw,
        dataset_import_receipt_raw=first_receipt,
        consumer_import_receipt_raw=consumer_receipt,
        expected_dataset_id=dataset["id"],
        expected_split="heldout",
    )
    assert resolved["split"] == "heldout"
    assert resolved["source_ids"] == ["candidate-mathematics-heldout-0"]
    assert resolved["protected_eval_item_admission"] is True

    def assert_evaluation_binding_refused(value: dict[str, object]) -> None:
        raw = canonical(value)
        receipt = import_receipt(
            manifest_raw=consumer_fragment,
            canonical_export=raw,
            inserted_records=0,
            inserted_edges=0,
        )
        with pytest.raises(
            InputIdentityError,
            match="catalog_dataset_substitution|catalog_receipt_drift",
        ):
            resolve_evaluation_dataset(
                catalog_export_raw=raw,
                dataset_import_receipt_raw=first_receipt,
                consumer_import_receipt_raw=receipt,
                expected_dataset_id=dataset["id"],
                expected_split="heldout",
            )

    for field, drifted_value in (
        ("ngram_ruling", "accepted"),
        ("near_dup_ruling", "refused"),
        ("exclusion_reason", "fabricated exclusion"),
        ("overlap_state", "unknown"),
    ):
        drifted_semantics = json.loads(combined_raw)
        next(
            record
            for record in drifted_semantics["records"]
            if record.get("kind") == "protected_eval"
        )[field] = drifted_value
        assert_evaluation_binding_refused(drifted_semantics)

    duplicate_dataset_record = json.loads(combined_raw)
    duplicate_dataset_record["records"].append(
        dict(
            next(
                record
                for record in duplicate_dataset_record["records"]
                if record.get("kind") == "dataset_version"
                and record.get("id") == dataset["id"]
            )
        )
    )
    assert_evaluation_binding_refused(duplicate_dataset_record)

    duplicate_version_membership = json.loads(combined_raw)
    duplicate_version_membership["edges"].append(
        dict(
            next(
                edge
                for edge in duplicate_version_membership["edges"]
                if edge.get("kind") == "version_membership"
                and edge.get("from_id") == dataset["id"]
            )
        )
    )
    assert_evaluation_binding_refused(duplicate_version_membership)

    for record_kind in ("immutable_object", "source"):
        duplicate_record = json.loads(combined_raw)
        duplicate_record["records"].append(
            dict(
                next(
                    record
                    for record in duplicate_record["records"]
                    if record.get("kind") == record_kind
                )
            )
        )
        assert_evaluation_binding_refused(duplicate_record)

    duplicate_source_object = json.loads(combined_raw)
    duplicate_source_object["edges"].append(
        dict(
            next(
                edge
                for edge in duplicate_source_object["edges"]
                if edge.get("kind") == "source_object"
            )
        )
    )
    assert_evaluation_binding_refused(duplicate_source_object)

    missing_evaluation_receipt = json.loads(combined_raw)
    missing_evaluation_receipt["edges"] = [
        edge
        for edge in missing_evaluation_receipt["edges"]
        if edge["kind"] != "evaluation_receipt"
    ]
    assert_evaluation_binding_refused(missing_evaluation_receipt)

    duplicate_evaluation_receipt = json.loads(combined_raw)
    duplicate_evaluation_receipt["edges"].append(
        dict(
            next(
                edge
                for edge in duplicate_evaluation_receipt["edges"]
                if edge["kind"] == "evaluation_receipt"
            )
        )
    )
    assert_evaluation_binding_refused(duplicate_evaluation_receipt)

    drifted_e_matrix_object = json.loads(combined_raw)
    evaluation_object_id = next(
        edge["to_id"]
        for edge in drifted_e_matrix_object["edges"]
        if edge["kind"] == "evaluation_object"
    )
    next(
        record
        for record in drifted_e_matrix_object["records"]
        if record.get("kind") == "immutable_object"
        and record.get("id") == evaluation_object_id
    )["sha256"] = "0" * 64
    assert_evaluation_binding_refused(drifted_e_matrix_object)

    overlapped = json.loads(combined_raw)
    next(
        edge
        for edge in overlapped["edges"]
        if edge["kind"] == "evaluation_object"
    )["to_id"] = shared_object_id
    assert_evaluation_binding_refused(overlapped)

    revalidation = revalidate_e_matrix_catalog_bindings(
        e_matrix_packet_raw=e_matrix, resolved_identity=resolved
    )
    cli_inputs = {
        "catalog-export": combined_raw,
        "dataset-import-receipt": first_receipt,
        "consumer-import-receipt": consumer_receipt,
        "e-matrix-packet": e_matrix,
    }
    cli_arguments = ["revalidate"]
    for name, raw in cli_inputs.items():
        path = tmp_path / f"cli-{name}.json"
        path.write_bytes(raw)
        cli_arguments.extend([f"--{name}", str(path)])
    cli_output = tmp_path / "cli-e-matrix-revalidation.json"
    cli_arguments.extend(
        [
            "--dataset-id",
            dataset["id"],
            "--output",
            str(cli_output),
        ]
    )
    assert catalog_main(cli_arguments) == 0
    assert cli_output.read_bytes() == canonical(revalidation)
    row = revalidation["rows"][0]
    assert row["row_id"] == "candidate-mathematics-heldout-0"
    assert row["state"] == "PRESENT"
    assert row["catalog_dataset_binding"] == "PRESENT"
    assert row["catalog_dataset_split"] == "heldout"
    assert "catalog_train_dataset_binding" not in row
    assert row["protected"] is True
    assert row["protected_eval_admission_satisfied"] is True

    general_packet = canonical(
        {
            "schema_version": "ember-e-matrix-definition-v1",
            "rows": [
                {
                    "row_id": "candidate-mathematics-heldout-0",
                    "state": "PRESENT",
                    "protected": False,
                }
            ],
        }
    )
    general = revalidate_e_matrix_catalog_bindings(
        e_matrix_packet_raw=general_packet, resolved_identity=resolved
    )["rows"][0]
    assert general["protected"] is True
    assert general["protected_eval_admission_satisfied"] is True
    assert "catalog_train_dataset_binding" not in general

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
    assert terminal["protected_eval_item_admission"] is True


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


def test_bulk_connector_uses_catalog_source_id_for_split_authority(
    tmp_path: Path,
) -> None:
    proofnet_selector = (
        "zhangir-azerbayev/ProofNet@"
        "509ad79710ed4f46ff5c282ed5640c1aa9ac3f30#partition-0-of-1"
    )
    connector_path, connector_sha = write_connector(
        tmp_path,
        source=proofnet_selector,
        domain="mathematics",
        files=[("proof.jsonl", b"owned proof row")],
    )
    common = {
        "receipt_path": connector_path,
        "expected_receipt_sha256": connector_sha,
        "source_id": "candidate-mathematics-train-0",
        "expected_source_selector": proofnet_selector,
        "expected_license_text_sha256": sha256(b"CC-BY-4.0"),
        "domain": "mathematics",
        "split": "train",
    }

    row = load_bulk_domain_connector_receipt(**common)
    assert row["source_id"] == "candidate-mathematics-train-0"
    assert row["split"] == "train"

    with pytest.raises(ValueError, match="source identity split"):
        load_bulk_domain_connector_receipt(
            **{**common, "source_id": "candidate-mathematics-heldout-0"}
        )
    with pytest.raises(ValueError, match="source selector"):
        load_bulk_domain_connector_receipt(
            **{**common, "expected_source_selector": "caller-substitution"}
        )

    payload = json.loads(connector_path.read_bytes())
    payload["fetched_at"] = "2026-08-29T00:00:00Z"
    connector_path.write_bytes(canonical(payload))
    with pytest.raises(ValueError, match="frozen identity"):
        load_bulk_domain_connector_receipt(**common)


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


def test_train_partition_projection_dispatches_closed_schema_and_names_authority_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    partition_path = tmp_path / "partition-receipt.json"
    partition_path.write_bytes(b"partition-v1")
    source_receipt = tmp_path / "source-receipt.json"
    source_receipt.write_bytes(canonical({
        "schema": "corpus-connector-receipt-v1",
        "canonical_url": "https://github.com/search?q=topic%3Acuda",
        "fetched_at": "2026-08-15T00:00:00Z",
    }))
    alpha_sha = sha256(b"alpha")
    charlie_sha = sha256(b"charlie")
    partition = {
        "source_id": "candidate-training_infrastructure-train-1",
        "domain": "training_infrastructure",
        "split": "train",
        "partition_root_sha256": "b" * 64,
        "source_connector_receipt_path": str(source_receipt),
        "source_connector_receipt_sha256": sha256(source_receipt.read_bytes()),
        "license_summary": ["Apache-2.0", "MIT"],
        "repositories": [{"files": [
            {"path": "src/main.py", "blob_path": "blobs/a", "bytes": 5, "sha256": alpha_sha},
            {"path": "cmake/Modules/FindFAISS.cmake", "blob_path": "blobs/c", "bytes": 7, "sha256": charlie_sha},
        ]}],
    }
    (tmp_path / "blobs").mkdir()
    (tmp_path / "blobs" / "a").write_bytes(b"alpha")
    (tmp_path / "blobs" / "c").write_bytes(b"charlie")
    monkeypatch.setattr(
        catalog_admission_module,
        "validate_partition_receipt",
        lambda _path: partition,
        raising=False,
    )
    monkeypatch.setattr(
        catalog_admission_module,
        "_load_partition_media_type_table",
        lambda: {
            "classes": {
                ".cmake": {
                    "count": 1,
                    "media_type": "text/plain; charset=utf-8",
                    "reason": "explicit source or build-language class",
                }
            }
        },
        raising=False,
    )
    monkeypatch.setattr(
        catalog_admission_module,
        "_load_predecessor_media_type_table",
        lambda: {"media_types_by_object_id": {"sha256:" + alpha_sha: "application/octet-stream"}},
        raising=False,
    )
    spec = canonical({
        "schema_version": "ember-issue1581-catalog-projection-spec-v1",
        "tokenizer_sha256": "4" * 64,
        "created_at_ms": 1,
        "rows": [{
            "license_partition_receipt_path": str(partition_path),
            "license_partition_receipt_sha256": sha256(partition_path.read_bytes()),
            "source_id": "candidate-training_infrastructure-train-1",
            "domain": "training_infrastructure",
            "split": "train",
            "supporting_receipts": [],
        }],
    })
    manifest_raw = project_catalog_spec(spec_raw=spec)
    manifest = json.loads(manifest_raw)
    assert str(tmp_path).encode() not in manifest_raw
    assert next(row for row in manifest["records"] if row["kind"] == "source")["id"] == "source:candidate-training_infrastructure-train-1"
    media_types = {
        row["sha256"]: row["media_type"]
        for row in manifest["records"]
        if row["kind"] == "immutable_object"
    }
    assert media_types[alpha_sha] == "application/octet-stream"
    assert media_types[charlie_sha] == "text/plain; charset=utf-8"
    assert all(edge["payload"] == {} for edge in manifest["edges"])

    planted_unknown = json.loads(manifest_raw)
    source_object = next(
        edge for edge in planted_unknown["edges"] if edge["kind"] == "source_object"
    )
    source_object["payload"]["path_derived_media_type"] = "text/plain; charset=utf-8"
    with pytest.raises(
        ValueError, match="CATALOG_EDGE_PAYLOAD_SCHEMA_REFUSED:source_object"
    ):
        catalog_admission_module.validate_edge_payloads_against_frozen_catalog_schema(
            planted_unknown
        )

    partition["repositories"][0]["files"].append(
        {"path": "future/new.brandnew", "blob_path": "blobs/d", "bytes": 3, "sha256": sha256(b"raw")}
    )
    (tmp_path / "blobs" / "d").write_bytes(b"raw")
    with pytest.raises(ValueError, match="PARTITION_PROJECTION_MEDIA_CLASS_UNMAPPED:.brandnew"):
        project_catalog_spec(spec_raw=spec)
    partition["repositories"][0]["files"].pop()

    partition_path.write_bytes(b"partition-with-one-repository-row-removed")
    monkeypatch.setattr(
        catalog_admission_module,
        "validate_partition_receipt",
        lambda _path: (_ for _ in ()).throw(ValueError("repository count mismatch")),
        raising=False,
    )
    tampered = json.loads(spec)
    tampered["rows"][0]["license_partition_receipt_sha256"] = sha256(partition_path.read_bytes())
    with pytest.raises(ValueError, match="PARTITION_PROJECTION_AUTHORITY_REFUSED:repository count mismatch"):
        project_catalog_spec(spec_raw=canonical(tampered))


def test_train_partition_media_table_is_goal_bound() -> None:
    table = catalog_admission_module._load_partition_media_type_table()
    assert table["goal_id"] == "EMBER-02"
    assert table["workstream_id"] == "EMBER-02B"
    assert table["next_executed_outcome"] == (
        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    )
    predecessor = catalog_admission_module._load_predecessor_media_type_table()
    assert predecessor["goal_id"] == "EMBER-02"
    assert predecessor["workstream_id"] == "EMBER-02B"
    assert predecessor["binding_count"] == 609
    assert predecessor["binding_count"] == len(predecessor["media_types_by_object_id"])


def test_content_sniff_is_path_independent_and_extension_is_only_a_binary_tiebreak(
    tmp_path: Path,
) -> None:
    raw = b"same utf8 bytes\n"
    first = tmp_path / "same.py"
    second = tmp_path / "same.bin"
    first.write_bytes(raw)
    second.write_bytes(raw)
    table = {"classes": {".bin": {"media_type": "application/octet-stream"}}}
    assert catalog_admission_module._content_media_type(first, PurePosixPath("same.py"), table) == (
        "text/plain; charset=utf-8"
    )
    assert catalog_admission_module._content_media_type(second, PurePosixPath("same.bin"), table) == (
        "text/plain; charset=utf-8"
    )

def _heldout_and_train_sharing_one_object(tmp_path: Path) -> tuple[dict, str]:
    """Combined export: one heldout and one admitted train membership over the same bytes."""
    shared = b"shared statistics text"
    combined: dict = {"schema_version": "ember-data-catalog-export-v1", "records": [], "edges": []}
    heldout_dataset_id = ""
    for source, domain_split in [
        ("candidate-statistics-heldout-1", ("statistics", "heldout")),
        ("candidate-statistics-train-0", ("statistics", "train")),
    ]:
        domain, split = domain_split
        connector_path, connector_sha = write_connector(
            tmp_path / source,
            source=source,
            domain=domain,
            files=[("shared.txt", shared)],
        )
        row = load_bulk_domain_connector_receipt(
            receipt_path=connector_path,
            expected_receipt_sha256=connector_sha,
            source_id=source,
            expected_source_selector=source,
            expected_license_text_sha256=sha256(b"CC-BY-4.0"),
            domain=domain,
            split=split,
        )
        manifest = json.loads(
            build_dataset_catalog_manifest(
                rows=[row], tokenizer_sha256="4" * 64, created_at_ms=1
            )
        )
        if split == "heldout":
            heldout_dataset_id = next(
                item["id"] for item in manifest["records"] if item["kind"] == "dataset_version"
            )
        combined["records"].extend(manifest["records"])
        combined["edges"].extend(manifest["edges"])
    return combined, heldout_dataset_id


def _evaluation_consumer_over(combined: dict, dataset_id: str) -> bytes:
    raw = canonical(combined)
    receipt = import_receipt(
        manifest_raw=raw,
        canonical_export=raw,
        inserted_records=len(combined["records"]),
        inserted_edges=len(combined["edges"]),
    )
    e_matrix = canonical(
        {
            "schema_version": "ember-issue1581-slot-e-matrix-definition-v1",
            "rows": [{"row_id": "candidate-statistics-heldout-1", "state": "ABSENT"}],
        }
    )
    return catalog_admission_module.build_evaluation_consumer_catalog_fragment(
        catalog_export_raw=raw,
        first_import_receipt_raw=receipt,
        dataset_id=dataset_id,
        e_matrix_packet_raw=e_matrix,
        source_commit="1" * 40,
        model_sha256="5" * 64,
        checkpoint_sha256="6" * 64,
        tokenizer_sha256="4" * 64,
        config_sha256="7" * 64,
        evaluator_sha256="8" * 64,
    )


def _heldout_memberships(combined: dict, dataset_id: str) -> list[dict]:
    ids = {
        edge["to_id"]
        for edge in combined["edges"]
        if edge["kind"] == "version_membership" and edge["from_id"] == dataset_id
    }
    return [row for row in combined["records"] if row.get("id") in ids]


def test_evaluation_consumer_takes_isolation_over_admitted_heldout_memberships_only(
    tmp_path: Path,
) -> None:
    """Live defect (#2105 -> #1581 debt row): 608 heldout memberships quarantined by
    data-catalog-quarantine-overlaps still mapped to admitted train objects, and the
    builder counted them, refusing a graph whose admitted-only overlap is zero."""
    combined, dataset_id = _heldout_and_train_sharing_one_object(tmp_path)
    memberships = _heldout_memberships(combined, dataset_id)
    assert len(memberships) == 1

    # Planted overlap while the heldout membership is still admitted: refuses.
    with pytest.raises(ValueError, match="overlaps admitted train objects"):
        _evaluation_consumer_over(combined, dataset_id)

    # The catalog quarantine removed that membership from the protected set:
    # the isolation proof holds over the remaining admitted heldout memberships.
    memberships[0]["admission_state"] = "quarantined"
    with pytest.raises(ValueError, match="no admitted heldout memberships"):
        _evaluation_consumer_over(combined, dataset_id)

    # Add a second, clean heldout membership to the same dataset: passes, and the
    # quarantined object never enters the fragment.
    clean_digest = sha256(b"clean heldout text")
    clean_membership = dict(memberships[0])
    clean_membership.update(
        {
            "id": f"membership:candidate-statistics-heldout-1:{clean_digest}",
            "admission_state": "admitted",
            "exact_sha256": clean_digest,
            "near_dedup_cluster": f"sha256:{clean_digest}",
            "shard_id": f"shard:sha256:{clean_digest}",
        }
    )
    combined["records"].append(clean_membership)
    combined["records"].append(
        {
            "kind": "immutable_object",
            "id": f"sha256:{clean_digest}",
            "sha256": clean_digest,
            "byte_count": len(b"clean heldout text"),
            "media_type": "text/plain; charset=utf-8",
            "locator": f"sha256/{clean_digest[:2]}/{clean_digest}",
            "custody_state": "available",
        }
    )
    combined["edges"].extend(
        [
            {
                "kind": "version_membership",
                "from_kind": "dataset_version",
                "from_id": dataset_id,
                "to_kind": "membership",
                "to_id": clean_membership["id"],
                "ordinal": 1,
                "payload": {},
            },
            {
                "kind": "membership_object",
                "from_kind": "membership",
                "from_id": clean_membership["id"],
                "to_kind": "immutable_object",
                "to_id": f"sha256:{clean_digest}",
                "ordinal": 0,
                "payload": {},
            },
        ]
    )
    fragment = json.loads(_evaluation_consumer_over(combined, dataset_id))
    attempt = next(row for row in fragment["records"] if row["kind"] == "consumer_attempt")
    assert attempt["id"].startswith("attempt:issue1581-catalog-evaluation:")
    protected_eval = next(row for row in fragment["records"] if row["kind"] == "protected_eval")
    assert protected_eval["overlap_state"] == "isolated"
    assert memberships[0]["exact_sha256"] not in json.dumps(fragment)

    # Any admission state this builder does not know is a refusal, never a pass.
    clean_membership["admission_state"] = "pending"
    with pytest.raises(ValueError, match="unknown admission state"):
        _evaluation_consumer_over(combined, dataset_id)

