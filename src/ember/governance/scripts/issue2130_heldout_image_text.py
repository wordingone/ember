#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Admit the frozen 847-item MMMU image+text set (#2130) without reading answers.

The object set is DEFINED by the frozen eligible id set (every multiple-choice
validation item): every image byte object an item references plus one canonical
item-text object per item.  There is no N and no lexical sampling.  Image objects
already admitted heldout by #2105 are recorded in the referenced union and are
not re-admitted; the answer dictionary is recorded as an identity only and is
never read by this module.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

CENSUS_SCHEMA = "ember-issue2130-heldout-image-text-item-census-v1"
PLAN_SCHEMA = "ember-issue2130-heldout-image-text-admission-plan-v1"
ADMISSION_RECEIPT_SCHEMA = "ember-issue2130-heldout-image-text-admission-receipt-v1"
CONTRACT_SCHEMA = "ember-protected-image-text-contract-v1"
TASK_ID = "EXACT_IMAGE_TEXT_PAYLOAD_SHA256_IDENTITY"
FORBIDDEN_INPUTS = ["mmmu_answer_dictionary", "prediction_custody"]
MMMU_REVISION = "f87afafe4afe71650b99ef5236d7b5bb3f6345c7"
LICENSE_SHA256 = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
CUSTODY_MANIFEST_SHA256 = "20af6ef398cd7913ea0ba5b53025dbf568eab6d74f7290d01ceda30c4a206b03"
PROTECTED_ITEM_SET_SHA256 = "7a8800c96f0a6003b004d4bc3dfc089b8d6d5aa56a5f85e8c4719fbadd63ecc6"
ANSWER_DICTIONARY_SHA256 = "76080f5597b8f4d29abba8551489c4b82e4a285b9d62b946fd67a1952e95502c"
EXPECTED_ITEM_COUNT = 847
EXPECTED_PARQUET_FILE_COUNT = 30
EXPECTED_ADMITTED_TRAIN_IMAGE_COUNT = 1755
EXPECTED_ADMITTED_HELDOUT_IMAGE_COUNT = 64
PREDECESSOR_IMAGE_SOURCE_ID = "mmmu-validation-heldout-image-64"
IMAGE_SOURCE_ID = "mmmu-validation-heldout-image-text-images"
TEXT_SOURCE_ID = "mmmu-validation-heldout-image-text-items"
CATALOG_IMAGE_SOURCE_ID = "candidate-image-text-images-heldout-0"
CATALOG_TEXT_SOURCE_ID = "candidate-image-text-items-heldout-0"
IMAGE_COLUMNS = tuple(f"image_{index}" for index in range(1, 8))
IMAGE_SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
TEXT_MEDIA_TYPE = "application/json"
TEXT_CANONICALIZATION = (
    "json.dumps({'id','question','options'}, sort_keys=True, separators=(',',':'), "
    "ensure_ascii=True) + LF; options = ast.literal_eval(parquet options string); "
    "the answer is never a member"
)
SELECTION_RULE = (
    "object set defined by the frozen eligible id set (question_type == "
    "multiple-choice over the validation split): every referenced image byte "
    "object plus one canonical item-text object per item; no N, no lexical "
    "sampling; image objects already admitted heldout are recorded in the "
    "referenced union and not re-admitted; exact exclusion of every admitted "
    "train object sha256 asserted"
)
CLAIM_BOUNDARY = (
    "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, "
    "OR GOAL CREDIT"
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def id_set_sha256(ids: list[str]) -> str:
    return sha(("\n".join(ids) + "\n").encode("utf-8"))


def parse_options(raw: object, item_id: str) -> list[str]:
    if not isinstance(raw, str):
        raise ValueError(f"ITEM_OPTIONS_SHAPE_REFUSED:{item_id}")
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as error:
        raise ValueError(f"ITEM_OPTIONS_SHAPE_REFUSED:{item_id}") from error
    if (
        not isinstance(value, list)
        or len(value) < 2
        or any(not isinstance(option, str) or not option for option in value)
    ):
        raise ValueError(f"ITEM_OPTIONS_SHAPE_REFUSED:{item_id}")
    return value


def item_text_object(item_id: str, question: object, options_raw: object) -> bytes:
    """The canonical item-text payload: id, question, options. Never the answer."""

    if not isinstance(question, str) or not question:
        raise ValueError(f"ITEM_QUESTION_SHAPE_REFUSED:{item_id}")
    payload = {
        "id": item_id,
        "question": question,
        "options": parse_options(options_raw, item_id),
    }
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def item_gold_sha256(image_payloads: list[bytes], text_payload: bytes) -> str:
    return sha(b"".join(image_payloads) + text_payload)


def items_from_rows(rows_by_subject: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Pure projection of parquet rows (already read) into eligible items.

    Each row carries ``id``, ``question``, ``options``, ``question_type`` and the
    seven image struct columns (``{"bytes": ..., "path": ...}`` or ``None``).
    """

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for subject in sorted(rows_by_subject):
        for row in rows_by_subject[subject]:
            if row.get("question_type") != "multiple-choice":
                continue
            item_id = row.get("id")
            if not isinstance(item_id, str) or not item_id:
                raise ValueError(f"ITEM_ID_SHAPE_REFUSED:{subject}")
            if item_id in seen:
                raise ValueError(f"DUPLICATE_ITEM_ID_REFUSED:{item_id}")
            seen.add(item_id)
            images: list[dict[str, Any]] = []
            for column in IMAGE_COLUMNS:
                image = row.get(column)
                if image is None:
                    continue
                raw = image.get("bytes") if isinstance(image, dict) else None
                if not isinstance(raw, bytes) or not raw:
                    raise TypeError(f"ITEM_IMAGE_PAYLOAD_SHAPE_REFUSED:{item_id}:{column}")
                source_path = image.get("path")
                suffix = Path(str(source_path or "image.png")).suffix.lower()
                if suffix not in IMAGE_SUFFIXES:
                    raise ValueError(f"ITEM_IMAGE_MEDIA_TYPE_REFUSED:{item_id}:{column}")
                images.append({
                    "column": column,
                    "sha256": sha(raw),
                    "byte_count": len(raw),
                    "suffix": suffix,
                    "payload": raw,
                })
            if not images:
                raise ValueError(f"ITEM_WITHOUT_IMAGE_REFUSED:{item_id}")
            text_payload = item_text_object(item_id, row.get("question"), row.get("options"))
            items.append({
                "subject": subject,
                "id": item_id,
                "images": images,
                "text_payload": text_payload,
                "text_sha256": sha(text_payload),
            })
    items.sort(key=lambda item: item["id"])
    return items


def read_items(mmmu_root: Path) -> tuple[list[dict[str, Any]], int]:
    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise ValueError("PYARROW_UNAVAILABLE_REFUSED") from error
    subject_dirs = sorted(
        path for path in mmmu_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )
    rows_by_subject: dict[str, list[dict[str, Any]]] = {}
    parquet_count = 0
    columns = ["id", "question", "options", "question_type", *IMAGE_COLUMNS]
    for subject_dir in subject_dirs:
        paths = sorted(subject_dir.glob("validation-*.parquet"))
        if len(paths) != 1:
            raise ValueError(
                f"MMMU_SUBJECT_PARQUET_TOTALITY_REFUSED:{subject_dir.name}:{len(paths)}"
            )
        parquet_count += 1
        rows_by_subject[subject_dir.name] = pq.read_table(paths[0], columns=columns).to_pylist()
    if parquet_count != EXPECTED_PARQUET_FILE_COUNT:
        raise ValueError(f"MMMU_PARQUET_FILE_COUNT_REFUSED:{parquet_count}")
    return items_from_rows(rows_by_subject), parquet_count


def _verify_custody_manifest(custody_manifest_raw: bytes) -> dict[str, Any]:
    if sha(custody_manifest_raw) != CUSTODY_MANIFEST_SHA256:
        raise ValueError("CUSTODY_MANIFEST_SHA256_DRIFT_REFUSED")
    try:
        custody = json.loads(custody_manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("CUSTODY_MANIFEST_UNREADABLE_REFUSED") from error
    split = custody.get("split") if isinstance(custody, dict) else None
    if not isinstance(split, dict) or split.get("eligible_id_set_sha256") != PROTECTED_ITEM_SET_SHA256:
        raise ValueError("PROTECTED_ITEM_SET_SHA256_DRIFT_REFUSED")
    return custody


def build_census(
    *,
    items: list[dict[str, Any]],
    parquet_file_count: int,
    license_raw: bytes,
    custody_manifest_raw: bytes,
    admitted_train_object_hashes: set[str],
    admitted_heldout_image_hashes: set[str],
) -> dict[str, Any]:
    """Read-only census: identities, union, train exclusion. No custody is written."""

    if sha(license_raw) != LICENSE_SHA256:
        raise ValueError("LICENSE_SHA256_DRIFT_REFUSED")
    _verify_custody_manifest(custody_manifest_raw)
    if parquet_file_count != EXPECTED_PARQUET_FILE_COUNT:
        raise ValueError(f"MMMU_PARQUET_FILE_COUNT_REFUSED:{parquet_file_count}")
    ids = [item["id"] for item in items]
    if ids != sorted(ids) or len(ids) != EXPECTED_ITEM_COUNT:
        raise ValueError(f"ELIGIBLE_ITEM_COUNT_REFUSED:{len(ids)}")
    observed_item_set = id_set_sha256(ids)
    if observed_item_set != PROTECTED_ITEM_SET_SHA256:
        raise ValueError("PROTECTED_ITEM_SET_SHA256_DRIFT_REFUSED")
    if len(admitted_heldout_image_hashes) != EXPECTED_ADMITTED_HELDOUT_IMAGE_COUNT:
        raise ValueError(
            f"HELDOUT_IMAGE_CATALOG_COUNT_DRIFT_REFUSED:{len(admitted_heldout_image_hashes)}"
        )

    image_objects: dict[str, dict[str, Any]] = {}
    text_objects: dict[str, str] = {}
    census_items: list[dict[str, Any]] = []
    for item in items:
        image_rows = []
        for image in item["images"]:
            digest = image["sha256"]
            known = image_objects.get(digest)
            if known is None:
                image_objects[digest] = {
                    "byte_count": image["byte_count"],
                    "suffix": image["suffix"],
                    "media_type": IMAGE_SUFFIXES[image["suffix"]],
                    "origin": {
                        "subject": item["subject"],
                        "row_id": item["id"],
                        "image_column": image["column"],
                    },
                }
            elif known["byte_count"] != image["byte_count"] or known["suffix"] != image["suffix"]:
                raise ValueError(f"IMAGE_OBJECT_IDENTITY_CONFLICT_REFUSED:{digest}")
            image_rows.append({
                "column": image["column"],
                "sha256": digest,
                "byte_count": image["byte_count"],
                "media_type": IMAGE_SUFFIXES[image["suffix"]],
            })
        text_digest = item["text_sha256"]
        if text_digest in text_objects or text_digest in image_objects:
            raise ValueError(f"TEXT_OBJECT_IDENTITY_CONFLICT_REFUSED:{text_digest}")
        text_objects[text_digest] = item["id"]
        census_items.append({
            "item_id": item["id"],
            "subject": item["subject"],
            "image_objects": image_rows,
            "item_text_object": {
                "sha256": text_digest,
                "byte_count": len(item["text_payload"]),
                "media_type": TEXT_MEDIA_TYPE,
            },
            "gold_item_sha256": item_gold_sha256(
                [image["payload"] for image in item["images"]], item["text_payload"]
            ),
        })
    for digest in sorted(set(image_objects) | set(text_objects)):
        if digest in admitted_train_object_hashes:
            raise ValueError(f"TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:{digest}")
    already_admitted = sorted(set(image_objects) & admitted_heldout_image_hashes)
    new_images = sorted(set(image_objects) - admitted_heldout_image_hashes)
    referenced = sorted(set(image_objects) | set(text_objects))
    admitted_here = sorted(set(new_images) | set(text_objects))
    census: dict[str, Any] = {
        "schema_version": CENSUS_SCHEMA,
        "result": "PASS",
        "source": {
            "benchmark_id": "MMMU",
            "revision": MMMU_REVISION,
            "split": "validation",
            "license_sha256": LICENSE_SHA256,
            "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
            "item_set_sha256": PROTECTED_ITEM_SET_SHA256,
            "answer_dictionary_sha256": ANSWER_DICTIONARY_SHA256,
            "answer_dictionary_access": "identity_only; never_read",
        },
        "parquet_file_count": parquet_file_count,
        "eligible_item_count": len(ids),
        "item_set_sha256": observed_item_set,
        "selection_rule": SELECTION_RULE,
        "text_canonicalization": TEXT_CANONICALIZATION,
        "unique_image_object_count": len(image_objects),
        "already_admitted_image_object_count": len(already_admitted),
        "already_admitted_image_object_set_sha256": sha(canonical(already_admitted)),
        "new_image_object_count": len(new_images),
        "item_text_object_count": len(text_objects),
        "train_intersection": {
            "executed": True,
            "admitted_train_object_count": len(admitted_train_object_hashes),
            "count": 0,
        },
        "referenced_object_count": len(referenced),
        "referenced_object_set_sha256": sha(canonical(referenced)),
        "admitted_object_count": len(admitted_here),
        "admitted_object_set_sha256": sha(canonical(admitted_here)),
        "image_objects": {
            digest: {key: value for key, value in row.items()}
            for digest, row in sorted(image_objects.items())
        },
        "items": census_items,
    }
    census["self_sha256"] = sha(canonical(census))
    return census


def verify_census(census: dict[str, Any]) -> None:
    body = dict(census)
    claimed = body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ValueError("CENSUS_SELF_SHA256_DRIFT_REFUSED")
    if (
        census.get("schema_version") != CENSUS_SCHEMA
        or census.get("result") != "PASS"
        or census.get("eligible_item_count") != EXPECTED_ITEM_COUNT
        or census.get("item_set_sha256") != PROTECTED_ITEM_SET_SHA256
        or census.get("selection_rule") != SELECTION_RULE
        or census.get("train_intersection", {}).get("count") != 0
        or census.get("train_intersection", {}).get("executed") is not True
        or len(census.get("items", [])) != EXPECTED_ITEM_COUNT
    ):
        raise ValueError("CENSUS_CONTRACT_DRIFT_REFUSED")


def build_admission_plan(
    census: dict[str, Any], *, payloads_by_sha: dict[str, bytes],
    admitted_heldout_image_hashes: set[str],
) -> dict[str, Any]:
    """Validate every payload against the census before any custody path exists."""

    verify_census(census)
    new_images = set()
    image_files: list[dict[str, Any]] = []
    for digest, row in census["image_objects"].items():
        if digest in admitted_heldout_image_hashes:
            continue
        new_images.add(digest)
        payload = payloads_by_sha.get(digest)
        if not isinstance(payload, bytes) or sha(payload) != digest or len(payload) != row["byte_count"]:
            raise ValueError(f"SELECTED_IMAGE_PAYLOAD_DRIFT_REFUSED:{digest}")
        image_files.append({
            "path": f"objects/{digest[:2]}/{digest}{row['suffix']}",
            "bytes": row["byte_count"],
            "sha256": digest,
            "source": dict(row["origin"]),
        })
    if len(new_images) != census["new_image_object_count"]:
        raise ValueError("NEW_IMAGE_OBJECT_TOTALITY_REFUSED")
    text_files: list[dict[str, Any]] = []
    for item in census["items"]:
        text = item["item_text_object"]
        digest = text["sha256"]
        payload = payloads_by_sha.get(digest)
        if not isinstance(payload, bytes) or sha(payload) != digest or len(payload) != text["byte_count"]:
            raise ValueError(f"ITEM_TEXT_PAYLOAD_DRIFT_REFUSED:{item['item_id']}")
        text_files.append({
            "path": f"items/{digest[:2]}/{digest}.json",
            "bytes": text["byte_count"],
            "sha256": digest,
            "source": {"subject": item["subject"], "row_id": item["item_id"]},
        })
    image_files.sort(key=lambda row: row["sha256"])
    text_files.sort(key=lambda row: row["sha256"])
    if len(text_files) != EXPECTED_ITEM_COUNT:
        raise ValueError("ITEM_TEXT_TOTALITY_REFUSED")
    admitted = sorted(row["sha256"] for row in image_files + text_files)
    if sha(canonical(admitted)) != census["admitted_object_set_sha256"]:
        raise ValueError("ADMITTED_OBJECT_SET_DRIFT_REFUSED")
    return {
        "schema_version": PLAN_SCHEMA,
        "result": "PASS",
        "selection_rule": SELECTION_RULE,
        "census_self_sha256": census["self_sha256"],
        "license_sha256": LICENSE_SHA256,
        "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
        "protected_item_set_sha256": PROTECTED_ITEM_SET_SHA256,
        "source_revision": MMMU_REVISION,
        "split": "heldout",
        "eligible_item_count": EXPECTED_ITEM_COUNT,
        "admitted_object_count": len(admitted),
        "selected_set_sha256": census["admitted_object_set_sha256"],
        "referenced_object_set_sha256": census["referenced_object_set_sha256"],
        "already_admitted_image_object_count": census["already_admitted_image_object_count"],
        "train_exclusion_assertion": "executed_pass",
        "rows": [
            {"domain": "image", "source_id": IMAGE_SOURCE_ID, "catalog_source_id": CATALOG_IMAGE_SOURCE_ID, "file_count": len(image_files)},
            {"domain": "text", "source_id": TEXT_SOURCE_ID, "catalog_source_id": CATALOG_TEXT_SOURCE_ID, "file_count": len(text_files)},
        ],
        "image_files": image_files,
        "text_files": text_files,
    }


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def _connector(
    *, source_id: str, files: list[dict[str, Any]], dest_root: Path,
    license_raw: bytes, upstream_url: str, fetched_at: str,
) -> bytes:
    rows = sorted(
        ({"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]} for row in files),
        key=lambda row: (row["path"], row["sha256"]),
    )
    connector = {
        "schema": "corpus-connector-receipt-v1",
        "source_id": source_id,
        "canonical_url": upstream_url,
        "fetched_at": fetched_at,
        "license": license_raw.decode("utf-8"),
        "dest_root": str(dest_root.resolve()),
        "total_bytes": sum(row["bytes"] for row in rows),
        "sha256_manifest": sha("\n".join(sorted(row["sha256"] for row in rows)).encode()),
        "files": rows,
    }
    return json.dumps(connector, sort_keys=True, indent=2).encode() + b"\n"


def write_admission_artifacts(
    *,
    plan: dict[str, Any],
    payloads_by_sha: dict[str, bytes],
    license_raw: bytes,
    custody_manifest_raw: bytes,
    output_root: Path,
    image_connector_path: Path,
    text_connector_path: Path,
    admission_receipt_path: Path,
    fetched_at: str,
) -> tuple[bytes, bytes, bytes]:
    """Create custody only after the complete read-only plan has passed."""

    if (
        output_root.exists()
        or image_connector_path.exists()
        or text_connector_path.exists()
        or admission_receipt_path.exists()
    ):
        raise ValueError("NO_OVERWRITE_REFUSED")
    if not fetched_at or "T" not in fetched_at or not fetched_at.endswith("Z"):
        raise ValueError("FETCHED_AT_REFUSED")
    custody = _verify_custody_manifest(custody_manifest_raw)
    output_root.mkdir(parents=True, exist_ok=False)
    image_root = output_root / "images"
    text_root = output_root / "items"
    for row in plan["image_files"]:
        write_new(image_root / Path(row["path"]), payloads_by_sha[row["sha256"]])
    for row in plan["text_files"]:
        write_new(text_root / Path(row["path"]), payloads_by_sha[row["sha256"]])
    upstream = str(custody["upstream_url"])
    image_raw = _connector(
        source_id=IMAGE_SOURCE_ID, files=plan["image_files"], dest_root=image_root,
        license_raw=license_raw, upstream_url=upstream, fetched_at=fetched_at,
    )
    text_raw = _connector(
        source_id=TEXT_SOURCE_ID, files=plan["text_files"], dest_root=text_root,
        license_raw=license_raw, upstream_url=upstream, fetched_at=fetched_at,
    )
    admission = dict(plan)
    admission["schema_version"] = ADMISSION_RECEIPT_SCHEMA
    admission["image_connector_receipt_raw_sha256"] = sha(image_raw)
    admission["text_connector_receipt_raw_sha256"] = sha(text_raw)
    admission["total_bytes"] = (
        json.loads(image_raw)["total_bytes"] + json.loads(text_raw)["total_bytes"]
    )
    admission["self_sha256"] = sha(canonical(admission))
    admission_raw = json.dumps(admission, sort_keys=True, indent=2).encode() + b"\n"
    write_new(image_connector_path, image_raw)
    write_new(text_connector_path, text_raw)
    write_new(admission_receipt_path, admission_raw)
    return image_raw, text_raw, admission_raw


def build_projection_spec(
    *, image_connector_path: Path, image_connector_raw: bytes,
    text_connector_path: Path, text_connector_raw: bytes,
    admission_receipt_path: Path, admission_receipt_raw: bytes,
    census_path: Path, census_raw: bytes, custody_manifest_path: Path, license_path: Path,
    tokenizer_sha256: str, created_at_ms: int,
) -> bytes:
    if len(tokenizer_sha256) != 64 or any(c not in "0123456789abcdef" for c in tokenizer_sha256):
        raise ValueError("TOKENIZER_SHA256_REFUSED")
    if isinstance(created_at_ms, bool) or not isinstance(created_at_ms, int) or created_at_ms < 0:
        raise ValueError("CREATED_AT_MS_REFUSED")
    supporting = [
        {"path": str(admission_receipt_path.resolve()), "sha256": sha(admission_receipt_raw)},
        {"path": str(census_path.resolve()), "sha256": sha(census_raw)},
        {"path": str(custody_manifest_path.resolve()), "sha256": CUSTODY_MANIFEST_SHA256},
        {"path": str(license_path.resolve()), "sha256": LICENSE_SHA256},
    ]
    rows = []
    for domain, source_id, selector, path, raw in (
        ("image", CATALOG_IMAGE_SOURCE_ID, IMAGE_SOURCE_ID, image_connector_path, image_connector_raw),
        ("text", CATALOG_TEXT_SOURCE_ID, TEXT_SOURCE_ID, text_connector_path, text_connector_raw),
    ):
        rows.append({
            "receipt_path": str(path.resolve()),
            "expected_receipt_sha256": sha(raw),
            "source_id": source_id,
            "expected_source_selector": selector,
            "expected_license_text_sha256": LICENSE_SHA256,
            "domain": domain,
            "split": "heldout",
            "supporting_receipts": list(supporting),
        })
    spec = {
        "schema_version": "ember-issue1581-catalog-projection-spec-v1",
        "tokenizer_sha256": tokenizer_sha256,
        "created_at_ms": created_at_ms,
        "rows": rows,
    }
    return json.dumps(spec, sort_keys=True, indent=2).encode() + b"\n"


def _catalog_binding(
    census: dict[str, Any], catalog_export_raw: bytes, dataset_ids: list[str],
) -> dict[str, Any]:
    try:
        catalog = json.loads(catalog_export_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("IMAGE_TEXT_CATALOG_EXPORT_UNREADABLE_REFUSED") from error
    records = catalog.get("records") if isinstance(catalog, dict) else None
    edges = catalog.get("edges") if isinstance(catalog, dict) else None
    if not isinstance(records, list) or not isinstance(edges, list) or not dataset_ids:
        raise ValueError("IMAGE_TEXT_CATALOG_EXPORT_SCHEMA_REFUSED")
    for dataset_id in dataset_ids:
        if not any(
            isinstance(row, dict)
            and row.get("kind") == "dataset_version"
            and row.get("id") == dataset_id
            and row.get("state") == "admitted"
            for row in records
        ):
            raise ValueError(f"IMAGE_TEXT_HELDOUT_DATASET_MISSING_REFUSED:{dataset_id}")
    membership_ids = {
        edge["to_id"] for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "version_membership"
        and edge.get("from_id") in dataset_ids
    }
    memberships = {
        row["id"]: row for row in records
        if isinstance(row, dict) and row.get("kind") == "membership" and row.get("id") in membership_ids
    }
    object_ids = {
        edge["to_id"] for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "membership_object"
        and edge.get("from_id") in membership_ids
    }
    expected_images = {f"sha256:{digest}" for digest in census["image_objects"]}
    expected_texts = {f"sha256:{item['item_text_object']['sha256']}" for item in census["items"]}
    expected = expected_images | expected_texts
    if (
        len(memberships) != len(membership_ids)
        or any(
            row.get("split") != "heldout"
            or row.get("admission_state") != "admitted"
            or row.get("domain") not in {"image", "text"}
            for row in memberships.values()
        )
        or not expected <= object_ids
    ):
        missing = sorted(expected - object_ids)[:3]
        raise ValueError(f"IMAGE_TEXT_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED:{len(expected & object_ids)}/{len(expected)}:{missing}")
    return {
        "dataset_ids": sorted(dataset_ids),
        "catalog_export_raw_sha256": sha(catalog_export_raw),
        "membership_count": len(memberships),
        "referenced_object_count": len(expected),
        "object_set_sha256": sha(canonical(sorted(expected))),
    }


def build_image_text_contract(
    census: dict[str, Any], *, image_connector_raw: bytes, text_connector_raw: bytes,
    predecessor_connector_raw: bytes, catalog_export_raw: bytes | None = None,
    dataset_ids: list[str] | None = None,
) -> dict[str, Any]:
    verify_census(census)
    try:
        predecessor = json.loads(predecessor_connector_raw)
        image_connector = json.loads(image_connector_raw)
        text_connector = json.loads(text_connector_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("IMAGE_TEXT_CONNECTOR_UNREADABLE_REFUSED") from error
    for connector, source_id in (
        (predecessor, PREDECESSOR_IMAGE_SOURCE_ID),
        (image_connector, IMAGE_SOURCE_ID),
        (text_connector, TEXT_SOURCE_ID),
    ):
        if connector.get("schema") != "corpus-connector-receipt-v1" or connector.get("source_id") != source_id:
            raise ValueError(f"IMAGE_TEXT_CONNECTOR_IDENTITY_REFUSED:{source_id}")
    predecessor_hashes = {row["sha256"] for row in predecessor["files"]}
    already = set(census["image_objects"]) & predecessor_hashes
    if (
        len(already) != census["already_admitted_image_object_count"]
        or sha(canonical(sorted(already))) != census["already_admitted_image_object_set_sha256"]
    ):
        raise ValueError("IMAGE_TEXT_PREDECESSOR_COVERAGE_REFUSED")
    carried = {row["sha256"] for row in image_connector["files"]} | {row["sha256"] for row in text_connector["files"]}
    referenced_images = set(census["image_objects"])
    texts = {item["item_text_object"]["sha256"] for item in census["items"]}
    if (carried | already) != (referenced_images | texts):
        raise ValueError("IMAGE_TEXT_CONNECTOR_COVERAGE_REFUSED")
    if (catalog_export_raw is None) != (dataset_ids is None):
        raise ValueError("IMAGE_TEXT_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED")
    frozen_items = [
        {
            "item_id": item["item_id"],
            "gold_item_sha256": item["gold_item_sha256"],
            "image_objects": [
                {"sha256": image["sha256"], "byte_count": image["byte_count"], "media_type": image["media_type"]}
                for image in item["image_objects"]
            ],
            "item_text_object": dict(item["item_text_object"]),
        }
        for item in census["items"]
    ]
    contract: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA,
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": TASK_ID,
            "consumes": ["image_payload_bytes", "item_text_payload_bytes"],
            "forbidden_inputs": list(FORBIDDEN_INPUTS),
            "prediction": "sha256(concat(image_payload_bytes in column order) + item_text_payload_bytes)",
            "scorer": "exact_match(prediction, gold_item_sha256)",
        },
        "source": {
            "revision": MMMU_REVISION,
            "connector_receipt_raw_sha256s": sorted(
                [sha(image_connector_raw), sha(text_connector_raw), sha(predecessor_connector_raw)]
            ),
            "connector_receipts": {
                "images": sha(image_connector_raw),
                "items": sha(text_connector_raw),
                "predecessor_images": sha(predecessor_connector_raw),
            },
            "census_self_sha256": census["self_sha256"],
            "license_sha256": LICENSE_SHA256,
            "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
            "protected_item_set_sha256": PROTECTED_ITEM_SET_SHA256,
            "answer_dictionary_sha256": ANSWER_DICTIONARY_SHA256,
            "answer_dictionary_access": "identity_only; never_read",
            "prediction_custody_access": "forbidden",
        },
        "text_canonicalization": TEXT_CANONICALIZATION,
        "selection_rule": SELECTION_RULE,
        "referenced_object_set_sha256": census["referenced_object_set_sha256"],
        "admitted_object_set_sha256": census["admitted_object_set_sha256"],
        "frozen_items": frozen_items,
        "totality": {
            "expected": EXPECTED_ITEM_COUNT,
            "observed": len(frozen_items),
            "complete": len(frozen_items) == EXPECTED_ITEM_COUNT,
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if catalog_export_raw is not None and dataset_ids is not None:
        contract["catalog_binding"] = _catalog_binding(census, catalog_export_raw, dataset_ids)
    contract["self_sha256"] = sha(canonical(contract))
    return contract


def read_admitted_train_object_hashes(catalog: Path) -> set[str]:
    connection = sqlite3.connect(
        catalog.resolve(strict=True).as_uri() + "?mode=ro&immutable=1", uri=True
    )
    try:
        rows = connection.execute(
            """
            SELECT json_extract(m.payload_json, '$.exact_sha256'),
                   lower(json_extract(o.payload_json, '$.media_type'))
            FROM data_catalog_records AS m
            JOIN data_catalog_records AS o
              ON o.kind = 'immutable_object'
             AND o.record_id = 'sha256:' || json_extract(m.payload_json, '$.exact_sha256')
            WHERE m.kind = 'membership'
              AND json_extract(m.payload_json, '$.admission_state') = 'admitted'
              AND json_extract(m.payload_json, '$.split') = 'train'
            """
        ).fetchall()
    finally:
        connection.close()
    images = {digest for digest, media in rows if isinstance(media, str) and media.startswith("image/")}
    if len(images) != EXPECTED_ADMITTED_TRAIN_IMAGE_COUNT:
        raise ValueError(f"TRAIN_IMAGE_CATALOG_COUNT_DRIFT_REFUSED:{len(images)}")
    return {digest for digest, _media in rows}


def read_admitted_heldout_image_hashes(catalog: Path) -> set[str]:
    connection = sqlite3.connect(
        catalog.resolve(strict=True).as_uri() + "?mode=ro&immutable=1", uri=True
    )
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
                  AND json_extract(m.payload_json, '$.split') = 'heldout'
                  AND lower(json_extract(o.payload_json, '$.media_type')) LIKE 'image/%'
                """
            )
        }
    finally:
        connection.close()
    if len(hashes) != EXPECTED_ADMITTED_HELDOUT_IMAGE_COUNT:
        raise ValueError(f"HELDOUT_IMAGE_CATALOG_COUNT_DRIFT_REFUSED:{len(hashes)}")
    return hashes


def payloads_from_items(items: list[dict[str, Any]]) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for item in items:
        for image in item["images"]:
            payloads[image["sha256"]] = image["payload"]
        payloads[item["text_sha256"]] = item["text_payload"]
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mmmu-root", type=Path, required=True)
    parser.add_argument("--license", type=Path, required=True)
    parser.add_argument("--custody-manifest", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True, help="census output (admit) or existing census (contract)")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--image-connector-receipt", type=Path)
    parser.add_argument("--text-connector-receipt", type=Path)
    parser.add_argument("--admission-receipt", type=Path)
    parser.add_argument("--fetched-at")
    parser.add_argument("--projection-spec", type=Path)
    parser.add_argument("--tokenizer-sha256")
    parser.add_argument("--created-at-ms", type=int)
    parser.add_argument("--image-connector-for-contract", type=Path)
    parser.add_argument("--text-connector-for-contract", type=Path)
    parser.add_argument("--predecessor-connector-receipt", type=Path)
    parser.add_argument("--catalog-export", type=Path)
    parser.add_argument("--dataset-id", action="append")
    parser.add_argument("--contract", type=Path)
    args = parser.parse_args()
    try:
        license_raw = args.license.read_bytes()
        custody_raw = args.custody_manifest.read_bytes()
        items, parquet_count = read_items(args.mmmu_root)
        heldout_images = read_admitted_heldout_image_hashes(args.catalog)
        census = build_census(
            items=items,
            parquet_file_count=parquet_count,
            license_raw=license_raw,
            custody_manifest_raw=custody_raw,
            admitted_train_object_hashes=read_admitted_train_object_hashes(args.catalog),
            admitted_heldout_image_hashes=heldout_images,
        )
        census_raw = json.dumps(census, sort_keys=True, indent=2).encode() + b"\n"
        if args.census.exists():
            if args.census.read_bytes() != census_raw:
                raise ValueError("CENSUS_DRIFT_FROM_RECORDED_REFUSED")
        else:
            write_new(args.census, census_raw)
        payloads = payloads_from_items(items)
        plan = build_admission_plan(
            census, payloads_by_sha=payloads, admitted_heldout_image_hashes=heldout_images
        )
        if args.plan is not None:
            plan_for_receipt = dict(plan)
            plan_for_receipt["self_sha256"] = sha(canonical(plan_for_receipt))
            write_new(args.plan, json.dumps(plan_for_receipt, sort_keys=True, indent=2).encode() + b"\n")
        artifact_values = [
            args.output_root, args.image_connector_receipt, args.text_connector_receipt,
            args.admission_receipt, args.fetched_at,
        ]
        image_raw = text_raw = None
        if any(value is not None for value in artifact_values):
            if any(value is None for value in artifact_values):
                raise ValueError("ADMISSION_ARTIFACT_ARGUMENT_TOTALITY_REFUSED")
            image_raw, text_raw, admission_raw = write_admission_artifacts(
                plan=plan,
                payloads_by_sha=payloads,
                license_raw=license_raw,
                custody_manifest_raw=custody_raw,
                output_root=args.output_root,
                image_connector_path=args.image_connector_receipt,
                text_connector_path=args.text_connector_receipt,
                admission_receipt_path=args.admission_receipt,
                fetched_at=args.fetched_at,
            )
            projection_values = [args.projection_spec, args.tokenizer_sha256, args.created_at_ms]
            if any(value is not None for value in projection_values):
                if any(value is None for value in projection_values):
                    raise ValueError("PROJECTION_SPEC_ARGUMENT_TOTALITY_REFUSED")
                write_new(args.projection_spec, build_projection_spec(
                    image_connector_path=args.image_connector_receipt,
                    image_connector_raw=image_raw,
                    text_connector_path=args.text_connector_receipt,
                    text_connector_raw=text_raw,
                    admission_receipt_path=args.admission_receipt,
                    admission_receipt_raw=admission_raw,
                    census_path=args.census,
                    census_raw=census_raw,
                    custody_manifest_path=args.custody_manifest,
                    license_path=args.license,
                    tokenizer_sha256=args.tokenizer_sha256,
                    created_at_ms=args.created_at_ms,
                ))
        if args.contract is not None:
            if args.predecessor_connector_receipt is None:
                raise ValueError("IMAGE_TEXT_CONTRACT_ARGUMENT_TOTALITY_REFUSED")
            if image_raw is None or text_raw is None:
                if args.image_connector_for_contract is None or args.text_connector_for_contract is None:
                    raise ValueError("IMAGE_TEXT_CONTRACT_ARGUMENT_TOTALITY_REFUSED")
                image_raw = args.image_connector_for_contract.read_bytes()
                text_raw = args.text_connector_for_contract.read_bytes()
            if (args.catalog_export is None) != (args.dataset_id is None):
                raise ValueError("IMAGE_TEXT_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED")
            contract = build_image_text_contract(
                census,
                image_connector_raw=image_raw,
                text_connector_raw=text_raw,
                predecessor_connector_raw=args.predecessor_connector_receipt.read_bytes(),
                catalog_export_raw=None if args.catalog_export is None else args.catalog_export.read_bytes(),
                dataset_ids=args.dataset_id,
            )
            write_new(args.contract, json.dumps(contract, sort_keys=True, indent=2).encode() + b"\n")
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}")
        return 2
    print(json.dumps({
        "result": "PASS",
        "eligible_item_count": census["eligible_item_count"],
        "new_image_object_count": census["new_image_object_count"],
        "already_admitted_image_object_count": census["already_admitted_image_object_count"],
        "item_text_object_count": census["item_text_object_count"],
        "admitted_object_set_sha256": census["admitted_object_set_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
