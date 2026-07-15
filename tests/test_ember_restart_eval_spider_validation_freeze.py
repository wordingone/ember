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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_spider_validation_freeze.py"


def test_freezes_exact_spider_validation_pairs_without_claiming_runnable_sql_scoring():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense:\n- cc-by-sa-4.0\n---\n", encoding="utf-8")
        split = root / "spider" / "validation-00000-of-00001.parquet"
        split.parent.mkdir()
        pq.write_table(pa.table({"db_id": ["a", "b"], "question": ["one", "two"], "query": ["select 1", "select 2"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", "0c350918f3f29ec754f1181c65cdce76cd6c133c", "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["admission"] == "NOT_EXECUTABLE_NO_FROZEN_DATABASE_ASSETS"
        assert payload["task_count"] == 2
        assert payload["split_sha256"] == hashlib.sha256(split.read_bytes()).hexdigest()
        assert payload["references_sha256"] == payload["split_sha256"]


def test_refuses_spider_validation_pairs_without_unique_nonempty_sql_rows():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense: cc-by-sa-4.0\n---\n", encoding="utf-8")
        split = root / "spider" / "validation-00000-of-00001.parquet"
        split.parent.mkdir()
        pq.write_table(pa.table({"db_id": ["a", "a"], "question": ["one", "one"], "query": ["select 1", "select 1"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--dataset-root", str(root), "--revision", "0c350918f3f29ec754f1181c65cdce76cd6c133c", "--protocol-sha256", "a" * 64, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert not output.exists()