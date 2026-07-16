# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_evalplus_runtime_audit.py"


def test_runtime_audit_reports_mutable_base_and_live_build_inputs_without_publishing_execution_claims():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "evalplus"; root.mkdir()
        (root / "Dockerfile").write_text('FROM python:3.11-slim\nRUN pip install --upgrade pip\nRUN python -c "get_human_eval_plus()"\n', encoding="utf-8")
        output = root.parent / "audit.json"
        run = subprocess.run([sys.executable, str(SCRIPT), "--evalplus-root", str(root), "--output", str(output)], text=True, capture_output=True, check=False)
        assert run.returncode == 0, run.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "RUNTIME_HELD_MUTABLE_CONTAINER_BUILD"
        assert payload["target_execution_permitted"] is False
        assert payload["mutable_base_image"] is True
        assert payload["live_dependency_resolution"] is True
        assert payload["live_dataset_fetch"] is True


def test_runtime_audit_refuses_digest_pinned_claim_when_live_build_step_remains():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "evalplus"; root.mkdir()
        (root / "Dockerfile").write_text('FROM python@sha256:' + 'a' * 64 + '\nRUN pip install --upgrade pip\n', encoding="utf-8")
        output = root.parent / "audit.json"
        run = subprocess.run([sys.executable, str(SCRIPT), "--evalplus-root", str(root), "--output", str(output)], text=True, capture_output=True, check=False)
        assert run.returncode == 0, run.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["target_execution_permitted"] is False
        assert payload["live_dependency_resolution"] is True

def test_runtime_audit_reports_network_fetch_tool_as_live_dataset_input():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "evalplus"; root.mkdir()
        (root / "Dockerfile").write_text("FROM python@sha256:" + "a" * 64 + "\nRUN curl -fsSL https://example.invalid/frozen-task.json -o task.json\n", encoding="utf-8")
        output = root.parent / "audit.json"
        run = subprocess.run([sys.executable, str(SCRIPT), "--evalplus-root", str(root), "--output", str(output)], text=True, capture_output=True, check=False)
        assert run.returncode == 0, run.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["live_dataset_fetch"] is True
        assert payload["target_execution_permitted"] is False