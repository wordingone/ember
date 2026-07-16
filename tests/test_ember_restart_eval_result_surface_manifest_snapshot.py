# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_result_surface.py"


def test_result_surface_validates_snapshotted_registry_and_receipt_bytes(monkeypatch, tmp_path):
    specification = importlib.util.spec_from_file_location("result_surface_manifest_snapshot", SCRIPT)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    receipt = tmp_path / "receipt.json"
    receipt_bytes = b'{"result":"MEASURED"}'
    receipt.write_bytes(receipt_bytes)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": "receipt.json"}]}).encode("utf-8"))
    registry = tmp_path / "registry.json"
    registry_bytes = b"{}"
    registry.write_bytes(registry_bytes)
    authority = tmp_path / "authorities.json"
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(registry_bytes).hexdigest()}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)

    def run(command, **_kwargs):
        snapshot_manifest = Path(command[3])
        snapshot_registry = Path(command[-1])
        snapshot_payload = json.loads(snapshot_manifest.read_text(encoding="utf-8"))
        staged_receipt = snapshot_manifest.parent / snapshot_payload["evaluations"][0]["receipt_path"]
        assert staged_receipt != receipt
        assert staged_receipt.read_bytes() == receipt_bytes
        assert snapshot_registry != registry
        assert snapshot_registry.read_bytes() == registry_bytes
        receipt.write_bytes(b'{"result":"SWAPPED"}')
        registry.write_text("{\"substituted\":true}", encoding="utf-8")
        manifest.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": []}), encoding="utf-8")
        assert staged_receipt.read_bytes() == receipt_bytes
        assert snapshot_registry.read_bytes() == registry_bytes
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module._admitted(manifest, registry, receipt_bytes)