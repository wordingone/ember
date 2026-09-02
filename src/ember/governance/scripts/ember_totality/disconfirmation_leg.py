#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""disconfirmation_leg.py -- board-wired disconfirmation-trigger leg per conditions-v1.md
sec 4.2 (live authority; archived pre-2026-07-06 at goal-archive.md) (gh issue #94 C-DISC,
phase 2; schema frozen by maintainer rulings R1-R7 on the phase-1 dossier).

Thin, reuse-only wrapper -- the same C-ENF/C-MILE pattern (issue #38's enforcement_leg.py,
issue #35's milestone_leg.py), scoped to the new src/ember/governance/scripts/check_disconfirmation_triggers.py.
Imports enforcement_leg's CheckerSpec and _run_one_checker UNMODIFIED -- the dual-source
verdict resolution (subprocess exit code cross-checked against the checker's own printed
verdict line) is not reimplemented here.

Checker's real, discovered verdict-line contract (read directly from
check_disconfirmation_triggers.py's run(), not guessed): on every path the final stdout line is
    hinges=3  fired=<n>  violations=<n>  exit=PASS|FAIL
`sys.exit(run())` returns 0 iff exit_status == "PASS" (no hinge fired-and-unacknowledged), 1
otherwise. Unlike check_milestone_reconciliation.py, this checker has no unhandled-exception
path in normal operation -- a fired hinge with a valid escalation or override object is PASS,
not a special-cased "honestly closed" state (R7: fire history is permanent in the attempts
record, but the CHK returns to GREEN once acknowledged).

Stdlib only (plus the sibling enforcement_leg module). No network. No GPU.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enforcement_leg import CheckerSpec, _run_one_checker  # noqa: E402

# Discovered canonical invocation (read-only source review of
# src/ember/governance/scripts/check_disconfirmation_triggers.py's run(), 2026-07-04): bare invocation, no args; the
# module's own ROOT resolves from os.path.dirname(HERE), so pointing _run_one_checker's
# cwd/contract_root at a sandbox copy containing its own src/ember/governance/scripts/check_disconfirmation_triggers.py
# is fully self-contained.
DISCONFIRMATION_CHECKER = CheckerSpec(
    name="check_disconfirmation_triggers",
    rel_path="src/ember/governance/scripts/check_disconfirmation_triggers.py",
    args=(),
    verdict_regex=r"^hinges=\d+\s+fired=\d+\s+violations=\d+\s+exit=(PASS|FAIL)\b",
    pass_values=("PASS",),
)


def _write_leg_receipt(results: dict, receipt_dir: Path) -> Path:
    receipt_dir = Path(receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    overall = "PASS" if all(r["verdict"] == "PASS" for r in results.values()) else "RED"
    receipt = {
        "ticket": "EMBER-TOTALITY-DISCONFIRMATION-LEG",
        "ts": ts,
        "kind": "gate",
        "chk_name": "run_disconfirmation_leg",
        "spec_ref": "gh issue #94 (C-DISC), phase-1 dossier + maintainer rulings R1-R7",
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "checkers": results,
        "overall_verdict": overall,
    }
    path = receipt_dir / f"disconfirmation-leg-{ts}.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return path


def run_disconfirmation_leg(
    contract_root: Path,
    timeout_s: float = 180,
    *,
    receipt_dir: Optional[Path] = None,
) -> dict:
    """Execute check_disconfirmation_triggers.py as a subprocess against contract_root, resolve
    its dual-source verdict via enforcement_leg's own (reused, unmodified) _run_one_checker,
    write one leg receipt JSON, and return
    {"check_disconfirmation_triggers": {executed, exit_code, verdict_line, verdict, wall_s,
    receipt_path, reason}} -- the same shape run_milestone_leg/run_enforcement_leg return.

    No board wiring here: this function does not read or write ember_totality_spec.py.
    """
    contract_root = Path(contract_root)
    result = _run_one_checker(contract_root, DISCONFIRMATION_CHECKER, timeout_s)
    results = {DISCONFIRMATION_CHECKER.name: result}
    out_dir = Path(receipt_dir) if receipt_dir is not None else (contract_root / "scripts" / "ember_totality" / "receipts-disconfirmation")
    _write_leg_receipt(results, out_dir)
    return results


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Run the board-wired disconfirmation-trigger leg against a contract tree.")
    ap.add_argument("--contract-root", required=True, type=Path)
    ap.add_argument("--timeout-s", type=float, default=180.0)
    ap.add_argument("--receipt-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    results = run_disconfirmation_leg(args.contract_root, args.timeout_s, receipt_dir=args.receipt_dir)
    for name, r in results.items():
        print(f"  [{r['verdict']}] {name}: exit={r['exit_code']} line={r['verdict_line']!r}")
        if r["reason"]:
            print(f"      reason: {r['reason']}")
    overall = "PASS" if all(r["verdict"] == "PASS" for r in results.values()) else "RED"
    print(f"OVERALL: {overall}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
