# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ember_restart_eval_result_surface.py"


def load_module():
    spec = importlib.util.spec_from_file_location("result_surface_authority_identity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_refuses_registry_whose_bytes_do_not_match_the_execution_authority_anchor(tmp_path, monkeypatch):
    module = load_module()
    receipt = tmp_path / "receipt.json"
    receipt_bytes = b'{"result":"MEASURED","capability":"text"}'
    receipt.write_bytes(receipt_bytes)
    manifest = tmp_path / "admission.json"
    manifest.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": receipt.name}]}), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema_version": "ember-trusted-verifiers-v1", "verifiers": []}), encoding="utf-8")
    authority = tmp_path / "authorities.json"
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(b"different pinned registry").hexdigest()}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority, raising=False)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    assert not module._admitted(manifest, registry, receipt_bytes)


def test_admitted_renderer_preserves_receipt_identity_instead_of_colliding(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "_admitted", lambda *args: True)
    outputs = []
    for marker in ("a", "b"):
        source = tmp_path / f"receipt-{marker}.json"
        output = tmp_path / f"surface-{marker}.md"
        source.write_text(json.dumps({
            "result": "MEASURED", "capability": "text",
            "checkpoint_manifest_sha256": marker * 64,
            "model_config_sha256": "c" * 64,
            "benchmark_id": "local-text", "benchmark_version": marker,
            "split_sha256": "d" * 64, "harness_sha256": "e" * 64,
            "protocol_sha256": "f" * 64, "predictions_sha256": "1" * 64,
            "score_artifact_sha256": "2" * 64, "criterion_id": "ember-3b-text-capability-v1",
            "criterion_result": "PASSED", "metrics": {"accuracy": 1.0},
            "verifier_sha256": "3" * 64,
        }), encoding="utf-8")
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--input", str(source), "--output", str(output)])
        module.main()
        outputs.append(output.read_text(encoding="utf-8"))
    assert outputs[0] != outputs[1]
    for required in ("checkpoint_manifest_sha256", "benchmark_id", "benchmark_version", "split_sha256", "harness_sha256", "protocol_sha256", "predictions_sha256", "score_artifact_sha256", "criterion_id", "criterion_result", "metrics", "verifier_sha256"):
        assert required in outputs[0]