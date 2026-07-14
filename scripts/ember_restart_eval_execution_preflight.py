#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate checkpoint-bound evaluator inputs without emitting a claim-bearing receipt."""
import argparse
import hashlib
import json
import re
from pathlib import Path


CAPABILITIES = ("text", "image", "audio", "reasoning", "tool")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", required=True, choices=CAPABILITIES)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--benchmark-manifest", required=True, type=Path)
    parser.add_argument("--raw-predictions", required=True, type=Path)
    parser.add_argument("--result-artifact", required=True, type=Path)
    parser.add_argument("--criterion-id", required=True)
    parser.add_argument("--criterion-passed", required=True, choices=("true", "false"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    benchmark = json.loads(args.benchmark_manifest.read_text(encoding="utf-8"))
    required = ("benchmark_id", "version", "split", "harness_sha256", "protocol_sha256")
    if not isinstance(benchmark, dict) or any(not benchmark.get(key) for key in required):
        parser.error("benchmark manifest is missing required custody fields")
    if not SHA256.fullmatch(benchmark["harness_sha256"]) or not SHA256.fullmatch(benchmark["protocol_sha256"]):
        parser.error("harness and protocol hashes must be lowercase SHA-256")
    predictions = json.loads(args.raw_predictions.read_text(encoding="utf-8"))
    metrics = json.loads(args.result_artifact.read_text(encoding="utf-8"))
    if not isinstance(predictions, list) or not predictions:
        parser.error("raw predictions must be a non-empty list")
    if not isinstance(metrics, dict) or not metrics or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in metrics.values()):
        parser.error("result artifact must contain non-empty numeric metrics")
    payload = {"result": "PREFLIGHT_ONLY", "admission": "NOT_ELIGIBLE", "capability": args.capability, "subject_checkpoint_sha256": sha256(args.checkpoint), "benchmark": {key: benchmark[key] for key in required}, "raw_predictions_sha256": sha256(args.raw_predictions), "result_artifact_sha256": sha256(args.result_artifact), "sample_count": len(predictions), "metrics": metrics, "criterion": {"id": args.criterion_id, "passed": args.criterion_passed == "true"}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
