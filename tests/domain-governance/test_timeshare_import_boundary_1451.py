# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Stage-1 verifier contract for the historical timeshare import boundary."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPTS = ROOT / "scripts"
TIMESHARE = SCRIPTS / "timeshare_pretrain.py"
VERIFIER = SCRIPTS / "verify_authority_conservation.py"
MANIFEST_REL = Path("docs/domains/governance/ember-restart/timeshare-importer-classification-1451-v1.json")


def _first_executable(body: list[ast.stmt]) -> ast.stmt | None:
    statements = list(body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements.pop(0)
    while (
        statements
        and isinstance(statements[0], ast.ImportFrom)
        and statements[0].module == "__future__"
    ):
        statements.pop(0)
    return statements[0] if statements else None


def _load_verifier():
    spec = importlib.util.spec_from_file_location("_stage1_authority_verifier", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_root() -> Path:
    root = Path(r"B:\tmp\niko-1451-stage1") / str(os.getpid())
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_stage1_fixture(root: Path) -> dict:
    source = root / "scripts" / "timeshare_pretrain.py"
    importer = root / "scripts" / "historical_importer.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    (root / "docs" / "ember-restart").mkdir(parents=True, exist_ok=True)
    source.write_bytes(TIMESHARE.read_bytes())
    importer.write_text(
        "# EMBER_ARTIFACT_CLASS=historical_only\n"
        "from timeshare_pretrain import build_v0_model\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "ember-timeshare-importer-classification-v1",
        "source": "src/ember/governance/scripts/timeshare_pretrain.py",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "import_denial": "execution_only",
        "importers": [
            {
                "path": "scripts/historical_importer.py",
                "classification": "historical_only",
                "import_outcome": "execution_denied_by_own_guard",
                "sha256": hashlib.sha256(importer.read_bytes()).hexdigest(),
                "module_scope": True,
                "nested_import_count": 0,
            }
        ],
    }
    (root / MANIFEST_REL).write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _write_future_stage_fixture(root: Path, variant: str = "valid") -> dict:
    source = root / "scripts" / "timeshare_pretrain.py"
    importer = root / "scripts" / "historical_importer.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    (root / "docs" / "ember-restart").mkdir(parents=True, exist_ok=True)
    source_text = (
        "# EMBER_ARTIFACT_CLASS=historical_only\n"
        "from __future__ import annotations\n\n"
        "def _historical_only_refusal():\n"
        "    raise SystemExit('historical_only')\n\n"
        "def main():\n"
    )
    if variant == "missing-main-call":
        source_text += "    return None\n\n"
    else:
        source_text += "    _historical_only_refusal()\n\n"
    if variant == "missing-main-route":
        source_text += "# execution-only import shape without a __main__ route\n"
    else:
        source_text += "if __name__ == '__main__':\n    main()\n"
    source.write_text(source_text, encoding="utf-8", newline="\n")
    for relative in ("src/ember/governance/scripts/conv_c03_muon_ns3_live.py", "src/ember/governance/scripts/train_multimodal_v0.py"):
        historical = root / relative
        historical.parent.mkdir(parents=True, exist_ok=True)
        historical.write_text(
            "# EMBER_ARTIFACT_CLASS=historical_only\n"
            "raise SystemExit('historical_only')\n",
            encoding="utf-8",
        )
    importer.write_text(
        "# EMBER_ARTIFACT_CLASS=historical_only\n"
        "from timeshare_pretrain import build_v0_model\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "ember-timeshare-importer-classification-v1",
        "source": "src/ember/governance/scripts/timeshare_pretrain.py",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "import_denial": "execution_only",
        "execution_boundary": {
            "helper": "_historical_only_refusal",
            "main": "main",
            "entrypoint": "__main__",
        },
        "importers": [
            {
                "path": "scripts/historical_importer.py",
                "classification": "historical_only",
                "import_outcome": "importable",
                "sha256": hashlib.sha256(importer.read_bytes()).hexdigest(),
                "module_scope": True,
                "nested_import_count": 0,
            }
        ],
    }
    (root / MANIFEST_REL).write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_stage1_base_kernel_refusal_remains_green():
    tree = ast.parse(TIMESHARE.read_text(encoding="utf-8"), filename=str(TIMESHARE))
    first = _first_executable(tree.body)
    assert isinstance(first, ast.Raise)
    assert isinstance(first.exc, ast.Call)
    assert isinstance(first.exc.func, ast.Name)
    assert first.exc.func.id == "SystemExit"

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", str(TIMESHARE), "--selftest"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "historical_only" in result.stdout + result.stderr


def test_stage1_verifier_accepts_closed_execution_only_manifest():
    root = _fixture_root()
    try:
        _write_future_stage_fixture(root)
        errors: list[dict] = []
        _load_verifier().check_execution_only_import_boundary(root, errors)
        assert errors == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_stage1_verifier_rejects_foreign_path_and_rehashed_source():
    root = _fixture_root()
    try:
        manifest = _write_stage1_fixture(root)
        manifest["source_sha256"] = "0" * 64
        manifest["importers"][0]["path"] = "scripts/../foreign.py"
        (root / MANIFEST_REL).write_text(json.dumps(manifest), encoding="utf-8")
        errors: list[dict] = []
        _load_verifier().check_execution_only_import_boundary(root, errors)
        codes = {item["code"] for item in errors}
        assert "historical.import_manifest_source_hash" in codes
        assert "historical.import_manifest_path" in codes
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_future_stage_import_safe_shape_is_accepted_only_with_closed_manifest():
    root = _fixture_root()
    try:
        _write_future_stage_fixture(root)
        errors: list[dict] = []
        verifier = _load_verifier()
        verifier.check_historical_executables(root, errors)
        verifier.check_execution_only_import_boundary(root, errors)
        assert errors == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_future_stage_missing_main_call_refuses_before_import_boundary():
    root = _fixture_root()
    try:
        _write_future_stage_fixture(root, "missing-main-call")
        errors: list[dict] = []
        verifier = _load_verifier()
        verifier.check_historical_executables(root, errors)
        verifier.check_execution_only_import_boundary(root, errors)
        assert "historical.execution_main_call" in {item["code"] for item in errors}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_future_stage_missing_main_route_refuses():
    root = _fixture_root()
    try:
        _write_future_stage_fixture(root, "missing-main-route")
        errors: list[dict] = []
        verifier = _load_verifier()
        verifier.check_historical_executables(root, errors)
        verifier.check_execution_only_import_boundary(root, errors)
        assert "historical.execution_entrypoint" in {item["code"] for item in errors}
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.parametrize("mutation", ["malformed", "foreign"])
def test_future_stage_malformed_or_foreign_manifest_refuses(mutation: str):
    root = _fixture_root()
    try:
        manifest = _write_future_stage_fixture(root)
        if mutation == "malformed":
            manifest["execution_boundary"].pop("main")
        else:
            manifest["execution_boundary"]["helper"] = "foreign_helper"
        (root / MANIFEST_REL).write_text(json.dumps(manifest), encoding="utf-8")
        errors: list[dict] = []
        verifier = _load_verifier()
        verifier.check_historical_executables(root, errors)
        verifier.check_execution_only_import_boundary(root, errors)
        codes = {item["code"] for item in errors}
        assert "historical.import_manifest_execution_contract" in codes
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.parametrize("mutation", ["unknown", "missing"])
def test_future_stage_top_level_manifest_shape_is_closed(mutation: str):
    root = _fixture_root()
    try:
        manifest = _write_future_stage_fixture(root)
        if mutation == "unknown":
            manifest["unreviewed_authority"] = "foreign"
        else:
            manifest.pop("importers")
        (root / MANIFEST_REL).write_text(json.dumps(manifest), encoding="utf-8")
        errors: list[dict] = []
        verifier = _load_verifier()
        verifier.check_historical_executables(root, errors)
        verifier.check_execution_only_import_boundary(root, errors)
        codes = {item["code"] for item in errors}
        assert "historical.import_manifest_keys" in codes
        assert "historical.execution_guard_missing" in codes
    finally:
        shutil.rmtree(root, ignore_errors=True)
