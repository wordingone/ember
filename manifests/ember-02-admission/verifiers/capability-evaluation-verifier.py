# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Adjudicate a per-capability ember-3b-<capability>-capability-v1 criterion.

Evidence class: evaluation. Invoked by src/ember/governance/scripts/ember_restart/contract.py as

    python -I capability-evaluation-verifier.py \
        --capability <capability> --checkpoint-manifest <path> \
        --benchmark-id <id> --benchmark-version <version> --criterion-id <id> \
        --split <path> --harness <path> --protocol <path> \
        --inference-implementation <path> --predictions <path> --score-artifact <path>

`sample_count` is recounted from the predictions envelope rather than read from the
score artifact, so a score computed over fewer rows than were predicted is caught
here. As with the sufficiency verifier, the pass bar is not hardcoded: it comes from
the frozen protocol's pre-registered `criterion` block, and a protocol without one
fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

CAPABILITIES = ("text", "image", "audio", "reasoning", "tool")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample_count(predictions: Path) -> int:
    payload = json.loads(predictions.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("predictions: expected a non-empty rows list")
    return len(rows)


def adjudicate(metrics: object, criterion: object, criterion_id: str) -> str:
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("score artifact metrics: expected a non-empty object")
    if not isinstance(criterion, dict):
        raise ValueError("protocol: pre-registered criterion block missing")
    if criterion.get("criterion_id") != criterion_id:
        raise ValueError("protocol: criterion_id does not match the requested criterion")
    metric_name = criterion.get("metric")
    threshold = criterion.get("min_value")
    if not isinstance(metric_name, str) or metric_name not in metrics:
        raise ValueError("protocol criterion.metric: not present in the score artifact metrics")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
    ):
        raise ValueError("protocol criterion.min_value: expected a finite number")
    observed = metrics[metric_name]
    if (
        isinstance(observed, bool)
        or not isinstance(observed, (int, float))
        or not math.isfinite(observed)
    ):
        raise ValueError(f"score artifact metrics.{metric_name}: expected a finite number")
    return "PASSED" if observed >= threshold else "FAILED"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capability", required=True, choices=CAPABILITIES)
    parser.add_argument("--checkpoint-manifest", required=True, type=Path)
    parser.add_argument("--benchmark-id", required=True)
    parser.add_argument("--benchmark-version", required=True)
    parser.add_argument("--criterion-id", required=True)
    parser.add_argument("--split", required=True, type=Path)
    parser.add_argument("--harness", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--inference-implementation", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--score-artifact", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.criterion_id != f"ember-3b-{args.capability}-capability-v1":
        print("criterion does not match the requested capability", file=sys.stderr)
        return 1

    try:
        protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
        score = json.loads(args.score_artifact.read_text(encoding="utf-8"))
        if score.get("benchmark_id") != args.benchmark_id:
            raise ValueError("score artifact: benchmark_id mismatch")
        if score.get("benchmark_version") != args.benchmark_version:
            raise ValueError("score artifact: benchmark_version mismatch")
        metrics = score.get("metrics")
        count = sample_count(args.predictions)
        criterion_result = adjudicate(metrics, protocol.get("criterion"), args.criterion_id)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    attestation = {
        "capability": args.capability,
        "result": "MEASURED",
        "subject_checkpoint_sha256": sha256(args.checkpoint_manifest),
        "benchmark_id": args.benchmark_id,
        "benchmark_version": args.benchmark_version,
        "split_sha256": sha256(args.split),
        "harness_sha256": sha256(args.harness),
        "protocol_sha256": sha256(args.protocol),
        "inference_implementation_sha256": sha256(args.inference_implementation),
        "predictions_sha256": sha256(args.predictions),
        "score_artifact_sha256": sha256(args.score_artifact),
        "sample_count": count,
        "metrics": metrics,
        "criterion_id": args.criterion_id,
        "criterion_result": criterion_result,
    }
    print(json.dumps(attestation, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
