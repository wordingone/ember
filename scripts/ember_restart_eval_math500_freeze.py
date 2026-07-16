#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze exact MATH-500 task bytes for non-admissible evaluator custody."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    if not COMMIT.fullmatch(arguments.revision) or not SHA256.fullmatch(arguments.protocol_sha256):
        parser.error("revision and protocol hash must be lowercase content identifiers")
    try:
        card_bytes = (arguments.dataset_root / "README.md").read_bytes()
        rows_bytes = (arguments.dataset_root / "test.jsonl").read_bytes()
        if b"license: mit" not in card_bytes.lower():
            raise ValueError("MATH-500 card must declare MIT license")
        rows = [json.loads(line) for line in rows_bytes.decode("utf-8").splitlines() if line.strip()]
        identifiers = [row.get("unique_id") if isinstance(row, dict) else None for row in rows]
        if not rows or len(set(identifiers)) != len(rows) or any(not isinstance(value, str) or not value for value in identifiers) or any(not isinstance(row.get("problem"), str) or not row["problem"] or not isinstance(row.get("answer"), str) or not row["answer"] for row in rows):
            raise ValueError("MATH-500 rows require unique ids, problems, and answers")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-math500-freeze-v1",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "FROZEN_MATH500_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS",
        "benchmark_id": "math-500",
        "benchmark_version": arguments.revision,
        "capability": "reasoning",
        "license": "MIT",
        "license_sha256": sha256(card_bytes),
        "references_sha256": sha256(rows_bytes),
        "split_sha256": sha256(rows_bytes),
        "protocol_sha256": arguments.protocol_sha256,
        "task_count": len(rows),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, prefix=arguments.output.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    os.replace(temporary, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
