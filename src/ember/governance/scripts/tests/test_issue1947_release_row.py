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


AUDIO_TEXT_ITEMS = 64


def _audio_text_canonical(utterance_id: str, transcript: str, extra: dict | None = None) -> bytes:
    payload = {"transcript": transcript, "utterance_id": utterance_id}
    if extra:
        payload.update(extra)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _write_audio_text_fixture(tmp_path: Path) -> tuple[Path, list[Path], dict[str, Path]]:
    """64 items: one admitted audio object (predecessor connector) and one canonical
    transcript object (carrier connector) each, bound exactly as the live contract binds them."""

    audio_root = tmp_path / "audio"
    text_root = tmp_path / "transcripts"
    audio_root.mkdir()
    text_root.mkdir()
    audio_files, text_files, frozen_items = [], [], []
    physical: dict[str, Path] = {}
    for index in range(AUDIO_TEXT_ITEMS):
        item_id = f"1995-1837-{index:04d}"
        audio_raw = f"flac-{index}".encode()
        audio_digest = hashlib.sha256(audio_raw).hexdigest()
        text_raw = _audio_text_canonical(item_id, f"LINE {index} OF THE FIXTURE")
        text_digest = hashlib.sha256(text_raw).hexdigest()
        audio_path = audio_root / f"{audio_digest}.flac"
        audio_path.write_bytes(audio_raw)
        text_path = text_root / f"{text_digest}.json"
        text_path.write_bytes(text_raw)
        physical[audio_digest] = audio_path
        physical[text_digest] = text_path
        audio_files.append({"path": audio_path.name, "bytes": len(audio_raw), "sha256": audio_digest})
        text_files.append({"path": text_path.name, "bytes": len(text_raw), "sha256": text_digest})
        frozen_items.append({
            "item_id": item_id,
            "gold_item_sha256": hashlib.sha256(audio_raw + text_raw).hexdigest(),
            "audio_object": {"sha256": audio_digest, "byte_count": len(audio_raw), "media_type": "audio/flac"},
            "item_text_object": {"sha256": text_digest, "byte_count": len(text_raw), "media_type": "application/json"},
        })
    receipts = []
    for name, root, files, source_id in (
        ("connector-transcripts.json", text_root, text_files, "librispeech-test-clean-heldout-audio-text-transcripts"),
        ("connector-predecessor-audio.json", audio_root, audio_files, "librispeech-test-clean-heldout-audio-64"),
    ):
        receipt = tmp_path / name
        receipt.write_text(json.dumps({
            "schema": "corpus-connector-receipt-v1",
            "source_id": source_id,
            "dest_root": str(root),
            "files": files,
        }), encoding="utf-8")
        receipts.append(receipt)
    contract = tmp_path / "audio-text-contract.json"
    _write_self_hashed(contract, {
        "schema_version": "ember-issue1947-protected-audio-text-contract-v1",
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": "EXACT_AUDIO_TEXT_PAIR_IDENTITY",
            "consumes": ["audio_payload_bytes", "transcript_text_payload_bytes"],
            "forbidden_inputs": ["speaker_metadata", "chapter_metadata", "prediction_custody"],
        },
        "source": {
            "connector_receipt_raw_sha256s": sorted(
                hashlib.sha256(receipt.read_bytes()).hexdigest() for receipt in receipts
            ),
        },
        "frozen_items": frozen_items,
        "totality": {"expected": AUDIO_TEXT_ITEMS, "observed": AUDIO_TEXT_ITEMS, "complete": True},
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    })
    return contract, receipts, physical


def _run_audio_text(contract: Path, receipts: list[Path], result: Path) -> subprocess.CompletedProcess:
    command = [sys.executable, str(SCRIPT), "adapt-audio-text", "--contract", str(contract)]
    for receipt in receipts:
        command += ["--source-receipt", str(receipt)]
    command += ["--result", str(result)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def test_audio_text_adapter_produces_the_pair_identity_row(tmp_path: Path) -> None:
    contract, receipts, _physical = _write_audio_text_fixture(tmp_path)
    result = tmp_path / "row.json"
    completed = _run_audio_text(contract, receipts, result)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    row = json.loads(result.read_text(encoding="utf-8"))
    assert row["result"] == "AUDIO_TEXT_HELDOUT_ROW_PRODUCED"
    assert row["row_id"] == "E-MATRIX-AUDIO-TEXT"
    assert row["task"] == "EXACT_AUDIO_TEXT_PAIR_IDENTITY"
    assert row["score"] == 1.0 and len(row["items"]) == AUDIO_TEXT_ITEMS
    assert row["connector_receipt_raw_sha256s"] == sorted(
        hashlib.sha256(receipt.read_bytes()).hexdigest() for receipt in receipts
    )
    body = dict(row)
    assert body.pop("self_sha256") == hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_audio_text_adapter_planted_corruption_scores_below_one(tmp_path: Path) -> None:
    contract, receipts, physical = _write_audio_text_fixture(tmp_path)
    contract_body = json.loads(contract.read_text(encoding="utf-8"))
    victim = contract_body["frozen_items"][7]
    # Same byte count, different bytes: the receipt row still matches, the pair identity does not.
    text_path = physical[victim["item_text_object"]["sha256"]]
    corrupted = _audio_text_canonical(victim["item_id"], "LINE 7 OF THE FIXTURF")
    assert len(corrupted) == victim["item_text_object"]["byte_count"]
    text_path.write_bytes(corrupted)
    result = tmp_path / "row.json"
    completed = _run_audio_text(contract, receipts, result)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    row = json.loads(result.read_text(encoding="utf-8"))
    assert abs(row["score"] - (AUDIO_TEXT_ITEMS - 1) / AUDIO_TEXT_ITEMS) < 1e-12
    assert [item["item_id"] for item in row["items"] if item["score"] == 0.0] == [victim["item_id"]]


def test_audio_text_adapter_refuses_forbidden_inputs(tmp_path: Path) -> None:
    contract, receipts, physical = _write_audio_text_fixture(tmp_path)
    contract_body = json.loads(contract.read_text(encoding="utf-8"))
    victim = contract_body["frozen_items"][3]
    # A transcript object that smuggles speaker metadata is a forbidden input, not a scored miss.
    text_path = physical[victim["item_text_object"]["sha256"]]
    smuggled = _audio_text_canonical(victim["item_id"], "LINE 3 OF THE FIXTURE", {"speaker_id": "1995"})
    text_path.write_bytes(smuggled)
    receipt_body = json.loads(receipts[0].read_text(encoding="utf-8"))
    for row in receipt_body["files"]:
        if row["sha256"] == victim["item_text_object"]["sha256"]:
            row["bytes"] = len(smuggled)
    receipts[0].write_text(json.dumps(receipt_body), encoding="utf-8")
    rebound = json.loads(contract.read_text(encoding="utf-8"))
    rebound["source"]["connector_receipt_raw_sha256s"] = sorted(
        hashlib.sha256(receipt.read_bytes()).hexdigest() for receipt in receipts
    )
    for item in rebound["frozen_items"]:
        if item["item_id"] == victim["item_id"]:
            item["item_text_object"]["byte_count"] = len(smuggled)
    rebound.pop("self_sha256")
    _write_self_hashed(tmp_path / "rebound.json", rebound)
    result = tmp_path / "row-forbidden.json"
    completed = _run_audio_text(tmp_path / "rebound.json", receipts, result)
    assert completed.returncode == 78
    refusal = json.loads(result.read_text(encoding="utf-8"))
    assert refusal["result"] == "AUDIO_TEXT_HELDOUT_REFUSED"
    assert refusal["reason"].startswith(f"AUDIO_TEXT_FORBIDDEN_INPUT_REFUSED:item_text_shape:{victim['item_id']}")

    # A prediction-custody receipt supplied as a source refuses before any byte is read.
    (tmp_path / "second").mkdir()
    contract2, receipts2, _ = _write_audio_text_fixture(tmp_path / "second")
    custody = tmp_path / "second" / "prediction-custody.json"
    custody.write_text(json.dumps({"schema_version": "ember-prediction-custody-v1", "rows": []}), encoding="utf-8")
    result2 = tmp_path / "row-custody.json"
    completed = _run_audio_text(contract2, [receipts2[0], custody], result2)
    assert completed.returncode == 78
    refusal = json.loads(result2.read_text(encoding="utf-8"))
    assert refusal["reason"] == "AUDIO_TEXT_FORBIDDEN_INPUT_REFUSED:source_schema:ember-prediction-custody-v1"

    # The bound receipt set must be supplied in full.
    result3 = tmp_path / "row-incomplete.json"
    completed = _run_audio_text(contract2, [receipts2[0]], result3)
    assert completed.returncode == 78
    assert json.loads(result3.read_text(encoding="utf-8"))["reason"] == "AUDIO_TEXT_SOURCE_RECEIPT_SET_INCOMPLETE_REFUSED"


def test_audio_text_adapter_row_satisfies_the_release_executor_item_schema(tmp_path: Path) -> None:
    import importlib.util

    contract, receipts, _ = _write_audio_text_fixture(tmp_path)
    result = tmp_path / "row.json"
    assert _run_audio_text(contract, receipts, result).returncode == 0
    row = json.loads(result.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "issue1947_release_execute", SCRIPT.parent / "issue1947_release_execute.py"
    )
    executor = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(executor)
    validated = executor.validate_row(row, "E-MATRIX-AUDIO-TEXT")
    assert validated is row


def _write_image_audio_text_fixture(tmp_path: Path) -> tuple[Path, list[Path], dict[str, Path]]:
    """64 items: one admitted image object (image connector), one audio object (audio connector) and
    one canonical transcript object (transcript connector) each, bound as the #2145 contract binds them."""

    image_root = tmp_path / "images"
    audio_root = tmp_path / "audio"
    text_root = tmp_path / "transcripts"
    for root in (image_root, audio_root, text_root):
        root.mkdir()
    image_files, audio_files, text_files, frozen_items = [], [], [], []
    physical: dict[str, Path] = {}
    for index in range(AUDIO_TEXT_ITEMS):
        item_id = f"1995-1837-{index:04d}"
        image_raw = f"png-{index}".encode()
        audio_raw = f"flac-{index}".encode()
        text_raw = _audio_text_canonical(item_id, f"LINE {index} OF THE FIXTURE")
        digests = [hashlib.sha256(raw).hexdigest() for raw in (image_raw, audio_raw, text_raw)]
        paths = [image_root / f"{digests[0]}.png", audio_root / f"{digests[1]}.flac", text_root / f"{digests[2]}.json"]
        for raw, digest, path, files in zip(
            (image_raw, audio_raw, text_raw), digests, paths, (image_files, audio_files, text_files)
        ):
            path.write_bytes(raw)
            physical[digest] = path
            files.append({"path": path.name, "bytes": len(raw), "sha256": digest})
        frozen_items.append({
            "item_id": item_id,
            "image_text_item_id": f"validation_Art_{index}",
            "gold_item_sha256": hashlib.sha256(image_raw + audio_raw + text_raw).hexdigest(),
            "image_object": {"sha256": digests[0], "byte_count": len(image_raw), "media_type": "image/png"},
            "audio_object": {"sha256": digests[1], "byte_count": len(audio_raw), "media_type": "audio/flac"},
            "item_text_object": {"sha256": digests[2], "byte_count": len(text_raw), "media_type": "application/json"},
        })
    receipts = []
    for name, root, files, source_id in (
        ("connector-images.json", image_root, image_files, "mmmu-validation-heldout-images"),
        ("connector-audio.json", audio_root, audio_files, "librispeech-test-clean-heldout-audio-64"),
        ("connector-transcripts.json", text_root, text_files, "librispeech-test-clean-heldout-audio-text-transcripts"),
    ):
        receipt = tmp_path / name
        receipt.write_text(json.dumps({
            "schema": "corpus-connector-receipt-v1",
            "source_id": source_id,
            "dest_root": str(root),
            "files": files,
        }), encoding="utf-8")
        receipts.append(receipt)
    contract = tmp_path / "image-audio-text-contract.json"
    _write_self_hashed(contract, {
        "schema_version": "ember-issue1947-protected-image-audio-text-contract-v1",
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": "EXACT_IMAGE_AUDIO_TEXT_TRIPLE_IDENTITY",
            "consumes": ["image_payload_bytes", "audio_payload_bytes", "transcript_text_payload_bytes"],
            "forbidden_inputs": ["speaker_metadata", "chapter_metadata", "mmmu_answer_dictionary", "prediction_custody"],
        },
        "source": {
            "connector_receipt_raw_sha256s": sorted(
                hashlib.sha256(receipt.read_bytes()).hexdigest() for receipt in receipts
            ),
        },
        "frozen_items": frozen_items,
        "totality": {"expected": AUDIO_TEXT_ITEMS, "observed": AUDIO_TEXT_ITEMS, "complete": True},
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    })
    return contract, receipts, physical


def _run_image_audio_text(contract: Path, receipts: list[Path], result: Path) -> subprocess.CompletedProcess:
    command = [sys.executable, str(SCRIPT), "adapt-image-audio-text", "--contract", str(contract)]
    for receipt in receipts:
        command += ["--source-receipt", str(receipt)]
    command += ["--result", str(result)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def test_image_audio_text_adapter_produces_the_triple_identity_row(tmp_path: Path) -> None:
    contract, receipts, _physical = _write_image_audio_text_fixture(tmp_path)
    result = tmp_path / "row.json"
    completed = _run_image_audio_text(contract, receipts, result)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    row = json.loads(result.read_text(encoding="utf-8"))
    assert row["result"] == "IMAGE_AUDIO_TEXT_HELDOUT_ROW_PRODUCED"
    assert row["row_id"] == "E-MATRIX-IMAGE-AUDIO-TEXT"
    assert row["task"] == "EXACT_IMAGE_AUDIO_TEXT_TRIPLE_IDENTITY"
    assert row["score"] == 1.0 and len(row["items"]) == AUDIO_TEXT_ITEMS
    assert row["connector_receipt_raw_sha256s"] == sorted(
        hashlib.sha256(receipt.read_bytes()).hexdigest() for receipt in receipts
    )
    body = dict(row)
    assert body.pop("self_sha256") == hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_image_audio_text_adapter_planted_image_corruption_scores_below_one(tmp_path: Path) -> None:
    contract, receipts, physical = _write_image_audio_text_fixture(tmp_path)
    contract_body = json.loads(contract.read_text(encoding="utf-8"))
    victim = contract_body["frozen_items"][9]
    # Same byte count, different bytes: the receipt row still matches, the triple identity does not.
    image_path = physical[victim["image_object"]["sha256"]]
    corrupted = b"png-X"
    assert len(corrupted) == victim["image_object"]["byte_count"]
    image_path.write_bytes(corrupted)
    result = tmp_path / "row.json"
    completed = _run_image_audio_text(contract, receipts, result)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    row = json.loads(result.read_text(encoding="utf-8"))
    assert abs(row["score"] - (AUDIO_TEXT_ITEMS - 1) / AUDIO_TEXT_ITEMS) < 1e-12
    assert [item["item_id"] for item in row["items"] if item["score"] == 0.0] == [victim["item_id"]]


def test_image_audio_text_adapter_refuses_forbidden_inputs(tmp_path: Path) -> None:
    contract, receipts, physical = _write_image_audio_text_fixture(tmp_path)
    contract_body = json.loads(contract.read_text(encoding="utf-8"))
    victim = contract_body["frozen_items"][3]
    # A transcript object that smuggles the MMMU answer dictionary is a forbidden input, not a scored miss.
    text_path = physical[victim["item_text_object"]["sha256"]]
    smuggled = _audio_text_canonical(victim["item_id"], "LINE 3 OF THE FIXTURE", {"answer": "B"})
    text_path.write_bytes(smuggled)
    receipt_body = json.loads(receipts[2].read_text(encoding="utf-8"))
    for row in receipt_body["files"]:
        if row["sha256"] == victim["item_text_object"]["sha256"]:
            row["bytes"] = len(smuggled)
    receipts[2].write_text(json.dumps(receipt_body), encoding="utf-8")
    rebound = json.loads(contract.read_text(encoding="utf-8"))
    rebound["source"]["connector_receipt_raw_sha256s"] = sorted(
        hashlib.sha256(receipt.read_bytes()).hexdigest() for receipt in receipts
    )
    for item in rebound["frozen_items"]:
        if item["item_id"] == victim["item_id"]:
            item["item_text_object"]["byte_count"] = len(smuggled)
    rebound.pop("self_sha256")
    _write_self_hashed(tmp_path / "rebound.json", rebound)
    result = tmp_path / "row-forbidden.json"
    completed = _run_image_audio_text(tmp_path / "rebound.json", receipts, result)
    assert completed.returncode == 78
    refusal = json.loads(result.read_text(encoding="utf-8"))
    assert refusal["result"] == "IMAGE_AUDIO_TEXT_HELDOUT_REFUSED"
    assert refusal["reason"].startswith(
        f"IMAGE_AUDIO_TEXT_FORBIDDEN_INPUT_REFUSED:item_text_shape:{victim['item_id']}"
    )

    # A prediction-custody receipt supplied as a source refuses before any byte is read.
    (tmp_path / "second").mkdir()
    contract2, receipts2, _ = _write_image_audio_text_fixture(tmp_path / "second")
    custody = tmp_path / "second" / "prediction-custody.json"
    custody.write_text(json.dumps({"schema_version": "ember-prediction-custody-v1", "rows": []}), encoding="utf-8")
    result2 = tmp_path / "row-custody.json"
    completed = _run_image_audio_text(contract2, [receipts2[0], receipts2[1], custody], result2)
    assert completed.returncode == 78
    refusal = json.loads(result2.read_text(encoding="utf-8"))
    assert refusal["reason"] == "IMAGE_AUDIO_TEXT_FORBIDDEN_INPUT_REFUSED:source_schema:ember-prediction-custody-v1"

    # The bound receipt set must be supplied in full (three receipts, not two).
    result3 = tmp_path / "row-incomplete.json"
    completed = _run_image_audio_text(contract2, receipts2[:2], result3)
    assert completed.returncode == 78
    assert (
        json.loads(result3.read_text(encoding="utf-8"))["reason"]
        == "IMAGE_AUDIO_TEXT_SOURCE_RECEIPT_SET_INCOMPLETE_REFUSED"
    )


def test_image_audio_text_adapter_row_satisfies_the_release_executor_item_schema(tmp_path: Path) -> None:
    import importlib.util

    contract, receipts, _ = _write_image_audio_text_fixture(tmp_path)
    result = tmp_path / "row.json"
    assert _run_image_audio_text(contract, receipts, result).returncode == 0
    row = json.loads(result.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "issue1947_release_execute", SCRIPT.parent / "issue1947_release_execute.py"
    )
    executor = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(executor)
    validated = executor.validate_row(row, "E-MATRIX-IMAGE-AUDIO-TEXT")
    assert validated is row


REASONING_ITEMS = 847


def _reasoning_answer_canonical(item_id: str, answer: str, extra: dict | None = None) -> bytes:
    payload = {"answer": answer, "id": item_id}
    if extra:
        payload.update(extra)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _write_reasoning_fixture(tmp_path: Path) -> tuple[Path, list[Path], dict[str, Path]]:
    """847 items: one admitted item-text object ({id, question, options}, the predecessor connector)
    and one canonical answer object ({answer, id}, the carrier connector) each, bound as the #2148
    contract binds them."""

    items_root = tmp_path / "items"
    answers_root = tmp_path / "answers"
    items_root.mkdir()
    answers_root.mkdir()
    item_files, answer_files, frozen_items = [], [], []
    physical: dict[str, Path] = {}
    for index in range(REASONING_ITEMS):
        item_id = f"validation_Subject_{index}"
        text_raw = _image_text_canonical(item_id)
        text_digest = hashlib.sha256(text_raw).hexdigest()
        answer_raw = _reasoning_answer_canonical(item_id, "ABCD"[index % 4])
        answer_digest = hashlib.sha256(answer_raw).hexdigest()
        text_path = items_root / f"{text_digest}.json"
        text_path.write_bytes(text_raw)
        answer_path = answers_root / f"{answer_digest}.json"
        answer_path.write_bytes(answer_raw)
        physical[text_digest] = text_path
        physical[answer_digest] = answer_path
        item_files.append({"path": text_path.name, "bytes": len(text_raw), "sha256": text_digest})
        answer_files.append({"path": answer_path.name, "bytes": len(answer_raw), "sha256": answer_digest})
        frozen_items.append({
            "item_id": item_id,
            "gold_item_sha256": hashlib.sha256(text_raw + answer_raw).hexdigest(),
            "item_text_object": {"sha256": text_digest, "byte_count": len(text_raw), "media_type": "application/json"},
            "answer_object": {"sha256": answer_digest, "byte_count": len(answer_raw), "media_type": "application/json"},
        })
    receipts = []
    for name, root, files, source_id in (
        ("connector-answers.json", answers_root, answer_files, "mmmu-validation-heldout-reasoning-answers"),
        ("connector-predecessor-items.json", items_root, item_files, "mmmu-validation-heldout-image-text-items"),
    ):
        receipt = tmp_path / name
        receipt.write_text(json.dumps({
            "schema": "corpus-connector-receipt-v1",
            "source_id": source_id,
            "dest_root": str(root),
            "files": files,
        }), encoding="utf-8")
        receipts.append(receipt)
    contract = tmp_path / "reasoning-contract.json"
    _write_self_hashed(contract, {
        "schema_version": "ember-issue1947-protected-reasoning-contract-v1",
        "result": "PASS",
        "task_class": "adapter_totality",
        "task": {
            "id": "EXACT_REASONING_ITEM_IDENTITY",
            "consumes": ["item_text_payload_bytes", "answer_payload_bytes"],
            "forbidden_inputs": ["explanation", "subfield", "topic_difficulty", "img_type", "image_payloads", "prediction_custody"],
        },
        "source": {
            "connector_receipt_raw_sha256s": sorted(
                hashlib.sha256(receipt.read_bytes()).hexdigest() for receipt in receipts
            ),
        },
        "frozen_items": frozen_items,
        "totality": {"expected": REASONING_ITEMS, "observed": REASONING_ITEMS, "complete": True},
        "claim_boundary": "ADAPTER TOTALITY SCORE ONLY; NOT CAPABILITY, THRESHOLD, RELEASE, CAMPAIGN, OR GOAL CREDIT",
    })
    return contract, receipts, physical


def _run_reasoning(contract: Path, receipts: list[Path], result: Path) -> subprocess.CompletedProcess:
    command = [sys.executable, str(SCRIPT), "adapt-reasoning", "--contract", str(contract)]
    for receipt in receipts:
        command += ["--source-receipt", str(receipt)]
    command += ["--result", str(result)]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def test_reasoning_adapter_produces_the_item_identity_row(tmp_path: Path) -> None:
    contract, receipts, _physical = _write_reasoning_fixture(tmp_path)
    result = tmp_path / "row.json"
    completed = _run_reasoning(contract, receipts, result)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    row = json.loads(result.read_text(encoding="utf-8"))
    assert row["result"] == "REASONING_HELDOUT_ROW_PRODUCED"
    assert row["row_id"] == "E-MATRIX-REASONING"
    assert row["task"] == "EXACT_REASONING_ITEM_IDENTITY"
    assert row["score"] == 1.0 and len(row["items"]) == REASONING_ITEMS
    assert row["connector_receipt_raw_sha256s"] == sorted(
        hashlib.sha256(receipt.read_bytes()).hexdigest() for receipt in receipts
    )
    body = dict(row)
    assert body.pop("self_sha256") == hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_reasoning_adapter_planted_answer_corruption_scores_846_of_847(tmp_path: Path) -> None:
    contract, receipts, physical = _write_reasoning_fixture(tmp_path)
    contract_body = json.loads(contract.read_text(encoding="utf-8"))
    victim = contract_body["frozen_items"][11]
    # Same byte count, different answer letter: the receipt row still matches, the item identity does not.
    answer_path = physical[victim["answer_object"]["sha256"]]
    corrupted = _reasoning_answer_canonical(victim["item_id"], "E")
    assert len(corrupted) == victim["answer_object"]["byte_count"]
    answer_path.write_bytes(corrupted)
    result = tmp_path / "row.json"
    completed = _run_reasoning(contract, receipts, result)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    row = json.loads(result.read_text(encoding="utf-8"))
    assert abs(row["score"] - (REASONING_ITEMS - 1) / REASONING_ITEMS) < 1e-12
    assert [item["item_id"] for item in row["items"] if item["score"] == 0.0] == [victim["item_id"]]


def test_reasoning_adapter_refuses_forbidden_inputs(tmp_path: Path) -> None:
    contract, receipts, physical = _write_reasoning_fixture(tmp_path)
    contract_body = json.loads(contract.read_text(encoding="utf-8"))
    victim = contract_body["frozen_items"][5]
    # An answer object that smuggles the explanation is a forbidden input, not a scored miss.
    answer_path = physical[victim["answer_object"]["sha256"]]
    smuggled = _reasoning_answer_canonical(victim["item_id"], "B", {"explanation": "because"})
    answer_path.write_bytes(smuggled)
    receipt_body = json.loads(receipts[0].read_text(encoding="utf-8"))
    for row in receipt_body["files"]:
        if row["sha256"] == victim["answer_object"]["sha256"]:
            row["bytes"] = len(smuggled)
    receipts[0].write_text(json.dumps(receipt_body), encoding="utf-8")
    rebound = json.loads(contract.read_text(encoding="utf-8"))
    rebound["source"]["connector_receipt_raw_sha256s"] = sorted(
        hashlib.sha256(receipt.read_bytes()).hexdigest() for receipt in receipts
    )
    for item in rebound["frozen_items"]:
        if item["item_id"] == victim["item_id"]:
            item["answer_object"]["byte_count"] = len(smuggled)
    rebound.pop("self_sha256")
    _write_self_hashed(tmp_path / "rebound.json", rebound)
    result = tmp_path / "row-forbidden.json"
    completed = _run_reasoning(tmp_path / "rebound.json", receipts, result)
    assert completed.returncode == 78
    refusal = json.loads(result.read_text(encoding="utf-8"))
    assert refusal["result"] == "REASONING_HELDOUT_REFUSED"
    assert refusal["reason"].startswith(f"REASONING_FORBIDDEN_INPUT_REFUSED:answer_shape:{victim['item_id']}")

    # An answer object carrying another item's id (two answers swapped in custody) refuses too.
    (tmp_path / "swap").mkdir()
    contract3, receipts3, physical3 = _write_reasoning_fixture(tmp_path / "swap")
    body3 = json.loads(contract3.read_text(encoding="utf-8"))
    first, second = body3["frozen_items"][0], body3["frozen_items"][1]
    raw_first = physical3[first["answer_object"]["sha256"]].read_bytes()
    raw_second = physical3[second["answer_object"]["sha256"]].read_bytes()
    assert len(raw_first) == len(raw_second)
    physical3[first["answer_object"]["sha256"]].write_bytes(raw_second)
    physical3[second["answer_object"]["sha256"]].write_bytes(raw_first)
    result3 = tmp_path / "row-swap.json"
    completed = _run_reasoning(contract3, receipts3, result3)
    assert completed.returncode == 78
    assert json.loads(result3.read_text(encoding="utf-8"))["reason"] == f"REASONING_FORBIDDEN_INPUT_REFUSED:answer_shape:{first['item_id']}"

    # A prediction-custody receipt supplied as a source refuses before any byte is read.
    (tmp_path / "second").mkdir()
    contract2, receipts2, _ = _write_reasoning_fixture(tmp_path / "second")
    custody = tmp_path / "second" / "prediction-custody.json"
    custody.write_text(json.dumps({"schema_version": "ember-prediction-custody-v1", "rows": []}), encoding="utf-8")
    result2 = tmp_path / "row-custody.json"
    completed = _run_reasoning(contract2, [receipts2[0], custody], result2)
    assert completed.returncode == 78
    refusal = json.loads(result2.read_text(encoding="utf-8"))
    assert refusal["reason"] == "REASONING_FORBIDDEN_INPUT_REFUSED:source_schema:ember-prediction-custody-v1"

    # The bound receipt set must be supplied in full.
    result4 = tmp_path / "row-incomplete.json"
    completed = _run_reasoning(contract2, [receipts2[0]], result4)
    assert completed.returncode == 78
    assert json.loads(result4.read_text(encoding="utf-8"))["reason"] == "REASONING_SOURCE_RECEIPT_SET_INCOMPLETE_REFUSED"


def test_reasoning_adapter_row_satisfies_the_release_executor_item_schema(tmp_path: Path) -> None:
    import importlib.util

    contract, receipts, _ = _write_reasoning_fixture(tmp_path)
    result = tmp_path / "row.json"
    assert _run_reasoning(contract, receipts, result).returncode == 0
    row = json.loads(result.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "issue1947_release_execute", SCRIPT.parent / "issue1947_release_execute.py"
    )
    executor = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(executor)
    validated = executor.validate_row(row, "E-MATRIX-REASONING")
    assert validated is row
