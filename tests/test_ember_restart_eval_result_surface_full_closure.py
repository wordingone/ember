# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_result_surface.py"


def load_module():
    spec = importlib.util.spec_from_file_location("result_surface_full_closure", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_admission_snapshots_every_evaluation_receipt_before_contract(monkeypatch, tmp_path):
    module = load_module()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_bytes = b'{"receipt":"first"}'
    second_bytes = b'{"receipt":"second"}'
    first.write_bytes(first_bytes)
    second.write_bytes(second_bytes)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": first.name}, {"receipt_path": second.name}]}), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry_bytes = b"{}"
    registry.write_bytes(registry_bytes)
    authority = tmp_path / "authorities.json"
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(registry_bytes).hexdigest()}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)

    def run(command, **_kwargs):
        snapshot_manifest = Path(command[3])
        payload = json.loads(snapshot_manifest.read_text(encoding="utf-8"))
        staged = [snapshot_manifest.parent / entry["receipt_path"] for entry in payload["evaluations"]]
        assert all(path not in (first, second) for path in staged)
        assert [path.read_bytes() for path in staged] == [first_bytes, second_bytes]
        second.write_bytes(b'{"receipt":"swapped"}')
        assert staged[1].read_bytes() == second_bytes
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module._admitted(manifest, registry, first_bytes)


def test_admission_rejects_evaluation_path_escape_before_snapshot(monkeypatch, tmp_path):
    module = load_module()
    receipt = tmp_path / "receipt.json"
    receipt_bytes = b'{"receipt":"first"}'
    receipt.write_bytes(receipt_bytes)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": "../outside.json"}]}), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry_bytes = b"{}"
    registry.write_bytes(registry_bytes)
    authority = tmp_path / "authorities.json"
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(registry_bytes).hexdigest()}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("contract must not run")))
    assert not module._admitted(manifest, registry, receipt_bytes)