#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression coverage for issue #586's current-master annex refresh.
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOTALITY = ROOT / "scripts" / "ember_totality"


def _load_scanner():
    os.environ["EMBER_TOTALITY_ROOT"] = str(ROOT)
    cneg_spec = importlib.util.spec_from_file_location(
        "test_c_neg1_round4_current", TOTALITY / "test_c_neg1.py"
    )
    cneg = importlib.util.module_from_spec(cneg_spec)
    sys.modules["test_c_neg1"] = cneg
    cneg_spec.loader.exec_module(cneg)

    scanner_spec = importlib.util.spec_from_file_location(
        "spend_annex_round4_current", TOTALITY / "spend_annex_scan.py"
    )
    scanner = importlib.util.module_from_spec(scanner_spec)
    scanner_spec.loader.exec_module(scanner)
    return scanner


def test_current_receipt_paths_resolve_only_to_their_real_writers():
    scanner = _load_scanner()
    expected = {
        "receipts/ember-c-scale/land210j-public-revalidation-20260729T135005Z.json":
            "scripts/land210j_public_revalidation.py",
        "receipts/ember-cli/issue-1043-text-wrap/capture-receipt.json":
            "tools/ember-cli/src/build-tools/capture-text-wrap-1043.ts",
        "receipts/issue-457-current-acceptance-20260730.json":
            "scripts/issue457_acceptance.py",
    }
    for receipt_path, writer_path in expected.items():
        resolved = scanner._resolve_via_convention(receipt_path)
        assert resolved is not None, receipt_path
        assert Path(resolved).resolve() == (ROOT / writer_path).resolve()

    assert scanner._resolve_via_convention(
        "receipts/unrelated/capture-receipt.json"
    ) is None


def test_current_hand_authored_receipts_have_exact_path_evidence():
    scanner = _load_scanner()
    paths = [
        "receipts/ember-c-scale/land210g-experiment-runners-receipt.json",
        "receipts/ember-c-scale/land210h-ops-tools-receipt.json",
        "receipts/ember-c-scale/land210i-harness-entry-receipt.json",
        "receipts/ember-c-scale/land210j-family3-stragglers-receipt.json",
        "receipts/ember-c-scale/land210k-e2b-pair-receipt.json",
        "receipts/issue-580-pr-b-retro-audit-20260730.json",
    ]
    for receipt_path in paths:
        with open(ROOT / receipt_path, "r", encoding="utf-8") as handle:
            receipt = json.load(handle)
        evidence = scanner._check_generator_absent_historical(receipt_path, receipt)
        assert evidence is not None, receipt_path
        subtype, note = evidence
        assert subtype == "manually_authored", receipt_path
        assert receipt_path in note, receipt_path


def test_generated_annex_is_path_free_and_authority_bound():
    scanner = _load_scanner()
    result = scanner.main(out_path=None)
    assert result["goal_id"] == "EMBER-02"
    assert result["workstream_id"] == "EMBER-02A"
    assert result["next_executed_outcome"] == (
        "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
    )
    assert result["ticket"] == "ISSUE-586-SPEND-ANNEX-ROUND4"
    assert result["invariant_sha256"] == (
        "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
    )
    assert result["sha_convention"] == (
        "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
    )
    assert result["ts"].endswith("Z")
    assert result["root_id"] == "repository-root"
    assert "root" not in result


def test_emitted_annex_uses_lf_bytes_on_windows():
    scanner = _load_scanner()
    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "annex.json"
        scanner._emit({"verdict": "PASS", "value": 1}, str(output))
        emitted = output.read_bytes()
    assert b"\r\n" not in emitted
    assert emitted.endswith(b"\n")


if __name__ == "__main__":
    test_current_receipt_paths_resolve_only_to_their_real_writers()
    test_current_hand_authored_receipts_have_exact_path_evidence()
    test_generated_annex_is_path_free_and_authority_bound()
    test_emitted_annex_uses_lf_bytes_on_windows()
    print("PASS spend-annex issue #586 current-receipt regressions")
