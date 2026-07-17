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


BATTERY = [
    {
        "name": "MMLU-Pro",
        "protocol_manifest": "manifests/ember-restart-mmlu-pro-protocol-v1.json",
        "execution_status": "BLOCKED_MMLU_PRO_LICENSE_CARD_HASH",
    },
    {
        "name": "GSM8K",
        "protocol_manifest": "manifests/ember-restart-gsm8k-protocol-v1.json",
        "execution_status": "BLOCKED_OWNED_CHECKPOINT_BINDING",
    },
    {
        "name": "MATH-500",
        "protocol_manifest": "manifests/ember-restart-eval-code-math-custody-v1.json",
        "execution_status": "BLOCKED_OWNED_CHECKPOINT_BINDING",
    },
    {
        "name": "ARC-Challenge",
        "protocol_manifest": "manifests/ember-restart-arc-challenge-protocol-v1.json",
        "execution_status": "BLOCKED_OWNED_CHECKPOINT_BINDING",
    },
    {
        "name": "HumanEval+",
        "protocol_manifest": "manifests/ember-restart-eval-code-math-custody-v1.json",
        "execution_status": "BLOCKED_OWNED_CHECKPOINT_BINDING",
    },
    {
        "name": "MBPP",
        "protocol_manifest": "manifests/ember-restart-eval-code-math-custody-v1.json",
        "execution_status": "BLOCKED_OWNED_CHECKPOINT_BINDING",
    },
    {
        "name": "HellaSwag",
        "protocol_manifest": "manifests/ember-restart-hellaswag-protocol-v1.json",
        "execution_status": "BLOCKED_OWNED_CHECKPOINT_BINDING",
    },
    {
        "name": "MMMU validation native-image scorer",
        "protocol_manifest": "manifests/ember-restart-mmmu-validation-custody-v1.json",
        "total_records": 900,
        "eligible_multiple_choice_items": 847,
        "execution_status": "BLOCKED_MMMU_CANONICAL_LOADER_PREDICTION_BINDING",
    },
]

BLOCKERS = [
    "MMLU-Pro license-card hash",
    "owned checkpoint binding",
    "MMMU canonical loader/prediction binding",
]


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_receipt(evaluator_commit: str) -> dict[str, object]:
    payload = {
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02C",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "schema_version": "ember-restart-vision-v4-eval-battery-v1",
        "receipt_status": "FROZEN_PRELAUNCH",
        "battery_id": "vision-v4-postrun",
        "evaluator_commit": evaluator_commit,
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