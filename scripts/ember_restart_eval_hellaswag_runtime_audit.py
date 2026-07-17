#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Audit HellaSwag custody and scorer bytes without executing a checkpoint."""
from __future__ import annotations

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
PROTOCOL_PATH = "manifests/ember-restart-hellaswag-protocol-v1.json"
SCORER_PATH = "scripts/ember_restart_eval_hellaswag_score.py"


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


def reference_count(data: bytes) -> int:
    try:
        rows = pq.read_table(
            pa.BufferReader(data),
            columns=["ind", "source_id", "ctx", "endings", "label"],
        ).to_pylist()
    except pa.ArrowException as error:
        raise ValueError("HellaSwag references must be a readable parquet artifact") from error
    if not rows:
        raise ValueError("HellaSwag references must be non-empty")
    seen: set[tuple[object, object]] = set()
    labels: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("HellaSwag references contain an invalid row")
        row_id = (row.get("source_id"), row.get("ind"))
        endings = row.get("endings")
        label = row.get("label")
        if (
            not isinstance(row.get("ind"), int)
            or isinstance(row.get("ind"), bool)
            or not isinstance(row.get("source_id"), str)
            or not row["source_id"]
            or row_id in seen
            or not isinstance(row.get("ctx"), str)
            or not row["ctx"]
            or not isinstance(endings, list)
            or not endings
            or any(not isinstance(item, str) or not item for item in endings)
            or not isinstance(label, str)
        ):
            raise ValueError("HellaSwag references require unique ids and valid endings")
        seen.add(row_id)
        labels.append(label)
    labels_withheld = all(label == "" for label in labels)
    labels_complete = all(label.isdigit() and int(label) < len(row["endings"]) for label, row in zip(labels, rows))
    if not labels_withheld and not labels_complete:
        raise ValueError("HellaSwag labels must be uniformly withheld or in range")
    return len(rows)


def audit(
    *,
    custody_bytes: bytes,
    protocol_bytes: bytes,
    reference_bytes: bytes,
    license_bytes: bytes,
    scorer_bytes: bytes,
    expected_scorer_bytes: bytes,
) -> dict[str, object]:
    custody = load_json(custody_bytes, "HellaSwag custody")
    protocol = load_json(protocol_bytes, "HellaSwag protocol")
    if custody.get("schema_version") != "ember-restart-benchmark-custody-v1":
        raise ValueError("HellaSwag custody schema is not frozen")
    if (
        custody.get("benchmark_id") != "hellaswag"
        or custody.get("target_execution_permitted") is not False
        or custody.get("target_training_access") != "FORBIDDEN"
    ):
        raise ValueError("HellaSwag custody is not fail-closed")
    materialization = custody.get("materialization")
    if not isinstance(materialization, dict):
        raise ValueError("HellaSwag custody lacks materialization identity")
    version = materialization.get("upstream_revision")
    split_sha = materialization.get("split_sha256")
    if not isinstance(version, str) or not version or not isinstance(split_sha, str) or not HASH.fullmatch(split_sha):
        raise ValueError("HellaSwag custody lacks benchmark/split identity")
    references_sha = digest(reference_bytes)
    if references_sha != split_sha:
        raise ValueError("HellaSwag references do not match frozen split custody")
    sample_count = reference_count(reference_bytes)
    license_sha = digest(license_bytes)
    if custody.get("license_sha256") != license_sha:
        raise ValueError("HellaSwag license bytes do not match frozen custody")
    if (
        protocol.get("schema_version") != "ember-restart-hellaswag-protocol-v1"
        or protocol.get("benchmark_id") != "hellaswag"
        or protocol.get("benchmark_revision") != version
        or protocol.get("references_sha256") != split_sha
        or protocol.get("split_sha256") != split_sha
        or protocol.get("license_sha256") != license_sha
    ):
        raise ValueError("HellaSwag protocol identity does not match custody")
    scoring = protocol.get("scoring_adapter")
    scorer_sha = digest(scorer_bytes)
    if (
        scorer_sha != digest(expected_scorer_bytes)
        or not isinstance(scoring, dict)
        or scoring.get("path") != SCORER_PATH
        or scoring.get("sha256") != scorer_sha
    ):
        raise ValueError("HellaSwag scorer bytes do not match frozen custody")
    expected_protocol = digest(f"hellaswag:{version}:{split_sha}:{license_sha}:{scorer_sha}".encode("utf-8"))
    if protocol.get("protocol_sha256") != expected_protocol:
        raise ValueError("HellaSwag protocol is not derived from exact scorer/split/license custody")
    return {
        "schema_version": "ember-restart-hellaswag-runtime-audit-v1",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "FROZEN_HELLASWAG_RUNTIME_CUSTODY",
        "benchmark_id": "hellaswag",
        "benchmark_version": version,
        "split_sha256": split_sha,
        "references_sha256": references_sha,
        "license_sha256": license_sha,
        "protocol_sha256": expected_protocol,
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
    parser.add_argument("--license-card", required=True, type=Path)
    parser.add_argument("--scoring-adapter", required=True, type=Path)
    parser.add_argument("--expected-scoring-adapter", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    try:
        payload = audit(
            custody_bytes=args.custody_manifest.read_bytes(),
            protocol_bytes=args.protocol_manifest.read_bytes(),
            reference_bytes=args.references.read_bytes(),
            license_bytes=args.license_card.read_bytes(),
            scorer_bytes=args.scoring_adapter.read_bytes(),
            expected_scorer_bytes=args.expected_scoring_adapter.read_bytes(),
        )
    except (OSError, ValueError, pa.ArrowException) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=args.output.parent, prefix=args.output.name + ".", suffix=".tmp", delete=False
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
