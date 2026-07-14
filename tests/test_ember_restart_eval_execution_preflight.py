# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green test for checkpoint-bound evaluator input custody preflight."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_execution_preflight.py"


def test_requires_and_hash_binds_real_evaluator_inputs_without_emitting_receipt():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); checkpoint = root / "checkpoint.bin"; manifest = root / "benchmark.json"; predictions = root / "predictions.json"; scored = root / "scored.json"; output = root / "preflight.json"
        checkpoint.write_bytes(b"owned-checkpoint-bytes")
        manifest.write_text(json.dumps({"benchmark_id": "frozen-text", "version": "v1", "split": "test", "harness_sha256": "a" * 64, "protocol_sha256": "b" * 64}))
        predictions.write_text(json.dumps([{"id": "1", "prediction": "yes"}, {"id": "2", "prediction": "no"}]))
        scored.write_text(json.dumps({"accuracy": 0.5, "loss": 1.25}))
        predictions_sha256 = hashlib.sha256(predictions.read_bytes()).hexdigest()
        scored_sha256 = hashlib.sha256(scored.read_bytes()).hexdigest()
        result = subprocess.run([sys.executable, str(SCRIPT), "--capability", "text", "--checkpoint", str(checkpoint), "--benchmark-manifest", str(manifest), "--raw-predictions", str(predictions), "--result-artifact", str(scored), "--criterion-id", "text.accuracy", "--criterion-passed", "true", "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text())
        assert payload == {"result": "PREFLIGHT_ONLY", "admission": "NOT_ELIGIBLE", "capability": "text", "subject_checkpoint_sha256": hashlib.sha256(b"owned-checkpoint-bytes").hexdigest(), "benchmark": {"benchmark_id": "frozen-text", "version": "v1", "split": "test", "harness_sha256": "a" * 64, "protocol_sha256": "b" * 64}, "raw_predictions_sha256": predictions_sha256, "result_artifact_sha256": scored_sha256, "sample_count": 2, "metrics": {"accuracy": 0.5, "loss": 1.25}, "criterion": {"id": "text.accuracy", "passed": True}}
