#!/usr/bin/env python3
"""TDD fixture for gh issue #394: cited-but-missing decisive receipts must RED C(-1).

When a spend-annex row cites a receipt path that does not exist on disk,
C(-1) must report RED with that missing path named in the verdict detail,
fail-closed. This prevents deletion-induced GREEN (the class of defect in #394).
"""

import json
import os
import sys
import tempfile
import subprocess
from pathlib import Path


def test_missing_cited_receipt_stays_red():
    """Fixture: annex cites a receipt; receipt is deleted from disk;
    C(-1) must stay RED and name the missing path."""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create minimal repo structure
        repo_root = tmpdir / "repo"
        receipts_dir = repo_root / "receipts"
        receipts_dir.mkdir(parents=True)

        spend_annex_dir = receipts_dir / "spend-annex"
        spend_annex_dir.mkdir(parents=True)

        scripts_dir = repo_root / "scripts" / "ember_totality"
        scripts_dir.mkdir(parents=True)

        # Create a decisive receipt with zero-cost declaration
        receipt_file = receipts_dir / "decisive-clean-20260707T120000Z.json"
        receipt_file.write_text(json.dumps({
            "verdict": "PASS",
            "api_spend_usd": 0,
            "paid_api_surface_used": False
        }))

        # Create a SECOND decisive receipt path that we'll cite in annex BUT DELETE
        missing_receipt_path = "receipts/missing-decisive-20260707T120000Z.json"
        missing_receipt_file = receipts_dir / "missing-decisive-20260707T120000Z.json"
        missing_receipt_file.write_text(json.dumps({
            "verdict": "PASS",
            "api_spend_usd": 0,
            "paid_api_surface_used": False
        }))

        # Create spend-annex that cites the missing receipt
        annex_file = spend_annex_dir / "spend-annex-20260707T130000Z.json"
        annex_file.write_text(json.dumps({
            "rows": [
                {
                    "path": missing_receipt_path,
                    "evidence_class": "declared",
                    "sha256": "abc123def456"  # dummy hash for missing file
                }
            ]
        }))

        # NOW delete the missing receipt from disk (simulates the deletion incident)
        missing_receipt_file.unlink()

        # Run the scanner via EMBER_TOTALITY_ROOT env var
        test_script = Path(__file__).parent / "test_c_neg1.py"
        result = subprocess.run(
            [sys.executable, str(test_script)],
            env={**os.environ, "EMBER_TOTALITY_ROOT": str(repo_root)},
            capture_output=True,
            text=True
        )

        output = result.stdout.strip()
        print(f"Scanner output: {output}")

        # MUST be RED, and MUST mention the missing path
        assert output.startswith("RED"), f"Expected RED, got: {output}"
        assert "missing" in output.lower() or missing_receipt_path in output, \
            f"Expected message to mention missing receipt path, got: {output}"

        print("[PASS] Test passed: missing-cited receipt correctly triggers RED")


def test_all_cited_receipts_present_goes_green():
    """Fixture: annex cites receipts that all exist on disk;
    C(-1) goes GREEN per normal behavior."""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create minimal repo structure
        repo_root = tmpdir / "repo"
        receipts_dir = repo_root / "receipts"
        receipts_dir.mkdir(parents=True)

        spend_annex_dir = receipts_dir / "spend-annex"
        spend_annex_dir.mkdir(parents=True)

        # Create a decisive receipt with zero-cost declaration
        receipt_file = receipts_dir / "decisive-clean-20260707T120000Z.json"
        receipt_file.write_text(json.dumps({
            "verdict": "PASS",
            "api_spend_usd": 0,
            "paid_api_surface_used": False
        }))

        # Create spend-annex (even if empty)
        annex_file = spend_annex_dir / "spend-annex-20260707T130000Z.json"
        annex_file.write_text(json.dumps({"rows": []}))

        # Run the scanner
        test_script = Path(__file__).parent / "test_c_neg1.py"
        result = subprocess.run(
            [sys.executable, str(test_script)],
            env={**os.environ, "EMBER_TOTALITY_ROOT": str(repo_root)},
            capture_output=True,
            text=True
        )

        output = result.stdout.strip()
        print(f"Scanner output: {output}")

        # MUST be GREEN since all receipts exist
        assert output.startswith("GREEN"), f"Expected GREEN, got: {output}"

        print("[PASS] Test passed: all-cited-present correctly triggers GREEN")


if __name__ == "__main__":
    print("\n=== Test 1: Missing cited receipt ===")
    test_missing_cited_receipt_stays_red()

    print("\n=== Test 2: All cited receipts present ===")
    test_all_cited_receipts_present_goes_green()

    print("\n[PASS] All tests passed")
