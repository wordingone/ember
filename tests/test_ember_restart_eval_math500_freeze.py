# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_math500_freeze.py"


def test_freezes_exact_math500_test_bytes_with_unique_problem_ids():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        card = root / "README.md"
        rows = root / "test.jsonl"
        output = root / "frozen.json"
        card.write_text("---\nlicense: mit\n---\n", encoding="utf-8")
        rows.write_text('{"unique_id":"a","problem":"1+1","answer":"2"}\n{"unique_id":"b","problem":"2+2","answer":"4"}\n', encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", "2cd6fe926f1203a15d19f73c9a329cbe62b806fd", "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "FROZEN_MATH500_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS"
        assert payload["benchmark_id"] == "math-500"
        assert payload["task_count"] == 2
        assert payload["references_sha256"] == hashlib.sha256(rows.read_bytes()).hexdigest()


def test_refuses_math500_rows_missing_answer_or_duplicate_id():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense: mit\n---\n", encoding="utf-8")
        rows = root / "test.jsonl"
        rows.write_text('{"unique_id":"a","problem":"1+1","answer":"2"}\n{"unique_id":"a","problem":"2+2"}\n', encoding="utf-8")
        output = root / "frozen.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", "2cd6fe926f1203a15d19f73c9a329cbe62b806fd", "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert not output.exists()

def test_cleans_temporary_payload_when_final_math500_publication_fails(monkeypatch):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense: mit\n---\n", encoding="utf-8")
        (root / "test.jsonl").write_text('{"unique_id":"a","problem":"1+1","answer":"2"}\n', encoding="utf-8")
        output = root / "frozen.json"
        spec = importlib.util.spec_from_file_location("math500_freeze_publication", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--dataset-root", str(root), "--revision", "2cd6fe926f1203a15d19f73c9a329cbe62b806fd", "--protocol-sha256", "a" * 64, "--output", str(output)])
        monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace denied")))
        with pytest.raises(OSError, match="replace denied"):
            module.main()
        assert not output.exists()
        assert not list(root.glob("frozen.json.*.tmp"))
