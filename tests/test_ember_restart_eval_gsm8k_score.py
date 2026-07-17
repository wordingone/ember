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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_gsm8k_score.py"


def strict_protocol(version: str, split: str) -> str:
    identity = {
        "benchmark_id": "gsm8k",
        "benchmark_version": version,
        "license_sha256": "f" * 64,
        "split_sha256": split,
        "scoring_adapter_path": "scripts/ember_restart_eval_gsm8k_score.py",
        "scoring_adapter_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_scores_canonical_gsm8k_final_answers_against_frozen_parquet():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        refs, manifest, preds, score = (root / name for name in ("refs.parquet", "manifest", "preds", "score"))
        version, protocol = "740312add88f781978c0658806c59bc2815b9866", "e" * 64
        pq.write_table(pa.table({"question": ["q1", "q2"], "answer": ["work\n#### 1", "work\n#### 2"]}), refs)
        split = hashlib.sha256(refs.read_bytes()).hexdigest()
        manifest.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "gsm8k", "benchmark_version": version, "capability": "reasoning", "references_sha256": split, "split_sha256": split, "protocol_sha256": protocol, "task_count": 2}))
        preds.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "gsm8k", "version": version, "capability": "reasoning", "split_sha256": split, "protocol_sha256": protocol}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "0", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "answer #### 1"}}, {"id": "1", "input_sha256": "1" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "#### 3"}}]}))
        run = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(refs), "--predictions", str(preds), "--score-output", str(score)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        payload = json.loads(score.read_text())
        assert payload["metrics"] == {"exact_match": 0.5} and payload["result"] == "PREFLIGHT_ONLY" and payload["criterion_result"] == "FAILED"


def _strict_inputs(tmp_path: Path):
    refs, manifest, preds, score = (tmp_path / name for name in ("refs.parquet", "manifest", "preds", "score"))
    version, checkpoint, config = "740312add88f781978c0658806c59bc2815b9866", "a" * 64, "b" * 64
    pq.write_table(pa.table({"question": ["q1"], "answer": ["work\n#### 1"]}), refs)
    split = hashlib.sha256(refs.read_bytes()).hexdigest()
    protocol = strict_protocol(version, split)
    manifest.write_text(json.dumps({"schema_version": "ember-restart-gsm8k-freeze-v2", "result": "PREFLIGHT_ONLY", "benchmark_id": "gsm8k", "benchmark_version": version, "capability": "reasoning", "references_sha256": split, "split_sha256": split, "protocol_sha256": protocol, "task_count": 1, "license_sha256": "f" * 64, "scoring_adapter_path": "scripts/ember_restart_eval_gsm8k_score.py", "scoring_adapter_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(), "checkpoint_manifest_sha256": checkpoint, "model_config_sha256": config}), encoding="utf-8")
    return refs, manifest, preds, score, version, split, protocol, checkpoint, config


def _prediction(path: Path, version: str, split: str, protocol: str, checkpoint: str, config: str):
    path.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": checkpoint, "model_config_sha256": config, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "gsm8k", "version": version, "capability": "reasoning", "split_sha256": split, "protocol_sha256": protocol}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "0", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "#### 1"}}]}), encoding="utf-8")


def test_gsm8k_strict_identity_binds_checkpoint_config_and_emits_receipt_identity(tmp_path):
    refs, manifest, preds, score, version, split, protocol, checkpoint, config = _strict_inputs(tmp_path)
    _prediction(preds, version, split, protocol, checkpoint, config)
    run = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(refs), "--predictions", str(preds), "--score-output", str(score)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    payload = json.loads(score.read_text())
    assert payload["benchmark_id"] == "gsm8k" and payload["benchmark_version"] == version
    assert payload["checkpoint_manifest_sha256"] == checkpoint and payload["model_config_sha256"] == config


def test_gsm8k_strict_identity_rejects_checkpoint_substitution(tmp_path):
    refs, manifest, preds, score, version, split, protocol, checkpoint, config = _strict_inputs(tmp_path)
    _prediction(preds, version, split, protocol, "f" * 64, config)
    run = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(refs), "--predictions", str(preds), "--score-output", str(score)], capture_output=True, text=True)
    assert run.returncode != 0 and not score.exists()
def test_gsm8k_strict_identity_rejects_protocol_substitution(tmp_path):
    refs, manifest, preds, score, version, split, protocol, checkpoint, config = _strict_inputs(tmp_path)
    _prediction(preds, version, split, "0" * 64, checkpoint, config)
    run = subprocess.run([sys.executable, str(SCRIPT), "--frozen-manifest", str(manifest), "--references", str(refs), "--predictions", str(preds), "--score-output", str(score)], capture_output=True, text=True)
    assert run.returncode != 0 and not score.exists()