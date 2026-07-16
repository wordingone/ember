# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_evalplus_result.py"
CODE_MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "ember-restart-eval-code-math-custody-v1.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scores_only_result_bound_to_evalplus_samples_sidecar():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); binding = root / "binding.json"; result = root / "result.json"; score = root / "score.json"
        task_ids_hash = hashlib.sha256(b"HumanEval/0\n").hexdigest()
        binding.write_text(json.dumps({"schema_version": "ember-restart-evalplus-samples-binding-v1", "result": "PREFLIGHT_ONLY", "suite": "humanevalplus_v0.1.10", "benchmark_id": "evalplus", "benchmark_version": "v0.1.10", "split_sha256": "c" * 64, "protocol_sha256": json.loads(CODE_MANIFEST.read_text(encoding="utf-8"))["protocol_sha256"], "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "task_asset_sha256": json.loads(CODE_MANIFEST.read_text(encoding="utf-8"))["frozen_task_assets"]["humanevalplus_v0.1.10"]["sha256"], "evalplus_dataset_md5": "0123456789abcdef0123456789abcdef", "predictions_sha256": "d" * 64, "samples_sha256": "e" * 64, "task_ids_sha256": task_ids_hash, "sample_count": 1, "frozen_code_manifest_sha256": digest(CODE_MANIFEST)}), encoding="utf-8")
        result.write_text(json.dumps({"hash": "0123456789abcdef0123456789abcdef", "eval": {"HumanEval/0": [{"base_status": "pass", "plus_status": "pass"}]}, "pass_at_k": {"base": {"pass@1": 1.0}, "plus": {"pass@1": 1.0}}}), encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--samples-binding", str(binding), "--eval-result", str(result), "--frozen-code-manifest", str(CODE_MANIFEST), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(score.read_text(encoding="utf-8"))
        assert payload["metrics"] == {"base_pass_at_1": 1.0, "plus_pass_at_1": 1.0}
        assert payload["benchmark_id"] == "evalplus"
        assert payload["benchmark_version"] == "v0.1.10"
        assert payload["protocol_sha256"] == json.loads(CODE_MANIFEST.read_text(encoding="utf-8"))["protocol_sha256"]
        assert payload["samples_binding_sha256"] == digest(binding)
        assert payload["evalplus_result_sha256"] == digest(result)
        assert payload["criterion_result"] == "FAILED"
        assert payload["result"] == "SELFTEST"
        assert payload["claim_status"] == "SELFTEST_ONLY_RESULT_ARTIFACT_VALIDATOR"


def test_refuses_evalplus_result_with_wrong_dataset_or_task_set():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); binding = root / "binding.json"; result = root / "result.json"; score = root / "score.json"
        binding.write_text(json.dumps({"schema_version": "ember-restart-evalplus-samples-binding-v1", "result": "PREFLIGHT_ONLY", "suite": "humanevalplus_v0.1.10", "benchmark_id": "evalplus", "benchmark_version": "v0.1.10", "split_sha256": "c" * 64, "protocol_sha256": json.loads(CODE_MANIFEST.read_text(encoding="utf-8"))["protocol_sha256"], "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "task_asset_sha256": json.loads(CODE_MANIFEST.read_text(encoding="utf-8"))["frozen_task_assets"]["humanevalplus_v0.1.10"]["sha256"], "evalplus_dataset_md5": "0123456789abcdef0123456789abcdef", "predictions_sha256": "d" * 64, "samples_sha256": "e" * 64, "task_ids_sha256": hashlib.sha256(b"HumanEval/0\n").hexdigest(), "sample_count": 1, "frozen_code_manifest_sha256": digest(CODE_MANIFEST)}), encoding="utf-8")
        result.write_text(json.dumps({"hash": "bad", "eval": {"HumanEval/1": [{"base_status": "pass", "plus_status": "pass"}]}, "pass_at_k": {"base": {"pass@1": 1.0}, "plus": {"pass@1": 1.0}}}), encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--samples-binding", str(binding), "--eval-result", str(result), "--frozen-code-manifest", str(CODE_MANIFEST), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert completed.returncode != 0
        assert "does not bind samples sidecar" in completed.stderr
        assert not score.exists()

def test_refuses_evalplus_sidecar_for_unpinned_suite():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); binding = root / "binding.json"; result = root / "result.json"; score = root / "score.json"
        binding.write_text(json.dumps({"schema_version": "ember-restart-evalplus-samples-binding-v1", "result": "PREFLIGHT_ONLY", "suite": "untrusted-v9", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "task_asset_sha256": json.loads(CODE_MANIFEST.read_text(encoding="utf-8"))["frozen_task_assets"]["humanevalplus_v0.1.10"]["sha256"], "evalplus_dataset_md5": "0123456789abcdef0123456789abcdef", "predictions_sha256": "d" * 64, "samples_sha256": "e" * 64, "task_ids_sha256": hashlib.sha256(b"HumanEval/0\n").hexdigest(), "sample_count": 1, "frozen_code_manifest_sha256": digest(CODE_MANIFEST)}), encoding="utf-8")
        result.write_text(json.dumps({"hash": "0123456789abcdef0123456789abcdef", "eval": {"HumanEval/0": [{"base_status": "pass", "plus_status": "pass"}]}, "pass_at_k": {"base": {"pass@1": 1.0}, "plus": {"pass@1": 1.0}}}), encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--samples-binding", str(binding), "--eval-result", str(result), "--frozen-code-manifest", str(CODE_MANIFEST), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert completed.returncode != 0
        assert "invalid EvalPlus samples sidecar" in completed.stderr
        assert not score.exists()

def test_refuses_evalplus_binding_with_protocol_not_bound_by_frozen_code_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); binding = root / "binding.json"; result = root / "result.json"; score = root / "score.json"; custody = root / "custody.json"
        task_ids_hash = hashlib.sha256(b"HumanEval/0\n").hexdigest()
        binding.write_text(json.dumps({"schema_version": "ember-restart-evalplus-samples-binding-v1", "result": "PREFLIGHT_ONLY", "suite": "humanevalplus_v0.1.10", "benchmark_id": "evalplus", "benchmark_version": "v0.1.10", "split_sha256": "c" * 64, "protocol_sha256": json.loads(CODE_MANIFEST.read_text(encoding="utf-8"))["protocol_sha256"], "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "task_asset_sha256": json.loads(CODE_MANIFEST.read_text(encoding="utf-8"))["frozen_task_assets"]["humanevalplus_v0.1.10"]["sha256"], "evalplus_dataset_md5": "0123456789abcdef0123456789abcdef", "predictions_sha256": "d" * 64, "samples_sha256": "e" * 64, "task_ids_sha256": task_ids_hash, "sample_count": 1, "frozen_code_manifest_sha256": digest(CODE_MANIFEST)}), encoding="utf-8")
        result.write_text(json.dumps({"hash": "0123456789abcdef0123456789abcdef", "eval": {"HumanEval/0": [{"base_status": "pass", "plus_status": "pass"}]}, "pass_at_k": {"base": {"pass@1": 1.0}, "plus": {"pass@1": 1.0}}}), encoding="utf-8")
        custody.write_bytes(CODE_MANIFEST.read_bytes())
        custody_payload = json.loads(custody.read_text(encoding="utf-8")); custody_payload["protocol_sha256"] = "0" * 64; custody.write_text(json.dumps(custody_payload), encoding="utf-8")
        binding_payload = json.loads(binding.read_text(encoding="utf-8")); binding_payload["frozen_code_manifest_sha256"] = digest(custody); binding.write_text(json.dumps(binding_payload), encoding="utf-8")
        completed = subprocess.run([sys.executable, str(SCRIPT), "--samples-binding", str(binding), "--eval-result", str(result), "--frozen-code-manifest", str(custody), "--score-output", str(score)], text=True, capture_output=True, check=False)
        assert completed.returncode != 0
        assert "protocol" in completed.stderr or "adapter" in completed.stderr
        assert not score.exists()


def test_refuses_valid_hex_protocol_not_derived_from_custody_tuple(tmp_path):
    import importlib.util
    import shutil
    spec = importlib.util.spec_from_file_location("evalplus_protocol_custody", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    root = tmp_path / "repo"; (root / "manifests").mkdir(parents=True); (root / "scripts").mkdir()
    manifest = json.loads(CODE_MANIFEST.read_text(encoding="utf-8")); manifest["protocol_sha256"] = "0" * 64
    for relative in tuple(entry["path"] for entry in manifest["scoring_adapters"]):
        destination = root / relative; destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(Path(__file__).resolve().parents[1] / relative, destination)
        for entry in manifest["scoring_adapters"]:
            if entry["path"] == relative:
                entry["sha256"] = digest(destination)
    custody = root / "manifests" / "custody.json"; custody.write_text(json.dumps(manifest), encoding="utf-8")
    binding = {"frozen_code_manifest_sha256": digest(custody), "suite": "humanevalplus_v0.1.10", "task_asset_sha256": manifest["frozen_task_assets"]["humanevalplus_v0.1.10"]["sha256"], "protocol_sha256": "0" * 64}
    with pytest.raises(ValueError, match="protocol"):
        module._load_frozen_code_manifest(custody, binding, binding["suite"])