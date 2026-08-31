#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""milestone_leg.py -- board-wired milestone/lattice-mirror leg (Class-2 item 2,
docs/audit/class2-unwatched-mandates-recon-20260704.md #2; parent issue #35 DISPATCH 3 of 3;
the recon's own text names this exact CHK build-out as "a separate later dispatch").

Thin, reuse-only wrapper -- EXACTLY the C-ENF pattern (issue #38,
scripts/ember_totality/enforcement_leg.py + test_c_enf.py), scoped to the ONE existing
checker docs/spec/milestones-v1.md's own "Validation hook" section names:
src/ember/governance/scripts/check_milestone_reconciliation.py. Imports enforcement_leg's CheckerSpec and
_run_one_checker UNMODIFIED -- the dual-source verdict resolution (subprocess exit code
cross-checked against the checker's own printed verdict line, never forced to agree
silently) is not reimplemented here.

Checker's real, discovered verdict-line contract (read directly from
src/ember/governance/scripts/check_milestone_reconciliation.py's run(), not guessed): on the non-exception
path the final stdout line is
    mapped=<n>/55  unmapped=<n>  lattice_diff=<n>  floor_contract_gaps=<n>  exit=PASS|FAIL
`sys.exit(run())` returns 0 iff exit_status == "PASS", else 1. A ParseError or any other
unexpected exception prints ONLY a stderr message ("FAIL (parse error): ..." /
"FAIL (unexpected ...): ...") and writes NO stdout line matching the pattern above -- that
path resolves to verdict UNRESOLVABLE through _run_one_checker's own "no line matched"
branch, which is fail-closed by construction (only PASS is ever a pass at the board layer).

DISCLOSED, live finding (not a synthetic hypothetical -- reproduced against today's real
tree the same session this module was authored): running
`python src/ember/governance/scripts/check_milestone_reconciliation.py` against the live goalforge tree RIGHT
NOW returns FAIL ("ember-completeness.md: expected exactly ids C1..C55, got missing=[]
extra=[0]") because docs/contracts/ember-completeness.md carries a C0 row (line 79) whose leading
`| C0 |` cell collides with check_milestone_reconciliation.py's own row-id regex
(_COMPLETENESS_ROW_RE, matching a leading pipe, "C", one or more digits, a pipe) --
that regex captures "C0" as legacy-milestone-id 0 even though the row is a
BOARD-CONDITION reference (C0, the
resident-training-gate condition), not one of the 55 legacy M<n>/C<n> milestone rows the
checker's own docstring says the table enumerates. This looks like a real parsing bug in
the checker (added after its 2026-07-01 PASS receipt, commit 462bbe7), not a genuine
milestone/lattice divergence -- flagged in the builder report, NOT silently fixed here:
fixing check_milestone_reconciliation.py itself is outside this dispatch's frozen scope
("board-wire the EXISTING check_milestone_reconciliation.py", not "fix" it). Wiring this
leg in as specified means the new CHK will read RED against the live tree the moment it is
wired -- an honest reflection of the checker's real current output, not a fabricated
red state.

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
# issue2015 exact-local-import:scripts/ember_totality/enforcement_leg.py
import importlib.util as _ember_e1051383780249b3_importlib
import sys as _ember_e1051383780249b3_sys
from pathlib import Path as _ember_e1051383780249b3_Path
_ember_e1051383780249b3_path = _ember_e1051383780249b3_Path(__file__).resolve().parents[5].joinpath('scripts', 'ember_totality', 'enforcement_leg.py')
if not _ember_e1051383780249b3_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/ember_totality/enforcement_leg.py')
_ember_e1051383780249b3_aliases = ('_ember_issue2015_e1051383780249b3', 'enforcement_leg', 'scripts.ember_totality.enforcement_leg')
_ember_e1051383780249b3_existing = []
for _ember_e1051383780249b3_alias in _ember_e1051383780249b3_aliases:
    _ember_e1051383780249b3_candidate = _ember_e1051383780249b3_sys.modules.get(_ember_e1051383780249b3_alias)
    if _ember_e1051383780249b3_candidate is not None and all(_ember_e1051383780249b3_candidate is not item for item in _ember_e1051383780249b3_existing):
        _ember_e1051383780249b3_existing.append(_ember_e1051383780249b3_candidate)
if len(_ember_e1051383780249b3_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/ember_totality/enforcement_leg.py')
if _ember_e1051383780249b3_existing:
    _ember_e1051383780249b3_module = _ember_e1051383780249b3_existing[0]
    _ember_e1051383780249b3_observed = getattr(_ember_e1051383780249b3_module, '__file__', None)
    if _ember_e1051383780249b3_observed is None or _ember_e1051383780249b3_Path(_ember_e1051383780249b3_observed).resolve() != _ember_e1051383780249b3_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/ember_totality/enforcement_leg.py')
else:
    _ember_e1051383780249b3_spec = _ember_e1051383780249b3_importlib.spec_from_file_location('_ember_issue2015_e1051383780249b3', _ember_e1051383780249b3_path)
    if _ember_e1051383780249b3_spec is None or _ember_e1051383780249b3_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/ember_totality/enforcement_leg.py')
    _ember_e1051383780249b3_module = _ember_e1051383780249b3_importlib.module_from_spec(_ember_e1051383780249b3_spec)
    for _ember_e1051383780249b3_alias in _ember_e1051383780249b3_aliases:
        _ember_e1051383780249b3_prior = _ember_e1051383780249b3_sys.modules.get(_ember_e1051383780249b3_alias)
        if _ember_e1051383780249b3_prior is not None and _ember_e1051383780249b3_prior is not _ember_e1051383780249b3_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_totality/enforcement_leg.py')
        _ember_e1051383780249b3_sys.modules[_ember_e1051383780249b3_alias] = _ember_e1051383780249b3_module
    try:
        _ember_e1051383780249b3_spec.loader.exec_module(_ember_e1051383780249b3_module)
    except BaseException:
        for _ember_e1051383780249b3_alias in _ember_e1051383780249b3_aliases:
            if _ember_e1051383780249b3_sys.modules.get(_ember_e1051383780249b3_alias) is _ember_e1051383780249b3_module:
                _ember_e1051383780249b3_sys.modules.pop(_ember_e1051383780249b3_alias, None)
        raise
for _ember_e1051383780249b3_alias in _ember_e1051383780249b3_aliases:
    _ember_e1051383780249b3_prior = _ember_e1051383780249b3_sys.modules.get(_ember_e1051383780249b3_alias)
    if _ember_e1051383780249b3_prior is not None and _ember_e1051383780249b3_prior is not _ember_e1051383780249b3_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_totality/enforcement_leg.py')
    _ember_e1051383780249b3_sys.modules[_ember_e1051383780249b3_alias] = _ember_e1051383780249b3_module
CheckerSpec = getattr(_ember_e1051383780249b3_module, 'CheckerSpec')
_run_one_checker = getattr(_ember_e1051383780249b3_module, '_run_one_checker')
# issue2015 exact-local-import-end:scripts/ember_totality/enforcement_leg.py  # noqa: E402

# Discovered canonical invocation (read-only source review of
# src/ember/governance/scripts/check_milestone_reconciliation.py's run(), 2026-07-04): bare invocation
# (`python check_milestone_reconciliation.py`), no args; the module's own ROOT resolves
# from `os.path.dirname(HERE)` (HERE = the script's own directory), so pointing
# _run_one_checker's cwd/contract_root at a sandbox copy that contains its own
# src/ember/governance/scripts/check_milestone_reconciliation.py is fully self-contained -- no absolute path
# to the live tree is baked in anywhere in this module.
MILESTONE_CHECKER = CheckerSpec(
    name="check_milestone_reconciliation",
    rel_path="src/ember/governance/scripts/check_milestone_reconciliation.py",
    args=(),
    verdict_regex=r"^mapped=\d+/\d+\s+unmapped=\d+\s+lattice_diff=\d+\s+floor_contract_gaps=\d+\s+exit=(PASS|FAIL)\b",
    pass_values=("PASS",),
)


def _write_leg_receipt(results: dict, receipt_dir: Path) -> Path:
    receipt_dir = Path(receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    overall = "PASS" if all(r["verdict"] == "PASS" for r in results.values()) else "RED"
    receipt = {
        "ticket": "EMBER-TOTALITY-MILESTONE-LEG",
        "ts": ts,
        "kind": "gate",
        "chk_name": "run_milestone_leg",
        "spec_ref": "docs/audit/class2-unwatched-mandates-recon-20260704.md #2 "
                    "(Class-2 item 2), parent gh issue #35 DISPATCH 3 of 3",
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "checkers": results,
        "overall_verdict": overall,
    }
    path = receipt_dir / f"milestone-leg-{ts}.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return path


def run_milestone_leg(
    contract_root: Path,
    timeout_s: float = 180,
    *,
    receipt_dir: Optional[Path] = None,
) -> dict:
    """Execute check_milestone_reconciliation.py as a subprocess against contract_root,
    resolve its dual-source verdict via enforcement_leg's own (reused, unmodified)
    _run_one_checker, write one leg receipt JSON, and return
    {"check_milestone_reconciliation": {executed, exit_code, verdict_line, verdict,
    wall_s, receipt_path, reason}} -- the same shape run_enforcement_leg returns, so
    test_c_mile.py can read it identically to how test_c_enf.py reads run_enforcement_leg.

    No board wiring here: this function does not read or write ember_totality_spec.py.
    """
    contract_root = Path(contract_root)
    result = _run_one_checker(contract_root, MILESTONE_CHECKER, timeout_s)
    results = {MILESTONE_CHECKER.name: result}
    out_dir = Path(receipt_dir) if receipt_dir is not None else (contract_root / "scratch" / "ember_totality")
    _write_leg_receipt(results, out_dir)
    return results


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Run the board-wired milestone/lattice-mirror leg against a contract tree.")
    ap.add_argument("--contract-root", required=True, type=Path)
    ap.add_argument("--timeout-s", type=float, default=180.0)
    ap.add_argument("--receipt-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    results = run_milestone_leg(args.contract_root, args.timeout_s, receipt_dir=args.receipt_dir)
    for name, r in results.items():
        print(f"  [{r['verdict']}] {name}: exit={r['exit_code']} line={r['verdict_line']!r}")
        if r["reason"]:
            print(f"      reason: {r['reason']}")
    overall = "PASS" if all(r["verdict"] == "PASS" for r in results.values()) else "RED"
    print(f"OVERALL: {overall}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
