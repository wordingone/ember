# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2153: Spider execution assets as protected heldout objects + the frozen tool-use contract.

Mirror of the #2148 admission-module shape with one more object class. Every item of the frozen
Spider validation set (1,034 pairs, #1947 freeze) binds FOUR content-addressed objects:

  prompt   canonical JSON {item_id, db_id, question, schema}   (what a producer formats)
  gold     canonical JSON {id, query}                           (the gold SQL, item-bound)
  schema   canonical JSON {db_id, tables, foreign_keys}         (serialized from tables.json)
  database the SQLite bytes of the item's db_id                 (20 development databases)

The census is a pure function of the archive bytes, the frozen set, and the live catalog; it
writes no custody. The gold-execution leg opens each admitted database read-only, runs every
gold query twice, canonicalizes the rows, and receipts a per-item result hash that the contract
binds as `gold_result_sha256`. Claim boundary: asset admission and a frozen prompt/gold/database
contract; no inference, no scoring, no capability, threshold, release, or campaign credit.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

CENSUS_SCHEMA = "ember-issue2153-heldout-tool-use-asset-census-v1"
PLAN_SCHEMA = "ember-issue2153-heldout-tool-use-asset-admission-plan-v1"
ADMISSION_RECEIPT_SCHEMA = "ember-issue2153-heldout-tool-use-asset-admission-receipt-v1"
EXECUTION_RECEIPT_SCHEMA = "ember-issue2153-gold-execution-receipt-v1"
REFUSAL_RECEIPT_SCHEMA = "ember-issue2153-planted-negative-refusal-receipt-v1"
CONTRACT_SCHEMA = "ember-issue1947-protected-tool-use-contract-v1"
FREEZE_SCHEMA = "ember-restart-spider-validation-freeze-v1"
CUSTODY_MANIFEST_SCHEMA = "ember-restart-benchmark-custody-v1"
TASK_ID = "EXACT_TOOL_USE_ITEM_IDENTITY"

# Official Spider 1.0 archive, byte-identical on two independent public mirrors (census 2026-09-05).
ARCHIVE_SHA256 = "5ddff97bb1d421282c593e8d30ce0ce107270f4dd4a21d60eba4bf287d5956b1"
ARCHIVE_BYTE_COUNT = 99_736_136
ARCHIVE_SQLITE_COUNT = 166
SOURCE_URL = "https://yale-lily.github.io/spider"
# The frozen validation set (#1947 freeze v1): the HF dataset card is its license text
# (CC-BY-SA-4.0) and the parquet is its references object.
LICENSE_SHA256 = "e932ef2c29ee5eb626694f59a7c910f7cdbe85cdb5abd226e759610cf3622103"
REFERENCES_SHA256 = "c3e2a46303899a2d4afe3f6a3a62e59f8d589f241b3cbfb52356479b1f054888"
PROTOCOL_SHA256 = "660fbf26471acb005f22ca314d9c7d5f3a7bc192ffcf383b0005fab9680734c8"
EXPECTED_ITEM_COUNT = 1034
EXPECTED_DEV_DATABASE_COUNT = 20

PROMPT_SOURCE_ID = "spider-dev-heldout-tool-use-prompts"
GOLD_SOURCE_ID = "spider-dev-heldout-tool-use-gold-queries"
SCHEMA_SOURCE_ID = "spider-dev-heldout-tool-use-schemas"
DATABASE_SOURCE_ID = "spider-dev-heldout-tool-use-databases"
CATALOG_SOURCE_IDS = {
    PROMPT_SOURCE_ID: "candidate-tool-use-prompts-heldout-0",
    GOLD_SOURCE_ID: "candidate-tool-use-gold-queries-heldout-0",
    SCHEMA_SOURCE_ID: "candidate-tool-use-schemas-heldout-0",
    DATABASE_SOURCE_ID: "candidate-tool-use-databases-heldout-0",
}
OBJECT_CLASSES = ("prompt", "gold", "schema", "database")
CLASS_SOURCE_ID = {
    "prompt": PROMPT_SOURCE_ID, "gold": GOLD_SOURCE_ID, "schema": SCHEMA_SOURCE_ID, "database": DATABASE_SOURCE_ID,
}
CLASS_SUBDIRS = {"prompt": "prompts", "gold": "golds", "schema": "schemas", "database": "databases"}
CLASS_SUFFIX = {"prompt": ".json", "gold": ".json", "schema": ".json", "database": ".sqlite"}
CLASS_DOMAIN = {"prompt": "text", "gold": "text", "schema": "text", "database": "tool"}
JSON_MEDIA_TYPE = "application/json"
DATABASE_MEDIA_TYPE = "application/vnd.sqlite3"
CLASS_MEDIA_TYPE = {
    "prompt": JSON_MEDIA_TYPE, "gold": JSON_MEDIA_TYPE, "schema": JSON_MEDIA_TYPE, "database": DATABASE_MEDIA_TYPE,
}
GOLD_KEYS = ("id", "query")
SCHEMA_RULE = (
    "tables in tables.json order; each column's original name, declared type, primary_key flag; "
    "foreign keys as [table, column] -> [table, column]; canonical JSON (sorted keys, compact separators, UTF-8 unescaped)"
)
PROMPT_RULE = "canonical JSON {item_id, db_id, question, schema} where schema is the serialized schema object of db_id"
RESULT_CANONICALIZATION = (
    "rows fetched fully; each cell -> null | int | float | str | hex(bytes); text decoded utf-8 with U+FFFD replacement; "
    "row order preserved when the gold query contains ORDER BY, else rows sorted by their canonical JSON; "
    "result sha256 = sha256(canonical JSON of the row list)"
)
SELECTION_RULE = (
    "the item set IS the frozen Spider validation set (task_count 1034, references sha pinned); "
    "the archive's dev.json (question, query, db_id) triples must equal it in order; no N, no sampling"
)
FORBIDDEN_INPUTS = [
    "model_inference", "predicted_sql", "execution_match_scoring", "train_split_json", "archive_test_split",
    "database_write_access",
]
CLAIM_BOUNDARY = (
    "asset admission and a frozen prompt/gold/database contract with a receipted gold-execution result per item; "
    "no inference, SQL emission, scoring, capability, threshold, release, campaign, EMBER-02, or goal credit; "
    "the E-MATRIX-TOOL-USE row stays refuse with its three inference predicates"
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def item_identifier(index: int) -> str:
    return f"spider-dev-{index:04d}"


def serialize_schema(table_entry: dict[str, Any]) -> dict[str, Any]:
    """Deterministic schema object from one tables.json entry (SCHEMA_RULE)."""

    names = table_entry["table_names_original"]
    columns = table_entry["column_names_original"]
    types = table_entry["column_types"]
    primary = set(table_entry["primary_keys"])
    if len(columns) != len(types):
        raise ValueError(f"SCHEMA_COLUMN_TYPE_TOTALITY_REFUSED:{table_entry.get('db_id')}")
    tables = []
    for table_index, table_name in enumerate(names):
        tables.append({
            "table": table_name,
            "columns": [
                {"name": column[1], "type": types[column_index], "primary_key": column_index in primary}
                for column_index, column in enumerate(columns)
                if column[0] == table_index
            ],
        })
    foreign_keys = [
        {"from": [names[columns[a][0]], columns[a][1]], "to": [names[columns[b][0]], columns[b][1]]}
        for a, b in table_entry["foreign_keys"]
    ]
    return {"db_id": table_entry["db_id"], "tables": tables, "foreign_keys": foreign_keys}


def prompt_object(item_id: str, db_id: str, question: str, schema: dict[str, Any]) -> bytes:
    return canonical({"item_id": item_id, "db_id": db_id, "question": question, "schema": schema})


def gold_object(item_id: str, query: str) -> bytes:
    return canonical({"id": item_id, "query": query})


def item_gold_sha256(prompt_raw: bytes, gold_raw: bytes, gold_result_sha256: str) -> str:
    return sha(prompt_raw + gold_raw + gold_result_sha256.encode("ascii"))


def verified_freeze(freeze_raw: bytes) -> dict[str, Any]:
    try:
        freeze = json.loads(freeze_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("FREEZE_UNREADABLE_REFUSED") from error
    if (
        not isinstance(freeze, dict)
        or freeze.get("schema_version") != FREEZE_SCHEMA
        or freeze.get("task_count") != EXPECTED_ITEM_COUNT
        or freeze.get("references_sha256") != REFERENCES_SHA256
        or freeze.get("protocol_sha256") != PROTOCOL_SHA256
        or freeze.get("license_sha256") != LICENSE_SHA256
    ):
        raise ValueError("FREEZE_IDENTITY_REFUSED")
    return freeze


def verified_custody_manifest(manifest_raw: bytes) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("CUSTODY_MANIFEST_UNREADABLE_REFUSED") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != CUSTODY_MANIFEST_SCHEMA
        or manifest.get("benchmark_id") != "spider"
        or manifest.get("target_training_access") != "FORBIDDEN"
    ):
        raise ValueError("CUSTODY_MANIFEST_IDENTITY_REFUSED")
    return manifest


def read_frozen_items(parquet_path: Path, freeze_raw: bytes) -> list[dict[str, str]]:
    """The frozen set's (question, query, db_id) rows in parquet order; the parquet is the
    freeze's references object, so its bytes are pinned before any column is read."""

    verified_freeze(freeze_raw)
    raw = parquet_path.read_bytes()
    if sha(raw) != REFERENCES_SHA256:
        raise ValueError("FROZEN_REFERENCES_SHA_DRIFT_REFUSED")
    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise ValueError("PYARROW_UNAVAILABLE_REFUSED") from error
    table = pq.read_table(io.BytesIO(raw), columns=["question", "query", "db_id"]).to_pylist()
    return frozen_rows_from_records(table)


def frozen_rows_from_records(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in records:
        if not all(isinstance(row.get(key), str) and row.get(key) for key in ("question", "query", "db_id")):
            raise ValueError("FROZEN_ROW_SHAPE_REFUSED")
        rows.append({"question": row["question"], "query": row["query"], "db_id": row["db_id"]})
    if len(rows) != EXPECTED_ITEM_COUNT:
        raise ValueError(f"FROZEN_ROW_COUNT_REFUSED:{len(rows)}")
    return rows


def read_archive(archive_raw: bytes, *, dev_db_ids: set[str]) -> dict[str, Any]:
    """Parse the pinned archive: dev rows, schema entries, and the development databases' bytes.
    Train splits and the 146 non-development databases are enumerated (counted) but never read."""

    if sha(archive_raw) != ARCHIVE_SHA256 or len(archive_raw) != ARCHIVE_BYTE_COUNT:
        raise ValueError(f"ARCHIVE_SHA_DRIFT_REFUSED:{sha(archive_raw)}")
    return parse_archive(archive_raw, dev_db_ids=dev_db_ids)


def parse_archive(archive_raw: bytes, *, dev_db_ids: set[str]) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(archive_raw)) as archive:
        names = set(archive.namelist())
        for member in ("spider/dev.json", "spider/tables.json", "spider/dev_gold.sql"):
            if member not in names:
                raise ValueError(f"ARCHIVE_MEMBER_MISSING_REFUSED:{member}")
        dev_raw = archive.read("spider/dev.json")
        tables_raw = archive.read("spider/tables.json")
        gold_raw = archive.read("spider/dev_gold.sql")
        databases: dict[str, bytes] = {}
        for db_id in sorted(dev_db_ids):
            member = f"spider/database/{db_id}/{db_id}.sqlite"
            if member not in names:
                raise ValueError(f"ARCHIVE_DATABASE_MISSING_REFUSED:{db_id}")
            databases[db_id] = archive.read(member)
        sqlite_count = sum(1 for name in names if name.endswith(".sqlite"))
    try:
        dev = json.loads(dev_raw)
        tables = json.loads(tables_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("ARCHIVE_JSON_UNREADABLE_REFUSED") from error
    if not isinstance(dev, list) or not isinstance(tables, list):
        raise ValueError("ARCHIVE_JSON_SHAPE_REFUSED")
    return {
        "dev": dev, "tables": tables, "databases": databases,
        "dev_json_sha256": sha(dev_raw), "tables_json_sha256": sha(tables_raw), "dev_gold_sql_sha256": sha(gold_raw),
        "dev_gold_lines": gold_raw.decode("utf-8", "replace").splitlines(), "sqlite_count": sqlite_count,
    }


def build_items(frozen: list[dict[str, str]], archive: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-item objects. Refuses before any object is built when the archive's dev rows differ
    from the frozen set in order, or when a dev database's schema entry is missing."""

    dev_triples = [
        (row.get("question"), row.get("query"), row.get("db_id")) if isinstance(row, dict) else None
        for row in archive["dev"]
    ]
    frozen_triples = [(row["question"], row["query"], row["db_id"]) for row in frozen]
    if dev_triples != frozen_triples:
        raise ValueError(f"ARCHIVE_FROZEN_SET_DRIFT_REFUSED:{len(dev_triples)}:{len(frozen_triples)}")
    gold_lines = archive["dev_gold_lines"]
    expected_lines = [f"{row['query']}\t{row['db_id']}" for row in frozen]
    if gold_lines != expected_lines:
        raise ValueError("ARCHIVE_DEV_GOLD_SQL_DRIFT_REFUSED")
    schemas: dict[str, dict[str, Any]] = {}
    for entry in archive["tables"]:
        if isinstance(entry, dict) and isinstance(entry.get("db_id"), str):
            if entry["db_id"] in schemas:
                raise ValueError(f"ARCHIVE_SCHEMA_DUPLICATE_REFUSED:{entry['db_id']}")
            schemas[entry["db_id"]] = entry
    items: list[dict[str, Any]] = []
    for index, row in enumerate(frozen):
        db_id = row["db_id"]
        if db_id not in schemas:
            raise ValueError(f"ARCHIVE_SCHEMA_MISSING_REFUSED:{db_id}")
        if db_id not in archive["databases"]:
            raise ValueError(f"ARCHIVE_DATABASE_MISSING_REFUSED:{db_id}")
        schema = serialize_schema(schemas[db_id])
        item_id = item_identifier(index)
        items.append({
            "item_id": item_id, "db_id": db_id,
            "prompt_payload": prompt_object(item_id, db_id, row["question"], schema),
            "gold_payload": gold_object(item_id, row["query"]),
            "schema_payload": canonical(schema),
            "database_payload": archive["databases"][db_id],
        })
    return items


def _object(payload: bytes, media_type: str) -> dict[str, Any]:
    return {"sha256": sha(payload), "byte_count": len(payload), "media_type": media_type}


def build_census(
    *,
    items: list[dict[str, Any]],
    archive: dict[str, Any],
    freeze_raw: bytes,
    license_raw: bytes,
    custody_manifest_raw: bytes,
    admitted_train_object_hashes: set[str],
) -> dict[str, Any]:
    """Read-only census: identities, per-item objects, train exclusion. No custody is written."""

    if sha(license_raw) != LICENSE_SHA256:
        raise ValueError("LICENSE_SHA256_DRIFT_REFUSED")
    freeze = verified_freeze(freeze_raw)
    verified_custody_manifest(custody_manifest_raw)
    if len(items) != EXPECTED_ITEM_COUNT:
        raise ValueError(f"ITEM_COUNT_REFUSED:{len(items)}")
    ids = [item["item_id"] for item in items]
    if ids != [item_identifier(index) for index in range(len(items))]:
        raise ValueError("ITEM_ID_SEQUENCE_REFUSED")
    if archive["sqlite_count"] != ARCHIVE_SQLITE_COUNT:
        raise ValueError(f"ARCHIVE_SQLITE_COUNT_REFUSED:{archive['sqlite_count']}")
    owners: dict[str, tuple[str, str]] = {}
    census_items: list[dict[str, Any]] = []
    class_hashes: dict[str, set[str]] = {name: set() for name in OBJECT_CLASSES}
    for item in items:
        # The gold object must be the canonical {id, query} of THIS item: two golds swapped is
        # gold drift and refuses the census before any custody exists.
        try:
            decoded = json.loads(item["gold_payload"])
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"GOLD_ITEM_ID_DRIFT_REFUSED:{item['item_id']}") from error
        if (
            not isinstance(decoded, dict) or set(decoded) != set(GOLD_KEYS)
            or decoded.get("id") != item["item_id"] or not isinstance(decoded.get("query"), str)
            or gold_object(item["item_id"], decoded["query"]) != item["gold_payload"]
        ):
            raise ValueError(f"GOLD_ITEM_ID_DRIFT_REFUSED:{item['item_id']}")
        try:
            prompt = json.loads(item["prompt_payload"])
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"PROMPT_ITEM_ID_DRIFT_REFUSED:{item['item_id']}") from error
        if (
            not isinstance(prompt, dict) or prompt.get("item_id") != item["item_id"] or prompt.get("db_id") != item["db_id"]
            or canonical(prompt.get("schema")) != item["schema_payload"]
        ):
            raise ValueError(f"PROMPT_ITEM_ID_DRIFT_REFUSED:{item['item_id']}")
        record: dict[str, Any] = {"item_id": item["item_id"], "db_id": item["db_id"]}
        for name in OBJECT_CLASSES:
            payload = item[f"{name}_payload"]
            digest = sha(payload)
            owner = owners.get(digest)
            if name in ("prompt", "gold"):
                if owner is not None:
                    raise ValueError(f"OBJECT_IDENTITY_CONFLICT_REFUSED:{digest}")
                owners[digest] = (name, item["item_id"])
            else:
                if owner is not None and owner != (name, item["db_id"]):
                    raise ValueError(f"OBJECT_IDENTITY_CONFLICT_REFUSED:{digest}")
                owners[digest] = (name, item["db_id"])
            class_hashes[name].add(digest)
            record[f"{name}_object"] = _object(payload, CLASS_MEDIA_TYPE[name])
        census_items.append(record)
    if len(class_hashes["database"]) != EXPECTED_DEV_DATABASE_COUNT or len(class_hashes["schema"]) != EXPECTED_DEV_DATABASE_COUNT:
        raise ValueError(
            f"DEV_DATABASE_COUNT_REFUSED:{len(class_hashes['database'])}:{len(class_hashes['schema'])}"
        )
    referenced = sorted(owners)
    for digest in referenced:
        if digest in admitted_train_object_hashes:
            raise ValueError(f"TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:{digest}")
    census: dict[str, Any] = {
        "schema_version": CENSUS_SCHEMA,
        "result": "PASS",
        "source": {
            "benchmark_id": "spider",
            "split": "dev",
            "source_url": SOURCE_URL,
            "archive_sha256": ARCHIVE_SHA256,
            "archive_byte_count": ARCHIVE_BYTE_COUNT,
            "dev_json_sha256": archive["dev_json_sha256"],
            "tables_json_sha256": archive["tables_json_sha256"],
            "dev_gold_sql_sha256": archive["dev_gold_sql_sha256"],
            "freeze_protocol_sha256": freeze["protocol_sha256"],
            "freeze_references_sha256": freeze["references_sha256"],
            "license_sha256": LICENSE_SHA256,
            "license": freeze.get("license"),
            "train_split_access": "never_read (train_spider.json, train_others.json, train_gold.sql)",
            "non_development_database_access": "counted, never read",
        },
        "item_count": len(ids),
        "selection_rule": SELECTION_RULE,
        "schema_rule": SCHEMA_RULE,
        "prompt_rule": PROMPT_RULE,
        "object_counts": {name: len(class_hashes[name]) for name in OBJECT_CLASSES},
        "train_intersection": {
            "executed": True,
            "admitted_train_object_count": len(admitted_train_object_hashes),
            "count": 0,
        },
        "referenced_object_count": len(referenced),
        "referenced_object_set_sha256": sha(canonical(referenced)),
        "admitted_object_count": len(referenced),
        "admitted_object_set_sha256": sha(canonical(referenced)),
        "selected_set_sha256": sha(canonical(sorted(class_hashes["gold"]))),
        "items": census_items,
    }
    census["self_sha256"] = sha(canonical(census))
    return census


def verify_census(census: dict[str, Any]) -> None:
    body = {key: value for key, value in census.items() if key != "self_sha256"}
    if (
        not isinstance(census, dict)
        or census.get("schema_version") != CENSUS_SCHEMA
        or census.get("result") != "PASS"
        or sha(canonical(body)) != census.get("self_sha256")
        or census.get("item_count") != EXPECTED_ITEM_COUNT
        or len(census.get("items", [])) != EXPECTED_ITEM_COUNT
        or census.get("train_intersection", {}).get("count") != 0
    ):
        raise ValueError("CENSUS_IDENTITY_REFUSED")
    referenced = set()
    for item in census["items"]:
        for name in OBJECT_CLASSES:
            referenced.add(item[f"{name}_object"]["sha256"])
    if sha(canonical(sorted(referenced))) != census["admitted_object_set_sha256"]:
        raise ValueError("CENSUS_OBJECT_SET_REFUSED")


def payloads_from_items(items: list[dict[str, Any]]) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for item in items:
        for name in OBJECT_CLASSES:
            payload = item[f"{name}_payload"]
            payloads[sha(payload)] = payload
    return payloads


def build_admission_plan(census: dict[str, Any], *, payloads_by_sha: dict[str, bytes]) -> dict[str, Any]:
    """Validate every payload against the census before any custody path exists."""

    verify_census(census)
    files: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in OBJECT_CLASSES}
    for item in census["items"]:
        for name in OBJECT_CLASSES:
            entry = item[f"{name}_object"]
            digest = entry["sha256"]
            payload = payloads_by_sha.get(digest)
            if not isinstance(payload, bytes) or sha(payload) != digest or len(payload) != entry["byte_count"]:
                raise ValueError(f"PAYLOAD_DRIFT_REFUSED:{name}:{item['item_id']}")
            source = {"item_id": item["item_id"]} if name in ("prompt", "gold") else {"db_id": item["db_id"]}
            files[name][digest] = {
                "path": f"{CLASS_SUBDIRS[name]}/{digest[:2]}/{digest}{CLASS_SUFFIX[name]}",
                "bytes": entry["byte_count"], "sha256": digest, "source": source,
            }
    rows = {name: sorted(files[name].values(), key=lambda row: row["sha256"]) for name in OBJECT_CLASSES}
    if len(rows["prompt"]) != EXPECTED_ITEM_COUNT or len(rows["gold"]) != EXPECTED_ITEM_COUNT:
        raise ValueError("ITEM_OBJECT_TOTALITY_REFUSED")
    if len(rows["schema"]) != EXPECTED_DEV_DATABASE_COUNT or len(rows["database"]) != EXPECTED_DEV_DATABASE_COUNT:
        raise ValueError("DATABASE_OBJECT_TOTALITY_REFUSED")
    admitted = sorted(digest for name in OBJECT_CLASSES for digest in files[name])
    if sha(canonical(admitted)) != census["admitted_object_set_sha256"]:
        raise ValueError("ADMITTED_OBJECT_SET_DRIFT_REFUSED")
    return {
        "schema_version": PLAN_SCHEMA,
        "result": "PASS",
        "selection_rule": SELECTION_RULE,
        "census_self_sha256": census["self_sha256"],
        "license_sha256": LICENSE_SHA256,
        "archive_sha256": ARCHIVE_SHA256,
        "split": "heldout",
        "item_count": EXPECTED_ITEM_COUNT,
        "admitted_object_count": len(admitted),
        "selected_set_sha256": census["selected_set_sha256"],
        "referenced_object_set_sha256": census["referenced_object_set_sha256"],
        "train_exclusion_assertion": "executed_pass",
        "rows": [
            {"domain": CLASS_DOMAIN[name], "source_id": CLASS_SOURCE_ID[name],
             "catalog_source_id": CATALOG_SOURCE_IDS[CLASS_SOURCE_ID[name]], "file_count": len(rows[name])}
            for name in OBJECT_CLASSES
        ],
        "files": rows,
    }


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def _connector(
    *, source_id: str, files: list[dict[str, Any]], dest_root: Path, license_raw: bytes, fetched_at: str,
) -> bytes:
    rows = sorted(
        ({"path": row["path"], "bytes": row["bytes"], "sha256": row["sha256"]} for row in files),
        key=lambda row: (row["path"], row["sha256"]),
    )
    connector = {
        "schema": "corpus-connector-receipt-v1",
        "source_id": source_id,
        "canonical_url": SOURCE_URL,
        "fetched_at": fetched_at,
        "license": license_raw.decode("utf-8"),
        "dest_root": str(dest_root.resolve()),
        "total_bytes": sum(row["bytes"] for row in rows),
        "sha256_manifest": sha("\n".join(sorted(row["sha256"] for row in rows)).encode()),
        "files": rows,
    }
    return json.dumps(connector, sort_keys=True, indent=2).encode() + b"\n"


def connector_paths(admission_dir: Path) -> dict[str, Path]:
    return {name: admission_dir / f"connector-receipt-{CLASS_SUBDIRS[name]}-v1.json" for name in OBJECT_CLASSES}


def write_admission_artifacts(
    *,
    plan: dict[str, Any],
    payloads_by_sha: dict[str, bytes],
    license_raw: bytes,
    output_root: Path,
    admission_dir: Path,
    admission_receipt_path: Path,
    fetched_at: str,
) -> tuple[dict[str, bytes], bytes]:
    """Create custody only after the complete read-only plan has passed. One connector per object class."""

    connectors = connector_paths(admission_dir)
    if output_root.exists() or admission_receipt_path.exists() or any(path.exists() for path in connectors.values()):
        raise ValueError("NO_OVERWRITE_REFUSED")
    if not fetched_at or "T" not in fetched_at or not fetched_at.endswith("Z"):
        raise ValueError("FETCHED_AT_REFUSED")
    output_root.mkdir(parents=True, exist_ok=False)
    connector_raws: dict[str, bytes] = {}
    for name in OBJECT_CLASSES:
        class_root = output_root / CLASS_SUBDIRS[name]
        for row in plan["files"][name]:
            write_new(class_root / Path(row["path"]), payloads_by_sha[row["sha256"]])
        connector_raws[name] = _connector(
            source_id=CLASS_SOURCE_ID[name], files=plan["files"][name], dest_root=class_root,
            license_raw=license_raw, fetched_at=fetched_at,
        )
    admission = dict(plan)
    admission["schema_version"] = ADMISSION_RECEIPT_SCHEMA
    admission["connector_receipt_raw_sha256s"] = {name: sha(connector_raws[name]) for name in OBJECT_CLASSES}
    admission["total_bytes"] = sum(json.loads(connector_raws[name])["total_bytes"] for name in OBJECT_CLASSES)
    admission["self_sha256"] = sha(canonical(admission))
    admission_raw = json.dumps(admission, sort_keys=True, indent=2).encode() + b"\n"
    for name in OBJECT_CLASSES:
        write_new(connectors[name], connector_raws[name])
    write_new(admission_receipt_path, admission_raw)
    return connector_raws, admission_raw


def build_projection_spec(
    *, admission_dir: Path, connector_raws: dict[str, bytes], admission_receipt_path: Path, admission_receipt_raw: bytes,
    census_path: Path, census_raw: bytes, freeze_path: Path, freeze_raw: bytes, license_path: Path,
    tokenizer_sha256: str, created_at_ms: int,
) -> bytes:
    if not _is_sha(tokenizer_sha256):
        raise ValueError("TOKENIZER_SHA256_REFUSED")
    if isinstance(created_at_ms, bool) or not isinstance(created_at_ms, int) or created_at_ms < 0:
        raise ValueError("CREATED_AT_MS_REFUSED")
    supporting = [
        {"path": str(admission_receipt_path.resolve()), "sha256": sha(admission_receipt_raw)},
        {"path": str(census_path.resolve()), "sha256": sha(census_raw)},
        {"path": str(freeze_path.resolve()), "sha256": sha(freeze_raw)},
        {"path": str(license_path.resolve()), "sha256": LICENSE_SHA256},
    ]
    connectors = connector_paths(admission_dir)
    spec = {
        "schema_version": "ember-issue1581-catalog-projection-spec-v1",
        "tokenizer_sha256": tokenizer_sha256,
        "created_at_ms": created_at_ms,
        "rows": [{
            "receipt_path": str(connectors[name].resolve()),
            "expected_receipt_sha256": sha(connector_raws[name]),
            "source_id": CATALOG_SOURCE_IDS[CLASS_SOURCE_ID[name]],
            "expected_source_selector": CLASS_SOURCE_ID[name],
            "expected_license_text_sha256": LICENSE_SHA256,
            "domain": CLASS_DOMAIN[name],
            "split": "heldout",
            "supporting_receipts": supporting,
        } for name in OBJECT_CLASSES],
    }
    return json.dumps(spec, sort_keys=True, indent=2).encode() + b"\n"


def canonical_result(rows: list[tuple[Any, ...]], *, ordered: bool) -> str:
    def cell(value: Any) -> Any:
        if value is None or isinstance(value, (int, float, str)) and not isinstance(value, bool):
            return value
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value).hex()
        return str(value)
    canon_rows = [[cell(value) for value in row] for row in rows]
    if not ordered:
        canon_rows.sort(key=lambda row: canonical(row))
    return sha(canonical(canon_rows))


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro&immutable=1", uri=True)
    connection.text_factory = lambda raw: raw.decode("utf-8", "replace")
    return connection


def execute_gold(
    census: dict[str, Any], *, payloads_by_sha: dict[str, bytes], passes: int = 2,
) -> dict[str, Any]:
    """Run every gold query read-only against its bound database bytes; two independent passes
    must agree per item. Database bytes are hashed before and after execution."""

    verify_census(census)
    if type(passes) is not int or passes < 2:
        raise ValueError("EXECUTION_PASSES_REFUSED")
    databases = {item["database_object"]["sha256"] for item in census["items"]}
    golds: dict[str, tuple[str, str]] = {}
    for item in census["items"]:
        gold_raw = payloads_by_sha.get(item["gold_object"]["sha256"])
        if not isinstance(gold_raw, bytes) or sha(gold_raw) != item["gold_object"]["sha256"]:
            raise ValueError(f"PAYLOAD_DRIFT_REFUSED:gold:{item['item_id']}")
        golds[item["item_id"]] = (json.loads(gold_raw)["query"], item["database_object"]["sha256"])
    results: list[dict[str, str | None]] = []
    failures: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="issue2153-gold-") as temporary:
        root = Path(temporary)
        paths: dict[str, Path] = {}
        for digest in sorted(databases):
            raw = payloads_by_sha.get(digest)
            if not isinstance(raw, bytes) or sha(raw) != digest:
                raise ValueError(f"PAYLOAD_DRIFT_REFUSED:database:{digest}")
            paths[digest] = root / f"{digest}.sqlite"
            paths[digest].write_bytes(raw)
        for pass_index in range(passes):
            connections = {digest: _open_read_only(path) for digest, path in paths.items()}
            try:
                pass_results: dict[str, str | None] = {}
                for item in census["items"]:
                    query, digest = golds[item["item_id"]]
                    try:
                        rows = connections[digest].execute(query).fetchall()
                    except sqlite3.Error as error:
                        if pass_index == 0:
                            failures.append({"item_id": item["item_id"], "error": f"{type(error).__name__}: {error}"[:200]})
                        pass_results[item["item_id"]] = None
                        continue
                    pass_results[item["item_id"]] = canonical_result(rows, ordered="order by" in query.lower())
            finally:
                for connection in connections.values():
                    connection.close()
            results.append(pass_results)
        after = {digest: sha(path.read_bytes()) for digest, path in paths.items()}
    if failures:
        raise ValueError(f"TOOL_USE_GOLD_EXECUTION_REFUSED:{len(failures)}:{failures[:3]}")
    if any(after[digest] != digest for digest in after):
        raise ValueError("TOOL_USE_DATABASE_BYTES_CHANGED_REFUSED")
    unstable = [item["item_id"] for item in census["items"] if len({run[item["item_id"]] for run in results}) != 1]
    if unstable:
        raise ValueError(f"TOOL_USE_GOLD_RESULT_UNSTABLE_REFUSED:{len(unstable)}:{unstable[:3]}")
    per_item = [{"item_id": item["item_id"], "gold_result_sha256": results[0][item["item_id"]]} for item in census["items"]]
    receipt: dict[str, Any] = {
        "schema_version": EXECUTION_RECEIPT_SCHEMA,
        "result": "PASS",
        "census_self_sha256": census["self_sha256"],
        "result_canonicalization": RESULT_CANONICALIZATION,
        "database_access": "sqlite3 uri mode=ro&immutable=1 on a private copy of the admitted bytes; bytes rehashed after execution",
        "passes": passes,
        "item_count": len(per_item),
        "executed_count": len(per_item),
        "unstable_count": 0,
        "database_bytes_unchanged": True,
        "gold_results_set_sha256": sha(canonical([row["gold_result_sha256"] for row in per_item])),
        "items": per_item,
    }
    receipt["self_sha256"] = sha(canonical(receipt))
    return receipt


def verify_execution_receipt(receipt: dict[str, Any], census: dict[str, Any]) -> dict[str, str]:
    body = {key: value for key, value in receipt.items() if key != "self_sha256"}
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != EXECUTION_RECEIPT_SCHEMA
        or receipt.get("result") != "PASS"
        or sha(canonical(body)) != receipt.get("self_sha256")
        or receipt.get("census_self_sha256") != census["self_sha256"]
        or receipt.get("unstable_count") != 0
        or receipt.get("database_bytes_unchanged") is not True
    ):
        raise ValueError("EXECUTION_RECEIPT_IDENTITY_REFUSED")
    results = {row["item_id"]: row["gold_result_sha256"] for row in receipt.get("items", [])}
    if set(results) != {item["item_id"] for item in census["items"]} or not all(_is_sha(v) for v in results.values()):
        raise ValueError("EXECUTION_RECEIPT_TOTALITY_REFUSED")
    return results


def _catalog_binding(census: dict[str, Any], catalog_export_raw: bytes, dataset_ids: list[str]) -> dict[str, Any]:
    """Prove, from the live export, that every referenced object is a member of one of the named
    admitted heldout dataset versions and absent from every admitted TRAIN membership."""

    try:
        catalog = json.loads(catalog_export_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("TOOL_USE_CATALOG_EXPORT_UNREADABLE_REFUSED") from error
    records = catalog.get("records") if isinstance(catalog, dict) else None
    edges = catalog.get("edges") if isinstance(catalog, dict) else None
    if not isinstance(records, list) or not isinstance(edges, list) or not dataset_ids:
        raise ValueError("TOOL_USE_CATALOG_EXPORT_SCHEMA_REFUSED")
    for dataset_id in dataset_ids:
        if not any(
            isinstance(row, dict) and row.get("kind") == "dataset_version"
            and row.get("id") == dataset_id and row.get("state") == "admitted"
            for row in records
        ):
            raise ValueError(f"TOOL_USE_HELDOUT_DATASET_MISSING_REFUSED:{dataset_id}")
    memberships = {row["id"]: row for row in records if isinstance(row, dict) and row.get("kind") == "membership"}
    objects_by_membership: dict[str, set[str]] = {}
    for edge in edges:
        if isinstance(edge, dict) and edge.get("kind") == "membership_object" and isinstance(edge.get("from_id"), str):
            objects_by_membership.setdefault(edge["from_id"], set()).add(edge.get("to_id"))
    dataset_memberships = {
        edge["to_id"] for edge in edges
        if isinstance(edge, dict) and edge.get("kind") == "version_membership"
        and edge.get("from_id") in dataset_ids and edge.get("to_id") in memberships
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
    expected = {
        f"sha256:{item[f'{name}_object']['sha256']}" for item in census["items"] for name in OBJECT_CLASSES
    }
    if not expected <= heldout_objects:
        missing = sorted(expected - heldout_objects)[:3]
        raise ValueError(
            f"TOOL_USE_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED:{len(expected & heldout_objects)}/{len(expected)}:{missing}"
        )
    overlap = sorted(expected & train_objects)
    if overlap:
        raise ValueError(f"TOOL_USE_TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:{len(overlap)}:{overlap[:3]}")
    covering = sorted(m for m in dataset_memberships if objects_by_membership.get(m, set()) & expected)
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


def build_tool_use_contract(
    census: dict[str, Any], *, connector_raws: dict[str, bytes], execution_receipt_raw: bytes,
    payloads_by_sha: dict[str, bytes], catalog_export_raw: bytes | None = None, dataset_ids: list[str] | None = None,
) -> dict[str, Any]:
    verify_census(census)
    if set(connector_raws) != set(OBJECT_CLASSES):
        raise ValueError("TOOL_USE_CONNECTOR_TOTALITY_REFUSED")
    for name in OBJECT_CLASSES:
        try:
            connector = json.loads(connector_raws[name])
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"TOOL_USE_CONNECTOR_UNREADABLE_REFUSED:{name}") from error
        if connector.get("schema") != "corpus-connector-receipt-v1" or connector.get("source_id") != CLASS_SOURCE_ID[name]:
            raise ValueError(f"TOOL_USE_CONNECTOR_IDENTITY_REFUSED:{name}")
        expected = {item[f"{name}_object"]["sha256"] for item in census["items"]}
        if {row["sha256"] for row in connector.get("files", [])} != expected:
            raise ValueError(f"TOOL_USE_CONNECTOR_COVERAGE_REFUSED:{name}")
    try:
        execution = json.loads(execution_receipt_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("EXECUTION_RECEIPT_UNREADABLE_REFUSED") from error
    results = verify_execution_receipt(execution, census)
    if (catalog_export_raw is None) != (dataset_ids is None):
        raise ValueError("TOOL_USE_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED")
    frozen_items = []
    for item in census["items"]:
        prompt_raw = payloads_by_sha.get(item["prompt_object"]["sha256"])
        gold_raw = payloads_by_sha.get(item["gold_object"]["sha256"])
        if (
            not isinstance(prompt_raw, bytes) or sha(prompt_raw) != item["prompt_object"]["sha256"]
            or not isinstance(gold_raw, bytes) or sha(gold_raw) != item["gold_object"]["sha256"]
        ):
            raise ValueError(f"PAYLOAD_DRIFT_REFUSED:contract:{item['item_id']}")
        frozen_items.append({
            "item_id": item["item_id"],
            "db_id": item["db_id"],
            "gold_result_sha256": results[item["item_id"]],
            "gold_item_sha256": item_gold_sha256(prompt_raw, gold_raw, results[item["item_id"]]),
            **{f"{name}_object": dict(item[f"{name}_object"]) for name in OBJECT_CLASSES},
        })
    contract: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA,
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": TASK_ID,
            "consumes": ["prompt_payload_bytes", "gold_payload_bytes", "gold_result_sha256"],
            "forbidden_inputs": list(FORBIDDEN_INPUTS),
            "prediction": "sha256(prompt_payload_bytes + gold_payload_bytes + gold_result_sha256)",
            "scorer": "exact_match(prediction, gold_item_sha256)",
        },
        "source": {
            "benchmark_id": "spider",
            "split": "dev",
            "source_url": SOURCE_URL,
            "archive_sha256": ARCHIVE_SHA256,
            "freeze_protocol_sha256": PROTOCOL_SHA256,
            "freeze_references_sha256": REFERENCES_SHA256,
            "connector_receipt_raw_sha256s": {name: sha(connector_raws[name]) for name in OBJECT_CLASSES},
            "execution_receipt_self_sha256": execution["self_sha256"],
            "census_self_sha256": census["self_sha256"],
            "license_sha256": LICENSE_SHA256,
            "train_split_access": "never_read",
            "database_write_access": "forbidden",
            "prediction_custody_access": "forbidden",
        },
        "schema_rule": SCHEMA_RULE,
        "prompt_rule": PROMPT_RULE,
        "result_canonicalization": RESULT_CANONICALIZATION,
        "selection_rule": SELECTION_RULE,
        "referenced_object_set_sha256": census["referenced_object_set_sha256"],
        "admitted_object_set_sha256": census["admitted_object_set_sha256"],
        "selected_set_sha256": census["selected_set_sha256"],
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


def _catalog_train_rows(catalog: Path) -> set[str]:
    connection = sqlite3.connect(catalog.resolve(strict=True).as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        rows = connection.execute(
            """
            SELECT json_extract(m.payload_json, '$.exact_sha256')
            FROM data_catalog_records AS m
            WHERE m.kind = 'membership'
              AND json_extract(m.payload_json, '$.admission_state') = 'admitted'
              AND json_extract(m.payload_json, '$.split') = 'train'
            """
        ).fetchall()
    finally:
        connection.close()
    return {digest for (digest,) in rows if isinstance(digest, str)}


def read_admitted_train_object_hashes(catalog: Path) -> set[str]:
    return _catalog_train_rows(catalog)


def apply_planted_negative(kind: str, items: list[dict[str, Any]], train_hashes: set[str]) -> str:
    """Two planted negatives, applied BEFORE the census so the refusal is the census's own."""

    if kind == "gold-drift":
        first, second = items[0], items[1]
        first["gold_payload"], second["gold_payload"] = second["gold_payload"], first["gold_payload"]
        return f"golds of {first['item_id']} and {second['item_id']} swapped"
    if kind == "train-hash":
        digest = sha(items[0]["prompt_payload"])
        train_hashes.add(digest)
        return f"prompt object of {items[0]['item_id']} ({digest}) injected into the admitted train set"
    raise ValueError(f"PLANTED_NEGATIVE_KIND_REFUSED:{kind}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True, help="official Spider 1.0 zip (sha pinned)")
    parser.add_argument("--freeze", type=Path, required=True, help="spider-validation freeze v1 json")
    parser.add_argument("--parquet", type=Path, required=True, help="the freeze's references parquet")
    parser.add_argument("--license", type=Path, required=True, help="the frozen set's license text (HF card)")
    parser.add_argument("--custody-manifest", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True, help="census output (admit) or existing census (contract)")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--admission-dir", type=Path, help="where the four connector receipts are written")
    parser.add_argument("--admission-receipt", type=Path)
    parser.add_argument("--fetched-at")
    parser.add_argument("--projection-spec", type=Path)
    parser.add_argument("--tokenizer-sha256")
    parser.add_argument("--created-at-ms", type=int)
    parser.add_argument("--execution-receipt", type=Path, help="write (admit) or read (contract) the gold-execution receipt")
    parser.add_argument("--admission-dir-for-contract", type=Path)
    parser.add_argument("--catalog-export", type=Path)
    parser.add_argument("--dataset-id", action="append")
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--planted-negative", choices=["gold-drift", "train-hash"])
    parser.add_argument("--refusal-receipt", type=Path, help="with --planted-negative: the self-hashed refusal receipt")
    args = parser.parse_args()
    planted_note = None
    try:
        license_raw = args.license.read_bytes()
        manifest_raw = args.custody_manifest.read_bytes()
        freeze_raw = args.freeze.read_bytes()
        frozen = read_frozen_items(args.parquet, freeze_raw)
        archive = read_archive(args.archive.read_bytes(), dev_db_ids={row["db_id"] for row in frozen})
        items = build_items(frozen, archive)
        train_hashes = read_admitted_train_object_hashes(args.catalog)
        if args.planted_negative is not None:
            if args.refusal_receipt is None:
                raise ValueError("PLANTED_NEGATIVE_RECEIPT_ARGUMENT_REFUSED")
            planted_note = apply_planted_negative(args.planted_negative, items, train_hashes)
        census = build_census(
            items=items, archive=archive, freeze_raw=freeze_raw, license_raw=license_raw,
            custody_manifest_raw=manifest_raw, admitted_train_object_hashes=train_hashes,
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
        artifact_values = [args.output_root, args.admission_dir, args.admission_receipt, args.fetched_at]
        connector_raws: dict[str, bytes] | None = None
        execution_raw: bytes | None = None
        if any(value is not None for value in artifact_values):
            if any(value is None for value in artifact_values):
                raise ValueError("ADMISSION_ARTIFACT_ARGUMENT_TOTALITY_REFUSED")
            connector_raws, admission_raw = write_admission_artifacts(
                plan=plan, payloads_by_sha=payloads, license_raw=license_raw, output_root=args.output_root,
                admission_dir=args.admission_dir, admission_receipt_path=args.admission_receipt, fetched_at=args.fetched_at,
            )
            projection_values = [args.projection_spec, args.tokenizer_sha256, args.created_at_ms]
            if any(value is not None for value in projection_values):
                if any(value is None for value in projection_values):
                    raise ValueError("PROJECTION_SPEC_ARGUMENT_TOTALITY_REFUSED")
                write_new(args.projection_spec, build_projection_spec(
                    admission_dir=args.admission_dir, connector_raws=connector_raws,
                    admission_receipt_path=args.admission_receipt, admission_receipt_raw=admission_raw,
                    census_path=args.census, census_raw=census_raw, freeze_path=args.freeze, freeze_raw=freeze_raw,
                    license_path=args.license, tokenizer_sha256=args.tokenizer_sha256, created_at_ms=args.created_at_ms,
                ))
            if args.execution_receipt is not None:
                execution = execute_gold(census, payloads_by_sha=payloads)
                execution_raw = json.dumps(execution, sort_keys=True, indent=2).encode() + b"\n"
                write_new(args.execution_receipt, execution_raw)
        if args.contract is not None:
            if connector_raws is None:
                if args.admission_dir_for_contract is None:
                    raise ValueError("TOOL_USE_CONTRACT_ARGUMENT_TOTALITY_REFUSED")
                connector_raws = {
                    name: path.read_bytes() for name, path in connector_paths(args.admission_dir_for_contract).items()
                }
            if execution_raw is None:
                if args.execution_receipt is None:
                    raise ValueError("TOOL_USE_CONTRACT_ARGUMENT_TOTALITY_REFUSED")
                execution_raw = args.execution_receipt.read_bytes()
            if (args.catalog_export is None) != (args.dataset_id is None):
                raise ValueError("TOOL_USE_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED")
            contract = build_tool_use_contract(
                census, connector_raws=connector_raws, execution_receipt_raw=execution_raw, payloads_by_sha=payloads,
                catalog_export_raw=None if args.catalog_export is None else args.catalog_export.read_bytes(),
                dataset_ids=args.dataset_id,
            )
            write_new(args.contract, json.dumps(contract, sort_keys=True, indent=2).encode() + b"\n")
    except (OSError, TypeError, ValueError, KeyError) as error:
        message = f"{error!r}" if isinstance(error, KeyError) else f"{error}"
        if planted_note is not None:
            refusal: dict[str, Any] = {
                "schema_version": REFUSAL_RECEIPT_SCHEMA, "result": "REFUSED", "planted_negative": args.planted_negative,
                "planted_note": planted_note, "refusal": message,
            }
            refusal["self_sha256"] = sha(canonical(refusal))
            write_new(args.refusal_receipt, json.dumps(refusal, sort_keys=True, indent=2).encode() + b"\n")
            print(json.dumps({"result": "PLANTED_NEGATIVE_REFUSED", "refusal": message}, sort_keys=True))
            return 78
        print(f"error: {message}")
        return 2
    if planted_note is not None:
        print(json.dumps({"result": "PLANTED_NEGATIVE_NOT_REFUSED", "planted_note": planted_note}, sort_keys=True))
        return 3
    print(json.dumps({
        "result": "PASS",
        "item_count": census["item_count"],
        "object_counts": census["object_counts"],
        "admitted_object_set_sha256": census["admitted_object_set_sha256"],
        "selected_set_sha256": census["selected_set_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
