#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Emit the immutable vision-v4 post-run battery freeze receipt."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

SHA1 = re.compile(r"[0-9a-f]{40}")
BASELINE_CHECKPOINT = "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b"
BASELINE_CONFIG = "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0"


BATTERY = [
    {
        "name": "MMLU-Pro",
        "protocol_manifest": "manifests/ember-restart-mmlu-pro-protocol-v1.json",
        "execution_status": "BLOCKED_NO_CHECKPOINT_BOUND_PREDICTIONS",
    },
    {
        "name": "GSM8K",
        "protocol_manifest": "manifests/ember-restart-gsm8k-protocol-v1.json",
        "execution_status": "BLOCKED_NO_CHECKPOINT_BOUND_PREDICTIONS",
    },
    {
        "name": "MATH-500",
        "protocol_manifest": "manifests/ember-restart-eval-code-math-custody-v1.json",
        "execution_status": "BLOCKED_NO_CHECKPOINT_BOUND_PREDICTIONS",
    },
    {
        "name": "ARC-Challenge",
        "protocol_manifest": "manifests/ember-restart-arc-challenge-protocol-v1.json",
        "execution_status": "BLOCKED_NO_CHECKPOINT_BOUND_PREDICTIONS",
    },
    {
        "name": "HumanEval+",
        "protocol_manifest": "manifests/ember-restart-eval-code-math-custody-v1.json",
        "execution_status": "BLOCKED_NO_CHECKPOINT_BOUND_PREDICTIONS",
    },
    {
        "name": "MBPP",
        "protocol_manifest": "manifests/ember-restart-eval-code-math-custody-v1.json",
        "execution_status": "BLOCKED_NO_CHECKPOINT_BOUND_PREDICTIONS",
    },
    {
        "name": "HellaSwag",
        "protocol_manifest": "manifests/ember-restart-hellaswag-protocol-v1.json",
        "execution_status": "BLOCKED_NO_CHECKPOINT_BOUND_PREDICTIONS",
    },
    {
        "name": "MMMU validation native-image scorer",
        "protocol_manifest": "manifests/ember-restart-mmmu-validation-custody-v1.json",
        "total_records": 900,
        "eligible_multiple_choice_items": 847,
        "execution_status": "BLOCKED_NO_CHECKPOINT_BOUND_PREDICTIONS",
    },
]

BLOCKERS = ["no checkpoint-bound predictions"]


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_postrun_candidate(candidate: object) -> None:
    if not isinstance(candidate, dict):
        raise ValueError("post-run candidate binding must be an object")
    checkpoint = candidate.get("checkpoint_manifest_sha256")
    config = candidate.get("model_config_sha256")
    receipt = candidate.get("receipt_sha256")
    if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in (checkpoint, config, receipt)):
        raise ValueError("post-run candidate binding requires content-addressed identities")
    if checkpoint == BASELINE_CHECKPOINT or config == BASELINE_CONFIG:
        raise ValueError("post-run candidate cannot reuse the pre-run candidate identity")

def build_receipt(evaluator_commit: str) -> dict[str, object]:
    payload = {
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02C",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "schema_version": "ember-restart-vision-v4-eval-battery-v1",
        "receipt_status": "FROZEN_PRELAUNCH",
        "battery_id": "vision-v4-postrun",
        "evaluator_commit": evaluator_commit,
        "baseline_checkpoint_manifest_sha256": BASELINE_CHECKPOINT,
        "baseline_model_config_sha256": BASELINE_CONFIG,
        "postrun_binding": {
            "status": "UNRESOLVED_AWAITING_EMITTED_CHECKPOINT",
            "receipt_sha256": None,
            "checkpoint_manifest_sha256": None,
            "model_config_sha256": None,
        },
        "mutation_policy": "FROZEN_NO_ADDITIONS_OR_RENAMES_AFTER_LAUNCH",
        "benchmarks": BATTERY,
        "runnability_blockers": BLOCKERS,
        "claim_boundary": "NO_CAPABILITY_ADMISSION_OR_SUFFICIENT_PRETRAINING_CREDIT",
    }
    payload["content_sha256"] = digest(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluator-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if not SHA1.fullmatch(arguments.evaluator_commit):
        parser.error("evaluator commit must be lowercase sha1")
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    payload = build_receipt(arguments.evaluator_commit)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, arguments.output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
