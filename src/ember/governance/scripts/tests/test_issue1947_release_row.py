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
