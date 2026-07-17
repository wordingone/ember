#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Audit a pinned Terminal-Bench source cache without executing any task."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 evaluator fallback
    import tomli as tomllib

CUSTODY = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-terminal-bench-custody-v1.json"
HASH = re.compile(r"^[0-9a-f]{64}$")
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
IMAGE = re.compile(r"^.+@sha256:([0-9a-f]{64})$")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_task(path: Path) -> dict[str, object]:
    task_id = path.parent.name
    if not TASK_ID.fullmatch(task_id):
        raise ValueError("Terminal-Bench task identity is invalid")
    try:
        raw = path.read_bytes()
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"invalid Terminal-Bench task metadata: {error}") from error
    declared = parsed.get("task") if isinstance(parsed, dict) else None
    environment = parsed.get("environment") if isinstance(parsed, dict) else None
    image = environment.get("docker_image") if isinstance(environment, dict) else None
    allow_internet = environment.get("allow_internet") if isinstance(environment, dict) else None
    if not isinstance(declared, dict) or declared.get("name") != f"terminal-bench/{task_id}":
        raise ValueError("Terminal-Bench task identity does not match its path")
    if not isinstance(image, str) or not image:
        raise ValueError("Terminal-Bench task image is missing")
    if not isinstance(allow_internet, bool):
        raise ValueError("Terminal-Bench allow_internet must be boolean")
    match = IMAGE.fullmatch(image)
    return {
        "task_id": task_id,
        "task_toml_sha256": _sha256_bytes(raw),
        "image_identity": image,
        "digest_pinned": match is not None,
        "network_disabled": allow_internet is False,
    }


def audit_task_root(root: Path) -> dict[str, object]:
    if not root.is_dir():
        raise ValueError("Terminal-Bench task root is not a directory")
    paths = sorted(root.glob("*/task.toml"), key=lambda item: item.parent.name)
    if not paths:
        raise ValueError("Terminal-Bench task root contains no task metadata")
    records = [_read_task(path) for path in paths]
    digest_count = sum(bool(record["digest_pinned"]) for record in records)
    network_disabled_count = sum(bool(record["network_disabled"]) for record in records)
    eligible_count = sum(bool(record["digest_pinned"] and record["network_disabled"]) for record in records)
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "task_count": len(records),
        "digest_pinned_image_task_count": digest_count,
        "network_disabled_task_count": network_disabled_count,
        "eligible_task_count": eligible_count,
        "task_manifest_sha256": _sha256_bytes(canonical),
        "target_execution_permitted": False,
    }


def _source_identity(root: Path) -> dict[str, str]:
    try:
        custody = json.loads(CUSTODY.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Terminal-Bench custody manifest is unavailable") from error
    if not isinstance(custody, dict) or custody.get("benchmark_id") != "terminal-bench" or custody.get("benchmark_version") != "2.0":
        raise ValueError("Terminal-Bench custody identity is invalid")
    expected = {key: custody.get(key) for key in ("source_commit", "source_tree", "license_sha256")}
    if any(not isinstance(value, str) or not value for value in expected.values()):
        raise ValueError("Terminal-Bench custody identity is incomplete")
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
        tree = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("Terminal-Bench source identity could not be verified") from error
    if head.returncode or tree.returncode or head.stdout.strip() != expected["source_commit"] or tree.stdout.strip() != expected["source_tree"]:
        raise ValueError("Terminal-Bench source commit/tree drifted from public custody")
    license_path = root / "LICENSE"
    try:
        license_sha = _sha256_bytes(license_path.read_bytes())
    except OSError as error:
        raise ValueError("Terminal-Bench LICENSE is unavailable") from error
    if license_sha != expected["license_sha256"]:
        raise ValueError("Terminal-Bench LICENSE drifted from public custody")
    return expected


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
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        identity = _source_identity(arguments.task_root)
        audit = audit_task_root(arguments.task_root)
        payload = {
            "schema_version": "ember-restart-terminal-bench-cache-audit-v1",
            "result": "PREFLIGHT_ONLY",
            "admission": "NOT_ELIGIBLE",
            "claim_status": "TERMINAL_BENCH_CACHE_AUDIT_NO_ELIGIBLE_OFFLINE_TASKS" if audit["eligible_task_count"] == 0 else "TERMINAL_BENCH_CACHE_AUDIT_ELIGIBLE_TASKS_PRESENT_BUT_NOT_ADMITTED",
            **identity,
            **audit,
        }
        atomic_write(arguments.output, payload)
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())