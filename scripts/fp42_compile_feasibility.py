"""fp42_compile_feasibility.py — two-wall §3 feasibility envelope for the c04 pick.

The c04 design benches (#353, c04-receipt3) show §3 gate FAIL on all 5 candidates
at eager. eli's receipt named TWO independent walls but did not compute their JOINT
effect on §3 feasibility — that is this artifact's job, and it is decision-changing.

THE TWO WALLS
-------------
  C-4  torch.compile broken (generic.py:865 co_varnames untraceable, torch 2.6 +
       transformers 5.2). Compile accelerates the MODEL forward/backward only.
  C-3  Muon Newton-Schulz dominates: optimizer_wall_share 0.41-0.74 (threshold
       0.15). Muon NS is NOT compiled, so compile does not touch it.

WHY COMPILE ALONE IS INSUFFICIENT
---------------------------------
Wall time T = T_model + T_opt with T_opt/T = opt_share. Compile speeds only the
model fraction by s_c; fused-muon (#329) speeds only the optimizer fraction by s_m:

    tok_s' = tok_s / ( (1-opt_share)/s_c + opt_share/s_m )

For c03 (tok_s=16834, opt_share=0.4137, §3 needs 25463):
  compile-ALONE required s_c (s_m=1): (1-0.4137)/s_c + 0.4137 <= 16834/25463=0.6611
    => s_c >= 2.37  (implausible for transformer training compile, typ. 1.3-1.7x)
  JOINT at s_c=1.5: s_m >= 1.53 clears; but 1.5/1.5 lands at 25251 = 0.8% SHORT.

So §3 feasibility for c03 requires BOTH walls broken, each slightly above 1.5x; the
margin is THIN (1.5/1.5 just misses 25463). This makes #329
(fused-muon) LOAD-BEARING on the critical path, not a side optimization — and it
defines the escalation trigger precisely: only if a real compiled+fused re-bench
still falls short of 25463 does the <=1-day bar become the user's call.

This is a feasibility ESTIMATE that sets targets (mira's compile target, the
fused-muon target). The binding verdict is the MEASURED compiled+fused re-bench;
the s_c/s_m independence-and-multiplicativity assumption is an approximation.

Emits a receipt; selftest validates the tok_s' model on known cases.
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write  # noqa: E402

RECEIPTS = f"{NC}/receipts"
SEC_PER_DAY = 86400
BUDGET_TOKENS = 2.2e9
S3_THRESHOLD = BUDGET_TOKENS / SEC_PER_DAY            # 25463 tok/s for 2.2B in 1 day
REALISTIC_COMPILE = 1.5      # typical transformer-train torch.compile speedup
REALISTIC_FUSED = 1.5        # target fused-muon NS speedup (#329)
MAX_PLAUSIBLE = 2.0          # generous ceiling per lever for the INFEASIBLE check
CONTAM_FRAC = 0.1            # tok_s < CONTAM_FRAC * max candidate => GPU-contention contaminated


def tok_s_after(tok_s, opt_share, s_c, s_m):
    """Projected tok/s when compile speeds the model fraction by s_c and fused-muon
    speeds the optimizer fraction by s_m."""
    return tok_s / ((1 - opt_share) / s_c + opt_share / s_m)


def required_s_c_alone(tok_s, opt_share, target=S3_THRESHOLD):
    """Compile-alone speedup (s_m=1) needed to clear target; None if impossible
    (target unreachable even as s_c -> inf, i.e. the optimizer floor alone exceeds it)."""
    # tok_s / ((1-opt)/s_c + opt) >= target  =>  (1-opt)/s_c <= tok_s/target - opt
    rhs = tok_s / target - opt_share
    if rhs <= 0:
        return None  # even infinite compile can't clear (opt floor too high)
    return (1 - opt_share) / rhs


def required_s_m_given_sc(tok_s, opt_share, s_c, target=S3_THRESHOLD):
    """Fused-muon speedup needed at a fixed compile speedup s_c; None if impossible."""
    rhs = tok_s / target - (1 - opt_share) / s_c
    if rhs <= 0:
        return None
    return opt_share / rhs


def _load_candidates():
    """Per-candidate (tok_s, opt_share) for the ckpt-compile arm (the C-2 default)."""
    rows = {}
    for p in sorted(glob.glob(f"{RECEIPTS}/c04-design-bench-*.json")):
        try:
            r = json.load(open(p))
        except Exception:
            continue
        if r.get("ticket") != "C04-DESIGN-BENCH":
            continue
        cand = r.get("candidate")
        for c in r.get("cells", []):
            if c.get("grad_checkpointing") and c.get("status") == "OK" and c.get("tok_s_paced"):
                key = cand
                if key not in rows or r["ts"] > rows[key]["_ts"]:
                    rows[key] = {"tok_s": c["tok_s_paced"],
                                 "opt_share": c.get("optimizer_wall_share"),
                                 "_ts": r["ts"]}
    return rows


def analyze():
    rows = _load_candidates()
    if not rows:
        print(json.dumps({"verdict": "NO_BENCH_RECEIPTS"}))
        sys.exit(2)
    max_tok = max(v["tok_s"] for v in rows.values())

    results = {}
    for cand, v in sorted(rows.items()):
        tok_s, opt = v["tok_s"], v["opt_share"]
        contaminated = tok_s < CONTAM_FRAC * max_tok
        s_c_alone = required_s_c_alone(tok_s, opt) if opt is not None else None
        s_m_at_15 = required_s_m_given_sc(tok_s, opt, REALISTIC_COMPILE) if opt is not None else None
        proj_realistic = tok_s_after(tok_s, opt, REALISTIC_COMPILE, REALISTIC_FUSED) if opt is not None else None
        proj_maxlever = tok_s_after(tok_s, opt, MAX_PLAUSIBLE, MAX_PLAUSIBLE) if opt is not None else None

        if contaminated:
            cls = "CONTAMINATED-NEEDS-SOLO-REBENCH"
        elif s_c_alone is not None and s_c_alone <= REALISTIC_COMPILE:
            cls = "FEASIBLE-COMPILE-ALONE"
        elif proj_maxlever is not None and proj_maxlever >= S3_THRESHOLD:
            cls = "FEASIBLE-JOINT-COMPILE+FUSEDMUON"
        else:
            cls = "INFEASIBLE-AT-2.2B-EVEN-JOINT"

        results[cand] = {
            "tok_s_eager": round(tok_s, 1),
            "opt_wall_share": opt,
            "contaminated": contaminated,
            "required_compile_alone_x": round(s_c_alone, 3) if s_c_alone else None,
            "required_fusedmuon_x_at_compile_1.5": round(s_m_at_15, 3) if s_m_at_15 else None,
            "proj_tok_s_compile1.5_fused1.5": round(proj_realistic, 1) if proj_realistic else None,
            "proj_clears_s3_at_realistic": (proj_realistic is not None and proj_realistic >= S3_THRESHOLD),
            "class": cls,
        }

    # primary reference = the non-contaminated candidate(s)
    clean = [c for c, r in results.items() if not r["contaminated"]]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP42-COMPILE-FEASIBILITY",
        "ts": ts,
        "issue": 374,
        "s3_threshold_tok_s": round(S3_THRESHOLD, 1),
        "budget_tokens": BUDGET_TOKENS,
        "assumptions": {
            "realistic_compile_x": REALISTIC_COMPILE,
            "realistic_fusedmuon_x": REALISTIC_FUSED,
            "max_plausible_per_lever_x": MAX_PLAUSIBLE,
            "model": "tok_s' = tok_s / ((1-opt_share)/s_c + opt_share/s_m); compile speeds model only, fused-muon speeds optimizer only",
        },
        "candidates": results,
        "clean_reference_candidates": clean,
        "finding": (
            "Compile alone is INSUFFICIENT: for c03 (opt_share 0.41) compile-alone "
            "needs s_c>=2.37x (implausible). §3 clears only with BOTH compile AND "
            "fused-muon, each ~1.5x — but 1.5/1.5 lands at 25251, 0.8% SHORT of 25463 "
            "(thin margin; one lever must slightly over-deliver, e.g. fused 1.53x at "
            "compile 1.5x). #329 (fused-muon) is therefore LOAD-BEARING on the "
            "critical path, not a side optimization."
        ),
        "decision_rule": (
            "Break BOTH walls: #373 (compile) + #329 (fused-muon). Re-bench c03 SOLO "
            "compiled+fused. Clean-re-bench the 4 contaminated candidates (parallel "
            "dispatch made their tok_s lower-bounds only). Escalation trigger: ONLY if "
            "a real compiled+fused solo re-bench is still < 25463 tok/s does the <=1-day "
            "bar become the user's call (wall-day fraction). Budget cut is NOT ours — "
            "only the user reduces scope."
        ),
        "caveats": [
            "s_c/s_m independence + multiplicativity is an approximation; binding verdict = measured re-bench",
            "4 of 5 candidates contaminated by 4-way parallel GPU dispatch (tok_s = lower bounds)",
            "c03 solo is the only valid §3 reference in this batch",
        ],
    }
    out = f"{RECEIPTS}/fp42-compile-feasibility-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps({
        "s3_threshold": round(S3_THRESHOLD, 1),
        "clean_reference": clean,
        "c03": results.get("c03-h1024-d20"),
    }, indent=2))
    print(f"FP42_COMPILE_FEASIBILITY_DONE {os.path.relpath(out, NC)}")


def selftest():
    ok = True
    # 1. no-op levers reproduce eager
    t = tok_s_after(16834, 0.4137, 1.0, 1.0)
    c1 = abs(t - 16834) < 1e-6
    # 2. compile-alone required for c03 ~ 2.37x
    sc = required_s_c_alone(16834, 0.4137)
    c2 = sc is not None and abs(sc - 2.370) < 0.01
    # 3. at compile 1.5x, fused-muon required ~1.53x
    sm = required_s_m_given_sc(16834, 0.4137, 1.5)
    c3 = sm is not None and abs(sm - 1.531) < 0.01
    # 4. joint 1.5x/1.5x is MARGINALLY SHORT (25251 < 25463); 1.6/1.6 clears
    proj_15 = tok_s_after(16834, 0.4137, 1.5, 1.5)
    proj_16 = tok_s_after(16834, 0.4137, 1.6, 1.6)
    c4 = (proj_15 < S3_THRESHOLD) and (proj_16 >= S3_THRESHOLD)
    # 5. opt floor too high => compile-alone impossible (opt_share high, low tok_s)
    c5 = required_s_c_alone(20000, 0.95) is None  # tok_s/target=0.785 < 0.95 => None
    for lbl, ok_i in [("noop-eager", c1), ("c03 compile-alone~2.37", c2),
                      ("c03 fused@1.5~1.53", c3), ("joint 1.5/1.5 clears", c4),
                      ("opt-floor impossible", c5)]:
        print(f"  [{'PASS' if ok_i else 'FAIL'}] {lbl}")
        ok = ok and ok_i
    print("FP42_FEASIBILITY_SELFTEST_" + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    analyze()
