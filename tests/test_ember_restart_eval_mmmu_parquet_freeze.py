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


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_mmmu_parquet_freeze.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_freezer_binds_validation_parquet_answers_to_existing_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        parquet_root = root / "parquet" / "Math"
        parquet_root.mkdir(parents=True)
        pq.write_table(pa.table({"id": ["validation_Math_1", "validation_Math_2"], "answer": ["A", "B"], "question_type": ["multiple-choice", "multiple-choice"]}), parquet_root / "validation-00000-of-00001.parquet")
        answers = root / "answers.json"
        answers.write_text(json.dumps({"validation_Math_1": {"question_type": "multiple-choice", "ground_truth": "A"}, "validation_Math_2": {"question_type": "multiple-choice", "ground_truth": "B"}}), encoding="utf-8")
        output = root / "receipt.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--validation-root", str(root / "parquet"), "--answers", str(answers), "--upstream-revision", "f" * 40, "--disk-receipt", str(answers), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "FROZEN_SOURCE_COMPATIBILITY_ONLY"
        assert payload["validation_row_count"] == 2
        assert payload["answer_dictionary_sha256"] == digest(answers)
        assert payload["validation_answer_dictionary_sha256"] == digest(answers)
        assert payload["validation_parquet_files"] == [{"path": "Math/validation-00000-of-00001.parquet", "sha256": digest(parquet_root / "validation-00000-of-00001.parquet")} ]


def test_freezer_refuses_answer_drift_and_does_not_publish_output():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        parquet_root = root / "parquet" / "Math"
        parquet_root.mkdir(parents=True)
        pq.write_table(pa.table({"id": ["validation_Math_1"], "answer": ["B"], "question_type": ["multiple-choice"]}), parquet_root / "validation-00000-of-00001.parquet")
        answers = root / "answers.json"
        answers.write_text(json.dumps({"validation_Math_1": {"question_type": "multiple-choice", "ground_truth": "A"}}), encoding="utf-8")
        output = root / "receipt.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--validation-root", str(root / "parquet"), "--answers", str(answers), "--upstream-revision", "f" * 40, "--disk-receipt", str(answers), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert "does not reproduce" in result.stderr
        assert not output.exists()


def test_freezer_accepts_upstream_open_rows_as_noneligible_short_answers():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        parquet_root = root / "parquet" / "Math"
        parquet_root.mkdir(parents=True)
        pq.write_table(pa.table({"id": ["validation_Math_1", "validation_Math_2"], "answer": ["A", "1.06"], "question_type": ["multiple-choice", "open"]}), parquet_root / "validation-00000-of-00001.parquet")
        answers = root / "answers.json"
        answers.write_text(json.dumps({"validation_Math_1": {"question_type": "multiple-choice", "ground_truth": "A"}, "validation_Math_2": {"question_type": "short-answer", "ground_truth": "1.06"}}), encoding="utf-8")
        output = root / "receipt.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--validation-root", str(root / "parquet"), "--answers", str(answers), "--upstream-revision", "f" * 40, "--disk-receipt", str(answers), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(output.read_text(encoding="utf-8"))["eligible_multiple_choice_count"] == 1

def test_freezer_accepts_serialized_open_answer_alternatives():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        parquet_root = root / "parquet" / "Chemistry"
        parquet_root.mkdir(parents=True)
        pq.write_table(pa.table({"id": ["validation_Chemistry_30"], "answer": ["['$MgS$', 'MgS']"], "question_type": ["open"]}), parquet_root / "validation-00000-of-00001.parquet")
        answers = root / "answers.json"
        answers.write_text(json.dumps({"validation_Chemistry_30": {"question_type": "short-answer", "ground_truth": ["$MgS$", "MgS"]}}), encoding="utf-8")
        output = root / "receipt.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--validation-root", str(root / "parquet"), "--answers", str(answers), "--upstream-revision", "f" * 40, "--disk-receipt", str(answers), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(output.read_text(encoding="utf-8"))["validation_row_count"] == 1