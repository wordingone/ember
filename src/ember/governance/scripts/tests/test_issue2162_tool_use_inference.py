# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2162 consumer tests: totality pass, adapter row, planted negatives, non-executing emissions."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SCRIPTS = ROOT / "src" / "ember" / "governance" / "scripts"
PRODUCER = SCRIPTS / "issue2162_tool_use_inference.py"
ROW_SCRIPT = SCRIPTS / "issue1947_release_row.py"
EXECUTE_SCRIPT = SCRIPTS / "issue1947_release_execute.py"
MANIFEST_SHA = "255cdb164b770f868da9a6727b1067512b5ce9caecd968f4544389c5a908aeef"
PINNED_DECODE_CONTRACT_SHA = "c20d478ad9deac029040e888309be8642b7a8be11ff5ccf00dac9e44e7d3e1df"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


producer = _load(PRODUCER, "issue2162_tool_use_inference_under_test")
executor = _load(EXECUTE_SCRIPT, "issue1947_release_execute_under_test")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _self_hashed(payload: dict) -> dict:
    body = {key: value for key, value in payload.items() if key != "self_sha256"}
    body["self_sha256"] = _sha(_canonical(body))
    return body


def _write_json(path: Path, payload: dict) -> bytes:
    raw = json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _gold_query(index: int, db_id: str) -> str:
    if db_id == "alpha":
        return f"SELECT id, name FROM t WHERE id = {index % 50} ORDER BY id;"
    return f"SELECT x FROM u WHERE x > {index % 30};"


class World:
    """1,034 frozen items over two admitted sqlite databases, four connector receipts, a contract."""

    def __init__(self, root: Path) -> None:
        self.root = root
        custody = root / "custody"
        objects: dict[str, dict[str, list[dict]]] = {cls: {"files": []} for cls in ("prompts", "golds", "schemas", "databases")}
        self.db_bytes: dict[str, bytes] = {}
        self.db_sha: dict[str, str] = {}
        for db_id in ("alpha", "beta"):
            path = root / f"{db_id}.sqlite"
            connection = sqlite3.connect(path)
            if db_id == "alpha":
                connection.execute("CREATE TABLE t(id INTEGER, name TEXT)")
                connection.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"n{i}") for i in range(50)])
            else:
                connection.execute("CREATE TABLE u(x INTEGER)")
                connection.executemany("INSERT INTO u VALUES (?)", [(i,) for i in range(40)])
            connection.commit()
            connection.close()
            raw = path.read_bytes()
            self.db_bytes[db_id] = raw
            self.db_sha[db_id] = _sha(raw)
            self._add(custody, objects, "databases", raw, ".sqlite")
        self.items: list[dict] = []
        self.gold_queries: list[str] = []
        for index in range(producer.ITEM_COUNT):
            db_id = "alpha" if index % 2 == 0 else "beta"
            query = _gold_query(index, db_id)
            self.gold_queries.append(query)
            prompt = f"-- database: {db_id}\n-- question {index}\nSQL:".encode()
            gold = query.encode()
            schema = f"schema-{db_id}".encode()
            connection = sqlite3.connect(root / f"{db_id}.sqlite")
            rows = connection.execute(query).fetchall()
            connection.close()
            gold_result = producer.canonical_result(rows, ordered="order by" in query.lower())
            item = {
                "item_id": f"spider-dev-{index:04d}",
                "db_id": db_id,
                "gold_item_sha256": _sha(prompt + gold),
                "gold_result_sha256": gold_result,
                "prompt_object": self._add(custody, objects, "prompts", prompt, ".txt"),
                "gold_object": self._add(custody, objects, "golds", gold, ".sql"),
                "schema_object": self._add(custody, objects, "schemas", schema, ".txt"),
                "database_object": {"sha256": self.db_sha[db_id], "byte_count": len(self.db_bytes[db_id]), "media_type": "application/vnd.sqlite3"},
            }
            self.items.append(item)
        self.receipt_paths: dict[str, Path] = {}
        bound: dict[str, str] = {}
        for cls, payload in objects.items():
            receipt = {"schema": "corpus-connector-receipt-v1", "dest_root": str(custody), "files": payload["files"]}
            path = root / f"connector-receipt-{cls}-v1.json"
            raw = _write_json(path, receipt)
            self.receipt_paths[cls] = path
            bound[cls[:-1] if cls != "databases" else "database"] = _sha(raw)
        contract = {
            "schema_version": producer.CONTRACT_SCHEMA,
            "result": "PASS",
            "task_class": "adapter_totality",
            "totality": {"expected": producer.ITEM_COUNT, "observed": producer.ITEM_COUNT, "complete": True},
            "frozen_items": self.items,
            "catalog_binding": {"catalog_export_raw_sha256": "6b" * 32},
            "source": {"connector_receipt_raw_sha256s": bound},
        }
        self.contract = _self_hashed(contract)
        self.contract_path = root / "protected-tool-use-contract-v1.json"
        self.contract_raw = _write_json(self.contract_path, self.contract)

    @staticmethod
    def _add(custody: Path, objects: dict, cls: str, raw: bytes, suffix: str) -> dict:
        digest = _sha(raw)
        relative = f"{cls}/{digest[:2]}/{digest}{suffix}"
        path = custody / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            objects[cls]["files"].append({"path": relative, "bytes": len(raw), "sha256": digest})
        return {"sha256": digest, "byte_count": len(raw), "media_type": "text/plain"}

    def sources(self):
        return producer.load_sources(self.contract, list(self.receipt_paths.values()))

    def emitter(self, position: int) -> str:
        if position % 5 == 0:
            return "SELEC nothing;"  # does not parse -> executed False
        if position % 7 == 0:
            return "SELECT 1;"  # executes, wrong result
        return self.gold_queries[position]

    def emit(self, prompt_text: str, position: int) -> dict:
        assert prompt_text.startswith("-- database:")
        return {"decoded_text": self.emitter(position) + " trailing text", "generated_token_count": 9, "prompt_token_count": 12, "stop_reason": "first_semicolon_in_decoded_text"}

    def expected_counts(self) -> tuple[int, int]:
        executed = sum(1 for i in range(producer.ITEM_COUNT) if i % 5 != 0)
        matched = sum(1 for i in range(producer.ITEM_COUNT) if i % 5 != 0 and i % 7 != 0)
        return executed, matched

    def receipt(self) -> dict:
        by_sha, supplied = self.sources()
        result = producer.run_pass(self.contract, by_sha, self.emit)
        return producer.build_receipt(
            contract=self.contract, contract_raw=self.contract_raw, pass_result=result,
            checkpoint_manifest_raw_sha256=MANIFEST_SHA, model_bindings={"device": "test"},
            connector_receipt_raw_sha256s=supplied,
        )


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    return World(tmp_path_factory.mktemp("issue2162"))


@pytest.fixture(scope="module")
def receipt(world: World) -> dict:
    return world.receipt()


def _run_adapter(world: World, receipt_path: Path, result_path: Path, manifest_sha: str = MANIFEST_SHA):
    return subprocess.run(
        [sys.executable, str(ROW_SCRIPT), "adapt-tool-use", "--contract", str(world.contract_path),
         "--inference-receipt", str(receipt_path), "--expected-checkpoint-manifest-sha256", manifest_sha,
         "--result", str(result_path)],
        capture_output=True, text=True, check=False,
    )


def test_decode_contract_sha_is_pinned() -> None:
    assert producer.decode_contract_sha256() == _sha(_canonical(producer.DECODE_CONTRACT)) == PINNED_DECODE_CONTRACT_SHA
    assert producer.DECODE_CONTRACT["strategy"] == "greedy_argmax"
    assert producer.DECODE_CONTRACT["max_new_tokens"] == 256
    assert producer.DECODE_CONTRACT["sampling"] is False and producer.DECODE_CONTRACT["retries"] == 0


def test_pass_is_total_ordered_and_self_hashed(world: World, receipt: dict) -> None:
    executed, matched = world.expected_counts()
    assert receipt["result"] == "TOOL_USE_INFERENCE_PASS"
    assert receipt["item_count"] == receipt["emitted_count"] == producer.ITEM_COUNT
    assert (receipt["executed_count"], receipt["matched_count"]) == (executed, matched)
    assert receipt["database_bytes_unchanged"] is True
    assert receipt["checkpoint_manifest_raw_sha256"] == MANIFEST_SHA
    assert receipt["contract_self_sha256"] == world.contract["self_sha256"]
    assert receipt["decode_contract_sha256"] == PINNED_DECODE_CONTRACT_SHA
    body = dict(receipt)
    assert body.pop("self_sha256") == _sha(_canonical(body))
    ids = [item["item_id"] for item in receipt["items"]]
    assert ids == [f"spider-dev-{i:04d}" for i in range(producer.ITEM_COUNT)]
    assert receipt["frozen_order_sha256"] == _sha(_canonical(ids))
    assert all(item["position"] == i for i, item in enumerate(receipt["items"]))
    # emission = decoded text up to the first ';' (the trailing text never reaches the record)
    assert receipt["items"][1]["emission"] == world.gold_queries[1]
    assert receipt["items"][0]["executed"] is False and receipt["items"][0]["error_class"] == "OperationalError"
    assert receipt["items"][7]["executed"] is True and receipt["items"][7]["matched"] is False
    assert receipt["items"][1]["matched"] is True
    assert "gold" not in json.dumps(receipt["items"][1]).lower().replace("gold_result", "")


def test_verify_receipt_rederives_score(world: World, receipt: dict, tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    _write_json(path, receipt)
    verified = producer.verify_receipt(path, world.contract_path, expected_checkpoint_manifest_sha256=MANIFEST_SHA)
    executed, matched = world.expected_counts()
    assert (verified["executed_count"], verified["matched_count"]) == (executed, matched)
    assert verified["score"] == matched / producer.ITEM_COUNT
    assert len(verified["items"]) == producer.ITEM_COUNT
    assert verified["items"][1]["prediction"] == receipt["items"][1]["emission_sha256"]
    assert verified["items"][1]["gold_item_sha256"] == world.items[1]["gold_item_sha256"]


def test_adapter_row_produced_and_accepted_by_executor(world: World, receipt: dict, tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    _write_json(receipt_path, receipt)
    result = tmp_path / "row.json"
    completed = _run_adapter(world, receipt_path, result)
    assert completed.returncode == 0, completed.stderr
    row = json.loads(result.read_text(encoding="utf-8"))
    assert row["result"] == "TOOL_USE_HELDOUT_ROW_PRODUCED"
    assert row["task_class"] == "checkpoint_inference"
    assert row["row_id"] == "E-MATRIX-TOOL-USE"
    executed, matched = world.expected_counts()
    assert row["score"] == matched / producer.ITEM_COUNT
    assert row["matched_count"] == matched and row["executed_count"] == executed
    assert row["inference_receipt_self_sha256"] == receipt["self_sha256"]
    assert row["checkpoint_manifest_raw_sha256"] == MANIFEST_SHA
    body = dict(row)
    assert body.pop("self_sha256") == _sha(_canonical(body))
    validated = executor.validate_row(row, "E-MATRIX-TOOL-USE")
    assert len(validated["items"]) == producer.ITEM_COUNT
    assert sum(item["score"] for item in validated["items"]) == matched
    # the row result is no-overwrite
    again = _run_adapter(world, receipt_path, result)
    assert again.returncode != 0


def _refusal(world: World, tmp_path: Path, name: str, payload: dict | bytes, *, manifest_sha: str = MANIFEST_SHA) -> dict:
    receipt_path = tmp_path / f"{name}.json"
    if isinstance(payload, bytes):
        receipt_path.write_bytes(payload)
    else:
        _write_json(receipt_path, payload)
    result = tmp_path / f"{name}-row.json"
    completed = _run_adapter(world, receipt_path, result, manifest_sha)
    assert completed.returncode == 78, completed.stderr
    row = json.loads(result.read_text(encoding="utf-8"))
    assert row["result"] == "TOOL_USE_HELDOUT_REFUSED"
    assert row["task_class"] == "checkpoint_inference"
    body = dict(row)
    assert body.pop("self_sha256") == _sha(_canonical(body))
    return row


def test_planted_negative_order_swap(world: World, receipt: dict, tmp_path: Path) -> None:
    tampered = json.loads(json.dumps(receipt))
    tampered["items"][3], tampered["items"][4] = tampered["items"][4], tampered["items"][3]
    row = _refusal(world, tmp_path, "order", _self_hashed(tampered))
    assert row["reason"].startswith("TOOL_USE_EMISSION_ORDER_REFUSED")


def test_planted_negative_checkpoint_binding(world: World, receipt: dict, tmp_path: Path) -> None:
    row = _refusal(world, tmp_path, "checkpoint", receipt, manifest_sha="ab" * 32)
    assert row["reason"] == "TOOL_USE_INFERENCE_CHECKPOINT_BINDING_REFUSED"


def test_planted_negative_byte_edit_after_self_hash(world: World, receipt: dict, tmp_path: Path) -> None:
    raw = json.dumps(receipt, indent=2, sort_keys=True).encode()
    edited = raw.replace(b'"matched_count": ', b'"matched_count": 1', 1)
    assert edited != raw
    row = _refusal(world, tmp_path, "byte-edit", edited)
    assert row["reason"].startswith("TOOL_USE_INFERENCE_RECEIPT_SELF_HASH_REFUSED")


def test_planted_negative_totality(world: World, receipt: dict, tmp_path: Path) -> None:
    tampered = json.loads(json.dumps(receipt))
    tampered["items"].pop()
    row = _refusal(world, tmp_path, "totality", _self_hashed(tampered))
    assert row["reason"].startswith("TOOL_USE_INFERENCE_TOTALITY_REFUSED")


def test_planted_negative_matched_flag_not_trusted(world: World, receipt: dict, tmp_path: Path) -> None:
    tampered = json.loads(json.dumps(receipt))
    assert tampered["items"][7]["matched"] is False
    tampered["items"][7]["matched"] = True
    tampered["matched_count"] += 1
    row = _refusal(world, tmp_path, "matched-flag", _self_hashed(tampered))
    assert row["reason"].startswith("TOOL_USE_INFERENCE_CONTRACT_BINDING_REFUSED:matched")


def test_planted_negative_contract_drift(world: World, receipt: dict, tmp_path: Path) -> None:
    tampered = json.loads(json.dumps(receipt))
    tampered["contract_self_sha256"] = "cd" * 32
    row = _refusal(world, tmp_path, "contract", _self_hashed(tampered))
    assert row["reason"] == "TOOL_USE_INFERENCE_CONTRACT_BINDING_REFUSED"


def test_non_executing_and_timeout_emissions_count_as_mismatch(world: World) -> None:
    by_sha, _supplied = world.sources()
    runaway = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c;"

    def emit(prompt_text: str, position: int) -> dict:
        if position == 3:
            text = runaway
        elif position == 4:
            text = ""
        elif position == 5:
            text = "DELETE FROM t;"  # read-only connection: OperationalError, counted, bytes unchanged
        else:
            text = world.gold_queries[position]
        return {"decoded_text": text, "generated_token_count": 1, "prompt_token_count": 1, "stop_reason": "eos_token"}

    result = producer.run_pass(world.contract, by_sha, emit, sql_timeout_seconds=0.2)
    records = result["items"]
    assert records[3]["executed"] is False and records[3]["error_class"] == "TIMEOUT"
    assert records[4]["executed"] is False and records[4]["error_class"] == "EMPTY_EMISSION"
    assert records[5]["executed"] is False and records[5]["error_class"] == "OperationalError"
    assert result["item_count"] == producer.ITEM_COUNT
    assert result["executed_count"] == producer.ITEM_COUNT - 3
    assert result["matched_count"] == producer.ITEM_COUNT - 3
    assert result["database_bytes_unchanged"] is True


def test_short_pass_is_a_totality_refusal(world: World) -> None:
    by_sha, _supplied = world.sources()
    short = json.loads(json.dumps(world.contract))
    short["frozen_items"] = short["frozen_items"][:-1]
    with pytest.raises(ValueError, match="TOOL_USE_INFERENCE_TOTALITY_REFUSED"):
        producer.run_pass(short, by_sha, world.emit)


def test_forbidden_source_schema_refused_before_read(world: World, tmp_path: Path) -> None:
    forged = tmp_path / "forged.json"
    _write_json(forged, {"schema": "something-else-v1", "dest_root": str(tmp_path), "files": []})
    paths = list(world.receipt_paths.values())
    with pytest.raises(ValueError, match="TOOL_USE_FORBIDDEN_INPUT_REFUSED:source_schema"):
        producer.load_sources(world.contract, paths[:-1] + [forged])
    with pytest.raises(ValueError, match="TOOL_USE_SOURCE_RECEIPT_SET_INCOMPLETE_REFUSED"):
        producer.load_sources(world.contract, paths[:-1])


def test_extract_sql_rules() -> None:
    assert producer.extract_sql("SELECT 1 ;\nignored") == "SELECT 1 ;"
    assert producer.extract_sql("select a\n\nmore") == "select a"
    assert producer.extract_sql("  bare ") == "bare"


def test_verify_subcommand_matches_adapter(world: World, receipt: dict, tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    _write_json(receipt_path, receipt)
    completed = subprocess.run(
        [sys.executable, str(PRODUCER), "verify", "--receipt", str(receipt_path), "--contract", str(world.contract_path),
         "--expected-checkpoint-manifest-sha256", MANIFEST_SHA],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    _executed, matched = world.expected_counts()
    assert payload["result"] == "VERIFIED" and payload["matched_count"] == matched
