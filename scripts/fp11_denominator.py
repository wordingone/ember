"""fp11_denominator.py — governed-wall-clock denominator robustness (#75, fp-11).

Every efficiency number on the record (bits/GPU-min, the fp-9 parity
verdict, the 785.5x gen-vs-verify ratio) divides by GOVERNED wall-clock:
generation time that INCLUDES deliberate pacing (headroom rule). Pacing
is absorbed asymmetrically — the same absolute pause is a larger FRACTION
of the faster core's wall — so the question (minted by fp-8) is whether
any headline ORDERING flips when the denominator is re-accounted.

Three accountings (pre-registered here, then computed):
  A1 as-receipted   — governed wall-clock (the current record).
  A2 throttle-exact — subtract the inter-batch sleep, EXACTLY computable
                      from receipts: ceil(n_gens/batch_size) * THROTTLE_S.
  A3 pacer-modeled  — additionally subtract the decode pacer
                      (PACE_S every PACE_EVERY decode steps), with decode
                      steps per batch MODELED from the samples files:
                      batches reconstructed via the generate_chat
                      length-sort, steps_b = max estimated completion
                      tokens in the batch (len(src)+fence overhead over
                      CHARS_PER_TOK, capped at max_new; extraction-fail
                      rows = max_new). The token estimate is a MODEL —
                      flag carried on the receipt, like fp-9's ext rates.

Verdict (pre-registered): ROBUST iff (a) the sampler-valued bits/min
ordering (1.5B vs 3B) is identical under A1/A2/A3, AND (b) the fp-9
ext-corrected parity verdict (CI vs 1.0) is unchanged under A1/A2/A3.
The fp-9 bootstrap CI is over task resampling with FIXED denominators,
so a re-accounting multiplies the whole draw distribution by one scalar
s = (G3'/G3)/(G15'/G15): CI bounds scale exactly — no re-bootstrap
needed. The receipt also quotes the FLIP THRESHOLD: the scalar s* that
would push the corrected CI lower bound to 1.0, expressed as the pacing
differential it would require, and whether that differential is
physically reachable given the max_new pacer ceiling.

CPU-from-receipts, runs anywhere. `python fp11_denominator.py --selftest`.
"""
import json
import math
import sys
from datetime import datetime, timezone

NC_WIN = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC_WIN}/receipts"
LEGS = {
    "q15": {"receipt": f"{RECEIPTS}/w1-floor-q15-20260610T202511Z.json",
            "samples": f"{RECEIPTS}/w1-floor-q15-20260610T202511Z-samples.jsonl"},
    "q3": {"receipt": f"{RECEIPTS}/w1-floor-q3-20260610T203401Z.json",
           "samples": f"{RECEIPTS}/w1-floor-q3-20260610T203401Z-samples.jsonl"},
}
# pacing constants as deployed (t1_probe.py defaults; env overrides not
# receipted — flag carried)
THROTTLE_S = 0.6
PACE_EVERY = 32
PACE_S = 0.5
CHARS_PER_TOK = 3.5    # Qwen coder text, modeled — flag carried
FENCE_OVERHEAD = 40    # ``` fences + trailing prose not in src, modeled
# fp-9 receipt (fp9-parity-20260611T002323Z.json): ext-corrected leg
FP9_CORRECTED = {"point": 1.02, "ci95": [0.867, 1.203]}
FP9_UNCORRECTED = {"point": 1.07, "ci95": [0.834, 1.367]}
# verify-timing receipt 20260611T000148Z: per-sample pooled ms
VERIFY_TIMING = {"gen_ms": 410.76, "verify_ms": 0.52, "ratio": 785.5}


def est_tokens(src, max_new=512, none_tokens=None):
    """Modeled completion length in decode steps for one sample row.
    none_tokens: what an extraction-fail row is assumed to have generated —
    default max_new (ran to the cap, the likely case); the sensitivity leg
    passes 0 (the opposite bracket). Adversarial-verify catch 2026-06-11:
    the legs have UNEQUAL None counts (q15 1, q3 0), so this assumption is
    an ASYMMETRIC channel and must be bracketed, not just flagged."""
    if src is None:
        return max_new if none_tokens is None else none_tokens
    return min(max_new, math.ceil((len(src) + FENCE_OVERHEAD) / CHARS_PER_TOK))


def reconstruct_batches(rows, batch_size):
    """generate_chat sorts prompts by templated length (template wrapper is
    constant, so len(prompt) ordering is the same; stable sort) and batches
    in that order. Returns list of batches of row indices."""
    order = sorted(range(len(rows)), key=lambda i: len(rows[i]["prompt"]))
    return [order[i:i + batch_size] for i in range(0, len(order), batch_size)]


def pacer_secs(rows, batch_size, max_new=512,
               pace_every=PACE_EVERY, pace_s=PACE_S, none_tokens=None):
    """Modeled decode-pacer sleep: per batch, fires = floor(steps/pace_every)
    where steps = the batch's longest completion (generation runs until the
    longest sequence finishes)."""
    total = 0.0
    for batch in reconstruct_batches(rows, batch_size):
        steps = max(est_tokens(rows[i]["src"], max_new, none_tokens)
                    for i in batch)
        total += (steps // pace_every) * pace_s
    return round(total, 1)


def throttle_secs(n_gens, batch_size, throttle_s=THROTTLE_S):
    return round(math.ceil(n_gens / batch_size) * throttle_s, 1)


def sampler_valued_bits(samples_path):
    """Each core's verified mass under its OWN posterior (fp-1 semantics):
    sum_t s_t * bits(laplace(s_t, n_t))."""
    from fp7_revalue import counts
    from vbits import bits, laplace_phat
    c = counts(samples_path)
    return round(sum(v["s"] * bits(laplace_phat(v["s"], v["n"]))
                     for v in c.values()), 1)


def scale_factor(g15, g3, g15_new, g3_new):
    """fp-9 ratio = (num15/num3) * (G3/G15): re-accounting both denominators
    multiplies every bootstrap draw by s = (G3'/G3) / (G15'/G15)."""
    return (g3_new / g3) / (g15_new / g15)


def parity_verdict(point, lo, hi):
    if lo > 1.0:
        return "edge-real"
    if hi < 1.0:
        return "edge-negative"
    return "cost-parity"


def main():
    sys.path.insert(0, f"{NC_WIN}/scripts")
    legs = {}
    for tag, paths in LEGS.items():
        r = json.load(open(paths["receipt"], encoding="utf-8"))
        rows = [json.loads(line) for line in
                open(paths["samples"], encoding="utf-8")]
        n_gens = len(rows)
        bs = r["args"]["batch_size"]
        wall = r["gen_secs"]
        thr = throttle_secs(n_gens, bs)
        pac = pacer_secs(rows, bs, r["args"]["max_new"])
        pac_none0 = pacer_secs(rows, bs, r["args"]["max_new"], none_tokens=0)
        bits_total = sampler_valued_bits(paths["samples"])
        srcs = [row["src"] for row in rows]
        legs[tag] = {
            "wall_secs": wall, "n_gens": n_gens, "batches": math.ceil(n_gens / bs),
            "throttle_secs": thr, "pacer_secs_modeled": pac,
            "pacer_secs_none0": pac_none0,
            "n_extraction_fail_rows": sum(1 for s in srcs if s is None),
            "mean_src_chars": round(sum(len(s) for s in srcs if s) /
                                    max(sum(1 for s in srcs if s), 1), 1),
            "sampler_valued_bits": bits_total,
            "A1_secs": wall,
            "A2_secs": round(wall - thr, 1),
            "A3_secs": round(wall - thr - pac, 1),
            "A3_none0_secs": round(wall - thr - pac_none0, 1),
        }
        assert legs[tag]["A3_secs"] > 0, (tag, legs[tag])

    q15, q3 = legs["q15"], legs["q3"]
    accountings = {}
    for acc in ("A1", "A2", "A3"):
        g15, g3 = q15[f"{acc}_secs"] / 60, q3[f"{acc}_secs"] / 60
        bpm15 = round(q15["sampler_valued_bits"] / g15, 1)
        bpm3 = round(q3["sampler_valued_bits"] / g3, 1)
        s = scale_factor(q15["A1_secs"] / 60, q3["A1_secs"] / 60, g15, g3)
        cor = {"point": round(FP9_CORRECTED["point"] * s, 3),
               "ci95": [round(FP9_CORRECTED["ci95"][0] * s, 3),
                        round(FP9_CORRECTED["ci95"][1] * s, 3)]}
        unc = {"point": round(FP9_UNCORRECTED["point"] * s, 3),
               "ci95": [round(FP9_UNCORRECTED["ci95"][0] * s, 3),
                        round(FP9_UNCORRECTED["ci95"][1] * s, 3)]}
        accountings[acc] = {
            "gen_min": {"q15": round(g15, 3), "q3": round(g3, 3)},
            "bits_per_min_sampler_valued": {"q15": bpm15, "q3": bpm3},
            "ordering": "q15>q3" if bpm15 > bpm3 else "q3>=q15",
            "denominator_scale_s": round(s, 4),
            "fp9_corrected": {**cor, "verdict": parity_verdict(
                cor["point"], *cor["ci95"])},
            "fp9_uncorrected": {**unc, "verdict": parity_verdict(
                unc["point"], *unc["ci95"])},
        }

    orderings = {a["ordering"] for a in accountings.values()}
    verdicts = {a["fp9_corrected"]["verdict"] for a in accountings.values()}
    robust = len(orderings) == 1 and len(verdicts) == 1

    # flip threshold: scalar s* pushing the corrected CI lower bound to 1.0,
    # and the pacing differential it would take, vs the physical ceiling
    s_star = 1.0 / FP9_CORRECTED["ci95"][0]
    # holding q3 at its A3 share, the q15 compute share that yields s*:
    share3_a3 = q3["A3_secs"] / q3["wall_secs"]
    share15_needed = share3_a3 / s_star
    extra_pacing_q15 = round(q15["wall_secs"] * (q15["A3_secs"] /
                             q15["wall_secs"] - share15_needed), 1)
    pacer_ceiling_q15 = round(q15["batches"] * (512 // PACE_EVERY) * PACE_S, 1)
    flip = {
        "s_star_to_flip_corrected_parity": round(s_star, 4),
        "q15_compute_share_needed": round(share15_needed, 4),
        "extra_q15_pacing_secs_beyond_A3": extra_pacing_q15,
        "q15_pacer_hard_ceiling_secs": pacer_ceiling_q15,
        "physically_reachable": extra_pacing_q15 <= (
            pacer_ceiling_q15 - q15["pacer_secs_modeled"]),
    }

    # None-assumption sensitivity (adversarial-verify catch): the legs have
    # unequal extraction-fail counts, so the None->max_new assumption is an
    # asymmetric channel. Bracket it: recompute s_A3 and the corrected
    # verdict with None rows assumed 0 tokens (opposite extreme).
    g15_n0 = q15["A3_none0_secs"] / 60
    g3_n0 = q3["A3_none0_secs"] / 60
    s_n0 = scale_factor(q15["A1_secs"] / 60, q3["A1_secs"] / 60,
                        g15_n0, g3_n0)
    cor_n0 = {"point": round(FP9_CORRECTED["point"] * s_n0, 3),
              "ci95": [round(FP9_CORRECTED["ci95"][0] * s_n0, 3),
                       round(FP9_CORRECTED["ci95"][1] * s_n0, 3)]}
    none_sensitivity = {
        "channel": "extraction-fail rows assumed max_new tokens; counts are "
                   "UNEQUAL across legs (asymmetric model channel)",
        "none_rows": {"q15": q15["n_extraction_fail_rows"],
                      "q3": q3["n_extraction_fail_rows"]},
        "s_A3_none0": round(s_n0, 4),
        "fp9_corrected_none0": {**cor_n0, "verdict": parity_verdict(
            cor_n0["point"], *cor_n0["ci95"])},
        "bracket_note": "A3 verdict quoted only if BOTH None brackets agree",
    }
    a3_verdicts = {accountings["A3"]["fp9_corrected"]["verdict"],
                   none_sensitivity["fp9_corrected_none0"]["verdict"]}
    a3_settled = len(a3_verdicts) == 1

    # the 785.5x gen-vs-verify ratio under the same shares (context line)
    share15 = {a: q15[f"{a}_secs"] / q15["wall_secs"] for a in
               ("A1", "A2", "A3")}
    v_ratio = {a: round(VERIFY_TIMING["ratio"] * share15[a], 1)
               for a in share15}

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP11-DENOMINATOR", "ts": ts,
        "constants": {"THROTTLE_S": THROTTLE_S, "PACE_EVERY": PACE_EVERY,
                      "PACE_S": PACE_S, "CHARS_PER_TOK": CHARS_PER_TOK,
                      "FENCE_OVERHEAD": FENCE_OVERHEAD},
        "legs": legs,
        "accountings": accountings,
        "verdict": "ROBUST" if robust else "NOT-ROBUST",
        "verdict_rule": "ordering identical AND fp-9 corrected parity "
                        "verdict unchanged across A1/A2/A3",
        "a3_none_bracket_settled": a3_settled,
        "none_sensitivity": none_sensitivity,
        "flip_threshold": flip,
        "verify_timing_ratio_context": {
            "as_receipted": VERIFY_TIMING["ratio"],
            "rescaled_by_q15_compute_share": v_ratio,
            "note": "orders-of-magnitude conclusion (generation is the "
                    "binding resource) untouched by any accounting"},
        "flags": [
            "A3 decode-step counts are MODELED from src char lengths "
            "(CHARS_PER_TOK + FENCE_OVERHEAD constants); A2 is exact",
            "extraction-fail None->max_new is an ASYMMETRIC channel "
            "(unequal None counts across legs) — bracketed in "
            "none_sensitivity, not just flagged",
            "pacing env overrides (EMBER_*) not receipted at run time — "
            "code defaults assumed",
            "fp-9 CI rescaling is exact only because denominators are "
            "constants inside every bootstrap draw",
        ],
    }
    out = f"{RECEIPTS}/fp11-denominator-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP11_DENOMINATOR_DONE {out}")


def _selftest():
    # token model: None -> cap; short src -> ceil((len+40)/3.5); cap binds
    assert est_tokens(None) == 512
    assert est_tokens("x" * 30) == math.ceil(70 / 3.5)
    assert est_tokens("x" * 10000) == 512
    # batch reconstruction: stable length-sort, correct chunking
    rows = [{"prompt": "bb"}, {"prompt": "a"}, {"prompt": "ccc"},
            {"prompt": "dd"}]
    b = reconstruct_batches(rows, 2)
    assert b == [[1, 0], [3, 2]], b  # 'a' first; tie bb/dd stable by index
    # pacer: steps below pace_every -> zero fires
    rows0 = [{"src": "x" * 30, "prompt": "p"}] * 4   # 20 tokens < 32
    assert pacer_secs(rows0, 2) == 0.0
    # one fire per batch at 32..63 steps
    rows1 = [{"src": "x" * 200, "prompt": "p"}] * 4  # ceil(240/3.5)=69 -> 2 fires
    assert pacer_secs(rows1, 2) == 2 * (69 // 32) * 0.5
    # None bracket: max_new default vs 0; a None row dominates its batch
    # under the default and vanishes under none_tokens=0
    rows_n = [{"src": None, "prompt": "p"}, {"src": "x" * 30, "prompt": "p"}]
    assert pacer_secs(rows_n, 2) == (512 // 32) * 0.5
    assert pacer_secs(rows_n, 2, none_tokens=0) == 0.0
    # throttle: ceil semantics
    assert throttle_secs(960, 8) == 72.0
    assert throttle_secs(9, 8) == 1.2
    # scale algebra: ratio = (num15/num3)*(G3/G15) -> equal-share change
    # cancels; one-sided change moves it the documented direction
    assert abs(scale_factor(6, 7, 4.8, 5.6) - 1.0) < 1e-9
    assert scale_factor(6, 7, 3.0, 7.0) > 1.0   # q15 cheaper -> ratio up
    assert scale_factor(6, 7, 6.0, 3.5) < 1.0   # q3 cheaper -> ratio down
    # parity verdict rule
    assert parity_verdict(1.02, 0.87, 1.2) == "cost-parity"
    assert parity_verdict(1.3, 1.05, 1.6) == "edge-real"
    assert parity_verdict(0.8, 0.6, 0.95) == "edge-negative"
    print("FP11_DENOMINATOR_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
