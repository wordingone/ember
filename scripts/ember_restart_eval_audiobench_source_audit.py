#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Verify AudioBench source custody without opening a closed evaluation run."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

CUSTODY = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-audiobench-custody-v1.json"


def _git_identity(root: Path) -> dict[str, str]:
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
        tree = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("AudioBench source identity could not be read") from error
    if head.returncode or tree.returncode:
        raise ValueError("AudioBench source is not a readable Git checkout")
    return {"source_commit": head.stdout.strip(), "source_tree": tree.stdout.strip()}


def _license_sha256(root: Path) -> str:
    try:
        return hashlib.sha256((root / "LICENSE").read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError("AudioBench LICENSE is unavailable") from error


def audit_source(root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise ValueError("AudioBench source root is not a directory")
    try:
        custody = json.loads(CUSTODY.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("AudioBench custody manifest is unavailable") from error
    if not isinstance(custody, dict) or custody.get("benchmark_id") != "audiobench" or custody.get("suite") != "ab/sound-id":
        raise ValueError("AudioBench custody identity is invalid")
    identity = _git_identity(root)
    expected_commit = custody.get("upstream_commit")
    expected_tree = custody.get("upstream_tree_git_sha1")
    expected_license = custody.get("license_sha256")
    if identity["source_commit"] != expected_commit:
        raise ValueError("AudioBench source commit drifted from public custody")
    if identity["source_tree"] != expected_tree:
        raise ValueError("AudioBench source tree drifted from public custody")
    actual_license = _license_sha256(root)
    if actual_license != expected_license:
        raise ValueError("AudioBench LICENSE drifted from public custody")
    return {
        "benchmark_id": custody["benchmark_id"],
        "benchmark_version": custody.get("benchmark_version"),
        "suite": custody["suite"],
        "source_commit": identity["source_commit"],
        "source_tree": identity["source_tree"],
        "license_sha256": actual_license,
        "source_materialization": "SOURCE_ONLY_CUSTODY",
        "target_execution_permitted": False,
        "closed_run_artifact_sha256": None,
    }


def atomic_write(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise ValueError("audit output must not pre-exist")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        payload = {
            "schema_version": "ember-restart-audiobench-source-audit-v1",
            "result": "PREFLIGHT_ONLY",
            "admission": "NOT_ELIGIBLE",
            "claim_status": "AUDIOBENCH_SOURCE_CUSTODY_ONLY_NO_CLOSED_RUN",
            **audit_source(arguments.source_root),
        }
        atomic_write(arguments.output, payload)
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())