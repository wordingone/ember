#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score canonical tool-call predictions against one frozen static BFCL manifest."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from ember_restart.prediction_contract import ContractError, validate_predictions


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-task-manifest", required=True, type=Path)
    parser.add_argument("--canonical-predictions", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    args = parser.parse_args()
    if args.score_output.exists():
        parser.error("score output must not pre-exist")
    try:
        frozen_bytes = args.frozen_task_manifest.read_bytes()
        prediction_bytes = args.canonical_predictions.read_bytes()
        frozen = json.loads(frozen_bytes.decode("utf-8"))
        envelope = validate_predictions(json.loads(prediction_bytes.decode("utf-8")))
        required = {"result", "benchmark_id", "benchmark_version", "capability", "split_sha256", "protocol_sha256", "tasks"}
        if not isinstance(frozen, dict) or set(frozen) != required or frozen["result"] != "PREFLIGHT_ONLY" or frozen["benchmark_id"] != "bfcl-static-non-live" or frozen["capability"] != "tool" or not isinstance(frozen["tasks"], list) or not frozen["tasks"]:
            raise ValueError("invalid frozen BFCL static manifest")
        benchmark = envelope["benchmark"]
        if any(benchmark.get(key) != frozen[field] for key, field in (("id", "benchmark_id"), ("version", "benchmark_version"), ("capability", "capability"), ("split_sha256", "split_sha256"), ("protocol_sha256", "protocol_sha256"))):
            raise ValueError("canonical predictions do not bind frozen BFCL identity")
        expected = {}
        for task in frozen["tasks"]:
            if not isinstance(task, dict) or set(task) != {"id", "expected_call"} or not isinstance(task["id"], str) or not task["id"] or not isinstance(task["expected_call"], dict) or task["id"] in expected:
                raise ValueError("invalid frozen BFCL task")
            expected[task["id"]] = task["expected_call"]
        actual = {}
        for row in envelope["rows"]:
            output = row["output"]
            if output.get("kind") != "tool_call":
                raise ValueError("BFCL predictions require tool_call outputs")
            actual[row["id"]] = {"name": output["name"], "arguments": output["arguments"]}
        if set(actual) != set(expected):
            raise ValueError("canonical predictions must exactly cover frozen BFCL tasks")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ContractError, ValueError) as error:
        parser.error(f"invalid BFCL static scorer inputs: {error}")
    payload = {"result": "PREFLIGHT_ONLY", "criterion_id": "ember-3b-tool-capability-v1", "criterion_result": "FAILED", "metrics": {"exact_tool_call": sum(canonical(actual[key]) == canonical(expected[key]) for key in expected) / len(expected)}, "sample_count": len(expected), "checkpoint_manifest_sha256": envelope["checkpoint_manifest_sha256"], "model_config_sha256": envelope["model_config_sha256"], "predictions_sha256": digest(prediction_bytes), "frozen_task_manifest_sha256": digest(frozen_bytes), "upstream": "frozen static BFCL non-live exact tool-call scorer"}
    args.score_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.score_output.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, args.score_output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())