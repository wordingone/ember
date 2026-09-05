# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "issue2148_heldout_reasoning_answers.py"
SPEC = importlib.util.spec_from_file_location("issue2148_heldout_reasoning_answers", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# Three MMMU-shaped items across two subjects; the item text objects are the #2130 canonical
# {id, question, options} payloads and the answers are the parquet `answer` strings.
ITEMS = {
    "validation_Art_1": ("Art", "Which period?", "['A', 'B', 'C', 'D']", "B"),
    "validation_Art_2": ("Art", "Which style?", "['A', 'B']", "A"),
    "validation_Math_1": ("Math", "Compute.", "['A', 'B', 'C']", "C"),
}
LICENSE_RAW = b"MMMU license fixture\n"
CUSTODY_MANIFEST_RAW = json.dumps({"license_sha256": sha(LICENSE_RAW), "files": []}, sort_keys=True).encode()


def _text_object(item_id: str, question: str, options: str) -> bytes:
    payload = {"id": item_id, "options": options, "question": question}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _predecessor_contract_raw(*, drop_one: bool = False) -> tuple[bytes, dict]:
    frozen = []
    for item_id, (_subject, question, options, _answer) in ITEMS.items():
        text = _text_object(item_id, question, options)
        frozen.append({
            "item_id": item_id,
            "gold_item_sha256": sha(b"image-" + item_id.encode() + text),
            "image_objects": [{"sha256": sha(b"image-" + item_id.encode()), "byte_count": 6, "media_type": "image/png"}],
            "item_text_object": {"sha256": sha(text), "byte_count": len(text), "media_type": "application/json"},
        })
    if drop_one:
        frozen = frozen[1:]
    n = len(ITEMS)
    contract = {
        "schema_version": MODULE.PREDECESSOR_CONTRACT_SCHEMA,
        "result": "PASS",
        "frozen_items": sorted(frozen, key=lambda row: row["item_id"]),
        "totality": {"expected": n, "observed": n, "complete": True},
        "admitted_object_set_sha256": sha(canonical(sorted(row["item_text_object"]["sha256"] for row in frozen))),
    }
    contract["self_sha256"] = sha(canonical(contract))
    return json.dumps(contract, sort_keys=True).encode(), contract


def _predecessor_connector(root: Path) -> tuple[Path, bytes]:
    custody = root / "items-custody"
    files = []
    for item_id, (_subject, question, options, _answer) in ITEMS.items():
        text = _text_object(item_id, question, options)
        digest = sha(text)
        path = custody / "items" / digest[:2] / f"{digest}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text)
        files.append({"path": f"items/{digest[:2]}/{digest}.json", "bytes": len(text), "sha256": digest})
    raw = json.dumps({
        "schema": "corpus-connector-receipt-v1",
        "source_id": MODULE.PREDECESSOR_ITEMS_SOURCE_ID,
        "dest_root": str(custody),
        "files": sorted(files, key=lambda row: row["sha256"]),
    }, sort_keys=True, indent=2).encode() + b"\n"
    receipt = root / "predecessor-connector.json"
    receipt.write_bytes(raw)
    return receipt, raw


def _items_from_contract(contract: dict, answers: dict[str, str] | None = None) -> list[dict]:
    answers = answers or {item_id: row[3] for item_id, row in ITEMS.items()}
    items = []
    for row in contract["frozen_items"]:
        payload = MODULE.answer_text_object(row["item_id"], answers[row["item_id"]])
        items.append({
            "item_id": row["item_id"],
            "item_text_sha256": row["item_text_object"]["sha256"],
            "item_text_byte_count": row["item_text_object"]["byte_count"],
            "answer_payload": payload,
            "answer_sha256": sha(payload),
        })
    return items


@pytest.fixture
def inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    contract_raw, contract = _predecessor_contract_raw()
    monkeypatch.setattr(MODULE, "EXPECTED_ITEM_COUNT", len(ITEMS))
    monkeypatch.setattr(MODULE, "EXPECTED_PARQUET_FILE_COUNT", 2)
    monkeypatch.setattr(MODULE, "LICENSE_SHA256", sha(LICENSE_RAW))
    monkeypatch.setattr(MODULE, "CUSTODY_MANIFEST_SHA256", sha(CUSTODY_MANIFEST_RAW))
    monkeypatch.setattr(MODULE, "PREDECESSOR_CONTRACT_SELF_SHA256", contract["self_sha256"])
    monkeypatch.setattr(MODULE, "PREDECESSOR_ADMITTED_OBJECT_SET_SHA256", contract["admitted_object_set_sha256"])
    predecessor_path, predecessor_raw = _predecessor_connector(tmp_path)
    text_hashes = {row["item_text_object"]["sha256"] for row in contract["frozen_items"]}
    return {
        "contract_raw": contract_raw, "contract": contract, "predecessor_path": predecessor_path,
        "predecessor_raw": predecessor_raw, "text_hashes": text_hashes, "tmp": tmp_path,
    }


def _census(inputs, *, train: set[str] | None = None, items: list[dict] | None = None, heldout: set[str] | None = None):
    items = items or _items_from_contract(inputs["contract"])
    payloads = MODULE.read_predecessor_text_payloads(inputs["predecessor_raw"], items)
    census = MODULE.build_census(
        items=items, parquet_file_count=2, license_raw=LICENSE_RAW, custody_manifest_raw=CUSTODY_MANIFEST_RAW,
        predecessor_contract_raw=inputs["contract_raw"], predecessor_connector_raw=inputs["predecessor_raw"],
        text_payloads=payloads, admitted_train_object_hashes=train or {sha(b"some-train-object")},
        admitted_heldout_text_hashes=inputs["text_hashes"] if heldout is None else heldout,
    )
    return items, census


def test_census_pairs_each_item_with_its_answer_and_executes_train_exclusion(inputs) -> None:
    _items, census = _census(inputs)
    MODULE.verify_census(census)
    assert census["item_count"] == 3 and census["answer_object_count"] == 3 and census["item_text_object_count"] == 3
    assert census["train_intersection"] == {"executed": True, "admitted_train_object_count": 1, "count": 0}
    by_id = {item["item_id"]: item for item in census["items"]}
    assert list(by_id) == sorted(ITEMS)
    for item_id, (_subject, question, options, answer) in ITEMS.items():
        row = by_id[item_id]
        text = _text_object(item_id, question, options)
        expected_answer = MODULE.answer_text_object(item_id, answer)
        assert json.loads(expected_answer) == {"answer": answer, "id": item_id}
        assert row["item_text_object"] == {"sha256": sha(text), "byte_count": len(text), "media_type": "application/json"}
        assert row["answer_object"] == {"sha256": sha(expected_answer), "byte_count": len(expected_answer), "media_type": "application/json"}
        assert row["gold_item_sha256"] == sha(text + expected_answer)
    assert census["admitted_object_set_sha256"] == sha(canonical(sorted(row["answer_object"]["sha256"] for row in census["items"])))
    assert census["referenced_object_count"] == 6
    # Determinism: the same inputs yield the same selected set identity.
    assert _census(inputs)[1]["admitted_object_set_sha256"] == census["admitted_object_set_sha256"]


def test_planted_train_hash_refuses_the_census(inputs) -> None:
    items, _ = _census(inputs)
    with pytest.raises(ValueError, match="TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED"):
        _census(inputs, train={items[0]["answer_sha256"]})
    with pytest.raises(ValueError, match="TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED"):
        _census(inputs, train={items[1]["item_text_sha256"]})


def test_answer_drift_two_answers_swapped_refuses(inputs) -> None:
    items = _items_from_contract(inputs["contract"])
    items[0]["answer_payload"], items[1]["answer_payload"] = items[1]["answer_payload"], items[0]["answer_payload"]
    items[0]["answer_sha256"], items[1]["answer_sha256"] = items[1]["answer_sha256"], items[0]["answer_sha256"]
    with pytest.raises(ValueError, match="ANSWER_ITEM_ID_DRIFT_REFUSED:validation_Art_1"):
        _census(inputs, items=items)
    # A recomputed sha over a swapped payload is still drift: identity is the item id, not the digest.
    with pytest.raises(ValueError, match="ANSWER_EMPTY_REFUSED"):
        MODULE.answer_text_object("validation_Art_1", "")


def test_predecessor_and_source_identity_drift_refuse_before_any_custody(inputs, monkeypatch: pytest.MonkeyPatch) -> None:
    items, _ = _census(inputs)
    payloads = MODULE.read_predecessor_text_payloads(inputs["predecessor_raw"], items)
    # Identity is the canonical body under the frozen self sha: a body edit that keeps the claimed
    # self sha is drift (whitespace-only re-serialization is not).
    edited = json.loads(inputs["contract_raw"])
    edited["totality"] = {"expected": 3, "observed": 2, "complete": False}
    with pytest.raises(ValueError, match="PREDECESSOR_CONTRACT_SELF_SHA256_DRIFT_REFUSED"):
        MODULE.build_census(
            items=items, parquet_file_count=2, license_raw=LICENSE_RAW, custody_manifest_raw=CUSTODY_MANIFEST_RAW,
            predecessor_contract_raw=json.dumps(edited).encode(), predecessor_connector_raw=inputs["predecessor_raw"],
            text_payloads=payloads, admitted_train_object_hashes=set(), admitted_heldout_text_hashes=inputs["text_hashes"],
        )
    assert MODULE._verified_predecessor_contract(inputs["contract_raw"] + b" ")["self_sha256"] == inputs["contract"]["self_sha256"]
    short = _items_from_contract(inputs["contract"])[1:]
    with pytest.raises(ValueError, match="PREDECESSOR_CONNECTOR_COVERAGE_REFUSED"):
        MODULE.read_predecessor_text_payloads(inputs["predecessor_raw"], short)
    with pytest.raises(ValueError, match="HELDOUT_TEXT_CATALOG_COVERAGE_REFUSED:2/3"):
        _census(inputs, heldout=set(list(inputs["text_hashes"])[:2]))
    monkeypatch.setattr(MODULE, "LICENSE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="LICENSE_SHA256_DRIFT_REFUSED"):
        _census(inputs)


def test_plan_artifacts_projection_and_contract_bind_totality(inputs) -> None:
    tmp = inputs["tmp"]
    items, census = _census(inputs)
    payloads = MODULE.payloads_from_items(items)
    plan = MODULE.build_admission_plan(census, payloads_by_sha=payloads)
    assert plan["selected_set_sha256"] == census["admitted_object_set_sha256"]
    assert plan["rows"] == [{
        "domain": "text", "source_id": MODULE.ANSWER_SOURCE_ID,
        "catalog_source_id": MODULE.CATALOG_ANSWER_SOURCE_ID, "file_count": 3,
    }]
    out = tmp / "out"
    answer_raw, admission_raw = MODULE.write_admission_artifacts(
        plan=plan, payloads_by_sha=payloads, license_raw=LICENSE_RAW, output_root=out / "custody",
        answer_connector_path=out / "connector-answers.json", admission_receipt_path=out / "admission.json",
        fetched_at="2026-09-05T18:00:00Z",
    )
    connector = json.loads(answer_raw)
    assert connector["source_id"] == MODULE.ANSWER_SOURCE_ID and len(connector["files"]) == 3
    for row in connector["files"]:
        physical = Path(connector["dest_root"]) / row["path"]
        assert sha(physical.read_bytes()) == row["sha256"]
        assert set(json.loads(physical.read_bytes())) == {"answer", "id"}
    admission = json.loads(admission_raw)
    assert admission["answer_connector_receipt_raw_sha256"] == sha(answer_raw)
    with pytest.raises(ValueError, match="NO_OVERWRITE_REFUSED"):
        MODULE.write_admission_artifacts(
            plan=plan, payloads_by_sha=payloads, license_raw=LICENSE_RAW, output_root=out / "custody",
            answer_connector_path=out / "connector-answers.json", admission_receipt_path=out / "admission.json",
            fetched_at="2026-09-05T18:00:00Z",
        )
    spec = json.loads(MODULE.build_projection_spec(
        answer_connector_path=out / "connector-answers.json", answer_connector_raw=answer_raw,
        admission_receipt_path=out / "admission.json", admission_receipt_raw=admission_raw,
        census_path=tmp / "census.json", census_raw=canonical(census), custody_manifest_path=tmp / "custody-manifest.json",
        license_path=tmp / "LICENSE", tokenizer_sha256="a" * 64, created_at_ms=1,
    ))
    assert [row["domain"] for row in spec["rows"]] == ["text"]
    assert spec["rows"][0]["expected_receipt_sha256"] == sha(answer_raw)
    assert spec["rows"][0]["split"] == "heldout"
    assert spec["rows"][0]["source_id"] == MODULE.CATALOG_ANSWER_SOURCE_ID

    contract = MODULE.build_reasoning_contract(
        census, answer_connector_raw=answer_raw, predecessor_connector_raw=inputs["predecessor_raw"],
        predecessor_contract_raw=inputs["contract_raw"],
    )
    assert contract["totality"] == {"expected": 3, "observed": 3, "complete": True}
    assert contract["task"]["id"] == MODULE.TASK_ID
    assert contract["task"]["consumes"] == ["item_text_payload_bytes", "answer_payload_bytes"]
    assert contract["task"]["forbidden_inputs"] == [
        "explanation", "subfield", "topic_difficulty", "img_type", "image_payloads", "prediction_custody",
    ]
    assert contract["source"]["connector_receipt_raw_sha256s"] == sorted([sha(answer_raw), sha(inputs["predecessor_raw"])])
    assert contract["source"]["predecessor_contract_self_sha256"] == inputs["contract"]["self_sha256"]
    for frozen in contract["frozen_items"]:
        assert set(frozen) == {"item_id", "gold_item_sha256", "item_text_object", "answer_object"}
    body = dict(contract)
    assert body.pop("self_sha256") == sha(canonical(body))

    short_raw, _ = _predecessor_contract_raw(drop_one=True)
    with pytest.raises(ValueError, match="PREDECESSOR_CONTRACT_SELF_SHA256_DRIFT_REFUSED"):
        MODULE.build_reasoning_contract(
            census, answer_connector_raw=answer_raw, predecessor_connector_raw=inputs["predecessor_raw"],
            predecessor_contract_raw=short_raw,
        )
    short = json.loads(answer_raw)
    short["files"] = short["files"][1:]
    with pytest.raises(ValueError, match="REASONING_CONNECTOR_COVERAGE_REFUSED"):
        MODULE.build_reasoning_contract(
            census, answer_connector_raw=json.dumps(short).encode(), predecessor_connector_raw=inputs["predecessor_raw"],
            predecessor_contract_raw=inputs["contract_raw"],
        )
    with pytest.raises(ValueError, match="REASONING_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED"):
        MODULE.build_reasoning_contract(
            census, answer_connector_raw=answer_raw, predecessor_connector_raw=inputs["predecessor_raw"],
            predecessor_contract_raw=inputs["contract_raw"], dataset_ids=["dataset:x"],
        )


def test_catalog_binding_requires_both_dataset_memberships(inputs) -> None:
    items, census = _census(inputs)
    payloads = MODULE.payloads_from_items(items)
    answer_raw = MODULE._connector(
        source_id=MODULE.ANSWER_SOURCE_ID,
        files=MODULE.build_admission_plan(census, payloads_by_sha=payloads)["answer_files"],
        dest_root=inputs["tmp"], license_raw=LICENSE_RAW, upstream_url=MODULE.SOURCE_URL,
        fetched_at="2026-09-05T18:00:00Z",
    )
    items_ds, answers_ds = "dataset:heldout:items", "dataset:heldout:answers"
    records = [
        {"kind": "dataset_version", "id": items_ds, "state": "admitted"},
        {"kind": "dataset_version", "id": answers_ds, "state": "admitted"},
    ]
    edges = []
    for index, item in enumerate(census["items"]):
        for label, digest, dataset in (
            ("items", item["item_text_object"]["sha256"], items_ds),
            ("answers", item["answer_object"]["sha256"], answers_ds),
        ):
            membership = f"membership:{label}:{index}"
            records.append({"kind": "membership", "id": membership, "split": "heldout", "admission_state": "admitted", "domain": "text"})
            edges.append({"kind": "version_membership", "from_id": dataset, "to_id": membership})
            edges.append({"kind": "membership_object", "from_id": membership, "to_id": f"sha256:{digest}"})
    export = json.dumps({"records": records, "edges": edges}).encode()
    contract = MODULE.build_reasoning_contract(
        census, answer_connector_raw=answer_raw, predecessor_connector_raw=inputs["predecessor_raw"],
        predecessor_contract_raw=inputs["contract_raw"], catalog_export_raw=export,
        dataset_ids=[answers_ds, items_ds],
    )
    assert contract["catalog_binding"]["membership_count"] == 6
    assert contract["catalog_binding"]["referenced_object_count"] == 6
    assert contract["catalog_binding"]["train_exclusion"] == {
        "executed": True, "admitted_train_membership_count": 0, "admitted_train_object_count": 0, "overlap_count": 0,
    }
    with pytest.raises(ValueError, match="REASONING_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED:3/6"):
        MODULE.build_reasoning_contract(
            census, answer_connector_raw=answer_raw, predecessor_connector_raw=inputs["predecessor_raw"],
            predecessor_contract_raw=inputs["contract_raw"], catalog_export_raw=export,
            dataset_ids=[answers_ds],
        )
    # A planted admitted TRAIN membership over one answer object anywhere in the export refuses the binding.
    planted_answer = census["items"][2]["answer_object"]["sha256"]
    records.append({"kind": "dataset_version", "id": "dataset:train:planted", "state": "admitted"})
    records.append({"kind": "membership", "id": "membership:train:planted", "split": "train", "admission_state": "admitted", "domain": "text"})
    edges.append({"kind": "version_membership", "from_id": "dataset:train:planted", "to_id": "membership:train:planted"})
    edges.append({"kind": "membership_object", "from_id": "membership:train:planted", "to_id": f"sha256:{planted_answer}"})
    with pytest.raises(ValueError, match="REASONING_TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:1:"):
        MODULE.build_reasoning_contract(
            census, answer_connector_raw=answer_raw, predecessor_connector_raw=inputs["predecessor_raw"],
            predecessor_contract_raw=inputs["contract_raw"], catalog_export_raw=json.dumps({"records": records, "edges": edges}).encode(),
            dataset_ids=[answers_ds, items_ds],
        )


def test_item_set_that_is_not_the_predecessor_frozen_set_refuses(inputs) -> None:
    items = _items_from_contract(inputs["contract"])
    payloads = MODULE.read_predecessor_text_payloads(inputs["predecessor_raw"], items)
    items[0]["item_text_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="PREDECESSOR_ITEM_SET_DRIFT_REFUSED"):
        MODULE.build_census(
            items=items, parquet_file_count=2, license_raw=LICENSE_RAW, custody_manifest_raw=CUSTODY_MANIFEST_RAW,
            predecessor_contract_raw=inputs["contract_raw"], predecessor_connector_raw=inputs["predecessor_raw"],
            text_payloads=payloads, admitted_train_object_hashes=set(),
            admitted_heldout_text_hashes=inputs["text_hashes"] | {"f" * 64},
        )


def test_read_answers_projects_only_id_and_answer(inputs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    root = tmp_path / "mmmu"
    by_subject: dict[str, list[dict]] = {}
    for item_id, (subject, question, options, answer) in ITEMS.items():
        by_subject.setdefault(subject, []).append({
            "id": item_id, "question": question, "options": options, "answer": answer,
            "explanation": "never read", "image_1": b"\x89PNG", "subfield": "x",
        })
    for subject, rows in by_subject.items():
        (root / subject).mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(rows), root / subject / "validation-00000-of-00001.parquet")
    items, count = MODULE.read_answers(root, inputs["contract_raw"])
    assert count == 2 and [item["item_id"] for item in items] == sorted(ITEMS)
    assert all(json.loads(item["answer_payload"]) == {"answer": ITEMS[item["item_id"]][3], "id": item["item_id"]} for item in items)
    monkeypatch.setattr(MODULE, "EXPECTED_PARQUET_FILE_COUNT", 3)
    with pytest.raises(ValueError, match="MMMU_PARQUET_FILE_COUNT_REFUSED:2"):
        MODULE.read_answers(root, inputs["contract_raw"])
    monkeypatch.setattr(MODULE, "EXPECTED_PARQUET_FILE_COUNT", 2)
    contract_raw, _ = _predecessor_contract_raw()
    dropped = json.loads(contract_raw)
    extra = dict(dropped["frozen_items"][0])
    extra["item_id"] = "validation_Art_9"
    dropped["frozen_items"].append(extra)
    dropped["totality"] = {"expected": 4, "observed": 4, "complete": True}
    monkeypatch.setattr(MODULE, "EXPECTED_ITEM_COUNT", 4)
    dropped.pop("self_sha256")
    dropped["self_sha256"] = sha(canonical(dropped))
    monkeypatch.setattr(MODULE, "PREDECESSOR_CONTRACT_SELF_SHA256", dropped["self_sha256"])
    with pytest.raises(ValueError, match="ANSWER_ROW_MISSING_REFUSED:validation_Art_9"):
        MODULE.read_answers(root, json.dumps(dropped, sort_keys=True).encode())
