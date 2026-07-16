#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score canonical ARC-Challenge choice predictions against frozen parquet bytes."""
import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from ember_restart.prediction_contract import ContractError, validate_predictions


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_answers(data: bytes) -> dict[str, str]:
    try:
        rows = pq.read_table(pa.BufferReader(data), columns=["id", "choices", "answerKey"]).to_pylist()
    except pa.ArrowException as error:
        raise ValueError("frozen ARC references must be parquet") from error
    answers: dict[str, str] = {}
    for row in rows:
        choices = row.get("choices") if isinstance(row, dict) else None
        labels = choices.get("label") if isinstance(choices, dict) else None
        identifier = row.get("id") if isinstance(row, dict) else None
        answer = row.get("answerKey") if isinstance(row, dict) else None
        if not isinstance(identifier, str) or not identifier or identifier in answers or not isinstance(labels, list) or not labels or any(not isinstance(label, str) or not label for label in labels) or not isinstance(answer, str) or answer not in labels:
            raise ValueError("frozen ARC references require unique ids and answer keys in choice labels")
        answers[identifier] = answer
    if not answers:
        raise ValueError("frozen ARC references must be non-empty")
    return answers


def predicted_answers(data: bytes) -> tuple[dict, dict[str, str]]:
    try:
        envelope = validate_predictions(json.loads(data.decode("utf-8")))
    except (ContractError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("canonical checkpoint predictions are required") from error
    rows: dict[str, str] = {}
    for row in envelope["rows"]:
        output = row["output"]
        if output.get("kind") != "text" or not isinstance(output.get("text"), str) or row["id"] in rows:
            raise ValueError("canonical ARC predictions require unique text outputs")
        rows[row["id"]] = output["text"].strip()
    if not rows:
        raise ValueError("canonical ARC predictions must be non-empty")
    return envelope, rows


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-manifest", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    args = parser.parse_args()
    if args.score_output.exists():
        parser.error("score output must not pre-exist")
    try:
        manifest_bytes = args.frozen_manifest.read_bytes()
        reference_bytes = args.references.read_bytes()
        prediction_bytes = args.predictions.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        references = expected_answers(reference_bytes)
        envelope, predictions = predicted_answers(prediction_bytes)
        benchmark = envelope["benchmark"]
        if not isinstance(manifest, dict) or manifest.get("result") != "PREFLIGHT_ONLY" or manifest.get("benchmark_id") != "arc-challenge" or manifest.get("capability") != "reasoning" or manifest.get("references_sha256") != sha256(reference_bytes) or manifest.get("split_sha256") != sha256(reference_bytes) or manifest.get("task_count") != len(references) or any(benchmark.get(field) != manifest.get({"id": "benchmark_id", "version": "benchmark_version", "split_sha256": "split_sha256", "protocol_sha256": "protocol_sha256"}[field]) for field in ("id", "version", "split_sha256", "protocol_sha256")):
            raise ValueError("frozen ARC manifest does not bind canonical prediction identity")
        if set(references) != set(predictions):
            raise ValueError("canonical ARC predictions must exactly cover frozen reference ids")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError, pa.ArrowException) as error:
        parser.error(f"invalid ARC scorer inputs: {error}")
    payload = {"result": "PREFLIGHT_ONLY", "claim_status": "NON_ADMISSIBLE_FROZEN_ARC_CHALLENGE_SCORER", "criterion_id": "ember-3b-reasoning-capability-v1", "criterion_result": "FAILED", "metrics": {"accuracy": sum(predictions[identifier] == answer for identifier, answer in references.items()) / len(references)}, "sample_count": len(references), "checkpoint_manifest_sha256": envelope["checkpoint_manifest_sha256"], "model_config_sha256": envelope["model_config_sha256"], "references_sha256": sha256(reference_bytes), "predictions_sha256": sha256(prediction_bytes), "frozen_manifest_sha256": sha256(manifest_bytes), "upstream": "deterministic frozen ARC-Challenge exact-label scorer"}
    atomic_write(args.score_output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())