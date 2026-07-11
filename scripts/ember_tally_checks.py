"""ember_tally_checks.py — per-condition executable CHK registry (#337 §4.3).

Maps §4 condition-id -> check(nc_dir: str) -> ('pass'|'fail'|'not_executable', detail: str).

A condition returning 'not_executable' is classified as missing[] in the tally
with reason='chk_not_executable' — it never counts as implemented.

C-EFF and C-GROW have fully-executable checks today.
Every other §4 condition returns 'not_executable' with an honest reason.

C1..C55 (manifest rows) are not in this registry; the tally uses
validate_receipt (schema floor) for those and warns 'chk_not_executable'
when the id matches a registry stub.
"""

import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# C-EFF closure bar (goal line 73). The shatter criterion is a >=3.3x-COMPOUND
# speedup over the anchor such that the USEFUL base trains in <=1 governed day
# — NOT a self-referential throughput floor. The prior receipt
# ceff-closure-gate9-shatter-bf16ns5-20260623T132000Z.json claimed "SHATTER"
# with effective_days=0.9803 computed as K_floor/throughput (self-referential:
# K_floor ~= 0.97x a PRIOR achieved throughput), which is NOT
# useful_base_tokens / (sustained_tok_s * governed_seconds_per_day). That
# verdict is REPUDIATED (receipts/ceff-shatter-REPUDIATED-*.json). Valid C-EFF
# closure is now read ONLY from a ceff-RESOLVED-*.json receipt meeting the
# honest bar below.
# ---------------------------------------------------------------------------
K_FLOOR_TOK_S = 19190.52              # retained for import-compat; NOT the pass bar
GOVERNED_SECONDS_PER_DAY = 86400.0
SHATTER_COMPOUND_MIN = 3.3            # goal line 46: the real shatter criterion
SHATTER_EFF_DAYS_MAX = 1.0           # useful base must train in <=1 governed day
EFF_DAYS_TOL = 0.05                  # internal-consistency tolerance (5%)
VALID_VERDICTS = {"SHATTER", "PRICED_SCALEOUT_RESIDUAL"}


def chk_ceff(nc_dir: str) -> tuple[str, str]:
    """C-EFF: gate-9 efficiency-closure check (honest bar, goal line 73).

    Reads the latest receipts/ceff-RESOLVED-*.json. The prior
    ...-gate9-shatter-... receipt is REPUDIATED (self-referential
    effective_days = K_floor/throughput; 1.85x compound = 56% of the >=3.3x
    criterion) and is NOT consulted.

    Honest bar:
      - verdict in {SHATTER, PRICED_SCALEOUT_RESIDUAL}
      - receipt declares useful_base_tokens, sustained_tok_s, effective_days,
        compound_speedup_over_anchor, effective_days_basis
      - effective_days_basis == 'useful_base_tokens_div_governed_day'
        (rejects the self-referential K_floor/throughput definition)
      - internal consistency: effective_days ~= useful_base_tokens /
        (sustained_tok_s * 86400) within EFF_DAYS_TOL
      - SHATTER  => compound_speedup_over_anchor >= 3.3 AND effective_days <= 1.0
      - RESIDUAL => fields present + consistent (effective_days may exceed 1.0;
        an honestly-priced residual IS a valid closure per goal line 73)

    Returns ('pass', summary) or ('fail', failure_detail).
    """
    import glob

    receipts_dir = os.path.join(nc_dir, "receipts")
    resolved = sorted(glob.glob(os.path.join(receipts_dir, "ceff-RESOLVED-*.json")))
    if not resolved:
        return (
            "fail",
            "C-EFF RE-OPENED: no ceff-RESOLVED-*.json closure receipt. The prior "
            "gate9-shatter verdict is REPUDIATED (effective_days = K_floor/throughput "
            "is self-referential, not useful_base_tokens/(tok_s*86400); measured "
            "1.18x lever / 1.85x c03 stack = 56% of the >=3.3x shatter criterion). "
            "Valid closure: SHATTER (>=3.3x compound AND base trains in <=1 governed "
            "day) OR PRICED_SCALEOUT_RESIDUAL.",
        )

    receipt_path = resolved[-1]  # latest by stamp-sorted name
    try:
        with open(receipt_path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return ("fail", f"C-EFF RESOLVED receipt parse error ({os.path.basename(receipt_path)}): {e}")

    findings = []

    verdict = d.get("verdict")
    if verdict not in VALID_VERDICTS:
        findings.append(f"verdict={verdict!r} not in {sorted(VALID_VERDICTS)}")

    basis = d.get("effective_days_basis")
    if basis != "useful_base_tokens_div_governed_day":
        findings.append(
            f"effective_days_basis={basis!r} != 'useful_base_tokens_div_governed_day' "
            "(self-referential or undeclared basis rejected)"
        )

    ubt = d.get("useful_base_tokens")
    tok_s = d.get("sustained_tok_s")
    eff_days = d.get("effective_days")
    compound = d.get("compound_speedup_over_anchor")
    for name, val in (
        ("useful_base_tokens", ubt),
        ("sustained_tok_s", tok_s),
        ("effective_days", eff_days),
        ("compound_speedup_over_anchor", compound),
    ):
        if not isinstance(val, (int, float)):
            findings.append(f"{name} missing or non-numeric: {val!r}")

    # internal consistency (only when the numerics are present)
    if (
        isinstance(ubt, (int, float))
        and isinstance(tok_s, (int, float))
        and isinstance(eff_days, (int, float))
        and tok_s > 0
        and eff_days > 0
    ):
        recomputed = ubt / (tok_s * GOVERNED_SECONDS_PER_DAY)
        if abs(recomputed - eff_days) / eff_days > EFF_DAYS_TOL:
            findings.append(
                f"effective_days {eff_days} inconsistent with useful_base_tokens/"
                f"(sustained_tok_s*{int(GOVERNED_SECONDS_PER_DAY)}) = {recomputed:.4f}"
            )

    if verdict == "SHATTER":
        if isinstance(compound, (int, float)) and compound < SHATTER_COMPOUND_MIN:
            findings.append(
                f"SHATTER but compound_speedup_over_anchor {compound} "
                f"< {SHATTER_COMPOUND_MIN} (goal shatter criterion)"
            )
        if isinstance(eff_days, (int, float)) and eff_days > SHATTER_EFF_DAYS_MAX:
            findings.append(
                f"SHATTER but effective_days {eff_days} > {SHATTER_EFF_DAYS_MAX} "
                "(useful base does not train in one governed day)"
            )

    if findings:
        return ("fail", "; ".join(findings))

    return (
        "pass",
        f"verdict={verdict}, compound={compound}x, effective_days={eff_days}, "
        f"useful_base_tokens={ubt}, sustained_tok_s={tok_s} "
        f"(basis={basis}, receipt={os.path.basename(receipt_path)})",
    )


# ---------------------------------------------------------------------------
# C-GROW closure bar (goal §4.2 C-GROW). Two experiment versions share this gate:
#
#   v2 (FF-widening):    mechanism = "ff_widening_net2net"
#                        First-to-target FLOP comparison; 7 machine-checks.
#   v3 (depth-growth):   mechanism = "identity_layer_insertion_depth"
#                        Iso-FLOP eval-loss comparison; structural checks below.
#
# This gate is the single source of truth; experiments MUST conform to it.
# ---------------------------------------------------------------------------

# v2 legacy constants
CGROW_MECHANISM_V2 = "ff_widening_net2net"
CGROW_LOSS_DELTA_TOL_CEIL = 0.10   # max v2 preservation tolerance (nats)
CGROW_LOGIT_MAX_DIFF_CEIL = 1e-2   # v2 function-preservation ceiling
CGROW_FLOP_RATIO_MIN = 1.0
CGROW_RATIO_TOL = 0.05

# v3 constants
CGROW_MECHANISM_V3       = "identity_layer_insertion_depth"
CGROW_V3_LOGIT_CEIL      = 1e-5    # stricter: spec requires <1e-5 for depth op
CGROW_V3_LOSS_DELTA_CEIL = 1e-4    # essentially zero in float32
CGROW_V3_BUDGET_TOL      = 0.01    # ±1% FLOP budget adherence

CGROW_VALID_MECHANISMS   = {CGROW_MECHANISM_V2, CGROW_MECHANISM_V3}
CGROW_V3_SWEEP_MIN_ARMS = 2   # minimum receipts for a meaningful cross-arm sweep

# ---------------------------------------------------------------------------
# C-PORT closure bar (goal §4.2 C-PORT).
# ---------------------------------------------------------------------------
CPORT_VRAM_FRACTION_MAX = 0.80   # tighten-only ceiling: no CUDA fraction may exceed this

# ---------------------------------------------------------------------------
# C-ANAT closure bar (goal §4.2 C-ANAT).
# ---------------------------------------------------------------------------
CANAT_DOC_COUNT_MIN = 16    # goal requires exactly 16 anatomy docs
CANAT_DOC_BYTES_MIN = 500   # each doc must have real content, not a stub placeholder


def _is_num(x) -> bool:
    """True for a real number, excluding bool (True/False are ints in Python)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _chk_cgrow_v2(d: dict, receipt_name: str) -> tuple[str, str]:
    """v2 (FF-widening) receipt checks — original 7 machine-checks."""
    findings = []
    seed = d.get("seed") or {}
    grow = d.get("grow_step") or {}
    pc   = grow.get("preservation_check") or {}
    arm_w = d.get("arm_w") or {}
    arm_s = d.get("arm_s") or {}
    fc    = d.get("flop_comparison") or {}
    ds    = d.get("dataset") or {}

    # 1. mechanism
    if grow.get("mechanism") != CGROW_MECHANISM_V2:
        findings.append(
            f"grow_step.mechanism={grow.get('mechanism')!r} != {CGROW_MECHANISM_V2!r}")

    # 2. preservation
    if pc.get("pass") is not True:
        findings.append(f"preservation_check.pass={pc.get('pass')!r} (must be True)")
    ld, tol, lmd = pc.get("loss_delta_nats"), pc.get("tolerance_nats"), pc.get("logit_max_diff")
    if not _is_num(ld) or not _is_num(tol):
        findings.append(f"preservation loss_delta_nats/tolerance_nats non-numeric: {ld!r}/{tol!r}")
    else:
        if tol > CGROW_LOSS_DELTA_TOL_CEIL:
            findings.append(f"preservation tolerance_nats {tol} > ceiling {CGROW_LOSS_DELTA_TOL_CEIL}")
        if abs(ld) > tol:
            findings.append(f"preservation |loss_delta_nats| {abs(ld)} > tolerance {tol}")
    if not _is_num(lmd):
        findings.append(f"preservation logit_max_diff non-numeric: {lmd!r}")
    elif lmd > CGROW_LOGIT_MAX_DIFF_CEIL:
        findings.append(f"preservation logit_max_diff {lmd} > ceiling {CGROW_LOGIT_MAX_DIFF_CEIL}")

    # 3. both arms reached target
    if arm_w.get("reached_target") is not True:
        findings.append(f"arm_w.reached_target={arm_w.get('reached_target')!r} (must be True)")
    if arm_s.get("reached_target") is not True:
        findings.append(f"arm_s.reached_target={arm_s.get('reached_target')!r} (must be True)")

    # 4. target harder than seed
    tln, sfl = d.get("target_loss_nats"), seed.get("final_loss_nats")
    if not _is_num(tln) or not _is_num(sfl):
        findings.append(f"target_loss_nats/seed.final_loss_nats non-numeric: {tln!r}/{sfl!r}")
    elif not (tln < sfl):
        findings.append(f"target_loss_nats {tln} not < seed.final_loss_nats {sfl}")

    # 5. FLOP comparison
    wt  = fc.get("warmstart_total_flops")
    st  = fc.get("scratch_total_flops")
    ratio = fc.get("ratio_scratch_over_warmstart")
    awt = arm_w.get("flops_total")
    asf = arm_s.get("flops_scratch_to_target")
    if not all(_is_num(x) for x in (wt, st, ratio)):
        findings.append(f"flop_comparison non-numeric: warmstart={wt!r} scratch={st!r} ratio={ratio!r}")
    elif wt <= 0 or st <= 0:
        findings.append(f"flop_comparison non-positive: warmstart={wt} scratch={st}")
    else:
        if ratio <= CGROW_FLOP_RATIO_MIN:
            findings.append(f"ratio_scratch_over_warmstart {ratio} <= {CGROW_FLOP_RATIO_MIN}")
        recomputed = st / wt
        if abs(recomputed - ratio) / ratio > CGROW_RATIO_TOL:
            findings.append(f"ratio {ratio} inconsistent with scratch/warmstart = {recomputed:.4f}")
        if _is_num(awt) and abs(awt - wt) > max(1.0, 1e-6 * abs(wt)):
            findings.append(f"warmstart_total_flops {wt} != arm_w.flops_total {awt}")
        if _is_num(asf) and abs(asf - st) > max(1.0, 1e-6 * abs(st)):
            findings.append(f"scratch_total_flops {st} != arm_s.flops_scratch_to_target {asf}")
    if fc.get("verdict") != "FLOP_REDUCTION_CONFIRMED":
        findings.append(f"flop_comparison.verdict={fc.get('verdict')!r} != 'FLOP_REDUCTION_CONFIRMED'")

    # 6. dataset frozen
    if ds.get("frozen_before_arm_s") is not True:
        findings.append(f"dataset.frozen_before_arm_s={ds.get('frozen_before_arm_s')!r}")

    # 7. no invalid tokens
    inv = d.get("invalid_tokens_present")
    if inv != []:
        findings.append(f"invalid_tokens_present={inv!r} (must be [])")

    if findings:
        return ("fail", "; ".join(findings))
    return (
        "pass",
        f"mechanism={grow.get('mechanism')}, loss_delta_nats={ld}, logit_max_diff={lmd}, "
        f"flop_ratio={ratio}x, verdict={fc.get('verdict')} (receipt={receipt_name})",
    )


def _chk_cgrow_v3(d: dict, receipt_name: str) -> tuple[str, str]:
    """v3 (identity-layer depth) receipt checks — iso-FLOP eval-loss path.

    Structural checks (all conjunctive):
      1. grow_step.mechanism == 'identity_layer_insertion_depth'
      2. preservation_check.pass True; logit_max_diff < 1e-5; loss_delta_nats < 1e-4
      3. arm_w.total_flops and arm_s.total_flops both within ±1% of iso_flop.budget_b
      4. arm_w.total_flops == arm_w.seed_flops + arm_w.cont_flops (component tie)
      5. eval_batch_hash present and non-empty
      6. frozen_before_arm_s == True
      7. invalid_tokens_present == []
      8. verdict.result in {DEPTH_FLOP_REDUCTION_CONFIRMED, NO_DEPTH_FLOP_REDUCTION}
         and eval-loss inequality consistent with result
    """
    findings = []
    grow     = d.get("grow_step") or {}
    pc       = grow.get("preservation_check") or {}
    arm_w    = d.get("arm_w") or {}
    arm_s    = d.get("arm_s") or {}
    iso      = d.get("iso_flop") or {}
    verdict  = d.get("verdict") or {}

    # 1. mechanism
    if grow.get("mechanism") != CGROW_MECHANISM_V3:
        findings.append(
            f"grow_step.mechanism={grow.get('mechanism')!r} != {CGROW_MECHANISM_V3!r}")

    # 2. preservation
    if pc.get("pass") is not True:
        findings.append(f"preservation_check.pass={pc.get('pass')!r} (must be True)")
    lmd = pc.get("logit_max_diff")
    if not _is_num(lmd):
        findings.append(f"preservation logit_max_diff non-numeric: {lmd!r}")
    elif lmd >= CGROW_V3_LOGIT_CEIL:
        findings.append(
            f"preservation logit_max_diff {lmd} >= {CGROW_V3_LOGIT_CEIL} "
            "(depth surgery not function-preserving)")
    ld = pc.get("loss_delta_nats")
    if not _is_num(ld):
        findings.append(f"preservation loss_delta_nats non-numeric: {ld!r}")
    elif abs(ld) >= CGROW_V3_LOSS_DELTA_CEIL:
        findings.append(
            f"preservation loss_delta_nats {abs(ld)} >= {CGROW_V3_LOSS_DELTA_CEIL} "
            "(not approximately zero)")

    # 3. budget adherence ±1%
    budget_b  = iso.get("budget_b")
    wt = arm_w.get("total_flops")
    st = arm_s.get("total_flops")
    if not _is_num(budget_b) or budget_b <= 0:
        findings.append(f"iso_flop.budget_b missing or non-positive: {budget_b!r}")
    else:
        if not _is_num(wt):
            findings.append(f"arm_w.total_flops non-numeric: {wt!r}")
        elif abs(wt - budget_b) / budget_b > CGROW_V3_BUDGET_TOL:
            findings.append(
                f"arm_w.total_flops {wt} deviates from budget_b {budget_b} by "
                f"{abs(wt-budget_b)/budget_b*100:.1f}% > {CGROW_V3_BUDGET_TOL*100}%")
        if not _is_num(st):
            findings.append(f"arm_s.total_flops non-numeric: {st!r}")
        elif abs(st - budget_b) / budget_b > CGROW_V3_BUDGET_TOL:
            findings.append(
                f"arm_s.total_flops {st} deviates from budget_b {budget_b} by "
                f"{abs(st-budget_b)/budget_b*100:.1f}% > {CGROW_V3_BUDGET_TOL*100}%")

    # 4. component tie: arm_w.total == arm_w.seed_flops + arm_w.cont_flops
    sf = arm_w.get("seed_flops")
    cf = arm_w.get("cont_flops")
    if _is_num(wt) and _is_num(sf) and _is_num(cf):
        component_sum = sf + cf
        if abs(component_sum - wt) > max(1.0, 1e-6 * abs(wt)):
            findings.append(
                f"arm_w.total_flops {wt} != arm_w.seed_flops + arm_w.cont_flops = {component_sum}")

    # 5. eval_batch_hash present and non-empty
    ebh = d.get("eval_batch_hash")
    if not isinstance(ebh, str) or not ebh:
        findings.append(f"eval_batch_hash missing or empty: {ebh!r}")

    # 6. frozen_before_arm_s
    if d.get("frozen_before_arm_s") is not True:
        findings.append(
            f"frozen_before_arm_s={d.get('frozen_before_arm_s')!r} (must be True)")

    # 7. no invalid tokens
    inv = d.get("invalid_tokens_present")
    if inv != []:
        findings.append(f"invalid_tokens_present={inv!r} (must be [])")

    # 8. verdict consistency
    vr = verdict.get("result")
    wl = verdict.get("warmstart_final_eval_loss")
    sl = verdict.get("scratch_final_eval_loss")
    valid_results = {"DEPTH_FLOP_REDUCTION_CONFIRMED", "NO_DEPTH_FLOP_REDUCTION"}
    if vr not in valid_results:
        findings.append(f"verdict.result={vr!r} not in {sorted(valid_results)}")
    if _is_num(wl) and _is_num(sl):
        if vr == "DEPTH_FLOP_REDUCTION_CONFIRMED" and not (wl < sl):
            findings.append(
                f"verdict CONFIRMED but warmstart_eval {wl} >= scratch_eval {sl} "
                "(eval-loss inequality violated)")
        if vr == "NO_DEPTH_FLOP_REDUCTION" and wl < sl:
            findings.append(
                f"verdict NO_REDUCTION but warmstart_eval {wl} < scratch_eval {sl} "
                "(should be CONFIRMED)")
    else:
        findings.append(
            f"verdict eval losses non-numeric: warmstart={wl!r} scratch={sl!r}")

    if findings:
        return ("fail", "; ".join(findings))
    return (
        "pass",
        f"mechanism={grow.get('mechanism')}, preservation=logit_max_diff={lmd:.2e}/"
        f"loss_delta={ld:.2e}, budget_b={budget_b}, arm_w={wt}/arm_s={st} (±1%), "
        f"warmstart_eval={wl}/scratch_eval={sl}, result={vr} (receipt={receipt_name})",
    )


def chk_cgrow(nc_dir: str) -> tuple[str, str]:
    """C-GROW: measured function-preserving capacity-growth check (goal §4.2).

    Routes on grow_step.mechanism:
      'ff_widening_net2net'         → v2 path (first-to-target FLOP comparison)
      'identity_layer_insertion_depth' → v3 path (iso-FLOP eval-loss comparison)

    Reads the latest receipts/cgrow-receipt-*.json.
    Returns ('pass', summary) or ('fail', detail).
    """
    import glob

    receipts_dir = os.path.join(nc_dir, "receipts")
    found = sorted(glob.glob(os.path.join(receipts_dir, "cgrow-receipt-*.json")))
    if not found:
        return (
            "fail",
            "C-GROW OPEN: no cgrow-receipt-*.json receipt. Valid closure requires a "
            "MEASURED function-preserving grow step (ff_widening_net2net v2 or "
            "identity_layer_insertion_depth v3) with fewer FLOPs than from-scratch.",
        )

    receipt_path = found[-1]
    try:
        with open(receipt_path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return ("fail", f"C-GROW receipt parse error ({os.path.basename(receipt_path)}): {e}")

    mechanism = (d.get("grow_step") or {}).get("mechanism", "")
    name = os.path.basename(receipt_path)

    if mechanism == CGROW_MECHANISM_V2:
        return _chk_cgrow_v2(d, name)
    if mechanism == CGROW_MECHANISM_V3:
        return _chk_cgrow_v3(d, name)
    return (
        "fail",
        f"grow_step.mechanism={mechanism!r} not in {sorted(CGROW_VALID_MECHANISMS)} "
        "(unrecognized growth operator; from-scratch widening is invalid_fromscratch_widening_as_growth)",
    )


def chk_cgrow_v3_sweep(
    receipts: list[dict], names: list[str]
) -> tuple[str, str]:
    """Cross-arm v3 sweep: N receipts with distinct growth fractions f.

    Purpose: validate a set of v3 runs (e.g. f in {0.1, 0.25, 0.5}) as a
    coherent sweep before drawing cross-f conclusions.  Does NOT replace the
    single-receipt chk_cgrow path — use this ONLY when comparing multiple
    f-value receipts against each other.

    Checks (S0-S4, all conjunctive):
      S0. Each receipt individually passes _chk_cgrow_v3.
      S1. All receipts use mechanism = CGROW_MECHANISM_V3.
      S2. iso_flop.budget_b is IDENTICAL across all receipts (same total compute
          envelope for every f — the iso-FLOP invariant holds sweep-wide).
      S3. iso_flop.growth_fraction_f values are DISTINCT (no duplicate f).
      S4. eval_batch_hash discipline: receipts with different f values must either
          (a) have DISTINCT eval_batch_hash values, OR
          (b) both carry a non-empty 'shared_eval_batch_rationale' field.
          Reusing the same eval batch without documentation risks undocumented
          cross-arm evaluation leakage.

    Returns ('pass', summary) or ('fail', detail).
    """
    if not receipts:
        return ("fail", "sweep: empty receipt list")
    if len(receipts) < CGROW_V3_SWEEP_MIN_ARMS:
        return (
            "fail",
            f"sweep: {len(receipts)} receipt(s) supplied but "
            f"min={CGROW_V3_SWEEP_MIN_ARMS} required for a cross-arm comparison",
        )
    if len(receipts) != len(names):
        return (
            "fail",
            f"sweep: receipts len={len(receipts)} != names len={len(names)}",
        )

    findings = []

    # S0: each receipt must individually pass _chk_cgrow_v3
    for i, (d, name) in enumerate(zip(receipts, names)):
        status, detail = _chk_cgrow_v3(d, name)
        if status != "pass":
            findings.append(f"S0[{i}] individual-v3 FAIL ({name}): {detail}")

    # S1: all mechanisms must be v3
    non_v3 = [
        f"[{i}]={(d.get('grow_step') or {}).get('mechanism')!r}"
        for i, d in enumerate(receipts)
        if (d.get("grow_step") or {}).get("mechanism") != CGROW_MECHANISM_V3
    ]
    if non_v3:
        findings.append(f"S1 non-v3 mechanism(s) in sweep: {', '.join(non_v3)}")

    # S2: budget_b must be identical across all receipts
    budgets = [(d.get("iso_flop") or {}).get("budget_b") for d in receipts]
    valid_b = [b for b in budgets if _is_num(b) and b > 0]
    if len(valid_b) < len(receipts):
        missing = [i for i, b in enumerate(budgets) if not (_is_num(b) and b > 0)]
        findings.append(f"S2 missing/invalid budget_b in receipt(s) {missing}")
    elif len(set(valid_b)) > 1:
        findings.append(
            f"S2 budget_b inconsistent across sweep: {valid_b} "
            "(all f-arms must use the same iso-FLOP compute envelope)"
        )

    # S3: growth_fraction_f values must be distinct
    f_values = [(d.get("iso_flop") or {}).get("growth_fraction_f") for d in receipts]
    seen_f: dict = {}
    for i, fv in enumerate(f_values):
        if not _is_num(fv):
            findings.append(f"S3[{i}] missing/non-numeric growth_fraction_f: {fv!r}")
        elif fv in seen_f:
            findings.append(
                f"S3 duplicate growth_fraction_f={fv} in receipt[{seen_f[fv]}] "
                f"and receipt[{i}] (each sweep arm needs a distinct f)"
            )
        else:
            seen_f[fv] = i

    # S4: eval_batch_hash discipline across different f values
    hashes = [d.get("eval_batch_hash") for d in receipts]
    for i in range(len(receipts)):
        for j in range(i + 1, len(receipts)):
            fi = f_values[i] if _is_num(f_values[i]) else None
            fj = f_values[j] if _is_num(f_values[j]) else None
            if fi is None or fj is None or fi == fj:
                continue  # skip: unknown f or same f (S3 already catches duplicate-f)
            hi, hj = hashes[i], hashes[j]
            if isinstance(hi, str) and isinstance(hj, str) and hi == hj:
                # shared eval batch between different f arms — require documented rationale
                rat_i = receipts[i].get("shared_eval_batch_rationale") or ""
                rat_j = receipts[j].get("shared_eval_batch_rationale") or ""
                if not (rat_i and rat_j):
                    missing_rat = []
                    if not rat_i:
                        missing_rat.append(f"receipt[{i}] (f={fi})")
                    if not rat_j:
                        missing_rat.append(f"receipt[{j}] (f={fj})")
                    findings.append(
                        f"S4 eval_batch_hash reused between f={fi} and f={fj} "
                        f"without shared_eval_batch_rationale in: {', '.join(missing_rat)}"
                    )

    if findings:
        return ("fail", "; ".join(findings))

    f_sorted = sorted(seen_f.keys())
    b_str = f"{valid_b[0]:.3e}" if valid_b else "?"
    verdicts = [(d.get("verdict") or {}).get("result") for d in receipts]
    return (
        "pass",
        f"sweep {len(receipts)} arms f={f_sorted} budget_b={b_str} "
        f"verdicts={verdicts} (S0-S4 pass)",
    )


# ---------------------------------------------------------------------------
# C-PORT: device-adaptive governor + CPU-portability check
# ---------------------------------------------------------------------------

def chk_cport(nc_dir: str) -> tuple[str, str]:
    """C-PORT: device-adaptive governor + CPU-portability check (goal §4.2).

    Reads the latest receipts/portability-probe-*.json.

    Checks (all conjunctive):
      1. cpu_forward.ok == True   (non-primary device forward pass without crash)
      2. cpu_forward.error is None  (no error present alongside an ok=True claim)
      3. cpu_forward.device_used == 'cpu'  (confirms the non-primary target is CPU)
      4. adaptive_governor_cpu.device == 'cpu'
      5. adaptive_governor_cpu.vram_fraction key IS PRESENT and its value is null
         (VRAM is not applicable on CPU; any non-null value implies a hardcoded
         constant -> invalid_device_locked)
      6. adaptive_governor_cpu.total_mem_gib is numeric and > 0
         (runtime-queried system RAM total, not hardcoded)
      7. If adaptive_governor_cuda is present AND adaptive_governor_cuda_error is None:
         - vram_fraction is numeric and <= CPORT_VRAM_FRACTION_MAX (tighten-only)
         - total_mem_gib is numeric and > 0  (runtime-queried device total)
         - margin_gib is numeric and > 0

    Invalid-token rejected: 'invalid_device_locked'
    Returns ('pass', summary) or ('fail', detail).
    """
    import glob

    receipts_dir = os.path.join(nc_dir, "receipts")
    found = sorted(glob.glob(os.path.join(receipts_dir, "portability-probe-*.json")))
    if not found:
        return (
            "fail",
            "C-PORT OPEN: no portability-probe-*.json receipt. Valid closure requires "
            "a receipt with cpu_forward.ok=True (non-primary CPU forward pass without "
            "crash), an adaptive governor that queries device memory at runtime "
            "(total_mem_gib from live query, not hardcoded), vram_fraction=null on "
            "the CPU governor, and vram_fraction <= 0.80 on the CUDA governor "
            "(tighten-only). invalid_device_locked.",
        )

    receipt_path = found[-1]
    try:
        with open(receipt_path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return ("fail", f"C-PORT receipt parse error ({os.path.basename(receipt_path)}): {e}")

    findings = []

    cpu_fwd = d.get("cpu_forward") or {}

    # 1. cpu_forward.ok
    if cpu_fwd.get("ok") is not True:
        findings.append(
            f"cpu_forward.ok={cpu_fwd.get('ok')!r} (non-primary CPU forward pass "
            "failed or not executed; invalid_device_locked if no CPU path proved)")

    # 2. cpu_forward.error — must be None even when ok=True
    err = cpu_fwd.get("error")
    if err is not None:
        findings.append(
            f"cpu_forward.error={err!r} (error present despite ok claim; "
            "non-primary forward pass did not complete cleanly)")

    # 3. cpu_forward.device_used
    dev_used = cpu_fwd.get("device_used")
    if dev_used != "cpu":
        findings.append(
            f"cpu_forward.device_used={dev_used!r} != 'cpu' "
            "(non-primary portability target must be CPU)")

    cpu_gov = d.get("adaptive_governor_cpu") or {}

    # 4. adaptive_governor_cpu.device
    if cpu_gov.get("device") != "cpu":
        findings.append(
            f"adaptive_governor_cpu.device={cpu_gov.get('device')!r} != 'cpu'")

    # 5. vram_fraction on CPU governor: key must exist AND value must be None/null
    #    (JSON null -> Python None)
    if "vram_fraction" not in cpu_gov:
        findings.append(
            "adaptive_governor_cpu.vram_fraction field absent "
            "(must be present with value null — VRAM is not applicable on CPU)")
    elif cpu_gov["vram_fraction"] is not None:
        findings.append(
            f"adaptive_governor_cpu.vram_fraction={cpu_gov['vram_fraction']!r} "
            "must be null (VRAM not applicable on CPU; non-null implies a hardcoded "
            "constant -> invalid_device_locked)")

    # 6. adaptive_governor_cpu.total_mem_gib — runtime-queried RAM
    cpu_tmg = cpu_gov.get("total_mem_gib")
    if not _is_num(cpu_tmg) or cpu_tmg <= 0:
        findings.append(
            f"adaptive_governor_cpu.total_mem_gib={cpu_tmg!r} missing or "
            "non-positive (runtime-queried system RAM must be present and positive)")

    # 7. CUDA governor checks — conditional on CUDA being available
    cuda_gov = d.get("adaptive_governor_cuda")
    cuda_err = d.get("adaptive_governor_cuda_error")

    if cuda_gov is not None and cuda_err is None:
        cuda_vf  = cuda_gov.get("vram_fraction")
        cuda_tmg = cuda_gov.get("total_mem_gib")
        cuda_mgib = cuda_gov.get("margin_gib")

        if not _is_num(cuda_vf):
            findings.append(
                f"adaptive_governor_cuda.vram_fraction={cuda_vf!r} missing or "
                "non-numeric (CUDA governor must declare its vram_fraction)")
        elif cuda_vf > CPORT_VRAM_FRACTION_MAX:
            findings.append(
                f"adaptive_governor_cuda.vram_fraction {cuda_vf} > "
                f"{CPORT_VRAM_FRACTION_MAX} (invalid_device_locked: "
                "governor is not tighten-only; CUDA vram_fraction must be <= 0.80)")

        if not _is_num(cuda_tmg) or cuda_tmg <= 0:
            findings.append(
                f"adaptive_governor_cuda.total_mem_gib={cuda_tmg!r} missing or "
                "non-positive (runtime device total must be queried and positive)")

        if not _is_num(cuda_mgib) or cuda_mgib <= 0:
            findings.append(
                f"adaptive_governor_cuda.margin_gib={cuda_mgib!r} missing or "
                "non-positive")

    if findings:
        return ("fail", "; ".join(findings))

    cpu_tmg_str = f"{cpu_tmg:.1f}" if _is_num(cpu_tmg) else "?"
    cuda_str = ""
    if cuda_gov is not None and cuda_err is None:
        cuda_str = (
            f", cuda=fraction={cuda_gov.get('vram_fraction')}"
            f"/total_mem={cuda_gov.get('total_mem_gib'):.1f}GiB"
            f"/margin={cuda_gov.get('margin_gib')}GiB"
        )
    return (
        "pass",
        f"cpu_forward=ok elapsed={cpu_fwd.get('elapsed_s')}s "
        f"cpu_total_mem={cpu_tmg_str}GiB{cuda_str} "
        f"(receipt={os.path.basename(receipt_path)})",
    )


# ---------------------------------------------------------------------------
# C-ANAT: canonical anatomy doc set check (replaces the _not_executable stub)
# ---------------------------------------------------------------------------

def chk_canat(nc_dir: str) -> tuple[str, str]:
    """C-ANAT: canonical anatomy doc set check (goal §4.2 C-ANAT).

    Reads the latest receipts/ember-anatomy/c-anat-anatomy-set-completion-*.json.

    Checks (all conjunctive):
      1. Receipt file exists under receipts/ember-anatomy/
      2. doc_set is a list
      3. len(doc_set) >= CANAT_DOC_COUNT_MIN (16)
      4. Each entry has a non-empty string 'path' and a non-empty string 'sha256'
      5. Each doc path exists on disk (absolute, or resolved relative to nc_dir)
      6. Each doc file size >= CANAT_DOC_BYTES_MIN (500) bytes
         (real content, not a stub placeholder)

    Invalid-token rejected: 'invalid_anatomy_incomplete'
    Returns ('pass', summary) or ('fail', detail).
    """
    import glob

    anatomy_dir = os.path.join(nc_dir, "receipts", "ember-anatomy")
    found = sorted(
        glob.glob(
            os.path.join(anatomy_dir, "c-anat-anatomy-set-completion-*.json")
        )
    )
    if not found:
        return (
            "fail",
            "C-ANAT OPEN: no c-anat-anatomy-set-completion-*.json receipt under "
            "receipts/ember-anatomy/. Valid closure requires a receipt with a doc_set "
            f"of >= {CANAT_DOC_COUNT_MIN} SHA-bound anatomy docs, each present on disk "
            f"with >= {CANAT_DOC_BYTES_MIN} bytes of real content. "
            "invalid_anatomy_incomplete.",
        )

    receipt_path = found[-1]
    try:
        with open(receipt_path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return (
            "fail",
            f"C-ANAT receipt parse error ({os.path.basename(receipt_path)}): {e}",
        )

    findings = []

    doc_set = d.get("doc_set")
    if not isinstance(doc_set, list):
        return (
            "fail",
            f"C-ANAT receipt missing or invalid doc_set: got "
            f"{type(doc_set).__name__!r} (must be a list; "
            "invalid_anatomy_incomplete)",
        )

    if len(doc_set) < CANAT_DOC_COUNT_MIN:
        findings.append(
            f"doc_set has {len(doc_set)} entries, need >= {CANAT_DOC_COUNT_MIN} "
            "(invalid_anatomy_incomplete)"
        )

    for i, entry in enumerate(doc_set):
        if not isinstance(entry, dict):
            findings.append(f"doc_set[{i}] is not a dict: {entry!r}")
            continue

        path = entry.get("path")
        sha  = entry.get("sha256")

        if not isinstance(path, str) or not path:
            findings.append(
                f"doc_set[{i}].path missing or empty: {path!r}")
            continue   # can't check disk without a path

        if not isinstance(sha, str) or not sha:
            findings.append(
                f"doc_set[{i}].sha256 missing or empty for {path!r} "
                "(SHA-binding required; invalid_anatomy_incomplete)")

        # Resolve relative paths against nc_dir
        resolved = path if os.path.isabs(path) else os.path.join(nc_dir, path)

        if not os.path.isfile(resolved):
            findings.append(
                f"doc_set[{i}] not found on disk: {path!r} "
                "(invalid_anatomy_incomplete)")
        else:
            size = os.path.getsize(resolved)
            if size < CANAT_DOC_BYTES_MIN:
                findings.append(
                    f"doc_set[{i}] {path!r} has {size} bytes < "
                    f"{CANAT_DOC_BYTES_MIN} minimum (stub placeholder rejected; "
                    "invalid_anatomy_incomplete)")

    if findings:
        return ("fail", "; ".join(findings))

    return (
        "pass",
        f"{len(doc_set)} anatomy docs SHA-bound and present on disk with "
        f">= {CANAT_DOC_BYTES_MIN} bytes each "
        f"(receipt={os.path.basename(receipt_path)})",
    )


# ---------------------------------------------------------------------------
# Stubs for §4 conditions without executable checks yet
# ---------------------------------------------------------------------------

def _not_executable(reason: str):
    """Return a stub check function that always reports not_executable."""
    def _stub(nc_dir: str) -> tuple[str, str]:
        return ("not_executable", reason)
    return _stub


chk_cbase = _not_executable(
    "C-BASE: no checkpoint file with hashes + NC2 manifest yet; "
    "executable check requires owned checkpoint artifact"
)

chk_cm1 = _not_executable(
    "C(-1): no clear-packet receipt confirming api_spend_usd=0 yet; "
    "executable check requires clear-packet artifact"
)

chk_c0 = _not_executable(
    "C0: C14 PASS receipt not yet present; "
    "executable check requires C14 gate receipt predating loop receipts"
)

chk_cobs = _not_executable(
    "C-OBS: no adapter receipts binding real GOAL/ledger/receipts -> EmberWorldState; "
    "executable check requires real (not synthetic) adapter artifacts"
)

chk_ctally = _not_executable(
    "C-TALLY: pct=100 receipt not yet emitted; "
    "executable check requires tally receipt with pct=100 and missing[]=[]"
)


# ---------------------------------------------------------------------------
# Registry: §4 condition-id -> check function
# ---------------------------------------------------------------------------

REGISTRY: dict[str, callable] = {
    "C-EFF":   chk_ceff,
    "C-GROW":  chk_cgrow,
    "C-PORT":  chk_cport,
    "C-BASE":  chk_cbase,
    "C(-1)":   chk_cm1,
    "C0":      chk_c0,
    "C-OBS":   chk_cobs,
    "C-ANAT":  chk_canat,
    "C-TALLY": chk_ctally,
}


# ---------------------------------------------------------------------------
# Selftest: fabricated/weakened C-EFF receipt MUST be rejected
# ---------------------------------------------------------------------------

def _selftest():
    import tempfile
    import shutil

    failures = []
    tmpdir = tempfile.mkdtemp()
    receipts_dir = os.path.join(tmpdir, "receipts")
    os.makedirs(receipts_dir)

    def _consistent_eff_days(ubt, tok_s):
        return ubt / (tok_s * GOVERNED_SECONDS_PER_DAY)

    def _write_resolved(stamp, payload):
        # remove any prior RESOLVED files so each case is read in isolation
        import glob as _glob
        for old in _glob.glob(os.path.join(receipts_dir, "ceff-RESOLVED-*.json")):
            os.remove(old)
        path = os.path.join(receipts_dir, f"ceff-RESOLVED-{stamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    TOK_S = 19577.1

    # Case 0: the REPUDIATED gate9-shatter receipt present, NO RESOLVED -> fail.
    # (Confirms the over-claimed receipt is never consulted; C-EFF stays re-opened.)
    with open(os.path.join(
        receipts_dir,
        "ceff-closure-gate9-shatter-bf16ns5-20260623T132000Z.json",
    ), "w", encoding="utf-8") as f:
        json.dump({"verdict": "SHATTER", "sustained_tok_s_full_60M_run": 19577.1}, f)
    status, detail = chk_ceff(tmpdir)
    if status != "fail":
        failures.append(f"Case 0 FAIL: repudiated shatter receipt alone must NOT pass; got {status!r}: {detail}")

    # Case 1: SHATTER but compound 1.85 (< 3.3) -> fail (the repudiated magnitude).
    ubt = 1_500_000_000
    _write_resolved("20260623T180001Z", {
        "verdict": "SHATTER",
        "useful_base_tokens": ubt,
        "sustained_tok_s": TOK_S,
        "effective_days": _consistent_eff_days(ubt, TOK_S),
        "compound_speedup_over_anchor": 1.85,  # < 3.3
        "effective_days_basis": "useful_base_tokens_div_governed_day",
    })
    status, detail = chk_ceff(tmpdir)
    if status != "fail":
        failures.append(f"Case 1 FAIL: SHATTER compound 1.85 must fail; got {status!r}: {detail}")

    # Case 2: SHATTER with self-referential basis -> fail.
    _write_resolved("20260623T180002Z", {
        "verdict": "SHATTER",
        "useful_base_tokens": ubt,
        "sustained_tok_s": TOK_S,
        "effective_days": _consistent_eff_days(ubt, TOK_S),
        "compound_speedup_over_anchor": 3.5,
        "effective_days_basis": "K_floor_div_throughput",  # the smuggled definition
    })
    status, detail = chk_ceff(tmpdir)
    if status != "fail":
        failures.append(f"Case 2 FAIL: self-referential basis must fail; got {status!r}: {detail}")

    # Case 3: SHATTER with inconsistent effective_days -> fail.
    _write_resolved("20260623T180003Z", {
        "verdict": "SHATTER",
        "useful_base_tokens": ubt,
        "sustained_tok_s": TOK_S,
        "effective_days": 0.50,  # not ubt/(tok_s*86400) ~= 0.887
        "compound_speedup_over_anchor": 3.5,
        "effective_days_basis": "useful_base_tokens_div_governed_day",
    })
    status, detail = chk_ceff(tmpdir)
    if status != "fail":
        failures.append(f"Case 3 FAIL: inconsistent effective_days must fail; got {status!r}: {detail}")

    # Case 4: honest SHATTER (compound 3.5, eff_days<=1, correct basis, consistent) -> pass.
    _write_resolved("20260623T180004Z", {
        "verdict": "SHATTER",
        "useful_base_tokens": ubt,
        "sustained_tok_s": TOK_S,
        "effective_days": _consistent_eff_days(ubt, TOK_S),  # ~0.887
        "compound_speedup_over_anchor": 3.5,
        "effective_days_basis": "useful_base_tokens_div_governed_day",
    })
    status, detail = chk_ceff(tmpdir)
    if status != "pass":
        failures.append(f"Case 4 FAIL: honest SHATTER must pass; got {status!r}: {detail}")

    # Case 5: SHATTER but effective_days > 1.0 -> fail (base does not fit one day).
    ubt_big = 20_000_000_000
    _write_resolved("20260623T180005Z", {
        "verdict": "SHATTER",
        "useful_base_tokens": ubt_big,
        "sustained_tok_s": TOK_S,
        "effective_days": _consistent_eff_days(ubt_big, TOK_S),  # ~11.8
        "compound_speedup_over_anchor": 3.5,
        "effective_days_basis": "useful_base_tokens_div_governed_day",
    })
    status, detail = chk_ceff(tmpdir)
    if status != "fail":
        failures.append(f"Case 5 FAIL: SHATTER eff_days>1 must fail; got {status!r}: {detail}")

    # Case 6: honest PRICED_SCALEOUT_RESIDUAL (eff_days ~11.8 OK for residual) -> pass.
    _write_resolved("20260623T180006Z", {
        "verdict": "PRICED_SCALEOUT_RESIDUAL",
        "useful_base_tokens": ubt_big,
        "sustained_tok_s": TOK_S,
        "effective_days": _consistent_eff_days(ubt_big, TOK_S),
        "compound_speedup_over_anchor": 1.85,
        "effective_days_basis": "useful_base_tokens_div_governed_day",
    })
    status, detail = chk_ceff(tmpdir)
    if status != "pass":
        failures.append(f"Case 6 FAIL: honest priced residual must pass; got {status!r}: {detail}")

    shutil.rmtree(tmpdir, ignore_errors=True)

    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        raise SystemExit("EMBER_TALLY_CHECKS_SELFTEST: failures found")

    print("EMBER_TALLY_CHECKS_SELFTEST_PASS")


def _selftest_cgrow():
    """A fabricated/weakened C-GROW receipt MUST be rejected; an honest one passes.

    Schema = docs/cgrow-experiment-design-*.md §5 (warmstart arm_w vs scratch arm_s).
    """
    import tempfile
    import shutil
    import glob as _glob

    failures = []
    tmpdir = tempfile.mkdtemp()
    receipts_dir = os.path.join(tmpdir, "receipts")
    os.makedirs(receipts_dir)

    def _write(stamp, payload):
        for old in _glob.glob(os.path.join(receipts_dir, "cgrow-receipt-*.json")):
            os.remove(old)
        with open(os.path.join(receipts_dir, f"cgrow-receipt-{stamp}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def _honest():
        return {
            "ticket": "CGROW-RECEIPT",
            "ts": "20260628T000000Z",
            "seed": {
                "arch": {"H": 256, "ff": 1024, "L": 8, "seq": 512},
                "param_count_nonembed": 14000000, "param_count_total": 14500000,
                "token_budget": 200000000, "final_loss_nats": 4.50,
                "plateau_detected": True, "weight_hash_sha256": "seedhash",
                "component_manifest": {"layers": "h1", "embed": "h2", "head": "h3"},
            },
            "grow_step": {
                "mechanism": "ff_widening_net2net", "seed_ff": 1024, "grown_ff": 2048,
                "grown_arch": {"H": 256, "ff": 2048, "L": 8, "seq": 512},
                "grown_param_count_nonembed": 20000000, "grown_param_count_total": 20500000,
                "preservation_check": {
                    "seed_eval_loss": 4.50, "grown_eval_loss": 4.501,
                    "loss_delta_nats": 0.001, "logit_max_diff": 3e-6,
                    "pass": True, "tolerance_nats": 0.05,
                },
            },
            "target_loss_nats": 4.40,
            "arm_w": {
                "flops_seed": 3.0e17, "flops_grow_to_target": 3.0e17, "flops_total": 6.0e17,
                "steps_grow_to_target": 1000, "final_loss_nats": 4.39,
                "reached_target": True, "wall_s": 1800.0,
            },
            "arm_s": {
                "flops_scratch_to_target": 9.0e17, "steps_scratch_to_target": 1500,
                "final_loss_nats": 4.39, "reached_target": True, "wall_s": 2700.0,
            },
            "flop_comparison": {
                "warmstart_total_flops": 6.0e17, "scratch_total_flops": 9.0e17,
                "ratio_scratch_over_warmstart": 1.5, "flop_saving_pct": 33.3,
                "verdict": "FLOP_REDUCTION_CONFIRMED",
            },
            "step_comparison": {
                "warmstart_grow_steps": 1000, "scratch_steps": 1500,
                "ratio_scratch_over_warmstart_steps": 1.5,
            },
            "dataset": {
                "name": "wikitext-103", "split": "train",
                "hash_sha256": "dshash", "frozen_before_arm_s": True,
            },
            "governor": {"vram_fraction": 0.70, "margin_gib": 2.0, "decode_pacer": True},
            "invalid_tokens_present": [],
            "chk_cgrow_pass": True,
        }

    cases = []  # (label, mutate_fn_or_None, expect)
    cases.append(("Case 0 no receipt", "SKIP_WRITE", "fail"))
    cases.append(("Case 1 honest", lambda p: p, "pass"))
    cases.append(("Case 2 from-scratch mechanism",
                  lambda p: p["grow_step"].__setitem__("mechanism", "from_scratch_init") or p, "fail"))
    cases.append(("Case 3 preservation pass False",
                  lambda p: p["grow_step"]["preservation_check"].__setitem__("pass", False) or p, "fail"))
    cases.append(("Case 4 loss_delta over tol",
                  lambda p: p["grow_step"]["preservation_check"].__setitem__("loss_delta_nats", 0.5) or p, "fail"))
    cases.append(("Case 5 logit_max_diff over ceil",
                  lambda p: p["grow_step"]["preservation_check"].__setitem__("logit_max_diff", 0.5) or p, "fail"))
    cases.append(("Case 6 tolerance ceiling abuse",
                  lambda p: p["grow_step"]["preservation_check"].__setitem__("tolerance_nats", 0.5) or p, "fail"))
    cases.append(("Case 7 arm_w not reached",
                  lambda p: p["arm_w"].__setitem__("reached_target", False) or p, "fail"))
    cases.append(("Case 8 arm_s not reached",
                  lambda p: p["arm_s"].__setitem__("reached_target", False) or p, "fail"))
    cases.append(("Case 9 target not harder",
                  lambda p: p.__setitem__("target_loss_nats", 4.60) or p, "fail"))

    def _no_saving(p):
        p["arm_w"]["flops_total"] = 9.0e17
        p["arm_s"]["flops_scratch_to_target"] = 8.0e17
        p["flop_comparison"] = {
            "warmstart_total_flops": 9.0e17, "scratch_total_flops": 8.0e17,
            "ratio_scratch_over_warmstart": 0.889, "flop_saving_pct": -12.5,
            "verdict": "FLOP_REDUCTION_CONFIRMED",
        }
        return p
    cases.append(("Case 10 no FLOP saving", _no_saving, "fail"))

    cases.append(("Case 11 inconsistent ratio",
                  lambda p: p["flop_comparison"].__setitem__("ratio_scratch_over_warmstart", 3.0) or p, "fail"))
    cases.append(("Case 12 verdict wrong",
                  lambda p: p["flop_comparison"].__setitem__("verdict", "NO_FLOP_REDUCTION") or p, "fail"))

    def _totals_mismatch(p):
        p["flop_comparison"]["warmstart_total_flops"] = 7.0e17  # != arm_w.flops_total 6.0e17
        p["flop_comparison"]["ratio_scratch_over_warmstart"] = 9.0e17 / 7.0e17  # keep ratio self-consistent
        return p
    cases.append(("Case 13 totals mismatch arm_w", _totals_mismatch, "fail"))

    cases.append(("Case 14 dataset not frozen",
                  lambda p: p["dataset"].__setitem__("frozen_before_arm_s", False) or p, "fail"))
    cases.append(("Case 15 invalid tokens present",
                  lambda p: p.__setitem__("invalid_tokens_present", ["invalid_growth_unmeasured"]) or p, "fail"))

    import copy
    for i, (label, mut, expect) in enumerate(cases):
        if mut == "SKIP_WRITE":
            # leave receipts dir empty
            for old in _glob.glob(os.path.join(receipts_dir, "cgrow-receipt-*.json")):
                os.remove(old)
        else:
            payload = mut(copy.deepcopy(_honest()))
            _write(f"20260628T0001{i:02d}Z", payload)
        status, detail = chk_cgrow(tmpdir)
        if status != expect:
            failures.append(f"cgrow {label}: expected {expect!r}, got {status!r}: {detail}")

    shutil.rmtree(tmpdir, ignore_errors=True)

    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        raise SystemExit("EMBER_TALLY_CHECKS_CGROW_SELFTEST: failures found")

    print("EMBER_TALLY_CHECKS_CGROW_SELFTEST_PASS")


def _selftest_cgrow_v3():
    """Individual v3 receipt selftest: fabricated/weakened v3 receipts MUST be rejected.

    Uses chk_cgrow (the routing entry-point) so the mechanism-dispatch path is also
    exercised.  16 cases: 1 honest (must pass) + 15 mutations (must each fail).
    """
    import tempfile, shutil, copy as _copy
    import glob as _glob

    failures = []
    tmpdir = tempfile.mkdtemp()
    receipts_dir = os.path.join(tmpdir, "receipts")
    os.makedirs(receipts_dir)

    def _write(stamp, payload):
        for old in _glob.glob(os.path.join(receipts_dir, "cgrow-receipt-*.json")):
            os.remove(old)
        path = os.path.join(receipts_dir, f"cgrow-receipt-{stamp}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    # Component values matching the dry-run receipt (arm_w 0.99% off budget — passes ±1%).
    _BUDGET_B   = 3_156_787_200
    _SEED_FLOPS = 789_504_000
    _CONT_FLOPS = 2_336_022_528
    _TOTAL_W    = _SEED_FLOPS + _CONT_FLOPS  # = 3_125_526_528

    def _honest_v3():
        return {
            "ticket": "CGROW-V3-RECEIPT",
            "ts": "20260628T120000Z",
            "grow_step": {
                "mechanism": "identity_layer_insertion_depth",
                "seed_layers": 8, "grown_layers": 16, "growth_mode": "interleaved",
                "preservation_check": {
                    "seed_eval_loss": 4.50, "grown_eval_loss": 4.50,
                    "loss_delta_nats": 0.0, "logit_max_diff": 0.0,
                    "pass": True,
                    "tolerance_logit": 1e-5, "tolerance_loss_nats": 1e-4,
                },
            },
            "iso_flop": {
                "budget_b": _BUDGET_B,
                "growth_fraction_f": 0.25,
            },
            "eval_batch_hash": "e3b0c44298fc1c149afb4c8996fb924",
            "frozen_before_arm_s": True,
            "arm_w": {
                "seed_flops": _SEED_FLOPS,
                "cont_flops": _CONT_FLOPS,
                "total_flops": _TOTAL_W,
                "final_eval_loss_nats": 6.26,
            },
            "arm_s": {
                "total_flops": _BUDGET_B,
                "final_eval_loss_nats": 6.29,
            },
            "verdict": {
                "warmstart_final_eval_loss": 6.26,
                "scratch_final_eval_loss": 6.29,
                "margin_nats": 0.03,
                "result": "DEPTH_FLOP_REDUCTION_CONFIRMED",
                "speedup_sp": 0.01,
            },
            "invalid_tokens_present": [],
        }

    def _del_hash(p):
        p.pop("eval_batch_hash", None)
        return p

    def _arm_w_budget_fail(p):
        # 5% deviation — also violates component tie; both checks fire correctly
        p["arm_w"]["seed_flops"]  = 700_000_000
        p["arm_w"]["cont_flops"]  = 2_300_000_000
        p["arm_w"]["total_flops"] = 3_000_000_000
        return p

    def _arm_s_budget_fail(p):
        p["arm_s"]["total_flops"] = 3_000_000_000   # 4.96% off budget_b
        return p

    def _component_tie_fail(p):
        # total within ±1% of budget but != seed + cont
        p["arm_w"]["total_flops"] = 3_150_000_000   # 0.21% off -> passes budget
        # seed(789504000) + cont(2336022528) = 3125526528 != 3150000000 -> tie fails
        return p

    def _confirmed_but_warmstart_gte_scratch(p):
        p["verdict"]["warmstart_final_eval_loss"] = 6.30   # >= scratch 6.29
        p["verdict"]["result"] = "DEPTH_FLOP_REDUCTION_CONFIRMED"
        return p

    cases = [  # (label, mutate_fn_or_SKIP, expected_status)
        ("v3-C0 no receipt",                  "SKIP_WRITE",                                         "fail"),
        ("v3-C1 honest v3",                   lambda p: p,                                          "pass"),
        ("v3-C2 mechanism wrong",             lambda p: p["grow_step"].__setitem__(
                                                  "mechanism", "ff_widening_net2net") or p,         "fail"),
        ("v3-C3 preservation pass False",     lambda p: p["grow_step"]["preservation_check"]
                                                  .__setitem__("pass", False) or p,                "fail"),
        ("v3-C4 logit_max_diff at ceil",      lambda p: p["grow_step"]["preservation_check"]
                                                  .__setitem__("logit_max_diff", 1e-5) or p,       "fail"),
        ("v3-C5 logit_max_diff above ceil",   lambda p: p["grow_step"]["preservation_check"]
                                                  .__setitem__("logit_max_diff", 2e-5) or p,       "fail"),
        ("v3-C6 loss_delta_nats at ceil",     lambda p: p["grow_step"]["preservation_check"]
                                                  .__setitem__("loss_delta_nats", 1e-4) or p,      "fail"),
        ("v3-C7 arm_w budget >1%",            _arm_w_budget_fail,                                  "fail"),
        ("v3-C8 arm_s budget >1%",            _arm_s_budget_fail,                                  "fail"),
        ("v3-C9 component tie violated",      _component_tie_fail,                                 "fail"),
        ("v3-C10 eval_batch_hash missing",    _del_hash,                                           "fail"),
        ("v3-C11 eval_batch_hash empty str",  lambda p: p.__setitem__(
                                                  "eval_batch_hash", "") or p,                     "fail"),
        ("v3-C12 frozen_before_arm_s False",  lambda p: p.__setitem__(
                                                  "frozen_before_arm_s", False) or p,              "fail"),
        ("v3-C13 invalid_tokens non-empty",   lambda p: p.__setitem__(
                                                  "invalid_tokens_present", ["tok_A"]) or p,       "fail"),
        ("v3-C14 CONFIRMED but ws>=sc",       _confirmed_but_warmstart_gte_scratch,                "fail"),
        ("v3-C15 NO_REDUCTION but ws<sc",     lambda p: p["verdict"].__setitem__(
                                                  "result", "NO_DEPTH_FLOP_REDUCTION") or p,       "fail"),
    ]

    for i, (label, mut, expect) in enumerate(cases):
        if mut == "SKIP_WRITE":
            for old in _glob.glob(os.path.join(receipts_dir, "cgrow-receipt-*.json")):
                os.remove(old)
        else:
            payload = mut(_copy.deepcopy(_honest_v3()))
            _write(f"20260628T001v3{i:02d}Z", payload)
        status, detail = chk_cgrow(tmpdir)
        if status != expect:
            failures.append(
                f"cgrow {label}: expected {expect!r}, got {status!r}: {detail}")

    shutil.rmtree(tmpdir, ignore_errors=True)

    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        raise SystemExit("EMBER_TALLY_CHECKS_CGROW_V3_SELFTEST: failures found")

    print("EMBER_TALLY_CHECKS_CGROW_V3_SELFTEST_PASS")


def _selftest_cgrow_sweep():
    """Cross-arm sweep selftest: fabricated/weakened sweep sets MUST be rejected.

    9 cases: 2 honest (2-arm and 3-arm, must pass) + 7 mutations (must each fail).
    Tests chk_cgrow_v3_sweep directly (not via chk_cgrow).
    """
    import copy as _copy

    failures = []

    _BUDGET_B   = 3_156_787_200
    _SEED_FLOPS = 789_504_000
    _CONT_FLOPS = 2_336_022_528
    _TOTAL_W    = _SEED_FLOPS + _CONT_FLOPS

    def _r(f_val, hash_sfx, warmstart=6.26, scratch=6.29):
        """Minimal honest v3 receipt for sweep testing."""
        result = (
            "DEPTH_FLOP_REDUCTION_CONFIRMED" if warmstart < scratch
            else "NO_DEPTH_FLOP_REDUCTION"
        )
        return {
            "grow_step": {
                "mechanism": "identity_layer_insertion_depth",
                "seed_layers": 8, "grown_layers": 16, "growth_mode": "interleaved",
                "preservation_check": {
                    "loss_delta_nats": 0.0, "logit_max_diff": 0.0, "pass": True,
                    "tolerance_logit": 1e-5, "tolerance_loss_nats": 1e-4,
                },
            },
            "iso_flop": {"budget_b": _BUDGET_B, "growth_fraction_f": f_val},
            "eval_batch_hash": f"hash_{hash_sfx}",
            "frozen_before_arm_s": True,
            "arm_w": {
                "seed_flops": _SEED_FLOPS, "cont_flops": _CONT_FLOPS,
                "total_flops": _TOTAL_W, "final_eval_loss_nats": warmstart,
            },
            "arm_s": {"total_flops": _BUDGET_B, "final_eval_loss_nats": scratch},
            "verdict": {
                "warmstart_final_eval_loss": warmstart,
                "scratch_final_eval_loss": scratch,
                "margin_nats": scratch - warmstart,
                "result": result,
            },
            "invalid_tokens_present": [],
        }

    r025 = _r(0.25, "f025")
    r050 = _r(0.50, "f050")
    r010 = _r(0.10, "f010", warmstart=6.27, scratch=6.29)

    # Case 0: honest 2-arm sweep (f=0.25, f=0.5, distinct hashes) -> pass
    status, detail = chk_cgrow_v3_sweep([r025, r050], ["f025", "f050"])
    if status != "pass":
        failures.append(f"sweep-C0 honest 2-arm: expected pass, got {status!r}: {detail}")

    # Case 1: only 1 receipt -> fail (below min)
    status, detail = chk_cgrow_v3_sweep([r025], ["f025"])
    if status != "fail":
        failures.append(f"sweep-C1 single receipt: expected fail, got {status!r}: {detail}")

    # Case 2: empty list -> fail
    status, detail = chk_cgrow_v3_sweep([], [])
    if status != "fail":
        failures.append(f"sweep-C2 empty list: expected fail, got {status!r}: {detail}")

    # Case 3: one receipt fails individual v3 check (S0)
    bad = _copy.deepcopy(r025)
    bad["grow_step"]["preservation_check"]["logit_max_diff"] = 1.0  # >> 1e-5
    bad["grow_step"]["preservation_check"]["pass"] = False
    status, detail = chk_cgrow_v3_sweep([bad, r050], ["bad_f025", "f050"])
    if status != "fail":
        failures.append(f"sweep-C3 bad receipt S0: expected fail, got {status!r}: {detail}")

    # Case 4: inconsistent budget_b (S2).
    # Use a slightly different budget so r_diff passes its own individual v3 check
    # (arm_w deviation within 1%) but S2 fires on the cross-receipt mismatch.
    _BUDGET_B2 = 3_157_000_000   # != _BUDGET_B; arm_w dev = 0.997% < 1% -> indiv. passes
    r_diff_b = _copy.deepcopy(r050)
    r_diff_b["iso_flop"]["budget_b"] = _BUDGET_B2
    r_diff_b["arm_s"]["total_flops"] = _BUDGET_B2   # arm_s exactly on its budget
    status, detail = chk_cgrow_v3_sweep([r025, r_diff_b], ["f025", "f050_diff_b"])
    if status != "fail":
        failures.append(f"sweep-C4 inconsistent budget_b S2: expected fail, got {status!r}: {detail}")

    # Case 5: duplicate f value (S3)
    r025_dup = _copy.deepcopy(r025)
    r025_dup["eval_batch_hash"] = "hash_f025_dup"   # different hash, but f is the same
    status, detail = chk_cgrow_v3_sweep([r025, r025_dup], ["f025", "f025_dup"])
    if status != "fail":
        failures.append(f"sweep-C5 duplicate f S3: expected fail, got {status!r}: {detail}")

    # Case 6: shared eval_batch_hash between different f, no rationale (S4) -> fail
    r050_shared = _copy.deepcopy(r050)
    r050_shared["eval_batch_hash"] = r025["eval_batch_hash"]   # reuse r025 hash
    # no shared_eval_batch_rationale in either
    status, detail = chk_cgrow_v3_sweep([r025, r050_shared], ["f025", "f050_shared"])
    if status != "fail":
        failures.append(f"sweep-C6 shared hash no rationale S4: expected fail, got {status!r}: {detail}")

    # Case 7: shared eval_batch_hash WITH rationale in BOTH receipts -> pass (S4 documented)
    _SHARED_HASH = "hash_shared_intentional"
    _RATIONALE   = "Same held-out batch for cross-f loss comparability (intentional)"
    r025_rat = _copy.deepcopy(r025)
    r025_rat["eval_batch_hash"] = _SHARED_HASH
    r025_rat["shared_eval_batch_rationale"] = _RATIONALE
    r050_rat = _copy.deepcopy(r050)
    r050_rat["eval_batch_hash"] = _SHARED_HASH
    r050_rat["shared_eval_batch_rationale"] = _RATIONALE
    status, detail = chk_cgrow_v3_sweep([r025_rat, r050_rat], ["f025_rat", "f050_rat"])
    if status != "pass":
        failures.append(f"sweep-C7 shared hash documented S4: expected pass, got {status!r}: {detail}")

    # Case 8: honest 3-arm sweep (f=0.1, 0.25, 0.5, all distinct hashes) -> pass
    status, detail = chk_cgrow_v3_sweep([r010, r025, r050], ["f010", "f025", "f050"])
    if status != "pass":
        failures.append(f"sweep-C8 honest 3-arm: expected pass, got {status!r}: {detail}")

    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        raise SystemExit("EMBER_TALLY_CHECKS_CGROW_SWEEP_SELFTEST: failures found")

    print("EMBER_TALLY_CHECKS_CGROW_SWEEP_SELFTEST_PASS")


def _selftest_cport():
    """C-PORT selftest: fabricated/weakened portability receipts MUST be rejected.

    3 positive (honest; must pass) + 6 negative (must each fail) = 9 cases.
    """
    import tempfile
    import shutil
    import copy as _copy
    import glob as _glob

    failures = []
    tmpdir = tempfile.mkdtemp()
    receipts_dir = os.path.join(tmpdir, "receipts")
    os.makedirs(receipts_dir)

    def _write(stamp, payload):
        for old in _glob.glob(os.path.join(receipts_dir, "portability-probe-*.json")):
            os.remove(old)
        with open(
            os.path.join(receipts_dir, f"portability-probe-{stamp}.json"),
            "w", encoding="utf-8"
        ) as f:
            json.dump(payload, f)

    def _honest():
        return {
            "ticket": "PORTABILITY-PROBE-v1",
            "ts": "20260628T000000Z",
            "marker": "PORTABILITY_PROBE",
            "cpu_forward": {
                "ok": True,
                "output_shape": [1, 8, 256],
                "device_used": "cpu",
                "elapsed_s": 0.008,
                "error": None,
            },
            "adaptive_governor_cpu": {
                "device": "cpu",
                "total_mem_gib": 32.0,
                "vram_fraction": None,   # JSON null — correct for CPU
                "margin_gib": 2.0,
                "pace_s": 0.1,
            },
            "adaptive_governor_cuda": {
                "device": "cuda",
                "device_name": "NVIDIA GeForce RTX 4090",
                "total_mem_gib": 24.0,
                "vram_fraction": 0.80,
                "margin_gib": 1.5,
                "pace_s": 0.05,
            },
            "adaptive_governor_cuda_error": None,
        }

    # --- Positive (honest; must pass) ---
    def _tighter_cuda(p):
        p["adaptive_governor_cuda"]["vram_fraction"] = 0.65   # tighten-only: valid
        return p

    def _cpu_only(p):
        p["adaptive_governor_cuda"] = None
        p["adaptive_governor_cuda_error"] = "No CUDA device available"
        return p

    cases = [
        # (label, mutate_fn_or_SKIP_WRITE, expected_status)
        ("P1 honest full receipt",            lambda p: p,           "pass"),
        ("P2 tighter cuda fraction=0.65",     _tighter_cuda,         "pass"),
        ("P3 CPU-only machine (cuda=None)",   _cpu_only,             "pass"),
        ("N1 no receipt",                     "SKIP_WRITE",          "fail"),
        ("N2 cpu_forward.ok=False",
         lambda p: p["cpu_forward"].__setitem__("ok", False) or p,   "fail"),
        ("N3 cpu_forward.error set",
         lambda p: p["cpu_forward"].__setitem__(
             "error", "RuntimeError: OOM") or p,                      "fail"),
        ("N4 cuda vram_fraction=0.85 (> 0.80)",
         lambda p: p["adaptive_governor_cuda"].__setitem__(
             "vram_fraction", 0.85) or p,                             "fail"),
        ("N5 cpu total_mem_gib=None (missing runtime query)",
         lambda p: p["adaptive_governor_cpu"].__setitem__(
             "total_mem_gib", None) or p,                             "fail"),
        ("N6 cpu vram_fraction=0.8 (not null, hardcoded constant)",
         lambda p: p["adaptive_governor_cpu"].__setitem__(
             "vram_fraction", 0.8) or p,                              "fail"),
    ]

    for i, (label, mut, expect) in enumerate(cases):
        if mut == "SKIP_WRITE":
            for old in _glob.glob(os.path.join(receipts_dir, "portability-probe-*.json")):
                os.remove(old)
        else:
            payload = mut(_copy.deepcopy(_honest()))
            _write(f"20260628T001p{i:02d}Z", payload)
        status, detail = chk_cport(tmpdir)
        if status != expect:
            failures.append(
                f"cport {label}: expected {expect!r}, got {status!r}: {detail}")

    shutil.rmtree(tmpdir, ignore_errors=True)

    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        raise SystemExit("EMBER_TALLY_CHECKS_CPORT_SELFTEST: failures found")

    print("EMBER_TALLY_CHECKS_CPORT_SELFTEST_PASS")


def _selftest_canat():
    """C-ANAT selftest: fabricated receipts referencing actual temp files.

    3 positive (honest; must pass) + 6 negative (must each fail) = 9 cases.
    """
    import tempfile
    import shutil
    import copy as _copy
    import glob as _glob

    failures = []
    tmpdir = tempfile.mkdtemp()
    anat_dir = os.path.join(tmpdir, "receipts", "ember-anatomy")
    os.makedirs(anat_dir)

    # Pool of 17 real doc files (>= 500 bytes)
    doc_files = []
    for idx in range(17):
        path = os.path.join(tmpdir, f"anatomy_doc_{idx:02d}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Anatomy doc {idx}\n" + "content line\n" * 50)  # ~700 bytes
        doc_files.append(path)

    # One stub file (< 500 bytes)
    stub_path = os.path.join(tmpdir, "stub_doc.md")
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write("stub")  # 4 bytes

    def _entry(path, sha="sha256:abc123validhash"):
        return {"path": path, "sha256": sha}

    def _write_receipt(stamp, payload):
        for old in _glob.glob(
            os.path.join(anat_dir, "c-anat-anatomy-set-completion-*.json")
        ):
            os.remove(old)
        with open(
            os.path.join(anat_dir, f"c-anat-anatomy-set-completion-{stamp}.json"),
            "w", encoding="utf-8"
        ) as f:
            json.dump(payload, f)

    def _honest_16():
        return {
            "ticket": "CANAT-RECEIPT-v1",
            "ts": "20260628T000000Z",
            "doc_count": 16,
            "doc_set": [_entry(doc_files[i]) for i in range(16)],
        }

    def _17_docs(p):
        p["doc_set"] = [_entry(doc_files[i]) for i in range(17)]
        p["doc_count"] = 17
        return p

    def _long_sha(p):
        for e in p["doc_set"]:
            e["sha256"] = "sha256:" + "a" * 64
        return p

    def _15_docs(p):
        p["doc_set"] = [_entry(doc_files[i]) for i in range(15)]
        p["doc_count"] = 15
        return p

    def _missing_doc(p):
        p["doc_set"][7] = _entry("/nonexistent/path/missing_doc.md")
        return p

    def _stub_doc(p):
        p["doc_set"][3] = _entry(stub_path)
        return p

    def _empty_sha(p):
        p["doc_set"][5]["sha256"] = ""
        return p

    def _empty_set(p):
        p["doc_set"] = []
        p["doc_count"] = 0
        return p

    cases = [
        # (label, mutate_fn_or_SKIP_WRITE, expected_status)
        ("P1 honest 16 docs",                  lambda p: p,    "pass"),
        ("P2 17 docs (> minimum)",             _17_docs,        "pass"),
        ("P3 16 docs with long sha256 strings", _long_sha,      "pass"),
        ("N1 no receipt",                      "SKIP_WRITE",    "fail"),
        ("N2 only 15 docs",                    _15_docs,        "fail"),
        ("N3 one doc path not on disk",        _missing_doc,    "fail"),
        ("N4 one stub doc < 500 bytes",        _stub_doc,       "fail"),
        ("N5 empty sha256 on one entry",       _empty_sha,      "fail"),
        ("N6 empty doc_set list",              _empty_set,      "fail"),
    ]

    for i, (label, mut, expect) in enumerate(cases):
        if mut == "SKIP_WRITE":
            for old in _glob.glob(
                os.path.join(anat_dir, "c-anat-anatomy-set-completion-*.json")
            ):
                os.remove(old)
        else:
            payload = mut(_copy.deepcopy(_honest_16()))
            _write_receipt(f"20260628T001c{i:02d}Z", payload)
        status, detail = chk_canat(tmpdir)
        if status != expect:
            failures.append(
                f"canat {label}: expected {expect!r}, got {status!r}: {detail}")

    shutil.rmtree(tmpdir, ignore_errors=True)

    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        raise SystemExit("EMBER_TALLY_CHECKS_CANAT_SELFTEST: failures found")

    print("EMBER_TALLY_CHECKS_CANAT_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
        _selftest_cgrow()
        _selftest_cgrow_v3()
        _selftest_cgrow_sweep()
        _selftest_cport()
        _selftest_canat()
    else:
        print("Usage: python ember_tally_checks.py --selftest")
