#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score Harbor outcomes only against a freezer-produced task manifest."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


HASH = re.compile(r"[0-9a-f]{64}")


def _load(path: Path, label: str) -> tuple[bytes, object]:
    try:
        data = path.read_bytes()
        return data, json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {label}: {error}") from error


def _atomic(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise ValueError("score output must not pre-exist")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-task-manifest", required=True, type=Path)
    parser.add_argument("--harbor-task-results", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        manifest_bytes, frozen = _load(arguments.frozen_task_manifest, "frozen task manifest")
        result_bytes, results = _load(arguments.harbor_task_results, "Harbor task results")
        tasks = frozen.get("tasks") if isinstance(frozen, dict) else None
        if frozen.get("result") != "PREFLIGHT_ONLY" or frozen.get("benchmark_id") != "terminal-bench" or frozen.get("benchmark_version") != "2.0" or not isinstance(tasks, list) or not tasks:
            raise ValueError("frozen Terminal-Bench manifest is invalid")
        expected = {}
        for task in tasks:
            if not isinstance(task, dict) or set(task) != {"task_id", "task_toml_sha256", "docker_image_sha256"} or not isinstance(task["task_id"], str) or not HASH.fullmatch(task["task_toml_sha256"]) or not HASH.fullmatch(task["docker_image_sha256"]) or task["task_id"] in expected:
                raise ValueError("frozen Terminal-Bench task binding is invalid")
            expected[task["task_id"]] = task["docker_image_sha256"]
        if not isinstance(results, list) or len(results) != len(tasks):
            raise ValueError("Harbor results must exactly cover frozen task count")
        observed = []
        passed = 0
        for item in results:
            if not isinstance(item, dict) or not isinstance(item.get("task_id"), str) or item.get("status") not in ("passed", "failed") or not isinstance(item.get("transcript_sha256"), str) or not HASH.fullmatch(item["transcript_sha256"]) or not isinstance(item.get("task_image_sha256"), str) or not HASH.fullmatch(item["task_image_sha256"]):
                raise ValueError("each Harbor result requires task id, pass/fail, transcript hash, and image hash")
            if expected.get(item["task_id"]) != item["task_image_sha256"]:
                raise ValueError("Harbor task image does not match frozen task manifest")
            observed.append(item["task_id"])
            passed += item["status"] == "passed"
        if observed != [task["task_id"] for task in tasks]:
            raise ValueError("Harbor results must preserve exact frozen task order")
        _atomic(arguments.score_output, {"result": "SELFTEST", "metrics": {"task_success_rate": passed / len(tasks)}, "sample_count": len(tasks), "criterion_id": "ember-3b-tool-capability-v1", "criterion_result": "FAILED", "frozen_task_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "harbor_task_results_sha256": hashlib.sha256(result_bytes).hexdigest(), "upstream": "fixture-only Harbor task-outcome validator"})
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
