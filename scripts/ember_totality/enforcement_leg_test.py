#!/usr/bin/env python3
"""test_enforcement_leg.py — fixture-based unit tests + a fixture-analog negative control
for scripts/ember_totality/enforcement_leg.py (issue #38 Deliverable 2).

No real-checker dependence: every case here uses tiny FIXTURE checker scripts written to
disk under B:/M/ember/scratch/pubgate-enforce/fixtures/<case>/ (never the live tree's
receipts, never check_publication_gate.py / check_energy_law_theory.py, which do not exist
in this working tree — see the builder report for that disclosed conflict).

Run: python -m pytest scripts/ember_totality/test_enforcement_leg.py -v
"""
import json
import os
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enforcement_leg import CheckerSpec, run_enforcement_leg  # noqa: E402

# Environment variable override for fixture sandbox root; default points to external location
# PUBGATE_ENFORCE_FIXTURES_ROOT env var can override. Default: B:/M/ember/scratch/pubgate-enforce/fixtures
SANDBOX_ROOT = Path(os.environ.get("PUBGATE_ENFORCE_FIXTURES_ROOT", "B:/M/ember/scratch/pubgate-enforce/fixtures"))


def _make_checker(case_dir: Path, filename: str, source: str) -> str:
    """Write a fixture checker script under case_dir/scripts/filename; return its
    contract_root-relative path."""
    scripts_dir = case_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / filename).write_text(textwrap.dedent(source), encoding="utf-8")
    return f"scripts/{filename}"


def _case_dir(name: str) -> Path:
    """Fresh per-invocation case dir. Removed and recreated every call so re-running the
    suite (builder, gater, or twice back-to-back) never inherits a prior run's timestamped
    enforcement-leg-*.json receipts — a test that only passes on a virgin tree produces
    divergent results between independent re-runs (gate finding, 2026-07-03)."""
    d = SANDBOX_ROOT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 1. pass / pass-agreement
# ---------------------------------------------------------------------------

def test_pass_pass_agreement():
    case = _case_dir("pass_agreement")
    rel = _make_checker(case, "fixture_pass.py", """
        import sys
        print("OVERALL: GREEN (fixture)")
        sys.exit(0)
    """)
    spec = CheckerSpec(name="fixture_pass", rel_path=rel)
    results = run_enforcement_leg(case, timeout_s=10, checkers=[spec],
                                   receipt_dir=case / "scratch")
    r = results["fixture_pass"]
    assert r["executed"] is True
    assert r["exit_code"] == 0
    assert r["verdict"] == "PASS"
    assert r["verdict_line"] == "OVERALL: GREEN (fixture)"


# ---------------------------------------------------------------------------
# 2. fail-agreement (both exit nonzero and print a RED line)
# ---------------------------------------------------------------------------

def test_fail_agreement():
    case = _case_dir("fail_agreement")
    rel = _make_checker(case, "fixture_fail.py", """
        import sys
        print("OVERALL: RED (fixture)")
        sys.exit(1)
    """)
    spec = CheckerSpec(name="fixture_fail", rel_path=rel)
    results = run_enforcement_leg(case, timeout_s=10, checkers=[spec],
                                   receipt_dir=case / "scratch")
    r = results["fixture_fail"]
    assert r["executed"] is True
    assert r["exit_code"] == 1
    assert r["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# 3. timeout
# ---------------------------------------------------------------------------

def test_timeout():
    case = _case_dir("timeout")
    rel = _make_checker(case, "fixture_timeout.py", """
        import time
        time.sleep(5)
        print("OVERALL: GREEN (fixture)")
    """)
    spec = CheckerSpec(name="fixture_timeout", rel_path=rel)
    results = run_enforcement_leg(case, timeout_s=1.0, checkers=[spec],
                                   receipt_dir=case / "scratch")
    r = results["fixture_timeout"]
    assert r["executed"] is True
    assert r["exit_code"] is None
    assert r["verdict"] == "UNRESOLVABLE"
    assert "timeout" in r["reason"]


# ---------------------------------------------------------------------------
# 4. exit-verdict disagreement — both directions
# ---------------------------------------------------------------------------

def test_disagreement_exit0_but_red_line():
    case = _case_dir("disagree_exit0_red")
    rel = _make_checker(case, "fixture_disagree_a.py", """
        import sys
        print("OVERALL: RED (fixture)")
        sys.exit(0)
    """)
    spec = CheckerSpec(name="fixture_disagree_a", rel_path=rel)
    results = run_enforcement_leg(case, timeout_s=10, checkers=[spec],
                                   receipt_dir=case / "scratch")
    r = results["fixture_disagree_a"]
    assert r["exit_code"] == 0
    assert r["verdict_line"] == "OVERALL: RED (fixture)"
    assert r["verdict"] == "DISAGREEMENT"
    assert "exit_code=0" in r["reason"]


def test_disagreement_nonzero_but_green_line():
    case = _case_dir("disagree_nonzero_green")
    rel = _make_checker(case, "fixture_disagree_b.py", """
        import sys
        print("OVERALL: GREEN (fixture)")
        sys.exit(1)
    """)
    spec = CheckerSpec(name="fixture_disagree_b", rel_path=rel)
    results = run_enforcement_leg(case, timeout_s=10, checkers=[spec],
                                   receipt_dir=case / "scratch")
    r = results["fixture_disagree_b"]
    assert r["exit_code"] == 1
    assert r["verdict_line"] == "OVERALL: GREEN (fixture)"
    assert r["verdict"] == "DISAGREEMENT"


# ---------------------------------------------------------------------------
# 5. missing checker
# ---------------------------------------------------------------------------

def test_missing_checker():
    case = _case_dir("missing_checker")
    spec = CheckerSpec(name="fixture_absent", rel_path="scripts/does_not_exist.py")
    results = run_enforcement_leg(case, timeout_s=10, checkers=[spec],
                                   receipt_dir=case / "scratch")
    r = results["fixture_absent"]
    assert r["executed"] is False
    assert r["verdict"] == "UNRESOLVABLE"
    assert "not found" in r["reason"]


# ---------------------------------------------------------------------------
# 6. unparseable output
# ---------------------------------------------------------------------------

def test_unparseable_output():
    case = _case_dir("unparseable")
    rel = _make_checker(case, "fixture_noise.py", """
        print("nothing resembling a verdict line here")
    """)
    spec = CheckerSpec(name="fixture_noise", rel_path=rel)
    results = run_enforcement_leg(case, timeout_s=10, checkers=[spec],
                                   receipt_dir=case / "scratch")
    r = results["fixture_noise"]
    assert r["executed"] is True
    assert r["exit_code"] == 0
    assert r["verdict"] == "UNRESOLVABLE"
    assert "no line matched" in r["reason"]


# ---------------------------------------------------------------------------
# 7. receipt_path capture
# ---------------------------------------------------------------------------

def test_receipt_path_capture():
    case = _case_dir("receipt_capture")
    rel = _make_checker(case, "fixture_with_receipt.py", """
        import sys
        print("OVERALL: GREEN (fixture)")
        print("receipt: receipts/fixture-20260703T000000Z.json")
        sys.exit(0)
    """)
    spec = CheckerSpec(name="fixture_with_receipt", rel_path=rel)
    results = run_enforcement_leg(case, timeout_s=10, checkers=[spec],
                                   receipt_dir=case / "scratch")
    r = results["fixture_with_receipt"]
    assert r["verdict"] == "PASS"
    assert r["receipt_path"] == "receipts/fixture-20260703T000000Z.json"


# ---------------------------------------------------------------------------
# 8. leg receipt is actually written with the required envelope fields
# ---------------------------------------------------------------------------

def test_leg_receipt_written():
    case = _case_dir("leg_receipt")
    rel = _make_checker(case, "fixture_pass2.py", """
        import sys
        print("OVERALL: GREEN (fixture)")
        sys.exit(0)
    """)
    spec = CheckerSpec(name="fixture_pass2", rel_path=rel)
    receipt_dir = case / "scratch"
    run_enforcement_leg(case, timeout_s=10, checkers=[spec], receipt_dir=receipt_dir)
    files = sorted(receipt_dir.glob("enforcement-leg-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["api_spend_usd"] == 0.0
    assert payload["paid_api_surface_used"] is False
    assert payload["overall_verdict"] == "PASS"
    assert "fixture_pass2" in payload["checkers"]


# ---------------------------------------------------------------------------
# 9. multi-checker overall RED when any one checker is not PASS
# ---------------------------------------------------------------------------

def test_overall_red_when_any_checker_not_pass():
    case = _case_dir("mixed_overall")
    rel_ok = _make_checker(case, "fixture_ok.py", """
        import sys
        print("OVERALL: GREEN (fixture)")
        sys.exit(0)
    """)
    rel_bad = _make_checker(case, "fixture_bad.py", """
        import sys
        print("OVERALL: RED (fixture)")
        sys.exit(1)
    """)
    specs = [CheckerSpec(name="ok", rel_path=rel_ok), CheckerSpec(name="bad", rel_path=rel_bad)]
    receipt_dir = case / "scratch"
    run_enforcement_leg(case, timeout_s=10, checkers=specs, receipt_dir=receipt_dir)
    files = sorted(receipt_dir.glob("enforcement-leg-*.json"))
    payload = json.loads(files[-1].read_text(encoding="utf-8"))
    assert payload["overall_verdict"] == "RED"
    assert payload["checkers"]["ok"]["verdict"] == "PASS"
    assert payload["checkers"]["bad"]["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# 10. Negative control — FIXTURE ANALOG of "sandbox COPY of the contract tree with one
#     publication-gate conjunct's input deliberately broken must yield RED through the leg."
#
#     NOT the real negative control the issue specifies: check_publication_gate.py does not
#     exist anywhere in this working tree (B:/M/ember), only in a separate lane's tree
#     (B:/M/ember-goalforge) this builder was not authorized to write into or vendor from.
#     This fixture checker mimics check_publication_gate.py's REPO_ROOT convention
#     (Path(__file__).resolve().parent.parent) and its pass/fail contract shape 1:1, so it
#     demonstrates the SAME mechanism (broken conjunct input -> RED through the leg) without
#     claiming to be the real checker. See the builder report for the disclosed gap.
# ---------------------------------------------------------------------------

def _write_conjunct_checker(sandbox: Path) -> str:
    scripts_dir = sandbox / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "fixture_conjunct_checker.py").write_text(textwrap.dedent("""
        import sys
        from pathlib import Path
        REPO_ROOT = Path(__file__).resolve().parent.parent
        required = REPO_ROOT / "paper" / "claims-evidence-map.md"
        ok = required.is_file() and required.read_text(encoding="utf-8").strip() != ""
        if ok:
            print("OVERALL: GREEN (fixture-conjunct, input present)")
            sys.exit(0)
        else:
            print("OVERALL: RED (fixture-conjunct, input missing/empty)")
            sys.exit(1)
    """), encoding="utf-8")
    return "scripts/fixture_conjunct_checker.py"


def test_negative_control_sandbox_broken_conjunct_input():
    sandbox = _case_dir("negative_control_sandbox")
    rel = _write_conjunct_checker(sandbox)
    paper_dir = sandbox / "paper"
    paper_dir.mkdir(parents=True, exist_ok=True)
    map_path = paper_dir / "claims-evidence-map.md"
    map_path.write_text("| 1 | claim | PROVEN | receipts/x.json | none |\n", encoding="utf-8")

    spec = CheckerSpec(name="fixture_conjunct", rel_path=rel)
    receipt_dir = sandbox / "scratch"

    # (a) clean input -> PASS through the leg
    results_ok = run_enforcement_leg(sandbox, timeout_s=10, checkers=[spec],
                                      receipt_dir=receipt_dir)
    assert results_ok["fixture_conjunct"]["verdict"] == "PASS"

    # (b) deliberately break the conjunct's input (empty the required file) -> RED through
    #     the leg, same mechanism the real check_publication_gate.py conjuncts use
    map_path.write_text("", encoding="utf-8")
    results_broken = run_enforcement_leg(sandbox, timeout_s=10, checkers=[spec],
                                          receipt_dir=receipt_dir)
    r = results_broken["fixture_conjunct"]
    assert r["exit_code"] == 1
    assert r["verdict"] == "FAIL"

    files = sorted(receipt_dir.glob("enforcement-leg-*.json"))
    payload = json.loads(files[-1].read_text(encoding="utf-8"))
    assert payload["overall_verdict"] == "RED"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
