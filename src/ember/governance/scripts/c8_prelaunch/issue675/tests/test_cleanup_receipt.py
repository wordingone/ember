# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "q2_cleanup_receipt.py"
CLASSES = ("temp", "tmp", "torch", "triton", "cuda", "hf", "xdg", "b3_fork")


def _load():
    assert MODULE_PATH.exists(), "q2_cleanup_receipt.py is not implemented"
    spec = importlib.util.spec_from_file_location("q2_cleanup_receipt", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence() -> dict[str, object]:
    return {
        "schema_version": "q2-cleanup-evidence-v1",
        "job_id": "q2-actual-update-001",
        "authority": "ember-lab",
        "preconditions": {
            "terminal_receipt_sha256": "a" * 64,
            "consumer_receipt_sha256": "b" * 64,
            "independent_review_receipt_sha256": "c" * 64,
        },
        "deleted": [
            {"logical_class": name, "pre_delete_sha256": f"{index + 1:064x}", "bytes": index + 1}
            for index, name in enumerate(CLASSES)
        ],
        "post_delete_absent": list(CLASSES),
        "preserved": {
            "seed_checkpoint_sha256": "d" * 64,
            "threshold_sha256": "e" * 64,
            "historical_receipts_index_sha256": "f" * 64,
        },
        "cleanup_exit_code": 0,
    }


def test_builds_path_free_noncredit_cleanup_receipt(tmp_path: Path):
    module = _load()
    evidence_path = tmp_path / "cleanup.json"
    evidence_path.write_text(json.dumps(_evidence()), encoding="utf-8")

    receipt = module.validate_cleanup_evidence(evidence_path)

    assert receipt["schema_version"] == "q2-cleanup-receipt-v1"
    assert receipt["deleted_logical_classes"] == list(CLASSES)
    assert receipt["cleanup_complete"] is True
    assert receipt["event_credit"] is False
    assert receipt["issue_completion_credit"] is False
    assert receipt["receipt_sha256"] == module.receipt_sha256(receipt)
    assert "path" not in json.dumps(receipt).lower()


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda row: row.update(authority="standalone-helper"), "CLEANUP_AUTHORITY_INVALID"),
        (lambda row: row["preconditions"].pop("independent_review_receipt_sha256"), "CLEANUP_PRECONDITIONS_INVALID"),
        (lambda row: row["deleted"].pop(), "CLEANUP_CLASS_SET_INVALID"),
        (lambda row: row["deleted"][0].update(path="B:/tmp/run"), "CLEANUP_ROW_SCHEMA_INVALID"),
        (lambda row: row["post_delete_absent"].pop(), "CLEANUP_POSTDELETE_INCOMPLETE"),
        (lambda row: row["preserved"].update(seed_checkpoint_sha256="0" * 63), "CLEANUP_PRESERVED_BINDINGS_INVALID"),
        (lambda row: row.update(cleanup_exit_code=1), "CLEANUP_FAILED"),
    ],
)
def test_refuses_unsafe_or_incomplete_cleanup(tmp_path: Path, mutate, code: str):
    module = _load()
    evidence = _evidence()
    mutate(evidence)
    evidence_path = tmp_path / "cleanup.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(module.CleanupRefusal, match=code):
        module.validate_cleanup_evidence(evidence_path)
