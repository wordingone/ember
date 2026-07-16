# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deletion tests for frozen admission and benchmark identity boundaries."""

import copy
import hashlib
import importlib.util
import json
import shutil
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


def test_result_surface_rejects_substituted_registry_even_with_consistent_snapshot(monkeypatch, tmp_path):
    module = _load("scripts/ember_restart_eval_result_surface.py", "identity_registry_anchor")
    receipt = tmp_path / "receipt.json"
    receipt_bytes = b'{"result":"MEASURED","capability":"text"}'
    receipt.write_bytes(receipt_bytes)
    admission = tmp_path / "admission.json"
    admission.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": receipt.name}]}), encoding="utf-8")
    good = b'{"schema_version":"ember-trusted-verifiers-v1","verifiers":[]}'
    substituted = tmp_path / "registry.json"
    substituted.write_bytes(good + b"\n")
    authority = tmp_path / "authorities.json"
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(good).hexdigest()}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)
    snapshot_root = tmp_path / "snapshot"
    snapshot_root.mkdir()
    snapshot = snapshot_root / "registry.json"
    snapshot.write_bytes(substituted.read_bytes())
    monkeypatch.setattr(module, "_pinned_registry_snapshot", lambda _path: (snapshot, snapshot_root))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    assert not module._admitted(admission, substituted, receipt_bytes)


def test_claim_renderer_preserves_identity_and_prevents_receipt_collision(monkeypatch, tmp_path):
    module = _load("scripts/ember_restart_eval_result_surface.py", "identity_renderer")
    monkeypatch.setattr(module, "_admitted", lambda *args: True)
    base = {
        "result": "MEASURED", "capability": "text", "model_config_sha256": "b" * 64,
        "benchmark_id": "local-text", "benchmark_version": "1", "split_sha256": "c" * 64,
        "harness_sha256": "d" * 64, "protocol_sha256": "e" * 64, "predictions_sha256": "f" * 64,
        "score_artifact_sha256": "1" * 64, "criterion_id": "ember-3b-text-capability-v1",
        "criterion_result": "PASSED", "metrics": {"accuracy": 1.0}, "verifier_sha256": "2" * 64,
    }
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps({**base, "checkpoint_manifest_sha256": "a" * 64}), encoding="utf-8")
    second.write_text(json.dumps({**base, "checkpoint_manifest_sha256": "9" * 64}), encoding="utf-8")
    outputs = []
    for source in (first, second):
        output = tmp_path / f"{source.stem}.md"
        monkeypatch.setattr(sys, "argv", [str(module.__file__), "--input", str(source), "--output", str(output)])
        module.main()
        outputs.append(output.read_text(encoding="utf-8"))
    assert outputs[0] != outputs[1]
    assert "checkpoint_manifest_sha256" in outputs[0]
    assert '"checkpoint_manifest_sha256":"aaaaaaaa' in outputs[0]
    assert '"checkpoint_manifest_sha256":"99999999' in outputs[1]


def test_audiobench_rejects_any_frozen_custody_tuple_substitution():
    module = _load("scripts/ember_restart_eval_audiobench_bound.py", "identity_audiobench")
    custody = json.loads((ROOT / "manifests" / "ember-restart-audiobench-custody-v1.json").read_text(encoding="utf-8"))
    for field, value in (("benchmark_version", "other-version"), ("suite", "other/suite"), ("protocol_sha256", "0" * 64)):
        mutated = copy.deepcopy(custody)
        mutated[field] = value
        with pytest.raises(ValueError, match="custody"):
            module._frozen_custody(json.dumps(mutated).encode("utf-8"))


def test_evalplus_spider_and_mmmu_reject_altered_checkpoint_protocol_or_version(tmp_path):
    evalplus = _load("scripts/ember_restart_eval_evalplus_result.py", "identity_evalplus")
    code_manifest = ROOT / "manifests" / "ember-restart-eval-code-math-custody-v1.json"
    source_manifest = json.loads(code_manifest.read_text(encoding="utf-8"))
    repo = tmp_path / "evalplus-repo"
    (repo / "manifests").mkdir(parents=True)
    for entry in source_manifest["scoring_adapters"]:
        destination = repo / entry["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / entry["path"], destination)
        entry["sha256"] = _sha(destination)
    source_manifest["protocol_sha256"] = evalplus.evalplus_protocol_sha256(source_manifest, "humanevalplus_v0.1.10", source_manifest["scoring_adapters"])
    code_manifest = repo / "manifests" / "custody.json"
    code_manifest.write_text(json.dumps(source_manifest), encoding="utf-8")
    binding = {
        "frozen_code_manifest_sha256": _sha(code_manifest),
        "suite": "humanevalplus_v0.1.10",
        "benchmark_id": "evalplus",
        "benchmark_version": "wrong-version",
        "task_asset_sha256": source_manifest["frozen_task_assets"]["humanevalplus_v0.1.10"]["sha256"],
        "protocol_sha256": source_manifest["protocol_sha256"],
    }
    with pytest.raises(ValueError, match="version"):
        evalplus._load_frozen_code_manifest(code_manifest, binding, binding["suite"])

    spider = _load("scripts/ember_restart_eval_spider.py", "identity_spider")
    envelope = {
        "schema_version": "ember-owned-predictions-v1", "claim_status": "NON_ADMISSIBLE_RAW_PREDICTIONS",
        "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64,
        "tokenizer_sha256": "c" * 64, "inference_implementation_sha256": "d" * 64,
        "benchmark": {"id": "spider", "version": spider.SPIDER_VERSION, "capability": "tool", "split_sha256": "e" * 64, "protocol_sha256": "0" * 64},
        "decoding": {"strategy": "GREEDY_AUTOREGRESSIVE", "teacher_forcing": False, "max_new_tokens": 1, "temperature": 0, "top_p": 1, "stop_token_ids": [2]},
        "rows": [{"id": "0", "input_sha256": "f" * 64, "generated_token_ids": [2], "stop_reason": "eos", "output": {"kind": "sql", "sql": "select 1"}}],
    }
    with pytest.raises(ValueError, match="canonical Spider"):
        spider.canonical_sql(json.dumps(envelope).encode("utf-8"), "e" * 64, "1" * 64)

    mmmu = _load("scripts/ember_restart_eval_mmmu.py", "identity_mmmu")
    with pytest.raises(ValueError, match="checkpoint"):
        mmmu.validate_manifest_identity({"checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64}, {"checkpoint_manifest_sha256": "9" * 64, "model_config_sha256": "b" * 64})
