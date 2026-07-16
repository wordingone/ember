#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze Spider validation pair bytes without authorizing SQL execution."""
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
SPLIT = Path("spider/validation-00000-of-00001.parquet")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def has_cc_by_sa_license(card_bytes: bytes) -> bool:
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
    return all(isinstance(value, str) for value in values) and "cc-by-sa-4.0" in values



def derived_protocol_sha256(revision: str, split_sha256: str, license_sha256: str) -> str:
    adapter = Path(__file__).with_name("ember_restart_eval_spider.py")
    adapter_sha256 = digest(adapter.read_bytes())
    identity = {
        "benchmark_id": "spider",
        "benchmark_version": revision,
        "split_sha256": split_sha256,
        "license_sha256": license_sha256,
        "scoring_adapter": {"path": "scripts/ember_restart_eval_spider.py", "sha256": adapter_sha256},
        "admission": "NOT_EXECUTABLE_NO_FROZEN_DATABASE_ASSETS",
    }
    return digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8"))

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
        if not has_cc_by_sa_license(card_bytes):
            raise ValueError("Spider card must declare CC-BY-SA-4.0")
        split_sha256 = digest(split_bytes)
        license_sha256 = digest(card_bytes)
        expected_protocol_sha256 = derived_protocol_sha256(arguments.revision, split_sha256, license_sha256)
        if arguments.protocol_sha256 != expected_protocol_sha256:
            raise ValueError("protocol hash is not derived from frozen Spider split/license/scorer custody")
        table = pq.read_table(pa.BufferReader(split_bytes), columns=["db_id", "question", "query"])
        rows = table.to_pylist()
        identifiers = [(row.get("db_id"), row.get("question"), row.get("query")) for row in rows]
        if not rows or len(set(identifiers)) != len(rows) or any(any(not isinstance(value, str) or not value for value in identifier) for identifier in identifiers):
            raise ValueError("Spider validation rows require unique nonempty db_id, question, and query")
    except (OSError, UnicodeDecodeError, pa.ArrowException, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-spider-validation-freeze-v1",
        "result": "PREFLIGHT_ONLY",
        "admission": "NOT_EXECUTABLE_NO_FROZEN_DATABASE_ASSETS",
        "claim_status": "FROZEN_SPIDER_VALIDATION_PAIRS_NO_DATABASE_EXECUTION",
        "benchmark_id": "spider",
        "benchmark_version": arguments.revision,
        "capability": "sql",
        "license": "CC-BY-SA-4.0",
        "license_sha256": license_sha256,
        "references_sha256": split_sha256,
        "split_sha256": split_sha256,
        "scoring_adapter": {"path": "scripts/ember_restart_eval_spider.py", "sha256": digest(Path(__file__).with_name("ember_restart_eval_spider.py").read_bytes())},
        "protocol_sha256": expected_protocol_sha256,
        "task_count": len(rows),
        "missing_execution_assets": ["gold_sql", "tables_json", "database_directory"],
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
