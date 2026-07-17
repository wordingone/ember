#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Audit MMLU-Pro custody and a supplied frozen reference artifact.

This is a bounded source/asset audit only. It never consumes checkpoint
predictions and always emits PREFLIGHT_ONLY evidence.
"""

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
PROTOCOL_PATH = "manifests/ember-restart-mmlu-pro-protocol-v1.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(data: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _reference_count(reference_bytes: bytes) -> int:
    try:
        table = pq.read_table(
            pa.BufferReader(reference_bytes),
            columns=["question_id", "options", "answer", "answer_index"],
        )
    except pa.ArrowException as error:
        raise ValueError("MMLU-Pro references must be a readable parquet artifact") from error
    rows = table.to_pylist()
    if not rows:
        raise ValueError("MMLU-Pro references must be non-empty")
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("MMLU-Pro references contain an invalid row")
        question_id = row.get("question_id")
        options = row.get("options")
        answer = row.get("answer")
        answer_index = row.get("answer_index")
        if (
            not isinstance(question_id, int)
            or isinstance(question_id, bool)
            or question_id in seen
            or not isinstance(options, list)
            or not options
            or any(not isinstance(option, str) or not option for option in options)
            or not isinstance(answer_index, int)
            or isinstance(answer_index, bool)
            or not 0 <= answer_index < len(options)
            or not isinstance(answer, str)
            or answer != chr(ord("A") + answer_index)
        ):
            raise ValueError("MMLU-Pro references require unique ids and matching answer indexes")
        seen.add(question_id)
    return len(rows)


def audit(
    *,
    custody_bytes: bytes,
    protocol_bytes: bytes,
    reference_bytes: bytes,
    scorer_bytes: bytes,
    expected_scorer_bytes: bytes,
) -> dict[str, object]:
    custody = _load_json(custody_bytes, "MMLU-Pro custody")
    protocol = _load_json(protocol_bytes, "MMLU-Pro protocol")
    if custody.get("schema_version") != "ember-restart-benchmark-custody-v1":
        raise ValueError("MMLU-Pro custody schema is not frozen")
    if (
        custody.get("benchmark_id") != "mmlu-pro"
        or custody.get("target_execution_permitted") is not False
        or custody.get("target_training_access") != "FORBIDDEN"
    ):
        raise ValueError("MMLU-Pro custody is not fail-closed")
    materialization = custody.get("materialization")
    if not isinstance(materialization, dict):
        raise ValueError("MMLU-Pro custody lacks materialization identity")
    version = custody.get("benchmark_version")
    split_sha = materialization.get("split_sha256")
    if not isinstance(version, str) or not version or not isinstance(split_sha, str) or not HASH.fullmatch(split_sha):
        raise ValueError("MMLU-Pro custody lacks benchmark/split identity")
    references_sha = digest(reference_bytes)
    if references_sha != split_sha or materialization.get("artifact_sha256") is None:
        raise ValueError("MMLU-Pro references do not match frozen split custody")
    sample_count = _reference_count(reference_bytes)
    identity_mismatches = [
        protocol.get("schema_version") != "ember-restart-mmlu-pro-protocol-v1",
        protocol.get("benchmark_id") != "mmlu-pro",
        protocol.get("benchmark_version") != version,
    ]
    if any(identity_mismatches):
        raise ValueError("MMLU-Pro protocol identity does not match custody")
    if protocol.get("custody_manifest_path") != PROTOCOL_PATH.replace("-protocol-v1", "-custody-v1"):
        raise ValueError("MMLU-Pro protocol custody path is not canonical")
    if protocol.get("custody_manifest_sha256") != digest(custody_bytes):
        raise ValueError("MMLU-Pro protocol does not bind exact custody bytes")
    if protocol.get("references_sha256") != split_sha or protocol.get("license_sha256") != custody.get("license_sha256"):
        raise ValueError("MMLU-Pro protocol does not bind split/license custody")
    scorer_sha = digest(scorer_bytes)
    if (
        scorer_sha != digest(expected_scorer_bytes)
        or scorer_sha != protocol.get("scoring_adapter_sha256")
        or scorer_sha != custody.get("scoring_adapter_sha256")
    ):
        raise ValueError("MMLU-Pro scorer bytes do not match frozen custody")
    expected_protocol = digest(f"mmlu-pro:{version}:{split_sha}:{custody.get('license_sha256')}:{scorer_sha}".encode("utf-8"))
    if protocol.get("protocol_sha256") != expected_protocol:
        raise ValueError("MMLU-Pro protocol is not derived from exact scorer/split/license custody")
    return {
        "schema_version": "ember-restart-mmlu-pro-runtime-audit-v1",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "FROZEN_MMLU_PRO_RUNTIME_CUSTODY",
        "benchmark_id": "mmlu-pro",
        "benchmark_version": version,
        "split_sha256": split_sha,
        "references_sha256": references_sha,
        "protocol_sha256": protocol["protocol_sha256"],
        "scoring_adapter_sha256": scorer_sha,
        "sample_count": sample_count,
        "custody_manifest_sha256": digest(custody_bytes),
        "protocol_manifest_sha256": digest(protocol_bytes),
        "target_execution_permitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--custody-manifest", required=True, type=Path)
    parser.add_argument("--protocol-manifest", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--scoring-adapter", required=True, type=Path)
    parser.add_argument("--expected-scoring-adapter", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    try:
        custody_bytes = args.custody_manifest.read_bytes()
        protocol_bytes = args.protocol_manifest.read_bytes()
        reference_bytes = args.references.read_bytes()
        scorer_bytes = args.scoring_adapter.read_bytes()
        expected_scorer_bytes = args.expected_scoring_adapter.read_bytes()
        payload = audit(
            custody_bytes=custody_bytes,
            protocol_bytes=protocol_bytes,
            reference_bytes=reference_bytes,
            scorer_bytes=scorer_bytes,
            expected_scorer_bytes=expected_scorer_bytes,
        )
    except (OSError, ValueError, pa.ArrowException) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=args.output.parent,
            prefix=args.output.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
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
