#!/usr/bin/env python3
"""fp33_surpass_verdict.py — the E2B-SURPASS terminal-gate aggregator.

Computes the frozen conjunction verdict from the seven leg receipts:

    SURPASS = A1 AND A2 AND A3 AND B1 AND B2 AND B3 AND B4

against the FROZEN prereg `docs/fp33-surpass-prereg-v1.md` (the 2nd of the
goal's two completion conditions; the 1st is ember_tally == 100%). This script
holds the *decision logic*; the prereg holds the *contract*. The means (base
pick, training plan) gate elsewhere (#255) and never touch this verdict.

Pre-registration discipline (fp-39 / fp-44 class): the decision rule is frozen
HERE, before the leg receipts exist, so the verdict cannot be shaped to the
data. Companion schema doc: research/fp33-surpass-verdict-gate.md.

Statistics (verbatim from the prereg's statistics block):
  - paired bootstrap over tasks, 10,000 resamples, 95% CI on the per-task delta
    (ember - E2B). "In ember's favor" = CI excludes 0 with positive mean.
  - "parity-or-better" = CI lower bound > -MDE (recorded at run time) OR CI
    excludes 0 in ember's favor.
  - binary duty episodes use McNemar's exact test, p < 0.05.
  - matched compute: each paired side within 10% on wall / gpu_s / tokens, else
    the receipt is INVALID (re-run, never reinterpret).

Pure stdlib: seeded `random.Random` bootstrap (reproducible) + exact McNemar via
`math.comb`. No numpy, no nondeterministic RNG — receipts-only-truth holds.

Usage:
  python scripts/fp33_surpass_verdict.py --receipts receipts   # analyze on-disk
  python scripts/fp33_surpass_verdict.py --selftest            # synthetic gate
"""
from __future__ import annotations
import argparse
import glob
import json
import math
import os
import random
import sys

# ---- frozen constants -------------------------------------------------------
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 33            # pinned (fp-33) → CI reproducible across runs
CI = 0.95
COMPUTE_TOL = 0.10            # matched-compute: within 10% per side, else INVALID
MCNEMAR_ALPHA = 0.05
LEGS = ["A1", "A2", "A3", "B1", "B2", "B3", "B4"]
SELFTEST_TAG = "FP33_SURPASS_VERDICT_SELFTEST_PASS"


# ---- statistics primitives --------------------------------------------------
def paired_bootstrap_ci(deltas, resamples=BOOTSTRAP_RESAMPLES,
                        seed=BOOTSTRAP_SEED, ci=CI):
    """95% CI on the mean per-task delta via seeded paired bootstrap.

    Returns (lo, hi, mean). delta = ember - E2B (positive ⇒ ember better).
    """
    n = len(deltas)
    if n == 0:
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        s = 0.0
        for _ in range(n):
            s += deltas[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo_idx = int(round((1 - ci) / 2 * (resamples - 1)))
    hi_idx = int(round((1 + ci) / 2 * (resamples - 1)))
    return (means[lo_idx], means[hi_idx], sum(deltas) / n)


def mcnemar_exact_p(b, c):
    """Two-sided exact McNemar p on discordant pairs.

    b = ember-pass / E2B-fail; c = ember-fail / E2B-pass. Under H0 each
    discordant pair is a fair coin. Returns p in [0,1].
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(2.0 * tail, 1.0)


def _ratio_within(a, b, tol):
    """True if a and b are within `tol` fractional distance (symmetric)."""
    if a is None or b is None:
        return None
    hi = max(abs(a), abs(b))
    if hi == 0:
        return True
    return abs(a - b) / hi <= tol


def matched_compute(receipt, tol=COMPUTE_TOL):
    """Return (ok, detail). ok is True/False/None(unverifiable).

    Checks wall_s / gpu_s / tokens between ember and E2B sides within `tol`.
    Missing compute block → None (cannot verify; flagged, not auto-failed).
    """
    comp = receipt.get("compute")
    if not isinstance(comp, dict):
        return (None, "no compute block")
    e = comp.get("ember", {})
    z = comp.get("e2b", {})
    fields = ["wall_s", "gpu_s", "tokens"]
    bad = []
    seen = 0
    for f in fields:
        r = _ratio_within(e.get(f), z.get(f), tol)
        if r is None:
            continue
        seen += 1
        if not r:
            bad.append(f)
    if seen == 0:
        return (None, "compute block empty")
    if bad:
        return (False, f"compute mismatch >{int(tol*100)}% on {','.join(bad)}")
    return (True, f"matched within {int(tol*100)}% ({seen} fields)")


# ---- receipt helpers --------------------------------------------------------
def _deltas(receipt):
    """Extract per-task deltas (ember - E2B) from a paired receipt."""
    if isinstance(receipt.get("per_task_delta"), list):
        out = []
        for x in receipt["per_task_delta"]:
            try:
                out.append(float(x))
            except (ValueError, TypeError):
                pass
        return out
    em = receipt.get("per_task_ember")
    z = receipt.get("per_task_e2b")
    if isinstance(em, list) and isinstance(z, list) and len(em) == len(z):
        out = []
        for a, b in zip(em, z):
            try:
                out.append(float(a) - float(b))
            except (ValueError, TypeError):
                pass
        return out
    return []


def _ci_excludes_zero_favor(deltas):
    lo, hi, mean = paired_bootstrap_ci(deltas)
    return (lo > 0.0, lo, hi, mean)


def _paired_pass(r, ekey, zkey):
    """Return (ember 0/1 list, e2b 0/1 list) if both present, equal-length, ≥1.

    The B-leg instruments (sp6b-replay-rig, density_ab_b1/b2) emit per-item
    pass/fail VECTORS per seat — NOT pre-counted discordant pairs (the rig
    explicitly defers McNemar to 'the fp-33 prereg scorer', i.e. here). This
    derives counts + discordant pairs from those paired vectors.
    """
    em, z = r.get(ekey), r.get(zkey)
    if isinstance(em, list) and isinstance(z, list) and em and len(em) == len(z):
        return ([1 if x else 0 for x in em], [1 if x else 0 for x in z])
    return None


def _discordant(em, z):
    """McNemar discordant counts from paired 0/1 vectors.

    b = ember-pass / E2B-fail; c = ember-fail / E2B-pass.
    """
    b = sum(1 for e, x in zip(em, z) if e and not x)
    c = sum(1 for e, x in zip(em, z) if (not e) and x)
    return b, c


# ---- per-leg evaluators -----------------------------------------------------
# Each returns dict: {leg, status: PASS|FAIL|INVALID|PENDING, detail, distance}
def eval_A1(r):
    if r is None:
        return _pending("A1", "floor-world paired eval")
    ok, cdetail = matched_compute(r)
    if ok is False:
        return _invalid("A1", cdetail)
    deltas = _deltas(r)
    if not deltas:
        return _invalid("A1", "no per-task deltas in receipt")
    excl, lo, hi, mean = _ci_excludes_zero_favor(deltas)
    if excl:
        return _pass("A1", f"CI[{lo:.4f},{hi:.4f}] excludes 0, mean +{mean:.4f}")
    return _fail("A1", f"CI[{lo:.4f},{hi:.4f}] includes 0 (mean {mean:+.4f})",
                 distance=max(0.0, -lo))


def eval_A2(r):
    if r is None:
        return _pending("A2", "accumulation-loop differential (THE thesis bar)")
    ok, cdetail = matched_compute(r)
    if ok is False:
        return _invalid("A2", cdetail)
    et = r.get("ember_three_test", {})
    zt = r.get("e2b_three_test", {})
    ember_3 = all(bool(et.get(k)) for k in
                  ("held_out_transfer", "matched_control", "deletion"))
    e2b_3 = all(bool(zt.get(k)) for k in
                ("held_out_transfer", "matched_control", "deletion"))
    if not ember_3:
        missing = [k for k in ("held_out_transfer", "matched_control", "deletion")
                   if not et.get(k)]
        return _fail("A2", f"ember three-test FAIL ({','.join(missing)})")
    # Path 2: ember passes three-test, E2B does not → A2 satisfied.
    if not e2b_3:
        return _pass("A2", "ember three-test PASS; E2B three-test FAIL (Path 2)")
    # Path 1: both pass three-test → require paired transfer-delta CI > 0.
    deltas = _deltas(r)
    if not deltas:
        return _invalid("A2", "both three-test PASS but no transfer-delta array")
    excl, lo, hi, mean = _ci_excludes_zero_favor(deltas)
    if excl:
        return _pass("A2", f"both three-test PASS; transfer-delta CI"
                            f"[{lo:.4f},{hi:.4f}] excludes 0 (+{mean:.4f})")
    return _fail("A2", f"both three-test PASS but transfer-delta CI"
                       f"[{lo:.4f},{hi:.4f}] includes 0", distance=max(0.0, -lo))


def eval_A3(r):
    if r is None:
        return _pending("A3", "public slices MBPP + GSM8K-200 (parity floor)")
    ok, cdetail = matched_compute(r)
    if ok is False:
        return _invalid("A3", cdetail)
    slices = r.get("slices", {})
    needed = ["mbpp", "gsm8k200"]
    sub = {}
    worst = 0.0
    for name in needed:
        s = slices.get(name)
        if not isinstance(s, dict):
            return _invalid("A3", f"missing slice '{name}'")
        deltas = _deltas(s)
        if not deltas:
            return _invalid("A3", f"slice '{name}' has no per-task deltas")
        try:
            mde = float(s.get("mde", 0.0))
        except (ValueError, TypeError):
            return _invalid("A3", f"slice '{name}' has non-numeric mde")
        lo, hi, mean = paired_bootstrap_ci(deltas)
        parity = lo > -mde            # parity-or-better
        sub[name] = (parity, lo, hi, mean, mde)
        if not parity:
            worst = max(worst, (-mde) - lo)
    if all(v[0] for v in sub.values()):
        d = "; ".join(f"{k}:CI_lo{v[1]:.4f}>-MDE{v[4]:.4f}" for k, v in sub.items())
        return _pass("A3", f"parity-or-better both slices ({d})")
    failed = [k for k, v in sub.items() if not v[0]]
    return _fail("A3", f"below parity floor on {','.join(failed)}", distance=worst)


def eval_B1(r):
    if r is None:
        return _pending("B1", "answers-when-spoken-to (5 probes)")
    # Accept paired per-probe vectors (harness-native) or scalar counts.
    vec = _paired_pass(r, "ember_probe_pass", "e2b_probe_pass")
    if vec:
        ev, zv = vec
        em, z = sum(ev), sum(zv)
        b, c = _discordant(ev, zv)
    else:
        try:
            em = int(r.get("ember_correct", -1))
            z = int(r.get("e2b_correct", -1))
        except (ValueError, TypeError):
            return _invalid("B1", "ember_correct/e2b_correct non-numeric")
        if em < 0 or z < 0:
            return _invalid("B1", "missing ember_probe_pass/e2b_probe_pass "
                                  "vectors or ember_correct/e2b_correct counts")
        disc = r.get("discordant", {})
        try:
            b, c = int(disc.get("b", 0)), int(disc.get("c", 0))
        except (ValueError, TypeError):
            return _invalid("B1", "discordant b/c non-numeric")
    if em < 4:
        return _fail("B1", f"ember {em}/5 < 4 floor", distance=4 - em)
    if em <= z:
        return _fail("B1", f"ember {em} not > E2B {z}", distance=(z - em) + 1)
    both_imperfect = em < 5 and z < 5
    if both_imperfect:
        p = mcnemar_exact_p(b, c)
        if not (b > c and p < MCNEMAR_ALPHA):
            return _fail("B1", f"both imperfect, McNemar p={p:.4f} (b={b},c={c}) "
                               f"not sig", distance=p)
        return _pass("B1", f"ember {em}/5 > E2B {z}, McNemar p={p:.4f}")
    return _pass("B1", f"ember {em}/5 > E2B {z}/5")


def eval_B2(r):
    if r is None:
        return _pending("B2", "agency (5 obligated actions)")
    vec = _paired_pass(r, "ember_action_done", "e2b_action_done")
    if vec:
        em, z = sum(vec[0]), sum(vec[1])
    else:
        try:
            em = int(r.get("ember_done", -1))
            z = int(r.get("e2b_done", -1))
        except (ValueError, TypeError):
            return _invalid("B2", "ember_done/e2b_done non-numeric")
        if em < 0 or z < 0:
            return _invalid("B2", "missing ember_action_done/e2b_action_done "
                                  "vectors or ember_done/e2b_done counts")
    if em < 4:
        return _fail("B2", f"ember {em}/5 < 4 floor", distance=4 - em)
    if em <= z:
        return _fail("B2", f"ember {em} not > E2B {z}", distance=(z - em) + 1)
    return _pass("B2", f"ember {em}/5 obligated, > E2B {z}/5")


def eval_B3(r):
    if r is None:
        return _pending("B3", "duty battery (20 episodes, McNemar)")
    # Harness-native: paired per-episode pass vectors (sp6b-replay-rig output,
    # one per seat) → derive discordant here. Fallback: pre-counted {b,c}.
    vec = _paired_pass(r, "ember_episode_pass", "e2b_episode_pass")
    if vec:
        b, c = _discordant(vec[0], vec[1])
    else:
        disc = r.get("discordant")
        if not isinstance(disc, dict):
            return _invalid("B3", "missing ember_episode_pass/e2b_episode_pass "
                                  "vectors or discordant {b,c}")
        try:
            b, c = int(disc.get("b", 0)), int(disc.get("c", 0))
        except (ValueError, TypeError):
            return _invalid("B3", "discordant b/c non-numeric")
    p = mcnemar_exact_p(b, c)
    if b > c and p < MCNEMAR_ALPHA:
        return _pass("B3", f"ember strictly better, McNemar p={p:.4f} (b={b},c={c})")
    return _fail("B3", f"not strictly-better-sig: p={p:.4f} (b={b},c={c})",
                 distance=p)


def eval_B4(r):
    if r is None:
        return _pending("B4", "evals-through-harness (binary)")
    if bool(r.get("receipt_exists")) and bool(r.get("dispatched_through_harness")):
        return _pass("B4", "Leg-A evals dispatched through ember harness")
    return _fail("B4", "harness-dispatch receipt absent/incomplete")


EVALUATORS = {
    "A1": eval_A1, "A2": eval_A2, "A3": eval_A3,
    "B1": eval_B1, "B2": eval_B2, "B3": eval_B3, "B4": eval_B4,
}


# ---- status constructors ----------------------------------------------------
def _mk(leg, status, detail, distance=None):
    return {"leg": leg, "status": status, "detail": detail, "distance": distance}


def _pass(leg, d):     return _mk(leg, "PASS", d, 0.0)
def _fail(leg, d, distance=None): return _mk(leg, "FAIL", d, distance)
def _invalid(leg, d):  return _mk(leg, "INVALID", d, None)
def _pending(leg, d):  return _mk(leg, "PENDING", f"no receipt yet — {d}", None)


# ---- aggregation ------------------------------------------------------------
def load_leg_receipts(receipts_dir):
    """Map leg-id → receipt dict (latest by filename) from a receipts dir."""
    out = {}
    for path in sorted(glob.glob(os.path.join(receipts_dir, "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                r = json.load(fh)
        except Exception:
            continue
        if not isinstance(r, dict):
            continue
        leg = r.get("leg")
        if leg in LEGS:
            out[leg] = r          # sorted → last wins (latest receipt)
    return out


def aggregate(leg_receipts):
    """Compute the conjunction verdict from a {leg: receipt} mapping.

    Returns the verdict dict. SURPASS requires every leg PASS. Any PENDING →
    INCOMPLETE (the honest pre-pretrain state). Any INVALID → INCOMPLETE
    (re-run that leg). Any FAIL with all others PASS/FAIL → SHORTFALL with the
    measured-distance receipt per the GOAL CALIBRATION block.
    """
    results = [EVALUATORS[leg](leg_receipts.get(leg)) for leg in LEGS]
    by = {r["leg"]: r for r in results}
    statuses = {r["status"] for r in results}

    if all(r["status"] == "PASS" for r in results):
        verdict = "SURPASS"
    elif "PENDING" in statuses or "INVALID" in statuses:
        verdict = "INCOMPLETE"
    else:
        verdict = "SHORTFALL"

    failed = [{"leg": r["leg"], "detail": r["detail"], "distance": r["distance"]}
              for r in results if r["status"] == "FAIL"]
    blocked = [{"leg": r["leg"], "status": r["status"], "detail": r["detail"]}
               for r in results if r["status"] in ("PENDING", "INVALID")]
    return {
        "ticket": "FP33-SURPASS-VERDICT",
        "verdict": verdict,
        "rule": "SURPASS = A1 AND A2 AND A3 AND B1 AND B2 AND B3 AND B4",
        "legs": {r["leg"]: {"status": r["status"], "detail": r["detail"],
                            "distance": r["distance"]} for r in results},
        "measured_distance": failed,     # which bars failed + numeric distance
        "blocked": blocked,              # PENDING/INVALID legs (not yet decidable)
        "deadline": "2026-06-22",
    }


def analyze(receipts_dir="receipts"):
    return aggregate(load_leg_receipts(receipts_dir))


def emit_receipt(verdict, receipts_dir="receipts"):
    """Write the verdict as a committed receipt.

    The goal's 2nd completion condition is 'an S5 E2B-surpass receipt exists' —
    a SURPASS verdict here, written to master, IS that receipt. We import
    datetime lazily and only on the emit path (the analyze/selftest paths stay
    time-free so they're reproducible and CI-safe).
    """
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(receipts_dir, exist_ok=True)
    path = os.path.join(receipts_dir, f"fp33-surpass-verdict-{ts}.json")
    payload = dict(verdict)
    payload["ts"] = ts
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=True, indent=2)
    return path


# ---- selftest ---------------------------------------------------------------
def _synth_all_pass():
    """Seven synthetic leg receipts engineered to clear every bar."""
    pos = [0.20 + 0.01 * (i % 5) for i in range(40)]   # clear +0.2 separation
    comp = {"ember": {"wall_s": 100, "gpu_s": 100, "tokens": 1_000_000},
            "e2b":   {"wall_s": 104, "gpu_s": 103, "tokens": 1_010_000}}
    return {
        "A1": {"leg": "A1", "per_task_delta": pos, "compute": comp},
        "A2": {"leg": "A2", "compute": comp,
               "ember_three_test": {"held_out_transfer": True,
                                    "matched_control": True, "deletion": True},
               "e2b_three_test": {"held_out_transfer": True,
                                  "matched_control": True, "deletion": False}},
        "A3": {"leg": "A3", "compute": comp, "slices": {
            "mbpp": {"per_task_delta": [0.05] * 30, "mde": 0.10},
            "gsm8k200": {"per_task_delta": [0.02] * 30, "mde": 0.10}}},
        "B1": {"leg": "B1", "ember_correct": 5, "e2b_correct": 3},
        "B2": {"leg": "B2", "ember_done": 5, "e2b_done": 2},
        "B3": {"leg": "B3", "discordant": {"b": 15, "c": 2}},
        "B4": {"leg": "B4", "receipt_exists": True,
               "dispatched_through_harness": True},
    }


def selftest():
    checks = []

    def chk(name, cond):
        checks.append((name, bool(cond)))

    # 1. all-pass synthetic → SURPASS
    v = aggregate(_synth_all_pass())
    chk("all-pass → SURPASS", v["verdict"] == "SURPASS")

    # 2. missing every receipt → INCOMPLETE, 7 PENDING
    v0 = aggregate({})
    chk("no receipts → INCOMPLETE", v0["verdict"] == "INCOMPLETE")
    chk("no receipts → 7 PENDING",
        sum(1 for L in LEGS if v0["legs"][L]["status"] == "PENDING") == 7)

    # 3. one leg FAIL (A1 CI includes 0) → SHORTFALL + distance recorded
    r = _synth_all_pass()
    r["A1"]["per_task_delta"] = [0.5, -0.5, 0.4, -0.6, 0.1, -0.2] * 6  # straddles 0
    v3 = aggregate(r)
    chk("A1 straddles 0 → SHORTFALL", v3["verdict"] == "SHORTFALL")
    chk("A1 in measured_distance",
        any(d["leg"] == "A1" for d in v3["measured_distance"]))

    # 4. compute mismatch >10% → INVALID → INCOMPLETE
    r = _synth_all_pass()
    r["A1"]["compute"] = {"ember": {"wall_s": 100, "gpu_s": 100, "tokens": 1e6},
                          "e2b": {"wall_s": 200, "gpu_s": 100, "tokens": 1e6}}
    v4 = aggregate(r)
    chk("compute mismatch → A1 INVALID", v4["legs"]["A1"]["status"] == "INVALID")
    chk("any INVALID → INCOMPLETE", v4["verdict"] == "INCOMPLETE")

    # 5. McNemar exact: clear separation significant, tie not
    chk("McNemar (15,2) p<0.05", mcnemar_exact_p(15, 2) < 0.05)
    chk("McNemar (8,8) p≈1 not sig", mcnemar_exact_p(8, 8) >= 0.05)
    chk("McNemar (0,0) → 1.0", mcnemar_exact_p(0, 0) == 1.0)

    # 6. B3 direction guard: ember WORSE (b<c) must FAIL even if |sep| large
    r = _synth_all_pass()
    r["B3"]["discordant"] = {"b": 2, "c": 15}
    v6 = aggregate(r)
    chk("B3 ember-worse → FAIL", v6["legs"]["B3"]["status"] == "FAIL")

    # 7. A2 Path-1: both three-test PASS, transfer-delta CI must exclude 0
    r = _synth_all_pass()
    r["A2"]["e2b_three_test"] = {"held_out_transfer": True,
                                 "matched_control": True, "deletion": True}
    r["A2"]["per_task_delta"] = [0.15] * 30      # ember transfer > e2b, clear
    v7 = aggregate(r)
    chk("A2 Path-1 (both 3-test, ember Δ>0) → PASS",
        v7["legs"]["A2"]["status"] == "PASS")
    r2 = _synth_all_pass()
    r2["A2"]["e2b_three_test"] = {"held_out_transfer": True,
                                  "matched_control": True, "deletion": True}
    r2["A2"]["per_task_delta"] = [0.3, -0.3] * 15  # straddles 0
    v7b = aggregate(r2)
    chk("A2 Path-1 (both 3-test, Δ straddles 0) → FAIL",
        v7b["legs"]["A2"]["status"] == "FAIL")

    # 8. B1 both-imperfect requires McNemar significance
    r = _synth_all_pass()
    r["B1"] = {"leg": "B1", "ember_correct": 4, "e2b_correct": 3,
               "discordant": {"b": 1, "c": 0}}     # 4>3 but McNemar p=1.0
    v8 = aggregate(r)
    chk("B1 both-imperfect, McNemar n.s. → FAIL",
        v8["legs"]["B1"]["status"] == "FAIL")
    r["B1"]["discordant"] = {"b": 6, "c": 0}        # now significant
    v8b = aggregate(r)
    chk("B1 both-imperfect, McNemar sig → PASS",
        v8b["legs"]["B1"]["status"] == "PASS")

    # 9. bootstrap CI sanity: clear positive → lo>0; zero-centered → lo<0
    lo, hi, m = paired_bootstrap_ci([0.5] * 20)
    chk("bootstrap constant +0.5 → lo>0", lo > 0)
    lo2, _, _ = paired_bootstrap_ci([1.0, -1.0] * 20)
    chk("bootstrap zero-centered → lo<0", lo2 < 0)

    # 10. harness-native VECTOR path (sp6b-replay-rig emits per-episode pass
    #     vectors per seat, NOT pre-counted {b,c}). B3 from paired vectors:
    r = _synth_all_pass()
    # 20 episodes: ember passes 18, e2b passes 5; discordant b=14,c=1 → sig
    ember_ep = [1] * 18 + [0] * 2
    e2b_ep =   [1] * 4 + [0] * 11 + [1] * 1 + [0] * 4   # 5 passes, arranged
    r["B3"] = {"leg": "B3", "ember_episode_pass": ember_ep,
               "e2b_episode_pass": e2b_ep}
    v10 = aggregate(r)
    chk("B3 from paired vectors → PASS", v10["legs"]["B3"]["status"] == "PASS")
    # B1 from paired probe vectors — passing path is ember perfect 5/5 vs <5.
    r2 = _synth_all_pass()
    r2["B1"] = {"leg": "B1",
                "ember_probe_pass": [1, 1, 1, 1, 1],   # 5/5 (perfect)
                "e2b_probe_pass":   [1, 0, 0, 0, 0]}   # 1/5
    v10b = aggregate(r2)
    chk("B1 vectors (5/5 vs 1/5, perfect) → PASS",
        v10b["legs"]["B1"]["status"] == "PASS")
    # PROPERTY (frozen prereg, n=5): when BOTH imperfect the McNemar bar is
    # unreachable (max discordant b=5,c=0 → p=0.0625 > 0.05), so ember 4/5 vs
    # imperfect e2b FAILS B1 — faithful to the frozen bar, not a scorer choice.
    r2b = _synth_all_pass()
    r2b["B1"] = {"leg": "B1",
                 "ember_probe_pass": [1, 1, 1, 1, 0],   # 4/5
                 "e2b_probe_pass":   [0, 0, 0, 1, 0]}   # 1/5 (both imperfect)
    v10b2 = aggregate(r2b)
    chk("B1 both-imperfect 4/5 @n=5 (McNemar unreachable) → FAIL",
        v10b2["legs"]["B1"]["status"] == "FAIL")
    # B2 from paired action vectors
    r3 = _synth_all_pass()
    r3["B2"] = {"leg": "B2",
                "ember_action_done": [1, 1, 1, 1, 1],
                "e2b_action_done":   [1, 1, 0, 0, 0]}
    v10c = aggregate(r3)
    chk("B2 from paired vectors (5/5 vs 2/5) → PASS",
        v10c["legs"]["B2"]["status"] == "PASS")
    # vector path agrees with pre-counted {b,c} (same discordant → same verdict)
    rv = {"leg": "B3", "ember_episode_pass": [1, 1, 1, 0], "e2b_episode_pass": [0, 0, 0, 1]}
    rc = {"leg": "B3", "discordant": {"b": 3, "c": 1}}
    chk("B3 vector ≡ pre-counted {b,c}",
        eval_B3(rv)["status"] == eval_B3(rc)["status"])

    # 11. A-leg per-seat paired form (harnesses are per-seat: fp33_a3ii_gsm8k,
    #     density_ab_a1/a2 emit one seat each → leg receipt carries both seats'
    #     per-task arrays; _deltas derives ember−E2B). Lock that branch.
    r = _synth_all_pass()
    r["A1"] = {"leg": "A1", "compute": _synth_all_pass()["A1"]["compute"],
               "per_task_ember": [0.9] * 30, "per_task_e2b": [0.6] * 30}  # +0.3
    v11 = aggregate(r)
    chk("A1 per-seat paired (ember .9 vs e2b .6) → PASS",
        v11["legs"]["A1"]["status"] == "PASS")
    # A3 slice carrying per-seat arrays (GSM8K binary pass per task)
    r2 = _synth_all_pass()
    r2["A3"] = {"leg": "A3", "compute": _synth_all_pass()["A3"]["compute"],
                "slices": {
                    "mbpp": {"per_task_ember": [1] * 25 + [0] * 5,
                             "per_task_e2b": [1] * 22 + [0] * 8, "mde": 0.10},
                    "gsm8k200": {"per_task_ember": [1] * 20 + [0] * 10,
                                 "per_task_e2b": [1] * 18 + [0] * 12, "mde": 0.10}}}
    v11b = aggregate(r2)
    chk("A3 slices per-seat paired → PASS",
        v11b["legs"]["A3"]["status"] == "PASS")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"{passed}/{total} checks passed")
    if passed == total:
        print(SELFTEST_TAG)
        return 0
    return 1


# ---- cli --------------------------------------------------------------------
def _utf8_stdout():
    # cp1252 default on Windows can't encode the verdict glyphs / arrows in
    # printed strings — reconfigure defensively so receipts print clean.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipts", default="receipts",
                    help="dir of leg receipts (*.json with a 'leg' field)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", action="store_true",
                    help="write the verdict as a committed receipt (the S5 "
                         "surpass receipt = goal completion condition #2)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    verdict = analyze(args.receipts)
    print(json.dumps(verdict, ensure_ascii=True, indent=2))
    if args.emit:
        path = emit_receipt(verdict, args.receipts)
        print(f"\nemitted: {path}")
    # exit 0 always — this is a report, not a CI gate; SURPASS is read by the tally
    return 0


if __name__ == "__main__":
    sys.exit(main())
