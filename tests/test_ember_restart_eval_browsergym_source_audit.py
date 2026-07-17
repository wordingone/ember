# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ember_restart_eval_browsergym_source_audit.py"


def _load():
    spec = importlib.util.spec_from_file_location("browsergym_source_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _checkout(tmp_path: Path, commit: str, license_bytes: bytes = b"Apache-2.0\n") -> Path:
    root = tmp_path / "browsergym"
    root.mkdir()
    (root / "LICENSE").write_bytes(license_bytes)
    (root / "README.md").write_text("source only\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    assert actual == commit
    return root


def _custody(tmp_path: Path, source: Path) -> None:
    manifest = json.loads((ROOT / "manifests" / "ember-restart-eval-browser-tool-custody-v1.json").read_text(encoding="utf-8"))
    browser = manifest["browser_ui"]
    browser["source_commit"] = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    browser["source_tree"] = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD^{tree}"], text=True).strip()
    browser["license_sha256"] = hashlib.sha256((source / "LICENSE").read_bytes()).hexdigest()
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / "ember-restart-eval-browser-tool-custody-v1.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_browsergym_source_audit_emits_fail_closed_source_receipt(tmp_path, monkeypatch):
    module = _load()
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "LICENSE").write_bytes(b"Apache-2.0\n")
    (seed / "README.md").write_text("source only\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(seed), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(seed), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(seed), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(seed), "add", "."], check=True)
    subprocess.run(["git", "-C", str(seed), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.check_output(["git", "-C", str(seed), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(seed), "rev-parse", "HEAD^{tree}"], text=True).strip()
    custody = tmp_path / "custody.json"
    custody.write_text(json.dumps({"browser_ui": {"benchmark_id": "browsergym-miniwob", "source_commit": commit, "source_tree": tree, "license_sha256": hashlib.sha256((seed / "LICENSE").read_bytes()).hexdigest()}}), encoding="utf-8")
    monkeypatch.setattr(module, "CUSTODY", custody)
    output = tmp_path / "audit.json"
    payload = module.audit_source(seed)
    module._atomic_write(output, payload)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["result"] == "PREFLIGHT_ONLY"
    assert payload["admission"] == "NOT_ELIGIBLE"
    assert payload["target_execution_permitted"] is False
    assert payload["runtime_or_task_bundle"] is None


def test_browsergym_source_audit_rejects_commit_or_license_drift(tmp_path, monkeypatch):
    module = _load()
    root = tmp_path / "source"
    root.mkdir()
    (root / "LICENSE").write_bytes(b"Apache-2.0\n")
    (root / "README.md").write_text("source only\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    custody = tmp_path / "custody.json"
    custody.write_text(json.dumps({"browser_ui": {"benchmark_id": "browsergym-miniwob", "source_commit": "0" * 40, "source_tree": "0" * 40, "license_sha256": "f" * 64}}), encoding="utf-8")
    monkeypatch.setattr(module, "CUSTODY", custody)
    with pytest.raises(ValueError, match="commit"):
        module.audit_source(root)
    custody.write_text(json.dumps({"browser_ui": {"benchmark_id": "browsergym-miniwob", "source_commit": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), "source_tree": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], text=True).strip(), "license_sha256": "f" * 64}}), encoding="utf-8")
    with pytest.raises(ValueError, match="LICENSE"):
        module.audit_source(root)


def test_browsergym_source_audit_refuses_preexisting_output_and_cleans_replace_failure(tmp_path, monkeypatch):
    module = _load()
    root = tmp_path / "source"
    root.mkdir()
    (root / "LICENSE").write_bytes(b"Apache-2.0\n")
    (root / "README.md").write_text("source only\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    custody = tmp_path / "custody.json"
    custody.write_text(json.dumps({"browser_ui": {"benchmark_id": "browsergym-miniwob", "source_commit": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), "source_tree": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], text=True).strip(), "license_sha256": hashlib.sha256((root / "LICENSE").read_bytes()).hexdigest()}}), encoding="utf-8")
    monkeypatch.setattr(module, "CUSTODY", custody)
    output = tmp_path / "audit.json"
    output.write_text("old", encoding="utf-8")
    with pytest.raises(ValueError, match="pre-exist"):
        module._atomic_write(output, {})
    output.unlink()
    monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace denied")))
    with pytest.raises(OSError, match="replace denied"):
        module._atomic_write(output, module.audit_source(root))
    assert not output.exists() and not list(tmp_path.glob("audit.json.*.tmp"))


def test_public_browsergym_custody_will_bind_the_audit_command():
    custody = json.loads((ROOT / "manifests" / "ember-restart-eval-browser-tool-custody-v1.json").read_text(encoding="utf-8"))
    assert custody["browser_ui"]["target_execution_permitted"] is False
