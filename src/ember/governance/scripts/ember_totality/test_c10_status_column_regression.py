#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression test for test_c10.py's per-row status-cell detection.

test_c10.py's debt-ledger tables carry a permanent taxonomy column ("Class":
ACTIVE-BLOCKER / ACTIVE-NEXT / TRIGGER-GATED, which never changes once a row
is written) to the LEFT of the live "Status" column. Both columns use the
same recognizable-status vocabulary. The probe's own comment says "the
status is the LAST cell in these tables", but the pre-fix scan walked cells
left-to-right and stopped at the FIRST match -- which is always the Class
cell, never the Status cell, for exactly the rows this file exists to check.
That meant a row could never be disposed (DONE:/KILLED:/ARCHIVAL:<receipt>)
while its Class cell used recognized vocabulary -- i.e. it could never be
disposed at all, since Class is set once at row creation and is exactly the
kind of token (ACTIVE-BLOCKER etc.) the scan matches on.

This drives the real script as a subprocess against a synthetic
docs/domains/governance/ledgers/ember-debt-ledger.md, matching test_c_invariant.py's EMBER_TOTALITY_ROOT
override convention, so the fix is proven against the actual executable, not
a reimplementation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
PROBE = REPO_ROOT / "scripts" / "ember_totality" / "test_c10.py"


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(PROBE)],
        cwd=str(root),
        env={"EMBER_TOTALITY_ROOT": str(root), **_minimal_env()},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _minimal_env() -> dict:
    import os

    return {k: v for k, v in os.environ.items() if k != "EMBER_TOTALITY_ROOT"}


def _write_ledger(root: Path, table_body: str) -> None:
    docs = root / "docs" / "ledgers"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "ember-debt-ledger.md").write_text(
        "# Ember Technical And Cognitive Debt Ledger\n\n"
        "## Active Rows\n\n"
        "| ID | Class | Debt | Why It Matters | Required Receipt | Status |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"{table_body}\n",
        encoding="utf-8",
    )


def test_disposed_row_with_recognized_class_cell_is_not_offending(
    tmp_path: Path,
) -> None:
    """A row whose Class column carries ACTIVE-BLOCKER (fixed taxonomy, never
    edited) but whose Status column carries a real ARCHIVAL:<receipt>
    disposition must clear -- the Status column, not the Class column, is
    the live field."""
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    (receipts_dir / "fake-archival.json").write_text("{}\n", encoding="utf-8")

    _write_ledger(
        tmp_path,
        "| DEBT-TEST | ACTIVE-BLOCKER | synthetic row | synthetic | synthetic | "
        "ARCHIVAL: receipts/fake-archival.json |",
    )

    result = _run(tmp_path)
    assert result.returncode == 0
    assert result.stdout.startswith("GREEN"), result.stdout


def test_genuinely_open_row_still_reports_red(tmp_path: Path) -> None:
    """Sanity control: a row that is genuinely still open (Status column
    literally OPEN) must still be caught -- the fix must not make the probe
    blind to real unresolved rows."""
    _write_ledger(
        tmp_path,
        "| DEBT-TEST | ACTIVE-BLOCKER | synthetic row | synthetic | synthetic | OPEN |",
    )

    result = _run(tmp_path)
    assert result.returncode == 0
    assert result.stdout.startswith("RED"), result.stdout
    assert "DEBT-TEST" in result.stdout


def test_disposed_row_without_receipt_token_still_reports_red(
    tmp_path: Path,
) -> None:
    """A disposed row with an empty receipt token must still fail --
    disposition without a named receipt is a distinct, still-caught
    violation, not silently accepted by the reverse-scan fix."""
    _write_ledger(
        tmp_path,
        "| DEBT-TEST | ACTIVE-BLOCKER | synthetic row | synthetic | synthetic | ARCHIVAL: |",
    )

    result = _run(tmp_path)
    assert result.returncode == 0
    assert result.stdout.startswith("RED"), result.stdout
    assert "WITHOUT a named receipt token" in result.stdout


if __name__ == "__main__":
    raise SystemExit(
        subprocess.call(
            [sys.executable, "-B", "-m", "pytest", "-q", __file__]
        )
    )
