"""fp21b_prereg.py — band-transfer prong-A RE-EXECUTION on round-3 sampling,
frozen BEFORE round-3 exists (#132, successor to fp-21 #120).

fp-21 executed the frozen fp-15 prong-A prereg on the round-2 sampling
receipts: INCONCLUSIVE — yield ratio 1.341 < 1.5, perm p 0.104; direction
favored the band (+34%) but neither bar cleared; prong B did not fire
(receipt fp15-bandtransfer-20260611T033030Z, audit §8.28). The question
"does the fp-12 band PREDICT where sampling GPU should go" survived round-2
unresolved. fp-21b is its LAST round at these bars.

FROZEN HERE (changing any after a round-3 sampling receipt exists is a
deviation, audit-§6 registry):

  1. SAME bars, imported from fp15_bandtransfer — never copied, never
     retuned: RATIO_BAR 1.5, PERM_N 10k, SEED 17, one-sided permutation.
  2. SAME band predicate: fp12_band.band_member on the ROUND-1 per-task
     stats from the three fp12-pinned samples files, q3 side POOLED
     k8 + focus-k24 (the fp-21 join precedent, declared pre-yield).
     Band membership is NEVER recomputed from round-2/3 outcomes.
  3. Round-3 yield join mirrors fp-21: k_sampled = round-3 sample rows per
     task; new_verified = ledger round==3 verified rows (post-dedup banked
     NEW); universe = round-3-sampled tasks with joint round-1 coverage,
     out-of-universe counts recorded.
  4. ROUND-2 INPUT PINNED + TAMPER-GUARDED: the prior result is read from
     the committed fp-21 receipt and must match the pinned values below
     (ratio 1.341, perm_p 0.104, INCONCLUSIVE) or this executor REFUSES —
     the cross-round rule may never be fed a re-derived round-2.
  5. CROSS-ROUND DECISION (the #132 kill rule, frozen):
       round-3 PREDICTIVE          -> PREDICTIVE: prong B fires (matched
                                      band-only vs nonband-only arms, G1
                                      paired delta decides transfer).
       round-3 REFUTED-direction   -> ANTI-PREDICTIVE: the question dies;
                                      band leaves the planning table with a
                                      negative receipt (spending sampling
                                      GPU by band would be WRONG-signed).
       round-3 INCONCLUSIVE        -> NOT-PREDICTIVE-AT-THIS-SCALE: the
                                      question DIES (two consecutive
                                      inconclusive rounds at frozen bars;
                                      no third round, no bar movement).
                                      NB: INCONCLUSIVE includes ratio>=1.5
                                      with p>=0.05 — "not proven at this
                                      scale" is still death, by design.
       round-3 INCOMPUTABLE        -> PROTOCOL-FLAG (empty split = a join
                                      or coverage fault, not a verdict).
     Death is a verdict, not a stall: it retires the band from sampling-
     allocation duty and frees fp-12's result to remain a CALIBRATION
     finding only. A kill specifies what comes next (successor below).

`--selftest` pure-logic. main() without a round-3 samples file prints the
STAGED sentinel; running the verdict early would un-freeze the prereg.
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fp15_bandtransfer import (  # noqa: E402 — frozen single source, never copied
    PERM_N, RATIO_BAR, SEED, _per_task_stats, perm_pvalue, split_yield, verdict,
)
from receipt_write import checked_write  # noqa: E402

# ---- frozen pins ----------------------------------------------------
R2_RECEIPT = "fp15-bandtransfer-20260611T033030Z.json"
R2_PIN = {"ratio": 1.341, "perm_p": 0.104, "verdict": "INCONCLUSIVE"}
ROUND = 3
# fp12-pinned round-1 legs (band membership inputs — same as fp-21's join)
R1_LEGS = {
    "q15": "w1-floor-q15-20260610T202511Z-samples.jsonl",
    "q3_k8": "w1-floor-q3-20260610T203401Z-samples.jsonl",
    "q3_focus_k24": "w1-floor-q3-focus-20260610T210228Z-samples.jsonl",
}


# ---- world-applicability pin (PRE-DATA amendment 2026-06-11, refs #132;
# added BEFORE any round-3 sampling receipt exists) ----
# The bars (RATIO_BAR/PERM_N/SEED) and the R1 band legs are DERIVED ON
# the borrowed-core w1-MBPP world. The fp-26 shape decision
# (research/fp26-round3-shape-decision.md) makes the next sampling round
# most likely the OWNED core in the fp-22 world. Cross-world application
# of these bars + borrowed band legs would be silent methodological
# breakage; the executor refuses it mechanically: sampling from a
# different model/world -> NOT-APPLICABLE-WORLD-CHANGED (fresh prong-A
# derivation required in the new world; the issue retargets, the bars do
# NOT carry).
WORLD_PIN = {"model": "Qwen/Qwen2.5-Coder-3B-Instruct",
             "world": "w1-mbpp"}


def check_sampling_world(sampling_samples_path):
    """Gate the round-3 sampling source against WORLD_PIN via its sibling
    receipt's args.model. Returns (verdict_or_None, detail); None =
    applicable, proceed."""
    rp = sampling_samples_path.replace("-samples.jsonl", ".json")
    if rp == sampling_samples_path or not os.path.exists(rp):
        return ("PROTOCOL-FLAG",
                f"no sibling receipt for {sampling_samples_path} — world "
                f"unverifiable, refusing to apply borrowed-world bars")
    rec = json.load(open(rp, encoding="utf-8"))
    model = rec.get("args", {}).get("model")
    if model != WORLD_PIN["model"]:
        return ("NOT-APPLICABLE-WORLD-CHANGED",
                f"sampling model {model!r} != pinned "
                f"{WORLD_PIN['model']!r} — fp-21b bars/band-legs are "
                f"borrowed-world artifacts; derive a fresh prong-A prereg "
                f"in the new world")
    return (None, "world pin intact")


def check_r2_pin(r2_receipt_path):
    """Tamper guard: the committed fp-21 receipt must carry exactly the
    pinned round-2 result. Returns mismatch list (empty = intact)."""
    rec = json.load(open(r2_receipt_path, encoding="utf-8"))
    res = rec.get("result", {})
    out = []
    if round(res.get("ratio", -1), 3) != R2_PIN["ratio"]:
        out.append({"field": "ratio", "pinned": R2_PIN["ratio"],
                    "found": res.get("ratio")})
    if round(rec.get("perm_p", -1), 3) != R2_PIN["perm_p"]:
        out.append({"field": "perm_p", "pinned": R2_PIN["perm_p"],
                    "found": rec.get("perm_p")})
    if res.get("verdict") != R2_PIN["verdict"]:
        out.append({"field": "verdict", "pinned": R2_PIN["verdict"],
                    "found": res.get("verdict")})
    return out


def decide_21b(r3_verdict):
    """The frozen cross-round rule. r3_verdict = fp15 verdict() dict on the
    round-3 join (same bars). Returns the binding fp-21b disposition."""
    v = r3_verdict.get("verdict")
    if v == "PREDICTIVE":
        return {"verdict": "PREDICTIVE",
                "consequence": ("prong B fires: matched band-only vs "
                                "nonband-only training arms; G1 paired delta "
                                "decides transfer (yield alone cannot)")}
    if v == "REFUTED-direction":
        return {"verdict": "ANTI-PREDICTIVE",
                "consequence": ("question dies with a negative receipt: "
                                "allocating sampling GPU by band would be "
                                "wrong-signed; band retired from allocation "
                                "duty; fp-12 remains a calibration finding")}
    if v == "INCONCLUSIVE":
        return {"verdict": "NOT-PREDICTIVE-AT-THIS-SCALE",
                "consequence": ("question DIES: two consecutive inconclusive "
                                "rounds at the frozen bars (r2 1.341/p0.104, "
                                "r3 this receipt); no third round, no bar "
                                "movement; band retired from sampling-"
                                "allocation duty; fp-12 remains a "
                                "calibration finding only")}
    return {"verdict": "PROTOCOL-FLAG",
            "consequence": ("round-3 result incomputable (empty split = "
                            "join/coverage fault) — fix the join, not the "
                            "bars; the kill rule needs a computable r3")}


def _selftest():
    # bars are IMPORTED from fp15, not redefined — freeze-consistency
    assert RATIO_BAR == 1.5 and PERM_N == 10000 and SEED == 17
    # decide_21b: all four branches
    d = decide_21b({"verdict": "PREDICTIVE"})
    assert d["verdict"] == "PREDICTIVE" and "prong B" in d["consequence"]
    d = decide_21b({"verdict": "REFUTED-direction"})
    assert d["verdict"] == "ANTI-PREDICTIVE"
    d = decide_21b({"verdict": "INCONCLUSIVE"})
    assert d["verdict"] == "NOT-PREDICTIVE-AT-THIS-SCALE"
    assert "DIES" in d["consequence"]
    assert decide_21b({"verdict": "INCOMPUTABLE"})["verdict"] == \
        "PROTOCOL-FLAG"
    # world-applicability gate: pinned model passes; foreign model ->
    # NOT-APPLICABLE-WORLD-CHANGED; missing sibling -> PROTOCOL-FLAG
    import tempfile
    import os as _os
    with tempfile.TemporaryDirectory() as td:
        sp = _os.path.join(td, "x-samples.jsonl")
        open(sp, "w", encoding="utf-8").write("{}\n")
        v, _d = check_sampling_world(sp)
        assert v == "PROTOCOL-FLAG", v
        rp = _os.path.join(td, "x.json")
        json.dump({"args": {"model": WORLD_PIN["model"]}},
                  open(rp, "w", encoding="utf-8"))
        v, _d = check_sampling_world(sp)
        assert v is None, v
        json.dump({"args": {"model": "ember-v0-0.37b"}},
                  open(rp, "w", encoding="utf-8"))
        v, _d = check_sampling_world(sp)
        assert v == "NOT-APPLICABLE-WORLD-CHANGED", v

    # r2 pin guard: matching receipt passes, tampered ratio caught
    good = {"result": {"ratio": 1.341, "verdict": "INCONCLUSIVE"},
            "perm_p": 0.104}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tf:
        json.dump(good, tf)
        gp = tf.name
    assert check_r2_pin(gp) == []
    bad = {"result": {"ratio": 2.0, "verdict": "INCONCLUSIVE"},
           "perm_p": 0.104}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tf:
        json.dump(bad, tf)
        bp = tf.name
    mm = check_r2_pin(bp)
    assert mm and mm[0]["field"] == "ratio", mm
    os.unlink(gp)
    os.unlink(bp)
    # the imported fp15 machinery still behaves (spot: strong separation
    # -> PREDICTIVE under the same frozen bars)
    mk = lambda b, k, v: {"task": f"t{b}{k}{v}", "band": b,
                          "k_sampled": k, "new_verified": v}
    tasks = [mk(True, 8, 4) for _ in range(10)] + \
            [mk(False, 8, 1) for _ in range(10)]
    p, obs = perm_pvalue(tasks, n=2000)
    assert verdict(obs, p)["verdict"] == "PREDICTIVE"
    # composition: r3 INCONCLUSIVE through decide_21b == death
    tasks2 = [mk(True, 8, 2) for _ in range(10)] + \
             [mk(False, 8, 2) for _ in range(10)]
    p2, obs2 = perm_pvalue(tasks2, n=2000)
    assert decide_21b(verdict(obs2, p2))["verdict"] == \
        "NOT-PREDICTIVE-AT-THIS-SCALE"
    print("FP21B_PREREG_SELFTEST_PASS")


def main():
    """Fire-time executor: identical join to fp-21 (declared there,
    reused here) with round==3 ledger rows + the round-3 samples file."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sampling", help="round-3 w1 *-samples.jsonl")
    ap.add_argument("--ledger", default=None)
    a, _ = ap.parse_known_args()
    if not a.sampling:
        print("FP21B_PREREG_STAGED (no round-3 sampling receipt exists yet; "
              "bars + join + r2 pin + cross-round kill rule frozen in this "
              "file — fp-21b executes when round-3 sampling lands)")
        return
    NC = os.path.dirname(HERE)
    R = f"{NC}/receipts"
    world_verdict, world_detail = check_sampling_world(a.sampling)
    if world_verdict:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        refusal = {"ticket": "FP21B-WORLD-GATE", "ts": ts,
                   "sampling": os.path.basename(a.sampling),
                   "world_pin": WORLD_PIN,
                   "result": {"verdict": world_verdict,
                              "detail": world_detail},
                   "sha_convention": ("file shas = sha256 over on-disk "
                                      "raw bytes")}
        out = f"{R}/fp21b-world-gate-{ts}.json"
        checked_write(out, refusal)
        print(json.dumps(refusal["result"], indent=2))
        print(f"FP21B_WORLD_GATE_REFUSAL {out}")
        return
    mism = check_r2_pin(f"{R}/{R2_RECEIPT}")
    if mism:
        raise SystemExit(f"fp21b: round-2 pin mismatch {mism} — refusing "
                         f"(the kill rule may not run on a drifted r2)")
    from fp12_band import band_member  # frozen single source

    s15 = _per_task_stats(f"{R}/{R1_LEGS['q15']}")
    q3a = _per_task_stats(f"{R}/{R1_LEGS['q3_k8']}")
    q3b = _per_task_stats(f"{R}/{R1_LEGS['q3_focus_k24']}")
    q3 = {}
    for t in set(q3a) | set(q3b):
        va, na = q3a.get(t, (0, 0))
        vb, nb = q3b.get(t, (0, 0))
        q3[t] = (va + vb, na + nb)

    r3_k = {}
    with open(a.sampling, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                t = json.loads(line)["task"]
                r3_k[t] = r3_k.get(t, 0) + 1
    ledger = a.ledger or f"{NC}/ledger/episodes.jsonl"
    new_v = {}
    with open(ledger, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("round") == ROUND and rec.get("verified"):
                new_v[rec["task"]] = new_v.get(rec["task"], 0) + 1

    tasks, no_joint = [], []
    for t, k in sorted(r3_k.items()):
        v15, n15 = s15.get(t, (0, 0))
        v3, n3 = q3.get(t, (0, 0))
        if n15 == 0 or n3 == 0:
            no_joint.append(t)
            continue
        tasks.append({"task": t, "band": band_member(v15, n15, v3, n3),
                      "k_sampled": k, "new_verified": new_v.get(t, 0)})

    p, obs = perm_pvalue(tasks)
    r3 = verdict(obs, p)
    final = decide_21b(r3)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP21B-BANDTRANSFER", "ts": ts, "prong": "A-r3",
        "frozen_bars": {"ratio_bar": RATIO_BAR, "perm_n": PERM_N,
                        "seed": SEED, "source": "fp15_bandtransfer (imported)"},
        "r2_pin": {"receipt": R2_RECEIPT, **R2_PIN, "verified_intact": True},
        "join": {"band_inputs": R1_LEGS,
                 "q3_side": "POOLED k8 + focus-k24 (fp-21 precedent)",
                 "new_verified_source": f"ledger round=={ROUND} verified rows",
                 "sampling": os.path.basename(a.sampling)},
        "universe": {"r3_sampled_tasks": len(r3_k),
                     "joint_coverage_tasks": len(tasks),
                     "no_joint_round1_stats": len(no_joint),
                     "band_tasks": sum(1 for t in tasks if t["band"]),
                     "nonband_tasks": sum(1 for t in tasks if not t["band"])},
        "observed": obs, "perm_p": p, "r3_result": r3,
        "result": final,
    }
    out = f"{R}/fp21b-bandtransfer-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"FP21B_PREREG_DONE {out}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
