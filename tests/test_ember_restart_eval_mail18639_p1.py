# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused test-first coverage for the four reviewed P1 boundaries."""

import hashlib
import importlib.util
import json
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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _complete_receipt(checkpoint: str) -> dict:
    return {
        "result": "MEASURED",
        "capability": "text",
        "checkpoint_manifest_sha256": checkpoint,
        "model_config_sha256": "b" * 64,
        "benchmark_id": "local-text",
        "benchmark_version": "1",
        "split_sha256": "c" * 64,
        "harness_sha256": "d" * 64,
        "protocol_sha256": "e" * 64,
        "predictions_sha256": "f" * 64,
        "score_artifact_sha256": "1" * 64,
        "criterion_id": "ember-3b-text-capability-v1",
        "criterion_result": "PASSED",
        "metrics": {"accuracy": 1.0},
        "verifier_sha256": "2" * 64,
    }


def test_result_surface_requires_external_trust_anchor_for_registry_bytes(tmp_path, monkeypatch):
    module = _load("scripts/ember_restart_eval_result_surface.py", "mail18639_registry_anchor")
    registry = tmp_path / "registry.json"
    registry_bytes = b'{"schema_version":"ember-trusted-verifiers-v1","verifiers":[]}'
    registry.write_bytes(registry_bytes)
    authority = tmp_path / "authorities.json"
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": _sha(b"different-registry")}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)
    assert module._registry_is_pinned(registry) is False
    assert module._registry_is_pinned_bytes(registry_bytes) is False


def test_claim_renderer_keeps_distinct_checkpoint_identity_in_claim_bytes(tmp_path, monkeypatch):
    module = _load("scripts/ember_restart_eval_result_surface.py", "mail18639_identity_renderer")
    monkeypatch.setattr(module, "_admitted", lambda *args: True)
    rendered = []
    for marker in ("a", "9"):
        source = tmp_path / f"receipt-{marker}.json"
        source.write_text(json.dumps(_complete_receipt(marker * 64)), encoding="utf-8")
        output = tmp_path / f"surface-{marker}.md"
        monkeypatch.setattr(sys, "argv", [str(module.__file__), "--input", str(source), "--output", str(output)])
        module.main()
        rendered.append(output.read_text(encoding="utf-8"))
    assert rendered[0] != rendered[1]
    assert '"checkpoint_manifest_sha256":"aaaaaaaa' in rendered[0]
    assert '"checkpoint_manifest_sha256":"99999999' in rendered[1]
    for field in module.IDENTITY_FIELDS:
        assert f"{field}:" in rendered[0]


def test_audiobench_requires_frozen_version_suite_protocol_and_closed_run_custody(tmp_path):
    module = _load("scripts/ember_restart_eval_audiobench_bound.py", "mail18639_audio_custody")
    custody = json.loads((ROOT / "manifests" / "ember-restart-audiobench-custody-v1.json").read_text(encoding="utf-8"))
    assert custody["benchmark_id"] == "audiobench"
    for field, bad in (
        ("benchmark_version", "foreign-version"),
        ("suite", "foreign-suite"),
        ("protocol_sha256", "0" * 64),
        ("closed_run_artifact_sha256", None),
    ):
        mutated = dict(custody)
        mutated[field] = bad
        with pytest.raises(ValueError, match="custody"):
            module._frozen_custody(json.dumps(mutated, sort_keys=True).encode())


def test_evalplus_spider_and_mmmu_reject_identity_drift_before_scoring():
    evalplus = _load("scripts/ember_restart_eval_evalplus_result.py", "mail18639_evalplus")
    with pytest.raises(ValueError, match="checkpoint/config"):
        evalplus.evalplus_protocol_sha256({
            "frozen_task_assets": {"humanevalplus_v0.1.10": {"sha256": "a" * 64}},
            "license_sha256": "b" * 64,
            "source_commit": "c" * 40,
            "source_tree": "d" * 40,
        }, "humanevalplus_v0.1.10", [])

    spider = _load("scripts/ember_restart_eval_spider.py", "mail18639_spider")
    with pytest.raises(ValueError, match="checkpoint_manifest_sha256"):
        spider.require_canonical_identity({"schema_version": "ember-restart-benchmark-custody-v1", "protocol_sha256": "a" * 64})

    mmmu = _load("scripts/ember_restart_eval_mmmu.py", "mail18639_mmmu")
    with pytest.raises(ValueError, match="checkpoint"):
        mmmu.validate_manifest_identity(
            {"schema_version": "ember-restart-benchmark-custody-v1", "checkpoint_manifest_sha256": "a" * 64, "model_config_sha256": "b" * 64},
            {"checkpoint_manifest_sha256": "9" * 64, "model_config_sha256": "b" * 64},
        )
