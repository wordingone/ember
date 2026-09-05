#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Widen the frozen #2105 heldout IMAGE set from 64 to 256 items (#2116).

The #2105 census (schema ``ember-issue1581-heldout-image-candidate-census-v1``, raw sha
frozen in that module) carries only the 64 selected rows plus aggregate counts over the
same MMMU validation pool (30 per-subject ``validation-*.parquet`` files under
``mmmu-validation-f87afafe``, image columns ``image_1``..``image_7`` read as bytes;
``question``/``options``/``explanation``/``answer`` are never read). This module re-derives
the full unique image byte-sha256 set from that same pool, excludes every admitted TRAIN
object hash read from the live catalog, sorts lexically ascending, and takes the first 256.

The selection rule is UNCHANGED and FROZEN from #2105/#1581 — only N widens from 64 to 256.
Because the rule is a pure function of (pool contents, train exclusion set, lexical order),
the new census's first 64 selected rows must reproduce the #2105 frozen
``selected_set_sha256`` exactly; a census that cannot reproduce it means either the pool or
the train-exclusion set drifted since #2105 froze, and the census refuses rather than
silently emitting a set that disagrees with its own predecessor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

CENSUS_SCHEMA = "ember-issue2116-heldout-image-widen-census-v1"
PLAN_SCHEMA = "ember-issue2116-heldout-image-widen-admission-plan-v1"
ADMISSION_RECEIPT_SCHEMA = "ember-issue2116-heldout-image-widen-admission-receipt-v1"
CONTRACT_SCHEMA = "ember-protected-image-contract-v2"
SECOND_SOURCE_CENSUS_SCHEMA = "ember-issue2116-second-source-census-v1"

PREDECESSOR_CENSUS_SCHEMA = "ember-issue1581-heldout-image-candidate-census-v1"
PREDECESSOR_CENSUS_RAW_SHA256 = "3496abeea7a56992e4e7645ccd29556489f3633551cf9fd80bdd9142c114b4d7"
PREDECESSOR_CENSUS_SELF_SHA256 = "3efc6187ea0de5028c88c1daa4657f1657c8a0e0d1f9149da7c864ade832bce8"
PREDECESSOR_SELECTED_SET_SHA256 = "9d8799b958aabf8e6cdb9fa58906ab7b550c270e7b3b1643b4575559eefcbe30"
LICENSE_SHA256 = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
CUSTODY_MANIFEST_SHA256 = "20af6ef398cd7913ea0ba5b53025dbf568eab6d74f7290d01ceda30c4a206b03"
MMMU_REVISION = "f87afafe4afe71650b99ef5236d7b5bb3f6345c7"
SOURCE_ID = "mmmu-validation-heldout-image-256"
CATALOG_SOURCE_ID = "candidate-image-heldout-widen-0"

EXPECTED_PARQUET_FILE_COUNT = 30
EXPECTED_UNIQUE_COUNT = 959
EXPECTED_PREDECESSOR_COUNT = 64
EXPECTED_SELECTED_COUNT = 256

SELECTION_RULE = (
    "first N unique image byte SHA256 values in ascending lexical order after exact "
    "exclusion of every admitted train image object SHA256; seed-free"
)
TASK_ID = "EXACT_IMAGE_PAYLOAD_SHA256_IDENTITY"
FORBIDDEN_INPUTS = ["mmmu_question", "mmmu_answer", "mmmu_options"]
CLAIM_BOUNDARY = (
    "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT"
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_path_for(row_id: str, image_column: str) -> str:
    return f"{row_id}_{image_column.rsplit('_', 1)[-1]}.png"


def discover_image_rows(mmmu_root: Path) -> tuple[dict[str, dict[str, Any]], int, int]:
    """Read only ``id`` plus every ``image_*`` column of each subject's single validation
    parquet; ``question``/``options``/``explanation``/``answer`` are never projected.
    Returns unique rows keyed by exact_sha256 (first occurrence kept), the occurrence
    count, and the parquet file count actually read."""

    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise ValueError("PYARROW_UNAVAILABLE_REFUSED") from error
    subject_dirs = sorted(
        path for path in mmmu_root.iterdir() if path.is_dir() and not path.name.startswith(".")
    )
    by_hash: dict[str, dict[str, Any]] = {}
    occurrence_count = 0
    parquet_count = 0
    for subject_dir in subject_dirs:
        paths = sorted(subject_dir.glob("validation-*.parquet"))
        if len(paths) != 1:
            raise ValueError(f"MMMU_SUBJECT_PARQUET_TOTALITY_REFUSED:{subject_dir.name}:{len(paths)}")
        parquet_count += 1
        table = pq.read_table(paths[0])
        image_columns = sorted(c for c in table.column_names if c.startswith("image_"))
        for row in table.to_pylist():
            row_id = row.get("id")
            if not isinstance(row_id, str):
                raise ValueError("MMMU_ROW_ID_REFUSED")  # noqa: TRY004
            for column in image_columns:
                image = row.get(column)
                if not isinstance(image, dict):
                    continue
                raw = image.get("bytes")
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                raw = bytes(raw)
                digest = sha(raw)
                occurrence_count += 1
                if digest not in by_hash:
                    by_hash[digest] = {
                        "subject": subject_dir.name,
                        "row_id": row_id,
                        "image_column": column,
                        "byte_count": len(raw),
                        "exact_sha256": digest,
                        "source_path": source_path_for(row_id, column),
                        "source_revision": MMMU_REVISION,
                        "source_split": "validation",
                    }
    if parquet_count != EXPECTED_PARQUET_FILE_COUNT:
        raise ValueError(f"MMMU_PARQUET_FILE_COUNT_REFUSED:{parquet_count}")
    return by_hash, occurrence_count, parquet_count


def read_admitted_train_object_hashes(catalog: Path) -> set[str]:
    """Every admitted TRAIN object hash, across all media types (same query shape as
    ``read_admitted_train_object_hashes`` in issue2148_heldout_reasoning_answers.py);
    the exclusion is not scoped to image media because an image byte-identical to a
    non-image train object would still be the same exact_sha256 value."""

    connection = sqlite3.connect(
        catalog.resolve(strict=True).as_uri() + "?mode=ro&immutable=1", uri=True
    )
    try:
        return {
            row[0]
            for row in connection.execute(
                """
                SELECT json_extract(m.payload_json, '$.exact_sha256')
                FROM data_catalog_records AS m
                WHERE m.kind = 'membership'
                  AND json_extract(m.payload_json, '$.admission_state') = 'admitted'
                  AND json_extract(m.payload_json, '$.split') = 'train'
                """
            )
        }
    finally:
        connection.close()


def build_census(
    *,
    by_hash: dict[str, dict[str, Any]],
    occurrence_count: int,
    parquet_file_count: int,
    admitted_train_object_hashes: set[str],
    license_raw: bytes,
    custody_manifest_raw: bytes,
) -> dict[str, Any]:
    """Read-only census: unique-count assertion, train exclusion, widen selection, and the
    frozen-predecessor drift assertion. No custody is written and no payload is read here."""

    if sha(license_raw) != LICENSE_SHA256:
        raise ValueError("LICENSE_SHA256_DRIFT_REFUSED")
    if sha(custody_manifest_raw) != CUSTODY_MANIFEST_SHA256:
        raise ValueError("CUSTODY_MANIFEST_SHA256_DRIFT_REFUSED")
    if parquet_file_count != EXPECTED_PARQUET_FILE_COUNT:
        raise ValueError(f"MMMU_PARQUET_FILE_COUNT_REFUSED:{parquet_file_count}")
    unique_count = len(by_hash)
    if unique_count != EXPECTED_UNIQUE_COUNT:
        raise ValueError(f"CENSUS_UNIQUE_COUNT_DRIFT_REFUSED:{unique_count}")
    excluded_train_hashes = sorted(set(by_hash) & admitted_train_object_hashes)
    candidates = sorted(digest for digest in by_hash if digest not in admitted_train_object_hashes)
    if len(candidates) < EXPECTED_SELECTED_COUNT:
        raise ValueError(f"CENSUS_SELECTION_TOTALITY_REFUSED:{len(candidates)}")
    selected_hashes = candidates[:EXPECTED_SELECTED_COUNT]
    post_selection_overlap = set(selected_hashes) & admitted_train_object_hashes
    if post_selection_overlap:
        raise ValueError(f"CENSUS_TRAIN_INTERSECTION_REFUSED:{len(post_selection_overlap)}")
    selected_rows = sorted(
        (dict(by_hash[digest]) for digest in selected_hashes),
        key=lambda row: row["exact_sha256"],
    )
    predecessor_rows = selected_rows[:EXPECTED_PREDECESSOR_COUNT]
    predecessor_set_sha256 = sha(canonical(predecessor_rows))
    if predecessor_set_sha256 != PREDECESSOR_SELECTED_SET_SHA256:
        raise ValueError("PREDECESSOR_SELECTED_SET_DRIFT_REFUSED")
    census: dict[str, Any] = {
        "schema_version": CENSUS_SCHEMA,
        "result": "PASS",
        "source": {
            "name": "MMMU",
            "revision": MMMU_REVISION,
            "split": "validation",
            "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
            "license_sha256": LICENSE_SHA256,
        },
        "predecessor": {
            "census_schema": PREDECESSOR_CENSUS_SCHEMA,
            "census_raw_sha256": PREDECESSOR_CENSUS_RAW_SHA256,
            "census_self_sha256": PREDECESSOR_CENSUS_SELF_SHA256,
            "selected_count": EXPECTED_PREDECESSOR_COUNT,
            "selected_set_sha256": PREDECESSOR_SELECTED_SET_SHA256,
        },
        "parquet_file_count": parquet_file_count,
        "image_occurrence_count": occurrence_count,
        "unique_image_count": unique_count,
        "train_overlap_count": len(excluded_train_hashes),
        "selection_rule": SELECTION_RULE,
        "selected_count": len(selected_rows),
        "selected": selected_rows,
        "selected_set_sha256": sha(canonical(selected_rows)),
    }
    census["self_sha256"] = sha(canonical(census))
    return census


def verify_census(census: dict[str, Any]) -> None:
    body = dict(census)
    claimed = body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ValueError("CENSUS_SELF_SHA256_DRIFT_REFUSED")
    selected = census.get("selected")
    if (
        census.get("schema_version") != CENSUS_SCHEMA
        or census.get("result") != "PASS"
        or census.get("parquet_file_count") != EXPECTED_PARQUET_FILE_COUNT
        or census.get("unique_image_count") != EXPECTED_UNIQUE_COUNT
        or census.get("train_overlap_count", -1) < 0
        or census.get("selection_rule") != SELECTION_RULE
        or census.get("selected_count") != EXPECTED_SELECTED_COUNT
        or not isinstance(selected, list)
        or len(selected) != EXPECTED_SELECTED_COUNT
        or census.get("selected_set_sha256") != sha(canonical(selected))
        or sha(canonical(selected[:EXPECTED_PREDECESSOR_COUNT])) != PREDECESSOR_SELECTED_SET_SHA256
    ):
        raise ValueError("CENSUS_CONTRACT_DRIFT_REFUSED")


def read_selected_payloads(
    mmmu_root: Path, selected: list[dict[str, Any]]
) -> dict[tuple[str, str, str], bytes]:
    """Read image bytes for ONLY the 256 selected rows, grouped by subject so each subject's
    parquet is opened at most once and only its selected image columns are projected."""

    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise ValueError("PYARROW_UNAVAILABLE_REFUSED") from error
    wanted: dict[str, list[dict[str, Any]]] = {}
    for row in selected:
        wanted.setdefault(str(row["subject"]), []).append(row)
    payloads: dict[tuple[str, str, str], bytes] = {}
    for subject, rows in wanted.items():
        paths = sorted((mmmu_root / subject).glob("validation-*.parquet"))
        if len(paths) != 1:
            raise ValueError(f"MMMU_SUBJECT_PARQUET_TOTALITY_REFUSED:{subject}:{len(paths)}")
        columns = ["id", *sorted({str(row["image_column"]) for row in rows})]
        table_rows = pq.read_table(paths[0], columns=columns).to_pylist()
        by_id = {str(row["id"]): row for row in table_rows}
        for selected_row in rows:
            row_id = str(selected_row["row_id"])
            column = str(selected_row["image_column"])
            image = by_id.get(row_id, {}).get(column)
            raw = image.get("bytes") if isinstance(image, dict) else None
            if not isinstance(raw, bytes):
                raise TypeError(f"SELECTED_IMAGE_ORIGIN_MISSING_REFUSED:{subject}:{row_id}:{column}")
            payloads[(subject, row_id, column)] = raw
    return payloads


def build_admission_plan(
    *,
    census: dict[str, Any],
    admitted_train_object_hashes: set[str],
    payloads_by_origin: dict[tuple[str, str, str], bytes],
) -> dict[str, Any]:
    """Validate every selected payload against the census before any custody path exists."""

    verify_census(census)
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
        if digest in admitted_train_object_hashes:
            raise ValueError(f"TRAIN_HELDOUT_IMAGE_OVERLAP_REFUSED:{digest}")
        if digest in selected_hashes:
            raise ValueError(f"DUPLICATE_SELECTED_IMAGE_REFUSED:{digest}")
        selected_hashes.add(digest)
        source_path = Path(str(row.get("source_path") or "image.png"))
        suffix = source_path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            raise ValueError(f"SELECTED_IMAGE_MEDIA_TYPE_REFUSED:{digest}")
        files.append({
            "path": f"objects/{digest[:2]}/{digest}{suffix}",
            "bytes": len(payload),
            "sha256": digest,
            "source": {
                "subject": origin[0],
                "row_id": origin[1],
                "image_column": origin[2],
            },
        })
    files.sort(key=lambda row: row["sha256"])
    if len(files) != EXPECTED_SELECTED_COUNT:
        raise ValueError("SELECTED_IMAGE_TOTALITY_REFUSED")
    return {
        "schema_version": PLAN_SCHEMA,
        "result": "PASS",
        "selection_rule": SELECTION_RULE,
        "selected_count": EXPECTED_SELECTED_COUNT,
        "selected_set_sha256": census["selected_set_sha256"],
        "predecessor_selected_set_sha256": PREDECESSOR_SELECTED_SET_SHA256,
        "train_exclusion_assertion": "executed_pass",
        "census_self_sha256": census["self_sha256"],
        "license_sha256": LICENSE_SHA256,
        "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
        "source_revision": MMMU_REVISION,
        "domain": "image",
        "split": "heldout",
        "files": files,
    }


def build_image_widen_contract(
    plan: dict[str, Any],
    *,
    connector_receipt_raw: bytes,
    catalog_export_raw: bytes | None = None,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    if (
        plan.get("result") != "PASS"
        or plan.get("selected_count") != EXPECTED_SELECTED_COUNT
        or plan.get("predecessor_selected_set_sha256") != PREDECESSOR_SELECTED_SET_SHA256
        or len(plan.get("files", [])) != EXPECTED_SELECTED_COUNT
    ):
        raise ValueError("IMAGE_ADMISSION_PLAN_TOTALITY_REFUSED")
    catalog_binding: dict[str, Any] | None = None
    if (catalog_export_raw is None) != (dataset_id is None):
        raise ValueError("IMAGE_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED")
    if catalog_export_raw is not None and dataset_id is not None:
        catalog_binding = _catalog_binding(plan, catalog_export_raw, dataset_id)
    contract: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA,
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": TASK_ID,
            "consumes": ["image_payload_bytes"],
            "forbidden_inputs": list(FORBIDDEN_INPUTS),
            "prediction": "sha256(image_payload_bytes)",
            "scorer": "exact_match(prediction, gold_object_sha256)",
        },
        "source": {
            "revision": MMMU_REVISION,
            "connector_receipt_raw_sha256": sha(connector_receipt_raw),
            "census_self_sha256": plan["census_self_sha256"],
            "license_sha256": LICENSE_SHA256,
            "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
        },
        "selection_rule": SELECTION_RULE,
        "selected_set_sha256": plan["selected_set_sha256"],
        "predecessor_selected_set_sha256": PREDECESSOR_SELECTED_SET_SHA256,
        "frozen_items": [
            {
                "item_id": f"sha256:{row['sha256']}",
                "gold_object_sha256": row["sha256"],
                "byte_count": row["bytes"],
                "media_type": "image/png" if row["path"].endswith(".png") else "image/jpeg",
            }
            for row in plan["files"]
        ],
        "totality": {
            "expected": EXPECTED_SELECTED_COUNT,
            "observed": len(plan["files"]),
            "complete": len(plan["files"]) == EXPECTED_SELECTED_COUNT,
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if catalog_binding is not None:
        contract["catalog_binding"] = catalog_binding
    contract["self_sha256"] = sha(canonical(contract))
    return contract


def _catalog_binding(plan: dict[str, Any], catalog_export_raw: bytes, dataset_id: str) -> dict[str, Any]:
    """Post-import intersection audit: every one of the 256 admitted image objects must be a
    member of the named admitted heldout dataset version through an admitted heldout
    membership, and none of the 256 may appear in ANY admitted TRAIN membership anywhere in
    the export (not merely the ones this dataset itself declares)."""

    try:
        catalog = json.loads(catalog_export_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("IMAGE_CATALOG_EXPORT_UNREADABLE_REFUSED") from error
    records = catalog.get("records") if isinstance(catalog, dict) else None
    edges = catalog.get("edges") if isinstance(catalog, dict) else None
    if not isinstance(records, list) or not isinstance(edges, list):
        raise ValueError("IMAGE_CATALOG_EXPORT_SCHEMA_REFUSED")  # noqa: TRY004
    if not any(
        isinstance(row, dict)
        and row.get("kind") == "dataset_version"
        and row.get("id") == dataset_id
        and row.get("state") == "admitted"
        for row in records
    ):
        raise ValueError("IMAGE_HELDOUT_DATASET_MISSING_REFUSED")
    memberships = {
        row["id"]: row for row in records if isinstance(row, dict) and row.get("kind") == "membership"
    }
    objects_by_membership: dict[str, set[str]] = {}
    for edge in edges:
        if isinstance(edge, dict) and edge.get("kind") == "membership_object" and isinstance(edge.get("from_id"), str):
            objects_by_membership.setdefault(edge["from_id"], set()).add(edge.get("to_id"))
    dataset_memberships = {
        edge["to_id"]
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "version_membership"
        and edge.get("from_id") == dataset_id
        and edge.get("to_id") in memberships
    }
    heldout_objects: set[str] = set()
    for membership_id in dataset_memberships:
        row = memberships[membership_id]
        if row.get("split") == "heldout" and row.get("admission_state") == "admitted":
            heldout_objects |= objects_by_membership.get(membership_id, set())
    train_objects: set[str] = set()
    admitted_train_membership_count = 0
    for membership_id, row in memberships.items():
        if row.get("split") == "train" and row.get("admission_state") == "admitted":
            admitted_train_membership_count += 1
            train_objects |= objects_by_membership.get(membership_id, set())
    expected = {f"sha256:{row['sha256']}" for row in plan["files"]}
    if not expected <= heldout_objects:
        missing = sorted(expected - heldout_objects)[:3]
        raise ValueError(
            f"IMAGE_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED:{len(expected & heldout_objects)}/{len(expected)}:{missing}"
        )
    overlap = sorted(expected & train_objects)
    if overlap:
        raise ValueError(f"IMAGE_TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:{len(overlap)}:{overlap[:3]}")
    covering = sorted(
        membership_id for membership_id in dataset_memberships
        if objects_by_membership.get(membership_id, set()) & expected
    )
    return {
        "dataset_id": dataset_id,
        "catalog_export_raw_sha256": sha(catalog_export_raw),
        "membership_count": len(covering),
        "object_set_sha256": sha(canonical(sorted(expected))),
        "train_exclusion": {
            "executed": True,
            "admitted_train_membership_count": admitted_train_membership_count,
            "admitted_train_object_count": len(train_objects),
            "overlap_count": 0,
        },
    }


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


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

    if output_root.exists() or connector_receipt_path.exists() or admission_receipt_path.exists():
        raise ValueError("NO_OVERWRITE_REFUSED")
    if not fetched_at or "T" not in fetched_at or not fetched_at.endswith("Z"):
        raise ValueError("FETCHED_AT_REFUSED")
    custody = json.loads(custody_manifest_raw)
    upstream_url = custody.get("upstream_url")
    if not isinstance(upstream_url, str) or not upstream_url:
        raise ValueError("CUSTODY_MANIFEST_UPSTREAM_URL_REFUSED")
    output_root.mkdir(parents=True, exist_ok=False)
    connector_files = []
    for row in plan["files"]:
        source = row["source"]
        origin = (source["subject"], source["row_id"], source["image_column"])
        raw = payloads_by_origin[origin]
        physical = output_root / Path(row["path"])
        write_new(physical, raw)
        connector_files.append({"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]})
    connector_files.sort(key=lambda row: (row["path"], row["sha256"]))
    connector = {
        "schema": "corpus-connector-receipt-v1",
        "source_id": SOURCE_ID,
        "canonical_url": upstream_url,
        "fetched_at": fetched_at,
        "license": license_raw.decode("utf-8"),
        "dest_root": str(output_root.resolve()),
        "total_bytes": sum(row["bytes"] for row in connector_files),
        "sha256_manifest": sha("\n".join(sorted(row["sha256"] for row in connector_files)).encode()),
        "files": connector_files,
    }
    connector_raw = json.dumps(connector, sort_keys=True, indent=2).encode() + b"\n"
    admission = dict(plan)
    admission["schema_version"] = ADMISSION_RECEIPT_SCHEMA
    admission["connector_receipt_raw_sha256"] = sha(connector_raw)
    admission["total_bytes"] = connector["total_bytes"]
    admission["self_sha256"] = sha(canonical(admission))
    admission_raw = json.dumps(admission, sort_keys=True, indent=2).encode() + b"\n"
    write_new(connector_receipt_path, connector_raw)
    write_new(admission_receipt_path, admission_raw)
    return connector_raw, admission_raw


def build_projection_spec(
    *,
    connector_receipt_path: Path,
    connector_receipt_raw: bytes,
    admission_receipt_path: Path,
    admission_receipt_raw: bytes,
    census_path: Path,
    census_raw: bytes,
    custody_manifest_path: Path,
    license_path: Path,
    tokenizer_sha256: str,
    created_at_ms: int,
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
            "source_id": CATALOG_SOURCE_ID,
            "expected_source_selector": SOURCE_ID,
            "expected_license_text_sha256": LICENSE_SHA256,
            "domain": "image",
            "split": "heldout",
            "supporting_receipts": [
                {"path": str(admission_receipt_path.resolve()), "sha256": sha(admission_receipt_raw)},
                {"path": str(census_path.resolve()), "sha256": sha(census_raw)},
                {"path": str(custody_manifest_path.resolve()), "sha256": CUSTODY_MANIFEST_SHA256},
                {"path": str(license_path.resolve()), "sha256": LICENSE_SHA256},
            ],
        }],
    }
    return json.dumps(spec, sort_keys=True, indent=2).encode() + b"\n"


def build_second_source_census(
    *,
    source_id: str,
    license_raw: bytes,
    revision: str,
    unique_hashes: set[str],
    admitted_train_object_hashes: set[str],
) -> dict[str, Any]:
    """Census-only leg for a candidate second heldout image source (#2116 point 5): no
    custody is created and no admission runs from this function. Refuses if the candidate's
    unique-hash set intersects any admitted TRAIN object."""

    if not source_id or not revision:
        raise ValueError("SECOND_SOURCE_IDENTITY_REFUSED")
    if not unique_hashes:
        raise ValueError("SECOND_SOURCE_EMPTY_REFUSED")
    overlap = sorted(unique_hashes & admitted_train_object_hashes)
    if overlap:
        raise ValueError(f"SECOND_SOURCE_TRAIN_INTERSECTION_REFUSED:{len(overlap)}")
    census: dict[str, Any] = {
        "schema_version": SECOND_SOURCE_CENSUS_SCHEMA,
        "result": "PASS",
        "source_id": source_id,
        "revision": revision,
        "license_sha256": sha(license_raw),
        "unique_hash_count": len(unique_hashes),
        "train_intersection_count": 0,
        "admission": "census_only; no custody created",
    }
    census["self_sha256"] = sha(canonical(census))
    return census


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mmmu-root", type=Path)
    parser.add_argument("--license", type=Path)
    parser.add_argument("--custody-manifest", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
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
        if not args.census.exists():
            for name, value in (
                ("--mmmu-root", args.mmmu_root),
                ("--license", args.license),
                ("--custody-manifest", args.custody_manifest),
                ("--catalog", args.catalog),
            ):
                if value is None:
                    raise ValueError(f"CENSUS_ARGUMENT_MISSING_REFUSED:{name}")
            by_hash, occurrence_count, parquet_count = discover_image_rows(args.mmmu_root)
            census = build_census(
                by_hash=by_hash,
                occurrence_count=occurrence_count,
                parquet_file_count=parquet_count,
                admitted_train_object_hashes=read_admitted_train_object_hashes(args.catalog),
                license_raw=args.license.read_bytes(),
                custody_manifest_raw=args.custody_manifest.read_bytes(),
            )
            write_new(args.census, json.dumps(census, sort_keys=True, indent=2).encode() + b"\n")
        else:
            census = json.loads(args.census.read_bytes())
            verify_census(census)

        if args.plan is not None:
            payloads = read_selected_payloads(args.mmmu_root, census["selected"])
            plan = build_admission_plan(
                census=census,
                admitted_train_object_hashes=read_admitted_train_object_hashes(args.catalog),
                payloads_by_origin=payloads,
            )
            write_new(args.plan, json.dumps(plan, sort_keys=True, indent=2).encode() + b"\n")

            artifact_values = [args.output_root, args.connector_receipt, args.admission_receipt, args.fetched_at]
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
                        census_raw=args.census.read_bytes(),
                        custody_manifest_path=args.custody_manifest,
                        license_path=args.license,
                        tokenizer_sha256=args.tokenizer_sha256,
                        created_at_ms=args.created_at_ms,
                    ))

            contract_values = [args.catalog_export, args.dataset_id, args.connector_for_contract, args.contract]
            if any(value is not None for value in contract_values):
                if any(value is None for value in contract_values):
                    raise ValueError("IMAGE_CONTRACT_ARGUMENT_TOTALITY_REFUSED")
                contract = build_image_widen_contract(
                    plan,
                    connector_receipt_raw=args.connector_for_contract.read_bytes(),
                    catalog_export_raw=args.catalog_export.read_bytes(),
                    dataset_id=args.dataset_id,
                )
                write_new(args.contract, json.dumps(contract, sort_keys=True, indent=2).encode() + b"\n")
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}")
        return 2
    print(json.dumps({
        "result": "PASS",
        "selected_count": census.get("selected_count"),
        "selected_set_sha256": census.get("selected_set_sha256"),
        "predecessor_selected_set_sha256": PREDECESSOR_SELECTED_SET_SHA256,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
