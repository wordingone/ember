# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production-shaped import-boundary and blast-radius checks for #1451."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TIMESHARE = SCRIPTS / "timeshare_pretrain.py"
MANIFEST = ROOT / "docs" / "ember-restart" / "timeshare-importer-classification-1451-v1.json"


def _is_timeshare_import(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Import)
        and any(alias.name == "timeshare_pretrain" for alias in node.names)
    ) or (
        isinstance(node, ast.ImportFrom)
        and node.module == "timeshare_pretrain"
    )


def _import_scope(path: Path) -> tuple[bool, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_imports = [node for node in tree.body if _is_timeshare_import(node)]
    nested_import_count = sum(
        1 for node in ast.walk(tree)
        if _is_timeshare_import(node) and node not in module_imports
    )
    return bool(module_imports), nested_import_count


def _direct_goal_importers() -> list[Path]:
    rows: list[Path] = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        if path == TIMESHARE:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        direct = any(_is_timeshare_import(node) for node in ast.walk(tree))
        header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:20])
        if direct and "goal_id: EMBER-02" in header:
            rows.append(path)
    return rows


def test_timeshare_import_is_safe_but_script_execution_remains_refused():
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    import_probe = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import sys; sys.path.insert(0, 'scripts'); import timeshare_pretrain as mod; assert callable(mod.main)",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert import_probe.returncode == 0, import_probe.stderr or import_probe.stdout

    execution_probe = subprocess.run(
        [sys.executable, "-B", str(TIMESHARE), "--selftest"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert execution_probe.returncode != 0
    assert "historical_only" in (execution_probe.stdout + execution_probe.stderr)


def test_current_goal_importer_blast_radius_is_closed_and_reproducible():
    importers = _direct_goal_importers()
    assert importers, "expected current EMBER-02 direct importers"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "ember-timeshare-importer-classification-v1"
    assert manifest["import_denial"] == "execution_only"
    assert manifest["source_sha256"] == hashlib.sha256(TIMESHARE.read_bytes()).hexdigest()
    expected = [row["path"] for row in manifest["importers"]]
    actual = [path.relative_to(ROOT).as_posix() for path in importers]
    assert expected == actual
    for row, path in zip(manifest["importers"], importers):
        assert set(row) == {
            "path", "classification", "import_outcome", "sha256",
            "module_scope", "nested_import_count",
        }
        assert row["classification"] in {"historical_only", "live_surface"}
        assert row["classification"] == "historical_only"
        assert row["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:20])
        assert "EMBER_ARTIFACT_CLASS=historical_only" in header
        module_scope, nested_import_count = _import_scope(path)
        assert row["module_scope"] is module_scope
        assert row["nested_import_count"] == nested_import_count
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        probe = subprocess.run(
            [
                sys.executable, "-B", "-c",
                "import importlib.util, sys; from pathlib import Path; "
                "path=sys.argv[1]; sys.path.insert(0, str(Path(path).parent)); "
                "spec=importlib.util.spec_from_file_location('_ember_import_probe', path); "
                "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)",
                str(path),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        if row["import_outcome"] == "importable":
            assert probe.returncode == 0, probe.stderr or probe.stdout
        else:
            assert row["import_outcome"] == "execution_denied_by_own_guard"
            assert probe.returncode != 0
            assert "historical_only" in (probe.stdout + probe.stderr)


def test_historical_refusal_is_bound_to_main_first_statement_and_module_guard():
    tree = ast.parse(TIMESHARE.read_text(encoding="utf-8"), filename=str(TIMESHARE))

    def first_executable(body):
        statements = list(body)
        if (
            statements
            and isinstance(statements[0], ast.Expr)
            and isinstance(statements[0].value, ast.Constant)
            and isinstance(statements[0].value.value, str)
        ):
            statements.pop(0)
        return statements[0] if statements else None

    refusal = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_historical_only_refusal")
    refusal_first = first_executable(refusal.body)
    assert isinstance(refusal_first, ast.Raise)
    assert isinstance(refusal_first.exc, ast.Call)
    assert isinstance(refusal_first.exc.func, ast.Name)
    assert refusal_first.exc.func.id == "SystemExit"

    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    main_first = first_executable(main.body)
    assert isinstance(main_first, ast.Expr)
    assert isinstance(main_first.value, ast.Call)
    assert isinstance(main_first.value.func, ast.Name)
    assert main_first.value.func.id == "_historical_only_refusal"

    module_guard = next(
        node for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
    )
    assert any(
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "main"
        for statement in module_guard.body
    )
