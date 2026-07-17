# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_audiobench_source_audit.py"
_SPEC = importlib.util.spec_from_file_location("audiobench_source_audit", SCRIPT)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)


def test_source_audit_requires_exact_git_and_license_identity(tmp_path, monkeypatch):
    custody = {
        "benchmark_id": "audiobench",
        "benchmark_version": "0fc7fef2709c00ac1e2eb2b372ec4c56362bb8c6",
        "upstream_tree_git_sha1": "a" * 40,
        "license_sha256": "b" * 64,
        "upstream_commit": "c" * 40,
        "suite": "ab/sound-id",
    }
    monkeypatch.setattr(_MODULE, "CUSTODY", tmp_path / "custody.json")
    _MODULE.CUSTODY.write_text(json.dumps(custody), encoding="utf-8")
    (tmp_path / "LICENSE").write_bytes(b"license")
    monkeypatch.setattr(_MODULE, "_git_identity", lambda root: {"source_commit": "c" * 40, "source_tree": "a" * 40})
    monkeypatch.setattr(_MODULE, "_license_sha256", lambda root: "b" * 64)
    value = _MODULE.audit_source(tmp_path)
    assert value["source_commit"] == "c" * 40
    assert value["source_tree"] == "a" * 40
    assert value["license_sha256"] == "b" * 64
    assert value["target_execution_permitted"] is False


def test_source_audit_rejects_drift_before_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(_MODULE, "CUSTODY", tmp_path / "custody.json")
    _MODULE.CUSTODY.write_text(json.dumps({
        "benchmark_id": "audiobench",
        "benchmark_version": "v",
        "upstream_tree_git_sha1": "a" * 40,
        "license_sha256": "b" * 64,
        "upstream_commit": "c" * 40,
        "suite": "ab/sound-id",
    }), encoding="utf-8")
    monkeypatch.setattr(_MODULE, "_git_identity", lambda root: {"source_commit": "d" * 40, "source_tree": "a" * 40})
    with pytest.raises(ValueError, match="commit"):
        _MODULE.audit_source(tmp_path)


def test_source_audit_publication_is_fresh(tmp_path):
    output = tmp_path / "audit.json"
    _MODULE.atomic_write(output, {"result": "PREFLIGHT_ONLY"})
    with pytest.raises(ValueError, match="must not pre-exist"):
        _MODULE.atomic_write(output, {"result": "PREFLIGHT_ONLY"})

def test_public_audio_custody_binds_source_audit_command():
    root = Path(__file__).parents[1]
    value = json.loads((root / "manifests" / "ember-restart-audiobench-custody-v1.json").read_text(encoding="utf-8"))
    audit = value["source_audit"]
    assert audit["path"] == "scripts/ember_restart_eval_audiobench_source_audit.py"
    assert audit["sha256"] == __import__("hashlib").sha256((root / audit["path"]).read_bytes()).hexdigest()
    assert audit["result_disposition"] == "PREFLIGHT_ONLY_NON_ADMISSIBLE"
