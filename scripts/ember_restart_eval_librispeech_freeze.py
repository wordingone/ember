#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze the pinned LibriSpeech clean/test references without scoring them."""
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
import yaml

COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SPLIT = Path("clean/test/0000.parquet")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def has_cc_by_40_license(card_bytes: bytes) -> bool:
    text = card_bytes.decode("utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return False
    end = text.find("\n---", 4)
    if end < 0:
        return False
    metadata = yaml.safe_load(text[4:end])
    if not isinstance(metadata, dict):
        return False
    license_value = metadata.get("license")
    values = license_value if isinstance(license_value, list) else [license_value]
    return all(isinstance(value, str) for value in values) and "cc-by-4.0" in values


def valid_row(row: object) -> bool:
    return isinstance(row, dict) and all(isinstance(row.get(field), str) and row[field].strip() for field in ("id", "text"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    if not COMMIT.fullmatch(arguments.revision) or not SHA256.fullmatch(arguments.protocol_sha256):
        parser.error("revision and protocol hash must be lowercase content identifiers")
    try:
        card_bytes = (arguments.dataset_root / "README.md").read_bytes()
        split_bytes = (arguments.dataset_root / SPLIT).read_bytes()
        if not has_cc_by_40_license(card_bytes):
            raise ValueError("LibriSpeech card must declare CC-BY-4.0")
        rows = pq.read_table(pa.BufferReader(split_bytes), columns=["id", "text"]).to_pylist()
        identifiers = [row.get("id") if isinstance(row, dict) else None for row in rows]
        if not rows or len(set(identifiers)) != len(rows) or any(not valid_row(row) for row in rows):
            raise ValueError("LibriSpeech rows require unique ids and nonblank transcripts")
    except (OSError, UnicodeDecodeError, pa.ArrowException, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-librispeech-clean-test-freeze-v1",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "FROZEN_LIBRISPEECH_CLEAN_TEST_REFERENCES_NO_CHECKPOINT_BOUND_PREDICTIONS",
        "benchmark_id": "librispeech-clean-test",
        "benchmark_version": arguments.revision,
        "capability": "audio",
        "license": "CC-BY-4.0",
        "license_sha256": digest(card_bytes),
        "references_sha256": digest(split_bytes),
        "split_sha256": digest(split_bytes),
        "protocol_sha256": arguments.protocol_sha256,
        "task_count": len(rows),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, prefix=arguments.output.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, arguments.output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())