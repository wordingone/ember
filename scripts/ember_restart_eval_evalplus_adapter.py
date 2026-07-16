#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Convert canonical code predictions to byte-bound EvalPlus sample JSONL."""
import argparse
import gzip
import hashlib
import json
import os
import tempfile
from pathlib import Path

from ember_restart.prediction_contract import ContractError, validate_predictions


SUITES = {
    "humanevalplus_v0.1.10": "v0.1.10",
    "mbppplus_v0.2.0": "v0.2.0",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def task_ids(data: bytes) -> set[str]:
    try:
        decoded = gzip.decompress(data).decode("utf-8")
        rows = [json.loads(line) for line in decoded.splitlines() if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("frozen EvalPlus task asset must be valid gzip JSONL") from error
    ids = {row.get("task_id") for row in rows if isinstance(row, dict) and isinstance(row.get("task_id"), str) and row["task_id"]}
    if len(ids) != len(rows) or not ids:
        raise ValueError("frozen EvalPlus task asset requires unique non-empty task ids")
    return ids


def canonical_rows(data: bytes, suite: str, asset_sha256: str) -> tuple[dict, dict[str, str]]:
    try:
        envelope = validate_predictions(json.loads(data.decode("utf-8")))
    except (ContractError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("canonical checkpoint predictions are required") from error
    benchmark = envelope["benchmark"]
    if benchmark.get("id") != "evalplus" or benchmark.get("capability") != "text" or benchmark.get("version") != SUITES[suite] or benchmark.get("split_sha256") != asset_sha256:
        raise ValueError("canonical predictions do not bind frozen EvalPlus suite identity")
    rows: dict[str, str] = {}
    for row in envelope["rows"]:
        output = row.get("output")
        if not isinstance(output, dict) or output.get("kind") != "text" or not isinstance(output.get("text"), str) or row["id"] in rows:
            raise ValueError("canonical EvalPlus rows require unique code text outputs")
        rows[row["id"]] = output["text"]
    if not rows:
        raise ValueError("canonical EvalPlus predictions must be non-empty")
    return envelope, rows


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=sorted(SUITES), required=True)
    parser.add_argument("--frozen-code-manifest", required=True, type=Path)
    parser.add_argument("--task-asset", required=True, type=Path)
    parser.add_argument("--canonical-predictions", required=True, type=Path)
    parser.add_argument("--samples-output", required=True, type=Path)
    parser.add_argument("--binding-output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.samples_output.exists() or arguments.binding_output.exists():
        parser.error("EvalPlus outputs must not pre-exist")
    try:
        manifest_bytes = arguments.frozen_code_manifest.read_bytes()
        asset_bytes = arguments.task_asset.read_bytes()
        prediction_bytes = arguments.canonical_predictions.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        asset_sha256 = sha256(asset_bytes)
        asset = manifest.get("frozen_task_assets", {}).get(arguments.suite) if isinstance(manifest, dict) else None
        if manifest.get("benchmark_id") != "evalplus" or not isinstance(asset, dict) or asset.get("sha256") != asset_sha256:
            raise ValueError("frozen EvalPlus custody does not bind supplied task asset")
        ids = task_ids(asset_bytes)
        envelope, rows = canonical_rows(prediction_bytes, arguments.suite, asset_sha256)
        if ids != set(rows) or asset.get("rows") != len(ids):
            raise ValueError("canonical predictions must exactly cover frozen EvalPlus task ids")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"invalid EvalPlus adapter inputs: {error}")
    samples_bytes = b"".join((json.dumps({"task_id": task_id, "completion": rows[task_id]}, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n") for task_id in sorted(rows))
    binding = {"schema_version": "ember-restart-evalplus-samples-binding-v1", "suite": arguments.suite, "benchmark_id": envelope["benchmark"]["id"], "benchmark_version": envelope["benchmark"]["version"], "split_sha256": envelope["benchmark"]["split_sha256"], "protocol_sha256": envelope["benchmark"]["protocol_sha256"], "checkpoint_manifest_sha256": envelope["checkpoint_manifest_sha256"], "model_config_sha256": envelope["model_config_sha256"], "task_asset_sha256": asset_sha256, "evalplus_dataset_md5": hashlib.md5(gzip.decompress(asset_bytes)).hexdigest(), "predictions_sha256": sha256(prediction_bytes), "samples_sha256": sha256(samples_bytes), "task_ids_sha256": sha256(("\n".join(sorted(rows)) + "\n").encode("utf-8")), "sample_count": len(rows), "frozen_code_manifest_sha256": sha256(manifest_bytes), "result": "PREFLIGHT_ONLY"}
    binding_bytes = (json.dumps(binding, sort_keys=True) + "\n").encode("utf-8")
    try:
        atomic_write(arguments.samples_output, samples_bytes)
        atomic_write(arguments.binding_output, binding_bytes)
    except OSError as error:
        arguments.samples_output.unlink(missing_ok=True)
        arguments.binding_output.unlink(missing_ok=True)
        parser.error(f"could not publish EvalPlus outputs: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
