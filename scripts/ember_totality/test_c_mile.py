#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_c_mile.py -- STATUS PROBE for Ember goal condition C-MILE.

Registry text: docs/spec/conditions-v1.md SS4.2 C-MILE (Class-2 item 2, docs/audit/
class2-unwatched-mandates-recon-20260704.md #2, parent gh issue #35). R: the milestone
lattice (docs/spec/milestones-v1.md sections A/C/D) EXECUTES and returns a coherent
verdict against its own source-of-truth inputs -- a GREEN board can never again coexist
with a silently broken/tampered/stale milestone-vs-lattice mirror (the checker existed,
landed 2026-07-01, but the board only ever tamper-hashed it, never ran it -- the same
un-wired shape C-ENF cured for the publication/energy-law layer, issue #38).

CHK enforced here: `milestone_leg.run_milestone_leg(ROOT)` subprocess-executes
src/ember/governance/scripts/check_milestone_reconciliation.py with dual-source verdict resolution (process
exit code cross-checked against the checker's own printed verdict line, reusing
enforcement_leg.py's _run_one_checker UNMODIFIED -- exactly the C-ENF pattern, not a
reimplementation):

  - executed == True AND verdict == "PASS" (both exit code and printed verdict line
    agree the checker passed) -- GREEN;
  - "FAIL" (checker ran, agreed it failed) -- RED;
  - "DISAGREEMENT" (exit code and verdict line conflict -- the probe-verdict-gate
    failure class) -- RED;
  - "UNRESOLVABLE" (timeout / missing checker / unparseable output -- including the
    checker's own ParseError/exception path, which prints only to stderr and leaves no
    stdout line matching the verdict regex) -- RED.

Unlike C-ENF's check_publication_gate conjunct (an endgame gate honestly CLOSED
pre-completion, so a coherent FAIL is GREEN-compatible there), check_milestone_
reconciliation.py's own contract has no such "honestly closed" state: docs/spec/
milestones-v1.md's Validation hook section treats (a) and (c) as FATAL-on-violation and
only (b) (the lattice-vs-PROBLEMS.md gates diff) as report-only-never-fatal. So here,
unlike C-ENF, a coherent FAIL is NOT GREEN-compatible -- only PASS is.

Fail-closed: milestone_leg.py or enforcement_leg.py missing/unimportable = RED (the leg
itself is gone -- that IS the regression), never UNEVALUABLE. UNEVALUABLE is reserved for
environment failure (no usable ROOT).

[ISSUE #749 cure, docs/charter/probe-authoring-contract.md] Execution-binding hardening. The
pre-cure checker trusted `run_milestone_leg()`'s IN-PROCESS return dict alone -- if
milestone_leg.py were ever broken/tampered to fabricate a `{"executed": True,
"verdict": "PASS", ...}` dict without actually launching the checker subprocess, this
file had no way to notice (checklist items 1/3/4: recompute the decisive number, resolve
+parse the cited artifact, cross-reference an independently-produced document). The leg
already writes its own receipt to disk (`_write_leg_receipt`, milestone_leg.py, unchanged
here); this file now (a) resolves and parses THAT on-disk receipt -- located by a
before/after glob diff scoped to this exact invocation, the same set-diff idiom
ind4_customize_experiment_producer.py uses for loop_econ_gate.py's selftest receipt --
(b) requires the on-disk artifact to agree field-for-field with the in-process dict (a
tampered return value that is not backed by a matching persisted artifact is caught),
and (c) independently RECOMPUTES the dual-source PASS/FAIL/DISAGREEMENT verdict from the
raw `verdict_line` text (re-matched against this file's OWN copy of the checker's
verdict-line contract, never trusting milestone_leg.py's pre-classified `verdict`
string) cross-checked against `exit_code` -- mirroring, not importing,
enforcement_leg.py's `_run_one_checker` resolution logic. A receipt with only
self-attested fields (an `executed`/`verdict`/`verdict_line` dict with no matching
persisted artifact, or a persisted artifact whose raw verdict_line does not actually
say PASS) fails this new binding and goes RED. UNAVAILABLE evidence -- the leg receipt
directory absent, no new receipt written, or the new receipt unreadable/unparseable --
is a REFUSAL (RED), never a silently-downgraded skip (checklist item 9: once the leg
has genuinely executed, its output is binding).

DISCIPLINE: status probe -- always exits 0, one line, real bytes decide, no hardcoded
verdict. RED / GREEN / UNEVALUABLE(env).
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

INVALID_TOKENS = [
    "invalid_milestone_regression",
]

CHECKER_NAME = "check_milestone_reconciliation"

# [ISSUE #749 cure] milestone_leg.py's own leg-receipt filename convention
# (`_write_leg_receipt`: f"milestone-leg-{ts}.json" under contract_root/scratch/
# ember_totality/ by default). Used ONLY to locate the receipt THIS invocation wrote via
# a before/after set-diff -- never trusted by name pattern alone, always resolved+parsed.
LEG_RECEIPT_GLOB = "milestone-leg-*.json"
LEG_RECEIPT_SUBDIR = os.path.join("scratch", "ember_totality")

# [ISSUE #749 cure] check_milestone_reconciliation.py's real verdict-line contract
# (read directly from milestone_leg.py's own MILESTONE_CHECKER.verdict_regex / docstring,
# re-derived HERE rather than imported so a compromised milestone_leg.py cannot also
# rewrite the regex this file recomputes against).
MILESTONE_VERDICT_LINE_RE = re.compile(
    r"^mapped=\d+/\d+\s+unmapped=\d+\s+lattice_diff=\d+\s+floor_contract_gaps=\d+\s+exit=(PASS|FAIL)\b")


def emit(color, reason):
    print(f"{color} {reason}")
    sys.exit(0)


def _leg_receipt_dir():
    return os.path.join(ROOT, LEG_RECEIPT_SUBDIR)


def _existing_leg_receipts():
    d = _leg_receipt_dir()
    if not os.path.isdir(d):
        return set()
    try:
        return set(glob.glob(os.path.join(d, LEG_RECEIPT_GLOB)))
    except OSError:
        return set()


def _recompute_dual_source_verdict(verdict_line, exit_code):
    """Independently re-derive PASS/FAIL/DISAGREEMENT from the RAW verdict_line text
    and exit_code -- never trusting a pre-classified 'verdict' string. Returns
    (recomputed_verdict, detail)."""
    if not isinstance(verdict_line, str) or not verdict_line.strip():
        return "UNRESOLVABLE", "verdict_line missing/empty -- cannot recompute"
    m = MILESTONE_VERDICT_LINE_RE.match(verdict_line.strip())
    if not m:
        return "UNRESOLVABLE", (
            f"verdict_line {verdict_line!r} does not match the checker's own "
            f"printed-verdict contract {MILESTONE_VERDICT_LINE_RE.pattern!r}")
    line_token = m.group(1)
    line_pass = (line_token == "PASS")
    exit_pass = (exit_code == 0)
    if line_pass and exit_pass:
        return "PASS", f"verdict_line token={line_token!r} + exit_code=0 agree"
    if (not line_pass) and (not exit_pass):
        return "FAIL", f"verdict_line token={line_token!r} + exit_code={exit_code} agree (fail)"
    return "DISAGREEMENT", (
        f"exit_code={exit_code} ({'pass' if exit_pass else 'fail'}) vs verdict_line "
        f"token={line_token!r} ({'pass' if line_pass else 'fail'}) -- never silently resolved")


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-MILE: no usable contract root (env)")

    sys.path.insert(0, os.path.join(ROOT, "scripts", "ember_totality"))
    try:
        from milestone_leg import run_milestone_leg  # noqa: E402
    except Exception as e:  # missing/broken module IS the regression -- fail closed
        emit("RED", f"C-MILE: milestone_leg unimportable ({type(e).__name__}: {e}) "
                    f"-- the milestone-reconciliation leg itself is gone [invalid_milestone_regression]")

    from pathlib import Path

    # [ISSUE #749 cure] snapshot BEFORE invocation so the on-disk receipt this exact
    # run writes can be isolated afterward (set-diff, not name-guessing).
    pre_existing = _existing_leg_receipts()

    try:
        results = run_milestone_leg(Path(ROOT))
    except Exception as e:
        emit("RED", f"C-MILE: run_milestone_leg raised {type(e).__name__}: {e} "
                    f"[invalid_milestone_regression]")

    if not isinstance(results, dict) or CHECKER_NAME not in results:
        emit("RED", f"C-MILE: leg returned no result for {CHECKER_NAME!r} [invalid_milestone_regression]")

    r = results[CHECKER_NAME]
    verdict = r.get("verdict")

    if not r.get("executed"):
        emit("RED", f"C-MILE: {CHECKER_NAME} never executed ({r.get('reason')}) "
                    f"[invalid_milestone_regression]")

    if verdict != "PASS":
        emit("RED", f"C-MILE: {CHECKER_NAME} verdict {verdict!r} "
                    f"({r.get('reason') or r.get('verdict_line')}) [invalid_milestone_regression]")

    # --- [ISSUE #749 cure] resolve + parse the on-disk leg receipt THIS invocation
    # wrote (never trust the in-process return dict alone). ------------------------
    post_existing = _existing_leg_receipts()
    new_receipts = sorted(post_existing - pre_existing)
    if len(new_receipts) != 1:
        emit("RED", f"C-MILE: expected exactly 1 new leg receipt from this invocation under "
                    f"{LEG_RECEIPT_SUBDIR}, found {len(new_receipts)} -- the leg's own persisted "
                    f"artifact does not resolve, so its in-process claim cannot be execution-bound "
                    f"[invalid_milestone_regression]")

    receipt_path = new_receipts[0]
    try:
        with open(receipt_path, "r", encoding="utf-8") as fh:
            on_disk = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        emit("RED", f"C-MILE: leg receipt {os.path.relpath(receipt_path, ROOT)} unreadable/"
                    f"unparseable ({type(e).__name__}: {e}) -- UNAVAILABLE evidence refuses, "
                    f"never a silent skip [invalid_milestone_regression]")

    disk_checkers = on_disk.get("checkers") if isinstance(on_disk, dict) else None
    disk_r = disk_checkers.get(CHECKER_NAME) if isinstance(disk_checkers, dict) else None
    if not isinstance(disk_r, dict):
        emit("RED", f"C-MILE: leg receipt {os.path.relpath(receipt_path, ROOT)} carries no "
                    f"result for {CHECKER_NAME!r} -- persisted artifact does not back the "
                    f"in-process claim [invalid_milestone_regression]")

    # Cross-reference: the persisted artifact must independently agree with the
    # in-process return value on every decisive field (checklist item 4 -- a
    # fabricated return value not backed by a matching written receipt is caught).
    mismatches = [
        f"{field}: in-process={r.get(field)!r} != on-disk={disk_r.get(field)!r}"
        for field in ("executed", "verdict", "exit_code", "verdict_line")
        if r.get(field) != disk_r.get(field)
    ]
    if mismatches:
        emit("RED", f"C-MILE: in-process leg result disagrees with its own persisted receipt "
                    f"{os.path.relpath(receipt_path, ROOT)} -- {'; '.join(mismatches)} "
                    f"[invalid_milestone_regression]")

    # Recompute the decisive PASS/FAIL/DISAGREEMENT verdict independently from the raw
    # verdict_line + exit_code on the PERSISTED artifact -- never trust the pre-classified
    # 'verdict' string, on-disk or in-process, as ground truth (checklist item 1).
    recomputed, detail = _recompute_dual_source_verdict(
        disk_r.get("verdict_line"), disk_r.get("exit_code"))
    if recomputed != "PASS":
        emit("RED", f"C-MILE: independently recomputed dual-source verdict={recomputed} "
                    f"({detail}) from persisted receipt {os.path.relpath(receipt_path, ROOT)} "
                    f"-- disagrees with or fails the claimed PASS [invalid_milestone_regression]")

    emit("GREEN", f"C-MILE CHK satisfied: {CHECKER_NAME} executed with coherent PASS "
                  f"dual-source verdict -- {r.get('verdict_line')!r} "
                  f"({r.get('wall_s')}s, exit {r.get('exit_code')}); persisted leg receipt "
                  f"{os.path.relpath(receipt_path, ROOT)} resolved+parsed, agrees field-for-"
                  f"field with the in-process result, and its own raw verdict_line + exit_code "
                  f"independently recompute to PASS")


if __name__ == "__main__":
    main()
