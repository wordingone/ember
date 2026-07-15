# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_arc_challenge_freeze.py"


def test_freezes_exact_arc_challenge_test_bytes_as_nonadmissible_multiple_choice_tasks():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense:\n- cc-by-sa-4.0\n---\n", encoding="utf-8")
        split = root / "ARC-Challenge" / "test-00000-of-00001.parquet"
        split.parent.mkdir()
        choices = pa.array([{"text": ["one", "two"], "label": ["A", "B"]}, {"text": ["three", "four"], "label": ["A", "B"]}])
        pq.write_table(pa.table({"id": ["a", "b"], "question": ["q1", "q2"], "choices": choices, "answerKey": ["A", "B"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", "210d026faf9955653af8916fad021475a3f00453", "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "FROZEN_ARC_CHALLENGE_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS"
        assert payload["task_count"] == 2
        assert payload["split_sha256"] == hashlib.sha256(split.read_bytes()).hexdigest()


def test_refuses_arc_challenge_rows_with_invalid_answer_or_choice_labels():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense: cc-by-sa-4.0\n---\n", encoding="utf-8")
        split = root / "ARC-Challenge" / "test-00000-of-00001.parquet"
        split.parent.mkdir()
        choices = pa.array([{"text": ["one"], "label": ["A"]}, {"text": ["two"], "label": ["A"]}])
        pq.write_table(pa.table({"id": ["a", "a"], "question": ["q1", "q2"], "choices": choices, "answerKey": ["B", "A"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", "210d026faf9955653af8916fad021475a3f00453", "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert not output.exists()