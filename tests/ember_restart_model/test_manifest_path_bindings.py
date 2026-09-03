# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "check_manifest_path_bindings.py"
SPEC = importlib.util.spec_from_file_location("check_manifest_path_bindings", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def write_manifest(root: Path, relative: str, digest: str) -> None:
    directory = root / "data" / "ember-restart-3b"
    directory.mkdir(parents=True)
    (directory / "stream.json").write_text(
        json.dumps({"binding": {"path": relative, "sha256": digest}}),
        encoding="utf-8",
    )


def test_manifest_binding_gate_accepts_exact_file(tmp_path: Path) -> None:
    target = tmp_path / "configs" / "model.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"model\n")
    write_manifest(tmp_path, "configs/model.json", hashlib.sha256(target.read_bytes()).hexdigest())
    assert module.validate(tmp_path) == []


def test_manifest_binding_gate_reds_missing_file(tmp_path: Path) -> None:
    write_manifest(tmp_path, "configs/missing.json", "0" * 64)
    errors = module.validate(tmp_path)
    assert len(errors) == 1
    assert "missing binding configs/missing.json" in errors[0]


def test_manifest_binding_gate_reds_hash_drift(tmp_path: Path) -> None:
    target = tmp_path / "configs" / "model.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"model\n")
    write_manifest(tmp_path, "configs/model.json", "0" * 64)
    errors = module.validate(tmp_path)
    assert len(errors) == 1
    assert "sha256 mismatch" in errors[0]


def test_manifest_binding_gate_accepts_declared_path_migration(tmp_path: Path) -> None:
    target = tmp_path / "domains" / "model" / "tokenizer" / "tokenizer.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"tokenizer\n")
    write_manifest(
        tmp_path,
        "tokenizer/tokenizer.json",
        hashlib.sha256(target.read_bytes()).hexdigest(),
    )
    assert module.validate(tmp_path) == []
