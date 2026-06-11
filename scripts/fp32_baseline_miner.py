"""fp32_baseline_miner.py — deterministic GPU-economics baseline
extraction from EXISTING receipts (#225, fp-32 deliverable 1 input).

Every number in the fp-32 bottleneck ledger must be provenance-tagged
receipt-or-hypothesis (directive, mail 14633). This miner makes the
receipt-side mechanical: it reads the named source receipts, re-derives
the economics in plain arithmetic, and emits one fp32-baselines receipt
binding each row to its source (path + the fields used). No model
self-report anywhere in the chain.

Rows mined:
  gen   — newest w1-humaneval sampling receipt: s/sample, verified
          episodes per generation-minute (the floor instrument's unit).
  pace  — fp20b-settle: as-operated pacing fraction of generation wall.
  bits  — fp11-denominator: sampler-valued bits per generation minute
          (A1 accounting; the existing instrument for Kai's
          signal-density hypothesis).
  train — newest t2-r2 training receipt: train seconds per example;
          gen:train wall ratio for the round loop.
  step  — fp19-bench c03-qat: paced/raw tok/s, derived pacing tax,
          projected v0 wall-days against the LIVE freeze total (fp-30
          binder — never a stale literal).
  power — w4-eval measured CI95 widths (the live eval instrument's
          resolution) + exact normal-approx MDE table for the frozen
          fp-27 round-gate N=100 at a range of discordance rates
          (paired-difference half-width 1.96*sqrt(disc/N); MDE at 80%
          power (1.96+0.84)*sqrt(disc/N)).

`--selftest` pure-logic on fixtures; `--run` mines the live tree and
emits receipts/fp32-baselines-<ts>.json.
"""
import glob as globmod
import json
import math
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write                 # noqa: E402
from receipt_check import validate_receipt              # noqa: E402
import fp30_total_consistency as fp30                   # noqa: E402

SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")
ROUNDGATE_N = 100              # fp-27 frozen
DISC_GRID = (0.1, 0.2, 0.3, 0.5)


def _newest(nc, pat):
    hits = sorted(globmod.glob(f"{nc}/{pat}"))
    return hits[-1] if hits else None


def _load(p):
    return json.load(open(p, encoding="utf-8"))


def mine_gen(nc=NC):
    p = _newest(nc, "receipts/w1-humaneval-*.json")
    if not p:
        return {"status": "NO-SOURCE", "pattern": "receipts/w1-humaneval-*"}
    d = _load(p)
    n_samples = d["n_tasks"] * d["k"]
    return {"status": "OK", "source": os.path.basename(p),
            "fields": ["gen_secs", "n_tasks", "k", "verified_samples"],
            "gen_secs": d["gen_secs"], "n_samples": n_samples,
            "secs_per_sample": round(d["gen_secs"] / n_samples, 3),
            "verified_samples": d["verified_samples"],
            "verified_per_gen_min": round(
                d["verified_samples"] / (d["gen_secs"] / 60.0), 1)}


def mine_pace(nc=NC):
    p = _newest(nc, "receipts/fp20b-settle-*.json")
    if not p:
        return {"status": "NO-SOURCE", "pattern": "receipts/fp20b-settle-*"}
    d = _load(p)["result"]["as_operated"]
    return {"status": "OK", "source": os.path.basename(p),
            "fields": ["result.as_operated"],
            "pacing_fraction_of_gen_wall":
                d["pacing_fraction_of_gen_wall"],
            "implied_raw_over_paced": d["implied_raw_over_paced"]}


def mine_bits(nc=NC):
    p = _newest(nc, "receipts/fp11-denominator-*.json")
    if not p:
        return {"status": "NO-SOURCE",
                "pattern": "receipts/fp11-denominator-*"}
    d = _load(p)
    a1 = d["accountings"]["A1"]["bits_per_min_sampler_valued"]
    return {"status": "OK", "source": os.path.basename(p),
            "fields": ["accountings.A1.bits_per_min_sampler_valued"],
            "bits_per_gen_min_A1": a1}


def mine_train(nc=NC, gen_row=None):
    p = _newest(nc, "receipts/t2-r2-*.json")
    if not p:
        return {"status": "NO-SOURCE", "pattern": "receipts/t2-r2-*"}
    d = _load(p)
    row = {"status": "OK", "source": os.path.basename(p),
           "fields": ["train_secs", "dataset.n_examples"],
           "train_secs": d["train_secs"],
           "n_examples": d["dataset"]["n_examples"],
           "secs_per_example": round(
               d["train_secs"] / d["dataset"]["n_examples"], 3)}
    if gen_row and gen_row.get("status") == "OK":
        row["gen_to_train_wall_ratio"] = round(
            gen_row["gen_secs"] / d["train_secs"], 2)
    return row


def mine_step(nc=NC):
    p = _newest(nc, "receipts/fp19-bench-*.json")
    if not p:
        return {"status": "NO-SOURCE", "pattern": "receipts/fp19-bench-*"}
    d = _load(p)["results"].get("c03-qat")
    if not d:
        return {"status": "NO-SOURCE", "pattern": "fp19 c03-qat cell"}
    freeze_name, total = fp30.live_freeze(nc)
    row = {"status": "OK", "source": os.path.basename(p),
           "fields": ["results.c03-qat.tok_s_paced", ".tok_s_raw",
                      ".batch"],
           "batch": d["batch"], "tok_s_paced": d["tok_s_paced"],
           "tok_s_raw": d["tok_s_raw"],
           "pacing_tax": round(1 - d["tok_s_paced"] / d["tok_s_raw"], 4),
           "free_vram_gib_post_warmup": d["free_vram_gib_post_warmup"]}
    if freeze_name:
        row["live_freeze_receipt"] = freeze_name
        row["real_token_total"] = total
        row["v0_wall_days_paced"] = round(
            total / (d["tok_s_paced"] * 86400.0), 3)
    else:
        row["live_freeze_receipt"] = None
    return row


def mde_table(n=ROUNDGATE_N, grid=DISC_GRID):
    """Paired-difference resolution at the frozen round-gate N. Normal
    approximation: a paired pass-rate difference's variance is bounded by
    disc/N where disc = discordant-pair rate; CI95 half-width =
    1.96*sqrt(disc/N); MDE at 80% power (one-sided 5%) =
    (1.645+0.84)*sqrt(disc/N). Reported per candidate disc since disc is
    only known after a round runs."""
    out = []
    for disc in grid:
        se = math.sqrt(disc / n)
        out.append({"discordance": disc,
                    "ci95_half_width_pp": round(196 * se, 1),
                    "mde80_one_sided_pp": round(100 * (1.645 + 0.84) * se,
                                                1)})
    return out


def mine_power(nc=NC):
    p = _newest(nc, "receipts/w4-eval-r2w-*.json")
    row = {"status": "OK" if p else "NO-SOURCE",
           "roundgate_n_frozen": ROUNDGATE_N,
           "mde_at_roundgate_n": mde_table()}
    if p:
        d = _load(p)
        widths = {k: round(v[1] - v[0], 2)
                  for k, v in d["deltas"].items() if k.endswith("_ci95")}
        row.update(source=os.path.basename(p), fields=["deltas", "n_tasks"],
                   eval_n_tasks=d["n_tasks"],
                   measured_ci95_widths_pp=widths)
    return row


def run(nc=NC):
    gen = mine_gen(nc)
    rows = {"gen": gen, "pace": mine_pace(nc), "bits": mine_bits(nc),
            "train": mine_train(nc, gen), "step": mine_step(nc),
            "power": mine_power(nc)}
    return {
        "ticket": "FP32-BASELINES",
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "issue": 225,
        "rows": rows,
        "result": {"rows_ok": sum(1 for r in rows.values()
                                  if r.get("status") == "OK"),
                   "rows_missing": [k for k, r in rows.items()
                                    if r.get("status") != "OK"]},
        "provenance_rule": "every numeric field re-derived from the named "
                           "source receipt's named fields by this script's "
                           "arithmetic — no free-typed numbers",
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def _selftest():
    # MDE math: disc 0.2 at N=100 -> se=0.04472; half-width 8.8pp
    t = mde_table()
    by = {r["discordance"]: r for r in t}
    assert by[0.2]["ci95_half_width_pp"] == 8.8, by[0.2]
    assert by[0.2]["mde80_one_sided_pp"] == 11.1, by[0.2]
    assert by[0.5]["ci95_half_width_pp"] == 13.9, by[0.5]
    # miner on fixtures
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/receipts")

        def w(name, obj):
            json.dump(obj, open(f"{td}/receipts/{name}", "w"))

        w("w1-humaneval-q3-20260101T000000Z.json",
          {"gen_secs": 600.0, "n_tasks": 50, "k": 8,
           "verified_samples": 300})
        w("t2-r2-x-20260101T000000Z.json",
          {"train_secs": 60.0, "dataset": {"n_examples": 100}})
        gen = mine_gen(td)
        assert gen["secs_per_sample"] == 1.5 and \
            gen["verified_per_gen_min"] == 30.0, gen
        tr = mine_train(td, gen)
        assert tr["secs_per_example"] == 0.6
        assert tr["gen_to_train_wall_ratio"] == 10.0
        assert mine_pace(td)["status"] == "NO-SOURCE"
        r = run(td)
        assert validate_receipt(r) == [], validate_receipt(r)
        assert "pace" in r["result"]["rows_missing"]
    # live tree: all six rows must mine OK (their sources are committed)
    live = run()
    assert live["result"]["rows_ok"] == 6, live["result"]
    print("FP32_BASELINE_MINER_SELFTEST_PASS")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    if "--run" not in sys.argv:
        print("FP32_BASELINE_MINER_STAGED (--run mines the live receipts)")
        return
    receipt = run()
    out = f"{NC}/receipts/fp32-baselines-{receipt['ts']}.json"
    checked_write(out, receipt)
    f = validate_receipt(json.load(open(out, encoding="utf-8")))
    if f:
        raise SystemExit(f"emitted receipt FAILS receipt_check: {f}")
    print(json.dumps(receipt["rows"], indent=1)[:2000])
    print(f"FP32_BASELINE_MINER_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
