#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_c_proc.py — STATUS PROBE for Ember goal condition C-PROC.

Registry text: docs/spec/conditions-v1.md §4.2 C-PROC (docs/domains/governance/authority/GOAL.md §13). R: the
delegation/review record the OPERATOR can see (public-repo issues, milestones,
PRs) is CURRENT with the work record — work never runs ahead of its visible
process reflection.

CHK enforced here (offline, receipts-based — the probe never touches the
network; currency is proven by a process-visibility receipt the working
session must write): the newest receipt under receipts/process-visibility/
must (a) cite >=1 public issue URL (an "/issues/<n>" reference), (b) name
covered commits that EXIST in the trees they claim (verified via git
cat-file), (c) be current — the newest work commit on either tree is at
most GRACE_HOURS newer than the newest covered commit — and (d) carry an
`open_prs` block enumerating every open PR on the public repo with its
review state: entries are {number, state: "reviewed"|"verdict-pending",
pending_h} (or the literal string "none-open"); any entry with
pending_h > GRACE_HOURS and state != "reviewed" = RED (an open PR is work
awaiting the review record, same clock as everything else; extension
2026-07-02 after PR #1 sat 32h unreviewed with nothing clocking it).
Receipt-absent on a scannable tree = RED (the visible process is genuinely
behind). Work outpacing the receipt by more than GRACE_HOURS = RED.

Receipt schema v2 (gh issue #15, frozen 2026-07-02): a receipt whose `ts`
is >= 20260703T02 (UTC cutover) MUST additionally carry a `delegation`
block -- an object keyed by issue ref (e.g. "issue-15"), each entry
{built_by, verified_by} both non-empty strings naming who built the work
and who verified it. Receipts older than the cutover are grandfathered --
clauses (a)-(d) above still apply to them, unchanged, with no delegation
block required. This is clause (e): a receipt at/after the cutover with no
delegation block, or any entry missing/empty built_by or verified_by, = RED
(invalid_process_receipt_without_delegation).

Why offline: a probe that calls the GitHub API renders the whole board
UNEVALUABLE on any network hiccup. Instead the burden is inverted — the
session that commits work must ALSO write the receipt citing the issue
surfaces it advanced; this probe checks the receipt against git, which is
local bytes. Fabricating the receipt without the surfaces is an ordinary
receipts-integrity violation (same court as every other receipt).

DISCIPLINE: status probe — always exits 0, one line, real bytes decide, no
hardcoded verdict. RED / GREEN / UNEVALUABLE(env); receipt-absent is RED.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

INVALID_TOKENS = [
    "invalid_internal_task_as_issue",
    "invalid_process_receipt_without_issue_urls",
    "invalid_process_receipt_without_delegation",
    "invalid_invisible_process",
]

GRACE_HOURS = 48
ISSUE_URL_RE = re.compile(r"/issues/\d+")

# Receipt schema v2 cutover (gh issue #15, frozen 2026-07-02): receipts at
# or after this UTC instant must carry a delegation block (clause e, below).
DELEGATION_CUTOVER_TS = "20260703T020000Z"
RECEIPT_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")

# Publication-visibility cutover (gh issue #42, frozen 2026-07-03): a receipt
# at/after this instant declaring open_prs "none-open" must carry a
# publication_state block proving nothing is invisibly unpublished (clause f).
PUBVIS_CUTOVER_TS = "20260703T230000Z"
PUBVIS_JUSTIFICATION_MAX_AGE_H = 24.0


def _receipt_ts(data, name):
    """Receipt UTC ts: the `ts` field when well-formed, else from the filename."""
    ts = data.get("ts")
    if isinstance(ts, str) and re.match(r"^\d{8}T\d{6}Z$", ts):
        return ts
    m = RECEIPT_TS_RE.search(name)
    return m.group(1) if m else None


def emit(color, reason):
    print(f"{color} {reason}")
    sys.exit(0)


def _git(tree, *args):
    """Run git in `tree`; return (ok, stdout). Never raises."""
    try:
        r = subprocess.run(
            ["git", "-C", tree, *args],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0, r.stdout.strip()
    except Exception as exc:  # git missing / timeout -> env failure
        return False, str(exc)


def _commit_time(tree, ref):
    ok, out = _git(tree, "log", "-1", "--format=%ct", ref)
    if not ok or not out.isdigit():
        return None
    return int(out)


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-PROC: state root not found under any known layout -- probe cannot look")
    pv_dir = os.path.join(ROOT, "receipts", "process-visibility")
    receipts_parent = os.path.join(ROOT, "receipts")
    if not os.path.isdir(receipts_parent):
        emit("UNEVALUABLE", f"C-PROC: receipts dir absent at {receipts_parent} -- probe cannot look")

    candidates = sorted(glob.glob(os.path.join(pv_dir, "*.json")))
    if not candidates:
        emit("RED", "C-PROC: no process-visibility receipt under receipts/process-visibility/ -> "
                    "the operator-visible process record is genuinely BEHIND the work record "
                    "(docs/domains/governance/authority/GOAL.md sec 13: work without its visible reflection). The cure is not a "
                    "receipt alone -- it is the public issues/milestones/PRs the receipt cites.")

    # Newest receipt by filename sort (receipts embed UTC ts in the name).
    newest = candidates[-1]
    name = os.path.basename(newest)
    try:
        with open(newest, "r", encoding="utf-8") as fh:
            raw = fh.read()
        data = json.loads(raw)
    except Exception as exc:
        emit("RED", f"C-PROC: newest receipt {name} unreadable ({exc})")
    if data.get("_synthetic_control_fixture"):
        emit("RED", f"C-PROC: newest receipt {name} is a synthetic control fixture, never evidence")
    lowered = raw.lower()
    hit = [t for t in INVALID_TOKENS if t in lowered]
    if hit:
        emit("RED", f"C-PROC: {name}: invalid-token present {hit}")

    urls = data.get("issue_urls")
    if not (isinstance(urls, list) and urls
            and all(isinstance(u, str) and ISSUE_URL_RE.search(u) for u in urls)):
        emit("RED", f"C-PROC: {name}: issue_urls must be a non-empty list of public issue URLs "
                    "(invalid_process_receipt_without_issue_urls)")

    open_prs = data.get("open_prs")
    if open_prs != "none-open":
        if not isinstance(open_prs, list):
            emit("RED", f"C-PROC: {name}: open_prs block absent -- the receipt must enumerate "
                        "open public PRs and their review state (or the literal \"none-open\")")
        for e in open_prs:
            if not (isinstance(e, dict) and isinstance(e.get("number"), int)
                    and e.get("state") in ("reviewed", "verdict-pending")
                    and isinstance(e.get("pending_h"), (int, float))):
                emit("RED", f"C-PROC: {name}: malformed open_prs entry {e!r}")
            if e["state"] != "reviewed" and e["pending_h"] > GRACE_HOURS:
                emit("RED", f"C-PROC: {name}: PR #{e['number']} verdict-pending "
                            f"{e['pending_h']:.1f}h > {GRACE_HOURS}h grace -- an open PR is work "
                            "awaiting its review record")

    # (f) publication-visibility (gh issue #42, frozen 2026-07-03): "none-open"
    # stopped being self-certifying the day a full operating window ran GREEN
    # while every landing sat in local trees with no PR activity (operator,
    # third repetition, 2026-07-03). A receipt at/after the cutover that
    # declares no open PRs must now PROVE the process is visible anyway:
    # either nothing is unpublished, or the receipt names an in-flight
    # export/PR-preparation lane whose own receipt exists on disk and is
    # fresh. Grandfathered below the cutover, same pattern as (e).
    _rts = _receipt_ts(data, name)
    if _rts is not None and _rts >= PUBVIS_CUTOVER_TS and open_prs == "none-open":
        pub = data.get("publication_state")
        ok_pub = (isinstance(pub, dict)
                  and isinstance(pub.get("public_master_sha"), str) and pub["public_master_sha"].strip()
                  and isinstance(pub.get("local_shas"), dict) and pub["local_shas"]
                  and isinstance(pub.get("unpublished_landings"), int)
                  and pub["unpublished_landings"] >= 0)
        if not ok_pub:
            emit("RED", f"C-PROC: {name}: open_prs is \"none-open\" but the receipt carries no "
                        "valid publication_state block {public_master_sha, local_shas, "
                        "unpublished_landings} (invalid_invisible_process)")
        if pub["unpublished_landings"] > 0:
            just = pub.get("justification")
            ok_just = False
            if isinstance(just, dict) and isinstance(just.get("lane"), str) and just["lane"].strip() \
                    and isinstance(just.get("receipt_path"), str) and just["receipt_path"].strip():
                jpath = just["receipt_path"]
                jabs = jpath if os.path.isabs(jpath) else os.path.join(ROOT, jpath)
                if os.path.isfile(jabs):
                    age_h = (time.time() - os.path.getmtime(jabs)) / 3600.0
                    ok_just = age_h <= PUBVIS_JUSTIFICATION_MAX_AGE_H
            if not ok_just:
                emit("RED", f"C-PROC: {name}: {pub['unpublished_landings']} unpublished landing(s) "
                            "declared with no open PR and no valid justification (an in-flight "
                            "export/PR-prep lane whose receipt_path exists on disk and is younger "
                            f"than {PUBVIS_JUSTIFICATION_MAX_AGE_H:.0f}h) -- the process is "
                            "invisible to the operator (invalid_invisible_process)")

    covered = data.get("covered_commits")
    if not (isinstance(covered, dict) and covered):
        emit("RED", f"C-PROC: {name}: covered_commits block absent (must map tree path -> commit sha)")

    newest_covered_ts = None
    newest_work_ts = None
    for tree, sha in covered.items():
        tree_abs = tree if os.path.isabs(tree) else os.path.join(ROOT, tree)
        if not os.path.isdir(tree_abs):
            emit("UNEVALUABLE", f"C-PROC: covered tree {tree} not found on disk -- probe cannot look")
        ok, _ = _git(tree_abs, "cat-file", "-e", f"{sha}^{{commit}}")
        if not ok:
            emit("RED", f"C-PROC: {name}: covered commit {sha[:12]} does not exist in {tree} "
                        "(unverifiable coverage claim)")
        cts = _commit_time(tree_abs, sha)
        wok, head = _git(tree_abs, "log", "-1", "--format=%ct", "HEAD")
        if cts is None or not wok or not head.isdigit():
            emit("UNEVALUABLE", f"C-PROC: git could not read timestamps in {tree} -- env failure")
        newest_covered_ts = max(newest_covered_ts or 0, cts)
        newest_work_ts = max(newest_work_ts or 0, int(head))

    lag_h = (newest_work_ts - newest_covered_ts) / 3600.0
    if lag_h > GRACE_HOURS:
        emit("RED", f"C-PROC: work commits run {lag_h:.1f}h ahead of the newest covered commit "
                    f"(> {GRACE_HOURS}h grace) -- the visible process record has fallen behind; "
                    f"refresh the public issues and write a new process-visibility receipt")

    # (e) receipt-schema v2 (gh issue #15, frozen 2026-07-02): a receipt
    # at/after the cutover must carry a delegation block naming who BUILT
    # and who VERIFIED the work behind each cited issue -- staying current
    # (a)-(d) is not the same as staying attributable. Grandfathered below
    # the cutover: existence rules (a)-(d) apply unchanged, no block needed.
    ts = data.get("ts")
    if not (isinstance(ts, str) and re.match(r"^\d{8}T\d{6}Z$", ts)):
        m = RECEIPT_TS_RE.search(name)
        ts = m.group(1) if m else None
    if ts is not None and ts >= DELEGATION_CUTOVER_TS:
        delegation = data.get("delegation")
        if not (isinstance(delegation, dict) and delegation):
            emit("RED", f"C-PROC: {name}: receipt at/after cutover ({ts}) carries no delegation "
                        "block (invalid_process_receipt_without_delegation)")
        for issue_ref, entry in delegation.items():
            ok_entry = (isinstance(entry, dict)
                        and isinstance(entry.get("built_by"), str) and entry["built_by"].strip()
                        and isinstance(entry.get("verified_by"), str) and entry["verified_by"].strip())
            if not ok_entry:
                emit("RED", f"C-PROC: {name}: delegation entry {issue_ref!r} missing/empty "
                            "built_by or verified_by (invalid_process_receipt_without_delegation)")

    pr_note = ("no open PRs" if open_prs == "none-open"
               else f"{len(open_prs)} open PR(s) all within review grace")
    emit("GREEN", f"C-PROC CHK satisfied by {name}: {len(urls)} public issue URL(s) cited, {pr_note}, "
                  f"covered commits verified in {len(covered)} tree(s), work-vs-coverage lag "
                  f"{max(lag_h, 0.0):.1f}h <= {GRACE_HOURS}h grace (docs/domains/governance/authority/GOAL.md sec 13: the board, "
                  f"not the operator, detects process drift)")


if __name__ == "__main__":
    main()
