#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Ingest a pinned EvalPlus result only when it binds an owned sample sidecar."""
import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ids_sha256(ids: set[str]) -> str:
    return sha256(("\n".join(sorted(ids)) + "\n").encode("utf-8"))


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples-binding", required=True, type=Path)
    parser.add_argument("--eval-result", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.score_output.exists():
        parser.error("score output must not pre-exist")
    try:
        binding_bytes = arguments.samples_binding.read_bytes()
        result_bytes = arguments.eval_result.read_bytes()
        binding = json.loads(binding_bytes.decode("utf-8"))
        result = json.loads(result_bytes.decode("utf-8"))
        required = {"schema_version", "result", "suite", "checkpoint_manifest_sha256", "model_config_sha256", "task_asset_sha256", "evalplus_dataset_md5", "predictions_sha256", "samples_sha256", "task_ids_sha256", "sample_count", "frozen_code_manifest_sha256"}
        if not isinstance(binding, dict) or set(binding) != required or binding["schema_version"] != "ember-restart-evalplus-samples-binding-v1" or binding["result"] != "PREFLIGHT_ONLY" or not isinstance(binding["sample_count"], int) or isinstance(binding["sample_count"], bool) or binding["sample_count"] <= 0:
            raise ValueError("invalid EvalPlus samples sidecar")
        if not isinstance(result, dict) or not isinstance(result.get("hash"), str) or not isinstance(result.get("eval"), dict) or not isinstance(result.get("pass_at_k"), dict):
            raise ValueError("invalid EvalPlus result artifact")
        evaluations = result["eval"]
        if result["hash"] != binding["evalplus_dataset_md5"] or len(evaluations) != binding["sample_count"] or ids_sha256(set(evaluations)) != binding["task_ids_sha256"]:
            raise ValueError("EvalPlus result does not bind samples sidecar")
        base_pass = 0
        plus_pass = 0
        for task_id, outcomes in evaluations.items():
            if not isinstance(task_id, str) or not task_id or not isinstance(outcomes, list) or len(outcomes) != 1 or not isinstance(outcomes[0], dict):
                raise ValueError("EvalPlus result does not bind samples sidecar")
            outcome = outcomes[0]
            if outcome.get("base_status") not in {"pass", "fail", "timeout"} or outcome.get("plus_status") not in {"pass", "fail", "timeout"}:
                raise ValueError("EvalPlus result has unsupported task status")
            base_pass += outcome["base_status"] == "pass"
            plus_pass += outcome["base_status"] == outcome["plus_status"] == "pass"
        metrics = {"base_pass_at_1": base_pass / len(evaluations), "plus_pass_at_1": plus_pass / len(evaluations)}
        supplied = result["pass_at_k"]
        if supplied.get("base", {}).get("pass@1") != metrics["base_pass_at_1"] or supplied.get("plus", {}).get("pass@1") != metrics["plus_pass_at_1"] or not all(finite(value) for value in metrics.values()):
            raise ValueError("EvalPlus result pass@1 does not reproduce task outcomes")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"invalid EvalPlus result inputs: {error}")
    payload = {"result": "SELFTEST", "criterion_id": "ember-3b-text-capability-v1", "criterion_result": "FAILED", "metrics": metrics, "sample_count": binding["sample_count"], "checkpoint_manifest_sha256": binding["checkpoint_manifest_sha256"], "model_config_sha256": binding["model_config_sha256"], "predictions_sha256": binding["predictions_sha256"], "samples_binding_sha256": sha256(binding_bytes), "evalplus_result_sha256": sha256(result_bytes), "upstream": "EvalPlus result artifact bound to canonical owned samples"}
    arguments.score_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.score_output.parent, prefix=arguments.score_output.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, arguments.score_output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
