# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_swebench_source_audit.py"


def make_source(root: Path, include_release: bool = False) -> str:
    (root / "swebench" / "harness").mkdir(parents=True)
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (root / "README.md").write_text("source\n", encoding="utf-8")
    (root / "swebench" / "harness" / "run_evaluation.py").write_text("print('harness')\n", encoding="utf-8")
    if include_release:
        (root / "data").mkdir()
        (root / "data" / "swebench_lite.json").write_text('{"instance_id":"x"}\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "audit@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "audit"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()


def test_source_audit_binds_exact_swebench_source_without_task_release():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "swebench"
        commit = make_source(root)
        output = root.parent / "audit.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--swebench-root", str(root), "--expected-commit", commit, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "SOURCE_ONLY_NO_FROZEN_SWEBENCH_TASK_RELEASE"
        assert payload["source_commit"] == commit
        assert payload["capability_families"] == ["code", "files"]
        assert payload["missing_task_release_paths"] == ["data", "datasets", "swebench_lite.json", "swebench_verified.json"]


def test_source_audit_refuses_swebench_task_release_in_source_tree():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "swebench"
        commit = make_source(root, include_release=True)
        output = root.parent / "audit.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--swebench-root", str(root), "--expected-commit", commit, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert "task-release assets are present" in result.stderr
        assert not output.exists()


def test_source_audit_refuses_nested_swebench_task_release_file():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "swebench"
        commit = make_source(root)
        nested = root / "swebench" / "data"; nested.mkdir()
        (nested / "swebench_lite.json").write_text('{"instance_id":"x"}\n', encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "nested-release"], check=True)
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        output = root.parent / "audit.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--swebench-root", str(root), "--expected-commit", commit, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert "task-release assets are present" in result.stderr
        assert not output.exists()