# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression for issue #768's retired sub-3B mixture assembler."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT = ROOT / "scripts" / "ember_cbase_mixture.py"
REFUSAL = (
    "historical_only: the sub-3B cbase mixture assembler and every "
    "importer are execution-denied"
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_historical_mixture_cli_cannot_run_selftest() -> None:
    result = _run(str(SCRIPT), "--selftest")
    assert result.returncode != 0
    assert REFUSAL in result.stdout + result.stderr


def test_historical_mixture_cannot_be_imported_as_data_authority() -> None:
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(SCRIPT.parent)!r}); "
        "import ember_cbase_mixture"
    )
    result = _run("-c", code)
    assert result.returncode != 0
    assert REFUSAL in result.stdout + result.stderr


def test_historical_mixture_source_has_closed_authority_markers() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "# EMBER_ARTIFACT_CLASS=historical_only" in source
    assert "# goal_id: EMBER-02" in source
    assert "# workstream_id: EMBER-02A" in source
    assert (
        "# next_executed_outcome: EMBER-02 first sufficiently pretrained "
        "clean-genesis 3B Ember" in source
    )
