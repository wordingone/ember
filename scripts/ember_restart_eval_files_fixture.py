#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic files-family patch binding selftest; never claim-bearing."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

HASH = re.compile(r"[0-9a-f]{64}")


def read_json_once(path: Path) -> tuple[bytes, object]:
    try:
        payload = path.read_bytes()
        return payload, json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON input: {error}") from error


def validate_tasks(value: object, schema: str) -> list[dict]:
    required = {"schema_version", "tasks"} if schema == "ember-restart-files-output-v1" else {"schema_version", "result", "benchmark_id", "benchmark_version", "tasks"}
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != schema or not isinstance(value["tasks"], list) or not value["tasks"]:
        raise ValueError("invalid files fixture/output envelope")
    tasks = []
    seen = set()
    for task in value["tasks"]:
        if not isinstance(task, dict) or set(task) != {"task_id", "patch_sha256", "changed_files"} or not isinstance(task["task_id"], str) or not task["task_id"] or task["task_id"] in seen or not HASH.fullmatch(task["patch_sha256"]) or not isinstance(task["changed_files"], list) or not task["changed_files"] or any(not isinstance(path, str) or not path or path.startswith(("/", chr(92))) or ".." in Path(path).parts for path in task["changed_files"]) or len(set(task["changed_files"])) != len(task["changed_files"]):
            raise ValueError("invalid files task binding")
        seen.add(task["task_id"])
        tasks.append(task)
    return tasks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--score-output", type=Path, required=True)
    args = parser.parse_args()
    if args.score_output.exists():
        parser.error("score output must not pre-exist")
    try:
        fixture_bytes, fixture = read_json_once(args.fixture)
        output_bytes, outputs = read_json_once(args.outputs)
        if not isinstance(fixture, dict) or fixture.get("schema_version") != "ember-restart-files-fixture-v1" or fixture.get("result") != "SELFTEST" or fixture.get("benchmark_id") != "swe-bench-fixture" or fixture.get("benchmark_version") != "1":
            raise ValueError("invalid files fixture identity")
        expected = validate_tasks(fixture, "ember-restart-files-fixture-v1")
        actual = validate_tasks(outputs, "ember-restart-files-output-v1")
        if [task["task_id"] for task in expected] != [task["task_id"] for task in actual] or len(expected) != len(actual):
            raise ValueError("files outputs must exactly cover fixture task order")
        patch_matches = [left["patch_sha256"] == right["patch_sha256"] for left, right in zip(expected, actual)]
        file_matches = [left["changed_files"] == right["changed_files"] for left, right in zip(expected, actual)]
        if not all(patch_matches) or not all(file_matches):
            raise ValueError("files fixture output does not bind exact patch and changed files")
    except ValueError as error:
        parser.error(str(error))
    payload = {
        "result": "SELFTEST",
        "admission": "NOT_ELIGIBLE",
        "claim_status": "SELFTEST_ONLY_FILES_PATCH_BINDING",
        "benchmark_id": fixture["benchmark_id"],
        "benchmark_version": fixture["benchmark_version"],
        "criterion_id": "ember-3b-files-capability-v1",
        "criterion_result": "FAILED",
        "metrics": {"exact_patch_binding": sum(patch_matches) / len(expected), "changed_file_binding": sum(file_matches) / len(expected)},
        "sample_count": len(expected),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "outputs_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "upstream": "deterministic SWE-bench patch/changed-file fixture validator; no repository sandbox or score",
    }
    args.score_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.score_output.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write(chr(10))
        temporary = handle.name
    try:
        os.replace(temporary, args.score_output)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
