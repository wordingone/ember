#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze exact MATH-500 task bytes without accepting caller-attested protocol identity."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
SCORER_PATH = "scripts/ember_restart_eval_math_exact.py"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def protocol_sha256(revision: str, reference_sha256: str, license_sha256: str, adapter_sha256: str) -> str:
    return sha256(f"math-500:{revision}:{reference_sha256}:{license_sha256}:{adapter_sha256}".encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    # Compatibility option retained for old packets, but never trusted or used.
    parser.add_argument("--protocol-sha256", required=False, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    if not COMMIT.fullmatch(arguments.revision):
        parser.error("revision must be a lowercase source commit")
    try:
        card_bytes = (arguments.dataset_root / "README.md").read_bytes()
        rows_bytes = (arguments.dataset_root / "test.jsonl").read_bytes()
        if b"license: mit" not in card_bytes.lower():
            raise ValueError("MATH-500 card must declare MIT license")
        rows = [json.loads(line) for line in rows_bytes.decode("utf-8").splitlines() if line.strip()]
        identifiers = [row.get("unique_id") if isinstance(row, dict) else None for row in rows]
        if (
            not rows
            or len(set(identifiers)) != len(rows)
            or any(not isinstance(value, str) or not value for value in identifiers)
            or any(
                not isinstance(row, dict)
                or not isinstance(row.get("problem"), str)
                or not row["problem"]
                or not isinstance(row.get("answer"), str)
                or not row["answer"]
                for row in rows
            )
        ):
            raise ValueError("MATH-500 rows require unique ids, problems, and answers")
        license_sha256 = sha256(card_bytes)
        reference_sha256 = sha256(rows_bytes)
        scorer_bytes = (Path(__file__).resolve().parent / "ember_restart_eval_math_exact.py").read_bytes()
        scorer_sha256 = sha256(scorer_bytes)
        derived_protocol = protocol_sha256(arguments.revision, reference_sha256, license_sha256, scorer_sha256)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-math500-freeze-v2",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "FROZEN_MATH500_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS",
        "benchmark_id": "math-500",
        "benchmark_version": arguments.revision,
        "capability": "reasoning",
        "license": "MIT",
        "license_sha256": license_sha256,
        "references_sha256": reference_sha256,
        "split_sha256": reference_sha256,
        "protocol_sha256": derived_protocol,
        "scoring_adapter_path": SCORER_PATH,
        "scoring_adapter_sha256": scorer_sha256,
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