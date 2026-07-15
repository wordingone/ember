#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score BrowserGym outcomes only when bound to a frozen local manifest."""
import argparse, hashlib, json, os, re, tempfile
from pathlib import Path

HASH = re.compile(r"[0-9a-f]{64}")

def load(path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error: raise ValueError(str(error)) from error

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--frozen-task-manifest", required=True, type=Path); parser.add_argument("--browser-results", required=True, type=Path); parser.add_argument("--score-output", required=True, type=Path); args = parser.parse_args()
    if args.score_output.exists(): parser.error("score output must not pre-exist")
    try:
        frozen, runs = load(args.frozen_task_manifest), load(args.browser_results)
        tasks = frozen.get("tasks") if isinstance(frozen, dict) else None
        if frozen.get("result") != "PREFLIGHT_ONLY" or frozen.get("benchmark_id") != "browsergym-miniwob" or frozen.get("benchmark_version") != "1" or not isinstance(tasks, list) or not tasks: raise ValueError("invalid frozen BrowserGym manifest")
        expected = {}
        for task in tasks:
            if not isinstance(task, dict) or set(task) != {"task_id", "task_sha256", "environment_sha256"} or not isinstance(task["task_id"], str) or not HASH.fullmatch(task["task_sha256"]) or not HASH.fullmatch(task["environment_sha256"]) or task["task_id"] in expected: raise ValueError("invalid frozen BrowserGym task binding")
            expected[task["task_id"]] = task["environment_sha256"]
        if not isinstance(runs, list) or len(runs) != len(tasks): raise ValueError("browser results must exactly cover frozen tasks")
        if [x.get("task_id") if isinstance(x, dict) else None for x in runs] != [x["task_id"] for x in tasks] or any(not isinstance(x.get("success"), bool) or not isinstance(x.get("trace_sha256"), str) or not HASH.fullmatch(x["trace_sha256"]) or expected.get(x["task_id"]) != x.get("environment_sha256") for x in runs): raise ValueError("browser results must bind the frozen task order, traces, and environment")
    except ValueError as error: parser.error(str(error))
    args.score_output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"metrics":{"task_success_rate":sum(x["success"] for x in runs)/len(tasks)},"sample_count":len(tasks),"criterion_id":"ember-3b-tool-capability-v1","criterion_result":"FAILED","frozen_task_manifest_sha256":hashlib.sha256(args.frozen_task_manifest.read_bytes()).hexdigest(),"upstream":"pinned local BrowserGym MiniWoB outcomes"}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.score_output.parent, delete=False) as handle: json.dump(payload, handle, sort_keys=True); temporary=handle.name
    os.replace(temporary,args.score_output)

if __name__ == "__main__": main()
