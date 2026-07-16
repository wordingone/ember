# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_math_exact.py"


def test_scores_canonical_math_answers_against_identity_bound_frozen_references():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        references = root / "references.jsonl"
        predictions = root / "predictions.json"
        manifest = root / "manifest.json"
        score = root / "score.json"
        references.write_text('{"id":"m1","answer":"42"}\n{"id":"m2","answer":"7"}\n', encoding="utf-8")
        references_sha256 = hashlib.sha256(references.read_bytes()).hexdigest()
        manifest.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "math-500", "benchmark_version": "frozen-v1", "references_sha256": references_sha256, "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "split_sha256": "e" * 64, "protocol_sha256": "f" * 64}), encoding="utf-8")
        predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "math-500", "version": "frozen-v1", "capability": "reasoning", "split_sha256": "e" * 64, "protocol_sha256": "f" * 64}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "m1", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "42"}}, {"id": "m2", "input_sha256": "1" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "8"}}]}), encoding="utf-8")

        completed = subprocess.run([sys.executable, str(SCRIPT), "--frozen-math-manifest", str(manifest), "--references", str(references), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)

        assert completed.returncode == 0, completed.stderr
        payload = json.loads(score.read_text(encoding="utf-8"))
        assert payload["metrics"] == {"exact_match": 0.5}
        assert payload["sample_count"] == 2
        assert payload["criterion_id"] == "ember-3b-reasoning-capability-v1"
        assert payload["result"] == "PREFLIGHT_ONLY"
        assert payload["claim_status"] == "NON_ADMISSIBLE_FROZEN_MATH_SCORER"
        assert payload["criterion_result"] == "FAILED"
        assert payload["predictions_sha256"] == hashlib.sha256(predictions.read_bytes()).hexdigest()
