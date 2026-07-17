#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate BrowserGym fixture outcomes against frozen manifest bytes only."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

HASH = re.compile(r"[0-9a-f]{64}")
BROWSERGYM_SOURCE_COMMIT = "9e779f087de9a65668b6974d11f9ce9816026e96"
BROWSERGYM_SOURCE_TREE = "d33e398c18d04d5da742b1c1ec11c4aab8bc010b"
BROWSERGYM_LICENSE_SHA256 = "b192c58991e8ff585cc574615d40e74185404d4b96c1109d423071ab1367344b"
BROWSERGYM_SCHEMA = "ember-restart-browsergym-miniwob-frozen-v1"


def read_json_bytes(path: Path) -> tuple[bytes, object]:
    try:
        data = path.read_bytes()
        return data, json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(str(error)) from error


def protocol_sha256(frozen: dict) -> str:
    identity = {
        "schema_version": frozen["schema_version"],
        "result": frozen["result"],
        "benchmark_id": frozen["benchmark_id"],
        "benchmark_version": frozen["benchmark_version"],
        "source_commit": frozen["source_commit"],
        "source_tree": frozen["source_tree"],
        "license_sha256": frozen["license_sha256"],
        "tasks": frozen["tasks"],
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-task-manifest", required=True, type=Path)
    parser.add_argument("--browser-results", required=True, type=Path)
    parser.add_argument("--score-output", required=True, type=Path)
    args = parser.parse_args()
    if args.score_output.exists():
        parser.error("score output must not pre-exist")
    try:
        manifest_bytes, frozen = read_json_bytes(args.frozen_task_manifest)
        result_bytes, runs = read_json_bytes(args.browser_results)
        tasks = frozen.get("tasks") if isinstance(frozen, dict) else None
        required = {"schema_version", "result", "benchmark_id", "benchmark_version", "source_commit", "source_tree", "license_sha256", "protocol_sha256", "tasks"}
        if not isinstance(frozen, dict) or set(frozen) != required or frozen.get("schema_version") != BROWSERGYM_SCHEMA or frozen.get("result") != "PREFLIGHT_ONLY" or frozen.get("benchmark_id") != "browsergym-miniwob" or frozen.get("benchmark_version") != "1" or frozen.get("source_commit") != BROWSERGYM_SOURCE_COMMIT or frozen.get("source_tree") != BROWSERGYM_SOURCE_TREE or frozen.get("license_sha256") != BROWSERGYM_LICENSE_SHA256 or not isinstance(tasks, list) or not tasks:
            raise ValueError("invalid frozen BrowserGym manifest")
        if frozen.get("protocol_sha256") != protocol_sha256(frozen):
            raise ValueError("BrowserGym protocol is not derived from pinned source/license/task custody")
        expected = {}
        for task in tasks:
            if not isinstance(task, dict) or set(task) != {"task_id", "task_sha256", "environment_sha256"} or not isinstance(task["task_id"], str) or not HASH.fullmatch(task["task_sha256"]) or not HASH.fullmatch(task["environment_sha256"]) or task["task_id"] in expected:
                raise ValueError("invalid frozen BrowserGym task binding")
            expected[task["task_id"]] = task["environment_sha256"]
        if not isinstance(runs, list) or len(runs) != len(tasks):
            raise ValueError("browser results must exactly cover frozen tasks")
        if [item.get("task_id") if isinstance(item, dict) else None for item in runs] != [task["task_id"] for task in tasks] or any(not isinstance(item.get("success"), bool) or not isinstance(item.get("trace_sha256"), str) or not HASH.fullmatch(item["trace_sha256"]) or expected.get(item["task_id"]) != item.get("environment_sha256") for item in runs):
            raise ValueError("browser results must bind the frozen task order, traces, and environment")
    except ValueError as error:
        parser.error(str(error))
    payload = {
        "result": "SELFTEST",
        "admission": "NOT_ELIGIBLE",
        "claim_status": "SELFTEST_ONLY_FIXTURE_BROWSER_OUTCOMES",
        "metrics": {"task_success_rate": sum(item["success"] for item in runs) / len(tasks)},
        "sample_count": len(tasks),
        "criterion_id": "ember-3b-tool-capability-v1",
        "criterion_result": "FAILED",
        "benchmark_id": frozen["benchmark_id"],
        "benchmark_version": frozen["benchmark_version"],
        "source_commit": frozen["source_commit"],
        "source_tree": frozen["source_tree"],
        "license_sha256": frozen["license_sha256"],
        "protocol_sha256": frozen["protocol_sha256"],
        "frozen_task_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "browser_results_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "upstream": "fixture-only BrowserGym MiniWoB outcome validator",
    }
    args.score_output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.score_output.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        temporary = handle.name
    try:
        os.replace(temporary, args.score_output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())