# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import hashlib
import json


PATCHED_SCRIPTS = Path(
    os.environ.get(
        "EMBER_ISSUE1451_PATCHED_SCRIPTS",
        Path(__file__).resolve().parents[1],
    )
)
REPO_ROOT = Path(
    os.environ.get("EMBER_ISSUE1451_REPO_ROOT", Path(__file__).resolve().parents[2])
)

LIVE_DIRECT_IMPORTERS = (
    "c04_harness",
    "cbase_grow_live",
    "cbase_grow_rung2_stabilize",
    "ember_ceff_closure_confirmation",
    "ember_ceff_composition_ab",
    "exp711_intervals",
    "w1_baseline_replay_closure",
    "w1_fullstate_resume_verify",
)

HISTORICAL_DIRECT_IMPORTERS = (
    "cbase_grow_rung",
    "ember_cbase_mixture",
    "train_multimodal_v0",
)

TEST_OR_HARNESS_DIRECT_IMPORTERS = (
    "test_580_optimizer_id_helper.py",
)

OTHER_LIVE_DIRECT_IMPORTERS = (
    "p1_envelope_sweep.py",
    "p5_ratio_audit/run_p5_audit.py",
    "screen792_bf16_momentum.py",
    "w1_collapse_control_run.py",
)

EXPECTED_DIRECT_IMPORTERS = {
    *(f"{module}.py" for module in LIVE_DIRECT_IMPORTERS),
    *(f"{module}.py" for module in HISTORICAL_DIRECT_IMPORTERS),
    *TEST_OR_HARNESS_DIRECT_IMPORTERS,
    *OTHER_LIVE_DIRECT_IMPORTERS,
}

IMPORTABLE_DIRECT_MODULES = (
    *LIVE_DIRECT_IMPORTERS,
    *(Path(path).with_suffix("").as_posix().replace("/", ".") for path in OTHER_LIVE_DIRECT_IMPORTERS),
    *(Path(path).stem for path in TEST_OR_HARNESS_DIRECT_IMPORTERS),
)

DIRECT_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+timeshare_pretrain\s+import\b|import\s+timeshare_pretrain\b)",
    re.MULTILINE,
)


def _run(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        (str(PATCHED_SCRIPTS), str(REPO_ROOT / "scripts"))
    )
    return subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def _timeshare_import_scope(source: str) -> tuple[bool, int]:
    tree = ast.parse(source)
    module_scope = False
    nested_count = 0

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope_depth = 0

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.scope_depth += 1
            self.generic_visit(node)
            self.scope_depth -= 1

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.scope_depth += 1
            self.generic_visit(node)
            self.scope_depth -= 1

        def _record(self) -> None:
            nonlocal module_scope, nested_count
            if self.scope_depth:
                nested_count += 1
            else:
                module_scope = True

        def visit_Import(self, node: ast.Import) -> None:
            if any(alias.name == "timeshare_pretrain" for alias in node.names):
                self._record()

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module == "timeshare_pretrain":
                self._record()

    Visitor().visit(tree)
    return module_scope, nested_count


def test_timeshare_module_and_live_consumers_are_importable() -> None:
    assert len(IMPORTABLE_DIRECT_MODULES) == 13
    for module in ("timeshare_pretrain", *IMPORTABLE_DIRECT_MODULES):
        result = _run(
            f"import timeshare_pretrain; import {module}; print('IMPORTED:{module}')"
        )
        assert result.returncode == 0, (
            module,
            result.stdout,
            result.stderr,
        )
        assert f"IMPORTED:{module}" in result.stdout


def test_direct_timeshare_execution_remains_historical_only() -> None:
    result = subprocess.run(
        [sys.executable, "-B", str(PATCHED_SCRIPTS / "timeshare_pretrain.py")],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode != 0
    assert "historical_only: the sub-3B cbase trainer is execution-denied" in (
        result.stdout + result.stderr
    )


def test_historical_importers_own_their_import_denial() -> None:
    for module in HISTORICAL_DIRECT_IMPORTERS:
        source = (REPO_ROOT / "scripts" / f"{module}.py").read_text(encoding="utf-8")
        assert "# EMBER_ARTIFACT_CLASS=historical_only" in source
        result = _run(f"import {module}")
        assert result.returncode != 0
        assert "historical_only:" in result.stdout + result.stderr


def test_execution_only_manifest_binds_source_and_historical_importers() -> None:
    manifest = json.loads(
        (
            REPO_ROOT
            / "docs/ember-restart/timeshare-importer-classification-1451-v1.json"
        ).read_text(encoding="utf-8")
    )
    source = PATCHED_SCRIPTS / "timeshare_pretrain.py"
    assert manifest["schema"] == "ember-timeshare-importer-classification-v1"
    assert manifest["import_denial"] == "execution_only"
    assert manifest["execution_boundary"] == {
        "helper": "_historical_only_refusal",
        "main": "main",
        "entrypoint": "__main__",
    }
    assert manifest["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert {Path(row["path"]).stem for row in manifest["importers"]} == set(
        HISTORICAL_DIRECT_IMPORTERS
    )
    assert {row["classification"] for row in manifest["importers"]} == {
        "historical_only"
    }
    assert {row["import_outcome"] for row in manifest["importers"]} == {
        "execution_denied_by_own_guard"
    }
    for row in manifest["importers"]:
        importer = REPO_ROOT / row["path"]
        source_text = importer.read_text(encoding="utf-8")
        module_scope, nested_count = _timeshare_import_scope(source_text)
        assert row["sha256"] == hashlib.sha256(importer.read_bytes()).hexdigest()
        assert row["module_scope"] is module_scope
        assert row["nested_import_count"] == nested_count


def test_every_ember02_direct_importer_has_an_explicit_classification() -> None:
    scripts = REPO_ROOT / "scripts"
    actual = {
        path.relative_to(scripts).as_posix()
        for path in scripts.rglob("*.py")
        if "goal_id: EMBER-02" in path.read_text(encoding="utf-8")
        and DIRECT_IMPORT_RE.search(path.read_text(encoding="utf-8"))
    }
    assert actual == EXPECTED_DIRECT_IMPORTERS
