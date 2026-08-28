# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ember_restart"))

import mmmu_front_unit as subject


def envelope(choice="A", row_id="validation_Math_1", input_sha="f" * 64):
    return {
        "schema_version": "ember-owned-predictions-v1",
        "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
        "checkpoint_manifest_sha256": "a" * 64,
        "model_config_sha256": "b" * 64,
        "tokenizer_sha256": "c" * 64,
        "inference_implementation_sha256": "d" * 64,
        "benchmark": {"id": "MMMU", "version": "v", "capability": "image", "split_sha256": "e" * 64, "protocol_sha256": "1" * 64},
        "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]},
        "rows": [{"id": row_id, "input_sha256": input_sha, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "choice", "value": choice}}],
    }


def loader():
    return {
        "id": "validation_Math_1",
        "input_sha256": "f" * 64,
        "options": ["one", "two"],
        "option_labels": ["A", "B"],
        "options_sha256": subject.canonical_digest(["one", "two"]),
        "ground_truth": "A",
    }


def test_eligible_identity_uses_sorted_lf_terminated_ids():
    answers = {
        "validation_b": {"question_type": "multiple-choice", "ground_truth": "B"},
        "validation_open": {"question_type": "short-answer", "ground_truth": "x"},
        "validation_a": {"question_type": "multiple-choice", "ground_truth": "A"},
    }
    ids, digest = subject.eligible_identity(answers)
    assert ids == ["validation_a", "validation_b"]
    assert digest == hashlib.sha256(b"validation_a\nvalidation_b\n").hexdigest()


def test_parse_options_preserves_order_and_refuses_bad_shape():
    assert subject.parse_options("['z', 'a']") == ["z", "a"]
    with pytest.raises(subject.FrontUnitError, match="OPTION_SHAPE"):
        subject.parse_options("{'A': 'z'}")


def test_parquet_index_requires_exact_paths_and_bytes(tmp_path):
    path = tmp_path / "Math" / "validation-00000-of-00001.parquet"
    path.parent.mkdir()
    path.write_bytes(b"pinned")
    expected = [{"path": "Math/validation-00000-of-00001.parquet", "sha256": hashlib.sha256(b"pinned").hexdigest()}]
    assert subject.validate_parquet_index(tmp_path, expected) == [path]
    path.write_bytes(b"drift")
    with pytest.raises(subject.FrontUnitError, match="PARQUET_BYTES_DRIFT"):
        subject.validate_parquet_index(tmp_path, expected)


def test_exact_choice_scoring_calls_real_adapter_shape():
    result = subject.score_one(loader(), envelope())
    assert result == {"exact_match": 1, "sample_count": 1}


def test_two_state_wiring_executes_match_and_mismatch():
    result = subject.run_two_state(loader())
    assert result["match"] == {"expected_exact_match": 1, "observed_exact_match": 1, "result": "PASS"}
    assert result["mismatch"] == {"expected_exact_match": 0, "observed_exact_match": 0, "result": "PASS"}
    assert result["terminal_result"] == "PASS"


@pytest.mark.parametrize(
    ("failure_class", "mutation"),
    [
        ("wrong-gold", lambda l, e: ({**l, "ground_truth": "B"}, e)),
        ("changed-order", lambda l, e: ({**l, "options": ["two", "one"]}, e)),
        ("duplicate-ID", lambda l, e: (l, {**e, "rows": e["rows"] * 2})),
        ("empty-prediction", lambda l, e: (l, envelope(choice=""))),
        ("scorer-substitution", lambda l, e: (l, e)),
        ("caller-prediction", lambda l, e: (l, e)),
    ],
)
def test_six_negative_classes_are_fail_closed(failure_class, mutation):
    mutated_loader, mutated_envelope = mutation(loader(), envelope())
    assert subject.run_negative(failure_class, mutated_loader, mutated_envelope) == "PASS_REFUSED"


def test_receipt_self_hash_omits_only_self_field():
    payload = {"schema_version": "x", "result": "PASS"}
    payload["self_sha256"] = subject.derive_self(payload)
    assert subject.derive_self(payload) == payload["self_sha256"]
