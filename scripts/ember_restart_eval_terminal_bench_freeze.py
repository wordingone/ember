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
CUSTODY = Path(__file__).resolve().parents[1] / 'manifests' / 'ember-restart-terminal-bench-custody-v1.json'
SCORER = Path(__file__).resolve().with_name('ember_restart_eval_terminal_bench.py')

def _protocol_sha256(identity: dict[str, object]) -> str:
    material = json.dumps(identity, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(material).hexdigest()

def _custody_identity() -> dict[str, object]:
    try:
        custody = json.loads(CUSTODY.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Terminal-Bench custody manifest is invalid: {error}') from error
    adapter = custody.get('scoring_adapter') if isinstance(custody, dict) else None
    if not isinstance(custody, dict) or not isinstance(adapter, dict):
        raise ValueError('Terminal-Bench custody manifest lacks adapter identity')
    adapter_sha = hashlib.sha256(SCORER.read_bytes()).hexdigest()
    if custody.get('benchmark_id') != 'terminal-bench' or custody.get('benchmark_version') != '2.0' or not isinstance(custody.get('source_commit'), str) or not isinstance(custody.get('source_tree'), str) or not isinstance(custody.get('license_sha256'), str) or adapter.get('path') != 'scripts/ember_restart_eval_terminal_bench.py' or adapter.get('sha256') != adapter_sha:
        raise ValueError('Terminal-Bench custody identity does not match current scorer')
    identity = {'benchmark_id': 'terminal-bench', 'benchmark_version': '2.0', 'source_commit': custody['source_commit'], 'source_tree': custody['source_tree'], 'license_sha256': custody['license_sha256'], 'scoring_adapter_path': adapter['path'], 'scoring_adapter_sha256': adapter_sha}
    if custody.get('protocol_sha256') != _protocol_sha256(identity):
        raise ValueError('Terminal-Bench custody protocol identity is stale or substituted')
    return identity


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
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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
        identity = _custody_identity()
        _atomic(arguments.output, {"goal_id": "EMBER-02", "workstream_id": "EMBER-02C", "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember", "schema_version": "ember-restart-terminal-bench-freeze-v2", "result": "PREFLIGHT_ONLY", **identity, "protocol_sha256": _protocol_sha256(identity), "tasks": tasks})
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
