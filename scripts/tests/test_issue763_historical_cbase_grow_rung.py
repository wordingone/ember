# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression for issue #763's retired sub-3B growth-rung consumer."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "cbase_grow_rung.py"
GOVERNOR = ROOT / "src" / "ember" / "governance" / "scripts" / "governor.py"
REFUSAL = (
    "historical_only: the sub-3B cbase growth-rung consumer and every "
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


def test_historical_growth_rung_cli_cannot_run_selftest() -> None:
    result = _run(str(SCRIPT), "--selftest")
    assert result.returncode != 0
    assert REFUSAL in result.stdout + result.stderr


def test_historical_growth_rung_cannot_be_imported() -> None:
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(SCRIPT.parent)!r}); "
        "import cbase_grow_rung"
    )
    result = _run("-c", code)
    assert result.returncode != 0
    assert REFUSAL in result.stdout + result.stderr


def test_historical_growth_rung_has_closed_authority_markers() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.startswith("# EMBER_ARTIFACT_CLASS=historical_only\n")
    assert "# goal_id: EMBER-02" in source
    assert "# workstream_id: EMBER-02A" in source
    assert (
        "# next_executed_outcome: EMBER-02 first sufficiently pretrained "
        "clean-genesis 3B Ember" in source
    )


def test_reusable_commit_governor_primitives_remain_available() -> None:
    spec = importlib.util.spec_from_file_location("issue763_governor", GOVERNOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in (
        "commit_env_limit",
        "estimate_checkpoint_mapped_bytes",
        "commit_margin_preflight",
    ):
        assert callable(getattr(module, name))
