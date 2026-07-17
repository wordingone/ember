# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused regressions for the four #862 identity/custody P1s.

These tests are intentionally narrow: they exercise the production APIs that
must fail closed when a caller substitutes an authority, erases receipt
identity, or detaches a scorer from its frozen benchmark custody.
"""

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(relative: str, name: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_result_surface_rejects_a_consistent_but_substituted_registry(tmp_path, monkeypatch):
    module = _load("scripts/ember_restart_eval_result_surface.py", "p1_matrix_surface")
    receipt = tmp_path / "receipt.json"
    receipt_bytes = b'{"result":"MEASURED","capability":"text"}'
    receipt.write_bytes(receipt_bytes)
    admission = tmp_path / "admission.json"
    admission.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": receipt.name}]}), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry_bytes = b'{"schema_version":"ember-trusted-verifiers-v1","verifiers":[]}'
    registry.write_bytes(registry_bytes)
    authority = tmp_path / "authorities.json"
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(b"different-registry").hexdigest()}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)
    assert not module._admitted(admission, registry, receipt_bytes)


def test_claim_renderer_preserves_identity_and_prevents_collisions(tmp_path, monkeypatch):
    module = _load("scripts/ember_restart_eval_result_surface.py", "p1_matrix_renderer")
    monkeypatch.setattr(module, "_admitted", lambda *args: True)
    base = {
        "result": "MEASURED", "capability": "text", "model_config_sha256": "b" * 64,
        "benchmark_id": "local-text", "benchmark_version": "1", "split_sha256": "c" * 64,
        "harness_sha256": "d" * 64, "protocol_sha256": "e" * 64, "predictions_sha256": "f" * 64,
        "score_artifact_sha256": "1" * 64, "criterion_id": "ember-3b-text-capability-v1",
        "criterion_result": "PASSED", "metrics": {"accuracy": 1.0}, "verifier_sha256": "2" * 64,
    }
    rendered = []
    for marker in ("a", "9"):
        source = tmp_path / f"receipt-{marker}.json"
        source.write_text(json.dumps({**base, "checkpoint_manifest_sha256": marker * 64}), encoding="utf-8")
        output = tmp_path / f"surface-{marker}.md"
        monkeypatch.setattr(sys, "argv", [str(module.__file__), "--input", str(source), "--output", str(output)])
        module.main()
        rendered.append(output.read_text(encoding="utf-8"))
    assert rendered[0] != rendered[1]
    assert '"checkpoint_manifest_sha256":"aaaaaaaa' in rendered[0]
    assert '"checkpoint_manifest_sha256":"99999999' in rendered[1]
    for field in module.IDENTITY_FIELDS:
        assert field in rendered[0]


def test_audiobench_rejects_changed_frozen_version_suite_and_protocol(tmp_path):
    module = _load("scripts/ember_restart_eval_audiobench_bound.py", "p1_matrix_audio")
    custody = json.loads((ROOT / "manifests" / "ember-restart-audiobench-custody-v1.json").read_text(encoding="utf-8"))
    for field, value in (("benchmark_version", "substituted-version"), ("suite", "foreign/suite"), ("protocol_sha256", "0" * 64)):
        mutated = copy.deepcopy(custody)
        mutated[field] = value
        with pytest.raises(ValueError, match="custody"):
            module._frozen_custody(json.dumps(mutated, sort_keys=True).encode("utf-8"))


def test_evalplus_spider_and_mmmu_reject_altered_protocol_or_checkpoint(tmp_path):
    evalplus = _load("scripts/ember_restart_eval_evalplus_result.py", "p1_matrix_evalplus")
    manifest = json.loads((ROOT / "manifests" / "ember-restart-eval-code-math-custody-v1.json").read_text(encoding="utf-8"))
    manifest["checkpoint_manifest_sha256"] = "a" * 64
    manifest["model_config_sha256"] = "b" * 64
    repo = tmp_path / "evalplus"; (repo / "manifests").mkdir(parents=True)
    for entry in manifest["scoring_adapters"]:
        destination = repo / entry["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / entry["path"]).read_bytes())
        entry["sha256"] = _sha(destination)
    manifest["protocol_sha256"] = evalplus.evalplus_protocol_sha256(manifest, "humanevalplus_v0.1.10", manifest["scoring_adapters"])
    frozen = repo / "manifests" / "custody.json"; frozen.write_text(json.dumps(manifest), encoding="utf-8")
    binding = {"frozen_code_manifest_sha256": _sha(frozen), "suite": "humanevalplus_v0.1.10", "benchmark_id": "evalplus", "benchmark_version": "v0.1.10", "task_asset_sha256": manifest["frozen_task_assets"]["humanevalplus_v0.1.10"]["sha256"], "protocol_sha256": manifest["protocol_sha256"], "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64}
    with pytest.raises(ValueError, match="checkpoint"):
        evalplus._load_frozen_code_manifest(frozen, {**binding, "checkpoint_manifest_sha256": "9" * 64}, binding["suite"])

    spider = _load("scripts/ember_restart_eval_spider.py", "p1_matrix_spider")
    with pytest.raises(ValueError, match="canonical Spider"):
        envelope = {"schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64, "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64, "benchmark": {"id": "spider", "version": spider.SPIDER_VERSION, "capability": "tool", "split_sha256": "e" * 64, "protocol_sha256": "0" * 64}, "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]}, "rows": [{"id": "0", "input_sha256": "f" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "sql", "sql": "select 1"}}]}
        spider.canonical_sql(json.dumps(envelope).encode(), "e" * 64, "1" * 64)

    mmmu = _load("scripts/ember_restart_eval_mmmu.py", "p1_matrix_mmmu")
    with pytest.raises(ValueError, match="checkpoint"):
        mmmu.validate_manifest_identity({"checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64}, {"checkpoint_manifest_sha256": "9" * 64, "model_config_sha256": "b" * 64})
