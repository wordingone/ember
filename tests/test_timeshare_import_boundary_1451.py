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


def _direct_goal_importers() -> list[Path]:
    rows: list[Path] = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        if path == TIMESHARE:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        direct = any(
            (isinstance(node, ast.Import) and any(alias.name == "timeshare_pretrain" for alias in node.names))
            or (isinstance(node, ast.ImportFrom) and node.module == "timeshare_pretrain")
            for node in ast.walk(tree)
        )
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
        assert row["classification"] in {"historical_only", "live_surface"}
        assert row["classification"] == "historical_only"
        assert row["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:20])
        assert "EMBER_ARTIFACT_CLASS=historical_only" in header
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        own_guard = any(
            isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and isinstance(node.exc.func, ast.Name)
            and node.exc.func.id == "SystemExit"
            for node in tree.body
        )
        expected = "execution_denied_by_own_guard" if own_guard else "importable"
        assert row["import_outcome"] == expected
