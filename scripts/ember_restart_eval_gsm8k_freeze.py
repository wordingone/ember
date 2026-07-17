#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze GSM8K main/test bytes without accepting caller-attested protocol identity."""
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
SPLIT = Path("main/test-00000-of-00001.parquet")
SCORER_PATH = "scripts/ember_restart_eval_gsm8k_score.py"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def protocol_sha256(revision: str, license_sha256: str, split_sha256: str, scorer_sha256: str) -> str:
    identity = {
        "benchmark_id": "gsm8k",
        "benchmark_version": revision,
        "license_sha256": license_sha256,
        "split_sha256": split_sha256,
        "scoring_adapter_path": SCORER_PATH,
        "scoring_adapter_sha256": scorer_sha256,
    }
    return digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def has_mit(card: bytes) -> bool:
    text = card.decode("utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return False
    end = text.find("\n---", 4)
    if end < 0:
        return False
    value = yaml.safe_load(text[4:end])
    if not isinstance(value, dict):
        return False
    license_value = value.get("license")
    values = license_value if isinstance(license_value, list) else [license_value]
    return all(isinstance(item, str) for item in values) and "mit" in {item.lower() for item in values}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    # Kept as a compatibility option for old packets, but never trusted or used.
    parser.add_argument("--protocol-sha256", required=False, help=argparse.SUPPRESS)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    if not COMMIT.fullmatch(args.revision):
        parser.error("revision must be a lowercase source commit")
    try:
        card_bytes = (args.dataset_root / "README.md").read_bytes()
        split_bytes = (args.dataset_root / SPLIT).read_bytes()
        if not has_mit(card_bytes):
            raise ValueError("GSM8K card must declare MIT license")
        rows = pq.read_table(pa.BufferReader(split_bytes), columns=["question", "answer"]).to_pylist()
        questions = [row.get("question") if isinstance(row, dict) else None for row in rows]
        if (
            not rows
            or len(set(questions)) != len(rows)
            or any(
                not isinstance(row, dict)
                or not isinstance(row.get("question"), str)
                or not row["question"]
                or not isinstance(row.get("answer"), str)
                or "####" not in row["answer"]
                or not row["answer"].rsplit("####", 1)[1].strip()
                for row in rows
            )
        ):
            raise ValueError("GSM8K rows require unique questions and final answer markers")
        license_sha256 = digest(card_bytes)
        split_sha256 = digest(split_bytes)
        scorer_bytes = (Path(__file__).resolve().parent / "ember_restart_eval_gsm8k_score.py").read_bytes()
        scorer_sha256 = digest(scorer_bytes)
        derived_protocol = protocol_sha256(args.revision, license_sha256, split_sha256, scorer_sha256)
    except (OSError, UnicodeDecodeError, pa.ArrowException, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-gsm8k-freeze-v2",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "FROZEN_GSM8K_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS",
        "benchmark_id": "gsm8k",
        "benchmark_version": args.revision,
        "capability": "reasoning",
        "license": "MIT",
        "license_sha256": license_sha256,
        "references_sha256": split_sha256,
        "split_sha256": split_sha256,
        "protocol_sha256": derived_protocol,
        "scoring_adapter_path": SCORER_PATH,
        "scoring_adapter_sha256": scorer_sha256,
        "task_count": len(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, prefix=args.output.name + ".", suffix=".tmp", delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())