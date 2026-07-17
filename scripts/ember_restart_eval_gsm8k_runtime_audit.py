#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Audit GSM8K frozen references and exact scorer custody without predictions."""

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


HASH = re.compile(r"[0-9a-f]{64}")
SCORER_PATH = "scripts/ember_restart_eval_gsm8k_score.py"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load(data: bytes) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("GSM8K custody must be UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError("GSM8K custody must be a JSON object")
    return value


def _reference_count(data: bytes) -> int:
    try:
        rows = pq.read_table(pa.BufferReader(data), columns=["question", "answer"]).to_pylist()
    except pa.ArrowException as error:
        raise ValueError("GSM8K references must be readable parquet") from error
    if not rows or any(not isinstance(row, dict) or not isinstance(row.get("question"), str) or not row["question"] or not isinstance(row.get("answer"), str) or "####" not in row["answer"] for row in rows):
        raise ValueError("GSM8K references require non-empty question/answer rows")
    return len(rows)


def audit(*, custody_bytes: bytes, reference_bytes: bytes, scorer_bytes: bytes) -> dict[str, object]:
    custody = _load(custody_bytes)
    if custody.get("schema_version") != "ember-restart-benchmark-custody-v1" or custody.get("benchmark_id") != "gsm8k" or custody.get("target_execution_permitted") is not False or custody.get("target_training_access") != "FORBIDDEN":
        raise ValueError("GSM8K custody is not fail-closed")
    materialization = custody.get("materialization")
    if not isinstance(materialization, dict):
        raise ValueError("GSM8K custody lacks materialization identity")
    version = custody.get("benchmark_version")
    split_sha = custody.get("split_sha256")
    if not isinstance(version, str) or not version or not isinstance(split_sha, str) or not HASH.fullmatch(split_sha):
        raise ValueError("GSM8K custody lacks benchmark/split identity")
    references_sha = digest(reference_bytes)
    if references_sha != split_sha or materialization.get("split_sha256") != split_sha or materialization.get("artifact_sha256") is None:
        raise ValueError("GSM8K references do not match frozen split custody")
    sample_count = _reference_count(reference_bytes)
    scorer_sha = digest(scorer_bytes)
    if custody.get("scoring_adapter_path") != SCORER_PATH or custody.get("scoring_adapter_sha256") != scorer_sha:
        raise ValueError("GSM8K scorer bytes do not match frozen custody")
    license_sha = custody.get("license_sha256")
    expected_protocol = digest(json.dumps({"benchmark_id": "gsm8k", "benchmark_version": version, "license_sha256": license_sha, "split_sha256": split_sha, "scoring_adapter_path": SCORER_PATH, "scoring_adapter_sha256": scorer_sha}, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    if custody.get("protocol_sha256") != expected_protocol:
        raise ValueError("GSM8K protocol is not derived from exact scorer/split custody")
    return {"schema_version": "ember-restart-gsm8k-runtime-audit-v1", "result": "PREFLIGHT_ONLY", "claim_status": "FROZEN_GSM8K_RUNTIME_CUSTODY", "benchmark_id": "gsm8k", "benchmark_version": version, "split_sha256": split_sha, "references_sha256": references_sha, "protocol_sha256": custody["protocol_sha256"], "scoring_adapter_sha256": scorer_sha, "sample_count": sample_count, "custody_manifest_sha256": digest(custody_bytes), "target_execution_permitted": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--custody-manifest", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--scoring-adapter", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    try:
        custody_bytes = args.custody_manifest.read_bytes()
        reference_bytes = args.references.read_bytes()
        scorer_bytes = args.scoring_adapter.read_bytes()
        payload = audit(custody_bytes=custody_bytes, reference_bytes=reference_bytes, scorer_bytes=scorer_bytes)
    except (OSError, ValueError, pa.ArrowException) as error:
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
