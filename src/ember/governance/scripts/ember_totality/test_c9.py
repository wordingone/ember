#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""C9 -- Hardest-core-first -- executable status probe (TDD).

Authoritative condition (<<external>>/state/<spec>, C9):

  R: identify and attack the hardest unresolved core ... BEFORE any
     scaffolding/docs/cleanup/readiness/credential/benchmark-shopping/
     harness-polish; a clear receipt shows the hardest named blocker solved
     or converted to a narrower executed successor.
  Does NOT count: scaffold/readiness/docs/credential work while a harder core
     is available; such work counts only when a receipt proves it directly
     removed the hardest named blocker.
  invalid token: invalid_scaffold_before_core
  CHK: every progress window reports the code-vs-docs metric
     (executable-code/test lines vs docs/receipt/spec lines, docs split
     before/during/after); a docs-only window is NOT substrate growth.

This file is a STATUS PROBE, not a unit test: it always exits 0 and prints a
single line by REALLY inspecting state under the resolved root. It never
hardcodes the verdict. C9 is a STANDING PROCESS-INVARIANT (docs/domains/governance/authority/GOAL.md �4.0(9)),
not a STATE-condition: it never prints RED/GREEN/UNEVALUABLE. It renders one
of AUDIT-OK / AUDIT-INCIDENT (a cadence audit from the goalforge-clear epoch)
or, pre-epoch (no operator-acceptance object exists yet), AUDIT-PENDING-EPOCH
� never RED. Pre-epoch history is explicitly OUT OF AUDIT SCOPE (�4.0(9)):
this probe only ever scans receipts dated at/after the epoch once one exists.

Run (Git Bash):  MSYS_NO_PATHCONV=1 wsl python3 \
  <local-exec-root>/state/ember-totality-build/test_c9.py
"""

# [PATH-REWRITE 2026-07-01] Imported from
# <<external>>/state/ember-totality-build/ into
# <local-exec-root>-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at <<external>>/state/<external-state> (and /mnt<local-mount-point>/M/...,
# <local-mount-point>/M/..., <TEMP_WORKSPACE>/... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. <external-state> does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.
from __future__ import annotations

import glob
import json
import os
import re

# --- locate <external-state> regardless of WSL vs Windows path conventions -------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                os.path.join(REPO_ROOT, "<external-state>"))
    if p
]

_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


def _find_root() -> str | None:
    for root in _CANDIDATE_ROOTS:
        if os.path.isdir(root):
            return root
    return None


def _norm_ts(ts: str) -> str:
    """Normalize an ISO8601-ish timestamp to the compact YYYYMMDDTHHMMSSZ
    form used by this codebase's receipt filenames."""
    return re.sub(r"[^0-9A-Za-z]", "", ts or "")


def _ts_from_name(path: str) -> str | None:
    m = _TS_RE.search(os.path.basename(path))
    return m.group(1) if m else None


def _find_epoch(root: str):
    """Return (epoch_ts, epoch_path) for the goalforge-clear operator-
    acceptance object (docs/spec/operator-acceptance-v1.md schema
    acceptance/v1, scope goalforge-clear, stored at
    receipts/acceptance/goalforge-clear-<date>.json), or (None, None) if no
    epoch has been recorded yet. docs/domains/governance/authority/GOAL.md �4.0(9): the epoch is the operator
    acceptance of this goal; C9 is a process-invariant with no meaning before
    it exists."""
    acc_dir = os.path.join(root, "receipts", "acceptance")
    if not os.path.isdir(acc_dir):
        return None, None
    candidates = sorted(glob.glob(os.path.join(acc_dir, "goalforge-clear-*.json")))
    for path in reversed(candidates):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if obj.get("schema") == "acceptance/v1" and obj.get("scope") == "goalforge-clear":
            ts = obj.get("ts")
            if ts:
                return _norm_ts(ts), path
    return None, None


# Tokens that DISQUALIFY a window from counting as C9-satisfying.  Two classes:
#   1. the condition's own invalid-token (must NOT appear as a real marker)
#   2. the does-NOT-count verdict: a docs-only window is not substrate growth
INVALID_TOKENS = [
    "invalid_scaffold_before_core",      # C9 invalid-token (negative assertion)
    "docs_only_no_executable_delta",     # does-NOT-count: docs-only != substrate growth
]

# Verdicts that DO count as substrate growth (real executable-code delta present)
SUBSTRATE_GROWTH_VERDICTS = {"code_only_executable_delta", "mixed_code_and_docs"}


def _is_code_vs_docs_receipt(obj: dict) -> bool:
    return obj.get("receipt_type") == "code_vs_docs_metric"


def _has_full_metric(metric: dict) -> bool:
    """CHK requires: code-vs-docs line totals + docs split before/during/after."""
    if not isinstance(metric, dict):
        return False
    lt = metric.get("line_totals")
    if not isinstance(lt, dict) or "code" not in lt or "docs" not in lt:
        return False
    dlt = metric.get("doc_lifecycle_totals")
    if not isinstance(dlt, dict):
        return False
    for phase in ("before_project", "during_project", "after_project"):
        if phase not in dlt:
            return False
    cvd = metric.get("code_vs_docs")
    if not isinstance(cvd, dict) or "code_fraction" not in cvd or "docs_fraction" not in cvd:
        return False
    return True


def scan(root: str, min_ts: "str | None") -> "tuple[str, str]":
    """Run the C9 detection logic over receipts in the given window and
    return (status, reason) with status in {RED, GREEN, UNEVALUABLE_ABSENT,
    UNEVALUABLE_ENVFAIL} -- a raw finding, not the final printed status.
    UNEVALUABLE_ABSENT = the window was scanned and is empty (evidence-
    absent, itself a cadence violation post-epoch). UNEVALUABLE_ENVFAIL =
    the probe could not scan at all (I/O error, missing dir -- defensive,
    never a violation finding). min_ts=None means unfiltered
    (whole-corpus, informational -- used pre-epoch); min_ts=<stamp> means
    filtered to receipts dated >= min_ts (the real post-epoch audit).
    """
    window = f">= {min_ts}" if min_ts is not None else "ALL (unfiltered, pre-epoch)"

    # Two distinct sub-cases of "no data", correction 2026-07-02: for a
    # standing cadence invariant, "the probe could not even look" (env
    # failure -- I/O error, missing receipts dir, glob exception) is NOT the
    # same finding as "the probe looked everywhere and the window is empty"
    # (evidence-absent). Only the former is a defensive/inconclusive case;
    # the latter is itself the cadence violation this probe exists to catch.
    receipts_dir = os.path.join(root, "receipts")
    if not os.path.isdir(receipts_dir):
        return "UNEVALUABLE_ENVFAIL", (
            f"C9: receipts dir not found at {receipts_dir} -- cannot scan "
            f"for code_vs_docs_metric receipts in window {window} "
            "(probe could not look, not a finding of an empty window)"
        )

    # Gather every code_vs_docs_metric receipt under the root, filtered to
    # the window.
    pattern = os.path.join(root, "receipts", "**", "*.json")
    try:
        paths_all = glob.glob(pattern, recursive=True)
    except OSError as exc:
        return "UNEVALUABLE_ENVFAIL", (
            f"C9: glob over {receipts_dir} raised {exc} in window {window} "
            "-- probe could not enumerate receipts"
        )
    paths = [p for p in paths_all
             if min_ts is None or (_ts_from_name(p) or "") >= min_ts]

    receipts: list[tuple[str, dict, str]] = []  # (path, obj, raw_text)
    parse_errors: list[str] = []
    for p in sorted(paths):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                raw = fh.read()
            obj = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            parse_errors.append(f"{os.path.basename(p)}: {exc}")
            continue
        if isinstance(obj, dict) and _is_code_vs_docs_receipt(obj):
            receipts.append((p, obj, raw))

    if not receipts:
        # The window WAS scanned successfully (glob ran, files were read);
        # zero code_vs_docs_metric receipts exist in it. For a standing
        # cadence invariant this is evidence-ABSENT, not input-missing: an
        # unreceipted window is the violation this probe is watching for.
        return "UNEVALUABLE_ABSENT", (
            f"C9: no code_vs_docs_metric receipt found under {root}/receipts "
            f"in window {window} ({len(paths)}/{len(paths_all)} "
            f"window/total json files scanned, {len(parse_errors)} parse "
            "errors) -- window was scanned successfully and is empty"
        )

    # (2) NEGATIVE assertions: NONE of the does-NOT-count invalid tokens may
    # appear as a genuine disqualifying marker.  invalid_scaffold_before_core
    # must not be present in any receipt's text at all.  A docs-only verdict
    # disqualifies that specific window from counting as substrate growth.
    scaffold_violations: list[str] = []
    docs_only_windows: list[str] = []
    for p, obj, raw in receipts:
        if "invalid_scaffold_before_core" in raw:
            scaffold_violations.append(os.path.basename(p))
        verdict = (obj.get("metric") or {}).get("verdict")
        if verdict == "docs_only_no_executable_delta":
            docs_only_windows.append(os.path.basename(p))

    if scaffold_violations:
        return "RED", (
            "C9: invalid_scaffold_before_core marker present in "
            f"{len(scaffold_violations)} receipt(s) in window {window}; "
            f"first={scaffold_violations[0]} "
            "(scaffold/docs counted while a harder core was available)"
        )

    # (1) POSITIVE CHK: at least one REAL code_vs_docs_metric receipt that
    # reports the full metric (code/docs line totals + before/during/after doc
    # split + fractions) AND represents substrate growth (executable-code delta
    # present, i.e. verdict is NOT docs-only).
    satisfying: list[tuple[str, dict]] = []
    incomplete: list[str] = []
    for p, obj, _raw in receipts:
        metric = obj.get("metric") or {}
        if not _has_full_metric(metric):
            incomplete.append(os.path.basename(p))
            continue
        if metric.get("verdict") in SUBSTRATE_GROWTH_VERDICTS and metric["line_totals"].get("code", 0) > 0:
            satisfying.append((p, obj))

    total = len(receipts)
    n_growth = len(satisfying)
    n_docs_only = len(docs_only_windows)

    if not satisfying:
        return "RED", (
            f"C9: {total} code_vs_docs_metric receipt(s) present in window "
            f"{window} but NONE report substrate growth (code lines>0, "
            f"non-docs-only); docs_only={n_docs_only}, "
            f"incomplete_metric={len(incomplete)}"
        )

    # GREEN: pick the largest-executable-code satisfying window as witness.
    witness_path, witness = max(
        satisfying, key=lambda t: t[1]["metric"]["line_totals"]["code"]
    )
    wm = witness["metric"]
    rel = os.path.relpath(witness_path, root)
    return "GREEN", (
        f"C9 CHK satisfied in window {window}: "
        f"{n_growth}/{total} code_vs_docs_metric window(s) show substrate "
        f"growth ({n_docs_only} docs-only excluded, no "
        "invalid_scaffold_before_core marker); witness "
        f"{rel} verdict={wm['verdict']} "
        f"code={wm['line_totals']['code']} docs={wm['line_totals']['docs']} "
        f"docs_split(before/during/after)="
        f"{wm['doc_lifecycle_totals']['before_project']}/"
        f"{wm['doc_lifecycle_totals']['during_project']}/"
        f"{wm['doc_lifecycle_totals']['after_project']} "
        f"code_fraction={wm['code_vs_docs']['code_fraction']}"
    )


def main() -> int:
    """Resolve the epoch, run scan() in the appropriate window, and relabel
    the raw RED/GREEN/UNEVALUABLE finding against the
    AUDIT-OK/AUDIT-INCIDENT/AUDIT-PENDING-EPOCH contract (docs/domains/governance/authority/GOAL.md �4.0(9))
    before printing."""
    root = _find_root()
    if root is None:
        print("AUDIT-PENDING-EPOCH C9: state root not found at any known path "
              f"(tried {_CANDIDATE_ROOTS}) -- cannot even locate "
              "receipts/acceptance to check for an epoch")
        return 0

    epoch_ts, epoch_path = _find_epoch(root)
    raw_status, raw_reason = scan(root, epoch_ts)

    if epoch_ts is None:
        print(
            f"AUDIT-PENDING-EPOCH {raw_reason} "
            f"[PRE-EPOCH INFORMATIONAL finding={raw_status} -- no "
            "goalforge-clear operator-acceptance object exists yet at "
            "receipts/acceptance/goalforge-clear-*.json (schema "
            "acceptance/v1); this is NOT an audit verdict, pre-epoch "
            "history is OUT OF AUDIT SCOPE per docs/domains/governance/authority/GOAL.md �4.0(9), the actual "
            "status is never RED/GREEN/UNEVALUABLE for this row]"
        )
        return 0

    # Post-epoch relabel (correction 2026-07-02: the prior UNEVALUABLE->
    # AUDIT-OK "vacuous-no-data" reading was FAIL-OPEN for a cadence
    # invariant). GREEN->AUDIT-OK. RED->AUDIT-INCIDENT. UNEVALUABLE_ABSENT
    # (scanned, window empty) -> AUDIT-INCIDENT: for a standing cadence
    # invariant an unreceipted window IS the violation. UNEVALUABLE_ENVFAIL
    # (could not even scan) -> AUDIT-PENDING-EPOCH, defensive, with the
    # failure text carried in reason -- never silently AUDIT-OK.
    if raw_status == "GREEN":
        final_status = "AUDIT-OK"
    elif raw_status == "RED":
        final_status = "AUDIT-INCIDENT"
    elif raw_status == "UNEVALUABLE_ABSENT":
        final_status = "AUDIT-INCIDENT"
        raw_reason = f"[EVIDENCE-ABSENT post-epoch] {raw_reason}"
    else:  # UNEVALUABLE_ENVFAIL, or any other unrecognized raw status
        final_status = "AUDIT-PENDING-EPOCH"
        raw_reason = f"[PROBE-ENV-FAILURE post-epoch, defensive -- not a cadence finding] {raw_reason}"
    print(f"{final_status} {raw_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
