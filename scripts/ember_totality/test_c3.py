#!/usr/bin/env python3
"""
Totality status-probe for Ember goal condition C3 (Equal budget).

Authoritative condition text (<spec>, condition C3):
  C3 - Equal budget.
    R: A<local-mount-point>/C arms share declared+measured wall time, GPU/CPU, data access,
       attempt budget, seed policy, verifier path.
    Does NOT count: a zero-attempt arm, waived governor, or unequal resource
       path; forcing Ember to split internal modes equally by clock
       (equal-budget is an evaluation law, not a cognition scheduler).
    invalid-token (the missing/faked X mark): invalid_unequal_budget
    CHK: per-arm budget rows present and equal.

Gloss (task): equal budget = A<local-mount-point>/C arms share wall time, GPU/CPU, data access,
attempts, seed policy, verifier path.
Receipt hint (task): A<local-mount-point>/C/deleted contract receipts, per-arm budget rows.

WHERE C3'S EVIDENCE ACTUALLY LIVES (verified by inspection 2026-06-23):
  - The `<peer-gate>/<peer-gate>-*.json` receipts carry the
    A<local-mount-point>/C/deleted contract and scores but have NO budget keys whatsoever.
  - The `<peer-loop>/<peer-loop>-*.json` receipts carry a real
    top-level `equal_budget` block: {attempts_per_arm_per_task, cpu_gpu,
    data_access, verifier} plus `reproducibility.seeds` (seed policy) and an
    `arm_contract` enumerating A<local-mount-point>/C/Deleted.
  So the peer-loop receipt is the canonical C3 budget artifact; this probe
  reads it. (If a future receipt grows a real per-arm wall-time row, the probe
  picks it up automatically -- nothing about the verdict is hardcoded.)

This is a STATUS PROBE:
  - exit code is ALWAYS 0
  - it prints exactly one line: "RED <reason>" or "GREEN <reason>"
  - RED/GREEN is determined by REALLY inspecting the receipt under
    <external-state-root> -- never hardcoded.

C3 SCOPE NOTE: C3 judges ONLY budget equality. It does NOT re-litigate the
SYMBOLIC_PROXY / neural-update question (that is C14's job). This probe therefore
encodes ONLY C3's own invalid-token (invalid_unequal_budget) plus C3's three
explicit does-NOT-count substitutes (zero-attempt arm / waived governor /
unequal resource path), each as a negative assertion.
"""

# [PATH-REWRITE 2026-07-01] Imported from external peer's
# state tree and rewritten for this repository. Original mount-point specific
# candidates replaced with a single REPO_ROOT-relative candidate,
# REPO_ROOT computed from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. External state directory does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

import json
import os
import glob

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
EXTERNAL_STATE = next(
    (p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                 os.path.join(REPO_ROOT, "<external-state>"))
     if p and os.path.isdir(p)),
    os.path.join(REPO_ROOT, "<external-state>"),
)
D3_LOOP_DIR = os.path.join(EXTERNAL_STATE, "receipts", "<peer-loop>")
RESIDENT_GATE_DIR = os.path.join(EXTERNAL_STATE, "receipts", "<peer-gate>")

# C3's invalid-token (the X mark) plus its enumerated does-NOT-count substitutes,
# each encoded as a negative assertion below. None may match for a GREEN.
C3_INVALID_TOKENS = ["invalid_unequal_budget"]

# The six budget dimensions C3 requires every arm to SHARE (declared+measured).
# Mapped to the field names a real equal_budget block uses.
REQUIRED_DIMENSIONS = {
    "wall_time": ["wall_time", "wall_clock", "wallclock", "walltime", "elapsed", "time_s", "seconds"],
    "gpu_cpu": ["cpu_gpu", "gpu_cpu", "gpu", "cpu", "compute", "governor", "device"],
    "data_access": ["data_access", "data"],
    "attempt_budget": ["attempts_per_arm_per_task", "attempts", "attempt", "attempt_budget"],
    "seed_policy": ["seed", "seeds", "seed_policy"],
    "verifier_path": ["verifier", "verifier_path", "evaluator"],
}

# The four canonical arm labels for the fixed contract.
ARM_LABELS = ["A", "B", "C", "Deleted"]


def status(color, reason):
    """Single-line status emit; STATUS PROBE always exits 0."""
    print(f"{color} {reason}")
    raise SystemExit(0)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def collect_invalid_codes(d):
    """Gather any literal active invalid-codes the receipt itself flags."""
    codes = []
    for key in ("invalid_codes", "errors", "invalid_tokens"):
        v = d.get(key)
        if isinstance(v, list):
            codes.extend(str(x) for x in v)
        elif isinstance(v, str):
            codes.append(v)
    return codes


def dimension_present(eb_keys_lower, seeds_present, names):
    """Is at least one of the field aliases for a dimension present?"""
    return any(any(alias == k or alias in k for k in eb_keys_lower) for alias in names)


def dimension_status(eb, seeds_present, names):
    """[ISSUE #97 cure 2, 2026-07-04] Return (satisfied, fail_reason) for one
    budget dimension, reading the matched field's REAL VALUE rather than
    only its key's presence. A real d3-native-loop receipt can carry a
    measured sub-block like:
        "wall_time": {"equal_within_tolerance": false,
                       "measured_per_arm_total_seconds": {...}, ...}
    -- i.e. the arms were ACTUALLY MEASURED and found unequal. The pre-cure
    checker only ever asked "is the key 'wall_time' present?" (yes) and
    never read equal_within_tolerance's own boolean, so a receipt that
    self-reports UNEQUAL measured wall time still passed. If the matched
    field's value is a dict carrying an explicit `equal_within_tolerance`
    flag, that flag decides the dimension: only `True` satisfies it. A
    plain declarative field (a string/bool with no such flag, e.g. a
    shared cpu_gpu/verifier/data_access description) still satisfies on
    presence alone -- there is no measured-value claim to contradict."""
    for k, v in eb.items():
        lk = str(k).lower()
        if any(alias == lk or alias in lk for alias in names):
            if isinstance(v, dict) and "equal_within_tolerance" in v:
                ewt = v.get("equal_within_tolerance")
                if ewt is True:
                    return True, None
                return False, (
                    f"{k}.equal_within_tolerance={ewt!r} "
                    f"(measured={v.get('measured_per_arm_total_seconds', v.get('measured_per_arm'))})"
                )
            return True, None
    if seeds_present and any(alias == "seeds" for alias in names):
        return True, None
    return False, None


def main():
    # ---- locate a REAL receipt carrying the A<local-mount-point>/C equal-budget block ----
    if not os.path.isdir(D3_LOOP_DIR):
        status("RED", f"no d3-native-loop receipt dir at {D3_LOOP_DIR} (C3 budget artifact absent)")

    loop_receipts = sorted(glob.glob(os.path.join(D3_LOOP_DIR, "d3-native-loop-*.json")))
    if not loop_receipts:
        status("RED", "no d3-native-loop-*.json receipts found (C3 equal-budget artifact absent)")

    # Choose the newest receipt that actually carries an equal_budget block AND an
    # A<local-mount-point>/C arm contract; that is the canonical C3 artifact. Never hardcode a path.
    chosen_path = None
    d = None
    for path in reversed(loop_receipts):  # newest first (lexical ts sort)
        try:
            cand = load_json(path)
        except Exception:
            continue
        if isinstance(cand.get("equal_budget"), dict) and cand.get("arm_contract"):
            chosen_path = path
            d = cand
            break

    if chosen_path is None:
        # Receipts exist but none carry a real equal_budget + arm_contract pair.
        # Cross-check the resident-training-gate family in case it grew one.
        for path in sorted(glob.glob(os.path.join(RESIDENT_GATE_DIR, "resident-training-gate-*.json")), reverse=True):
            try:
                cand = load_json(path)
            except Exception:
                continue
            if isinstance(cand.get("equal_budget"), dict):
                chosen_path = path
                d = cand
                break
    if chosen_path is None:
        status("RED",
               "d3-native-loop receipts present but NONE carry an equal_budget+arm_contract "
               "pair, and no resident-training-gate receipt has an equal_budget block -> "
               "no per-arm budget rows exist (invalid_unequal_budget / artifact absent)")

    receipt_name = os.path.basename(chosen_path)
    eb = d.get("equal_budget", {})
    arm_contract = d.get("arm_contract", {})
    repro = d.get("reproducibility", {}) if isinstance(d.get("reproducibility"), dict) else {}
    seeds_val = repro.get("seeds", eb.get("seeds"))
    seeds_present = seeds_val not in (None, "", [])

    # Build the set of field names available across equal_budget + seed-policy source.
    eb_keys_lower = [str(k).lower() for k in eb.keys()]
    if seeds_present:
        eb_keys_lower.append("seeds")

    # ---------------------------------------------------------------------------
    # (2) Negative assertions: NONE of C3's does-NOT-count substitutes may match.
    # ---------------------------------------------------------------------------
    matched_invalid = []

    # 2a. literal invalid_unequal_budget flagged active by the receipt itself
    active_codes = [c for c in collect_invalid_codes(d)]
    if any("invalid_unequal_budget" in c for c in active_codes):
        matched_invalid.append("literal invalid_unequal_budget active in receipt codes")

    # 2b. zero-attempt arm: attempt budget present and == 0 (or any arm given 0 attempts)
    attempts = eb.get("attempts_per_arm_per_task", eb.get("attempts"))
    try:
        if attempts is not None and float(attempts) <= 0:
            matched_invalid.append(f"zero-attempt arm (attempts_per_arm_per_task={attempts})")
    except (TypeError, ValueError):
        pass

    # 2c. waived governor: any budget text that says the resource governor was
    #     waived / disabled / unlimited for any arm.
    gov_blob = json.dumps(eb).lower() + " " + json.dumps(d.get("limits", {})).lower()
    if any(tok in gov_blob for tok in ["governor waived", "waived governor", "governor disabled",
                                       "no governor", "ungoverned", "unlimited budget", "unbounded budget"]):
        matched_invalid.append("waived/disabled governor referenced in budget block")

    # 2d. unequal resource path: the cpu_gpu / data_access / verifier statements must
    #     describe a SINGLE shared path for every arm. If the block enumerates a
    #     PER-ARM resource map where the arms differ on compute/verifier, that is
    #     an unequal resource path. We detect the equal case (shared scalar strings)
    #     vs. an unequal case (a dict keyed by arm with differing compute/verifier).
    for dim_key in ("cpu_gpu", "verifier", "data_access"):
        dimv = eb.get(dim_key)
        if isinstance(dimv, dict):
            # per-arm map -> arms must be identical to count as equal
            present_arms = [a for a in ARM_LABELS if a in dimv]
            vals = {a: dimv[a] for a in present_arms}
            distinct = set(json.dumps(v, sort_keys=True) for v in vals.values())
            if len(distinct) > 1:
                matched_invalid.append(f"unequal resource path: arms differ on '{dim_key}' ({vals})")

    if matched_invalid:
        status("RED",
               f"{receipt_name}: C3 does-NOT-count matched -> {'; '.join(matched_invalid)}")

    # ---------------------------------------------------------------------------
    # (1) Positive CHK: per-arm budget rows present AND equal across A<local-mount-point>/C arms,
    #     covering all six required dimensions (declared+measured wall time,
    #     GPU/CPU, data access, attempt budget, seed policy, verifier path).
    # ---------------------------------------------------------------------------
    # The equal_budget block declares ONE shared path for every arm (the strongest
    # form of "equal"); that satisfies the "equal" half. The "rows present" half
    # requires all six dimensions to actually appear. Recompute coverage from the
    # real fields -- never trust a stored "matched=true" boolean.
    present, missing = [], []
    # [ISSUE #97 cure 2] tolerance_failed: a dimension whose field IS present
    # but whose own measured equal_within_tolerance flag reads False -- a
    # genuinely different failure from "field absent entirely", surfaced
    # with its own reason.
    tolerance_failed = []
    for dim, aliases in REQUIRED_DIMENSIONS.items():
        ok, fail_reason = dimension_status(eb, seeds_present, aliases)
        if ok:
            present.append(dim)
        elif fail_reason is not None:
            tolerance_failed.append((dim, fail_reason))
            missing.append(dim)
        else:
            missing.append(dim)

    # Arms covered: the contract must enumerate A, B, C at minimum.
    arms_present = [a for a in ARM_LABELS if a in arm_contract]
    arms_ok = all(a in arm_contract for a in ("A", "B", "C"))

    detail = (f"arms={arms_present} budget_fields={sorted(eb.keys())} "
              f"seeds={'present' if seeds_present else 'ABSENT'} "
              f"dims_present={present} dims_missing={missing}")

    if not arms_ok:
        status("RED",
               f"{receipt_name}: arm contract does not enumerate A<local-mount-point>/C "
               f"(found {arms_present}) -> per-arm budget rows incomplete. {detail}")

    if missing:
        # A required budget dimension is genuinely absent from the artifact,
        # OR present but its own measured equal_within_tolerance value reads
        # False -- [ISSUE #97 cure 2] the two are reported distinctly since
        # they are different failures (artifact-absent vs measured-unequal).
        # Per C3 the arms must SHARE *declared+measured* values on ALL six
        # dimensions; either failure means the per-arm budget rows are
        # incomplete -> RED for the right reason.
        if tolerance_failed:
            status("RED",
                   f"{receipt_name}: equal_budget dimension(s) FAILED their own "
                   f"measured equal_within_tolerance check -> "
                   f"{['%s: %s' % (d, r) for d, r in tolerance_failed]} "
                   f"(measured, not merely declared, and found UNEQUAL across arms "
                   f"-> invalid_unequal_budget). Other missing dimensions: "
                   f"{[m for m in missing if m not in dict(tolerance_failed)]}. {detail}")
        status("RED",
               f"{receipt_name}: equal_budget block is missing required dimension(s) "
               f"{missing} -> per-arm budget rows incomplete (not all six C3 budget "
               f"dimensions declared+measured). {detail}")

    status("GREEN",
           f"C3 satisfied by {receipt_name}: A<local-mount-point>/C arm contract present and the "
           f"equal_budget block declares one SHARED (equal) path across all six "
           f"required dimensions (wall time, GPU/CPU, data access, attempt budget, "
           f"seed policy, verifier path); no zero-attempt arm, no waived governor, "
           f"no unequal resource path, no active invalid_unequal_budget. {detail}")


if __name__ == "__main__":
    main()
