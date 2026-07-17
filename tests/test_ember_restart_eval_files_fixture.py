# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_files_fixture.py"


def test_files_fixture_binds_patch_and_changed_file_outputs(tmp_path):
    patch = b"diff --git a/a.py b/a.py\n"
    patch_sha = hashlib.sha256(patch).hexdigest()
    fixture = tmp_path / "fixture.json"
    outputs = tmp_path / "outputs.json"
    score = tmp_path / "score.json"
    fixture.write_text(json.dumps({
        "schema_version": "ember-restart-files-fixture-v1",
        "result": "SELFTEST",
        "benchmark_id": "swe-bench-fixture",
        "benchmark_version": "1",
        "tasks": [{"task_id": "t1", "patch_sha256": patch_sha, "changed_files": ["a.py"]}],
    }), encoding="utf-8")
    outputs.write_text(json.dumps({
        "schema_version": "ember-restart-files-output-v1",
        "tasks": [{"task_id": "t1", "patch_sha256": patch_sha, "changed_files": ["a.py"]}],
    }), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--fixture", str(fixture), "--outputs", str(outputs), "--score-output", str(score)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    value = json.loads(score.read_text(encoding="utf-8"))
    assert value["result"] == "SELFTEST"
    assert value["admission"] == "NOT_ELIGIBLE"
    assert value["sample_count"] == 1
    assert value["metrics"] == {"exact_patch_binding": 1.0, "changed_file_binding": 1.0}


def test_files_fixture_rejects_patch_or_changed_file_substitution(tmp_path):
    fixture = tmp_path / "fixture.json"
    outputs = tmp_path / "outputs.json"
    score = tmp_path / "score.json"
    patch_sha = "a" * 64
    fixture.write_text(json.dumps({"schema_version": "ember-restart-files-fixture-v1", "result": "SELFTEST", "benchmark_id": "swe-bench-fixture", "benchmark_version": "1", "tasks": [{"task_id": "t1", "patch_sha256": patch_sha, "changed_files": ["a.py"]}]}), encoding="utf-8")
    outputs.write_text(json.dumps({"schema_version": "ember-restart-files-output-v1", "tasks": [{"task_id": "t1", "patch_sha256": "b" * 64, "changed_files": ["b.py"]}]}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--fixture", str(fixture), "--outputs", str(outputs), "--score-output", str(score)], capture_output=True, text=True)
    assert result.returncode != 0
    assert not score.exists()

def test_files_fixture_rejects_drive_qualified_changed_file_paths(tmp_path):
    fixture = tmp_path / "fixture.json"
    outputs = tmp_path / "outputs.json"
    score = tmp_path / "score.json"
    payload = {
        "schema_version": "ember-restart-files-fixture-v1",
        "result": "SELFTEST",
        "benchmark_id": "swe-bench-fixture",
        "benchmark_version": "1",
        "tasks": [{"task_id": "t1", "patch_sha256": "a" * 64, "changed_files": ["C:detached.py"]}],
    }
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    outputs.write_text(json.dumps({"schema_version": "ember-restart-files-output-v1", "tasks": payload["tasks"]}), encoding="utf-8")

    result = subprocess.run([sys.executable, str(SCRIPT), "--fixture", str(fixture), "--outputs", str(outputs), "--score-output", str(score)], capture_output=True, text=True)

    assert result.returncode != 0
    assert not score.exists()
def test_files_fixture_rejects_claim_bearing_output_marker(tmp_path):
    fixture = tmp_path / "fixture.json"
    outputs = tmp_path / "outputs.json"
    score = tmp_path / "score.json"
    patch_sha = "a" * 64
    fixture.write_text(json.dumps({
        "schema_version": "ember-restart-files-fixture-v1",
        "result": "SELFTEST",
        "benchmark_id": "swe-bench-fixture",
        "benchmark_version": "1",
        "tasks": [{"task_id": "t1", "patch_sha256": patch_sha, "changed_files": ["a.py"]}],
    }), encoding="utf-8")
    outputs.write_text(json.dumps({
        "schema_version": "ember-restart-files-output-v1",
        "result": "MEASURED",
        "tasks": [{"task_id": "t1", "patch_sha256": patch_sha, "changed_files": ["a.py"]}],
    }), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--fixture", str(fixture), "--outputs", str(outputs), "--score-output", str(score)], capture_output=True, text=True)
    assert result.returncode != 0
    assert not score.exists()
