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
