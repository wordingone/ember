#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score canonical HellaSwag choice predictions against frozen labels."""
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
STRICT_SCHEMA = "ember-restart-hellaswag-freeze-v2"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def protocol_sha256(manifest: dict[str, object], adapter_sha256: str) -> str:
    license_sha256 = manifest.get("license_sha256")
    reference_sha256 = manifest.get("references_sha256")
    version = manifest.get("benchmark_version")
    if not isinstance(license_sha256, str) or not HASH.fullmatch(license_sha256) or not isinstance(reference_sha256, str) or not HASH.fullmatch(reference_sha256) or not isinstance(version, str):
        raise ValueError("HellaSwag custody lacks license, reference, or version identity")
    return digest(f"hellaswag:{version}:{reference_sha256}:{license_sha256}:{adapter_sha256}".encode())


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
        source_rows = pq.read_table(pa.BufferReader(reference_bytes), columns=["source_id", "ind", "label"]).to_pylist()
        references = {}
        for row in source_rows:
            if not isinstance(row, dict) or not isinstance(row.get("source_id"), str) or not isinstance(row.get("ind"), int) or isinstance(row.get("ind"), bool) or not isinstance(row.get("label"), str) or not row["label"].isdigit():
                raise ValueError("HellaSwag references require complete numeric labels")
            identifier = f"{row['source_id']}:{row['ind']}"
            if identifier in references:
                raise ValueError("HellaSwag references require unique ids")
            references[identifier] = row["label"]
        if not references:
            raise ValueError("HellaSwag references must be non-empty")
        envelope = validate_predictions(json.loads(prediction_bytes.decode("utf-8")))
        benchmark = envelope["benchmark"]
        predictions = {}
        for row in envelope["rows"]:
            output = row.get("output")
            if not isinstance(output, dict) or output.get("kind") != "text" or not isinstance(output.get("text"), str) or row["id"] in predictions:
                raise ValueError("canonical HellaSwag predictions require unique text outputs")
            predictions[row["id"]] = output["text"].strip()
        if not isinstance(manifest, dict) or manifest.get("result") != "PREFLIGHT_ONLY" or manifest.get("benchmark_id") != "hellaswag" or manifest.get("references_sha256") != digest(reference_bytes) or manifest.get("split_sha256") != digest(reference_bytes) or manifest.get("task_count") != len(references) or any(benchmark.get(key) != manifest.get(field) for key, field in (("id", "benchmark_id"), ("version", "benchmark_version"), ("split_sha256", "split_sha256"), ("protocol_sha256", "protocol_sha256"))):
            raise ValueError("frozen HellaSwag manifest does not bind canonical prediction identity")
        if set(references) != set(predictions):
            raise ValueError("canonical HellaSwag predictions must exactly cover frozen ids")
        strict = manifest.get("schema_version") == STRICT_SCHEMA or any(field in manifest for field in ("checkpoint_manifest_sha256", "model_config_sha256"))
        if strict:
            for field in ("checkpoint_manifest_sha256", "model_config_sha256"):
                if not isinstance(manifest.get(field), str) or not HASH.fullmatch(manifest[field]) or envelope.get(field) != manifest[field]:
                    raise ValueError("strict HellaSwag custody does not bind canonical checkpoint/config identity")
            adapter_sha256 = manifest.get("scoring_adapter_sha256")
            if manifest.get("scoring_adapter_path") != "scripts/ember_restart_eval_hellaswag_score.py" or not isinstance(adapter_sha256, str) or not HASH.fullmatch(adapter_sha256) or digest(Path(__file__).read_bytes()) != adapter_sha256:
                raise ValueError("HellaSwag strict custody requires exact scorer identity")
            if manifest.get("protocol_sha256") != protocol_sha256(manifest, adapter_sha256):
                raise ValueError("HellaSwag protocol is not derived from scorer custody")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError, ContractError, pa.ArrowException) as error:
        parser.error(f"invalid HellaSwag scorer inputs: {error}")
    payload = {"result": "PREFLIGHT_ONLY", "claim_status": "NON_ADMISSIBLE_FROZEN_HELLASWAG_SCORER", "criterion_id": "ember-3b-reasoning-capability-v1", "criterion_result": "FAILED", "metrics": {"accuracy": sum(predictions[key] == value for key, value in references.items()) / len(references)}, "sample_count": len(references), "benchmark_id": benchmark["id"], "benchmark_version": benchmark["version"], "split_sha256": benchmark["split_sha256"], "protocol_sha256": benchmark["protocol_sha256"], "checkpoint_manifest_sha256": envelope["checkpoint_manifest_sha256"], "model_config_sha256": envelope["model_config_sha256"], "references_sha256": digest(reference_bytes), "predictions_sha256": digest(prediction_bytes), "frozen_manifest_sha256": digest(manifest_bytes), "upstream": "deterministic frozen HellaSwag exact-label scorer"}
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