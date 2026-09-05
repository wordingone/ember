# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SCRIPT = ROOT / "src" / "ember" / "governance" / "scripts" / "issue1947_release_row.py"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_refusal_is_named_self_hashed_and_nonzero(tmp_path: Path) -> None:
    receipt = tmp_path / "text-refusal.json"
    missing = [
        "MISSING_CURRENT_PROTECTED_STANDALONE_TEXT_CONTRACT",
        "MISSING_REMAINING_TEXT_ROW_TOTALITY",
    ]
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "refuse",
            "--row-id",
            "E-MATRIX-TEXT-LANGUAGE",
            "--receipt",
            str(receipt),
            *sum((["--missing-predicate", item] for item in missing), []),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 78
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["result"] == "REFUSED"
    assert payload["row_id"] == "E-MATRIX-TEXT-LANGUAGE"
    assert payload["missing_predicates"] == missing
    claimed = payload.pop("self_sha256")
    assert claimed == hashlib.sha256(_canonical(payload)).hexdigest()


def test_refusal_receipt_is_no_overwrite(tmp_path: Path) -> None:
    receipt = tmp_path / "occupied.json"
    receipt.write_text("owned", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "refuse",
            "--row-id",
            "E-MATRIX-IMAGE",
            "--receipt",
            str(receipt),
            "--missing-predicate",
            "MISSING_CURRENT_PROTECTED_IMAGE_ONLY_CONTRACT",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert receipt.read_text(encoding="utf-8") == "owned"


def _write_self_hashed(path: Path, payload: dict) -> None:
    payload = dict(payload)
    payload["self_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_text_adapter_uses_real_bound_inference_row(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source_body = {
        "schema_version": "ember-issue1964-statistics-child-row-carrier-v1",
        "row": {
            "row_id": "candidate-statistics-heldout-0",
            "target_token_id_sha256": "a" * 64,
            "source_text_sha256": "b" * 64,
            "content_sha256": "c" * 64,
            "prefix_token_ids_sha256": "d" * 64,
            "predicted_token_id": 7,
            "exact_id_match": False,
        },
    }
    _write_self_hashed(source, source_body)
    contract = tmp_path / "contract.json"
    _write_self_hashed(contract, {
        "schema_version": "ember-issue1947-protected-text-contract-totality-v1",
        "source_child_receipt": {
            "raw_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "frozen_items": [{
            "item_id": "candidate-statistics-heldout-0",
            "gold_item_sha256": "a" * 64,
            "source_text_sha256": "b" * 64,
            "content_sha256": "c" * 64,
            "prefix_token_ids_sha256": "d" * 64,
        }],
        "totality": {"complete": True},
    })
    result = tmp_path / "row.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "adapt-text", "--contract", str(contract),
         "--source-receipt", str(source), "--result", str(result)],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    assert json.loads(result.read_text(encoding="utf-8")) == {
        "row_id": "E-MATRIX-TEXT-LANGUAGE",
        "items": [{
            "item_id": "candidate-statistics-heldout-0",
            "gold_item_sha256": "a" * 64,
            "prediction": 7,
            "score": 0.0,
        }],
    }


def _write_image_fixture(tmp_path: Path) -> tuple[Path, Path, list[Path]]:
    custody = tmp_path / "objects"
    custody.mkdir()
    files = []
    frozen_items = []
    physical_paths = []
    for index in range(64):
        raw = f"image-{index}".encode()
        digest = hashlib.sha256(raw).hexdigest()
        relative = f"{digest}.png"
        physical = custody / relative
        physical.write_bytes(raw)
        physical_paths.append(physical)
        files.append({"path": relative, "bytes": len(raw), "sha256": digest})
        frozen_items.append({
            "item_id": f"sha256:{digest}",
            "gold_object_sha256": digest,
            "byte_count": len(raw),
            "media_type": "image/png",
        })
    connector = tmp_path / "connector.json"
    connector.write_text(json.dumps({
        "schema": "corpus-connector-receipt-v1",
        "dest_root": str(custody),
        "files": files,
    }), encoding="utf-8")
    contract = tmp_path / "contract.json"
    _write_self_hashed(contract, {
        "schema_version": "ember-issue2105-protected-image-contract-v1",
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": "EXACT_IMAGE_PAYLOAD_SHA256_IDENTITY",
            "consumes": ["image_payload_bytes"],
            "forbidden_inputs": ["mmmu_question", "mmmu_answer", "mmmu_options"],
        },
        "source": {"connector_receipt_raw_sha256": hashlib.sha256(connector.read_bytes()).hexdigest()},
        "frozen_items": frozen_items,
        "totality": {"expected": 64, "observed": 64, "complete": True},
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    })
    return contract, connector, physical_paths


def test_image_adapter_planted_corruption_scores_below_one(tmp_path: Path) -> None:
    contract, connector, paths = _write_image_fixture(tmp_path)
    paths[0].write_bytes(b"corrupted")
    result = tmp_path / "image-row.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "adapt-image", "--contract", str(contract),
         "--source-receipt", str(connector), "--result", str(result)],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    row = json.loads(result.read_text(encoding="utf-8"))
    assert row["result"] == "IMAGE_HELDOUT_ROW_PRODUCED"
    assert row["row_id"] == "E-MATRIX-IMAGE"
    assert row["task_class"] == "adapter_totality"
    assert row["score"] == 63 / 64
    assert sum(item["score"] == 0.0 for item in row["items"]) == 1
    body = dict(row)
    claimed = body.pop("self_sha256")
    assert claimed == hashlib.sha256(_canonical(body)).hexdigest()


def test_image_adapter_missing_payload_writes_refusal_receipt(tmp_path: Path) -> None:
    contract, connector, paths = _write_image_fixture(tmp_path)
    paths[0].unlink()
    result = tmp_path / "image-refusal.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "adapt-image", "--contract", str(contract),
         "--source-receipt", str(connector), "--result", str(result)],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 78
    refusal = json.loads(result.read_text(encoding="utf-8"))
    assert refusal["result"] == "IMAGE_HELDOUT_REFUSED"
    assert refusal["reason"].startswith("IMAGE_PAYLOAD_MISSING_REFUSED:")
    assert refusal["task_class"] == "adapter_totality"
    body = dict(refusal)
    claimed = body.pop("self_sha256")
    assert claimed == hashlib.sha256(_canonical(body)).hexdigest()

def test_image_adapter_row_satisfies_the_release_executor_item_schema(tmp_path: Path) -> None:
    """Live refusal 2026-09-05 (ITEM_SCHEMA_DRIFT:E-MATRIX-IMAGE): the adapter emitted the
    contract's `gold_object_sha256` key while the executor requires `gold_item_sha256`.
    The executor's own validator is the consumer, so it adjudicates the produced row."""
    import importlib.util

    contract, connector, _paths = _write_image_fixture(tmp_path)
    result = tmp_path / "image-row.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "adapt-image", "--contract", str(contract),
         "--source-receipt", str(connector), "--result", str(result)],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    row = json.loads(result.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "issue1947_release_execute", SCRIPT.with_name("issue1947_release_execute.py")
    )
    executor = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(executor)
    validated = executor.validate_row(row, "E-MATRIX-IMAGE")
    assert len(validated["items"]) == 64
    assert all(
        set(item) == {"item_id", "gold_item_sha256", "prediction", "score"}
        for item in validated["items"]
    )



def _write_audio_fixture(tmp_path: Path) -> tuple[Path, Path, list[Path]]:
    custody = tmp_path / "objects"
    custody.mkdir()
    files = []
    frozen_items = []
    physical_paths = []
    for index in range(64):
        raw = f"flac-{index}".encode()
        digest = hashlib.sha256(raw).hexdigest()
        relative = f"{digest}.flac"
        physical = custody / relative
        physical.write_bytes(raw)
        physical_paths.append(physical)
        files.append({"path": relative, "bytes": len(raw), "sha256": digest})
        frozen_items.append({
            "item_id": f"sha256:{digest}",
            "gold_object_sha256": digest,
            "byte_count": len(raw),
            "media_type": "audio/flac",
        })
    connector = tmp_path / "connector.json"
    connector.write_text(json.dumps({
        "schema": "corpus-connector-receipt-v1",
        "dest_root": str(custody),
        "files": files,
    }), encoding="utf-8")
    contract = tmp_path / "contract.json"
    _write_self_hashed(contract, {
        "schema_version": "ember-issue1947-protected-audio-contract-v1",
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": "EXACT_AUDIO_PAYLOAD_SHA256_IDENTITY",
            "consumes": ["audio_payload_bytes"],
            "forbidden_inputs": ["librispeech_transcript", "speaker_metadata", "chapter_metadata"],
        },
        "source": {"connector_receipt_raw_sha256": hashlib.sha256(connector.read_bytes()).hexdigest()},
        "frozen_items": frozen_items,
        "totality": {"expected": 64, "observed": 64, "complete": True},
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    })
    return contract, connector, physical_paths


def test_audio_adapter_planted_corruption_scores_below_one(tmp_path: Path) -> None:
    contract, connector, paths = _write_audio_fixture(tmp_path)
    paths[0].write_bytes(b"corrupted")
    result = tmp_path / "audio-row.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "adapt-audio", "--contract", str(contract),
         "--source-receipt", str(connector), "--result", str(result)],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    row = json.loads(result.read_text(encoding="utf-8"))
    assert row["result"] == "AUDIO_HELDOUT_ROW_PRODUCED"
    assert row["row_id"] == "E-MATRIX-AUDIO"
    assert row["task_class"] == "adapter_totality"
    assert row["score"] == 63 / 64
    assert sum(item["score"] == 0.0 for item in row["items"]) == 1
    body = dict(row)
    claimed = body.pop("self_sha256")
    assert claimed == hashlib.sha256(_canonical(body)).hexdigest()


def test_audio_adapter_missing_payload_writes_refusal_receipt(tmp_path: Path) -> None:
    contract, connector, paths = _write_audio_fixture(tmp_path)
    paths[0].unlink()
    result = tmp_path / "audio-refusal.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "adapt-audio", "--contract", str(contract),
         "--source-receipt", str(connector), "--result", str(result)],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 78
    refusal = json.loads(result.read_text(encoding="utf-8"))
    assert refusal["result"] == "AUDIO_HELDOUT_REFUSED"
    assert refusal["reason"].startswith("AUDIO_PAYLOAD_MISSING_REFUSED:")
    assert refusal["task_class"] == "adapter_totality"
    body = dict(refusal)
    claimed = body.pop("self_sha256")
    assert claimed == hashlib.sha256(_canonical(body)).hexdigest()

def test_audio_adapter_row_satisfies_the_release_executor_item_schema(tmp_path: Path) -> None:
    """Audio row mirror of the executor-schema test: the adapter must emit the
    executor's `gold_item_sha256` key, not the contract's `gold_object_sha256`.
    The executor's own validator is the consumer, so it adjudicates the produced row."""
    import importlib.util

    contract, connector, _paths = _write_audio_fixture(tmp_path)
    result = tmp_path / "audio-row.json"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "adapt-audio", "--contract", str(contract),
         "--source-receipt", str(connector), "--result", str(result)],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    row = json.loads(result.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "issue1947_release_execute", SCRIPT.with_name("issue1947_release_execute.py")
    )
    executor = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(executor)
    validated = executor.validate_row(row, "E-MATRIX-AUDIO")
    assert len(validated["items"]) == 64
    assert all(
        set(item) == {"item_id", "gold_item_sha256", "prediction", "score"}
        for item in validated["items"]
    )


IMAGE_TEXT_ITEMS = 847


def _image_text_canonical(item_id: str, extra: dict | None = None) -> bytes:
    payload = {"id": item_id, "question": f"What is <image 1> in {item_id}?", "options": ["a", "b", "c"]}
    if extra:
        payload.update(extra)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _write_image_text_fixture(tmp_path: Path) -> tuple[Path, list[Path], dict[str, Path]]:
    """847 items: one image object each (the first item shares its image with the
    second), one canonical item-text object each; images split across a carrier
    connector and a predecessor connector exactly as the live contract binds them."""

    carrier_root = tmp_path / "carrier"
    predecessor_root = tmp_path / "predecessor"
    text_root = tmp_path / "items"
    for root in (carrier_root, predecessor_root, text_root):
        root.mkdir()
    carrier_files, predecessor_files, text_files, frozen_items = [], [], [], []
    physical: dict[str, Path] = {}
    for index in range(IMAGE_TEXT_ITEMS):
        item_id = f"validation_Fixture_{index}"
        image_raw = b"png-shared" if index < 2 else f"png-{index}".encode()
        image_digest = hashlib.sha256(image_raw).hexdigest()
        text_raw = _image_text_canonical(item_id)
        text_digest = hashlib.sha256(text_raw).hexdigest()
        if image_digest not in physical:
            if index == 0:
                target_root, target_files = predecessor_root, predecessor_files
            else:
                target_root, target_files = carrier_root, carrier_files
            image_path = target_root / f"{image_digest}.png"
            image_path.write_bytes(image_raw)
            physical[image_digest] = image_path
            target_files.append({"path": image_path.name, "bytes": len(image_raw), "sha256": image_digest})
        text_path = text_root / f"{text_digest}.json"
        text_path.write_bytes(text_raw)
        physical[text_digest] = text_path
        text_files.append({"path": text_path.name, "bytes": len(text_raw), "sha256": text_digest})
        frozen_items.append({
            "item_id": item_id,
            "gold_item_sha256": hashlib.sha256(image_raw + text_raw).hexdigest(),
            "image_objects": [{"sha256": image_digest, "byte_count": len(image_raw), "media_type": "image/png"}],
            "item_text_object": {"sha256": text_digest, "byte_count": len(text_raw), "media_type": "application/json"},
        })
    receipts = []
    for name, root, files, source_id in (
        ("connector-images.json", carrier_root, carrier_files, "mmmu-validation-heldout-image-text-images"),
        ("connector-items.json", text_root, text_files, "mmmu-validation-heldout-image-text-items"),
        ("connector-predecessor.json", predecessor_root, predecessor_files, "mmmu-validation-heldout-image-64"),
    ):
        receipt = tmp_path / name
        receipt.write_text(json.dumps({
            "schema": "corpus-connector-receipt-v1",
            "source_id": source_id,
            "dest_root": str(root),
            "files": files,
        }), encoding="utf-8")
        receipts.append(receipt)
    contract = tmp_path / "contract.json"
    _write_self_hashed(contract, {
        "schema_version": "ember-protected-image-text-contract-v1",
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": "EXACT_IMAGE_TEXT_PAYLOAD_SHA256_IDENTITY",
            "consumes": ["image_payload_bytes", "item_text_payload_bytes"],
            "forbidden_inputs": ["mmmu_answer_dictionary", "prediction_custody"],
        },
        "source": {
            "connector_receipt_raw_sha256s": sorted(
                hashlib.sha256(receipt.read_bytes()).hexdigest() for receipt in receipts
            ),
        },
        "frozen_items": frozen_items,
        "totality": {"expected": IMAGE_TEXT_ITEMS, "observed": IMAGE_TEXT_ITEMS, "complete": True},
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    })
    return contract, receipts, physical


def _run_image_text(contract: Path, receipts: list[Path], result: Path) -> subprocess.CompletedProcess:
    command = [sys.executable, str(SCRIPT), "adapt-image-text", "--contract", str(contract)]
    for receipt in receipts:
        command += ["--source-receipt", str(receipt)]
    command += ["--result", str(result)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def test_image_text_adapter_planted_corruption_scores_below_one(tmp_path: Path) -> None:
    contract, receipts, physical = _write_image_text_fixture(tmp_path)
    corrupted = hashlib.sha256(b"png-5").hexdigest()
    physical[corrupted].write_bytes(b"corrupted")
    result = tmp_path / "row.json"
    completed = _run_image_text(contract, receipts, result)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    row = json.loads(result.read_text(encoding="utf-8"))
    assert row["result"] == "IMAGE_TEXT_HELDOUT_ROW_PRODUCED"
    assert row["row_id"] == "E-MATRIX-IMAGE-TEXT"
    assert row["task_class"] == "adapter_totality"
    assert len(row["items"]) == IMAGE_TEXT_ITEMS
    assert row["score"] == (IMAGE_TEXT_ITEMS - 1) / IMAGE_TEXT_ITEMS
    assert [item["item_id"] for item in row["items"] if item["score"] == 0.0] == ["validation_Fixture_5"]
    assert len(row["connector_receipt_raw_sha256s"]) == 3
    body = dict(row)
    claimed = body.pop("self_sha256")
    assert claimed == hashlib.sha256(_canonical(body)).hexdigest()


def test_image_text_adapter_missing_payload_and_missing_receipt_refuse(tmp_path: Path) -> None:
    contract, receipts, physical = _write_image_text_fixture(tmp_path)
    physical[hashlib.sha256(b"png-shared").hexdigest()].unlink()
    result = tmp_path / "refusal.json"
    completed = _run_image_text(contract, receipts, result)
    assert completed.returncode == 78
    refusal = json.loads(result.read_text(encoding="utf-8"))
    assert refusal["result"] == "IMAGE_TEXT_HELDOUT_REFUSED"
    assert refusal["reason"].startswith("IMAGE_TEXT_PAYLOAD_MISSING_REFUSED:validation_Fixture_0:")
    body = dict(refusal)
    claimed = body.pop("self_sha256")
    assert claimed == hashlib.sha256(_canonical(body)).hexdigest()
    # Supplying only two of the three bound receipts refuses before any item is scored.
    completed = _run_image_text(contract, receipts[:2], tmp_path / "refusal-2.json")
    assert completed.returncode == 78
    refusal = json.loads((tmp_path / "refusal-2.json").read_text(encoding="utf-8"))
    assert refusal["reason"] == "IMAGE_TEXT_SOURCE_RECEIPT_SET_INCOMPLETE_REFUSED"


def test_image_text_adapter_refuses_forbidden_inputs(tmp_path: Path) -> None:
    """Deliberate reds: a prediction custody receipt supplied as a source, and an
    item-text object that carries the answer, both refuse as forbidden inputs."""

    contract, receipts, physical = _write_image_text_fixture(tmp_path)
    predictions = tmp_path / "predictions.json"
    predictions.write_text(json.dumps({
        "schema_version": "ember-restart-mmmu-predictions-v1",
        "dest_root": str(tmp_path),
        "files": [],
    }), encoding="utf-8")
    completed = _run_image_text(contract, receipts[:2] + [predictions], tmp_path / "refusal-a.json")
    assert completed.returncode == 78
    refusal = json.loads((tmp_path / "refusal-a.json").read_text(encoding="utf-8"))
    assert refusal["reason"].startswith("IMAGE_TEXT_FORBIDDEN_INPUT_REFUSED:source_schema:")

    item_id = "validation_Fixture_3"
    clean = _image_text_canonical(item_id)
    with_answer = _image_text_canonical(item_id, {"answer": "B"})
    text_path = physical[hashlib.sha256(clean).hexdigest()]
    # Keep the receipt's byte count honest so the refusal is the shape check, not a size check.
    padded = with_answer[: len(clean)] if len(with_answer) >= len(clean) else with_answer.ljust(len(clean))
    text_path.write_bytes(padded)
    completed = _run_image_text(contract, receipts, tmp_path / "refusal-b.json")
    assert completed.returncode == 78
    refusal = json.loads((tmp_path / "refusal-b.json").read_text(encoding="utf-8"))
    assert refusal["reason"].startswith("IMAGE_TEXT_FORBIDDEN_INPUT_REFUSED:item_text_")
    assert item_id in refusal["reason"]


def test_image_text_adapter_row_satisfies_the_release_executor_item_schema(tmp_path: Path) -> None:
    import importlib.util

    contract, receipts, _physical = _write_image_text_fixture(tmp_path)
    result = tmp_path / "row.json"
    completed = _run_image_text(contract, receipts, result)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    row = json.loads(result.read_text(encoding="utf-8"))
    assert row["score"] == 1.0
    spec = importlib.util.spec_from_file_location(
        "issue1947_release_execute", SCRIPT.with_name("issue1947_release_execute.py")
    )
    executor = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(executor)
    validated = executor.validate_row(row, "E-MATRIX-IMAGE-TEXT")
    assert len(validated["items"]) == IMAGE_TEXT_ITEMS
    assert all(
        set(item) == {"item_id", "gold_item_sha256", "prediction", "score"}
        for item in validated["items"]
    )
