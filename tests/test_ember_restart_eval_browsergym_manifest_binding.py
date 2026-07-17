# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_browsergym.py"
_BROWSER_SPEC=importlib.util.spec_from_file_location("browsergym_protocol", SCRIPT)
_BROWSER=importlib.util.module_from_spec(_BROWSER_SPEC)
_BROWSER_SPEC.loader.exec_module(_BROWSER)

def frozen_manifest(task_sha, environment_sha):
    value={"schema_version":"ember-restart-browsergym-miniwob-frozen-v1","result":"PREFLIGHT_ONLY","benchmark_id":"browsergym-miniwob","benchmark_version":"1","source_commit":"9e779f087de9a65668b6974d11f9ce9816026e96","source_tree":"d33e398c18d04d5da742b1c1ec11c4aab8bc010b","license_sha256":"b192c58991e8ff585cc574615d40e74185404d4b96c1109d423071ab1367344b","tasks":[{"task_id":"click-test","task_sha256":task_sha,"environment_sha256":environment_sha}]}
    value["protocol_sha256"]=_BROWSER.protocol_sha256(value)
    return value


def test_scores_only_outcomes_bound_to_frozen_browser_manifest():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest, runs, output = root / "frozen.json", root / "runs.json", root / "score.json"
        manifest.write_text(json.dumps(frozen_manifest("a" * 64, "b" * 64)), encoding="utf-8")
        runs.write_text(json.dumps([{"task_id": "click-test", "success": True, "trace_sha256": "c" * 64, "environment_sha256": "b" * 64}]), encoding="utf-8")

        completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(manifest), "--browser-results", str(runs), "--score-output", str(output)], capture_output=True, text=True)

        assert completed.returncode == 0, completed.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["sample_count"] == 1
        assert payload["result"] == "SELFTEST"
        assert payload["browser_results_sha256"] == __import__("hashlib").sha256(runs.read_bytes()).hexdigest()

def test_rejects_browser_protocol_substitution_even_with_matching_tasks():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest, runs, output = root / "frozen.json", root / "runs.json", root / "score.json"
        manifest.write_text(json.dumps({
            "schema_version": "ember-restart-browsergym-miniwob-frozen-v1",
            "result": "PREFLIGHT_ONLY",
            "benchmark_id": "browsergym-miniwob",
            "benchmark_version": "1",
            "source_commit": "9e779f087de9a65668b6974d11f9ce9816026e96",
            "source_tree": "d33e398c18d04d5da742b1c1ec11c4aab8bc010b",
            "license_sha256": "b192c58991e8ff585cc574615d40e74185404d4b96c1109d423071ab1367344b",
            "protocol_sha256": "0" * 64,
            "tasks": [{"task_id": "click-test", "task_sha256": "a" * 64, "environment_sha256": "b" * 64}],
        }), encoding="utf-8")
        runs.write_text(json.dumps([{"task_id": "click-test", "success": True, "trace_sha256": "c" * 64, "environment_sha256": "b" * 64}]), encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(manifest), "--browser-results", str(runs), "--score-output", str(output)], capture_output=True, text=True)
        assert completed.returncode != 0
        assert not output.exists()
