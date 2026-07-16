# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_result_surface.py"


def test_result_surface_validates_a_same_byte_manifest_snapshot(monkeypatch, tmp_path):
    specification = importlib.util.spec_from_file_location("result_surface_manifest_snapshot", SCRIPT)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    receipt = tmp_path / "receipt.json"
    receipt_bytes = b'{"result":"MEASURED"}'
    receipt.write_bytes(receipt_bytes)
    manifest = tmp_path / "manifest.json"
    manifest_bytes = json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": "receipt.json"}]}).encode("utf-8")
    manifest.write_bytes(manifest_bytes)

    def run(command, **_kwargs):
        snapshot = Path(command[3])
        assert snapshot != manifest
        assert snapshot.read_bytes() == manifest_bytes
        manifest.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": []}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module._admitted(manifest, tmp_path / "registry.json", receipt_bytes)
