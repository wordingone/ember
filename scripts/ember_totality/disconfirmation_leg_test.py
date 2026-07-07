#!/usr/bin/env python3
"""disconfirmation_leg_test.py -- hermetic regression suite for disconfirmation_leg.py /
check_disconfirmation_triggers.py (gh issue #94 C-DISC, phase 2; maintainer rulings R1-R7).

Every case gets a fresh tempfile.TemporaryDirectory() sandbox (never a shared path) containing
a REAL, unmodified copy of check_disconfirmation_triggers.py (shutil.copyfile) plus minimal-but-
real-shaped fixture docs/receipts -- real code, synthetic-only data, exactly the discipline
milestone_leg_test.py/enforcement_leg_test.py established.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enforcement_leg import _run_one_checker  # noqa: E402
from disconfirmation_leg import (  # noqa: E402
    DISCONFIRMATION_CHECKER,
    run_disconfirmation_leg,
)

REAL_CHECKER_SRC = Path(__file__).resolve().parents[1] / "check_disconfirmation_triggers.py"

H0_PREREG_MD = """# H0 residual collapse: lever ladder pre-registration

| # | Lever | Mechanism | Keep bar (alone) | Kill condition |
|---|---|---|---|---|
| L1 | Production-graph compile revival | x | >=1.10x | x |
| L2 | CUDA-graphs step capture | x | >=1.05x | x |
| L3 | Batch geometry + sequence packing audit | x | x | x |
| L4 | Fused-kernel completion | x | >=1.08x | x |
| L5 | FP8 (sm89) at rung-1 proxy shape | x | >=1.40x | x |
"""

FEASIBILITY_ENVELOPE_MD = """## 4. The collapse stack

| Lever | Factor (source) | Status |
|---|---|---|
| H0 mechanical stack | target >=3.3x; measured **1.85x** | fixture |
"""


def _ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_base_fixture_tree(root: Path):
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_CHECKER_SRC, root / "scripts" / "check_disconfirmation_triggers.py")

    spec_dir = root / "docs" / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "h0-residual-lever-prereg-v1.md").write_text(H0_PREREG_MD, encoding="utf-8")
    (spec_dir / "feasibility-envelope-v1.md").write_text(FEASIBILITY_ENVELOPE_MD, encoding="utf-8")


def _write_growth_attempt(root, ts, verdict, evaluable=True, rung=1):
    d = root / "receipts" / "growth-rung-attempts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"rung{rung}-attempt-{ts}.json"
    p.write_text(json.dumps({
        "receipt_type": "growth_rung_attempt",
        "rung": rung,
        "ts": ts,
        "evaluable": evaluable,
        "verdict": verdict,
    }), encoding="utf-8")
    return p


def _write_b2_attempt(root, ts, bootstrap_pass, evaluable=True, receipt_type="b2_bootstrap_attempt"):
    d = root / "receipts" / "bootstrap-rung"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"b2-attempt-{ts}.json"
    p.write_text(json.dumps({
        "receipt_type": receipt_type,
        "ts": ts,
        "evaluable": evaluable,
        "bootstrap_pass": bootstrap_pass,
    }), encoding="utf-8")
    return p


def _write_escalation(root, hinge, valid=True):
    d = root / "receipts" / "escalation"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"disconfirmation-{hinge.lower()}-{_ts()}.json"
    obj = {
        "hinge": hinge,
        "predicate": "fixture predicate text",
        "firing_receipt_refs": ["fixture/ref.json"],
        "ts": _ts(),
        "git_anchor": "deadbeef",
        "amendment_proposal": "fixture §4.0 amendment proposal text" if valid else "",
    }
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _write_override(root, hinge):
    d = root / "receipts" / "escalation"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"override-{hinge.lower()}-{_ts()}.json"
    p.write_text(json.dumps({"hinge": hinge, "ts": _ts(), "operator_note": "fixture override"}), encoding="utf-8")
    return p


def _write_h0_sidecar(root, statuses):
    p = root / "docs" / "spec" / "h0-lever-status.json"
    p.write_text(json.dumps(statuses), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. Baseline -- no attempts anywhere, all three hinges honestly unmet -> PASS
# ---------------------------------------------------------------------------

def test_baseline_all_hinges_unmet_yields_pass():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)
        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["exit_code"] == 0
        assert r["verdict"] == "PASS", r
        assert r["verdict_line"].startswith("hinges=3  fired=0  violations=0")


# ---------------------------------------------------------------------------
# 2. EARNED_GROWTH fires (2 consecutive NOT_EARNED), escalation object missing -> RED
# ---------------------------------------------------------------------------

def test_earned_growth_fired_escalation_missing_yields_fail():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)
        _write_growth_attempt(root, "20260701T000000Z", "NOT_EARNED", rung=1)
        _write_growth_attempt(root, "20260702T000000Z", "NOT_EARNED", rung=2)

        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["exit_code"] == 1
        assert r["verdict"] == "FAIL", r
        assert "fired=1" in r["verdict_line"] and "violations=1" in r["verdict_line"]


# ---------------------------------------------------------------------------
# 3. Same fired state, valid escalation object present -> PASS (fired != violation)
# ---------------------------------------------------------------------------

def test_earned_growth_fired_with_valid_escalation_yields_pass():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)
        _write_growth_attempt(root, "20260701T000000Z", "NOT_EARNED", rung=1)
        _write_growth_attempt(root, "20260702T000000Z", "NOT_EARNED", rung=2)
        _write_escalation(root, "EARNED_GROWTH", valid=True)

        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["exit_code"] == 0
        assert r["verdict"] == "PASS", r
        assert "fired=1" in r["verdict_line"] and "violations=0" in r["verdict_line"]


# ---------------------------------------------------------------------------
# 4. A trailing EARNED attempt breaks the streak -> unmet -> PASS
# ---------------------------------------------------------------------------

def test_trailing_earned_attempt_breaks_streak_stays_unmet():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)
        _write_growth_attempt(root, "20260701T000000Z", "NOT_EARNED", rung=1)
        _write_growth_attempt(root, "20260702T000000Z", "EARNED", rung=2)

        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["verdict"] == "PASS", r
        assert "fired=0" in r["verdict_line"]


# ---------------------------------------------------------------------------
# 5. Override object present -> PASS even though the fire stays in the record (R7)
# ---------------------------------------------------------------------------

def test_override_returns_pass_fire_stays_on_record():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)
        _write_growth_attempt(root, "20260701T000000Z", "NOT_EARNED", rung=1)
        _write_growth_attempt(root, "20260702T000000Z", "NOT_EARNED", rung=2)
        _write_override(root, "EARNED_GROWTH")

        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["verdict"] == "PASS", r
        assert "fired=1" in r["verdict_line"] and "violations=0" in r["verdict_line"]

        # the underlying evaluation receipt still records trigger_fired=True for the hinge --
        # the override does not erase the fire, only acknowledges it (R7).
        receipts_dir = root / "scripts" / "ember_totality" / "receipts-disconfirmation"
        eval_receipts = sorted(receipts_dir.glob("disconfirmation-eval-*.json"))
        assert eval_receipts, "no disconfirmation-eval receipt written"
        payload = json.loads(eval_receipts[-1].read_text(encoding="utf-8"))
        growth_hinge = next(h for h in payload["hinges"] if h["hinge"] == "EARNED_GROWTH")
        assert growth_hinge["trigger_fired"] is True
        assert growth_hinge["compliant"] is True
        assert growth_hinge["reason"] == "override"


# ---------------------------------------------------------------------------
# 6. R6: a falsifier-selftest receipt (wrong receipt_type) sitting in the SAME directory as
#    real B2 attempts must never count toward the B2_BOOTSTRAP tally, even though 3
#    bootstrap_pass=false rows are physically present -- class exclusion, not directory
#    exclusion.
# ---------------------------------------------------------------------------

def test_falsifier_selftest_receipt_excluded_from_b2_tally():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)
        d = root / "receipts" / "bootstrap-rung"
        d.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            p = d / f"stray-falsifier-{i}.json"
            p.write_text(json.dumps({
                "receipt_type": "bootstrap_falsifier_selftest",
                "ts": f"2026070{i+1}T000000Z",
                "evaluable": True,
                "bootstrap_pass": False,
            }), encoding="utf-8")

        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["verdict"] == "PASS", r
        assert "fired=0" in r["verdict_line"]

        receipts_dir = root / "scripts" / "ember_totality" / "receipts-disconfirmation"
        payload = json.loads(sorted(receipts_dir.glob("disconfirmation-eval-*.json"))[-1].read_text(encoding="utf-8"))
        b2_hinge = next(h for h in payload["hinges"] if h["hinge"] == "B2_BOOTSTRAP")
        assert b2_hinge["attempts_seen"] == 0, b2_hinge


# ---------------------------------------------------------------------------
# 7. R3: an UNEVALUABLE attempt is skipped -- never breaks, never counts -- so 2
#    genuinely-evaluable BOOTSTRAP_FAIL attempts either side of an UNEVALUABLE one still
#    form a continuous trailing streak.
# ---------------------------------------------------------------------------

def test_unevaluable_attempt_is_skipped_not_breaking():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)
        _write_b2_attempt(root, "20260701T000000Z", bootstrap_pass=False, evaluable=True)
        _write_b2_attempt(root, "20260702T000000Z", bootstrap_pass=None, evaluable=False)
        _write_b2_attempt(root, "20260703T000000Z", bootstrap_pass=False, evaluable=True)
        _write_b2_attempt(root, "20260704T000000Z", bootstrap_pass=False, evaluable=True)

        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is True
        # B2_BOOTSTRAP threshold is 3; the trailing evaluable streak (skipping the
        # UNEVALUABLE one) is exactly 3 -> fired, and no escalation/override -> FAIL.
        assert r["verdict"] == "FAIL", r
        payload = json.loads(sorted((root / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("disconfirmation-eval-*.json"))[-1].read_text(encoding="utf-8"))
        b2_hinge = next(h for h in payload["hinges"] if h["hinge"] == "B2_BOOTSTRAP")
        assert b2_hinge["consecutive_fail_streak"] == 3, b2_hinge
        assert b2_hinge["attempts_seen"] == 4  # the UNEVALUABLE one is still counted as "seen"


# ---------------------------------------------------------------------------
# 8a. R2/H0_CEILING: the base fixture's feasibility-envelope already carries a composed
#     multiplier (1.85) under the 3.3x bar, but with no h0-lever-status.json sidecar
#     all_levers_resolved is conservatively False -- H0_CEILING must NOT fire on the
#     multiplier alone. Confirms the AND-gate, not just the multiplier half.
# ---------------------------------------------------------------------------

def test_h0_ceiling_does_not_fire_without_lever_status_sidecar():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)  # composed 1.85x < 3.3x, but no sidecar
        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["verdict"] == "PASS", r
        payload = json.loads(sorted((root / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("disconfirmation-eval-*.json"))[-1].read_text(encoding="utf-8"))
        h0 = next(h for h in payload["hinges"] if h["hinge"] == "H0_CEILING")
        assert h0["all_levers_resolved"] is False
        assert h0["trigger_fired"] is False


# ---------------------------------------------------------------------------
# 8b. R2/H0_CEILING: with the sidecar present and all five levers resolved
#     (KEPT/PARKED/KILLED) AND composed_multiplier < 3.3x, H0_CEILING fires; with a valid
#     escalation object, the CHK is PASS (fired != violation, same as the other two hinges).
# ---------------------------------------------------------------------------

def test_h0_ceiling_fires_with_sidecar_all_resolved_and_escalation_present():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)
        _write_h0_sidecar(root, {"L1": "PARKED", "L2": "KEPT", "L3": "KEPT", "L4": "KILLED", "L5": "PARKED"})
        _write_escalation(root, "H0_CEILING", valid=True)

        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["verdict"] == "PASS", r
        payload = json.loads(sorted((root / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("disconfirmation-eval-*.json"))[-1].read_text(encoding="utf-8"))
        h0 = next(h for h in payload["hinges"] if h["hinge"] == "H0_CEILING")
        assert h0["all_levers_resolved"] is True
        assert h0["trigger_fired"] is True
        assert h0["compliant"] is True
        assert h0["reason"] == "escalated"


# ---------------------------------------------------------------------------
# 8c. R2/H0_CEILING: one lever left unresolved (null) still blocks the AND-gate even with
#     four of five resolved -- partial resolution is not resolution.
# ---------------------------------------------------------------------------

def test_h0_ceiling_one_unresolved_lever_blocks_fire():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)
        _write_h0_sidecar(root, {"L1": "PARKED", "L2": "KEPT", "L3": "KEPT", "L4": "KILLED", "L5": None})

        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["verdict"] == "PASS", r
        payload = json.loads(sorted((root / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("disconfirmation-eval-*.json"))[-1].read_text(encoding="utf-8"))
        h0 = next(h for h in payload["hinges"] if h["hinge"] == "H0_CEILING")
        assert h0["all_levers_resolved"] is False
        assert h0["trigger_fired"] is False


# ---------------------------------------------------------------------------
# 9. Missing checker script -> UNRESOLVABLE, exactly the enforcement_leg-generic contract.
# ---------------------------------------------------------------------------

def test_missing_checker_script_is_unresolvable():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # deliberately do NOT write scripts/check_disconfirmation_triggers.py
        r = _run_one_checker(root, DISCONFIRMATION_CHECKER, timeout_s=30)
        assert r["executed"] is False
        assert r["verdict"] == "UNRESOLVABLE", r


# ---------------------------------------------------------------------------
# 10. run_disconfirmation_leg writes a leg receipt with the disconfirmation ticket.
# ---------------------------------------------------------------------------

def test_leg_receipt_written_with_disconfirmation_ticket():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_base_fixture_tree(root)
        results = run_disconfirmation_leg(root, timeout_s=30, receipt_dir=root / "scratch")
        assert results["check_disconfirmation_triggers"]["verdict"] == "PASS"

        leg_receipts = sorted((root / "scratch").glob("disconfirmation-leg-*.json"))
        assert leg_receipts, "no disconfirmation-leg receipt written"
        payload = json.loads(leg_receipts[-1].read_text(encoding="utf-8"))
        assert payload["ticket"] == "EMBER-TOTALITY-DISCONFIRMATION-LEG"
        assert payload["overall_verdict"] == "PASS"
