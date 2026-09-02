#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_run_controls_receipt_test.py -- TDD tests for the PR955 round-2 repair:
run_controls.py (the canonical chk_controls driver) must itself execute the
gh #715 C-MANIFEST/C-TALLY denominator regression (reviewer defect P1), with
structured missing_condition_ids (P2, no substring parsing), and a
transactional fail-closed --receipt-out finalization (P1-second): chain
verification failure OR final-write failure => nonzero, no "receipt written"
line, no final receipt file surviving on disk.

Run:
  PYTHONIOENCODING=utf-8 python \\
    src/ember/governance/scripts/ember_totality/chk_controls/test_run_controls_receipt_test.py
  or: python -m pytest src/ember/governance/scripts/ember_totality/chk_controls/test_run_controls_receipt_test.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_CONTROLS_PATH = os.path.join(HERE, "run_controls.py")

failures: list[str] = []


def check(label: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        failures.append(label)


def _load_run_controls():
    """Fresh import of run_controls.py each call (module-level RESULTS is a
    mutable global the real driver accumulates into across a single main()
    run -- tests must not share that state)."""
    spec = importlib.util.spec_from_file_location("run_controls_under_test", RUN_CONTROLS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- (1) intact production fixture wired through the canonical driver's own
#         record()/RESULTS bookkeeping -> GREEN, empty structured missing ids ---

def test_issue715_intact_wired_into_driver_green():
    rc = _load_run_controls()
    rc.RESULTS = []
    pos_root = rc.build_issue715_pos()
    ok = rc.record(
        "23 ISSUE#715 C-MANIFEST/C-TALLY denominator (production-shaped)",
        "POS unmodified production docs/spec+completeness -> GREEN, no missing ids",
        "test_c_manifest.py", pos_root, "GREEN", expected_missing_ids=[],
    )
    check("intact production fixture: driver's own record() call reports ok=True", ok)
    check("intact production fixture: row carries details.missing_condition_ids == []",
          rc.RESULTS[-1]["details"]["missing_condition_ids"] == [])


# --- (2) missing C-MANIFEST row -> RED, structured missing id == ['C-MANIFEST'] ---

def test_issue715_missing_c_manifest_wired_red():
    rc = _load_run_controls()
    rc.RESULTS = []
    neg_root = rc.build_issue715_neg("C-MANIFEST")
    ok = rc.record(
        "23 ISSUE#715 C-MANIFEST/C-TALLY denominator (production-shaped)",
        "NEG production manifest with C-MANIFEST row deleted -> RED naming only C-MANIFEST",
        "test_c_manifest.py", neg_root, "RED", expected_missing_ids=["C-MANIFEST"],
    )
    check("missing C-MANIFEST: driver's own record() call reports ok=True", ok)
    check("missing C-MANIFEST: structured details == ['C-MANIFEST']",
          rc.RESULTS[-1]["details"]["missing_condition_ids"] == ["C-MANIFEST"])


# --- (3) missing C-TALLY row -> RED, structured missing id == ['C-TALLY'] ---

def test_issue715_missing_c_tally_wired_red():
    rc = _load_run_controls()
    rc.RESULTS = []
    neg_root = rc.build_issue715_neg("C-TALLY")
    ok = rc.record(
        "23 ISSUE#715 C-MANIFEST/C-TALLY denominator (production-shaped)",
        "NEG production manifest with C-TALLY row deleted -> RED naming only C-TALLY",
        "test_c_manifest.py", neg_root, "RED", expected_missing_ids=["C-TALLY"],
    )
    check("missing C-TALLY: driver's own record() call reports ok=True", ok)
    check("missing C-TALLY: structured details == ['C-TALLY']",
          rc.RESULTS[-1]["details"]["missing_condition_ids"] == ["C-TALLY"])


# --- (4) a mismatched expectation is caught (proves record() actually checks
#         the structured ids, not just the status token) ---

def test_issue715_wrong_expected_missing_ids_fails_the_row():
    rc = _load_run_controls()
    rc.RESULTS = []
    neg_root = rc.build_issue715_neg("C-MANIFEST")
    ok = rc.record(
        "23 ISSUE#715 C-MANIFEST/C-TALLY denominator (production-shaped)",
        "NEG production manifest with C-MANIFEST row deleted",
        "test_c_manifest.py", neg_root, "RED", expected_missing_ids=["C-TALLY"],
    )
    check("wrong expected missing ids: record() reports ok=False (status matched but ids did not)",
          ok is False)


# --- (5) hermetic --receipt-out finalization: intact pass writes + chain-verifies ---

def test_finalize_receipt_writes_and_prints_on_clean_pass():
    rc = _load_run_controls()
    with tempfile.TemporaryDirectory() as tmp:
        receipt_dir = os.path.join(tmp, "receipts")
        results = [
            {"hardening": "x", "control": "y", "probe": "p", "expected": "GREEN",
             "actual": "GREEN", "ok": True, "line": "GREEN ok", "stderr": "",
             "details": {"missing_condition_ids": []}},
        ]
        ok = rc._finalize_receipt(receipt_dir, results, controls_ok=True)
        check("clean pass: _finalize_receipt returns True", ok is True)
        written = [f for f in os.listdir(receipt_dir) if f.startswith("chk-controls-")]
        check("clean pass: exactly one receipt file written", len(written) == 1)
        if written:
            with open(os.path.join(receipt_dir, written[0]), encoding="utf-8") as fh:
                receipt = json.load(fh)
            check("clean pass: receipt carries the structured rows verbatim",
                  receipt["rows"][0]["details"]["missing_condition_ids"] == [])
            check("clean pass: receipt prev_totality_receipt_sha256 is the 0*64 epoch value (first receipt)",
                  receipt["prev_totality_receipt_sha256"] == "0" * 64)


# --- (6) unwritable receipt destination -> fails closed, no file survives ---

def test_finalize_receipt_unwritable_destination_fails_closed():
    rc = _load_run_controls()
    with tempfile.TemporaryDirectory() as tmp:
        blocked_path = os.path.join(tmp, "blocked")
        # Plant a plain FILE at the exact path the driver will try to
        # os.makedirs() as a directory -- a real "destination unwritable as
        # a receipts directory" shape, portable across OSes.
        with open(blocked_path, "w", encoding="utf-8") as fh:
            fh.write("not a directory")

        results = [{"hardening": "x", "control": "y", "probe": "p", "expected": "GREEN",
                    "actual": "GREEN", "ok": True, "line": "GREEN ok", "stderr": "",
                    "details": {"missing_condition_ids": []}}]
        ok = rc._finalize_receipt(blocked_path, results, controls_ok=True)
        check("unwritable destination: _finalize_receipt returns False", ok is False)
        check("unwritable destination: the blocked path is still a plain file, never a receipt",
              os.path.isfile(blocked_path) and not os.path.isdir(blocked_path))


# --- (7) seeded broken chain -> fails closed, new receipt never survives ---

def test_finalize_receipt_seeded_broken_chain_fails_closed():
    rc = _load_run_controls()
    with tempfile.TemporaryDirectory() as tmp:
        receipt_dir = os.path.join(tmp, "receipts")
        os.makedirs(receipt_dir)
        # Seed a corrupt "first" receipt: a real chk-controls-*.json whose
        # prev_totality_receipt_sha256 is neither 0*64 nor any real
        # predecessor -- an already-broken chain before this run starts.
        corrupt_name = "chk-controls-20260101T000000Z.json"
        with open(os.path.join(receipt_dir, corrupt_name), "w", encoding="utf-8") as fh:
            json.dump({"schema": "chk-controls/v1", "ts": "20260101T000000Z",
                       "rows": [], "prev_totality_receipt_sha256": "f" * 64}, fh)

        results = [{"hardening": "x", "control": "y", "probe": "p", "expected": "GREEN",
                    "actual": "GREEN", "ok": True, "line": "GREEN ok", "stderr": "",
                    "details": {"missing_condition_ids": []}}]
        ok = rc._finalize_receipt(receipt_dir, results, controls_ok=True)
        check("seeded broken chain: _finalize_receipt returns False", ok is False)
        remaining = sorted(os.listdir(receipt_dir))
        check(f"seeded broken chain: only the pre-seeded corrupt receipt remains, "
              f"no new receipt survives (got {remaining!r})",
              remaining == [corrupt_name])


def main() -> int:
    test_issue715_intact_wired_into_driver_green()
    test_issue715_missing_c_manifest_wired_red()
    test_issue715_missing_c_tally_wired_red()
    test_issue715_wrong_expected_missing_ids_fails_the_row()
    test_finalize_receipt_writes_and_prints_on_clean_pass()
    test_finalize_receipt_unwritable_destination_fails_closed()
    test_finalize_receipt_seeded_broken_chain_fails_closed()
    print()
    if failures:
        print(f"FAILED {len(failures)}: {failures}")
        return 1
    print("ALL CASES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
