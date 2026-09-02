#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""check_disconfirmation_triggers.py -- Program-level disconfirmation triggers per
conditions-v1.md sec 4.2, made machine-evaluable (gh issue #94 C-DISC, phase 2; schema
frozen by maintainer rulings R1-R7, phase-1 dossier).

Conditions-v1.md sec 4.2 (live authority; archived pre-2026-07-06 at docs/domains/governance/archive/goal/goal-archive.md)
names three hinges, each carrying a disconfirmation predicate: EARNED_GROWTH (2 consecutive
NOT-earned growth-rung attempts), B2_BOOTSTRAP (3 consecutive BOOTSTRAP_FAIL B-rung attempts),
H0_CEILING (the L1-L5 lever ladder fully resolved with the composed stack still under the
3.3x shatter bar). "A trigger with no evaluator is prose" (conditions-v1.md's own words) --
this script, run via disconfirmation_leg.py's dual-source verdict wrapper and re-invoked on
every board run, IS the standing evaluator the conditions call for (R1: the dangling citation
to experimentation-v1.md sec 6, whose own T1/T2/T3 cadence does something else entirely --
claim/board-flip/GPU-spend adversarial review, not a disconfirmation tally -- is a maintainer
text amendment, not code owed here).

[2026-07-10 NOTE: Per gh issue #729, tally receipts landing 2026-07-10 onward. rung1
(2026-07-03 receipt: cbase-grow-live-live-20260703T053225Z.json) and rung2 (2026-07-10
completion, dated later in that day) predate the feed start — the emitter-side contract was
formalized post-hoc. Both historical rungs EARNED per their completion receipts; the unwritten
tallies do not affect streak math either way. This checker watches forward from the landing date.]

Per-hinge tally rule (R3): attempts are ordered chronologically WITHIN the hinge's own receipt
family (rung number never partitions the streak -- the hinge is program-grain); an attempt is
included only if its own receipt says `evaluable: true` (UNEVALUABLE/crashed runs are SKIPPED --
never break the streak, never count toward it); `consecutive_fail_streak` is the TRAILING run of
evaluable-FAIL attempts. A receipt is recognized as belonging to a hinge's tally ONLY by its own
`receipt_type` field, never by directory location alone (R6: a stray bootstrap-falsifier
selftest receipt, `receipt_type=bootstrap_falsifier_selftest`, is structurally excluded from the
B2_BOOTSTRAP tally even if it were misplaced inside the bootstrap-rung directory).

H0_CEILING (R2) is NOT a consecutive-attempt hinge -- it is a single state check: are all five
L1-L5 levers resolved (KEPT/PARKED/KILLED) AND is the composed multiplier still under 3.3x. The
ladder table at docs/spec/h0-residual-lever-prereg-v1.md carries no structured per-lever
resolution field today (its Kill-condition prose can describe a FUTURE conditional outcome --
e.g. L5's "<1.15x at h2048 -> FP8 PARKED" -- that a naive keyword search would misread as a
CURRENT status), so this checker does not parse that prose for KEPT/PARKED/KILLED tokens.
Instead it looks for an explicit sidecar, docs/spec/h0-lever-status.json (a NEW convention
introduced here, not previously established), mapping each L<n> to KEPT/PARKED/KILLED; if the
sidecar is absent or any lever is unresolved, `all_levers_resolved` is conservatively False --
matching today's true state honestly (no lever has actually been resolved yet) and never risking
a false-positive trigger from a prose misparse. The composed multiplier is read from
docs/spec/feasibility-envelope-v1.md's own bolded `measured **N.NNx**` marker.

A fired trigger is compliant (not a violation) iff an override object
(receipts/escalation/override-<hinge>-<date>.json, presence+shape only, content never judged --
R7) or a properly-shaped escalation object
(receipts/escalation/disconfirmation-<hinge>-<date>.json, fields frozen by R4: hinge, predicate,
firing_receipt_refs, ts, git_anchor, amendment_proposal) exists. Unlike C-MILE, a fired hinge is
NOT automatically a violation -- sec 8's own text is "the system may not continue past a fired
trigger AS IF IT HAD NOT FIRED," i.e. the violation is silently continuing unacknowledged, not
the firing itself. Fire history is permanent (R7): an override returns the CHK to GREEN, but the
fire stays recorded in the attempts data -- it is never erased.

DISCIPLINE: prints one verdict line matched by disconfirmation_leg.py's verdict_regex, writes a
receipt of its own evaluation (every evaluation is itself receipted per conditions-v1.md sec 4.2),
exit 0=PASS (no unacknowledged fire) / 1=FAIL (>=1 hinge fired with no escalation/override).
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

GROWTH_RUNG_DIR = "receipts/growth-rung-attempts"
B2_BOOTSTRAP_DIR = "receipts/bootstrap-rung"
ESCALATION_DIR = "receipts/escalation"
H0_LEVER_PREREG = "docs/spec/h0-residual-lever-prereg-v1.md"
FEASIBILITY_ENVELOPE = "docs/spec/feasibility-envelope-v1.md"
H0_LEVER_STATUS_SIDECAR = "docs/spec/h0-lever-status.json"

GROWTH_RUNG_RECEIPT_TYPE = "growth_rung_attempt"
B2_BOOTSTRAP_RECEIPT_TYPE = "b2_bootstrap_attempt"

_H0_LADDER_ROW_RE = re.compile(r"^\|\s*L(\d)\s*\|")
_COMPOSED_MULTIPLIER_RE = re.compile(r"measured \*\*([\d.]+)\s*×\*\*|measured \*\*([\d.]+)x\*\*")

_ESCALATION_FIELDS = ("hinge", "predicate", "firing_receipt_refs", "ts", "git_anchor", "amendment_proposal")

EARNED_GROWTH_THRESHOLD = 2
B2_BOOTSTRAP_THRESHOLD = 3
H0_CEILING_BAR = 3.3


class ParseError(Exception):
    pass


def _utc_ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _list_json_files(dirpath):
    if not os.path.isdir(dirpath):
        return []
    return sorted(os.path.join(dirpath, fn) for fn in os.listdir(dirpath) if fn.endswith(".json"))


def _consecutive_fail_streak(attempts, fail_pred):
    """attempts: chronologically sorted dicts, each carrying 'evaluable' and enough fields for
    fail_pred. Returns (streak, refs) for the TRAILING run of evaluable-fail attempts;
    non-evaluable attempts are skipped without breaking the streak."""
    streak = 0
    refs = []
    for a in reversed(attempts):
        if not a.get("evaluable", False):
            continue
        if fail_pred(a):
            streak += 1
            refs.append(a["_ref"])
        else:
            break
    refs.reverse()
    return streak, refs


def _load_hinge_receipts(root, dirpath, receipt_type):
    files = _list_json_files(os.path.join(root, dirpath))
    attempts = []
    for path in files:
        try:
            d = _load_json(path)
        except Exception:
            continue
        if d.get("receipt_type") != receipt_type:
            continue  # structurally excluded by class -- e.g. a stray falsifier-selftest receipt
        d = dict(d)
        d["_ref"] = os.path.relpath(path, root)
        attempts.append(d)
    attempts.sort(key=lambda a: a.get("ts", ""))
    return attempts


def compute_earned_growth(root):
    attempts = _load_hinge_receipts(root, GROWTH_RUNG_DIR, GROWTH_RUNG_RECEIPT_TYPE)
    streak, refs = _consecutive_fail_streak(attempts, lambda a: a.get("verdict") == "NOT_EARNED")
    trigger_fired = streak >= EARNED_GROWTH_THRESHOLD
    return {
        "hinge": "EARNED_GROWTH",
        "attempts_seen": len(attempts),
        "consecutive_fail_streak": streak,
        "threshold": EARNED_GROWTH_THRESHOLD,
        "trigger_fired": trigger_fired,
        "firing_receipt_refs": refs if trigger_fired else [],
    }


def compute_b2_bootstrap(root):
    attempts = _load_hinge_receipts(root, B2_BOOTSTRAP_DIR, B2_BOOTSTRAP_RECEIPT_TYPE)
    streak, refs = _consecutive_fail_streak(attempts, lambda a: a.get("bootstrap_pass") is False)
    trigger_fired = streak >= B2_BOOTSTRAP_THRESHOLD
    return {
        "hinge": "B2_BOOTSTRAP",
        "attempts_seen": len(attempts),
        "consecutive_fail_streak": streak,
        "threshold": B2_BOOTSTRAP_THRESHOLD,
        "trigger_fired": trigger_fired,
        "firing_receipt_refs": refs if trigger_fired else [],
    }


def compute_h0_ceiling(root):
    prereg_path = os.path.join(root, H0_LEVER_PREREG)
    feas_path = os.path.join(root, FEASIBILITY_ENVELOPE)

    lever_ids = set()
    if os.path.isfile(prereg_path):
        with open(prereg_path, encoding="utf-8") as f:
            for line in f:
                m = _H0_LADDER_ROW_RE.match(line)
                if m:
                    lever_ids.add(int(m.group(1)))

    composed_multiplier = None
    if os.path.isfile(feas_path):
        with open(feas_path, encoding="utf-8") as f:
            text = f.read()
        m = _COMPOSED_MULTIPLIER_RE.search(text)
        if m:
            composed_multiplier = float(m.group(1) or m.group(2))

    sidecar_path = os.path.join(root, H0_LEVER_STATUS_SIDECAR)
    lever_status = {}
    sidecar_present = os.path.isfile(sidecar_path)
    if sidecar_present:
        try:
            lever_status = _load_json(sidecar_path)
        except Exception:
            lever_status = {}

    resolved_terms = {"KEPT", "PARKED", "KILLED"}
    all_levers_resolved = bool(lever_ids) and len(lever_ids) == 5 and all(
        lever_status.get(f"L{n}") in resolved_terms for n in sorted(lever_ids)
    )
    trigger_fired = bool(
        all_levers_resolved and composed_multiplier is not None and composed_multiplier < H0_CEILING_BAR
    )
    return {
        "hinge": "H0_CEILING",
        "lever_ids_found": sorted(lever_ids),
        "lever_status_sidecar_present": sidecar_present,
        "all_levers_resolved": all_levers_resolved,
        "composed_multiplier": composed_multiplier,
        "threshold": H0_CEILING_BAR,
        "trigger_fired": trigger_fired,
        "firing_receipt_refs": (
            [os.path.relpath(prereg_path, root), os.path.relpath(feas_path, root)]
            if trigger_fired else []
        ),
    }


def _find_object(root, hinge, prefix):
    dirpath = os.path.join(root, ESCALATION_DIR)
    if not os.path.isdir(dirpath):
        return None, None
    want = f"{prefix}{hinge.lower()}-"
    for fn in sorted(os.listdir(dirpath)):
        if fn.startswith(want) and fn.endswith(".json"):
            path = os.path.join(dirpath, fn)
            try:
                d = _load_json(path)
            except Exception:
                continue
            return os.path.relpath(path, root), d
    return None, None


def evaluate_hinge(root, state):
    hinge = state["hinge"]
    if not state["trigger_fired"]:
        return {**state, "compliant": True, "reason": "unmet"}

    override_ref, _ = _find_object(root, hinge, "override-")
    if override_ref:
        return {**state, "compliant": True, "reason": "override", "override_ref": override_ref}

    escalation_ref, escalation_obj = _find_object(root, hinge, "disconfirmation-")
    if escalation_ref and escalation_obj is not None and all(
        k in escalation_obj for k in _ESCALATION_FIELDS
    ) and escalation_obj.get("amendment_proposal"):
        return {**state, "compliant": True, "reason": "escalated", "escalation_ref": escalation_ref}

    return {**state, "compliant": False, "reason": "fired_unacknowledged"}


def run():
    hinge_states = [
        evaluate_hinge(ROOT, compute_h0_ceiling(ROOT)),
        evaluate_hinge(ROOT, compute_earned_growth(ROOT)),
        evaluate_hinge(ROOT, compute_b2_bootstrap(ROOT)),
    ]
    fired = sum(1 for h in hinge_states if h["trigger_fired"])
    violations = [h["hinge"] for h in hinge_states if not h["compliant"]]
    exit_status = "FAIL" if violations else "PASS"

    ts = _utc_ts()
    receipt = {
        "receipt_type": "disconfirmation_evaluation",
        "ticket": "EMBER-TOTALITY-DISCONFIRMATION",
        "ts": ts,
        "hinges": hinge_states,
        "fired": fired,
        "violations": violations,
        "exit": exit_status,
    }
    receipts_dir = os.path.join(ROOT, "scripts", "ember_totality", "receipts-disconfirmation")
    os.makedirs(receipts_dir, exist_ok=True)
    receipt_path = os.path.join(receipts_dir, f"disconfirmation-eval-{ts}.json")
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)

    print(f"receipt: {receipt_path}")
    print(f"hinges=3  fired={fired}  violations={len(violations)}  exit={exit_status}")
    return 0 if exit_status == "PASS" else 1


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
