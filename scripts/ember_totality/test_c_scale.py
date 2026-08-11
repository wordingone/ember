#!/usr/bin/env python3
"""test_c_scale.py — STATUS PROBE for Ember goal condition C-SCALE (the APEX).

Registry text: docs/spec/conditions-v1.md §4.2 C-SCALE. R: the self-modification
gain demonstrated at a non-toy operating point reached by measured growth from
the owned seed, such that BOTH hold — (i) dense-undismissable (capability-per-
compute strictly above the 6·N·D dense scaling-law PROJECTION at matched
active-compute, excess outside noise, C8 deletion collapses it) and (ii)
scale-credible (>3B floor, reached via W1 pretrain-scale + W2 finetune-scale
compute COLLAPSES — never a VRAM fit, never hardware escalation, never a
borrowed base).

CHK (verbatim contract this probe enforces): a scale-credibility receipt
records {operating_capability_point (>3e9), W1:{measured_tokens_to_base,
projected_dense_tokens_to_base, token_bill_collapse_ratio>1,
growth_lineage_from_cbase_seed, no_borrowed_weights_load_bearing=true},
W2:{native_finetune_mechanism_id, per_update_cost_at_scale,
free_cognitive_mode_transition_receipt, no_borrowed_base=true},
measured_flops_to_capability, projected_dense_flops_to_capability,
capability_per_compute_ratio>1, contribution_deletion_collapses_excess=true,
active_working_set_bytes <= device floor}. Ratios are RE-DERIVED from the
receipt's own numerator/denominator (1% tolerance) — a claimed ratio that does
not re-derive is self-refuting, never trusted. A memory-fit-only receipt is
`invalid_memory_fit_as_scale_affordability`.

Receipt search surface: receipts/**/ *scale-credibility*.json, *c-scale*.json,
*cscale*.json (this pattern set is part of the probe contract; a receipt that
wants to satisfy C-SCALE lands on it).

DISCIPLINE: status probe — always exits 0, prints exactly ONE line, decides
every branch by reading real bytes on disk, hardcodes no verdict. Three-valued
per docs/authority/GOAL.md §4.1: RED / GREEN / UNEVALUABLE(env). Receipt-absent is RED
(satisfying artifact genuinely ABSENT — the probe looked and the answer is
no), never UNEVALUABLE; UNEVALUABLE is reserved for the probe being unable to
look at all.
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lane14_common import resolve_in_tree  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT)
    if p
]  # legacy secondary root candidate dropped -- dead under this repo root
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

INVALID_TOKENS = [
    "toy_scale_not_undismissable",
    "invalid_fixed_scale_convenience",
    "invalid_hardware_exit_ramp",
    "invalid_memory_fit_as_scale_affordability",
    "invalid_borrowed_base_as_owned_scale",
]

SCALE_FLOOR_PARAMS = 3e9   # dense-undismissable floor (registry §2b: sociological, pinned)
RATIO_TOL = 0.01           # claimed ratio must re-derive within 1%


def emit(color, reason):
    print(f"{color} {reason}")
    sys.exit(0)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _ratio_ok(claimed, numerator, denominator):
    """claimed > 1 AND claimed re-derives as numerator/denominator within tol."""
    if not (_num(claimed) and _num(numerator) and _num(denominator)):
        return False, "ratio fields non-numeric"
    if denominator <= 0:
        return False, "ratio denominator <= 0"
    if claimed <= 1:
        return False, f"ratio {claimed} not > 1 (no collapse/excess)"
    derived = numerator / denominator
    if abs(derived - claimed) > RATIO_TOL * max(abs(derived), abs(claimed)):
        return False, f"claimed ratio {claimed} does not re-derive ({derived:.6g}) -- self-refuting"
    return True, ""


def check_candidate(data: dict) -> "tuple[bool, str]":
    """Return (passes, first-failure-reason) for one receipt object."""
    op = data.get("operating_capability_point")
    if not _num(op) or op <= SCALE_FLOOR_PARAMS:
        return False, (f"operating_capability_point={op!r} not a number > {SCALE_FLOOR_PARAMS:.0e} "
                       "(toy scale is not undismissable)")

    w1 = data.get("W1") or data.get("w1") or {}
    if not isinstance(w1, dict):
        return False, "W1 block absent (pretrain-scale wall unmeasured)"
    ok, why = _ratio_ok(w1.get("token_bill_collapse_ratio"),
                        w1.get("projected_dense_tokens_to_base"),
                        w1.get("measured_tokens_to_base"))
    if not ok:
        return False, f"W1 token-bill collapse fails: {why}"
    if not w1.get("growth_lineage_from_cbase_seed"):
        return False, "W1 growth_lineage_from_cbase_seed absent (not grown from the owned seed)"
    if w1.get("no_borrowed_weights_load_bearing") is not True:
        return False, "W1 no_borrowed_weights_load_bearing != true (owned is absolute)"

    w2 = data.get("W2") or data.get("w2") or {}
    if not isinstance(w2, dict):
        return False, "W2 block absent (finetune-scale wall unmeasured)"
    if not (isinstance(w2.get("native_finetune_mechanism_id"), str)
            and w2["native_finetune_mechanism_id"].strip()):
        return False, "W2 native_finetune_mechanism_id absent"
    if not (_num(w2.get("per_update_cost_at_scale")) and w2["per_update_cost_at_scale"] > 0):
        return False, "W2 per_update_cost_at_scale absent/non-positive"
    mode_receipt = w2.get("free_cognitive_mode_transition_receipt")
    if not (isinstance(mode_receipt, str) and mode_receipt.strip()):
        return False, "W2 free_cognitive_mode_transition_receipt absent"
    if resolve_in_tree(mode_receipt, ROOT) is None:
        return False, (f"W2 free_cognitive_mode_transition_receipt {mode_receipt!r} does not "
                       "resolve in-tree (unreachable evidence, lane-14 reachability)")
    if w2.get("no_borrowed_base") is not True:
        return False, "W2 no_borrowed_base != true"

    ok, why = _ratio_ok(data.get("capability_per_compute_ratio"),
                        data.get("projected_dense_flops_to_capability"),
                        data.get("measured_flops_to_capability"))
    if not ok:
        return False, f"capability-per-compute excess fails: {why}"

    if data.get("contribution_deletion_collapses_excess") is not True:
        return False, ("contribution_deletion_collapses_excess != true (the excess is not "
                       "deletion-bound to the self-modification gain, C8 linkage unproven)")

    aws = data.get("active_working_set_bytes")
    floor = data.get("device_working_set_floor_bytes")
    if not (_num(aws) and aws > 0 and _num(floor) and floor > 0 and aws <= floor):
        return False, (f"active_working_set_bytes={aws!r} vs device floor={floor!r}: both must be "
                       "positive numbers with active <= floor (governed fit, no hardware escalation)")

    return True, ""


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-SCALE: state root not found under any known layout -- "
                            "probe cannot look (env), not a finding")
    receipts_dir = os.path.join(ROOT, "receipts")
    if not os.path.isdir(receipts_dir):
        emit("UNEVALUABLE", f"C-SCALE: receipts dir absent at {receipts_dir} -- probe cannot look")

    found = set()
    for pat in ("*scale-credibility*.json", "*c-scale*.json", "*cscale*.json"):
        found.update(glob.glob(os.path.join(receipts_dir, "**", pat), recursive=True))
    candidates = sorted(found)
    if not candidates:
        emit("RED", "C-SCALE: no scale-credibility receipt under receipts/ "
                    "(patterns *scale-credibility*/*c-scale*/*cscale*) -> the apex artifact is "
                    "genuinely ABSENT. Honest boot state: W1 (owned >3e9 base affordable) and W2 "
                    "(native in-loop adaptation at scale) both unbroken; keystone C-BASE unmet "
                    "upstream. A memory-fit probe would not change this "
                    "(invalid_memory_fit_as_scale_affordability).")

    failures = []
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
        ok, why = check_candidate(data)
        if ok:
            emit("GREEN",
                 f"C-SCALE CHK satisfied by {name}: operating point "
                 f"{data['operating_capability_point']:.3g} params > 3e9 floor; W1 token-bill "
                 f"collapse {data['W1' if 'W1' in data else 'w1']['token_bill_collapse_ratio']}x "
                 f"re-derived, grown from the owned seed, no borrowed weights; W2 native "
                 f"finetune mechanism receipted in-tree; capability-per-compute "
                 f"{data['capability_per_compute_ratio']}x above the 6ND dense projection, "
                 f"re-derived; C8 deletion collapses the excess; active working set within the "
                 f"device floor.")
        failures.append(f"{name}: {why}")

    emit("RED", f"C-SCALE: {len(candidates)} candidate receipt(s) present but NONE satisfy the "
                f"CHK -> {failures[:3]}")


if __name__ == "__main__":
    main()
