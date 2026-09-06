# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "issue2153_heldout_tool_use_assets.py"
SPEC = importlib.util.spec_from_file_location("issue2153_heldout_tool_use_assets", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


LICENSE_RAW = b"spider dataset card fixture (CC-BY-SA-4.0)\n"
# Two development databases, three items; item 2 shares db_b with item 1 so schema/database
# objects are shared across items while prompt/gold objects stay item-unique.
TABLES = [
    {
        "db_id": "db_a", "table_names_original": ["singer", "concert"],
        "column_names_original": [[-1, "*"], [0, "singer_id"], [0, "name"], [1, "concert_id"], [1, "singer_id"]],
        "column_types": ["text", "number", "text", "number", "number"], "primary_keys": [1, 3], "foreign_keys": [[4, 1]],
    },
    {
        "db_id": "db_b", "table_names_original": ["pets"],
        "column_names_original": [[-1, "*"], [0, "pet_id"], [0, "weight"]],
        "column_types": ["text", "number", "number"], "primary_keys": [1], "foreign_keys": [],
    },
]
ROWS = [
    {"question": "How many singers?", "query": "SELECT count(*) FROM singer", "db_id": "db_a"},
    {"question": "Pets by weight", "query": "SELECT pet_id FROM pets ORDER BY weight", "db_id": "db_b"},
    {"question": "All pet ids", "query": "SELECT pet_id FROM pets", "db_id": "db_b"},
]


def _database(sql: str) -> bytes:
    """Deterministic SQLite file image for a fixture schema (Python 3.10: no Connection.serialize)."""

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "fixture.sqlite"
        connection = sqlite3.connect(path)
        connection.executescript(sql)
        connection.commit()
        connection.close()
        return path.read_bytes()


DB_A = _database("CREATE TABLE singer(singer_id INT PRIMARY KEY, name TEXT); INSERT INTO singer VALUES (1,'a'),(2,'b');"
                 "CREATE TABLE concert(concert_id INT PRIMARY KEY, singer_id INT);")
DB_B = _database("CREATE TABLE pets(pet_id INT PRIMARY KEY, weight REAL); INSERT INTO pets VALUES (1,9.5),(2,3.0),(3,12.25);")


def _archive(rows=ROWS, *, databases=None, extra_sqlite: int = 0) -> bytes:
    databases = databases or {"db_a": DB_A, "db_b": DB_B}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("spider/dev.json", json.dumps(rows))
        archive.writestr("spider/tables.json", json.dumps(TABLES))
        archive.writestr("spider/dev_gold.sql", "".join(f"{r['query']}\t{r['db_id']}\n" for r in rows))
        for db_id, raw in databases.items():
            archive.writestr(f"spider/database/{db_id}/{db_id}.sqlite", raw)
        for index in range(extra_sqlite):
            archive.writestr(f"spider/database/other_{index}/other_{index}.sqlite", b"not read")
    return buffer.getvalue()


def _freeze() -> bytes:
    return json.dumps({
        "schema_version": MODULE.FREEZE_SCHEMA, "task_count": len(ROWS), "references_sha256": MODULE.REFERENCES_SHA256,
        "protocol_sha256": MODULE.PROTOCOL_SHA256, "license_sha256": sha(LICENSE_RAW), "license": "CC-BY-SA-4.0",
    }).encode()


MANIFEST_RAW = json.dumps({
    "schema_version": MODULE.CUSTODY_MANIFEST_SCHEMA, "benchmark_id": "spider", "target_training_access": "FORBIDDEN",
}).encode()


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(MODULE, "EXPECTED_ITEM_COUNT", len(ROWS))
    monkeypatch.setattr(MODULE, "EXPECTED_DEV_DATABASE_COUNT", 2)
    monkeypatch.setattr(MODULE, "ARCHIVE_SQLITE_COUNT", 3)
    monkeypatch.setattr(MODULE, "LICENSE_SHA256", sha(LICENSE_RAW))


def _items(rows=ROWS, archive_raw: bytes | None = None):
    frozen = MODULE.frozen_rows_from_records(rows)
    archive = MODULE.parse_archive(archive_raw or _archive(rows, extra_sqlite=1), dev_db_ids={r["db_id"] for r in rows})
    return MODULE.build_items(frozen, archive), archive


def _census(items, archive, train=frozenset()):
    return MODULE.build_census(
        items=items, archive=archive, freeze_raw=_freeze(), license_raw=LICENSE_RAW,
        custody_manifest_raw=MANIFEST_RAW, admitted_train_object_hashes=set(train),
    )


def test_schema_serialization_is_deterministic_and_keeps_table_order() -> None:
    first = MODULE.serialize_schema(json.loads(json.dumps(TABLES[0])))
    second = MODULE.serialize_schema(json.loads(json.dumps(TABLES[0])))
    assert MODULE.canonical(first) == MODULE.canonical(second)
    assert [table["table"] for table in first["tables"]] == ["singer", "concert"]
    assert first["tables"][0]["columns"][0] == {"name": "singer_id", "type": "number", "primary_key": True}
    assert first["foreign_keys"] == [{"from": ["concert", "singer_id"], "to": ["singer", "singer_id"]}]


def test_prompt_object_is_canonical_json_bound_to_item_db_and_schema(small) -> None:
    items, _archive = _items()
    prompt = json.loads(items[0]["prompt_payload"])
    assert set(prompt) == {"item_id", "db_id", "question", "schema"}
    assert prompt["item_id"] == "spider-dev-0000" and prompt["db_id"] == "db_a"
    assert MODULE.canonical(prompt["schema"]) == items[0]["schema_payload"]
    assert json.loads(items[0]["gold_payload"]) == {"id": "spider-dev-0000", "query": ROWS[0]["query"]}


def test_census_passes_and_counts_shared_database_objects_once(small) -> None:
    items, archive = _items()
    census = _census(items, archive)
    MODULE.verify_census(census)
    assert census["object_counts"] == {"prompt": 3, "gold": 3, "schema": 2, "database": 2}
    assert census["referenced_object_count"] == 10
    assert census["train_intersection"] == {"executed": True, "admitted_train_object_count": 0, "count": 0}


def test_archive_dev_rows_that_differ_from_the_frozen_set_refuse_before_any_object_exists(small) -> None:
    rows = [dict(ROWS[0]), dict(ROWS[1]), dict(ROWS[2])]
    rows[1]["query"] = "SELECT pet_id FROM pets ORDER BY weight DESC"
    frozen = MODULE.frozen_rows_from_records(ROWS)
    archive = MODULE.parse_archive(_archive(rows, extra_sqlite=1), dev_db_ids={"db_a", "db_b"})
    with pytest.raises(ValueError, match="ARCHIVE_FROZEN_SET_DRIFT_REFUSED"):
        MODULE.build_items(frozen, archive)


def test_planted_train_hash_refuses_the_census(small) -> None:
    items, archive = _items()
    train: set[str] = set()
    MODULE.apply_planted_negative("train-hash", items, train)
    with pytest.raises(ValueError, match="TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED"):
        _census(items, archive, train)


def test_planted_gold_drift_two_golds_swapped_refuses_the_census(small) -> None:
    items, archive = _items()
    MODULE.apply_planted_negative("gold-drift", items, set())
    with pytest.raises(ValueError, match="GOLD_ITEM_ID_DRIFT_REFUSED:spider-dev-0000"):
        _census(items, archive)


def test_totality_short_by_one_refuses(small, monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "EXPECTED_ITEM_COUNT", len(ROWS) + 1)
    with pytest.raises(ValueError, match="FROZEN_ROW_COUNT_REFUSED"):
        MODULE.frozen_rows_from_records(ROWS)


def test_result_canonicalization_ignores_order_only_without_order_by() -> None:
    forward = [(1, "a"), (2, "b")]
    backward = [(2, "b"), (1, "a")]
    assert MODULE.canonical_result(forward, ordered=False) == MODULE.canonical_result(backward, ordered=False)
    assert MODULE.canonical_result(forward, ordered=True) != MODULE.canonical_result(backward, ordered=True)
    assert MODULE.canonical_result([(b"\x00\x01",)], ordered=True) == MODULE.canonical_result([("0001",)], ordered=True)


def test_gold_execution_is_stable_read_only_and_binds_the_census(small) -> None:
    items, archive = _items()
    census = _census(items, archive)
    receipt = MODULE.execute_gold(census, payloads_by_sha=MODULE.payloads_from_items(items))
    assert receipt["item_count"] == receipt["executed_count"] == 3 and receipt["unstable_count"] == 0
    assert receipt["database_bytes_unchanged"] is True and receipt["census_self_sha256"] == census["self_sha256"]
    results = MODULE.verify_execution_receipt(receipt, census)
    # Item 2 (unordered) and item 1 (ORDER BY) read the same rows; their hashes differ only by order rule.
    assert results["spider-dev-0001"] != results["spider-dev-0002"]
    assert results["spider-dev-0000"] == MODULE.canonical_result([(2,)], ordered=False)


def test_a_gold_query_that_writes_refuses_execution(small) -> None:
    rows = [dict(ROWS[0]), dict(ROWS[1]), dict(ROWS[2])]
    rows[2]["query"] = "DELETE FROM pets"
    items, archive = _items(rows)
    census = _census(items, archive)
    with pytest.raises(ValueError, match="TOOL_USE_GOLD_EXECUTION_REFUSED"):
        MODULE.execute_gold(census, payloads_by_sha=MODULE.payloads_from_items(items))


def test_a_nondeterministic_gold_result_refuses_as_unstable(small) -> None:
    rows = [dict(ROWS[0]), dict(ROWS[1]), dict(ROWS[2])]
    rows[2]["query"] = "SELECT random()"
    items, archive = _items(rows)
    census = _census(items, archive)
    with pytest.raises(ValueError, match="TOOL_USE_GOLD_RESULT_UNSTABLE_REFUSED"):
        MODULE.execute_gold(census, payloads_by_sha=MODULE.payloads_from_items(items))


def test_admission_plan_files_and_contract_bind_execution_results(small, tmp_path) -> None:
    items, archive = _items()
    census = _census(items, archive)
    payloads = MODULE.payloads_from_items(items)
    plan = MODULE.build_admission_plan(census, payloads_by_sha=payloads)
    assert {row["source_id"] for row in plan["rows"]} == set(MODULE.CLASS_SOURCE_ID.values())
    assert plan["files"]["database"][0]["path"].endswith(".sqlite") and len(plan["files"]["prompt"]) == 3
    connectors, admission_raw = MODULE.write_admission_artifacts(
        plan=plan, payloads_by_sha=payloads, license_raw=LICENSE_RAW, output_root=tmp_path / "custody",
        admission_dir=tmp_path / "admission", admission_receipt_path=tmp_path / "admission" / "admission-receipt-v1.json",
        fetched_at="2026-09-05T00:00:00Z",
    )
    assert set(connectors) == set(MODULE.OBJECT_CLASSES)
    written = sorted(p.relative_to(tmp_path / "custody").as_posix() for p in (tmp_path / "custody").rglob("*") if p.is_file())
    assert len(written) == 10
    with pytest.raises(ValueError, match="NO_OVERWRITE_REFUSED"):
        MODULE.write_admission_artifacts(
            plan=plan, payloads_by_sha=payloads, license_raw=LICENSE_RAW, output_root=tmp_path / "custody",
            admission_dir=tmp_path / "admission", admission_receipt_path=tmp_path / "admission" / "admission-receipt-v1.json",
            fetched_at="2026-09-05T00:00:00Z",
        )
    execution = MODULE.execute_gold(census, payloads_by_sha=payloads)
    execution_raw = json.dumps(execution, sort_keys=True).encode()
    contract = MODULE.build_tool_use_contract(
        census, connector_raws=connectors, execution_receipt_raw=execution_raw, payloads_by_sha=payloads,
    )
    assert contract["totality"] == {"expected": 3, "observed": 3, "complete": True}
    item = contract["frozen_items"][0]
    assert item["gold_item_sha256"] == sha(items[0]["prompt_payload"] + items[0]["gold_payload"] + item["gold_result_sha256"].encode())
    assert "catalog_binding" not in contract
    tampered = dict(execution)
    tampered["items"] = list(execution["items"][1:])
    with pytest.raises(ValueError, match="EXECUTION_RECEIPT_IDENTITY_REFUSED"):
        MODULE.build_tool_use_contract(
            census, connector_raws=connectors, execution_receipt_raw=json.dumps(tampered).encode(), payloads_by_sha=payloads,
        )
    spec = json.loads(MODULE.build_projection_spec(
        admission_dir=tmp_path / "admission", connector_raws=connectors,
        admission_receipt_path=tmp_path / "admission" / "admission-receipt-v1.json", admission_receipt_raw=admission_raw,
        census_path=tmp_path / "census.json", census_raw=b"{}", freeze_path=tmp_path / "freeze.json", freeze_raw=_freeze(),
        license_path=tmp_path / "LICENSE", tokenizer_sha256="0" * 64, created_at_ms=1,
    ))
    assert [row["domain"] for row in spec["rows"]] == ["text", "text", "text", "tool"]
    assert all("-heldout-" in row["source_id"] and row["split"] == "heldout" for row in spec["rows"])


def test_catalog_binding_requires_every_object_admitted_heldout_and_absent_from_train(small) -> None:
    items, archive = _items()
    census = _census(items, archive)
    objects = [f"sha256:{item[f'{name}_object']['sha256']}" for item in census["items"] for name in MODULE.OBJECT_CLASSES]
    dataset = "dataset:issue1581-bulk-heldout:" + "a" * 64
    export = {
        "records": [
            {"kind": "dataset_version", "id": dataset, "state": "admitted"},
            {"kind": "membership", "id": "m-heldout", "split": "heldout", "admission_state": "admitted"},
            {"kind": "membership", "id": "m-train", "split": "train", "admission_state": "admitted"},
        ],
        "edges": [{"kind": "version_membership", "from_id": dataset, "to_id": "m-heldout"}]
        + [{"kind": "membership_object", "from_id": "m-heldout", "to_id": digest} for digest in objects],
    }
    binding = MODULE._catalog_binding(census, json.dumps(export).encode(), [dataset])
    assert binding["referenced_object_count"] == 10 and binding["train_exclusion"]["overlap_count"] == 0
    export["edges"].append({"kind": "membership_object", "from_id": "m-train", "to_id": objects[0]})
    with pytest.raises(ValueError, match="TOOL_USE_TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED"):
        MODULE._catalog_binding(census, json.dumps(export).encode(), [dataset])
    # Drop the train edge again and remove the (item-unique) prompt object's heldout edge.
    export["edges"] = [edge for edge in export["edges"][:-1] if edge.get("to_id") != objects[0]]
    with pytest.raises(ValueError, match="TOOL_USE_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED"):
        MODULE._catalog_binding(census, json.dumps(export).encode(), [dataset])
