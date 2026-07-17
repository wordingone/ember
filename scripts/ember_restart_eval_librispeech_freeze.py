#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze LibriSpeech clean/test references without caller-attested protocol identity."""
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
SCORER_PATH = "scripts/ember_restart_eval_audio_wer.py"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derived_protocol_sha256(revision: str, split_sha256: str, license_sha256: str, adapter_sha256: str) -> str:
    return digest(f"librispeech-clean-test:{revision}:{split_sha256}:{license_sha256}:{adapter_sha256}".encode("utf-8"))


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
    # Compatibility option retained for old packets, but never trusted or used.
    parser.add_argument("--protocol-sha256", required=False, help=argparse.SUPPRESS)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    if not COMMIT.fullmatch(arguments.revision):
        parser.error("revision must be a lowercase source commit")
    try:
        card_bytes = (arguments.dataset_root / "README.md").read_bytes()
        split_bytes = (arguments.dataset_root / SPLIT).read_bytes()
        if not has_cc_by_40_license(card_bytes):
            raise ValueError("LibriSpeech card must declare CC-BY-4.0")
        rows = pq.read_table(pa.BufferReader(split_bytes), columns=["id", "text"]).to_pylist()
        identifiers = [row.get("id") if isinstance(row, dict) else None for row in rows]
        if not rows or len(set(identifiers)) != len(rows) or any(not valid_row(row) for row in rows):
            raise ValueError("LibriSpeech rows require unique ids and nonblank transcripts")
        license_sha256 = digest(card_bytes)
        split_sha256 = digest(split_bytes)
        adapter_sha256 = digest(Path(__file__).resolve().with_name("ember_restart_eval_audio_wer.py").read_bytes())
        protocol_sha256 = derived_protocol_sha256(arguments.revision, split_sha256, license_sha256, adapter_sha256)
    except (OSError, UnicodeDecodeError, pa.ArrowException, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-librispeech-clean-test-freeze-v2",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "FROZEN_LIBRISPEECH_CLEAN_TEST_REFERENCES_NO_CHECKPOINT_BOUND_PREDICTIONS",
        "benchmark_id": "librispeech-clean-test",
        "benchmark_version": arguments.revision,
        "capability": "audio",
        "license": "CC-BY-4.0",
        "license_sha256": license_sha256,
        "references_sha256": split_sha256,
        "split_sha256": split_sha256,
        "protocol_sha256": protocol_sha256,
        "scoring_adapter_path": SCORER_PATH,
        "scoring_adapter_sha256": adapter_sha256,
        "task_count": len(rows),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, prefix=arguments.output.name + ".", suffix=".tmp", delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, arguments.output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())