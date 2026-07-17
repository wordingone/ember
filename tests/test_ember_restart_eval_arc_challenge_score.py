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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_arc_challenge.py"


def envelope(version, split, protocol, checkpoint, config, text):
    return {"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": checkpoint, "model_config_sha256": config, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "arc-challenge", "version": version, "capability": "reasoning", "split_sha256": split, "protocol_sha256": protocol}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "q1", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": text}}]}


def test_scores_arc_challenge_and_binds_strict_checkpoint_identity(tmp_path):
    refs, manifest, predictions, score = tmp_path / "arc.parquet", tmp_path / "manifest.json", tmp_path / "predictions.json", tmp_path / "score.json"
    version, checkpoint, config, protocol = "210d026faf9955653af8916fad021475a3f00453", "a" * 64, "b" * 64, "e" * 64
    pq.write_table(pa.Table.from_pylist([{"id": "q1", "choices": {"label": ["A", "B"]}, "answerKey": "B"}]), refs)
    split = hashlib.sha256(refs.read_bytes()).hexdigest()
    manifest.write_text(json.dumps({"schema_version": "ember-restart-arc-challenge-freeze-v2", "result": "PREFLIGHT_ONLY", "benchmark_id": "arc-challenge", "benchmark_version": version, "capability": "reasoning", "references_sha256": split, "split_sha256": split, "protocol_sha256": protocol, "task_count": 1, "checkpoint_manifest_sha256": checkpoint, "model_config_sha256": config}), encoding="utf-8")
    predictions.write_text(json.dumps(envelope(version, split, protocol, checkpoint, config, "B")), encoding="utf-8")
    run = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(refs), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    payload = json.loads(score.read_text())
    assert payload["result"] == "PREFLIGHT_ONLY" and payload["metrics"] == {"accuracy": 1.0} and payload["checkpoint_manifest_sha256"] == checkpoint


def test_rejects_arc_checkpoint_substitution(tmp_path):
    refs, manifest, predictions, score = tmp_path / "arc.parquet", tmp_path / "manifest.json", tmp_path / "predictions.json", tmp_path / "score.json"
    version, checkpoint, config, protocol = "210d026faf9955653af8916fad021475a3f00453", "a" * 64, "b" * 64, "e" * 64
    pq.write_table(pa.Table.from_pylist([{"id": "q1", "choices": {"label": ["A", "B"]}, "answerKey": "B"}]), refs)
    split = hashlib.sha256(refs.read_bytes()).hexdigest()
    manifest.write_text(json.dumps({"schema_version": "ember-restart-arc-challenge-freeze-v2", "result": "PREFLIGHT_ONLY", "benchmark_id": "arc-challenge", "benchmark_version": version, "capability": "reasoning", "references_sha256": split, "split_sha256": split, "protocol_sha256": protocol, "task_count": 1, "checkpoint_manifest_sha256": checkpoint, "model_config_sha256": config}), encoding="utf-8")
    predictions.write_text(json.dumps(envelope(version, split, protocol, "f" * 64, config, "B")), encoding="utf-8")
    run = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(refs), "--predictions", str(predictions), "--score-output", str(score)], capture_output=True, text=True)
    assert run.returncode != 0 and not score.exists()