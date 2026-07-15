#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score frozen MMMU multiple-choice predictions without making an admission claim."""
import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ember_restart.prediction_contract import ContractError, validate_predictions


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_predictions(data: bytes) -> tuple[dict, dict[str, object]]:
    try:
        envelope = validate_predictions(json.loads(data.decode("utf-8")))
    except (ContractError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("canonical checkpoint predictions are required") from error
    benchmark = envelope["benchmark"]
    if benchmark.get("id") != "MMMU" or benchmark.get("capability") != "image":
        raise ValueError("canonical predictions must declare MMMU image capability")
    converted: dict[str, object] = {}
    for row in envelope["rows"]:
        output = row.get("output")
        if not isinstance(output, dict) or output.get("kind") != "text" or not isinstance(output.get("text"), str) or not output["text"] or row["id"] in converted:
            raise ValueError("canonical MMMU prediction rows require unique text outputs")
        converted[row["id"]] = output["text"]
    if not converted:
        raise ValueError("canonical MMMU predictions must be non-empty")
    return envelope, converted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mmmu-root", required=True, type=Path)
    parser.add_argument("--answers", required=True, type=Path)
    parser.add_argument("--canonical-predictions", required=True, type=Path)
    parser.add_argument("--frozen-mmmu-manifest", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    arguments = parser.parse_args()
    if arguments.score_output.exists():
        parser.error("score output must not pre-exist")
    if not 1 <= arguments.timeout_seconds <= 120:
        parser.error("timeout seconds must be between 1 and 120")
    try:
        answer_bytes = arguments.answers.read_bytes()
        prediction_bytes = arguments.canonical_predictions.read_bytes()
        manifest_bytes = arguments.frozen_mmmu_manifest.read_bytes()
        answers = json.loads(answer_bytes.decode("utf-8"))
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        envelope, converted = canonical_predictions(prediction_bytes)
        benchmark = envelope["benchmark"]
        if not isinstance(answers, dict) or not answers or any(not isinstance(value, dict) or value.get("question_type") != "multiple-choice" for value in answers.values()):
            raise ValueError("MMMU adapter permits multiple-choice answers only")
        split = manifest.get("split") if isinstance(manifest, dict) else None
        if not isinstance(split, dict) or manifest.get("benchmark_id") != "MMMU" or manifest.get("benchmark_version") != benchmark.get("version") or split.get("name") != "validation" or split.get("answer_dictionary_sha256") != sha256(answer_bytes) or benchmark.get("split_sha256") != sha256(answer_bytes):
            raise ValueError("frozen MMMU custody does not bind canonical predictions")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"invalid MMMU evaluator inputs: {error}")
    if answers.keys() != converted.keys():
        parser.error("MMMU predictions must exactly cover frozen answer ids")
    scorer = arguments.mmmu_root / "mmmu" / "main_eval_only.py"
    if not scorer.is_file():
        parser.error("cached MMMU main_eval_only.py is required")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.canonical_predictions.parent, prefix=arguments.canonical_predictions.name + ".", suffix=".mmmu.tmp", delete=False) as handle:
        json.dump(converted, handle, sort_keys=True)
        temporary = Path(handle.name)
    with tempfile.NamedTemporaryFile("wb", dir=arguments.answers.parent, prefix=arguments.answers.name + ".", suffix=".mmmu.answers.tmp", delete=False) as handle:
        handle.write(answer_bytes)
        answer_snapshot = Path(handle.name)
    try:
        run = subprocess.run([sys.executable, str(scorer), "--output_path", str(temporary), "--answer_path", str(answer_snapshot)], cwd=scorer.parent, text=True, capture_output=True, timeout=arguments.timeout_seconds, check=False)
    except subprocess.TimeoutExpired:
        parser.error("MMMU scorer timed out")
    finally:
        temporary.unlink(missing_ok=True)
        answer_snapshot.unlink(missing_ok=True)
    if run.returncode != 0:
        parser.error(f"MMMU scorer failed: {run.stderr.strip()}")
    try:
        aggregate = ast.literal_eval(run.stdout.strip().splitlines()[-1])
        overall = aggregate["Overall"]
        sample_count = int(overall["num"])
        accuracy = float(overall["acc"])
    except (ValueError, SyntaxError, KeyError, IndexError, TypeError):
        parser.error("MMMU scorer returned an invalid aggregate")
    if sample_count <= 0 or sample_count != len(converted):
        parser.error("MMMU scorer did not cover the frozen prediction set")
    payload = {"metrics": {"accuracy": accuracy}, "sample_count": sample_count, "criterion_id": "ember-3b-image-capability-v1", "criterion_result": "FAILED", "predictions_sha256": sha256(prediction_bytes), "answers_sha256": sha256(answer_bytes), "frozen_mmmu_manifest_sha256": sha256(manifest_bytes), "upstream": "MMMU exact multiple-choice local scorer bound to canonical predictions"}
    arguments.score_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.score_output.parent, prefix=arguments.score_output.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, arguments.score_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())