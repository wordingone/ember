#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verify that a pinned Spider source checkout contains no evaluation data."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

HASH = re.compile(r"[0-9a-f]{40}")
REQUIRED_SOURCE = ("evaluation.py", "LICENSE")
EVALUATION_ASSETS = ("data/dev_gold.sql", "data/tables.json", "data/database")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spider-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    if not HASH.fullmatch(arguments.expected_commit):
        parser.error("expected commit must be lowercase sha1")
    try:
        if not arguments.spider_root.is_dir() or any(not (arguments.spider_root / name).is_file() for name in REQUIRED_SOURCE):
            raise ValueError("pinned Spider source is incomplete")
        actual = subprocess.run(["git", "-C", str(arguments.spider_root), "rev-parse", "HEAD"], text=True, capture_output=True, timeout=10, check=False)
        if actual.returncode or actual.stdout.strip() != arguments.expected_commit:
            raise ValueError("Spider source commit does not match expected commit")
        present = [name for name in EVALUATION_ASSETS if (arguments.spider_root / name).exists()]
        if present:
            raise ValueError("evaluation assets are present in source-only checkout")
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-spider-source-audit-v1",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "SOURCE_ONLY_NO_FROZEN_SQL_EVALUATION_ASSETS",
        "benchmark_id": "spider",
        "source_commit": arguments.expected_commit,
        "evaluator_sha256": digest(arguments.spider_root / "evaluation.py"),
        "license_sha256": digest(arguments.spider_root / "LICENSE"),
        "missing_assets": sorted(EVALUATION_ASSETS),
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