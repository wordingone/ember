#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze only locally runnable, digest-pinned Terminal-Bench task metadata."""
import argparse
import hashlib
import json
import os
import re
import tempfile
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 evaluator runtime
    import tomli as tomllib
from pathlib import Path


IMAGE = re.compile(r".+@sha256:([0-9a-f]{64})$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise ValueError("frozen task output must not pre-exist")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _task(root: Path, task_id: str) -> dict[str, str]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", task_id):
        raise ValueError("Terminal-Bench task id is invalid")
    path = root / task_id / "task.toml"
    try:
        task_bytes = path.read_bytes()
        task = tomllib.loads(task_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"invalid Terminal-Bench task metadata: {error}") from error
    declared = task.get("task") if isinstance(task, dict) else None
    environment = task.get("environment") if isinstance(task, dict) else None
    image = environment.get("docker_image") if isinstance(environment, dict) else None
    match = IMAGE.fullmatch(image) if isinstance(image, str) else None
    if not isinstance(declared, dict) or declared.get("name") != f"terminal-bench/{task_id}":
        raise ValueError("Terminal-Bench task identity does not match its frozen path")
    if match is None:
        raise ValueError("Terminal-Bench task image must be content-addressed by sha256")
    if environment.get("allow_internet") is not False:
        raise ValueError("Terminal-Bench task must disable network access for owned evaluation")
    return {"task_id": task_id, "task_toml_sha256": hashlib.sha256(task_bytes).hexdigest(), "docker_image_sha256": match.group(1)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--task-id", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if not arguments.task_root.is_dir() or len(set(arguments.task_id)) != len(arguments.task_id):
            raise ValueError("Terminal-Bench frozen task selection is invalid")
        tasks = [_task(arguments.task_root, task_id) for task_id in sorted(arguments.task_id)]
        _atomic(arguments.output, {"goal_id": "EMBER-02", "workstream_id": "EMBER-02C", "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember", "result": "PREFLIGHT_ONLY", "benchmark_id": "terminal-bench", "benchmark_version": "2.0", "tasks": tasks})
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
