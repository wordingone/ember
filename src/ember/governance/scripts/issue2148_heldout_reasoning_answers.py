#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Admit one canonical answer object per admitted heldout MMMU item (#2148).

The item set IS the #2130 protected image-text contract's frozen item set (847 MMMU
validation items, contract self sha frozen below).  There is no N and no sampling.
Per item this module reads exactly the ``answer`` column of the item's parquet row,
canonicalizes it to ``{answer, id}``, and binds the item to its already-admitted
item-text object (read from the #2130 items connector custody, never re-admitted)
and its new answer object.  ``explanation``, ``subfield``, ``topic_difficulty``,
``img_type`` and every image column are never read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

CENSUS_SCHEMA = "ember-issue2148-heldout-reasoning-answer-census-v1"
PLAN_SCHEMA = "ember-issue2148-heldout-reasoning-answer-admission-plan-v1"
ADMISSION_RECEIPT_SCHEMA = "ember-issue2148-heldout-reasoning-answer-admission-receipt-v1"
CONTRACT_SCHEMA = "ember-issue1947-protected-reasoning-contract-v1"
PREDECESSOR_CONTRACT_SCHEMA = "ember-protected-image-text-contract-v1"
TASK_ID = "EXACT_REASONING_ITEM_IDENTITY"
FORBIDDEN_INPUTS = [
    "explanation", "subfield", "topic_difficulty", "img_type", "image_payloads", "prediction_custody",
]
PREDECESSOR_CONTRACT_SELF_SHA256 = "50d4a8361b55e99365b24f9ff5776eb903f3c1ad512256d5685acd6ab159d05b"
PREDECESSOR_ADMITTED_OBJECT_SET_SHA256 = "308a1e4ee3ea4cc1ef2bb433fbb32f68d0a59cbf84af6bc33666f7226c0c2bf1"
CUSTODY_MANIFEST_SHA256 = "20af6ef398cd7913ea0ba5b53025dbf568eab6d74f7290d01ceda30c4a206b03"
LICENSE_SHA256 = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
SOURCE_URL = "https://github.com/MMMU-Benchmark/MMMU.git"
EXPECTED_ITEM_COUNT = 847
EXPECTED_PARQUET_FILE_COUNT = 30
PREDECESSOR_ITEMS_SOURCE_ID = "mmmu-validation-heldout-image-text-items"
ANSWER_SOURCE_ID = "mmmu-validation-heldout-reasoning-answers"
CATALOG_ANSWER_SOURCE_ID = "candidate-reasoning-answers-heldout-0"
TEXT_MEDIA_TYPE = "application/json"
ANSWER_KEYS = ("answer", "id")
TEXT_CANONICALIZATION = (
    "json.dumps({'id','answer'}, sort_keys=True, separators=(',',':'), ensure_ascii=True) + LF; "
    "answer = the parquet `answer` string verbatim; explanation, subfield, topic_difficulty, "
    "img_type and image columns are never members and never read"
)
SELECTION_RULE = (
    "item set IS the #2130 protected image-text contract's frozen item set (self sha frozen); "
    "one canonical answer object per item; no N, no sampling; item-text objects are "
    "referenced from the predecessor dataset and never re-admitted; exact exclusion of "
    "every admitted train object sha256 asserted; selected_set_sha256 of this carrier = "
    "sha256 of the sorted answer-object sha256 set"
)
CLAIM_BOUNDARY = (
    "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, "
    "OR GOAL CREDIT"
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def answer_text_object(item_id: str, answer: str) -> bytes:
    if not item_id or not isinstance(answer, str) or not answer:
        raise ValueError(f"ANSWER_EMPTY_REFUSED:{item_id}")
    payload = {"answer": answer, "id": item_id}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def item_gold_sha256(item_text_payload: bytes, answer_payload: bytes) -> str:
    return sha(item_text_payload + answer_payload)


def _verified_predecessor_contract(raw: bytes) -> dict[str, Any]:
    try:
        contract = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("PREDECESSOR_CONTRACT_UNREADABLE_REFUSED") from error
    body = dict(contract) if isinstance(contract, dict) else {}
    claimed = body.pop("self_sha256", None)
    if not body or claimed != PREDECESSOR_CONTRACT_SELF_SHA256 or sha(canonical(body)) != PREDECESSOR_CONTRACT_SELF_SHA256:
        raise ValueError("PREDECESSOR_CONTRACT_SELF_SHA256_DRIFT_REFUSED")
    frozen = contract.get("frozen_items")
    if (
        contract.get("schema_version") != PREDECESSOR_CONTRACT_SCHEMA
        or contract.get("result") != "PASS"
        or not isinstance(frozen, list)
        or contract.get("totality") != {"expected": EXPECTED_ITEM_COUNT, "observed": EXPECTED_ITEM_COUNT, "complete": True}
        or contract.get("admitted_object_set_sha256") != PREDECESSOR_ADMITTED_OBJECT_SET_SHA256
    ):
        raise ValueError("PREDECESSOR_CONTRACT_TOTALITY_REFUSED")
    for row in frozen:
        text = row.get("item_text_object") if isinstance(row, dict) else None
        if (
            not isinstance(row.get("item_id"), str)
            or not isinstance(text, dict)
            or not isinstance(text.get("sha256"), str)
            or not isinstance(text.get("byte_count"), int)
        ):
            raise ValueError("PREDECESSOR_CONTRACT_ITEM_SCHEMA_REFUSED")  # noqa: TRY004
    return contract


def _verify_custody_manifest(custody_manifest_raw: bytes) -> dict[str, Any]:
    if sha(custody_manifest_raw) != CUSTODY_MANIFEST_SHA256:
        raise ValueError("CUSTODY_MANIFEST_SHA256_DRIFT_REFUSED")
    try:
        custody = json.loads(custody_manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("CUSTODY_MANIFEST_UNREADABLE_REFUSED") from error
    if not isinstance(custody, dict) or custody.get("license_sha256") != LICENSE_SHA256:
        raise ValueError("CUSTODY_MANIFEST_LICENSE_BINDING_REFUSED")
    return custody


def read_answers(mmmu_root: Path, predecessor_contract_raw: bytes) -> tuple[list[dict[str, Any]], int]:
    """Read ONLY the `id` and `answer` columns of every validation parquet; image and
    metadata columns are never projected. The predecessor contract is verified first."""

    contract = _verified_predecessor_contract(predecessor_contract_raw)
    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise ValueError("PYARROW_UNAVAILABLE_REFUSED") from error
    subject_dirs = sorted(
        path for path in mmmu_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )
    answers: dict[str, str] = {}
    parquet_count = 0
    for subject_dir in subject_dirs:
        paths = sorted(subject_dir.glob("validation-*.parquet"))
        if len(paths) != 1:
            raise ValueError(f"MMMU_SUBJECT_PARQUET_TOTALITY_REFUSED:{subject_dir.name}:{len(paths)}")
        parquet_count += 1
        for row in pq.read_table(paths[0], columns=["id", "answer"]).to_pylist():
            item_id = row.get("id")
            if not isinstance(item_id, str):
                raise ValueError("MMMU_ROW_ID_REFUSED")  # noqa: TRY004
            if item_id in answers:
                raise ValueError(f"MMMU_ITEM_ID_DUPLICATE_REFUSED:{item_id}")
            answers[item_id] = row.get("answer")
    if parquet_count != EXPECTED_PARQUET_FILE_COUNT:
        raise ValueError(f"MMMU_PARQUET_FILE_COUNT_REFUSED:{parquet_count}")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in sorted(contract["frozen_items"], key=lambda entry: entry["item_id"]):
        item_id = row["item_id"]
        if item_id in seen:
            raise ValueError(f"ITEM_ID_DUPLICATE_REFUSED:{item_id}")
        seen.add(item_id)
        if item_id not in answers:
            raise ValueError(f"ANSWER_ROW_MISSING_REFUSED:{item_id}")
        answer_payload = answer_text_object(item_id, answers[item_id])
        items.append({
            "item_id": item_id,
            "item_text_sha256": row["item_text_object"]["sha256"],
            "item_text_byte_count": row["item_text_object"]["byte_count"],
            "answer_payload": answer_payload,
            "answer_sha256": sha(answer_payload),
        })
    return items, parquet_count


def read_predecessor_text_payloads(
    predecessor_connector_raw: bytes, items: list[dict[str, Any]],
) -> dict[str, bytes]:
    """Item-text bytes come from the #2130 admitted custody (connector dest_root), verified
    per object against the contract identity; the parquet question columns are never read."""

    try:
        connector = json.loads(predecessor_connector_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("PREDECESSOR_CONNECTOR_UNREADABLE_REFUSED") from error
    if (
        not isinstance(connector, dict)
        or connector.get("schema") != "corpus-connector-receipt-v1"
        or connector.get("source_id") != PREDECESSOR_ITEMS_SOURCE_ID
    ):
        raise ValueError("PREDECESSOR_CONNECTOR_IDENTITY_REFUSED")
    root_value = connector.get("dest_root")
    files = connector.get("files")
    if not isinstance(root_value, str) or not isinstance(files, list):
        raise ValueError("PREDECESSOR_CONNECTOR_TOTALITY_REFUSED")  # noqa: TRY004
    root = Path(root_value)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("PREDECESSOR_CUSTODY_ROOT_MISSING_REFUSED")
    root = root.resolve()
    by_sha = {row["sha256"]: row for row in files if isinstance(row, dict) and isinstance(row.get("sha256"), str)}
    if set(by_sha) != {item["item_text_sha256"] for item in items} or len(by_sha) != len(files):
        raise ValueError("PREDECESSOR_CONNECTOR_COVERAGE_REFUSED")
    payloads: dict[str, bytes] = {}
    for item in items:
        row = by_sha[item["item_text_sha256"]]
        if row.get("bytes") != item["item_text_byte_count"] or not isinstance(row.get("path"), str):
            raise ValueError(f"PREDECESSOR_TEXT_IDENTITY_REFUSED:{item['item_id']}")
        physical = (root / Path(row["path"])).resolve()
        try:
            physical.relative_to(root)
        except ValueError as error:
            raise ValueError(f"PREDECESSOR_TEXT_PATH_ESCAPE_REFUSED:{item['item_id']}") from error
        raw = physical.read_bytes()
        if sha(raw) != item["item_text_sha256"] or len(raw) != item["item_text_byte_count"]:
            raise ValueError(f"PREDECESSOR_TEXT_PAYLOAD_DRIFT_REFUSED:{item['item_id']}")
        payloads[item["item_text_sha256"]] = raw
    return payloads


def build_census(
    *,
    items: list[dict[str, Any]],
    parquet_file_count: int,
    license_raw: bytes,
    custody_manifest_raw: bytes,
    predecessor_contract_raw: bytes,
    predecessor_connector_raw: bytes,
    text_payloads: dict[str, bytes],
    admitted_train_object_hashes: set[str],
    admitted_heldout_text_hashes: set[str],
) -> dict[str, Any]:
    """Read-only census: identities, pairing, train exclusion. No custody is written."""

    if sha(license_raw) != LICENSE_SHA256:
        raise ValueError("LICENSE_SHA256_DRIFT_REFUSED")
    _verify_custody_manifest(custody_manifest_raw)
    if parquet_file_count != EXPECTED_PARQUET_FILE_COUNT:
        raise ValueError(f"MMMU_PARQUET_FILE_COUNT_REFUSED:{parquet_file_count}")
    predecessor = _verified_predecessor_contract(predecessor_contract_raw)
    ids = [item["item_id"] for item in items]
    if ids != sorted(ids) or len(ids) != EXPECTED_ITEM_COUNT or len(set(ids)) != len(ids):
        raise ValueError(f"ITEM_COUNT_REFUSED:{len(ids)}")
    text_hashes = {item["item_text_sha256"] for item in items}
    # The item set is bound by set equality with the predecessor contract's frozen items, never by
    # re-deriving an identity under a formula of this module's own.
    if text_hashes != {row["item_text_object"]["sha256"] for row in predecessor["frozen_items"]} or len(text_hashes) != len(ids):
        raise ValueError("PREDECESSOR_ITEM_SET_DRIFT_REFUSED")
    if not text_hashes <= admitted_heldout_text_hashes:
        raise ValueError(
            f"HELDOUT_TEXT_CATALOG_COVERAGE_REFUSED:{len(admitted_heldout_text_hashes & text_hashes)}/{len(text_hashes)}"
        )
    if set(text_payloads) != text_hashes:
        raise ValueError("TEXT_PAYLOAD_COVERAGE_REFUSED")
    answer_objects: dict[str, str] = {}
    census_items: list[dict[str, Any]] = []
    for item in items:
        digest = item["answer_sha256"]
        if sha(item["answer_payload"]) != digest:
            raise ValueError(f"ANSWER_OBJECT_IDENTITY_DRIFT_REFUSED:{item['item_id']}")
        # The answer object must be the canonical {answer, id} of THIS item: a payload carrying another
        # item's id (two answers swapped) is answer drift and refuses the census before any custody exists.
        try:
            decoded = json.loads(item["answer_payload"])
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"ANSWER_ITEM_ID_DRIFT_REFUSED:{item['item_id']}") from error
        if (
            not isinstance(decoded, dict)
            or set(decoded) != set(ANSWER_KEYS)
            or decoded.get("id") != item["item_id"]
            or not isinstance(decoded.get("answer"), str)
            or answer_text_object(item["item_id"], decoded["answer"]) != item["answer_payload"]
        ):
            raise ValueError(f"ANSWER_ITEM_ID_DRIFT_REFUSED:{item['item_id']}")
        if digest in answer_objects or digest in text_hashes:
            raise ValueError(f"ANSWER_OBJECT_IDENTITY_CONFLICT_REFUSED:{digest}")
        answer_objects[digest] = item["item_id"]
        census_items.append({
            "item_id": item["item_id"],
            "item_text_object": {
                "sha256": item["item_text_sha256"],
                "byte_count": item["item_text_byte_count"],
                "media_type": TEXT_MEDIA_TYPE,
            },
            "answer_object": {
                "sha256": digest,
                "byte_count": len(item["answer_payload"]),
                "media_type": TEXT_MEDIA_TYPE,
            },
            "gold_item_sha256": item_gold_sha256(text_payloads[item["item_text_sha256"]], item["answer_payload"]),
        })
    referenced = sorted(text_hashes | set(answer_objects))
    for digest in referenced:
        if digest in admitted_train_object_hashes:
            raise ValueError(f"TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:{digest}")
    admitted_here = sorted(answer_objects)
    census: dict[str, Any] = {
        "schema_version": CENSUS_SCHEMA,
        "result": "PASS",
        "source": {
            "benchmark_id": "MMMU",
            "split": "validation",
            "source_url": SOURCE_URL,
            "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
            "license_sha256": LICENSE_SHA256,
            "predecessor_contract_self_sha256": PREDECESSOR_CONTRACT_SELF_SHA256,
            "predecessor_admitted_object_set_sha256": PREDECESSOR_ADMITTED_OBJECT_SET_SHA256,
            "predecessor_source_id": PREDECESSOR_ITEMS_SOURCE_ID,
            "predecessor_connector_receipt_raw_sha256": sha(predecessor_connector_raw),
            "metadata_columns_access": "never_read (explanation, subfield, topic_difficulty, img_type, images)",
        },
        "parquet_file_count": parquet_file_count,
        "item_count": len(ids),
        "selection_rule": SELECTION_RULE,
        "text_canonicalization": TEXT_CANONICALIZATION,
        "item_text_object_count": len(text_hashes),
        "answer_object_count": len(answer_objects),
        "train_intersection": {
            "executed": True,
            "admitted_train_object_count": len(admitted_train_object_hashes),
            "count": 0,
        },
        "referenced_object_count": len(referenced),
        "referenced_object_set_sha256": sha(canonical(referenced)),
        "admitted_object_count": len(admitted_here),
        "admitted_object_set_sha256": sha(canonical(admitted_here)),
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
        or census.get("item_count") != EXPECTED_ITEM_COUNT
        or census.get("source", {}).get("predecessor_contract_self_sha256") != PREDECESSOR_CONTRACT_SELF_SHA256
        or census.get("selection_rule") != SELECTION_RULE
        or census.get("train_intersection", {}).get("count") != 0
        or census.get("train_intersection", {}).get("executed") is not True
        or len(census.get("items", [])) != EXPECTED_ITEM_COUNT
    ):
        raise ValueError("CENSUS_CONTRACT_DRIFT_REFUSED")


def build_admission_plan(census: dict[str, Any], *, payloads_by_sha: dict[str, bytes]) -> dict[str, Any]:
    """Validate every answer payload against the census before any custody path exists."""

    verify_census(census)
    answer_files: list[dict[str, Any]] = []
    for item in census["items"]:
        answer = item["answer_object"]
        digest = answer["sha256"]
        payload = payloads_by_sha.get(digest)
        if not isinstance(payload, bytes) or sha(payload) != digest or len(payload) != answer["byte_count"]:
            raise ValueError(f"ANSWER_PAYLOAD_DRIFT_REFUSED:{item['item_id']}")
        answer_files.append({
            "path": f"answers/{digest[:2]}/{digest}.json",
            "bytes": answer["byte_count"],
            "sha256": digest,
            "source": {"item_id": item["item_id"]},
        })
    answer_files.sort(key=lambda row: row["sha256"])
    if len(answer_files) != EXPECTED_ITEM_COUNT:
        raise ValueError("ANSWER_TOTALITY_REFUSED")
    admitted = sorted(row["sha256"] for row in answer_files)
    if sha(canonical(admitted)) != census["admitted_object_set_sha256"]:
        raise ValueError("ADMITTED_OBJECT_SET_DRIFT_REFUSED")
    return {
        "schema_version": PLAN_SCHEMA,
        "result": "PASS",
        "selection_rule": SELECTION_RULE,
        "census_self_sha256": census["self_sha256"],
        "license_sha256": LICENSE_SHA256,
        "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
        "predecessor_contract_self_sha256": PREDECESSOR_CONTRACT_SELF_SHA256,
        "split": "heldout",
        "item_count": EXPECTED_ITEM_COUNT,
        "admitted_object_count": len(admitted),
        "selected_set_sha256": census["admitted_object_set_sha256"],
        "referenced_object_set_sha256": census["referenced_object_set_sha256"],
        "item_text_objects_reference": "predecessor dataset; never re-admitted",
        "train_exclusion_assertion": "executed_pass",
        "rows": [
            {"domain": "text", "source_id": ANSWER_SOURCE_ID, "catalog_source_id": CATALOG_ANSWER_SOURCE_ID, "file_count": len(answer_files)},
        ],
        "answer_files": answer_files,
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
    output_root: Path,
    answer_connector_path: Path,
    admission_receipt_path: Path,
    fetched_at: str,
) -> tuple[bytes, bytes]:
    """Create custody only after the complete read-only plan has passed."""

    if output_root.exists() or answer_connector_path.exists() or admission_receipt_path.exists():
        raise ValueError("NO_OVERWRITE_REFUSED")
    if not fetched_at or "T" not in fetched_at or not fetched_at.endswith("Z"):
        raise ValueError("FETCHED_AT_REFUSED")
    output_root.mkdir(parents=True, exist_ok=False)
    answer_root = output_root / "answers"
    for row in plan["answer_files"]:
        write_new(answer_root / Path(row["path"]), payloads_by_sha[row["sha256"]])
    answer_raw = _connector(
        source_id=ANSWER_SOURCE_ID, files=plan["answer_files"], dest_root=answer_root,
        license_raw=license_raw, upstream_url=SOURCE_URL, fetched_at=fetched_at,
    )
    admission = dict(plan)
    admission["schema_version"] = ADMISSION_RECEIPT_SCHEMA
    admission["answer_connector_receipt_raw_sha256"] = sha(answer_raw)
    admission["total_bytes"] = json.loads(answer_raw)["total_bytes"]
    admission["self_sha256"] = sha(canonical(admission))
    admission_raw = json.dumps(admission, sort_keys=True, indent=2).encode() + b"\n"
    write_new(answer_connector_path, answer_raw)
    write_new(admission_receipt_path, admission_raw)
    return answer_raw, admission_raw


def build_projection_spec(
    *, answer_connector_path: Path, answer_connector_raw: bytes,
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
    spec = {
        "schema_version": "ember-issue1581-catalog-projection-spec-v1",
        "tokenizer_sha256": tokenizer_sha256,
        "created_at_ms": created_at_ms,
        "rows": [{
            "receipt_path": str(answer_connector_path.resolve()),
            "expected_receipt_sha256": sha(answer_connector_raw),
            "source_id": CATALOG_ANSWER_SOURCE_ID,
            "expected_source_selector": ANSWER_SOURCE_ID,
            "expected_license_text_sha256": LICENSE_SHA256,
            "domain": "text",
            "split": "heldout",
            "supporting_receipts": supporting,
        }],
    }
    return json.dumps(spec, sort_keys=True, indent=2).encode() + b"\n"


def _catalog_binding(
    census: dict[str, Any], catalog_export_raw: bytes, dataset_ids: list[str],
) -> dict[str, Any]:
    """Prove, from the live export, that every referenced object (847 item texts + 847 answers) is a
    member of one of the named admitted heldout dataset versions through an admitted heldout
    membership, and that none of them is a member of any admitted TRAIN membership anywhere in
    the export. The predecessor items dataset also carries the #2130 image memberships; those are
    not referenced here and are neither required nor refused."""

    try:
        catalog = json.loads(catalog_export_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("REASONING_CATALOG_EXPORT_UNREADABLE_REFUSED") from error
    records = catalog.get("records") if isinstance(catalog, dict) else None
    edges = catalog.get("edges") if isinstance(catalog, dict) else None
    if not isinstance(records, list) or not isinstance(edges, list) or not dataset_ids:
        raise ValueError("REASONING_CATALOG_EXPORT_SCHEMA_REFUSED")
    for dataset_id in dataset_ids:
        if not any(
            isinstance(row, dict)
            and row.get("kind") == "dataset_version"
            and row.get("id") == dataset_id
            and row.get("state") == "admitted"
            for row in records
        ):
            raise ValueError(f"REASONING_HELDOUT_DATASET_MISSING_REFUSED:{dataset_id}")
    memberships = {row["id"]: row for row in records if isinstance(row, dict) and row.get("kind") == "membership"}
    objects_by_membership: dict[str, set[str]] = {}
    for edge in edges:
        if isinstance(edge, dict) and edge.get("kind") == "membership_object" and isinstance(edge.get("from_id"), str):
            objects_by_membership.setdefault(edge["from_id"], set()).add(edge.get("to_id"))
    dataset_memberships = {
        edge["to_id"] for edge in edges
        if isinstance(edge, dict)
        and edge.get("kind") == "version_membership"
        and edge.get("from_id") in dataset_ids
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
    expected_texts = {f"sha256:{item['item_text_object']['sha256']}" for item in census["items"]}
    expected_answers = {f"sha256:{item['answer_object']['sha256']}" for item in census["items"]}
    expected = expected_texts | expected_answers
    if not expected <= heldout_objects:
        missing = sorted(expected - heldout_objects)[:3]
        raise ValueError(
            f"REASONING_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED:{len(expected & heldout_objects)}/{len(expected)}:{missing}"
        )
    overlap = sorted(expected & train_objects)
    if overlap:
        raise ValueError(f"REASONING_TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:{len(overlap)}:{overlap[:3]}")
    covering = sorted(
        membership_id for membership_id in dataset_memberships
        if objects_by_membership.get(membership_id, set()) & expected
    )
    return {
        "dataset_ids": sorted(dataset_ids),
        "catalog_export_raw_sha256": sha(catalog_export_raw),
        "membership_count": len(covering),
        "referenced_object_count": len(expected),
        "object_set_sha256": sha(canonical(sorted(expected))),
        "train_exclusion": {
            "executed": True,
            "admitted_train_membership_count": admitted_train_membership_count,
            "admitted_train_object_count": len(train_objects),
            "overlap_count": 0,
        },
    }


def build_reasoning_contract(
    census: dict[str, Any], *, answer_connector_raw: bytes, predecessor_connector_raw: bytes,
    predecessor_contract_raw: bytes, catalog_export_raw: bytes | None = None,
    dataset_ids: list[str] | None = None,
) -> dict[str, Any]:
    verify_census(census)
    try:
        predecessor = json.loads(predecessor_connector_raw)
        answer_connector = json.loads(answer_connector_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("REASONING_CONNECTOR_UNREADABLE_REFUSED") from error
    for connector, source_id in (
        (predecessor, PREDECESSOR_ITEMS_SOURCE_ID),
        (answer_connector, ANSWER_SOURCE_ID),
    ):
        if connector.get("schema") != "corpus-connector-receipt-v1" or connector.get("source_id") != source_id:
            raise ValueError(f"REASONING_CONNECTOR_IDENTITY_REFUSED:{source_id}")
    if sha(predecessor_connector_raw) != census["source"]["predecessor_connector_receipt_raw_sha256"]:
        raise ValueError("REASONING_PREDECESSOR_CONNECTOR_BINDING_REFUSED")
    texts = {item["item_text_object"]["sha256"] for item in census["items"]}
    answers = {item["answer_object"]["sha256"] for item in census["items"]}
    if {row["sha256"] for row in predecessor["files"]} != texts:
        raise ValueError("REASONING_PREDECESSOR_COVERAGE_REFUSED")
    if {row["sha256"] for row in answer_connector["files"]} != answers:
        raise ValueError("REASONING_CONNECTOR_COVERAGE_REFUSED")
    predecessor_contract = _verified_predecessor_contract(predecessor_contract_raw)
    if {row["item_text_object"]["sha256"] for row in predecessor_contract["frozen_items"]} != texts:
        raise ValueError("REASONING_PREDECESSOR_ITEM_SET_DRIFT_REFUSED")
    if (catalog_export_raw is None) != (dataset_ids is None):
        raise ValueError("REASONING_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED")
    frozen_items = [
        {
            "item_id": item["item_id"],
            "gold_item_sha256": item["gold_item_sha256"],
            "item_text_object": dict(item["item_text_object"]),
            "answer_object": dict(item["answer_object"]),
        }
        for item in census["items"]
    ]
    contract: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA,
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": TASK_ID,
            "consumes": ["item_text_payload_bytes", "answer_payload_bytes"],
            "forbidden_inputs": list(FORBIDDEN_INPUTS),
            "prediction": "sha256(item_text_payload_bytes + answer_payload_bytes)",
            "scorer": "exact_match(prediction, gold_item_sha256)",
        },
        "source": {
            "benchmark_id": "MMMU",
            "split": "validation",
            "source_url": SOURCE_URL,
            "custody_manifest_sha256": CUSTODY_MANIFEST_SHA256,
            "connector_receipt_raw_sha256s": sorted([sha(answer_connector_raw), sha(predecessor_connector_raw)]),
            "connector_receipts": {
                "answers": sha(answer_connector_raw),
                "predecessor_items": sha(predecessor_connector_raw),
            },
            "predecessor_contract_self_sha256": predecessor_contract["self_sha256"],
            "census_self_sha256": census["self_sha256"],
            "license_sha256": LICENSE_SHA256,
            "metadata_columns_access": "never_read",
            "image_payload_access": "forbidden",
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


def _catalog_rows(catalog: Path, split: str) -> list[tuple[str, str | None]]:
    connection = sqlite3.connect(
        catalog.resolve(strict=True).as_uri() + "?mode=ro&immutable=1", uri=True
    )
    try:
        return connection.execute(
            """
            SELECT json_extract(m.payload_json, '$.exact_sha256'),
                   lower(json_extract(o.payload_json, '$.media_type'))
            FROM data_catalog_records AS m
            JOIN data_catalog_records AS o
              ON o.kind = 'immutable_object'
             AND o.record_id = 'sha256:' || json_extract(m.payload_json, '$.exact_sha256')
            WHERE m.kind = 'membership'
              AND json_extract(m.payload_json, '$.admission_state') = 'admitted'
              AND json_extract(m.payload_json, '$.split') = ?
            """,
            (split,),
        ).fetchall()
    finally:
        connection.close()


def read_admitted_train_object_hashes(catalog: Path) -> set[str]:
    return {digest for digest, _media in _catalog_rows(catalog, "train")}


def read_admitted_heldout_text_hashes(catalog: Path) -> set[str]:
    hashes = {
        digest for digest, media in _catalog_rows(catalog, "heldout")
        if isinstance(media, str) and media.startswith(("text/", "application/json"))
    }
    if len(hashes) < EXPECTED_ITEM_COUNT:
        raise ValueError(f"HELDOUT_TEXT_CATALOG_COUNT_DRIFT_REFUSED:{len(hashes)}")
    return hashes


def payloads_from_items(items: list[dict[str, Any]]) -> dict[str, bytes]:
    return {item["answer_sha256"]: item["answer_payload"] for item in items}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mmmu-root", type=Path, required=True)
    parser.add_argument("--license", type=Path, required=True)
    parser.add_argument("--custody-manifest", type=Path, required=True)
    parser.add_argument("--predecessor-contract", type=Path, required=True, help="the #2130 protected image-text contract")
    parser.add_argument("--predecessor-connector-receipt", type=Path, required=True, help="the #2130 items connector receipt")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True, help="census output (admit) or existing census (contract)")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--answer-connector-receipt", type=Path)
    parser.add_argument("--admission-receipt", type=Path)
    parser.add_argument("--fetched-at")
    parser.add_argument("--projection-spec", type=Path)
    parser.add_argument("--tokenizer-sha256")
    parser.add_argument("--created-at-ms", type=int)
    parser.add_argument("--answer-connector-for-contract", type=Path)
    parser.add_argument("--catalog-export", type=Path)
    parser.add_argument("--dataset-id", action="append")
    parser.add_argument("--contract", type=Path)
    args = parser.parse_args()
    try:
        license_raw = args.license.read_bytes()
        manifest_raw = args.custody_manifest.read_bytes()
        predecessor_contract_raw = args.predecessor_contract.read_bytes()
        predecessor_raw = args.predecessor_connector_receipt.read_bytes()
        items, parquet_count = read_answers(args.mmmu_root, predecessor_contract_raw)
        text_payloads = read_predecessor_text_payloads(predecessor_raw, items)
        census = build_census(
            items=items,
            parquet_file_count=parquet_count,
            license_raw=license_raw,
            custody_manifest_raw=manifest_raw,
            predecessor_contract_raw=predecessor_contract_raw,
            predecessor_connector_raw=predecessor_raw,
            text_payloads=text_payloads,
            admitted_train_object_hashes=read_admitted_train_object_hashes(args.catalog),
            admitted_heldout_text_hashes=read_admitted_heldout_text_hashes(args.catalog),
        )
        census_raw = json.dumps(census, sort_keys=True, indent=2).encode() + b"\n"
        if args.census.exists():
            if args.census.read_bytes() != census_raw:
                raise ValueError("CENSUS_DRIFT_FROM_RECORDED_REFUSED")
        else:
            write_new(args.census, census_raw)
        payloads = payloads_from_items(items)
        plan = build_admission_plan(census, payloads_by_sha=payloads)
        if args.plan is not None:
            plan_for_receipt = dict(plan)
            plan_for_receipt["self_sha256"] = sha(canonical(plan_for_receipt))
            write_new(args.plan, json.dumps(plan_for_receipt, sort_keys=True, indent=2).encode() + b"\n")
        artifact_values = [args.output_root, args.answer_connector_receipt, args.admission_receipt, args.fetched_at]
        answer_raw = None
        if any(value is not None for value in artifact_values):
            if any(value is None for value in artifact_values):
                raise ValueError("ADMISSION_ARTIFACT_ARGUMENT_TOTALITY_REFUSED")
            answer_raw, admission_raw = write_admission_artifacts(
                plan=plan,
                payloads_by_sha=payloads,
                license_raw=license_raw,
                output_root=args.output_root,
                answer_connector_path=args.answer_connector_receipt,
                admission_receipt_path=args.admission_receipt,
                fetched_at=args.fetched_at,
            )
            projection_values = [args.projection_spec, args.tokenizer_sha256, args.created_at_ms]
            if any(value is not None for value in projection_values):
                if any(value is None for value in projection_values):
                    raise ValueError("PROJECTION_SPEC_ARGUMENT_TOTALITY_REFUSED")
                write_new(args.projection_spec, build_projection_spec(
                    answer_connector_path=args.answer_connector_receipt,
                    answer_connector_raw=answer_raw,
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
            if answer_raw is None:
                if args.answer_connector_for_contract is None:
                    raise ValueError("REASONING_CONTRACT_ARGUMENT_TOTALITY_REFUSED")
                answer_raw = args.answer_connector_for_contract.read_bytes()
            if (args.catalog_export is None) != (args.dataset_id is None):
                raise ValueError("REASONING_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED")
            contract = build_reasoning_contract(
                census,
                answer_connector_raw=answer_raw,
                predecessor_connector_raw=predecessor_raw,
                predecessor_contract_raw=predecessor_contract_raw,
                catalog_export_raw=None if args.catalog_export is None else args.catalog_export.read_bytes(),
                dataset_ids=args.dataset_id,
            )
            write_new(args.contract, json.dumps(contract, sort_keys=True, indent=2).encode() + b"\n")
    except (OSError, TypeError, ValueError, KeyError) as error:
        print(f"error: {error!r}" if isinstance(error, KeyError) else f"error: {error}")
        return 2
    print(json.dumps({
        "result": "PASS",
        "item_count": census["item_count"],
        "parquet_file_count": census["parquet_file_count"],
        "answer_object_count": census["answer_object_count"],
        "admitted_object_set_sha256": census["admitted_object_set_sha256"],
        "referenced_object_set_sha256": census["referenced_object_set_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
