# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_mmmu_image_input_freeze.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_freezes_mmmu_image_payload_digests_from_validation_bytes_once(tmp_path):
    root = tmp_path / "validation"; shard = root / "Math" / "validation-00000-of-00001.parquet"; shard.parent.mkdir(parents=True)
    pq.write_table(pa.table({
        "id": ["validation_Math_1"], "question": ["Which figure?"], "options": ["['A', 'B']"],
        "image_1": [{"bytes": b"image-one", "path": "image-one.png"}], "image_2": [None],
    }), shard)
    validation_freeze = tmp_path / "validation-freeze.json"
    validation_freeze.write_text(json.dumps({"schema_version": "ember-restart-mmmu-validation-freeze-v1", "benchmark_id": "MMMU", "upstream_revision": "f" * 40, "validation_parquet_file_count": 1, "validation_parquet_files": [{"path": "Math/validation-00000-of-00001.parquet", "sha256": digest(shard)}], "validation_row_count": 1}), encoding="utf-8")
    output = tmp_path / "image-inputs.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--validation-root", str(root), "--validation-freeze", str(validation_freeze), "--output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["result"] == "PREFLIGHT_ONLY"
    assert payload["claim_status"] == "FROZEN_MMMU_IMAGE_INPUTS_NO_CHECKPOINT_BOUND_PREDICTIONS"
    assert payload["row_count"] == 1
    assert payload["rows"] == [{"id": "validation_Math_1", "image_sha256s": [hashlib.sha256(b"image-one").hexdigest()], "input_sha256": payload["rows"][0]["input_sha256"]}]


def test_refuses_mmmu_shard_substitution_against_frozen_file_index(tmp_path):
    root = tmp_path / "validation"; shard = root / "Math" / "validation-00000-of-00001.parquet"; shard.parent.mkdir(parents=True)
    pq.write_table(pa.table({"id": ["validation_Math_1"], "question": ["q"], "options": ["['A']"], "image_1": [{"bytes": b"one", "path": "one.png"}]}), shard)
    validation_freeze = tmp_path / "validation-freeze.json"
    validation_freeze.write_text(json.dumps({"schema_version": "ember-restart-mmmu-validation-freeze-v1", "benchmark_id": "MMMU", "upstream_revision": "f" * 40, "validation_parquet_file_count": 1, "validation_parquet_files": [{"path": "Math/validation-00000-of-00001.parquet", "sha256": "0" * 64}], "validation_row_count": 1}), encoding="utf-8")
    output = tmp_path / "image-inputs.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--validation-root", str(root), "--validation-freeze", str(validation_freeze), "--output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert not output.exists()