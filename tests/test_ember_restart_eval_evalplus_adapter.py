# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_evalplus_adapter.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_derives_evalplus_samples_only_from_canonical_code_predictions():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); asset = root / "HumanEvalPlus.jsonl.gz"; custody = root / "custody.json"; predictions = root / "predictions.json"; samples = root / "samples.jsonl"; binding = root / "binding.json"
        with gzip.open(asset, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps({"task_id": "HumanEval/0"}) + "\n")
        custody.write_text(json.dumps({"benchmark_id": "evalplus", "frozen_task_assets": {"humanevalplus_v0.1.10": {"sha256": digest(asset), "rows": 1}}}), encoding="utf-8")
        predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "evalplus", "version": "v0.1.10", "capability": "text", "split_sha256": digest(asset), "protocol_sha256": "e" * 64}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "HumanEval/0", "input_sha256": "f" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "text", "text": "    return 0"}}]}), encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--suite", "humanevalplus_v0.1.10", "--frozen-code-manifest", str(custody), "--task-asset", str(asset), "--canonical-predictions", str(predictions), "--samples-output", str(samples), "--binding-output", str(binding)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert json.loads(samples.read_text(encoding="utf-8")) == {"task_id": "HumanEval/0", "completion": "    return 0"}
        proof = json.loads(binding.read_text(encoding="utf-8"))
        assert proof["predictions_sha256"] == digest(predictions)
        assert proof["task_asset_sha256"] == digest(asset)
        assert proof["samples_sha256"] == digest(samples)
        assert proof["sample_count"] == 1


def test_refuses_detached_or_incomplete_evalplus_predictions():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); asset = root / "HumanEvalPlus.jsonl.gz"; custody = root / "custody.json"; predictions = root / "predictions.json"; samples = root / "samples.jsonl"; binding = root / "binding.json"
        with gzip.open(asset, "wt", encoding="utf-8") as handle:
            handle.write(json.dumps({"task_id": "HumanEval/0"}) + "\n")
        custody.write_text(json.dumps({"benchmark_id": "evalplus", "frozen_task_assets": {"humanevalplus_v0.1.10": {"sha256": digest(asset), "rows": 1}}}), encoding="utf-8")
        predictions.write_text(json.dumps({"HumanEval/0": "return 0"}), encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--suite", "humanevalplus_v0.1.10", "--frozen-code-manifest", str(custody), "--task-asset", str(asset), "--canonical-predictions", str(predictions), "--samples-output", str(samples), "--binding-output", str(binding)], text=True, capture_output=True, check=False)
        assert result.returncode != 0
        assert "canonical checkpoint predictions are required" in result.stderr
        assert not samples.exists() and not binding.exists()
