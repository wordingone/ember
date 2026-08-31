#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score text predictions only against a hash-bound frozen reference manifest."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from ember_restart.prediction_contract import ContractError, validate_predictions

HASH = re.compile(r"[0-9a-f]{64}")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_rows(data: bytes) -> dict[str, str]:
    raw = data.decode("utf-8")
    try:
        parsed = json.loads(raw)
        values = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        values = [json.loads(line) for line in raw.splitlines() if line.strip()]
    rows: dict[str, str] = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"] or not isinstance(value.get("answer"), str) or value["id"] in rows:
            raise ValueError("each row needs a unique non-empty id and answer")
        rows[value["id"]] = value["answer"]
    if not rows:
        raise ValueError("rows must be non-empty")
    return rows


def read_predictions(data: bytes) -> tuple[dict[str, object], dict[str, str]]:
    try:
        envelope = validate_predictions(json.loads(data.decode("utf-8")))
    except (ContractError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("canonical checkpoint predictions are required") from error
    benchmark = envelope["benchmark"]
    if benchmark.get("capability") != "text":
        raise ValueError("canonical predictions must declare text capability")
    rows: dict[str, str] = {}
    for row in envelope["rows"]:
        output = row.get("output")
        if not isinstance(output, dict) or output.get("kind") != "text" or not isinstance(output.get("text"), str) or row["id"] in rows:
            raise ValueError("canonical text predictions are malformed")
        rows[row["id"]] = output["text"]
    if not rows:
        raise ValueError("canonical text predictions must be non-empty")
    return envelope, rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-text-manifest", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.score_output.exists():
        parser.error("score output must not pre-exist")
    try:
        manifest_bytes = arguments.frozen_text_manifest.read_bytes()
        reference_bytes = arguments.references.read_bytes()
        prediction_bytes = arguments.predictions.read_bytes()
        manifest_sha256 = _sha256_bytes(manifest_bytes)
        references_sha256 = _sha256_bytes(reference_bytes)
        predictions_sha256 = _sha256_bytes(prediction_bytes)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        references = read_rows(reference_bytes)
        envelope, predictions = read_predictions(prediction_bytes)
        benchmark = envelope["benchmark"]
        identity_fields = ("checkpoint_manifest_sha256", "model_config_sha256", "split_sha256", "protocol_sha256")
        if not isinstance(manifest, dict) or manifest.get("result") != "PREFLIGHT_ONLY" or manifest.get("benchmark_id") != "local-text" or manifest.get("benchmark_version") != "1" or manifest.get("references_sha256") != references_sha256 or not HASH.fullmatch(manifest.get("references_sha256", "")):
            raise ValueError("frozen text manifest does not bind the supplied references")
        if any(not isinstance(manifest.get(field), str) or not HASH.fullmatch(manifest[field]) for field in identity_fields) or manifest["checkpoint_manifest_sha256"] != envelope["checkpoint_manifest_sha256"] or manifest["model_config_sha256"] != envelope["model_config_sha256"] or manifest["benchmark_id"] != benchmark["id"] or manifest["benchmark_version"] != benchmark["version"] or manifest["split_sha256"] != benchmark["split_sha256"] or manifest["protocol_sha256"] != benchmark["protocol_sha256"]:
            raise ValueError("frozen text manifest does not bind canonical prediction identity")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"invalid local answer artifacts: {error}")
    if references.keys() != predictions.keys():
        parser.error("predictions must exactly cover the frozen reference ids")
    correct = sum(references[key] == predictions[key] for key in references)
    payload = {"criterion_id": "ember-3b-text-capability-v1", "criterion_result": "FAILED", "metrics": {"exact_match": correct / len(references)}, "sample_count": len(references), "references_sha256": references_sha256, "predictions_sha256": predictions_sha256, "frozen_text_manifest_sha256": manifest_sha256, "upstream": "deterministic local frozen-answer scorer"}
    arguments.score_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.score_output.parent, delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, arguments.score_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
