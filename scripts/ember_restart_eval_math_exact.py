#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score canonical math predictions against byte-bound frozen references."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from ember_restart.prediction_contract import ContractError, validate_predictions


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_rows(data: bytes) -> dict[str, str]:
    try:
        parsed = json.loads(data.decode("utf-8"))
        values = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        values = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    rows = {}
    for value in values:
        identifier = value.get("unique_id") if isinstance(value, dict) and isinstance(value.get("unique_id"), str) and value["unique_id"] else value.get("id") if isinstance(value, dict) else None
        if not isinstance(value, dict) or not isinstance(identifier, str) or not identifier or (isinstance(value.get("id"), str) and isinstance(value.get("unique_id"), str) and value["id"] != value["unique_id"]) or not isinstance(value.get("answer"), str) or identifier in rows:
            raise ValueError("each math reference needs a unique id and answer")
        rows[identifier] = value["answer"]
    if not rows:
        raise ValueError("math references must be non-empty")
    return rows


def canonical_predictions(data: bytes) -> tuple[dict, dict[str, str]]:
    try:
        envelope = validate_predictions(json.loads(data.decode("utf-8")))
    except (ContractError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("canonical checkpoint predictions are required") from error
    benchmark = envelope["benchmark"]
    if benchmark.get("id") != "math-500" or benchmark.get("capability") != "reasoning":
        raise ValueError("canonical predictions must declare math-500 reasoning")
    rows = {}
    for row in envelope["rows"]:
        output = row.get("output")
        if not isinstance(output, dict) or output.get("kind") != "text" or not isinstance(output.get("text"), str) or row["id"] in rows:
            raise ValueError("canonical math predictions are malformed")
        rows[row["id"]] = output["text"]
    if not rows:
        raise ValueError("canonical math predictions must be non-empty")
    return envelope, rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-math-manifest", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    args = parser.parse_args()
    if args.score_output.exists():
        parser.error("score output must not pre-exist")
    try:
        manifest_bytes = args.frozen_math_manifest.read_bytes()
        reference_bytes = args.references.read_bytes()
        prediction_bytes = args.predictions.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        references = read_rows(reference_bytes)
        envelope, predicted = canonical_predictions(prediction_bytes)
        benchmark = envelope["benchmark"]
        fields = ("checkpoint_manifest_sha256", "model_config_sha256", "split_sha256", "protocol_sha256")
        if not isinstance(manifest, dict) or manifest.get("result") != "PREFLIGHT_ONLY" or manifest.get("benchmark_id") != "math-500" or manifest.get("references_sha256") != sha256(reference_bytes) or any(manifest.get(field) != (envelope[field] if field in envelope else benchmark.get(field)) for field in fields[:2]) or manifest.get("split_sha256") != benchmark.get("split_sha256") or manifest.get("protocol_sha256") != benchmark.get("protocol_sha256") or manifest.get("benchmark_version") != benchmark.get("version"):
            raise ValueError("frozen math manifest does not bind canonical prediction identity")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"invalid frozen math artifacts: {error}")
    if references.keys() != predicted.keys():
        parser.error("predictions must exactly cover frozen math ids")
    payload = {"result": "PREFLIGHT_ONLY", "claim_status": "NON_ADMISSIBLE_FROZEN_MATH_SCORER", "criterion_id": "ember-3b-reasoning-capability-v1", "criterion_result": "FAILED", "metrics": {"exact_match": sum(references[key] == predicted[key] for key in references) / len(references)}, "sample_count": len(references), "references_sha256": sha256(reference_bytes), "predictions_sha256": sha256(prediction_bytes), "frozen_math_manifest_sha256": sha256(manifest_bytes), "upstream": "deterministic frozen math exact-match scorer"}
    args.score_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.score_output.parent, delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, args.score_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
