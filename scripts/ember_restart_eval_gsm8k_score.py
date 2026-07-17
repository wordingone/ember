#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score canonical GSM8K final-answer predictions against frozen parquet."""
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
STRICT_SCHEMA = "ember-restart-gsm8k-freeze-v2"
SCORER_PATH = "scripts/ember_restart_eval_gsm8k_score.py"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derived_protocol_sha256(manifest: dict[str, object]) -> str:
    if manifest.get("scoring_adapter_path") != SCORER_PATH:
        raise ValueError("strict GSM8K custody requires the canonical scoring adapter path")
    scorer_sha256 = manifest.get("scoring_adapter_sha256")
    license_sha256 = manifest.get("license_sha256")
    split_sha256 = manifest.get("split_sha256")
    revision = manifest.get("benchmark_version")
    if (
        not isinstance(scorer_sha256, str)
        or not HASH.fullmatch(scorer_sha256)
        or not isinstance(license_sha256, str)
        or not HASH.fullmatch(license_sha256)
        or not isinstance(split_sha256, str)
        or not HASH.fullmatch(split_sha256)
        or not isinstance(revision, str)
        or not revision
    ):
        raise ValueError("strict GSM8K custody lacks protocol identity fields")
    scorer_path = Path(__file__).resolve()
    if digest(scorer_path.read_bytes()) != scorer_sha256:
        raise ValueError("strict GSM8K scoring adapter bytes do not match frozen custody")
    identity = {
        "benchmark_id": "gsm8k",
        "benchmark_version": revision,
        "license_sha256": license_sha256,
        "split_sha256": split_sha256,
        "scoring_adapter_path": SCORER_PATH,
        "scoring_adapter_sha256": scorer_sha256,
    }
    return digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-manifest", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--score-output", type=Path, required=True)
    args = parser.parse_args()
    if args.score_output.exists():
        parser.error("score output must not pre-exist")
    try:
        manifest_bytes = args.frozen_manifest.read_bytes()
        reference_bytes = args.references.read_bytes()
        prediction_bytes = args.predictions.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        rows = pq.read_table(pa.BufferReader(reference_bytes), columns=["question", "answer"]).to_pylist()
        references = {str(index): row["answer"].rsplit("####", 1)[1].strip() for index, row in enumerate(rows)}
        envelope = validate_predictions(json.loads(prediction_bytes.decode("utf-8")))
        benchmark = envelope["benchmark"]
        predictions = {}
        for row in envelope["rows"]:
            output = row.get("output")
            if not isinstance(output, dict) or output.get("kind") != "text" or not isinstance(output.get("text"), str) or row["id"] in predictions:
                raise ValueError("canonical GSM8K predictions require unique text outputs")
            predictions[row["id"]] = output["text"].rsplit("####", 1)[-1].strip()
        if (
            not references
            or len(predictions) != len(envelope["rows"])
            or set(references) != set(predictions)
            or not isinstance(manifest, dict)
            or manifest.get("result") != "PREFLIGHT_ONLY"
            or manifest.get("benchmark_id") != "gsm8k"
            or manifest.get("references_sha256") != digest(reference_bytes)
            or manifest.get("split_sha256") != digest(reference_bytes)
            or manifest.get("task_count") != len(references)
            or any(benchmark.get(key) != manifest.get(field) for key, field in (("id", "benchmark_id"), ("version", "benchmark_version"), ("split_sha256", "split_sha256"), ("protocol_sha256", "protocol_sha256")))
        ):
            raise ValueError("frozen GSM8K manifest does not bind canonical prediction identity")
        strict = manifest.get("schema_version") == STRICT_SCHEMA or any(field in manifest for field in ("checkpoint_manifest_sha256", "model_config_sha256"))
        if strict:
            expected_protocol = derived_protocol_sha256(manifest)
            if manifest.get("protocol_sha256") != expected_protocol or benchmark.get("protocol_sha256") != expected_protocol:
                raise ValueError("strict GSM8K protocol is not derived from frozen scorer custody")
            for field in ("checkpoint_manifest_sha256", "model_config_sha256"):
                if not isinstance(manifest.get(field), str) or not HASH.fullmatch(manifest[field]) or envelope.get(field) != manifest[field]:
                    raise ValueError("strict GSM8K custody does not bind canonical checkpoint/config identity")
    except (OSError, ValueError, KeyError, UnicodeDecodeError, json.JSONDecodeError, ContractError, pa.ArrowException) as error:
        parser.error(str(error))
    payload = {"result": "PREFLIGHT_ONLY", "claim_status": "NON_ADMISSIBLE_FROZEN_GSM8K_SCORER", "criterion_id": "ember-3b-reasoning-capability-v1", "criterion_result": "FAILED", "metrics": {"exact_match": sum(predictions[key] == value for key, value in references.items()) / len(references)}, "sample_count": len(references), "benchmark_id": benchmark["id"], "benchmark_version": benchmark["version"], "split_sha256": benchmark["split_sha256"], "protocol_sha256": benchmark["protocol_sha256"], "checkpoint_manifest_sha256": envelope["checkpoint_manifest_sha256"], "model_config_sha256": envelope["model_config_sha256"], "predictions_sha256": digest(prediction_bytes), "references_sha256": digest(reference_bytes), "frozen_manifest_sha256": digest(manifest_bytes)}
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