#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Audit strict MMMU source, answer, image-input, and scorer custody only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

HASH = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(data: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def answer_count(data: bytes, expected_sha: str) -> int:
    if digest(data) != expected_sha:
        raise ValueError("MMMU answer dictionary bytes do not match frozen custody")
    answers = load_json(data, "MMMU answer dictionary")
    if not answers:
        raise ValueError("MMMU answer dictionary must be non-empty")
    count = 0
    for value in answers.values():
        if not isinstance(value, dict) or value.get("question_type") != "multiple-choice":
            continue
        count += 1
    if count <= 0:
        raise ValueError("MMMU answer dictionary has no frozen multiple-choice rows")
    return count


def image_row_count(data: bytes, expected_sha: str) -> int:
    if digest(data) != expected_sha:
        raise ValueError("MMMU image-input receipt bytes do not match frozen custody")
    receipt = load_json(data, "MMMU image-input receipt")
    if (
        receipt.get("schema_version") != "ember-restart-mmmu-image-input-freeze-v1"
        or receipt.get("result") != "PREFLIGHT_ONLY"
        or receipt.get("benchmark_id") != "MMMU"
        or not isinstance(receipt.get("rows"), list)
        or receipt.get("row_count") != len(receipt["rows"])
    ):
        raise ValueError("MMMU image-input receipt is not the frozen schema")
    seen: set[str] = set()
    for row in receipt["rows"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not row["id"]
            or row["id"] in seen
            or not isinstance(row.get("image_sha256s"), list)
            or not row["image_sha256s"]
            or any(not isinstance(value, str) or not HASH.fullmatch(value) for value in row["image_sha256s"])
            or not isinstance(row.get("input_sha256"), str)
            or not HASH.fullmatch(row["input_sha256"])
        ):
            raise ValueError("MMMU image-input receipt contains an invalid row")
        seen.add(row["id"])
    return len(seen)


def audit(
    *,
    custody_bytes: bytes,
    answers_bytes: bytes,
    image_bytes: bytes,
    scorer_bytes: bytes,
    expected_scorer_bytes: bytes,
    adapter_bytes: bytes,
    expected_adapter_bytes: bytes,
) -> dict[str, object]:
    custody = load_json(custody_bytes, "MMMU custody")
    if custody.get("schema_version") != "ember-restart-benchmark-custody-v1":
        raise ValueError("MMMU custody schema is not frozen")
    if (
        custody.get("benchmark_id") != "MMMU"
        or custody.get("target_execution_permitted") is not False
        or custody.get("target_training_access") != "FORBIDDEN"
    ):
        raise ValueError("MMMU custody is not fail-closed")
    version = custody.get("benchmark_version")
    upstream_tree = custody.get("upstream_tree_git_sha1")
    license_sha = custody.get("license_sha256")
    if not isinstance(version, str) or not COMMIT.fullmatch(version) or not isinstance(upstream_tree, str) or not COMMIT.fullmatch(upstream_tree) or not isinstance(license_sha, str) or not HASH.fullmatch(license_sha):
        raise ValueError("MMMU custody lacks immutable source/license identity")
    split = custody.get("split")
    image_materialization = custody.get("image_input_materialization")
    validation_materialization = custody.get("validation_parquet_materialization")
    if not isinstance(split, dict) or not isinstance(image_materialization, dict) or not isinstance(validation_materialization, dict):
        raise ValueError("MMMU custody lacks split/image materialization")
    answer_sha = split.get("answer_dictionary_sha256")
    if not isinstance(answer_sha, str) or not HASH.fullmatch(answer_sha):
        raise ValueError("MMMU custody lacks answer-dictionary identity")
    answer_rows = answer_count(answers_bytes, answer_sha)
    image_sha = image_materialization.get("artifact_sha256")
    if not isinstance(image_sha, str) or not HASH.fullmatch(image_sha):
        raise ValueError("MMMU custody lacks image-input identity")
    image_rows = image_row_count(image_bytes, image_sha)
    if image_rows != image_materialization.get("row_count") or image_rows != validation_materialization.get("row_count", image_rows):
        raise ValueError("MMMU image-input row count does not match custody")
    scorer = custody.get("scorer")
    adapter = custody.get("scoring_adapter")
    scorer_sha = digest(scorer_bytes)
    adapter_sha = digest(adapter_bytes)
    if (
        not isinstance(scorer, dict)
        or scorer.get("sha256") != scorer_sha
        or scorer_sha != digest(expected_scorer_bytes)
        or not isinstance(adapter, dict)
        or adapter.get("path") != "scripts/ember_restart_eval_mmmu.py"
        or adapter.get("sha256") != adapter_sha
        or adapter_sha != digest(expected_adapter_bytes)
    ):
        raise ValueError("MMMU scorer or adapter bytes do not match frozen custody")
    checkpoint_sha = custody.get("checkpoint_manifest_sha256")
    config_sha = custody.get("model_config_sha256")
    if not isinstance(checkpoint_sha, str) or not HASH.fullmatch(checkpoint_sha) or not isinstance(config_sha, str) or not HASH.fullmatch(config_sha):
        raise ValueError("MMMU custody lacks checkpoint/config identity")
    expected_protocol = digest(f"MMMU:{version}:{answer_sha}:{scorer_sha}:{license_sha}:{upstream_tree}:{adapter_sha}:{image_sha}:{checkpoint_sha}:{config_sha}".encode())
    if custody.get("protocol_sha256") != expected_protocol:
        raise ValueError("MMMU protocol is not derived from complete frozen custody")
    return {
        "schema_version": "ember-restart-mmmu-runtime-audit-v1",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "FROZEN_MMMU_RUNTIME_CUSTODY",
        "benchmark_id": "MMMU",
        "benchmark_version": version,
        "answer_dictionary_sha256": answer_sha,
        "image_inputs_sha256": image_sha,
        "protocol_sha256": expected_protocol,
        "scoring_adapter_sha256": adapter_sha,
        "scorer_sha256": scorer_sha,
        "sample_count": answer_rows,
        "image_row_count": image_rows,
        "custody_manifest_sha256": digest(custody_bytes),
        "target_execution_permitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--custody-manifest", required=True, type=Path)
    parser.add_argument("--answers", required=True, type=Path)
    parser.add_argument("--image-inputs", required=True, type=Path)
    parser.add_argument("--scorer", required=True, type=Path)
    parser.add_argument("--expected-scorer", required=True, type=Path)
    parser.add_argument("--adapter", required=True, type=Path)
    parser.add_argument("--expected-adapter", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    try:
        payload = audit(custody_bytes=args.custody_manifest.read_bytes(), answers_bytes=args.answers.read_bytes(), image_bytes=args.image_inputs.read_bytes(), scorer_bytes=args.scorer.read_bytes(), expected_scorer_bytes=args.expected_scorer.read_bytes(), adapter_bytes=args.adapter.read_bytes(), expected_adapter_bytes=args.expected_adapter.read_bytes())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, prefix=args.output.name + ".", suffix=".tmp", delete=False) as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
