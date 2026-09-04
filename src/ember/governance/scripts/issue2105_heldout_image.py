#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Admit the frozen #2105 heldout IMAGE set without consuming MMMU Q/A."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

CENSUS_SCHEMA = "ember-issue1581-heldout-image-candidate-census-v1"
CENSUS_RAW_SHA256 = "3496abeea7a56992e4e7645ccd29556489f3633551cf9fd80bdd9142c114b4d7"
CENSUS_SELF_SHA256 = "3efc6187ea0de5028c88c1daa4657f1657c8a0e0d1f9149da7c864ade832bce8"
SELECTED_SET_SHA256 = "9d8799b958aabf8e6cdb9fa58906ab7b550c270e7b3b1643b4575559eefcbe30"
LICENSE_SHA256 = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
CUSTODY_MANIFEST_SHA256 = "20af6ef398cd7913ea0ba5b53025dbf568eab6d74f7290d01ceda30c4a206b03"
PROTECTED_ITEM_SET_SHA256 = "7a8800c96f0a6003b004d4bc3dfc089b8d6d5aa56a5f85e8c4719fbadd63ecc6"
MMMU_REVISION = "f87afafe4afe71650b99ef5236d7b5bb3f6345c7"
SELECTION_RULE = (
    "first N unique image byte SHA256 values in ascending lexical order after exact "
    "exclusion of every admitted train image object SHA256; seed-free"
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _verified_census(raw: bytes) -> dict[str, Any]:
    if sha(raw) != CENSUS_RAW_SHA256:
        raise ValueError("CENSUS_RAW_SHA256_DRIFT_REFUSED")
    try:
        census = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("CENSUS_UNREADABLE_REFUSED") from error
    body = dict(census)
    claimed = body.pop("self_sha256", None)
    if claimed != CENSUS_SELF_SHA256 or claimed != sha(canonical(body)):
        raise ValueError("CENSUS_SELF_SHA256_DRIFT_REFUSED")
    source = census.get("source")
    selected = census.get("selected")
    if (
        census.get("schema_version") != CENSUS_SCHEMA
        or census.get("result") != "PASS"
        or census.get("parquet_file_count") != 30
        or census.get("image_occurrence_count") != 982
        or census.get("unique_image_count") != 959
        or census.get("train_overlap_count") != 0
        or census.get("selection_rule") != SELECTION_RULE
        or census.get("selected_count") != 64
        or not isinstance(selected, list)
        or len(selected) != 64
        or census.get("selected_set_sha256") != SELECTED_SET_SHA256
        or sha(canonical(selected)) != SELECTED_SET_SHA256
        or not isinstance(source, dict)
        or source.get("revision") != MMMU_REVISION
        or source.get("split") != "validation"
        or source.get("custody_manifest_sha256") != CUSTODY_MANIFEST_SHA256
        or source.get("license_sha256") != LICENSE_SHA256
        or source.get("item_set_sha256") != PROTECTED_ITEM_SET_SHA256
    ):
        raise ValueError("CENSUS_CONTRACT_DRIFT_REFUSED")
    return census


def build_admission_plan(
    *,
    census_raw: bytes,
    license_raw: bytes,
    custody_manifest_raw: bytes,
    admitted_train_image_hashes: set[str],
    payloads_by_origin: dict[tuple[str, str, str], bytes],
) -> dict[str, Any]:
    """Validate all immutable inputs before any custody path is created."""

    census = _verified_census(census_raw)
    if sha(license_raw) != LICENSE_SHA256:
        raise ValueError("LICENSE_SHA256_DRIFT_REFUSED")
    if sha(custody_manifest_raw) != CUSTODY_MANIFEST_SHA256:
        raise ValueError("CUSTODY_MANIFEST_SHA256_DRIFT_REFUSED")
    try:
        custody = json.loads(custody_manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("CUSTODY_MANIFEST_UNREADABLE_REFUSED") from error
    if (
        custody.get("split", {}).get("eligible_id_set_sha256")
        != PROTECTED_ITEM_SET_SHA256
    ):
        raise ValueError("PROTECTED_ITEM_SET_SHA256_DRIFT_REFUSED")

    files: list[dict[str, Any]] = []
    selected_hashes: set[str] = set()
    for row in census["selected"]:
        origin = (str(row["subject"]), str(row["row_id"]), str(row["image_column"]))
        payload = payloads_by_origin.get(origin)
        digest = str(row["exact_sha256"])
        if (
            not isinstance(payload, bytes)
            or sha(payload) != digest
            or len(payload) != row["byte_count"]
        ):
            raise ValueError(f"SELECTED_IMAGE_PAYLOAD_DRIFT_REFUSED:{digest}")
        if digest in admitted_train_image_hashes:
            raise ValueError(f"TRAIN_HELDOUT_IMAGE_OVERLAP_REFUSED:{digest}")
        if digest in selected_hashes:
            raise ValueError(f"DUPLICATE_SELECTED_IMAGE_REFUSED:{digest}")
        selected_hashes.add(digest)
        source_path = Path(str(row.get("source_path") or "image.png"))
        suffix = source_path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            raise ValueError(f"SELECTED_IMAGE_MEDIA_TYPE_REFUSED:{digest}")
        files.append(
            {
                "path": f"objects/{digest[:2]}/{digest}{suffix}",
                "bytes": len(payload),
                "sha256": digest,
                "source": {
                    "subject": origin[0],
                    "row_id": origin[1],
                    "image_column": origin[2],
                },
            }
        )
    files.sort(key=lambda row: row["sha256"])
    if len(files) != 64:
        raise ValueError("SELECTED_IMAGE_TOTALITY_REFUSED")
    return {
        "schema_version": "ember-issue2105-heldout-image-admission-plan-v1",
        "result": "PASS",
        "selection_rule": SELECTION_RULE,
        "selected_count": 64,
        "selected_set_sha256": SELECTED_SET_SHA256,
        "train_exclusion_assertion": "executed_pass",
        "census_raw_sha256": CENSUS_RAW_SHA256,
        "census_self_sha256": CENSUS_SELF_SHA256,
        "license_sha256": LICENSE_SHA256,
        "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
        "protected_item_set_sha256": PROTECTED_ITEM_SET_SHA256,
        "source_revision": MMMU_REVISION,
        "domain": "image",
        "split": "heldout",
        "files": files,
    }


def build_image_only_contract(
    plan: dict[str, Any], *, connector_receipt_raw: bytes,
    catalog_export_raw: bytes | None = None, dataset_id: str | None = None,
) -> dict[str, Any]:
    if (
        plan.get("result") != "PASS"
        or plan.get("selected_count") != 64
        or plan.get("selected_set_sha256") != SELECTED_SET_SHA256
        or len(plan.get("files", [])) != 64
    ):
        raise ValueError("IMAGE_ADMISSION_PLAN_TOTALITY_REFUSED")
    catalog_binding: dict[str, Any] | None = None
    if (catalog_export_raw is None) != (dataset_id is None):
        raise ValueError("IMAGE_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED")
    if catalog_export_raw is not None and dataset_id is not None:
        try:
            catalog = json.loads(catalog_export_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("IMAGE_CATALOG_EXPORT_UNREADABLE_REFUSED") from error
        records = catalog.get("records") if isinstance(catalog, dict) else None
        edges = catalog.get("edges") if isinstance(catalog, dict) else None
        if not isinstance(records, list) or not isinstance(edges, list):
            raise ValueError("IMAGE_CATALOG_EXPORT_SCHEMA_REFUSED")
        if not any(
            isinstance(row, dict)
            and row.get("kind") == "dataset_version"
            and row.get("id") == dataset_id
            and row.get("state") == "admitted"
            for row in records
        ):
            raise ValueError("IMAGE_HELDOUT_DATASET_MISSING_REFUSED")
        membership_ids = {
            edge["to_id"] for edge in edges
            if isinstance(edge, dict)
            and edge.get("kind") == "version_membership"
            and edge.get("from_id") == dataset_id
        }
        memberships = {
            row["id"]: row for row in records
            if isinstance(row, dict)
            and row.get("kind") == "membership"
            and row.get("id") in membership_ids
        }
        object_ids = {
            edge["to_id"] for edge in edges
            if isinstance(edge, dict)
            and edge.get("kind") == "membership_object"
            and edge.get("from_id") in membership_ids
        }
        expected_object_ids = {f"sha256:{row['sha256']}" for row in plan["files"]}
        if (
            len(membership_ids) != 64
            or len(memberships) != 64
            or any(
                row.get("split") != "heldout"
                or row.get("domain") != "image"
                or row.get("admission_state") != "admitted"
                for row in memberships.values()
            )
            or object_ids != expected_object_ids
        ):
            raise ValueError("IMAGE_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED")
        catalog_binding = {
            "dataset_id": dataset_id,
            "catalog_export_raw_sha256": sha(catalog_export_raw),
            "membership_count": 64,
            "object_set_sha256": sha(canonical(sorted(object_ids))),
        }
    contract: dict[str, Any] = {
        "schema_version": "ember-issue2105-protected-image-contract-v1",
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": "EXACT_IMAGE_PAYLOAD_SHA256_IDENTITY",
            "consumes": ["image_payload_bytes"],
            "forbidden_inputs": ["mmmu_question", "mmmu_answer", "mmmu_options"],
            "prediction": "sha256(image_payload_bytes)",
            "scorer": "exact_match(prediction, gold_object_sha256)",
        },
        "source": {
            "revision": MMMU_REVISION,
            "connector_receipt_raw_sha256": sha(connector_receipt_raw),
            "census_raw_sha256": CENSUS_RAW_SHA256,
            "license_sha256": LICENSE_SHA256,
            "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
            "protected_item_set_sha256": PROTECTED_ITEM_SET_SHA256,
            "protected_item_set_access": "read_only; questions_answers_options_forbidden",
        },
        "selection_rule": SELECTION_RULE,
        "selected_set_sha256": SELECTED_SET_SHA256,
        "frozen_items": [
            {
                "item_id": f"sha256:{row['sha256']}",
                "gold_object_sha256": row["sha256"],
                "byte_count": row["bytes"],
                "media_type": (
                    "image/png" if row["path"].endswith(".png") else "image/jpeg"
                ),
            }
            for row in plan["files"]
        ],
        "totality": {"expected": 64, "observed": 64, "complete": True},
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    }
    if catalog_binding is not None:
        contract["catalog_binding"] = catalog_binding
    contract["self_sha256"] = sha(canonical(contract))
    return contract


def write_admission_artifacts(
    *,
    plan: dict[str, Any],
    payloads_by_origin: dict[tuple[str, str, str], bytes],
    license_raw: bytes,
    custody_manifest_raw: bytes,
    output_root: Path,
    connector_receipt_path: Path,
    admission_receipt_path: Path,
    fetched_at: str,
) -> tuple[bytes, bytes]:
    """Create new custody only after the complete read-only plan has passed."""

    if (
        output_root.exists()
        or connector_receipt_path.exists()
        or admission_receipt_path.exists()
    ):
        raise ValueError("NO_OVERWRITE_REFUSED")
    if not fetched_at or "T" not in fetched_at or not fetched_at.endswith("Z"):
        raise ValueError("FETCHED_AT_REFUSED")
    output_root.mkdir(parents=True, exist_ok=False)
    connector_files = []
    for row in plan["files"]:
        source = row["source"]
        origin = (source["subject"], source["row_id"], source["image_column"])
        raw = payloads_by_origin[origin]
        physical = output_root / Path(row["path"])
        write_new(physical, raw)
        connector_files.append({
            "path": row["path"],
            "bytes": row["bytes"],
            "sha256": row["sha256"],
        })
    connector_files.sort(key=lambda row: (row["path"], row["sha256"]))
    custody = json.loads(custody_manifest_raw)
    connector = {
        "schema": "corpus-connector-receipt-v1",
        "source_id": "mmmu-validation-heldout-image-64",
        "canonical_url": custody["upstream_url"],
        "fetched_at": fetched_at,
        "license": license_raw.decode("utf-8"),
        "dest_root": str(output_root.resolve()),
        "total_bytes": sum(row["bytes"] for row in connector_files),
        "sha256_manifest": sha(
            "\n".join(sorted(row["sha256"] for row in connector_files)).encode()
        ),
        "files": connector_files,
    }
    connector_raw = json.dumps(connector, sort_keys=True, indent=2).encode() + b"\n"
    admission = dict(plan)
    admission["schema_version"] = "ember-issue2105-heldout-image-admission-receipt-v1"
    admission["connector_receipt_raw_sha256"] = sha(connector_raw)
    admission["total_bytes"] = connector["total_bytes"]
    admission["self_sha256"] = sha(canonical(admission))
    admission_raw = json.dumps(admission, sort_keys=True, indent=2).encode() + b"\n"
    write_new(connector_receipt_path, connector_raw)
    write_new(admission_receipt_path, admission_raw)
    return connector_raw, admission_raw


def build_projection_spec(
    *, connector_receipt_path: Path, connector_receipt_raw: bytes,
    admission_receipt_path: Path, admission_receipt_raw: bytes,
    census_path: Path, custody_manifest_path: Path, license_path: Path,
    tokenizer_sha256: str, created_at_ms: int,
) -> bytes:
    if len(tokenizer_sha256) != 64 or any(c not in "0123456789abcdef" for c in tokenizer_sha256):
        raise ValueError("TOKENIZER_SHA256_REFUSED")
    if isinstance(created_at_ms, bool) or not isinstance(created_at_ms, int) or created_at_ms < 0:
        raise ValueError("CREATED_AT_MS_REFUSED")
    spec = {
        "schema_version": "ember-issue1581-catalog-projection-spec-v1",
        "tokenizer_sha256": tokenizer_sha256,
        "created_at_ms": created_at_ms,
        "rows": [{
            "receipt_path": str(connector_receipt_path.resolve()),
            "expected_receipt_sha256": sha(connector_receipt_raw),
            "source_id": "candidate-image-heldout-0",
            "expected_source_selector": "mmmu-validation-heldout-image-64",
            "expected_license_text_sha256": LICENSE_SHA256,
            "domain": "image",
            "split": "heldout",
            "supporting_receipts": [
                {"path": str(admission_receipt_path.resolve()), "sha256": sha(admission_receipt_raw)},
                {"path": str(census_path.resolve()), "sha256": CENSUS_RAW_SHA256},
                {"path": str(custody_manifest_path.resolve()), "sha256": CUSTODY_MANIFEST_SHA256},
                {"path": str(license_path.resolve()), "sha256": LICENSE_SHA256},
            ],
        }],
    }
    return json.dumps(spec, sort_keys=True, indent=2).encode() + b"\n"


def read_admitted_train_image_hashes(catalog: Path) -> set[str]:
    connection = sqlite3.connect(catalog.resolve(strict=True).as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        hashes = {
            row[0]
            for row in connection.execute(
                """
                SELECT json_extract(m.payload_json, '$.exact_sha256')
                FROM data_catalog_records AS m
                JOIN data_catalog_records AS o
                  ON o.kind = 'immutable_object'
                 AND o.record_id = 'sha256:' || json_extract(m.payload_json, '$.exact_sha256')
                WHERE m.kind = 'membership'
                  AND json_extract(m.payload_json, '$.admission_state') = 'admitted'
                  AND json_extract(m.payload_json, '$.split') = 'train'
                  AND lower(json_extract(o.payload_json, '$.media_type')) LIKE 'image/%'
                """
            )
        }
    finally:
        connection.close()
    if len(hashes) != 1755:
        raise ValueError(f"TRAIN_IMAGE_CATALOG_COUNT_DRIFT_REFUSED:{len(hashes)}")
    return hashes


def read_selected_payloads(mmmu_root: Path, census_raw: bytes) -> dict[tuple[str, str, str], bytes]:
    census = _verified_census(census_raw)
    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise ValueError("PYARROW_UNAVAILABLE_REFUSED") from error
    wanted: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in census["selected"]:
        wanted[str(row["subject"])].append(row)
    payloads: dict[tuple[str, str, str], bytes] = {}
    for subject, rows in wanted.items():
        paths = sorted((mmmu_root / subject).glob("validation-*.parquet"))
        if len(paths) != 1:
            raise ValueError(f"MMMU_SUBJECT_PARQUET_TOTALITY_REFUSED:{subject}:{len(paths)}")
        columns = ["id", *sorted({str(row["image_column"]) for row in rows})]
        table_rows = pq.read_table(paths[0], columns=columns).to_pylist()
        by_id = {str(row["id"]): row for row in table_rows}
        for selected in rows:
            row_id = str(selected["row_id"])
            column = str(selected["image_column"])
            image = by_id.get(row_id, {}).get(column)
            raw = image.get("bytes") if isinstance(image, dict) else None
            if not isinstance(raw, bytes):
                raise TypeError(f"SELECTED_IMAGE_ORIGIN_MISSING_REFUSED:{subject}:{row_id}:{column}")
            payloads[(subject, row_id, column)] = raw
    return payloads


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--license", type=Path, required=True)
    parser.add_argument("--custody-manifest", type=Path, required=True)
    parser.add_argument("--mmmu-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--connector-receipt", type=Path)
    parser.add_argument("--admission-receipt", type=Path)
    parser.add_argument("--fetched-at")
    parser.add_argument("--projection-spec", type=Path)
    parser.add_argument("--tokenizer-sha256")
    parser.add_argument("--created-at-ms", type=int)
    parser.add_argument("--catalog-export", type=Path)
    parser.add_argument("--dataset-id")
    parser.add_argument("--connector-for-contract", type=Path)
    parser.add_argument("--contract", type=Path)
    args = parser.parse_args()
    try:
        census_raw = args.census.read_bytes()
        payloads = read_selected_payloads(args.mmmu_root, census_raw)
        plan = build_admission_plan(
            census_raw=census_raw,
            license_raw=args.license.read_bytes(),
            custody_manifest_raw=args.custody_manifest.read_bytes(),
            admitted_train_image_hashes=read_admitted_train_image_hashes(args.catalog),
            payloads_by_origin=payloads,
        )
        plan_for_receipt = dict(plan)
        plan_for_receipt["self_sha256"] = sha(canonical(plan_for_receipt))
        write_new(args.plan, json.dumps(plan_for_receipt, sort_keys=True, indent=2).encode() + b"\n")
        artifact_values = [
            args.output_root,
            args.connector_receipt,
            args.admission_receipt,
            args.fetched_at,
        ]
        if any(value is not None for value in artifact_values):
            if any(value is None for value in artifact_values):
                raise ValueError("ADMISSION_ARTIFACT_ARGUMENT_TOTALITY_REFUSED")
            connector_raw, admission_raw = write_admission_artifacts(
                plan=plan,
                payloads_by_origin=payloads,
                license_raw=args.license.read_bytes(),
                custody_manifest_raw=args.custody_manifest.read_bytes(),
                output_root=args.output_root,
                connector_receipt_path=args.connector_receipt,
                admission_receipt_path=args.admission_receipt,
                fetched_at=args.fetched_at,
            )
            projection_values = [args.projection_spec, args.tokenizer_sha256, args.created_at_ms]
            if any(value is not None for value in projection_values):
                if any(value is None for value in projection_values):
                    raise ValueError("PROJECTION_SPEC_ARGUMENT_TOTALITY_REFUSED")
                write_new(args.projection_spec, build_projection_spec(
                    connector_receipt_path=args.connector_receipt,
                    connector_receipt_raw=connector_raw,
                    admission_receipt_path=args.admission_receipt,
                    admission_receipt_raw=admission_raw,
                    census_path=args.census,
                    custody_manifest_path=args.custody_manifest,
                    license_path=args.license,
                    tokenizer_sha256=args.tokenizer_sha256,
                    created_at_ms=args.created_at_ms,
                ))
        contract_values = [args.catalog_export, args.dataset_id, args.connector_for_contract, args.contract]
        if any(value is not None for value in contract_values):
            if any(value is None for value in contract_values):
                raise ValueError("IMAGE_CONTRACT_ARGUMENT_TOTALITY_REFUSED")
            connector_raw = args.connector_for_contract.read_bytes()
            contract = build_image_only_contract(
                plan,
                connector_receipt_raw=connector_raw,
                catalog_export_raw=args.catalog_export.read_bytes(),
                dataset_id=args.dataset_id,
            )
            write_new(args.contract, json.dumps(contract, sort_keys=True, indent=2).encode() + b"\n")
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}")
        return 2
    print(json.dumps({"result": "PASS", "selected_count": 64, "selected_set_sha256": SELECTED_SET_SHA256}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
