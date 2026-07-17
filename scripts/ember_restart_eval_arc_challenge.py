#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score canonical ARC-Challenge choice predictions against frozen parquet."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from ember_restart.prediction_contract import ContractError, validate_predictions

HASH = re.compile(r"[0-9a-f]{64}")
STRICT_SCHEMA = "ember-restart-arc-challenge-freeze-v2"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
        source_rows = pq.read_table(pa.BufferReader(reference_bytes), columns=["id", "choices", "answerKey"]).to_pylist()
        references = {}
        for row in source_rows:
            choices = row.get("choices") if isinstance(row, dict) else None
            labels = choices.get("label") if isinstance(choices, dict) else None
            identifier = row.get("id") if isinstance(row, dict) else None
            answer = row.get("answerKey") if isinstance(row, dict) else None
            if not isinstance(identifier, str) or not identifier or identifier in references or not isinstance(labels, list) or not labels or any(not isinstance(label, str) or not label for label in labels) or not isinstance(answer, str) or answer not in labels:
                raise ValueError("frozen ARC references require unique ids and answer keys in choice labels")
            references[identifier] = answer
        if not references:
            raise ValueError("frozen ARC references must be non-empty")
        envelope = validate_predictions(json.loads(prediction_bytes.decode("utf-8")))
        benchmark = envelope["benchmark"]
        predictions = {}
        for row in envelope["rows"]:
            output = row.get("output")
            if not isinstance(output, dict) or output.get("kind") != "text" or not isinstance(output.get("text"), str) or row["id"] in predictions:
                raise ValueError("canonical ARC predictions require unique text outputs")
            predictions[row["id"]] = output["text"].strip()
        if not isinstance(manifest, dict) or manifest.get("result") != "PREFLIGHT_ONLY" or manifest.get("benchmark_id") != "arc-challenge" or manifest.get("capability") != "reasoning" or manifest.get("references_sha256") != digest(reference_bytes) or manifest.get("split_sha256") != digest(reference_bytes) or manifest.get("task_count") != len(references) or any(benchmark.get(key) != manifest.get(field) for key, field in (("id", "benchmark_id"), ("version", "benchmark_version"), ("split_sha256", "split_sha256"), ("protocol_sha256", "protocol_sha256"))):
            raise ValueError("frozen ARC manifest does not bind canonical prediction identity")
        if set(references) != set(predictions):
            raise ValueError("canonical ARC predictions must exactly cover frozen reference ids")
        strict = manifest.get("schema_version") == STRICT_SCHEMA or any(field in manifest for field in ("checkpoint_manifest_sha256", "model_config_sha256"))
        if strict:
            for field in ("checkpoint_manifest_sha256", "model_config_sha256"):
                if not isinstance(manifest.get(field), str) or not HASH.fullmatch(manifest[field]) or envelope.get(field) != manifest[field]:
                    raise ValueError("strict ARC custody does not bind canonical checkpoint/config identity")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError, ContractError, pa.ArrowException) as error:
        parser.error(f"invalid ARC scorer inputs: {error}")
    payload = {"result": "PREFLIGHT_ONLY", "claim_status": "NON_ADMISSIBLE_FROZEN_ARC_CHALLENGE_SCORER", "criterion_id": "ember-3b-reasoning-capability-v1", "criterion_result": "FAILED", "metrics": {"accuracy": sum(predictions[key] == value for key, value in references.items()) / len(references)}, "sample_count": len(references), "benchmark_id": benchmark["id"], "benchmark_version": benchmark["version"], "split_sha256": benchmark["split_sha256"], "protocol_sha256": benchmark["protocol_sha256"], "checkpoint_manifest_sha256": envelope["checkpoint_manifest_sha256"], "model_config_sha256": envelope["model_config_sha256"], "references_sha256": digest(reference_bytes), "predictions_sha256": digest(prediction_bytes), "frozen_manifest_sha256": digest(manifest_bytes), "upstream": "deterministic frozen ARC-Challenge exact-label scorer"}
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