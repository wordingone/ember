# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "q2_terminal_chain.py"


def _load():
    assert MODULE_PATH.exists(), "q2_terminal_chain.py is not implemented"
    spec = importlib.util.spec_from_file_location("q2_terminal_chain", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _seal(value: dict[str, object], field: str = "receipt_sha256") -> dict[str, object]:
    unsigned = dict(value)
    unsigned.pop(field, None)
    value[field] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    return value


def _write(root: Path) -> dict[str, Path]:
    root.mkdir()
    job = "q2-actual-update-001"
    capture = _seal(
        {
            "schema": "q2-actual-update-capture-v1",
            "run_id": job,
            "scope": "TARGET_TENSOR_COUNTERFACTUAL",
            "verdict": "CAPTURED_NOT_ADJUDICATED",
            "no_new_parallel_authority": True,
        },
        "manifest_sha256",
    )
    capture_path = root / "capture.json"
    capture_path.write_bytes(_canonical(capture))
    capture_sha = hashlib.sha256(capture_path.read_bytes()).hexdigest()

    terminal = {
        "schema": "ember-lab-operational-receipt-v1",
        "job_id": job,
        "state": "exited",
        "exit_code": 0,
        "scientific_capability_evidence": False,
    }
    terminal_raw = _canonical(terminal)
    terminal_sha = hashlib.sha256(terminal_raw).hexdigest()
    terminal_path = root / f"{terminal_sha}.json"
    terminal_path.write_bytes(terminal_raw)

    adjudication = _seal(
        {
            "schema_version": "q2-actual-update-successor-receipt-v1",
            "verdict": "NON_NULL_ORIENTATION",
            "event_custody": {
                "job_id": job,
                "capture_manifest_sha256": capture["manifest_sha256"],
                "terminal_receipt_sha256": terminal_sha,
            },
            "credits": {"whole_step": False, "material_loss_bridge": False},
            "no_new_parallel_authority": True,
        }
    )
    adjudication_path = root / "adjudication.json"
    adjudication_path.write_bytes(_canonical(adjudication))
    adjudication_sha = hashlib.sha256(adjudication_path.read_bytes()).hexdigest()

    review = _seal(
        {
            "schema_version": "q2-independent-event-review-v1",
            "job_id": job,
            "reviewer": "independent-verifier",
            "verdict": "PASS",
            "reviewed": {
                "capture_file_sha256": capture_sha,
                "adjudication_file_sha256": adjudication_sha,
                "terminal_receipt_sha256": terminal_sha,
            },
            "no_new_parallel_authority": True,
        }
    )
    review_path = root / "review.json"
    review_path.write_bytes(_canonical(review))
    review_sha = hashlib.sha256(review_path.read_bytes()).hexdigest()

    cleanup = _seal(
        {
            "schema_version": "q2-cleanup-receipt-v1",
            "job_id": job,
            "authority": "ember-lab",
            "preconditions": {
                "terminal_receipt_sha256": terminal_sha,
                "consumer_receipt_sha256": adjudication_sha,
                "independent_review_receipt_sha256": review_sha,
            },
            "cleanup_complete": True,
            "event_credit": False,
            "scientific_credit": False,
            "issue_completion_credit": False,
            "no_new_parallel_authority": True,
        }
    )
    cleanup_path = root / "cleanup.json"
    cleanup_path.write_bytes(_canonical(cleanup))
    return {
        "capture": capture_path,
        "terminal": terminal_path,
        "adjudication": adjudication_path,
        "review": review_path,
        "cleanup": cleanup_path,
    }


def test_seals_one_path_free_terminal_chain(tmp_path: Path):
    module = _load()
    paths = _write(tmp_path / "chain")

    result = module.validate_terminal_chain(**{f"{key}_path": value for key, value in paths.items()})

    assert result["schema_version"] == "q2-terminal-chain-receipt-v1"
    assert result["event_chain_complete"] is True
    assert result["issue_completion_credit"] is False
    assert result["receipt_sha256"] == module.receipt_sha256(result)
    assert "path" not in json.dumps(result).lower()


@pytest.mark.parametrize(
    ("target", "mutate", "code"),
    [
        ("adjudication", lambda row: row["event_custody"].update(job_id="foreign"), "TERMINAL_CHAIN_JOB_MISMATCH"),
        ("review", lambda row: row.update(verdict="P1"), "TERMINAL_CHAIN_REVIEW_NOT_PASS"),
        ("cleanup", lambda row: row["preconditions"].update(consumer_receipt_sha256="0" * 64), "TERMINAL_CHAIN_CLEANUP_MISMATCH"),
        ("terminal", lambda row: row.update(exit_code=1), "TERMINAL_CHAIN_TERMINAL_FAILED"),
    ],
)
def test_refuses_cross_run_or_failed_chain(tmp_path: Path, target, mutate, code: str):
    module = _load()
    paths = _write(tmp_path / "chain")
    value = json.loads(paths[target].read_text(encoding="utf-8"))
    mutate(value)
    if target in {"adjudication", "review", "cleanup"}:
        _seal(value)
    paths[target].write_bytes(_canonical(value))

    with pytest.raises(module.TerminalChainRefusal, match=code):
        module.validate_terminal_chain(**{f"{key}_path": item for key, item in paths.items()})
