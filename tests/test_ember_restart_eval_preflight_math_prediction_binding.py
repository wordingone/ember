# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_execution_preflight.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reasoning_preflight_rejects_math_score_without_canonical_prediction_hash():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); checkpoint = root / "checkpoint"; split = root / "split"; harness = root / "harness"; protocol = root / "protocol"; predictions = root / "predictions"; score = root / "score"; output = root / "output"
        for path in (checkpoint, split, harness, protocol): path.write_text(path.name, encoding="utf-8")
        predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": digest(checkpoint), "model_config_sha256": "a" * 64, "tokenizer_sha256": "b" * 64, "inference_implementation_sha256": "c" * 64, "benchmark": {"id": "math-500", "version": "v", "capability": "reasoning", "split_sha256": digest(split), "protocol_sha256": digest(protocol)}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "x", "input_sha256": "d" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "42"}}]}), encoding="utf-8")
        score.write_text(json.dumps({"criterion_id": "ember-3b-reasoning-capability-v1", "criterion_result": "FAILED", "sample_count": 1, "metrics": {"exact_match": 0.0}}), encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--capability", "reasoning", "--checkpoint-manifest", str(checkpoint), "--benchmark-id", "math-500", "--benchmark-version", "v", "--split-artifact", str(split), "--harness-artifact", str(harness), "--protocol-artifact", str(protocol), "--raw-predictions", str(predictions), "--result-artifact", str(score), "--output", str(output)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert "reasoning score source hashes do not bind supplied evidence" in result.stderr
        assert not output.exists()
