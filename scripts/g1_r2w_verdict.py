"""g1_r2w_verdict.py — repaired round-2 G1 verdict (Kai HARD HOLD 14528).

w4_eval emits `<arm>_minus_base_ci95` for every non-base arm, but it only
emits the trained-vs-control delta when arms are LITERALLY named "trained"
and "control" (both the bootstrap and the exact block gate on that literal
name). w4_r2_g1 names the trained arms sft/mtp/grpo, so the terminal
w4-eval-r2w-q3 receipt carries base-deltas but NOT
sft/mtp/grpo − control — which the round-2 advance rule REQUIRES (prereg
§1.3: each arm − base AND each trained arm − control, both CIs exclude 0,
AND powered-t5 harm_flag false).

This is the receipt-backed repair Kai named: it does NOT rerun the GPU
eval — it reads the per-sample rows the G1 job already wrote and computes
the missing paired deltas with the SAME pre-registered methods used in
r1 (g1_paired.compare → power.newcombe_paired_delta for the task-level
feed counts + 10k paired bootstrap seed-16 for the per-sample rate, the
primary gains metric). compare() is arm-name-agnostic, so reusing it
keeps the binding analysis identical to r1; only the arm labels differ.

The repaired receipt this writes is the BINDING G1 verdict; the raw
w4-eval receipt is demoted to the sample/base-delta source. As a
consistency check, the recomputed `<arm>_minus_base` is compared to
w4_eval's own `<arm>_minus_base_ci95` (the feed Newcombe must match — same
inputs, same method).

`--selftest` pure-logic. Live:
  python g1_r2w_verdict.py --samples receipts/w4-eval-r2w-q3-<ts>-samples.jsonl \
         --w4-receipt receipts/w4-eval-r2w-q3-<ts>.json
"""
import json
import os
import random
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from g1_paired import compare  # noqa: E402  (reuses the r1 pre-registered methods)

TRAINED = ("sft", "mtp", "grpo")
BASE = "base"
CONTROL = "control"


def load_tab(samples_path):
    """Combined w4_eval samples.jsonl -> (tab, order).

    tab = {arm: {tid: [0/1 x k]}}; rows accumulate per (arm, tid) in file
    order = the k samples for that task. `order` = tids by FIRST appearance
    across the file, which reproduces w4_eval's load_split task order (the
    first arm's rows are written problem-order x k) — needed so the
    reconstruction crosscheck's paired bootstrap RNG walks the pairs in the
    same sequence w4_eval used."""
    tab, order, seen = {}, [], set()
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            arm = r["arm"]
            tid = r["tid"]
            if tid not in seen:
                seen.add(tid)
                order.append(tid)
            tab.setdefault(arm, {}).setdefault(tid, []).append(
                1 if r.get("verified") else 0)
    return tab, order


def advance_decision(vs_base, vs_control):
    """prereg §1.3 gains rule on the PRIMARY metric (per-sample rate,
    bootstrap): a trained arm ADVANCES iff it is UP vs base AND UP vs
    control. The task-level feed (Newcombe exact) is reported alongside;
    a feed/sample disagreement is surfaced, never silently dropped.
    powered-t5 harm_flag is a SEPARATE downstream leg (not decided here)."""
    sample_up = (vs_base["sample"]["flag"] == "UP"
                 and vs_control["sample"]["flag"] == "UP")
    feed_up = (vs_base["feed"]["flag"] == "UP"
               and vs_control["feed"]["flag"] == "UP")
    return {
        "advances_on_primary_sample_rate": sample_up,
        "feed_newcombe_both_up": feed_up,
        "metric_agreement": sample_up == feed_up,
        "note": ("ADVANCE on the primary per-sample-rate gains metric "
                 "requires UP vs base AND vs control; powered-t5 harm_flag "
                 "(separate leg) must also be false before round-3 default."),
    }


def build_verdict(tab):
    arms = set(tab)
    for need in (BASE, CONTROL, *TRAINED):
        if need not in arms:
            return {"error": f"missing arm {need!r}; have {sorted(arms)}"}
    # task-set identity across arms (paired analysis precondition)
    task_sets = {arm: set(tab[arm]) for arm in (BASE, CONTROL, *TRAINED)}
    ref_tasks = task_sets[BASE]
    for arm, ts in task_sets.items():
        if ts != ref_tasks:
            return {"error": f"task-set mismatch: {arm} has "
                             f"{len(ts)} vs base {len(ref_tasks)}"}
    blocks, decisions = {}, {}
    blocks["control_minus_base"] = compare(tab, CONTROL, BASE)
    for arm in TRAINED:
        vb = compare(tab, arm, BASE)
        vc = compare(tab, arm, CONTROL)
        blocks[f"{arm}_minus_base"] = vb
        blocks[f"{arm}_minus_control"] = vc
        decisions[arm] = advance_decision(vb, vc)
    return {"blocks": blocks, "decisions": decisions,
            "n_tasks": len(ref_tasks)}


def _paired_delta_ci(a, b, n=10000, seed=7):
    """Verbatim copy of t4_eval.paired_delta_ci (pure-stdlib paired bootstrap,
    percent scale). Copied — not imported — because t4_eval's module import
    pulls torch via t1_probe. Same algorithm + seed => same CI given the same
    pair ordering, so this reproduces w4_eval's published delta exactly."""
    rng = random.Random(seed)
    pairs = list(zip(a, b))
    m = len(pairs)
    deltas = sorted(
        sum(x - y for x, y in rng.choices(pairs, k=m)) / m for _ in range(n))
    return [round(100 * deltas[int(n * q)], 2) for q in (0.025, 0.975)]


def crosscheck_base(tab, order, w4_receipt):
    """RECONSTRUCTION-FIDELITY check (not an estimator comparison). Rebuild
    each arm's pass-any vector from the rows I parsed, recompute w4_eval's
    OWN metric (paired_delta_ci, the same percent-scale bootstrap it ran),
    and require it to reproduce the published <arm>_minus_base_ci95 exactly.
    A match proves load_tab faithfully reconstructed the data the GPU job
    wrote — which is what licenses trusting the binding Newcombe/per-sample
    deltas in `blocks`. Returns mismatch list (empty = reconstruction sound).

    NB: w4_eval emits <arm>_minus_base for every non-base arm (incl control)
    but NOT <trained>_minus_control (the literal-name bug being repaired), so
    only the base-deltas are crosscheckable here — exactly the ones present."""
    w4 = json.load(open(w4_receipt, encoding="utf-8"))
    w4d = w4.get("deltas", {})

    def pass_any(arm):
        return [1 if any(tab[arm][tid]) else 0 for tid in order]

    base_v = pass_any(BASE)
    out = []
    for arm in (*TRAINED, CONTROL):
        key = f"{arm}_minus_base_ci95"
        if key in w4d and arm in tab:
            mine = _paired_delta_ci(pass_any(arm), base_v)
            theirs = w4d[key]
            if [round(x, 2) for x in mine] != [round(x, 2) for x in theirs]:
                out.append({"arm": arm, "recomputed": mine, "w4_eval": theirs})
    return out


def _selftest():
    # synthetic: 4 tasks, k=4. base weak, sft strong, control mid, mtp
    # strongest, grpo == base.
    def vec(*per_task):
        return {f"t{i}": list(v) for i, v in enumerate(per_task)}
    tab = {
        "base":    vec([0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]),
        "control": vec([1, 0, 0, 0], [1, 1, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]),
        "sft":     vec([1, 1, 1, 0], [1, 1, 1, 0], [1, 1, 0, 0], [1, 1, 1, 1]),
        "mtp":     vec([1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 0], [1, 1, 1, 1]),
        "grpo":    vec([0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]),
    }
    v = build_verdict(tab)
    assert "error" not in v, v
    assert set(v["blocks"]) == {
        "control_minus_base", "sft_minus_base", "sft_minus_control",
        "mtp_minus_base", "mtp_minus_control", "grpo_minus_base",
        "grpo_minus_control"}, sorted(v["blocks"])
    # grpo == base -> sample mean_diff ~0 vs base -> not UP -> no advance
    assert v["decisions"]["grpo"]["advances_on_primary_sample_rate"] is False
    # decision keys present for every trained arm
    for arm in TRAINED:
        d = v["decisions"][arm]
        assert "advances_on_primary_sample_rate" in d
        assert "metric_agreement" in d
    # missing-arm guard
    bad = {k: tab[k] for k in ("base", "sft")}
    assert "error" in build_verdict(bad)
    # task-set mismatch guard
    bad2 = {k: dict(tab[k]) for k in tab}
    del bad2["control"]["t0"]
    assert "error" in build_verdict(bad2)

    # _paired_delta_ci determinism (same seed -> identical CI)
    a0 = [1, 0, 1, 1]
    b0 = [0, 0, 1, 0]
    assert _paired_delta_ci(a0, b0) == _paired_delta_ci(a0, b0)

    # crosscheck round-trip: a faithful w4 receipt reconstructs (empty), a
    # corrupted one is caught. Reproduces w4_eval's own paired_delta_ci on
    # pass-any vectors built in the same task order.
    import tempfile
    order = [f"t{i}" for i in range(4)]

    def pa(arm):
        return [1 if any(tab[arm][tid]) else 0 for tid in order]
    faithful = {"deltas": {
        f"{arm}_minus_base_ci95": _paired_delta_ci(pa(arm), pa("base"))
        for arm in (*TRAINED, "control")}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tf:
        json.dump(faithful, tf)
        faithful_path = tf.name
    assert crosscheck_base(tab, order, faithful_path) == [], "faithful crosscheck"
    corrupt = {"deltas": dict(faithful["deltas"])}
    corrupt["deltas"]["sft_minus_base_ci95"] = [99.0, 99.0]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tf:
        json.dump(corrupt, tf)
        corrupt_path = tf.name
    cc = crosscheck_base(tab, order, corrupt_path)
    assert any(m["arm"] == "sft" for m in cc), ("corrupt crosscheck", cc)
    os.unlink(faithful_path)
    os.unlink(corrupt_path)
    print("G1_R2W_VERDICT_SELFTEST_PASS")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True,
                    help="w4-eval-r2w-q3-<ts>-samples.jsonl from the G1 job")
    ap.add_argument("--w4-receipt", default=None,
                    help="w4-eval-r2w-q3-<ts>.json (base-delta crosscheck)")
    a, _ = ap.parse_known_args()
    tab, order = load_tab(a.samples)
    verdict = build_verdict(tab)
    if "error" in verdict:
        raise SystemExit(f"g1_r2w_verdict: {verdict['error']}")
    crosscheck = None
    if a.w4_receipt:
        crosscheck = crosscheck_base(tab, order, a.w4_receipt)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    advancing = [arm for arm in TRAINED
                 if verdict["decisions"][arm]["advances_on_primary_sample_rate"]]
    receipt = {
        "ticket": "G1-R2W-VERDICT", "ts": ts,
        "samples_file": os.path.basename(a.samples),
        "w4_receipt": os.path.basename(a.w4_receipt) if a.w4_receipt else None,
        "basis": ("repairs Kai 14528: w4_eval omits <trained>_minus_control "
                  "(literal-name condition); recomputed from per-sample rows "
                  "with g1_paired.compare (r1 pre-registered methods: "
                  "Newcombe feed + 10k bootstrap seed-16 per-sample rate)"),
        "n_tasks": verdict["n_tasks"],
        "advance_rule": ("PRIMARY per-sample-rate UP vs base AND vs control; "
                         "powered-t5 harm_flag (separate leg) must be false "
                         "before round-3 default"),
        "advancing_arms_pre_t5": advancing,
        "base_delta_crosscheck_mismatches": crosscheck,
        "decisions": verdict["decisions"],
        "blocks": verdict["blocks"],
    }
    NC = os.path.dirname(HERE)
    out = f"{NC}/receipts/g1-r2w-verdict-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({"advancing_arms_pre_t5": advancing,
                      "decisions": verdict["decisions"],
                      "base_crosscheck": crosscheck}, indent=2))
    print(f"G1_R2W_VERDICT_DONE {out}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
