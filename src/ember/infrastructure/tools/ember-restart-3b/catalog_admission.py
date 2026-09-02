# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic #1581 bulk-row projection into the one Ember Lab data catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

# issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/domain_manifest.py
import importlib.util as _ember_465614ebb0a85785_importlib
import sys as _ember_465614ebb0a85785_sys
from pathlib import Path as _ember_465614ebb0a85785_Path
_ember_465614ebb0a85785_path = _ember_465614ebb0a85785_Path(__file__).resolve().parent.joinpath('domain_manifest.py')
if not _ember_465614ebb0a85785_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/domain_manifest.py')
_ember_465614ebb0a85785_aliases = ('_ember_issue2015_465614ebb0a85785', 'domain_manifest', 'src.ember.infrastructure.tools.ember-restart-3b.domain_manifest')
_ember_465614ebb0a85785_existing = []
for _ember_465614ebb0a85785_alias in _ember_465614ebb0a85785_aliases:
    _ember_465614ebb0a85785_candidate = _ember_465614ebb0a85785_sys.modules.get(_ember_465614ebb0a85785_alias)
    if _ember_465614ebb0a85785_candidate is not None and all(_ember_465614ebb0a85785_candidate is not item for item in _ember_465614ebb0a85785_existing):
        _ember_465614ebb0a85785_existing.append(_ember_465614ebb0a85785_candidate)
if len(_ember_465614ebb0a85785_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/domain_manifest.py')
if _ember_465614ebb0a85785_existing:
    _ember_465614ebb0a85785_module = _ember_465614ebb0a85785_existing[0]
    _ember_465614ebb0a85785_observed = getattr(_ember_465614ebb0a85785_module, '__file__', None)
    if _ember_465614ebb0a85785_observed is None or _ember_465614ebb0a85785_Path(_ember_465614ebb0a85785_observed).resolve() != _ember_465614ebb0a85785_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/domain_manifest.py')
else:
    _ember_465614ebb0a85785_spec = _ember_465614ebb0a85785_importlib.spec_from_file_location('_ember_issue2015_465614ebb0a85785', _ember_465614ebb0a85785_path)
    if _ember_465614ebb0a85785_spec is None or _ember_465614ebb0a85785_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/domain_manifest.py')
    _ember_465614ebb0a85785_module = _ember_465614ebb0a85785_importlib.module_from_spec(_ember_465614ebb0a85785_spec)
    for _ember_465614ebb0a85785_alias in _ember_465614ebb0a85785_aliases:
        _ember_465614ebb0a85785_prior = _ember_465614ebb0a85785_sys.modules.get(_ember_465614ebb0a85785_alias)
        if _ember_465614ebb0a85785_prior is not None and _ember_465614ebb0a85785_prior is not _ember_465614ebb0a85785_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/domain_manifest.py')
        _ember_465614ebb0a85785_sys.modules[_ember_465614ebb0a85785_alias] = _ember_465614ebb0a85785_module
    try:
        _ember_465614ebb0a85785_spec.loader.exec_module(_ember_465614ebb0a85785_module)
    except BaseException:
        for _ember_465614ebb0a85785_alias in _ember_465614ebb0a85785_aliases:
            if _ember_465614ebb0a85785_sys.modules.get(_ember_465614ebb0a85785_alias) is _ember_465614ebb0a85785_module:
                _ember_465614ebb0a85785_sys.modules.pop(_ember_465614ebb0a85785_alias, None)
        raise
for _ember_465614ebb0a85785_alias in _ember_465614ebb0a85785_aliases:
    _ember_465614ebb0a85785_prior = _ember_465614ebb0a85785_sys.modules.get(_ember_465614ebb0a85785_alias)
    if _ember_465614ebb0a85785_prior is not None and _ember_465614ebb0a85785_prior is not _ember_465614ebb0a85785_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/domain_manifest.py')
    _ember_465614ebb0a85785_sys.modules[_ember_465614ebb0a85785_alias] = _ember_465614ebb0a85785_module
load_bulk_domain_connector_receipt = getattr(_ember_465614ebb0a85785_module, 'load_bulk_domain_connector_receipt')
_connector_media_type = getattr(_ember_465614ebb0a85785_module, '_connector_media_type')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/domain_manifest.py
from input_identity import (
    resolve_catalog_evaluation_dataset,
    resolve_catalog_training_datasets,
)
from mint_github_license_partition import validate_partition_receipt


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _milliseconds(timestamp: str) -> int:
    try:
        return int(
            datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000
        )
    except (TypeError, ValueError) as error:
        raise ValueError("connector fetched_at is not an ISO timestamp") from error


def _sorted_manifest(
    records: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> bytes:
    records.sort(key=lambda row: (row["kind"], row["id"]))
    edges.sort(
        key=lambda row: (
            row["kind"],
            row["from_kind"],
            row["from_id"],
            row["to_kind"],
            row["to_id"],
            row["ordinal"],
        )
    )
    return _canonical(
        {
            "schema_version": "ember-data-catalog-manifest-v1",
            "records": records,
            "edges": edges,
        }
    )


def build_dataset_catalog_manifest(
    *, rows: list[dict[str, Any]], tokenizer_sha256: str, created_at_ms: int
) -> bytes:
    """Build one admitted split-honest dataset from content-addressed connector rows."""

    tokenizer_sha256 = _require_sha(tokenizer_sha256, "tokenizer identity")
    if (
        not rows
        or isinstance(created_at_ms, bool)
        or not isinstance(created_at_ms, int)
        or created_at_ms < 0
    ):
        raise ValueError("catalog dataset rows and creation time are required")
    ordered_rows = sorted(rows, key=lambda row: row["source_id"])
    if len({row["source_id"] for row in ordered_rows}) != len(ordered_rows):
        raise ValueError("catalog source identities must be unique")
    splits = {row.get("split") for row in ordered_rows}
    if len(splits) != 1 or next(iter(splits)) not in {"train", "heldout"}:
        raise ValueError("catalog rows must contain one admitted split")
    split = next(iter(splits))
    if any(f"-{split}-" not in row["source_id"] for row in ordered_rows):
        raise ValueError("catalog source identity split does not match the declared split")
    identity_rows = [
        {
            "source_id": row["source_id"],
            "domain": row["domain"],
            "split": row["split"],
            "receipt_sha256": row["receipt_sha256"],
            "supporting_receipt_sha256": row.get("supporting_receipt_sha256", []),
            "manifest_sha256": row["manifest_sha256"],
            "files": [
                {
                    "bytes": item["bytes"],
                    "sha256": item["sha256"],
                    "media_type": item["media_type"],
                }
                for item in row["files"]
            ],
        }
        for row in ordered_rows
    ]
    dataset_manifest_sha256 = _sha256(_canonical(identity_rows))
    dataset_id = f"dataset:issue1581-bulk-{split}:{dataset_manifest_sha256}"
    records: list[dict[str, Any]] = [
        {
            "kind": "dataset_version",
            "id": dataset_id,
            "name": f"issue1581-bulk-{split}-front",
            "manifest_sha256": dataset_manifest_sha256,
            "created_at_ms": created_at_ms,
            "version_class": "genesis",
            "state": "admitted",
        }
    ]
    edges: list[dict[str, Any]] = []
    objects: dict[str, int] = {}
    memberships: set[str] = set()
    membership_ordinal = 0
    for row in ordered_rows:
        source_record_id = f"source:{row['source_id']}"
        receipt_id = f"sha256:{_require_sha(row['receipt_sha256'], 'connector receipt identity')}"
        for value in row.get("supporting_receipt_sha256", []):
            _require_sha(value, "supporting receipt identity")
        records.extend(
            [
                {
                    "kind": "source",
                    "id": source_record_id,
                    "canonical_url": row["canonical_url"],
                    "revision": f"sha256:{row['manifest_sha256']}",
                    "license_text_sha256": row["license_text_sha256"],
                    "license_verdict": "accepted",
                    "access_class": "public",
                    "acquired_at_ms": _milliseconds(row["fetched_at"]),
                    "refusal_reason": None,
                },
                {
                    "kind": "receipt",
                    "id": receipt_id,
                    "sha256": row["receipt_sha256"],
                    "producing_authority": "corpus_connector",
                    "receipt_class": "acquisition",
                    "observed_at_ms": _milliseconds(row["fetched_at"]),
                    "state": "accepted",
                },
            ]
        )
        for source_ordinal, item in enumerate(row["files"]):
            digest = _require_sha(item["sha256"], "source object identity")
            byte_count = item["bytes"]
            if digest in objects and objects[digest] != byte_count:
                raise ValueError(
                    "one immutable object hash is bound to conflicting byte counts"
                )
            if digest not in objects:
                objects[digest] = byte_count
                records.append(
                    {
                        "kind": "immutable_object",
                        "id": f"sha256:{digest}",
                        "sha256": digest,
                        "byte_count": byte_count,
                        "media_type": item["media_type"],
                        "locator": f"sha256/{digest[:2]}/{digest}",
                        "custody_state": "available",
                    }
                )
            membership_id = f"membership:{row['source_id']}:{digest}"
            if membership_id in memberships:
                continue
            memberships.add(membership_id)
            records.append(
                {
                    "kind": "membership",
                    "id": membership_id,
                    "domain": row["domain"],
                    "register": "L4",
                    "split": split,
                    "tokenizer_sha256": tokenizer_sha256,
                    "shard_id": f"shard:sha256:{digest}",
                    "window_start": 0,
                    "window_end": byte_count,
                    "exact_sha256": digest,
                    "near_dedup_cluster": f"sha256:{digest}",
                    "admission_state": "admitted",
                }
            )
            edges.extend(
                [
                    {
                        "kind": "source_object",
                        "from_kind": "source",
                        "from_id": source_record_id,
                        "to_kind": "immutable_object",
                        "to_id": f"sha256:{digest}",
                        "ordinal": source_ordinal,
                        "payload": {},
                    },
                    {
                        "kind": "object_receipt",
                        "from_kind": "immutable_object",
                        "from_id": f"sha256:{digest}",
                        "to_kind": "receipt",
                        "to_id": receipt_id,
                        "ordinal": 0,
                        "payload": {},
                    },
                    {
                        "kind": "version_membership",
                        "from_kind": "dataset_version",
                        "from_id": dataset_id,
                        "to_kind": "membership",
                        "to_id": membership_id,
                        "ordinal": membership_ordinal,
                        "payload": {},
                    },
                    {
                        "kind": "membership_object",
                        "from_kind": "membership",
                        "from_id": membership_id,
                        "to_kind": "immutable_object",
                        "to_id": f"sha256:{digest}",
                        "ordinal": 0,
                        "payload": {},
                    },
                ]
            )
            membership_ordinal += 1
    return _sorted_manifest(records, edges)


def _verified_import_receipt(
    raw: bytes,
    *,
    expected_export_sha256: str | None = None,
    expected_input_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("catalog import receipt is unreadable") from error
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "ember-data-catalog-import-receipt-v1"
        or value.get("result") != "PASS"
    ):
        raise ValueError("catalog import receipt is not PASS")
    claimed = value.pop("self_sha256", None)
    if claimed != _sha256(_canonical(value)):
        raise ValueError("catalog import receipt self hash is invalid")
    value["self_sha256"] = claimed
    if (
        expected_export_sha256 is not None
        and value.get("canonical_export_sha256") != expected_export_sha256
    ):
        raise ValueError("catalog import receipt does not bind the canonical export")
    if (
        expected_input_manifest_sha256 is not None
        and value.get("input_manifest_raw_sha256") != expected_input_manifest_sha256
    ):
        raise ValueError("catalog import receipt does not bind the input manifest")
    return value


def build_evaluation_consumer_catalog_fragment(
    *,
    catalog_export_raw: bytes,
    first_import_receipt_raw: bytes,
    dataset_id: str,
    e_matrix_packet_raw: bytes,
    source_commit: str,
    model_sha256: str,
    checkpoint_sha256: str,
    tokenizer_sha256: str,
    config_sha256: str,
    evaluator_sha256: str,
) -> bytes:
    """Build a heldout-only evaluation consumer fragment."""

    try:
        catalog = json.loads(catalog_export_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("canonical catalog export is unreadable") from error
    records = catalog.get("records") if isinstance(catalog, dict) else None
    edges = catalog.get("edges") if isinstance(catalog, dict) else None
    if not isinstance(records, list) or not isinstance(edges, list):
        raise ValueError("canonical catalog export schema is invalid")
    membership_ids = {
        edge["to_id"]
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "version_membership"
        and edge.get("from_id") == dataset_id
        and isinstance(edge.get("to_id"), str)
    }
    memberships = [
        row
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "membership"
        and row.get("id") in membership_ids
    ]
    if (
        dataset_id.startswith("dataset:issue1581-bulk-train:")
        or not membership_ids
        or len(memberships) != len(membership_ids)
        or any(row.get("split") != "heldout" for row in memberships)
    ):
        raise ValueError("evaluation consumer admits only heldout datasets")
    heldout_object_ids = {
        edge["to_id"]
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "membership_object"
        and edge.get("from_id") in membership_ids
        and isinstance(edge.get("to_id"), str)
    }
    heldout_mapped_membership_ids = {
        edge["from_id"]
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "membership_object"
        and edge.get("from_id") in membership_ids
        and isinstance(edge.get("to_id"), str)
    }
    train_membership_ids = {
        row["id"]
        for row in records
        if isinstance(row, dict)
        and row.get("kind") == "membership"
        and row.get("split") == "train"
        and row.get("admission_state") == "admitted"
        and isinstance(row.get("id"), str)
    }
    train_object_ids = {
        edge["to_id"]
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "membership_object"
        and edge.get("from_id") in train_membership_ids
        and isinstance(edge.get("to_id"), str)
    }
    train_mapped_membership_ids = {
        edge["from_id"]
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "membership_object"
        and edge.get("from_id") in train_membership_ids
        and isinstance(edge.get("to_id"), str)
    }
    if (
        heldout_mapped_membership_ids != set(membership_ids)
        or train_mapped_membership_ids != train_membership_ids
        or not heldout_object_ids
        or heldout_object_ids.intersection(train_object_ids)
    ):
        raise ValueError("evaluation dataset is absent or overlaps admitted train objects")
    fragment = json.loads(
        build_consumer_catalog_fragment(
            catalog_export_raw=catalog_export_raw,
            first_import_receipt_raw=first_import_receipt_raw,
            dataset_id=dataset_id,
            e_matrix_packet_raw=e_matrix_packet_raw,
            source_commit=source_commit,
            model_sha256=model_sha256,
            checkpoint_sha256=checkpoint_sha256,
            tokenizer_sha256=tokenizer_sha256,
            config_sha256=config_sha256,
            evaluator_sha256=evaluator_sha256,
        )
    )
    attempt = next(
        row for row in fragment["records"] if row.get("kind") == "consumer_attempt"
    )
    old_attempt_id = attempt["id"]
    new_attempt_id = (
        f"attempt:issue1581-catalog-evaluation:{_sha256(catalog_export_raw)}"
    )
    attempt["id"] = new_attempt_id
    attempt["run_attempt_id"] = new_attempt_id
    protected_eval = next(
        row for row in fragment["records"] if row.get("kind") == "protected_eval"
    )
    protected_eval["ngram_ruling"] = "not_run"
    protected_eval["near_dup_ruling"] = "not_run"
    protected_eval["exclusion_reason"] = None
    protected_eval["overlap_state"] = "isolated"
    for edge in fragment["edges"]:
        if edge.get("from_id") != old_attempt_id:
            continue
        edge["from_id"] = new_attempt_id
    return _sorted_manifest(fragment["records"], fragment["edges"])


def build_consumer_catalog_fragment(
    *,
    catalog_export_raw: bytes,
    first_import_receipt_raw: bytes,
    dataset_id: str,
    e_matrix_packet_raw: bytes,
    source_commit: str,
    model_sha256: str,
    checkpoint_sha256: str,
    tokenizer_sha256: str,
    config_sha256: str,
    evaluator_sha256: str,
) -> bytes:
    export_sha = _sha256(catalog_export_raw)
    _verified_import_receipt(
        first_import_receipt_raw, expected_export_sha256=export_sha
    )
    catalog = json.loads(catalog_export_raw)
    if not any(
        row.get("kind") == "dataset_version"
        and row.get("id") == dataset_id
        and row.get("state") == "admitted"
        for row in catalog.get("records", [])
    ):
        raise ValueError("consumer dataset is absent from the canonical catalog export")
    for label, value in [
        ("model", model_sha256),
        ("checkpoint", checkpoint_sha256),
        ("tokenizer", tokenizer_sha256),
        ("config", config_sha256),
        ("evaluator", evaluator_sha256),
    ]:
        _require_sha(value, f"{label} identity")
    if len(source_commit) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit
    ):
        raise ValueError("source commit must be a lowercase Git SHA")
    e_matrix_sha = _sha256(e_matrix_packet_raw)
    first_receipt_sha = _sha256(first_import_receipt_raw)
    attempt_id = f"attempt:issue1581-catalog-preflight:{export_sha}"
    evaluation_id = f"evaluation:e-matrix-catalog-isolation:{e_matrix_sha}"
    records = [
        {
            "kind": "immutable_object",
            "id": f"sha256:{e_matrix_sha}",
            "sha256": e_matrix_sha,
            "byte_count": len(e_matrix_packet_raw),
            "media_type": "application/json",
            "locator": f"sha256/{e_matrix_sha[:2]}/{e_matrix_sha}",
            "custody_state": "available",
        },
        {
            "kind": "protected_eval",
            "id": evaluation_id,
            "frozen_manifest_sha256": e_matrix_sha,
            "test_set_sha256": e_matrix_sha,
            "ngram_ruling": "refused",
            "near_dup_ruling": "refused",
            "exclusion_reason": "protected item admission remains unresolved; catalog-bound train identities stay isolated",
            "overlap_state": "unknown",
            "frozen_at_ms": 0,
        },
        {
            "kind": "consumer_attempt",
            "id": attempt_id,
            "run_attempt_id": attempt_id,
            "model_sha256": model_sha256,
            "checkpoint_sha256": checkpoint_sha256,
            "tokenizer_sha256": tokenizer_sha256,
            "config_sha256": config_sha256,
            "source_tree_sha": source_commit,
            "evaluator_sha256": evaluator_sha256,
            "state": "admitted",
        },
        {
            "kind": "receipt",
            "id": f"sha256:{first_receipt_sha}",
            "sha256": first_receipt_sha,
            "producing_authority": "ember_lab",
            "receipt_class": "consumer",
            "observed_at_ms": 0,
            "state": "accepted",
        },
        {
            "kind": "receipt",
            "id": f"sha256:{e_matrix_sha}",
            "sha256": e_matrix_sha,
            "producing_authority": "evaluation",
            "receipt_class": "evaluation",
            "observed_at_ms": 0,
            "state": "accepted",
        },
    ]
    edges = [
        {
            "kind": "evaluation_object",
            "from_kind": "protected_eval",
            "from_id": evaluation_id,
            "to_kind": "immutable_object",
            "to_id": f"sha256:{e_matrix_sha}",
            "ordinal": 0,
            "payload": {},
        },
        {
            "kind": "evaluation_receipt",
            "from_kind": "protected_eval",
            "from_id": evaluation_id,
            "to_kind": "receipt",
            "to_id": f"sha256:{e_matrix_sha}",
            "ordinal": 0,
            "payload": {},
        },
        {
            "kind": "consumer_dataset",
            "from_kind": "consumer_attempt",
            "from_id": attempt_id,
            "to_kind": "dataset_version",
            "to_id": dataset_id,
            "ordinal": 0,
            "payload": {},
        },
        {
            "kind": "consumer_evaluation",
            "from_kind": "consumer_attempt",
            "from_id": attempt_id,
            "to_kind": "protected_eval",
            "to_id": evaluation_id,
            "ordinal": 0,
            "payload": {},
        },
        {
            "kind": "consumer_receipt",
            "from_kind": "consumer_attempt",
            "from_id": attempt_id,
            "to_kind": "receipt",
            "to_id": f"sha256:{first_receipt_sha}",
            "ordinal": 0,
            "payload": {},
        },
    ]
    return _sorted_manifest(records, edges)


def revalidate_e_matrix_catalog_bindings(
    *, e_matrix_packet_raw: bytes, resolved_identity: dict[str, Any]
) -> dict[str, Any]:
    packet = json.loads(e_matrix_packet_raw)
    if packet.get("schema_version") == "ember-issue1581-slot-e-matrix-definition-v1":
        rows = packet.get("rows")
        if (
            set(packet) != {"schema_version", "rows"}
            or not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
            or set(rows[0]) != {"row_id", "state"}
            or rows[0].get("state") != "ABSENT"
        ):
            raise ValueError("slot E-MATRIX requires exactly one absent slot row")
        source_ids = resolved_identity.get("source_ids")
        if not isinstance(source_ids, list) or len(source_ids) != 1:
            raise ValueError("catalog must derive exactly one slot from source/object edges")
        expected_slot_id = source_ids[0]
        if rows[0].get("row_id") != expected_slot_id:
            raise ValueError("slot row does not match the catalog-derived slot identity")
        protected = resolved_identity["split"] == "heldout"
        return {
            "schema_version": "ember-issue1581-slot-e-matrix-revalidation-v1",
            "catalog_export_sha256": resolved_identity["catalog_export_sha256"],
            "expected_slot_id": expected_slot_id,
            "rows": [
                {
                    "row_id": expected_slot_id,
                    "state": "PRESENT",
                    "catalog_dataset_binding": "PRESENT",
                    "catalog_dataset_id": resolved_identity["dataset_id"],
                    "catalog_dataset_split": resolved_identity["split"],
                    "protected": protected,
                    "protected_eval_admission_satisfied": protected,
                }
            ],
        }
    rows = []
    for original in packet.get("rows", []):
        row = dict(original)
        split = resolved_identity["split"]
        row["catalog_dataset_binding"] = "PRESENT"
        row["catalog_dataset_id"] = resolved_identity["dataset_id"]
        row["catalog_dataset_split"] = split
        if split == "train":
            row["catalog_train_dataset_binding"] = "PRESENT"
            row["catalog_train_dataset_id"] = resolved_identity["dataset_id"]
        row["protected"] = split == "heldout"
        row["protected_eval_admission_satisfied"] = split == "heldout"
        rows.append(row)
    return {
        "schema_version": "ember-issue1581-e-matrix-catalog-revalidation-v1",
        "catalog_export_sha256": resolved_identity["catalog_export_sha256"],
        "rows": rows,
    }


_PROJECTION_SPEC_FIELDS = {
    "schema_version",
    "tokenizer_sha256",
    "created_at_ms",
    "rows",
}
_PROJECTION_ROW_FIELDS = {
    "receipt_path",
    "expected_receipt_sha256",
    "source_id",
    "expected_source_selector",
    "expected_license_text_sha256",
    "domain",
    "split",
    "supporting_receipts",
}
_TRAIN_PARTITION_PROJECTION_ROW_FIELDS = {
    "license_partition_receipt_path",
    "license_partition_receipt_sha256",
    "source_id",
    "domain",
    "split",
    "supporting_receipts",
}
_SUPPORTING_RECEIPT_FIELDS = {"path", "sha256"}
_PARTITION_MEDIA_TYPE_TABLE = Path(__file__).with_name("train_partition_media_types.json")


def _partition_media_class(path: PurePosixPath) -> str:
    return path.suffix.lower() if path.suffix else f"<name:{path.name.lower()}>"


def _load_partition_media_type_table() -> dict[str, Any]:
    raw = _read(_PARTITION_MEDIA_TYPE_TABLE)
    table = json.loads(raw)
    self_sha = table.pop("self_sha256", None)
    if self_sha != _sha256(_canonical(table)):
        raise ValueError("PARTITION_PROJECTION_MEDIA_TABLE_SELF_HASH_REFUSED")
    table["self_sha256"] = self_sha
    if (
        table.get("schema_version") != "ember-issue1581-train-partition-media-types-v1"
        or table.get("goal_id") != "EMBER-02"
        or table.get("workstream_id") != "EMBER-02B"
        or table.get("next_executed_outcome")
        != "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        or table.get("class_count") != len(table.get("classes", {}))
        or table.get("file_count") != sum(row.get("count", 0) for row in table.get("classes", {}).values())
    ):
        raise ValueError("PARTITION_PROJECTION_MEDIA_TABLE_SCHEMA_REFUSED")
    return table


def _partition_media_type(path: PurePosixPath, table: dict[str, Any]) -> str:
    """Classify via the existing mapper or an explicit census-bound class row."""

    try:
        return _connector_media_type(path)
    except ValueError as error:
        if "unsupported media type" not in str(error):
            raise
        key = _partition_media_class(path)
        row = table["classes"].get(key)
        if row is None:
            raise ValueError(
                f"PARTITION_PROJECTION_MEDIA_CLASS_UNMAPPED:{key}:{path.as_posix()}"
            ) from error
        return row["media_type"]


def _load_train_partition_projection(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("split") != "train" or "-train-" not in row.get("source_id", ""):
        raise ValueError("PARTITION_PROJECTION_SPLIT_REFUSED:train authority required")
    receipt_path = Path(row["license_partition_receipt_path"])
    expected_sha = _require_sha(
        row["license_partition_receipt_sha256"], "partition receipt identity"
    )
    receipt_raw = _read(receipt_path)
    if _sha256(receipt_raw) != expected_sha:
        raise ValueError("PARTITION_PROJECTION_RECEIPT_HASH_DRIFT")
    try:
        receipt = validate_partition_receipt(receipt_path)
    except (OSError, ValueError) as error:
        raise ValueError(f"PARTITION_PROJECTION_AUTHORITY_REFUSED:{error}") from error
    for field in ("source_id", "domain", "split"):
        if receipt.get(field) != row[field]:
            raise ValueError(f"PARTITION_PROJECTION_{field.upper()}_SUBSTITUTION")
    source_path = Path(receipt["source_connector_receipt_path"])
    source_raw = _read(source_path)
    if _sha256(source_raw) != receipt["source_connector_receipt_sha256"]:
        raise ValueError("PARTITION_PROJECTION_SOURCE_RECEIPT_HASH_DRIFT")
    try:
        source = json.loads(source_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("PARTITION_PROJECTION_SOURCE_RECEIPT_UNREADABLE") from error
    if (
        not isinstance(source, dict)
        or source.get("schema") != "corpus-connector-receipt-v1"
        or not isinstance(source.get("canonical_url"), str)
        or not isinstance(source.get("fetched_at"), str)
    ):
        raise ValueError("PARTITION_PROJECTION_SOURCE_RECEIPT_SCHEMA_REFUSED")
    media_table = _load_partition_media_type_table()
    unsupported_counts: dict[str, int] = {}
    files = [
        {
            "bytes": item["bytes"],
            "sha256": item["sha256"],
            "media_type": _partition_media_type(PurePosixPath(item["path"]), media_table),
        }
        for repository in receipt["repositories"]
        for item in repository["files"]
        if item["bytes"] > 0
    ]
    for repository in receipt["repositories"]:
        for item in repository["files"]:
            if item["bytes"] <= 0:
                continue
            path = PurePosixPath(item["path"])
            try:
                _connector_media_type(path)
            except ValueError as error:
                if "unsupported media type" not in str(error):
                    raise
                key = _partition_media_class(path)
                unsupported_counts[key] = unsupported_counts.get(key, 0) + 1
    expected_counts = {
        key: row["count"] for key, row in media_table["classes"].items()
    }
    if unsupported_counts != expected_counts:
        raise ValueError("PARTITION_PROJECTION_MEDIA_CLASS_COUNTS_REFUSED")
    if not files:
        raise ValueError("PARTITION_PROJECTION_EMPTY_PARTITION_REFUSED")
    return {
        "source_id": row["source_id"],
        "domain": row["domain"],
        "split": row["split"],
        "receipt_sha256": expected_sha,
        "manifest_sha256": receipt["partition_root_sha256"],
        "canonical_url": source["canonical_url"],
        "fetched_at": source["fetched_at"],
        "license_text_sha256": _sha256(_canonical(receipt["license_summary"])),
        "files": files,
    }


def project_catalog_spec(*, spec_raw: bytes) -> bytes:
    """Execute a closed projection spec and return only path-free catalog metadata."""

    try:
        spec = json.loads(spec_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("catalog projection spec is unreadable") from error
    if (
        not isinstance(spec, dict)
        or set(spec) != _PROJECTION_SPEC_FIELDS
        or spec.get("schema_version") != "ember-issue1581-catalog-projection-spec-v1"
        or not isinstance(spec.get("rows"), list)
        or not spec["rows"]
    ):
        raise ValueError("catalog projection spec has an invalid closed schema")
    rows = []
    for row in spec["rows"]:
        if not isinstance(row, dict) or set(row) not in (
            _PROJECTION_ROW_FIELDS,
            _TRAIN_PARTITION_PROJECTION_ROW_FIELDS,
        ):
            raise ValueError("catalog projection row has an invalid closed schema")
        supporting_receipt_sha256 = []
        supporting_receipts = row["supporting_receipts"]
        if not isinstance(supporting_receipts, list):
            raise TypeError("supporting receipt authority must be a list")
        for supporting in supporting_receipts:
            if (
                not isinstance(supporting, dict)
                or set(supporting) != _SUPPORTING_RECEIPT_FIELDS
            ):
                raise ValueError("supporting receipt has an invalid closed schema")
            raw = _read(Path(supporting["path"]))
            claimed = _require_sha(supporting["sha256"], "supporting receipt identity")
            if _sha256(raw) != claimed:
                raise ValueError(
                    "supporting receipt bytes do not match the frozen identity"
                )
            supporting_receipt_sha256.append(claimed)
        if set(row) == _TRAIN_PARTITION_PROJECTION_ROW_FIELDS:
            projected = _load_train_partition_projection(row)
        else:
            projected = load_bulk_domain_connector_receipt(
                receipt_path=Path(row["receipt_path"]),
                expected_receipt_sha256=row["expected_receipt_sha256"],
                source_id=row["source_id"],
                expected_source_selector=row["expected_source_selector"],
                expected_license_text_sha256=row["expected_license_text_sha256"],
                domain=row["domain"],
                split=row["split"],
            )
        projected["supporting_receipt_sha256"] = supporting_receipt_sha256
        rows.append(projected)
    return build_dataset_catalog_manifest(
        rows=rows,
        tokenizer_sha256=spec["tokenizer_sha256"],
        created_at_ms=spec["created_at_ms"],
    )


def _dataset_resolver_for_manifest(
    manifest_raw: bytes, *, expected_dataset_id: str
) -> tuple[Any, str]:
    """Select train or evaluation resolution only from an exact catalog edge."""

    try:
        manifest = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("catalog consumer manifest is unreadable") from error
    edges = manifest.get("edges") if isinstance(manifest, dict) else None
    if not isinstance(edges, list):
        raise ValueError("catalog consumer manifest schema is invalid")
    matching_edges = [
        edge
        for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "consumer_dataset"
        and edge.get("to_id") == expected_dataset_id
    ]
    if len(matching_edges) != 1:
        raise ValueError(
            "catalog consumer manifest must select exactly one dataset resolver"
        )
    attempt_id = matching_edges[0].get("from_id")
    has_training_edge = (
        isinstance(attempt_id, str)
        and attempt_id.startswith("attempt:issue1581-catalog-preflight:")
    )
    has_evaluation_edge = (
        isinstance(attempt_id, str)
        and attempt_id.startswith("attempt:issue1581-catalog-evaluation:")
    )
    if has_training_edge == has_evaluation_edge:
        raise ValueError(
            "catalog consumer manifest must select exactly one dataset resolver"
        )
    if has_evaluation_edge:
        return resolve_catalog_evaluation_dataset, "heldout"
    return resolve_catalog_training_datasets, "train"


def finalize_catalog_admission(
    *,
    projection_manifest_raw: bytes,
    first_import_receipt_raw: bytes,
    replay_import_receipt_raw: bytes,
    first_catalog_export_raw: bytes,
    replay_catalog_export_raw: bytes,
    consumer_fragment_raw: bytes,
    consumer_import_receipt_raw: bytes,
    final_catalog_export_raw: bytes,
    e_matrix_packet_raw: bytes,
    e_matrix_revalidation_raw: bytes,
    expected_dataset_id: str,
) -> bytes:
    """Verify the complete import/replay/consumer chain and emit a self-hashed PASS."""

    first_export_sha = _sha256(first_catalog_export_raw)
    projection_manifest_sha = _sha256(projection_manifest_raw)
    consumer_fragment_sha = _sha256(consumer_fragment_raw)
    if first_catalog_export_raw != replay_catalog_export_raw:
        raise ValueError("catalog idempotent replay export bytes have drifted")
    first = _verified_import_receipt(
        first_import_receipt_raw,
        expected_export_sha256=first_export_sha,
        expected_input_manifest_sha256=projection_manifest_sha,
    )
    replay = _verified_import_receipt(
        replay_import_receipt_raw,
        expected_export_sha256=first_export_sha,
        expected_input_manifest_sha256=projection_manifest_sha,
    )
    final = _verified_import_receipt(
        consumer_import_receipt_raw,
        expected_export_sha256=_sha256(final_catalog_export_raw),
        expected_input_manifest_sha256=consumer_fragment_sha,
    )
    if (
        not isinstance(first.get("inserted_records"), int)
        or first["inserted_records"] <= 0
        or not isinstance(first.get("inserted_edges"), int)
        or first["inserted_edges"] <= 0
        or replay.get("inserted_records") != 0
        or replay.get("inserted_edges") != 0
        or not isinstance(final.get("inserted_records"), int)
        or final["inserted_records"] <= 0
        or not isinstance(final.get("inserted_edges"), int)
        or final["inserted_edges"] <= 0
    ):
        raise ValueError(
            "catalog import counts do not prove first/replay/consumer execution"
        )
    source_commits = {
        first.get("source_commit"),
        replay.get("source_commit"),
        final.get("source_commit"),
    }
    if len(source_commits) != 1:
        raise ValueError("catalog import receipts do not share one source commit")
    resolver, expected_split = _dataset_resolver_for_manifest(
        consumer_fragment_raw, expected_dataset_id=expected_dataset_id
    )
    resolved = resolver(
        catalog_export_raw=final_catalog_export_raw,
        dataset_import_receipt_raw=first_import_receipt_raw,
        consumer_import_receipt_raw=consumer_import_receipt_raw,
        expected_dataset_id=expected_dataset_id,
        expected_split=expected_split,
    )
    expected_revalidation = revalidate_e_matrix_catalog_bindings(
        e_matrix_packet_raw=e_matrix_packet_raw,
        resolved_identity=resolved,
    )
    try:
        revalidation = json.loads(e_matrix_revalidation_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("E-MATRIX catalog revalidation is unreadable") from error
    if revalidation != expected_revalidation:
        raise ValueError(
            "E-MATRIX catalog revalidation does not match the resolved identity"
        )
    payload = {
        "schema_version": "ember-issue1581-catalog-admission-terminal-v1",
        "result": "PASS",
        "source_commit": next(iter(source_commits)),
        "dataset_id": resolved["dataset_id"],
        "object_count": resolved["object_count"],
        "object_set_sha256": resolved["object_set_sha256"],
        "projection_manifest_raw_sha256": projection_manifest_sha,
        "first_import_receipt_raw_sha256": _sha256(first_import_receipt_raw),
        "replay_import_receipt_raw_sha256": _sha256(replay_import_receipt_raw),
        "first_and_replay_catalog_export_sha256": first_export_sha,
        "consumer_fragment_raw_sha256": consumer_fragment_sha,
        "consumer_import_receipt_raw_sha256": _sha256(consumer_import_receipt_raw),
        "final_catalog_export_sha256": resolved["catalog_export_sha256"],
        "e_matrix_packet_raw_sha256": _sha256(e_matrix_packet_raw),
        "e_matrix_revalidation_raw_sha256": _sha256(e_matrix_revalidation_raw),
        "protected_eval_item_admission": resolved["protected_eval_item_admission"],
        "catalog_admission_source_sha256": _sha256(Path(__file__).read_bytes()),
    }
    payload["self_sha256"] = _sha256(_canonical(payload))
    return _canonical(payload)


def write_new(path: Path, raw: bytes) -> None:
    """Write one immutable output, refusing an existing path."""

    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise ValueError(
            f"required catalog-admission input is unreadable: {path.name}"
        ) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project and verify the governed #1581 data-catalog admission front."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    project = commands.add_parser("project")
    project.add_argument("--spec", required=True, type=Path)
    project.add_argument("--output", required=True, type=Path)

    consumer = commands.add_parser("consumer")
    consumer.add_argument("--catalog-export", required=True, type=Path)
    consumer.add_argument("--dataset-import-receipt", required=True, type=Path)
    consumer.add_argument("--dataset-id", required=True)
    consumer.add_argument("--e-matrix-packet", required=True, type=Path)
    consumer.add_argument("--source-commit", required=True)
    for name in ["model", "checkpoint", "tokenizer", "config", "evaluator"]:
        consumer.add_argument(f"--{name}-sha256", required=True)
    consumer.add_argument("--output", required=True, type=Path)

    evaluation_consumer = commands.add_parser("evaluation-consumer")
    evaluation_consumer.add_argument("--catalog-export", required=True, type=Path)
    evaluation_consumer.add_argument(
        "--dataset-import-receipt", required=True, type=Path
    )
    evaluation_consumer.add_argument("--dataset-id", required=True)
    evaluation_consumer.add_argument("--e-matrix-packet", required=True, type=Path)
    evaluation_consumer.add_argument("--source-commit", required=True)
    for name in ["model", "checkpoint", "tokenizer", "config", "evaluator"]:
        evaluation_consumer.add_argument(f"--{name}-sha256", required=True)
    evaluation_consumer.add_argument("--output", required=True, type=Path)

    revalidate = commands.add_parser("revalidate")
    revalidate.add_argument("--catalog-export", required=True, type=Path)
    revalidate.add_argument("--dataset-import-receipt", required=True, type=Path)
    revalidate.add_argument("--consumer-import-receipt", required=True, type=Path)
    revalidate.add_argument("--dataset-id", required=True)
    revalidate.add_argument("--e-matrix-packet", required=True, type=Path)
    revalidate.add_argument("--output", required=True, type=Path)

    finalize = commands.add_parser("finalize")
    for name in [
        "projection-manifest",
        "first-import-receipt",
        "replay-import-receipt",
        "first-catalog-export",
        "replay-catalog-export",
        "consumer-fragment",
        "consumer-import-receipt",
        "final-catalog-export",
        "e-matrix-packet",
        "e-matrix-revalidation",
    ]:
        finalize.add_argument(f"--{name}", required=True, type=Path)
    finalize.add_argument("--dataset-id", required=True)
    finalize.add_argument("--output", required=True, type=Path)

    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "project":
            output = project_catalog_spec(spec_raw=_read(arguments.spec))
        elif arguments.command in {"consumer", "evaluation-consumer"}:
            builder = (
                build_evaluation_consumer_catalog_fragment
                if arguments.command == "evaluation-consumer"
                else build_consumer_catalog_fragment
            )
            output = builder(
                catalog_export_raw=_read(arguments.catalog_export),
                first_import_receipt_raw=_read(arguments.dataset_import_receipt),
                dataset_id=arguments.dataset_id,
                e_matrix_packet_raw=_read(arguments.e_matrix_packet),
                source_commit=arguments.source_commit,
                model_sha256=arguments.model_sha256,
                checkpoint_sha256=arguments.checkpoint_sha256,
                tokenizer_sha256=arguments.tokenizer_sha256,
                config_sha256=arguments.config_sha256,
                evaluator_sha256=arguments.evaluator_sha256,
            )
        elif arguments.command == "revalidate":
            catalog_export_raw = _read(arguments.catalog_export)
            resolver, expected_split = _dataset_resolver_for_manifest(
                catalog_export_raw, expected_dataset_id=arguments.dataset_id
            )
            resolved = resolver(
                catalog_export_raw=catalog_export_raw,
                dataset_import_receipt_raw=_read(arguments.dataset_import_receipt),
                consumer_import_receipt_raw=_read(arguments.consumer_import_receipt),
                expected_dataset_id=arguments.dataset_id,
                expected_split=expected_split,
            )
            output = _canonical(
                revalidate_e_matrix_catalog_bindings(
                    e_matrix_packet_raw=_read(arguments.e_matrix_packet),
                    resolved_identity=resolved,
                )
            )
        else:
            output = finalize_catalog_admission(
                projection_manifest_raw=_read(arguments.projection_manifest),
                first_import_receipt_raw=_read(arguments.first_import_receipt),
                replay_import_receipt_raw=_read(arguments.replay_import_receipt),
                first_catalog_export_raw=_read(arguments.first_catalog_export),
                replay_catalog_export_raw=_read(arguments.replay_catalog_export),
                consumer_fragment_raw=_read(arguments.consumer_fragment),
                consumer_import_receipt_raw=_read(arguments.consumer_import_receipt),
                final_catalog_export_raw=_read(arguments.final_catalog_export),
                e_matrix_packet_raw=_read(arguments.e_matrix_packet),
                e_matrix_revalidation_raw=_read(arguments.e_matrix_revalidation),
                expected_dataset_id=arguments.dataset_id,
            )
        write_new(arguments.output, output)
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
