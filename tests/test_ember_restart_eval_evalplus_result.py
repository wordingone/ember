# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_evalplus_result.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scores_only_result_bound_to_evalplus_samples_sidecar():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); binding = root / "binding.json"; result = root / "result.json"; score = root / "score.json"
        task_ids_hash = hashlib.sha256(b"HumanEval/0\n").hexdigest()
        binding.write_text(json.dumps({"schema_version": "ember-restart-evalplus-samples-binding-v1", "result": "PREFLIGHT_ONLY", "suite": "humanevalplus_v0.1.10", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "task_asset_sha256": "c" * 64, "evalplus_dataset_md5": "0123456789abcdef0123456789abcdef", "predictions_sha256": "d" * 64, "samples_sha256": "e" * 64, "task_ids_sha256": task_ids_hash, "sample_count": 1, "frozen_code_manifest_sha256": "f" * 64}), encoding="utf-8")
        result.write_text(json.dumps({"hash": "0123456789abcdef0123456789abcdef", "eval": {"HumanEval/0": [{"base_status": "pass", "plus_status": "pass"}]}, "pass_at_k": {"base": {"pass@1": 1.0}, "plus": {"pass@1": 1.0}}}), encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--samples-binding", str(binding), "--eval-result", str(result), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(score.read_text(encoding="utf-8"))
        assert payload["metrics"] == {"base_pass_at_1": 1.0, "plus_pass_at_1": 1.0}
        assert payload["samples_binding_sha256"] == digest(binding)
        assert payload["evalplus_result_sha256"] == digest(result)
        assert payload["criterion_result"] == "FAILED"
        assert payload["result"] == "SELFTEST"


def test_refuses_evalplus_result_with_wrong_dataset_or_task_set():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); binding = root / "binding.json"; result = root / "result.json"; score = root / "score.json"
        binding.write_text(json.dumps({"schema_version": "ember-restart-evalplus-samples-binding-v1", "result": "PREFLIGHT_ONLY", "suite": "humanevalplus_v0.1.10", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "task_asset_sha256": "c" * 64, "evalplus_dataset_md5": "0123456789abcdef0123456789abcdef", "predictions_sha256": "d" * 64, "samples_sha256": "e" * 64, "task_ids_sha256": hashlib.sha256(b"HumanEval/0\n").hexdigest(), "sample_count": 1, "frozen_code_manifest_sha256": "f" * 64}), encoding="utf-8")
        result.write_text(json.dumps({"hash": "bad", "eval": {"HumanEval/1": [{"base_status": "pass", "plus_status": "pass"}]}, "pass_at_k": {"base": {"pass@1": 1.0}, "plus": {"pass@1": 1.0}}}), encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--samples-binding", str(binding), "--eval-result", str(result), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert completed.returncode != 0
        assert "does not bind samples sidecar" in completed.stderr
        assert not score.exists()
