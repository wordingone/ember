from __future__ import annotations

# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import hashlib
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(os.environ.get("EMBER_ISSUE1267_ROOT", Path(__file__).parents[2]))
DISPOSITION = Path(
    os.environ.get(
        "EMBER_ISSUE1267_DISPOSITION",
        ROOT / "docs/domains/governance/spec/c4-c5-frozen-receipt-disposition-v1.md",
    )
)
FROZEN = ROOT / (
    "receipts/ember-resident-training-gate/"
    "resident-training-gate-20260704T065507Z-intree-issue70-redacted-edition.json"
)
EXPECTED_FROZEN_SHA256 = (
    "21841a3eae9992470b7c44b7ed1bee84a2998bb51159b19286bb32c40c2727f7"
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_disposition_is_closed_zero_credit_and_exhaustive() -> None:
    text = _text(DISPOSITION)
    assert "does **not** attach an overlay" in text
    assert "C4 and C5 remain RED" in text
    assert "Only a genuinely fresh governed resident-training-gate event" in text
    assert "zero-credit disposition" in text
    assert "clean in-tree byte match | 3" in text
    assert "same-name content mismatch | 3" in text
    assert "private-split artifact absent from the public tree | 4" in text
    assert "mutable debt-ledger citation | 1" in text
    assert "The 11 rows above exhaust" in text


def test_frozen_receipt_identity_is_unchanged() -> None:
    assert hashlib.sha256(FROZEN.read_bytes()).hexdigest() == EXPECTED_FROZEN_SHA256


def test_c4_c5_have_no_supplemental_merge_authority() -> None:
    for name in ("test_c4.py", "test_c5.py"):
        text = _text(ROOT / "scripts/ember_totality" / name).lower()
        for forbidden in ("issue1267", "receipt-errata", "receipt-supersession", "overlay"):
            assert forbidden not in text
        assert "check_path_sha_pairs" in text


def test_canonical_board_language_keeps_artifact_reachability_red() -> None:
    evaluation = _text(ROOT / "docs/domains/governance/anatomy/06_EVALUATION_AND_BENCHMARKS.md")
    report = _text(ROOT / "docs/domains/governance/anatomy/15_TECHNICAL_REPORT.md")
    evaluation_normalized = " ".join(evaluation.split())
    report_normalized = " ".join(report.split())
    assert "`C4`/`C5` RED" in evaluation_normalized
    assert "ARTIFACT REACHABILITY failed" in evaluation_normalized
    assert "`C4`/`C5` RED" in report_normalized
    assert "harness-interface reachability" in report_normalized


def test_historical_receipt_remains_artifact_reachability_red() -> None:
    env = os.environ.copy()
    env["EMBER_TOTALITY_ROOT"] = str(ROOT)
    for name in ("test_c4.py", "test_c5.py"):
        proc = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/ember_totality" / name)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        output = (proc.stdout + proc.stderr).strip()
        assert proc.returncode == 0, output
        assert output.startswith("RED "), output
        assert "ARTIFACT REACHABILITY" in output, output
