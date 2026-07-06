#!/usr/bin/env python3
"""enforcement_leg.py — board-wired pubgate enforcement leg (issue #38, Class-2 cure,
sub-issue of #35).

Standalone module. `run_enforcement_leg` subprocess-executes each named checker with its
own canonical CLI and cross-checks the process EXIT CODE against the checker's own PRINTED
VERDICT LINE. The two are never forced to agree silently:

  - both signal pass                          -> verdict "PASS"
  - both signal fail                          -> verdict "FAIL"
  - they disagree (exit 0 + fail-line, or
    nonzero exit + pass-line)                  -> verdict "DISAGREEMENT" (probe-verdict-gate
                                                   class: probes that exit 0 while printing RED)
  - timeout / missing checker / unparseable
    stdout                                     -> verdict "UNRESOLVABLE"

Fail-closed by construction: only "PASS" is a pass. Board-layer mapping of anything != PASS
to a RED board row is Deliverable 3 (board wiring) — maintainer-owned, NOT done here. This
module does not import, reference, or modify `ember_totality_spec.py`, any checker, or any
rig/bar file; it is new and unwired.

Checker registry (`DEFAULT_CHECKERS`) is resolved relative to a caller-supplied
`contract_root` — this module hardcodes no absolute path to any checker. The exact CLI
invocations and verdict-line/exit-code conventions below were discovered by reading each
checker's own module docstring, argparse block, and `main()` (see the builder report for the
read locations and the disclosed conflict: at build time neither checker existed inside the
tree this module was authored in, so the registry below is DESIGN-VERIFIED against the
checkers' real source but has not been integration-tested against a live contract tree from
this working tree).

Stdlib only. No network. No GPU allocation (subprocess-launch + regex/JSON only).
"""
import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence


@dataclass(frozen=True)
class CheckerSpec:
    """One checker's canonical enforcement invocation + verdict-line contract."""
    name: str
    rel_path: str                      # resolved against contract_root
    args: tuple = ()
    verdict_regex: str = r"^OVERALL:\s*(GREEN|RED)\b"
    pass_values: tuple = ("GREEN",)
    receipt_regex: str = r"^receipt:\s*(.+)$"


# Discovered canonical invocations (read-only source review, 2026-07-03):
#
# check_publication_gate.py — bare invocation (`python check_publication_gate.py`) runs the
# real 5-conjunct gate against REPO_ROOT = <script>.parent.parent, prints one "OVERALL: GREEN
# (OPEN N/M)" or "OVERALL: RED (CLOSED N/M)" line, then "receipt: <relpath>"; exit 0 iff
# overall verdict GREEN, else 1 (`run()` -> `sys.exit(run())`).
#
# check_energy_law_theory.py — the only invocation that both (a) checks the checker's own
# regression state and (b) yields a real pass/fail exit code is `--selftest` (prints
# "selftest: ALL PASS" or "N FAILED", exit 0/1). `--all` is report-only and ALWAYS exits 0
# even when every receipt FAILs, so it cannot serve as a dual-source gate input; `--file`
# needs one caller-supplied receipt path, not a general regression check. `--selftest` is
# therefore the canonical enforcement invocation for this checker.
DEFAULT_CHECKERS: tuple = (
    CheckerSpec(
        name="check_publication_gate",
        rel_path="scripts/check_publication_gate.py",
        args=(),
        verdict_regex=r"^OVERALL:\s*(GREEN|RED)\b",
        pass_values=("GREEN",),
    ),
    CheckerSpec(
        name="check_energy_law_theory",
        rel_path="scripts/check_energy_law_theory.py",
        args=("--selftest",),
        verdict_regex=r"^selftest:\s*(ALL PASS|\d+ FAILED)\s*$",
        pass_values=("ALL PASS",),
    ),
)

VERDICTS = ("PASS", "FAIL", "DISAGREEMENT", "UNRESOLVABLE")


def _new_result(checker_path: Path) -> dict:
    return {
        "executed": False,
        "exit_code": None,
        "verdict_line": None,
        "verdict": "UNRESOLVABLE",
        "wall_s": 0.0,
        "receipt_path": None,
        "reason": None,
        "checker_path": str(checker_path),
    }


def _run_one_checker(contract_root: Path, spec: CheckerSpec, timeout_s: float) -> dict:
    """Execute one checker as a subprocess and resolve its dual-source verdict. Never
    raises — every failure mode (missing file, timeout, launch error, unparseable output,
    disagreement) is captured in the returned dict."""
    script_path = contract_root / spec.rel_path
    result = _new_result(script_path)

    if not script_path.is_file():
        result["reason"] = f"checker script not found: {script_path}"
        return result

    cmd = [sys.executable, "-u", str(script_path), *spec.args]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=str(contract_root), capture_output=True, text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        result["executed"] = True
        result["wall_s"] = round(time.monotonic() - t0, 3)
        result["reason"] = f"timeout after {timeout_s}s"
        partial = e.stdout
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        result["stdout_tail"] = (partial or "")[-2000:]
        return result
    except OSError as e:
        result["executed"] = True
        result["wall_s"] = round(time.monotonic() - t0, 3)
        result["reason"] = f"subprocess launch failed: {type(e).__name__}: {e}"
        return result

    wall_s = round(time.monotonic() - t0, 3)
    stdout = proc.stdout or ""
    result["executed"] = True
    result["wall_s"] = wall_s
    result["exit_code"] = proc.returncode

    receipt_m = re.search(spec.receipt_regex, stdout, flags=re.MULTILINE)
    if receipt_m:
        result["receipt_path"] = receipt_m.group(1).strip()

    verdict_m = None
    for line in stdout.splitlines():
        m = re.match(spec.verdict_regex, line.strip())
        if m:
            verdict_m = m
            result["verdict_line"] = line.strip()
            break

    if verdict_m is None:
        result["verdict"] = "UNRESOLVABLE"
        result["reason"] = f"no line matched verdict_regex {spec.verdict_regex!r}"
        result["stdout_tail"] = stdout[-2000:]
        return result

    token = verdict_m.group(1)
    line_pass = token in spec.pass_values
    exit_pass = (proc.returncode == 0)

    if exit_pass and line_pass:
        result["verdict"] = "PASS"
    elif (not exit_pass) and (not line_pass):
        result["verdict"] = "FAIL"
    else:
        result["verdict"] = "DISAGREEMENT"
        result["reason"] = (
            f"exit_code={proc.returncode} ({'pass' if exit_pass else 'fail'}) vs "
            f"verdict_line token={token!r} ({'pass' if line_pass else 'fail'}) — "
            f"never silently resolved"
        )
    return result


def _write_leg_receipt(results: dict, receipt_dir: Path) -> Path:
    receipt_dir = Path(receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    overall = "PASS" if all(r["verdict"] == "PASS" for r in results.values()) else "RED"
    receipt = {
        "ticket": "EMBER-TOTALITY-ENFORCEMENT-LEG",
        "ts": ts,
        "kind": "gate",
        "chk_name": "run_enforcement_leg",
        "spec_ref": "GitHub issue #38 (board-wired pubgate enforcement leg), parent #35 Class 2",
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "checkers": results,
        "overall_verdict": overall,
    }
    path = receipt_dir / f"enforcement-leg-{ts}.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return path


def run_enforcement_leg(
    contract_root: Path,
    timeout_s: float = 300,
    *,
    checkers: Optional[Sequence[CheckerSpec]] = None,
    receipt_dir: Optional[Path] = None,
) -> dict:
    """Execute every checker in `checkers` (default: DEFAULT_CHECKERS) as a subprocess
    against `contract_root`, resolve each one's dual-source verdict, write one leg receipt
    JSON, and return {checker_name: {executed, exit_code, verdict_line, verdict, wall_s,
    receipt_path, reason}}.

    No board wiring: this function does not read or write ember_totality_spec.py, and its
    return value maps checker names to PASS/FAIL/DISAGREEMENT/UNRESOLVABLE — the board-row
    RED-mapping (anything != PASS) is Deliverable 3, done elsewhere by the maintainer.
    """
    contract_root = Path(contract_root)
    specs = checkers if checkers is not None else DEFAULT_CHECKERS
    results = {spec.name: _run_one_checker(contract_root, spec, timeout_s) for spec in specs}
    out_dir = Path(receipt_dir) if receipt_dir is not None else (contract_root / "scratch" / "ember_totality")
    _write_leg_receipt(results, out_dir)
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Run the board-wired pubgate enforcement leg (issue #38) against a contract tree.")
    ap.add_argument("--contract-root", required=True, type=Path)
    ap.add_argument("--timeout-s", type=float, default=300.0)
    ap.add_argument("--receipt-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    results = run_enforcement_leg(args.contract_root, args.timeout_s, receipt_dir=args.receipt_dir)
    for name, r in results.items():
        print(f"  [{r['verdict']}] {name}: exit={r['exit_code']} line={r['verdict_line']!r}")
        if r["reason"]:
            print(f"      reason: {r['reason']}")
    overall = "PASS" if all(r["verdict"] == "PASS" for r in results.values()) else "RED"
    print(f"OVERALL: {overall}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
