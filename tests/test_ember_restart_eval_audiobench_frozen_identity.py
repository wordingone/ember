# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ember_restart_eval_audiobench_bound.py"


def test_refuses_predictions_not_bound_to_the_frozen_audiobench_custody_tuple(tmp_path):
    text = "hello"
    row = {"mixture_name": "m", "weight": 1.0, "recall": 0.5, "fpr": 0.1, "transcript_sha256": hashlib.sha256(text.encode()).hexdigest()}
    identity = {"suite": "different-suite", "per_mixture": [row]}
    run = tmp_path / "run.json"
    run.write_text(json.dumps({**identity, "run_hash": hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "headline": {"weighted_recall": 0.5, "weighted_fpr": 0.1}}), encoding="utf-8")
    custody = tmp_path / "custody.json"
    custody.write_text(json.dumps({"benchmark_id": "audiobench", "benchmark_version": "frozen-version", "suite": "ab/sound-id", "scoring_adapter": {"path": "scripts/ember_restart_eval_audiobench_bound.py", "sha256": "a" * 64}}), encoding="utf-8")
    predictions = tmp_path / "predictions.json"
    predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "b" * 64, "model_config_sha256": "c" * 64, "tokenizer_sha256": "d" * 64, "inference_implementation_sha256": "e" * 64, "benchmark": {"id": "audiobench", "version": "different-version", "capability": "audio", "split_sha256": "f" * 64, "protocol_sha256": "0" * 64}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [1]}, "rows": [{"id": "m", "input_sha256": "1" * 64, "generated_token_ids": [1], "stop_reason": "eos", "output": {"kind": "transcript", "text": text}}]}), encoding="utf-8")
    score = tmp_path / "score.json"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--canonical-predictions", str(predictions), "--run-artifact", str(run), "--frozen-audiobench-manifest", str(custody), "--score-output", str(score)], text=True, capture_output=True, check=False)
    assert completed.returncode != 0
    assert "frozen AudioBench custody" in completed.stderr
    assert not score.exists()