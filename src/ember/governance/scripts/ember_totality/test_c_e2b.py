#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_c_e2b.py — STATUS PROBE for Ember goal condition C-E2B.

Registry text: docs/domains/governance/spec/conditions-v1.md §4.2 C-E2B. R: the from-scratch owned
core (no borrowed weights load-bearing) beats Gemma-E2B-swapped-into-Ember's-
own-seat on BOTH legs at matched governed budget, with the paired protocol
frozen BEFORE any verdict: (i) Ember-work (verified, transferring, deletion-
surviving gains where E2B-in-the-same-seat does not) and (ii) founder-likeness
(runs its own event stream, initiates+completes work with receipts, answers
when addressed — measurably better than E2B in the same seat). Does NOT count:
one leg only; a comparison not paired in Ember's own harness/worlds/budget; a
borrowed/quantized core as the Ember side. Past the 2026-06-22 forcing date a
shortfall is a MEASURED-DISTANCE receipt and the loop continues — such a
receipt is protocol-compliant but the condition stays RED (unmet), because the
R is SURPASS, not report.

CHK enforced here: a paired surpass receipt records BOTH legs at matched
budget with the owned-core identity — legs.ember_work + legs.founder_likeness
each carrying numeric owned_core_score and e2b_score (owned > e2b re-derived
numerically, never a bare boolean), matched_budget with per-arm budgets EQUAL,
owned_core_identity with no_borrowed_weights=true and quantized=false, and
protocol_frozen_ref resolving in-tree with its freeze ts strictly BEFORE the
receipt ts. OR a measured-distance receipt naming the remaining gap (rendered
RED with the gap quoted).

Receipt search surface: receipts/**/ *e2b*.json (contract pattern).

DISCIPLINE: status probe — always exits 0, one line, real bytes decide, no
hardcoded verdict. RED / GREEN / UNEVALUABLE(env); receipt-absent is RED.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# issue2015 exact-local-import:src/ember/governance/scripts/ember_totality/_lane14_common.py
import importlib.util as _ember_43fbe346bdd606d4_importlib
import sys as _ember_43fbe346bdd606d4_sys
from pathlib import Path as _ember_43fbe346bdd606d4_Path
_ember_43fbe346bdd606d4_path = _ember_43fbe346bdd606d4_Path(__file__).resolve().parent.joinpath('_lane14_common.py')
if not _ember_43fbe346bdd606d4_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_totality/_lane14_common.py')
_ember_43fbe346bdd606d4_aliases = ('_ember_issue2015_43fbe346bdd606d4', '_lane14_common', 'src.ember.governance.scripts.ember_totality._lane14_common')
_ember_43fbe346bdd606d4_existing = []
for _ember_43fbe346bdd606d4_alias in _ember_43fbe346bdd606d4_aliases:
    _ember_43fbe346bdd606d4_candidate = _ember_43fbe346bdd606d4_sys.modules.get(_ember_43fbe346bdd606d4_alias)
    if _ember_43fbe346bdd606d4_candidate is not None and all(_ember_43fbe346bdd606d4_candidate is not item for item in _ember_43fbe346bdd606d4_existing):
        _ember_43fbe346bdd606d4_existing.append(_ember_43fbe346bdd606d4_candidate)
if len(_ember_43fbe346bdd606d4_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_totality/_lane14_common.py')
if _ember_43fbe346bdd606d4_existing:
    _ember_43fbe346bdd606d4_module = _ember_43fbe346bdd606d4_existing[0]
    _ember_43fbe346bdd606d4_observed = getattr(_ember_43fbe346bdd606d4_module, '__file__', None)
    if _ember_43fbe346bdd606d4_observed is None or _ember_43fbe346bdd606d4_Path(_ember_43fbe346bdd606d4_observed).resolve() != _ember_43fbe346bdd606d4_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_totality/_lane14_common.py')
else:
    _ember_43fbe346bdd606d4_spec = _ember_43fbe346bdd606d4_importlib.spec_from_file_location('_ember_issue2015_43fbe346bdd606d4', _ember_43fbe346bdd606d4_path)
    if _ember_43fbe346bdd606d4_spec is None or _ember_43fbe346bdd606d4_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_totality/_lane14_common.py')
    _ember_43fbe346bdd606d4_module = _ember_43fbe346bdd606d4_importlib.module_from_spec(_ember_43fbe346bdd606d4_spec)
    for _ember_43fbe346bdd606d4_alias in _ember_43fbe346bdd606d4_aliases:
        _ember_43fbe346bdd606d4_prior = _ember_43fbe346bdd606d4_sys.modules.get(_ember_43fbe346bdd606d4_alias)
        if _ember_43fbe346bdd606d4_prior is not None and _ember_43fbe346bdd606d4_prior is not _ember_43fbe346bdd606d4_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_totality/_lane14_common.py')
        _ember_43fbe346bdd606d4_sys.modules[_ember_43fbe346bdd606d4_alias] = _ember_43fbe346bdd606d4_module
    try:
        _ember_43fbe346bdd606d4_spec.loader.exec_module(_ember_43fbe346bdd606d4_module)
    except BaseException:
        for _ember_43fbe346bdd606d4_alias in _ember_43fbe346bdd606d4_aliases:
            if _ember_43fbe346bdd606d4_sys.modules.get(_ember_43fbe346bdd606d4_alias) is _ember_43fbe346bdd606d4_module:
                _ember_43fbe346bdd606d4_sys.modules.pop(_ember_43fbe346bdd606d4_alias, None)
        raise
for _ember_43fbe346bdd606d4_alias in _ember_43fbe346bdd606d4_aliases:
    _ember_43fbe346bdd606d4_prior = _ember_43fbe346bdd606d4_sys.modules.get(_ember_43fbe346bdd606d4_alias)
    if _ember_43fbe346bdd606d4_prior is not None and _ember_43fbe346bdd606d4_prior is not _ember_43fbe346bdd606d4_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_totality/_lane14_common.py')
    _ember_43fbe346bdd606d4_sys.modules[_ember_43fbe346bdd606d4_alias] = _ember_43fbe346bdd606d4_module
resolve_in_tree = getattr(_ember_43fbe346bdd606d4_module, 'resolve_in_tree')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_totality/_lane14_common.py  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT)
    if p
]  # legacy secondary root candidate dropped -- dead under this repo root
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

INVALID_TOKENS = ["invalid_e2b_unpaired", "invalid_single_leg_surpass"]
LEGS = ("ember_work", "founder_likeness")
_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


def emit(color, reason):
    print(f"{color} {reason}")
    sys.exit(0)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _norm_ts(ts):
    return re.sub(r"[^0-9A-Za-z]", "", ts or "")


def check_paired_surpass(data: dict) -> "tuple[bool, str]":
    legs = data.get("legs")
    if not isinstance(legs, dict):
        return False, "legs block absent"
    present = [l for l in LEGS if isinstance(legs.get(l), dict)]
    if len(present) < 2:
        return False, (f"only {present or 'no'} leg(s) present -- a one-leg comparison is "
                       "invalid_single_leg_surpass by construction")
    for leg in LEGS:
        row = legs[leg]
        own, e2b = row.get("owned_core_score"), row.get("e2b_score")
        if not (_num(own) and _num(e2b)):
            return False, (f"leg {leg}: owned_core_score/e2b_score not both numeric -- "
                           "EVIDENCE-IN-RECEIPT requires the numbers, a boolean is not admissible")
        if not own > e2b:
            return False, (f"leg {leg}: owned {own} does not surpass e2b {e2b} "
                           "(re-derived from the receipt's own numbers)")

    mb = data.get("matched_budget")
    if not isinstance(mb, dict):
        return False, "matched_budget block absent (not paired in Ember's own budget)"
    own_b, e2b_b = mb.get("owned_arm"), mb.get("e2b_arm")
    if not (_num(own_b) and _num(e2b_b) and own_b == e2b_b and own_b > 0):
        return False, (f"matched_budget owned_arm={own_b!r} e2b_arm={e2b_b!r}: must be equal "
                       "positive numbers (matched governed budget)")

    ident = data.get("owned_core_identity")
    if not isinstance(ident, dict) or not str(ident.get("id", "")).strip():
        return False, "owned_core_identity absent"
    if ident.get("no_borrowed_weights") is not True:
        return False, "owned_core_identity.no_borrowed_weights != true"
    if ident.get("quantized") is not False:
        return False, ("owned_core_identity.quantized != false (a quantized core as the Ember "
                       "side does NOT count)")

    frozen = data.get("protocol_frozen_ref")
    if not (isinstance(frozen, str) and frozen.strip()):
        return False, "protocol_frozen_ref absent (paired protocol not frozen before verdict)"
    on_disk = resolve_in_tree(frozen, ROOT)
    if on_disk is None:
        return False, f"protocol_frozen_ref {frozen!r} does not resolve in-tree"
    fr_m = _TS_RE.search(os.path.basename(on_disk))
    fr_ts = fr_m.group(1) if fr_m else None
    own_ts = _norm_ts(data.get("ts"))
    if not (fr_ts and own_ts and fr_ts < own_ts):
        return False, (f"protocol freeze ts {fr_ts!r} is not strictly before receipt ts "
                       f"{own_ts!r} -- frozen-before-verdict unproven")
    return True, ""


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-E2B: state root not found under any known layout -- probe cannot look")
    receipts_dir = os.path.join(ROOT, "receipts")
    if not os.path.isdir(receipts_dir):
        emit("UNEVALUABLE", f"C-E2B: receipts dir absent at {receipts_dir} -- probe cannot look")

    candidates = sorted(glob.glob(os.path.join(receipts_dir, "**", "*e2b*.json"), recursive=True))
    if not candidates:
        emit("RED", "C-E2B: no paired-surpass or measured-distance receipt under receipts/ "
                    "(pattern *e2b*) -> artifact genuinely ABSENT; the milestone is live until "
                    "met or retired by name (forcing date past, loop continues)")

    failures = []
    distance = None
    for rp in candidates:
        name = os.path.basename(rp)
        try:
            with open(rp, "r", encoding="utf-8") as fh:
                raw = fh.read()
            data = json.loads(raw)
        except Exception as exc:
            failures.append(f"{name}: unreadable ({exc})")
            continue
        if data.get("_synthetic_control_fixture"):
            failures.append(f"{name}: synthetic control fixture, never evidence")
            continue
        lowered = raw.lower()
        hit = [t for t in INVALID_TOKENS if t in lowered]
        if hit:
            failures.append(f"{name}: invalid-token present {hit}")
            continue

        rtype = data.get("receipt_type") or data.get("verdict") or ""
        if rtype == "e2b_measured_distance" or data.get("remaining_gap"):
            gap = data.get("remaining_gap")
            if isinstance(gap, str) and gap.strip():
                distance = (name, gap)
            else:
                failures.append(f"{name}: measured-distance receipt without a named remaining_gap")
            continue

        ok, why = check_paired_surpass(data)
        if ok:
            legs = data["legs"]
            emit("GREEN",
                 f"C-E2B CHK satisfied by {name}: BOTH legs surpass at matched governed budget "
                 f"(ember_work {legs['ember_work']['owned_core_score']} > "
                 f"{legs['ember_work']['e2b_score']}; founder_likeness "
                 f"{legs['founder_likeness']['owned_core_score']} > "
                 f"{legs['founder_likeness']['e2b_score']}), owned-core identity "
                 f"unborrowed+unquantized, protocol frozen before verdict (in-tree ref)")
        failures.append(f"{name}: {why}")

    if distance:
        emit("RED", f"C-E2B: measured-distance receipt {distance[0]} is protocol-compliant but "
                    f"the condition is SURPASS, not report -- remaining gap: {distance[1][:200]} "
                    "(loop continues)")
    emit("RED", f"C-E2B: {len(candidates)} candidate receipt(s) present but none is a valid "
                f"paired surpass or measured-distance record -> {failures[:3]}")


if __name__ == "__main__":
    main()
