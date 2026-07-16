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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_gsm8k_freeze.py"


def test_freezes_exact_gsm8k_main_test_bytes_without_checkpoint_bound_predictions():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense:\n- mit\n---\n", encoding="utf-8")
        split = root / "main" / "test-00000-of-00001.parquet"
        split.parent.mkdir()
        pq.write_table(pa.table({"question": ["one", "two"], "answer": ["work\n#### 1", "work\n#### 2"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", "740312add88f781978c0658806c59bc2815b9866", "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "FROZEN_GSM8K_TASKS_NO_CHECKPOINT_BOUND_PREDICTIONS"
        assert payload["task_count"] == 2
        assert payload["split_sha256"] == hashlib.sha256(split.read_bytes()).hexdigest()


def test_refuses_gsm8k_rows_without_unique_questions_or_final_answer_markers():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense: mit\n---\n", encoding="utf-8")
        split = root / "main" / "test-00000-of-00001.parquet"
        split.parent.mkdir()
        pq.write_table(pa.table({"question": ["one", "one"], "answer": ["#### 1", "no final marker"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", "740312add88f781978c0658806c59bc2815b9866", "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert not output.exists()