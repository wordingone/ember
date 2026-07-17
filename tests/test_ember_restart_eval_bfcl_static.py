# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_bfcl_static.py"


def test_scores_only_exact_frozen_bfcl_static_tool_envelope(tmp_path):
    frozen = tmp_path / "frozen.json"
    predictions = tmp_path / "predictions.json"
    output = tmp_path / "score.json"
    split = "a" * 64
    protocol = "b" * 64
    frozen.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "bfcl-static-non-live", "benchmark_version": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8", "capability": "tool", "split_sha256": split, "protocol_sha256": protocol, "tasks": [{"id": "simple_python_0", "expected_call": {"name": "lookup", "arguments": {"city": "Paris"}}}]}), encoding="utf-8")
    predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "c" * 64, "model_config_sha256": "d" * 64, "tokenizer_sha256": "e" * 64, "inference_implementation_sha256": "f" * 64, "benchmark": {"id": "bfcl-static-non-live", "version": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8", "capability": "tool", "split_sha256": split, "protocol_sha256": protocol}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "simple_python_0", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "tool_call", "name": "lookup", "arguments": {"city": "Paris"}}}]}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(frozen), "--canonical-predictions", str(predictions), "--score-output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["result"] == "PREFLIGHT_ONLY"
    assert value["claim_status"] == "NON_ADMISSIBLE_FROZEN_BFCL_STATIC_SCORER"
    assert value["criterion_result"] == "FAILED"
    assert value["metrics"] == {"exact_tool_call": 1.0}
    assert value["sample_count"] == 1
    assert value["benchmark_id"] == "bfcl-static-non-live"
    assert value["benchmark_version"] == "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
    assert value["split_sha256"] == split
    assert value["protocol_sha256"] == protocol
    assert value["predictions_sha256"] == hashlib.sha256(predictions.read_bytes()).hexdigest()
    assert value["frozen_task_manifest_sha256"] == hashlib.sha256(frozen.read_bytes()).hexdigest()


def test_refuses_detached_or_incomplete_bfcl_predictions(tmp_path):
    frozen = tmp_path / "frozen.json"
    predictions = tmp_path / "predictions.json"
    output = tmp_path / "score.json"
    frozen.write_text(json.dumps({"result": "PREFLIGHT_ONLY", "benchmark_id": "bfcl-static-non-live", "benchmark_version": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8", "capability": "tool", "split_sha256": "a" * 64, "protocol_sha256": "b" * 64, "tasks": [{"id": "one", "expected_call": {"name": "one", "arguments": {}}}]}), encoding="utf-8")
    predictions.write_text(json.dumps({"one": {"name": "one", "arguments": {}}}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(frozen), "--canonical-predictions", str(predictions), "--score-output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert not output.exists()

def test_scores_frozen_bfcl_simple_prompt_oracle_schema(tmp_path):
    frozen = tmp_path / "frozen.json"
    predictions = tmp_path / "predictions.json"
    output = tmp_path / "score.json"
    split = "a" * 64
    protocol = "dc8eb257fca47fc1e5b1e217fc2b64a9f1511fc931ab9f33cf78f68312e4b6fd"
    frozen.write_text(json.dumps({"schema_version": "ember-restart-bfcl-simple-frozen-v1", "result": "PREFLIGHT_ONLY", "benchmark_id": "bfcl-static-simple", "benchmark_version": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8", "capability": "tool", "split_sha256": split, "protocol_sha256": protocol, "source_files": [], "task_count": 1, "tasks": [{"id": "simple_python_0", "category": "simple_python", "functions": [{"name": "lookup"}], "question": [{"role": "user", "content": "find Paris"}], "ground_truth": [{"lookup": {"city": ["Paris"]}}]}]}), encoding="utf-8")
    predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "c" * 64, "model_config_sha256": "d" * 64, "tokenizer_sha256": "e" * 64, "inference_implementation_sha256": "f" * 64, "benchmark": {"id": "bfcl-static-simple", "version": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8", "capability": "tool", "split_sha256": split, "protocol_sha256": protocol}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "simple_python_0", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "tool_call", "name": "lookup", "arguments": {"city": ["Paris"]}}}]}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(frozen), "--canonical-predictions", str(predictions), "--score-output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["result"] == "PREFLIGHT_ONLY"
    assert value["claim_status"] == "NON_ADMISSIBLE_FROZEN_BFCL_STATIC_SCORER"
    assert value["metrics"] == {"exact_tool_call": 1.0}


def test_rejects_valid_hex_bfcl_simple_protocol_not_derived_from_task_custody(tmp_path):
    frozen = tmp_path / "frozen.json"; predictions = tmp_path / "predictions.json"; output = tmp_path / "score.json"
    frozen.write_text(json.dumps({"schema_version": "ember-restart-bfcl-simple-frozen-v1", "result": "PREFLIGHT_ONLY", "benchmark_id": "bfcl-static-simple", "benchmark_version": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8", "capability": "tool", "split_sha256": "a" * 64, "protocol_sha256": "0" * 64, "source_files": [], "task_count": 1, "tasks": [{"id": "simple_python_0", "category": "simple_python", "functions": [{"name": "lookup"}], "question": [{"role": "user", "content": "find Paris"}], "ground_truth": [{"lookup": {"city": ["Paris"]}}]}]}), encoding="utf-8")
    predictions.write_text(json.dumps({"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "c" * 64, "model_config_sha256": "d" * 64, "tokenizer_sha256": "e" * 64, "inference_implementation_sha256": "f" * 64, "benchmark": {"id": "bfcl-static-simple", "version": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8", "capability": "tool", "split_sha256": "a" * 64, "protocol_sha256": "0" * 64}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "simple_python_0", "input_sha256": "0" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "tool_call", "name": "lookup", "arguments": {"city": ["Paris"]}}}]}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--frozen-task-manifest", str(frozen), "--canonical-predictions", str(predictions), "--score-output", str(output)], text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert not output.exists()