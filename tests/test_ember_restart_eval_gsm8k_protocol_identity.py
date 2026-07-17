# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_gsm8k_freeze.py"


def _run(root: Path, output: Path, protocol: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dataset-root",
            str(root),
            "--revision",
            "740312add88f781978c0658806c59bc2815b9866",
            "--protocol-sha256",
            protocol,
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_gsm8k_protocol_identity_is_not_caller_attested(tmp_path):
    root = tmp_path / "dataset"
    (root / "main").mkdir(parents=True)
    (root / "README.md").write_text("---\nlicense: mit\n---\n", encoding="utf-8")
    pq.write_table(pa.table({"question": ["one"], "answer": ["work\n#### 1"]}), root / "main" / "test-00000-of-00001.parquet")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    assert _run(root, first, "a" * 64).returncode == 0
    assert _run(root, second, "b" * 64).returncode == 0
    first_value = json.loads(first.read_text(encoding="utf-8"))
    second_value = json.loads(second.read_text(encoding="utf-8"))
    assert first_value["protocol_sha256"] == second_value["protocol_sha256"]