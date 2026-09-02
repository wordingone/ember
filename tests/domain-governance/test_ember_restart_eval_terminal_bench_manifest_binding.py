# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_terminal_bench.py"


def test_rejects_harbor_outcome_image_that_does_not_match_frozen_manifest():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        frozen = root / "frozen.json"
        results = root / "results.json"
        output = root / "score.json"
        frozen.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "terminal-bench", "benchmark_version": "2.0", "tasks": [{"task_id": "bounded-task", "task_toml_sha256": "a" * 64, "docker_image_sha256": "b" * 64}]}), encoding="utf-8")
        results.write_text(json.dumps([{"task_id": "bounded-task", "status": "passed", "transcript_sha256": "c" * 64, "task_image_sha256": "d" * 64}]), encoding="utf-8")

        completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(frozen), "--harbor-task-results", str(results), "--score-output", str(output)], capture_output=True, text=True)

        assert completed.returncode != 0
        assert not output.exists()


def test_scores_only_harbor_outcome_bound_to_frozen_manifest():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        frozen = root / "frozen.json"
        results = root / "results.json"
        output = root / "score.json"
        frozen.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "terminal-bench", "benchmark_version": "2.0", "tasks": [{"task_id": "bounded-task", "task_toml_sha256": "a" * 64, "docker_image_sha256": "b" * 64}]}), encoding="utf-8")
        results.write_text(json.dumps([{"task_id": "bounded-task", "status": "passed", "transcript_sha256": "c" * 64, "task_image_sha256": "b" * 64}]), encoding="utf-8")

        completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(frozen), "--harbor-task-results", str(results), "--score-output", str(output)], capture_output=True, text=True)

        assert completed.returncode == 0, completed.stderr
