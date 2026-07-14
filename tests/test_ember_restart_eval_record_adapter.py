# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for central evaluation-record assembly."""
import hashlib, json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_record_adapter.py"

def test_emits_central_evaluation_record_bound_to_receipt_bytes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); receipt = root / "text.json"; checkpoint = "a" * 64
        receipt.write_text(json.dumps({"capability":"text","result":"MEASURED","subject_checkpoint_sha256":checkpoint,"verifier_sha256":"b"*64}), encoding="utf-8")
        expected_sha256 = hashlib.sha256(receipt.read_bytes()).hexdigest()
        output = root / "record.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--receipt", str(receipt), "--benchmark-id", "frozen-text-v1", "--checkpoint-sha256", checkpoint, "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        record = json.loads(output.read_text(encoding="utf-8"))
    assert record == {"capability":"text","benchmark_id":"frozen-text-v1","receipt_path":"text.json","sha256":expected_sha256,"subject_checkpoint_sha256":checkpoint}
