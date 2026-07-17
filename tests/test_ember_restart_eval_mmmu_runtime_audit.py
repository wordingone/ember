# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json

import pytest

from scripts.ember_restart_eval_mmmu_runtime_audit import audit


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(protocol_sha256: str | None = None):
    answers = {
        "q1": {"question_type": "multiple-choice", "answer": "A"},
        "q2": {"question_type": "multiple-choice", "answer": "B"},
    }
    answers_bytes = json.dumps(answers, sort_keys=True, separators=(",", ":")).encode()
    image = {
        "schema_version": "ember-restart-mmmu-image-input-freeze-v1",
        "result": "PREFLIGHT_ONLY",
        "benchmark_id": "MMMU",
        "row_count": 2,
        "rows": [
            {"id": "q1", "image_sha256s": ["a" * 64], "input_sha256": "b" * 64},
            {"id": "q2", "image_sha256s": ["c" * 64], "input_sha256": "d" * 64},
        ],
    }
    image_bytes = json.dumps(image, sort_keys=True, separators=(",", ":")).encode()
    scorer = b"mmmu scorer fixture\n"
    adapter = b"mmmu adapter fixture\n"
    version = "e" * 40
    tree = "f" * 40
    license_sha = "1" * 64
    checkpoint = "2" * 64
    config = "3" * 64
    protocol = _digest(f"MMMU:{version}:{_digest(answers_bytes)}:{_digest(scorer)}:{license_sha}:{tree}:{_digest(adapter)}:{_digest(image_bytes)}:{checkpoint}:{config}".encode())
    custody = {
        "schema_version": "ember-restart-benchmark-custody-v1",
        "benchmark_id": "MMMU",
        "benchmark_version": version,
        "upstream_tree_git_sha1": tree,
        "license_sha256": license_sha,
        "target_training_access": "FORBIDDEN",
        "target_execution_permitted": False,
        "split": {"answer_dictionary_sha256": _digest(answers_bytes), "eligible_multiple_choice_items": 2},
        "image_input_materialization": {"artifact_sha256": _digest(image_bytes), "row_count": 2},
        "validation_parquet_materialization": {"row_count": 2},
        "scorer": {"sha256": _digest(scorer)},
        "scoring_adapter": {"path": "scripts/ember_restart_eval_mmmu.py", "sha256": _digest(adapter)},
        "checkpoint_manifest_sha256": checkpoint,
        "model_config_sha256": config,
        "protocol_sha256": protocol,
    }
    return json.dumps(custody, sort_keys=True, separators=(",", ":")).encode(), answers_bytes, image_bytes, scorer, adapter, protocol


def test_mmmu_runtime_audit_derives_complete_protocol_and_stays_preflight_only():
    custody, answers, image, scorer, adapter, expected = _fixture()
    payload = audit(custody_bytes=custody, answers_bytes=answers, image_bytes=image, scorer_bytes=scorer, expected_scorer_bytes=scorer, adapter_bytes=adapter, expected_adapter_bytes=adapter)
    assert payload["result"] == "PREFLIGHT_ONLY"
    assert payload["target_execution_permitted"] is False
    assert payload["protocol_sha256"] == expected
    assert payload["sample_count"] == 2


def test_mmmu_runtime_audit_rejects_substituted_protocol_digest():
    custody, answers, image, scorer, adapter, _ = _fixture("9" * 64)
    with pytest.raises(ValueError, match="derived"):
        audit(custody_bytes=custody, answers_bytes=answers, image_bytes=image, scorer_bytes=scorer, expected_scorer_bytes=scorer, adapter_bytes=adapter, expected_adapter_bytes=adapter)
