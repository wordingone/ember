# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Receipt-family import-boundary regressions.

Direct admission and connector entry points append the repository root when
they use package-qualified intra-repository imports.  Unlike publishing a
module directory at position zero, appending the root introduces no bare module
names and does not shadow standard-library or site-package imports.  A
repository-wide root ``conftest.py`` or pytest ``pythonpath`` setting remains
separate durable debt.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
ADMISSION = ROOT / "scripts" / "ember_admission"
CONNECTORS = ROOT / "tools" / "corpus_connectors"
FAMILY_ROOTS = (ADMISSION, CONNECTORS)
PREAMBLE_APPEND = "sys.path.append(str(_REPO_ROOT))"
PACKAGE_IMPORT_PREFIXES = ("scripts.ember_admission", "tools.corpus_connectors")


def _load_as_top_level_receipt(path: Path) -> object:
    spec = importlib.util.spec_from_file_location("receipt", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["receipt"] = module
    spec.loader.exec_module(module)
    return module


def _clear_modules(*prefixes: str) -> None:
    for name in tuple(sys.modules):
        if name == "receipt" or any(
            name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes
        ):
            sys.modules.pop(name, None)


def test_connector_consumer_ignores_preloaded_admission_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_modules("scripts.ember_admission", "tools.corpus_connectors")
    monkeypatch.syspath_prepend(str(ADMISSION))
    admission_receipt = _load_as_top_level_receipt(ADMISSION / "receipt.py")

    connector = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.arxiv_fetch")
    canonical = importlib.import_module("src.ember.infrastructure.tools.corpus_connectors.receipt")

    assert connector.rcpt is canonical
    assert connector.rcpt is not admission_receipt


def test_admission_consumer_ignores_preloaded_connector_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_modules("scripts.ember_admission", "tools.corpus_connectors")
    monkeypatch.syspath_prepend(str(ADMISSION))
    connector_receipt = _load_as_top_level_receipt(CONNECTORS / "receipt.py")

    candidate = importlib.import_module("src.ember.governance.scripts.ember_admission.produce_candidate")
    canonical = importlib.import_module("src.ember.governance.scripts.ember_admission.receipt")

    assert candidate.verify_producer_receipt is canonical.verify_producer_receipt
    assert canonical is not connector_receipt


def _has_main_guard(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            continue
        if not isinstance(test.left, ast.Name) or test.left.id != "__name__":
            continue
        if not isinstance(test.ops[0], ast.Eq) or len(test.comparators) != 1:
            continue
        value = test.comparators[0]
        if isinstance(value, ast.Constant) and value.value == "__main__":
            return True
    return False


def _has_package_import(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(PACKAGE_IMPORT_PREFIXES):
                return True
        if isinstance(node, ast.Import):
            if any(alias.name.startswith(PACKAGE_IMPORT_PREFIXES) for alias in node.names):
                return True
    return False


def _direct_package_entrypoints() -> tuple[Path, ...]:
    selected = []
    for family_root in FAMILY_ROOTS:
        for path in sorted(family_root.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if _has_main_guard(tree) and _has_package_import(tree):
                selected.append(path)
    return tuple(selected)


def test_every_direct_package_entrypoint_has_nonshadowing_root_preamble() -> None:
    entrypoints = _direct_package_entrypoints()
    assert {path.relative_to(ROOT).as_posix() for path in entrypoints} == {
        "src/ember/governance/scripts/ember_admission/produce_candidate.py",
        "src/ember/infrastructure/tools/corpus_connectors/arxiv_fetch.py",
        "src/ember/infrastructure/tools/corpus_connectors/bulk_fetch.py",
        "src/ember/infrastructure/tools/corpus_connectors/github_fetch.py",
        "src/ember/infrastructure/tools/corpus_connectors/hf_fetch.py",
        "src/ember/infrastructure/tools/corpus_connectors/http_fetch.py",
        "src/ember/infrastructure/tools/corpus_connectors/kaggle_fetch.py",
        "src/ember/infrastructure/tools/corpus_connectors/lean_fetch.py",
        "src/ember/infrastructure/tools/corpus_connectors/mint_connector_license_sidecar.py",
        "src/ember/infrastructure/tools/corpus_connectors/openreview_fetch.py",
        "src/ember/infrastructure/tools/corpus_connectors/pdf_tree_to_utf8.py",
        "src/ember/infrastructure/tools/corpus_connectors/regen_bloated_manifest.py",
    }
    preamble_paths = {
        path
        for family_root in FAMILY_ROOTS
        for path in family_root.glob("*.py")
        if PREAMBLE_APPEND in path.read_text(encoding="utf-8")
    }
    assert preamble_paths == set(entrypoints)
    for path in entrypoints:
        source = path.read_text(encoding="utf-8")
        assert PREAMBLE_APPEND in source, path
        assert "sys.path.insert(0, str(_REPO_ROOT))" not in source, path


@pytest.mark.parametrize("entrypoint", _direct_package_entrypoints(), ids=lambda p: p.name)
def test_direct_package_entrypoint_imports_from_unrelated_cwd(
    entrypoint: Path,
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [sys.executable, "-B", str(entrypoint), "--help"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, (entrypoint, result.stdout, result.stderr)
