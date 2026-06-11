"""fp27b_round1_verdict.py — round-1 execution verdicts on real
owned-core round receipts (#205), STAGED FAIL-CLOSED.

Built before any round-1 receipt exists so the fire is mechanical (the
fp-28 pattern). Zero decisions at fire time — everything is frozen
upstream: pins in fp27_round1_prereg (seed/k/counts/split), grammar in
fp31_l2_grammar, verdict vocabulary in fp-27 (GAIN/FLAT/NEGATIVE by
paired CI on the binding arm).

Consumes the round-1 bundle:
  --sampling  the round's sampling receipt (carries per-task entries +
              the pacing block that fires the retargeted fp-20c #146)
  --gate      the round-gate eval receipt (binding sft arm, paired CI
              vs base on the round-gate split)

Split discipline is AUDITED, never trusted: every sampled task's bucket
is RE-DERIVED from (op_name, repr(input)) — L1 via fp23.bucket, L2
('+'-joined names) via the same convention — and must land in the train
range 10-89; every round-gate eval task must land in 90-99. A single
out-of-range instance fails the round receipt (leakage = invalid round,
not a deduction).

Verdict (frozen): GAIN  iff ci_low > 0
                  FLAT  iff ci_low <= 0 <= ci_high
                  NEGATIVE iff ci_high < 0
FLAT/NEGATIVE = data for round-2 design; never a rung-kill.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write               # noqa: E402
from receipt_check import validate_receipt             # noqa: E402
import fp23_probe_prereg as fp23                       # noqa: E402
import fp27_round1_prereg as fp27                      # noqa: E402

T0, T1 = fp27.TRAIN_BUCKETS
G0, G1 = fp27.ROUNDGATE_BUCKETS
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")


def _bucket(op_name, xs):
    """L1 and L2 share the convention: bucket(op_name, repr(input)) —
    fp-31 froze l2_bucket as exactly this with '+'-joined names."""
    return fp23.bucket(op_name, repr(xs))


def check_sampling(sr):
    """Findings on the sampling receipt: pins + audited split."""
    f = list(validate_receipt(sr))
    for k in ("ticket", "ts", "seed", "k", "tasks", "pacing", "governor"):
        if k not in sr:
            f.append(f"missing field: {k}")
    if f:
        return f
    if sr["seed"] != fp27.SAMPLING["seed"]:
        f.append(f"seed {sr['seed']} != frozen {fp27.SAMPLING['seed']}")
    if sr["k"] != fp27.SAMPLING["k"]:
        f.append(f"k {sr['k']} != frozen {fp27.SAMPLING['k']}")
    tasks = sr["tasks"]
    n_l1 = sum(1 for t in tasks if "+" not in t.get("op_name", ""))
    n_l2 = len(tasks) - n_l1
    if n_l1 != fp27.SAMPLING["n_tasks_l1"]:
        f.append(f"n_tasks_l1 {n_l1} != frozen {fp27.SAMPLING['n_tasks_l1']}")
    if n_l2 != fp27.SAMPLING["n_tasks_l2"]:
        f.append(f"n_tasks_l2 {n_l2} != frozen {fp27.SAMPLING['n_tasks_l2']}")
    for t in tasks:
        b = _bucket(t["op_name"], t["input"])
        if not (T0 <= b <= T1):
            f.append(f"LEAKAGE: sampled task {t.get('task_id')} re-derived "
                     f"bucket {b} outside train {T0}-{T1}")
    return f


def check_gate(gr):
    """Findings on the round-gate eval receipt: split + CI fields."""
    f = list(validate_receipt(gr))
    for k in ("ticket", "ts", "arm", "tasks", "gain", "ci_low", "ci_high",
              "governor"):
        if k not in gr:
            f.append(f"missing field: {k}")
    if f:
        return f
    if gr["arm"] != fp27.ACCUMULATION["binding_arm"]:
        f.append(f"binding arm must be "
                 f"{fp27.ACCUMULATION['binding_arm']!r}, got {gr['arm']!r}")
    if len(gr["tasks"]) != fp27.ROUNDGATE_N:
        f.append(f"round-gate N {len(gr['tasks'])} != frozen "
                 f"{fp27.ROUNDGATE_N}")
    for t in gr["tasks"]:
        b = _bucket(t["op_name"], t["input"])
        if not (G0 <= b <= G1):
            f.append(f"LEAKAGE: gate task {t.get('task_id')} re-derived "
                     f"bucket {b} outside round-gate {G0}-{G1}")
    lo, hi, g = gr["ci_low"], gr["ci_high"], gr["gain"]
    if not (lo <= g <= hi):
        f.append(f"gain {g} outside its own CI [{lo}, {hi}]")
    return f


def verdict(ci_low, ci_high):
    if ci_low > 0:
        return "GAIN"
    if ci_high < 0:
        return "NEGATIVE"
    return "FLAT"


def power_annotation(ci_low, ci_high):
    """REPORTING ONLY (fp-27c, #240) — the frozen verdict vocabulary is
    untouched. Derived from the SAME normal SE that produced the CI
    (half = 1.96*se), so no new statistical model enters the receipt:
    mde80 = (1.645 + 0.84) * se is the smallest effect this gate detects
    at 80% power, one-sided 5% (fp-32 R8: the round gate is N-capped at
    the frozen N=100 — GPU-hours cannot buy resolution here)."""
    half = (ci_high - ci_low) / 2.0
    se = half / 1.96
    return {
        "n_frozen": fp27.ROUNDGATE_N,
        "ci95_half_width": round(half, 4),
        "mde80_one_sided": round((1.645 + 0.84) * se, 4),
        "basis": "fp-32 R8 (verdict instrument is STAT-limited); "
                 "reporting only — verdict rule frozen in fp-27",
    }


def build_receipt(ts, sr, gr):
    v = verdict(gr["ci_low"], gr["ci_high"])
    power = power_annotation(gr["ci_low"], gr["ci_high"])
    result = {"verdict": v,
              "gain": gr["gain"],
              "ci": [gr["ci_low"], gr["ci_high"]],
              "power": power,
              "never_a_rung_kill": True}
    if v == "FLAT":
        result["flat_caveat"] = (
            f"FLAT at this width detects only effects >= "
            f"{power['mde80_one_sided']} — read as 'no effect >= "
            f"{power['mde80_one_sided']} demonstrated', never 'no effect' "
            f"(fp-25 power lesson, mechanized)")
    return {
        "ticket": "FP27B-ROUND1-VERDICT",
        "ts": ts,
        "issue": 205,
        "round": fp27.ROUND,
        "sampling_ticket": sr["ticket"],
        "gate_ticket": gr["ticket"],
        "split_audited": True,
        "fp20c_pacing_block": sr["pacing"],
        "result": result,
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def _fix_tasks(region, n, level="l1"):
    """Synthetic fixture tasks whose RE-DERIVED buckets land in region."""
    out, i = [], 0
    lo, hi = (T0, T1) if region == "train" else (G0, G1)
    while len(out) < n:
        name = "reverse" if level == "l1" else "reverse+sum_fold"
        xs = list(range(i % 9 + 4))
        xs[-1] = i
        if lo <= _bucket(name, xs) <= hi:
            out.append({"task_id": f"{region}-{len(out)}", "op_name": name,
                        "input": xs})
        i += 1
    return out


def _selftest():
    sr = {"ticket": "R1-SAMPLING", "ts": "x",
          "seed": fp27.SAMPLING["seed"], "k": fp27.SAMPLING["k"],
          "tasks": (_fix_tasks("train", fp27.SAMPLING["n_tasks_l1"], "l1")
                    + _fix_tasks("train", fp27.SAMPLING["n_tasks_l2"], "l2")),
          "pacing": {"governed_wall": "compute+pacing"},
          "governor": {"vram_fraction": 0.8}, "sha_convention": "x"}
    assert check_sampling(sr) == [], check_sampling(sr)[:3]
    assert any("seed" in x for x in check_sampling(dict(sr, seed=16)))
    leaky = dict(sr, tasks=sr["tasks"][:-1]
                 + [{"task_id": "bad", "op_name": "reverse",
                     "input": _fix_tasks("gate", 1)[0]["input"]}])
    assert any("LEAKAGE" in x for x in check_sampling(leaky))
    gr = {"ticket": "R1-GATE", "ts": "x", "arm": "sft",
          "tasks": _fix_tasks("gate", fp27.ROUNDGATE_N),
          "gain": 0.10, "ci_low": 0.02, "ci_high": 0.19,
          "governor": {"vram_fraction": 0.8}, "sha_convention": "x"}
    assert check_gate(gr) == [], check_gate(gr)[:3]
    assert any("arm" in x for x in check_gate(dict(gr, arm="grpo")))
    assert any("LEAKAGE" in x for x in check_gate(
        dict(gr, tasks=gr["tasks"][:-1]
             + [dict(_fix_tasks("train", 1)[0], task_id="bad")])))
    assert any("outside its own CI" in x for x in check_gate(
        dict(gr, gain=0.5)))
    # the frozen verdict vocabulary — all three branches
    assert verdict(0.02, 0.19) == "GAIN"
    assert verdict(-0.05, 0.05) == "FLAT"
    assert verdict(-0.19, -0.02) == "NEGATIVE"
    r = build_receipt("20260101T000000Z", sr, gr)
    assert validate_receipt(r) == [], validate_receipt(r)
    assert r["result"]["verdict"] == "GAIN"
    # power annotation (fp-27c, #240): reporting only, derived from the
    # CI's own SE. GAIN carries power but NO flat caveat.
    p = r["result"]["power"]
    assert p["n_frozen"] == fp27.ROUNDGATE_N
    assert p["ci95_half_width"] == 0.085          # (0.19-0.02)/2
    assert p["mde80_one_sided"] == 0.1078, p      # 2.485*(0.085/1.96)
    assert "flat_caveat" not in r["result"]
    # FLAT carries the mechanized fp-25 caveat with the derived mde80
    rf = build_receipt("20260101T000000Z", sr,
                       dict(gr, gain=0.0, ci_low=-0.05, ci_high=0.05))
    assert rf["result"]["verdict"] == "FLAT"
    assert rf["result"]["power"]["mde80_one_sided"] == 0.0634  # 2.485*(.05/1.96)
    assert "0.0634" in rf["result"]["flat_caveat"]
    assert validate_receipt(rf) == [], validate_receipt(rf)
    print("FP27B_ROUND1_VERDICT_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sampling", metavar="RECEIPT")
    ap.add_argument("--gate", metavar="RECEIPT")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if not (a.sampling and a.gate):
        print("FP27B_ROUND1_VERDICT_STAGED (refuses until the round-1 "
              "sampling + round-gate receipts exist; both required)")
        return
    sr = json.load(open(a.sampling, encoding="utf-8"))
    gr = json.load(open(a.gate, encoding="utf-8"))
    f = check_sampling(sr) + check_gate(gr)
    if f:
        for x in f:
            print(f"ROUND VIOLATION: {x}")
        raise SystemExit("FP27B_REFUSED — round bundle does not bind")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = build_receipt(ts, sr, gr)
    out = f"{NC}/receipts/fp27b-round1-verdict-{ts}.json"
    checked_write(out, receipt)
    f2 = validate_receipt(json.load(open(out, encoding="utf-8")))
    if f2:
        raise SystemExit(f"emitted verdict receipt FAILS receipt_check: {f2}")
    print(json.dumps(receipt["result"], indent=2))
    print(f"FP27B_ROUND1_VERDICT_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
