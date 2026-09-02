# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_browsergym.py"


def test_scores_only_outcomes_bound_to_frozen_browser_manifest():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest, runs, output = root / "frozen.json", root / "runs.json", root / "score.json"
        manifest.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "browsergym-miniwob", "benchmark_version": "1", "tasks": [{"task_id": "click-test", "task_sha256": "a" * 64, "environment_sha256": "b" * 64}]}), encoding="utf-8")
        runs.write_text(json.dumps([{"task_id": "click-test", "success": True, "trace_sha256": "c" * 64, "environment_sha256": "b" * 64}]), encoding="utf-8")

        completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(manifest), "--browser-results", str(runs), "--score-output", str(output)], capture_output=True, text=True)

        assert completed.returncode == 0, completed.stderr
        assert json.loads(output.read_text(encoding="utf-8"))["sample_count"] == 1
