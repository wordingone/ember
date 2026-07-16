# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ember_restart_eval_result_surface.py"


def load_module():
    spec = importlib.util.spec_from_file_location("result_surface_transitive_closure", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def setup_admission(tmp_path: Path, receipt_bytes: bytes = b'{"nested_path":"nested.json"}'):
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(receipt_bytes)
    nested = tmp_path / "nested.json"
    nested.write_bytes(b"nested-original")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": receipt.name}]}), encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry_bytes = b"{}"
    registry.write_bytes(registry_bytes)
    authority = tmp_path / "authorities.json"
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(registry_bytes).hexdigest()}]}), encoding="utf-8")
    return receipt, nested, manifest, registry, authority


def test_admission_stages_transitive_paths_referenced_by_receipt(monkeypatch, tmp_path):
    module = load_module()
    receipt, nested, manifest, registry, authority = setup_admission(tmp_path)
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)

    def run(command, **_kwargs):
        snapshot_manifest = Path(command[3])
        payload = json.loads(snapshot_manifest.read_text(encoding="utf-8"))
        staged_receipt = snapshot_manifest.parent / payload["evaluations"][0]["receipt_path"]
        receipt_payload = json.loads(staged_receipt.read_text(encoding="utf-8"))
        staged_nested = staged_receipt.parent / receipt_payload["nested_path"]
        assert staged_nested.read_bytes() == b"nested-original"
        nested.write_bytes(b"nested-swapped")
        assert staged_nested.read_bytes() == b"nested-original"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module._admitted(manifest, registry, receipt.read_bytes())


def test_admission_snapshots_registry_verifier_closure(monkeypatch, tmp_path):
    module = load_module()
    receipt, _nested, manifest, registry, authority = setup_admission(tmp_path, b"{}")
    verifier = tmp_path / "verifier.py"
    verifier.write_bytes(b"VERIFIER ORIGINAL")
    registry.write_text(json.dumps({"schema_version": "ember-trusted-verifiers-v1", "verifiers": [{"path": verifier.name, "sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(), "evidence_classes": ["evaluation"], "criterion_ids": ["ember-3b-text-capability-v1"]}]}), encoding="utf-8")
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest()}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)

    def run(command, **_kwargs):
        snapshot_registry = Path(command[-1])
        entry = json.loads(snapshot_registry.read_text(encoding="utf-8"))["verifiers"][0]
        verifier.write_bytes(b"VERIFIER SWAPPED")
        assert (snapshot_registry.parent / entry["path"]).read_bytes() == b"VERIFIER ORIGINAL"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module._admitted(manifest, registry, receipt.read_bytes())


def test_admission_rejects_symlink_before_resolve(monkeypatch, tmp_path):
    module = load_module()
    target = tmp_path / "target.json"
    target.write_bytes(b"target")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    _receipt, _nested, manifest, registry, authority = setup_admission(tmp_path, b"target")
    manifest.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": link.name}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("contract must not run")))
    assert not module._admitted(manifest, registry, b"target")


def test_admission_surfaces_cleanup_failure(monkeypatch, tmp_path):
    module = load_module()
    receipt, _nested, manifest, registry, authority = setup_admission(tmp_path)
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(module.shutil, "rmtree", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("cleanup denied")))
    with pytest.raises(RuntimeError, match="cleanup"):
        module._admitted(manifest, registry, receipt.read_bytes())

def test_admission_uses_each_json_document_base_and_ignores_serving_identity_route(monkeypatch, tmp_path):
    module = load_module()
    checkpoint = tmp_path / "checkpoint"; shards = checkpoint / "shards"; shards.mkdir(parents=True)
    receipt = checkpoint / "receipt.json"; receipt.write_text(json.dumps({"shards_dir": "shards"}), encoding="utf-8")
    (shards / "shared.bin").write_bytes(b"shared")
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": "checkpoint/receipt.json"}], "cli": {"identity_path": "/v1/models"}}), encoding="utf-8")
    registry = tmp_path / "registry.json"; registry_bytes = b"{}"; registry.write_bytes(registry_bytes)
    authority = tmp_path / "authorities.json"; authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(registry_bytes).hexdigest()}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)

    def run(command, **_kwargs):
        snapshot_manifest = Path(command[3]); snapshot_payload = json.loads(snapshot_manifest.read_text(encoding="utf-8"))
        staged_receipt = snapshot_manifest.parent / snapshot_payload["evaluations"][0]["receipt_path"]
        assert (staged_receipt.parent / "shards" / "shared.bin").read_bytes() == b"shared"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module._admitted(manifest, registry, receipt.read_bytes())


def test_admission_snapshots_imported_registry_verifier_helpers(monkeypatch, tmp_path):
    module = load_module()
    receipt, _nested, manifest, registry, authority = setup_admission(tmp_path, b"{}")
    verifier = tmp_path / "verifier.py"; helper = tmp_path / "helper.py"
    verifier.write_text("import helper\n", encoding="utf-8"); helper.write_bytes(b"VALUE = 'original'\n")
    registry.write_text(json.dumps({"schema_version": "ember-trusted-verifiers-v1", "verifiers": [{"path": verifier.name, "sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(), "evidence_classes": ["evaluation"], "criterion_ids": ["ember-3b-text-capability-v1"]}]}), encoding="utf-8")
    authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest()}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)

    def run(command, **_kwargs):
        snapshot_registry = Path(command[-1]); helper.write_bytes(b"VALUE = 'swapped'\n")
        assert (snapshot_registry.parent / "helper.py").read_bytes() == b"VALUE = 'original'\n"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module._admitted(manifest, registry, receipt.read_bytes())


def test_admission_rejects_symlink_parent_components(monkeypatch, tmp_path):
    module = load_module()
    real = tmp_path / "real"; real.mkdir(); receipt = real / "receipt.json"; receipt.write_bytes(b"{}")
    linkdir = tmp_path / "linkdir"
    try:
        linkdir.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation unavailable")
    manifest = tmp_path / "manifest.json"; manifest.write_text(json.dumps({"stage": "OWNED_ADMITTED", "evaluations": [{"receipt_path": "linkdir/receipt.json"}]}), encoding="utf-8")
    registry = tmp_path / "registry.json"; registry_bytes = b"{}"; registry.write_bytes(registry_bytes)
    authority = tmp_path / "authorities.json"; authority.write_text(json.dumps({"authorities": [{"trusted_verifier_registry_sha256": hashlib.sha256(registry_bytes).hexdigest()}]}), encoding="utf-8")
    monkeypatch.setattr(module, "EXECUTION_AUTHORITIES", authority)
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("contract must not run")))
    assert not module._admitted(manifest, registry, b"{}")