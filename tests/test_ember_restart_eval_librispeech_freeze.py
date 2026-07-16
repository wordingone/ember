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


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_librispeech_freeze.py"


def test_freezes_exact_librispeech_clean_test_references_as_nonadmissible_audio_inputs():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense:\n- cc-by-4.0\n---\n", encoding="utf-8")
        split = root / "clean" / "test" / "0000.parquet"
        split.parent.mkdir(parents=True)
        pq.write_table(pa.table({"id": ["1-2-3", "1-2-4"], "text": ["FIRST WORDS", "SECOND WORDS"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([
            sys.executable, str(SCRIPT), "--dataset-root", str(root),
            "--revision", "71cacbfb7e2354c4226d01e70d77d5fca3d04ba1",
            "--protocol-sha256", "a" * 64, "--output", str(output),
        ], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "FROZEN_LIBRISPEECH_CLEAN_TEST_REFERENCES_NO_CHECKPOINT_BOUND_PREDICTIONS"
        assert payload["benchmark_id"] == "librispeech-clean-test"
        assert payload["capability"] == "audio"
        assert payload["task_count"] == 2
        assert payload["references_sha256"] == hashlib.sha256(split.read_bytes()).hexdigest()


def test_refuses_librispeech_duplicate_ids_or_blank_transcripts():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("---\nlicense: cc-by-4.0\n---\n", encoding="utf-8")
        split = root / "clean" / "test" / "0000.parquet"
        split.parent.mkdir(parents=True)
        pq.write_table(pa.table({"id": ["1-2-3", "1-2-3"], "text": ["", "WORDS"]}), split)
        output = root / "frozen.json"
        result = subprocess.run([
            sys.executable, str(SCRIPT), "--dataset-root", str(root),
            "--revision", "71cacbfb7e2354c4226d01e70d77d5fca3d04ba1",
            "--protocol-sha256", "a" * 64, "--output", str(output),
        ], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert not output.exists()
