# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Public truth-bound receipt for the first owned step-2 shared raw forward."""

import hashlib
import json
from pathlib import Path


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
RECEIPT = ROOT / "manifests" / "ember-restart-eval-first-shared-raw-forward-v1.json"
PREDICTIONS = ROOT / "manifests" / "ember-restart-eval-first-shared-raw-forward-v1-predictions.json"
AUTHORITY = ROOT / "manifests" / "ember-restart-execution-authorities-v1.json"


def test_first_shared_raw_forward_receipt_is_hash_bound_and_non_claim():
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    published = json.loads(PREDICTIONS.read_text(encoding="utf-8"))
    predictions = published["predictions"]
    authority = json.loads(AUTHORITY.read_text(encoding="utf-8"))["authorities"][0]

    assert receipt["schema_version"] == "ember-first-shared-raw-forward-v1"
    assert receipt["result"] == "VERIFIED_NON_CLAIM_RAW_FORWARD"
    assert receipt["claim_status"] == "NON_ADMISSIBLE_RAW_PREDICTIONS"
    assert receipt["truth_boundary"] == {
        "training_tokens_seen": 2048,
        "sufficient_pretraining_proven": False,
        "capability_proven": False,
        "benchmark_score": None,
        "interpretation": "Execution-path evidence only. The decoded output is weak and receives no capability credit.",
    }
    assert predictions["claim_status"] == "NON_ADMISSIBLE_RAW_PREDICTIONS"
    assert published["goal_id"] == "EMBER-02"
    assert published["workstream_id"] == "EMBER-02C"
    assert published["next_executed_outcome"] == "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    assert published["source_predictions_sha256"] == receipt["artifacts"]["canonical_predictions_sha256"]
    assert receipt["output"]["generated_token_ids"] == predictions["rows"][0]["generated_token_ids"]
    assert receipt["output"]["decoded_text"] == predictions["rows"][0]["output"]["text"]
    assert receipt["prompt"]["input_sha256"] == predictions["rows"][0]["input_sha256"]

    stamps = receipt["identity_stamps"]
    assert stamps["checkpoint_sha256"] == authority["checkpoint_manifest_sha256"]
    assert stamps["model_config_sha256"] == authority["model_config_sha256"]
    assert stamps["tokenizer_sha256"] == authority["tokenizer_sha256"]
    assert stamps["model_source_sha256"] == authority["model_source_sha256"]
    assert stamps["inference_implementation_sha256"] == authority["inference_implementation_sha256"]
    assert stamps["parameter_receipt_sha256"] == authority["parameter_receipt_sha256"]
    assert stamps["parameter_counter_sha256"] == authority["parameter_counter_sha256"]
    assert stamps["trusted_verifier_registry_sha256"] == authority["trusted_verifier_registry_sha256"]

    resource = receipt["resource_receipt"]
    assert resource["runner_outcome"] == "COMPLETED"
    assert resource["child_exit_code"] == 0
    assert resource["operating_reserve_breaches"] == []
    assert resource["actual_seconds"] > resource["predicted_seconds"]
    assert resource["drift_alarm"] is True
