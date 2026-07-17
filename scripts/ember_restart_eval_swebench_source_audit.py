#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verify that a pinned SWE-bench source checkout contains no task release."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

HASH = re.compile(r"[0-9a-f]{40}")
REQUIRED_SOURCE = ("LICENSE", "README.md", "swebench/harness/run_evaluation.py")
TASK_RELEASE_PATHS = ("data", "datasets", "swebench_lite.json", "swebench_verified.json")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def swebench_protocol_sha256(source_commit: str, harness_sha256: str, license_sha256: str) -> str:
    """Derive a stable source-only protocol identity from exact custody bytes."""
    identity = {
        "benchmark_id": "swe-bench",
        "benchmark_version": source_commit,
        "source_commit": source_commit,
        "harness_sha256": harness_sha256,
        "license_sha256": license_sha256,
        "task_release": "ABSENT",
        "claim_status": "SOURCE_ONLY_NO_FROZEN_SWEBENCH_TASK_RELEASE",
        "admission": "NOT_EXECUTABLE_UNDECLARED_DATASET_LICENSE_AND_NO_OFFLINE_SANDBOX",
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--swebench-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    if not HASH.fullmatch(arguments.expected_commit):
        parser.error("expected commit must be lowercase sha1")
    try:
        if not arguments.swebench_root.is_dir() or any(not (arguments.swebench_root / name).is_file() for name in REQUIRED_SOURCE):
            raise ValueError("pinned SWE-bench source is incomplete")
        actual = subprocess.run(["git", "-C", str(arguments.swebench_root), "rev-parse", "HEAD"], text=True, capture_output=True, timeout=10, check=False)
        if actual.returncode or actual.stdout.strip() != arguments.expected_commit:
            raise ValueError("SWE-bench source commit does not match expected commit")
        clean = subprocess.run(["git", "-C", str(arguments.swebench_root), "status", "--porcelain=v1", "--untracked-files=all"], text=True, capture_output=True, timeout=10, check=False)
        if clean.returncode or clean.stdout.strip():
            raise ValueError("SWE-bench source working tree must be clean")
        present = [name for name in TASK_RELEASE_PATHS if (arguments.swebench_root / name).exists()]
        release_names = {"swebench_lite.json", "swebench_verified.json"}
        present.extend(path.relative_to(arguments.swebench_root).as_posix() for path in arguments.swebench_root.rglob("*") if path.is_file() and path.name.lower() in release_names)
        if present:
            raise ValueError("task-release assets are present in source-only checkout")
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-swebench-source-audit-v1",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "SOURCE_ONLY_NO_FROZEN_SWEBENCH_TASK_RELEASE",
        "benchmark_id": "swe-bench",
        "capability_families": ["code", "files"],
        "source_commit": arguments.expected_commit,
        "benchmark_version": arguments.expected_commit,
        "harness_sha256": digest(arguments.swebench_root / "swebench/harness/run_evaluation.py"),
        "license_sha256": digest(arguments.swebench_root / "LICENSE"),
        "protocol_sha256": swebench_protocol_sha256(arguments.expected_commit, digest(arguments.swebench_root / "swebench/harness/run_evaluation.py"), digest(arguments.swebench_root / "LICENSE")),
        "protocol_derivation": "sha256(canonical benchmark/source/harness/license/task-release/admission identity)",
        "missing_task_release_paths": sorted(TASK_RELEASE_PATHS),
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
