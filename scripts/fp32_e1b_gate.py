"""fp32_e1b_gate.py — fire-time gate for the E1b batch-deviation
loss-match (#225), STAGED FAIL-CLOSED.

The decision rule is frozen in research/fp32-e1b-prereg.md (frozen
2026-06-11 BEFORE any v0 shard existed). This executor makes the fire
mechanical: the eng-54 trainer emits the FP32-E1B-LOSSMATCH pair
receipt; this gate validates it against the frozen pins and applies the
rule. Zero decisions at fire time — the emitter's claims are AUDITED
(identical-pins, single-variable, budget), never trusted.

Frozen rule (verbatim from the prereg):
  PASS            iff ce_final10(candidate) <= ce_final10(B4) * 1.02
                  at frozen lr (muon 0.02 / adamw 3e-4).
  PASS-SCALED-LR  same inequality on the single permitted retry leg
                  (muon 0.04 / adamw 6e-4, linear batch 4->16 scaling).
  FAIL            both legs miss -> deviation KILLED, B=4 stands, #225
                  closes on the negative receipt. No third
                  configuration, no tolerance widening (fp-22 class).
  B=24 candidate additionally requires free-VRAM margin >= 1.5 GiB held
  in the REAL trainer (the bench's 5.15 GiB free did not carry Muon
  states / MTP heads / loader buffers).

Pair-receipt contract (one receipt, both legs):
  legs[].{batch, lr_muon, lr_adamw, steps, tokens, ce_final10, wall_s,
  governor{vram_fraction, margin_gib_floor, pace_s_per_step},
  free_vram_gib_min}
  + shared pins: shard_set_sha256, init_seed, seq, token_budget
  (10,485,760 per leg), data_order_basis.
Identical across legs: shard set, seed, seq, token budget, governor.
The ONLY differing axes: batch, and lr ONLY on a scaled-lr retry leg at
exactly the permitted values. Any other difference = confound = the
comparison does not bind (proof-gate rejection class: "before/after
measurements change multiple variables without naming the confound").
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write                 # noqa: E402
from receipt_check import validate_receipt              # noqa: E402

TOKEN_BUDGET = 10_485_760
TOLERANCE = 1.02
FROZEN_LR = {"lr_muon": 0.02, "lr_adamw": 0.0003}
SCALED_LR = {"lr_muon": 0.04, "lr_adamw": 0.0006}
BASE_BATCH = 4
CANDIDATES = (16, 24)
B24_MARGIN_GIB = 1.5
GOVERNOR_KEYS = ("vram_fraction", "margin_gib_floor", "pace_s_per_step")
PAIR_REQUIRED = ("ticket", "ts", "shard_set_sha256", "init_seed", "seq",
                 "token_budget", "data_order_basis", "legs",
                 "sha_convention")
LEG_REQUIRED = ("batch", "lr_muon", "lr_adamw", "steps", "tokens",
                "ce_final10", "wall_s", "governor", "free_vram_gib_min")
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")


def _lr_of(leg):
    return {"lr_muon": leg["lr_muon"], "lr_adamw": leg["lr_adamw"]}


def check_pair(pr):
    """Findings list (empty = the pair receipt binds)."""
    f = list(validate_receipt(pr))
    for k in PAIR_REQUIRED:
        if k not in pr:
            f.append(f"missing field: {k}")
    if f:
        return f
    legs = pr["legs"]
    if not isinstance(legs, list) or not 2 <= len(legs) <= 3:
        return [f"legs must be 2 (pair) or 3 (pair + one scaled-lr "
                f"retry), got {len(legs) if isinstance(legs, list) else legs!r}"]
    for i, leg in enumerate(legs):
        for k in LEG_REQUIRED:
            if k not in leg:
                f.append(f"leg[{i}] missing field: {k}")
    if f:
        return f
    if pr["token_budget"] != TOKEN_BUDGET:
        f.append(f"token_budget {pr['token_budget']} != frozen "
                 f"{TOKEN_BUDGET}")
    for i, leg in enumerate(legs):
        if leg["tokens"] != pr["token_budget"]:
            f.append(f"leg[{i}] tokens {leg['tokens']} != shared budget "
                     f"{pr['token_budget']}")
        if not (isinstance(leg["ce_final10"], (int, float))
                and leg["ce_final10"] == leg["ce_final10"]
                and leg["ce_final10"] > 0):
            f.append(f"leg[{i}] ce_final10 must be a positive finite "
                     f"number, got {leg['ce_final10']!r}")
    g0 = legs[0]["governor"]
    for i, leg in enumerate(legs[1:], 1):
        for k in GOVERNOR_KEYS:
            if leg["governor"].get(k) != g0.get(k):
                f.append(f"CONFOUND: leg[{i}] governor.{k} "
                         f"{leg['governor'].get(k)} != leg[0] {g0.get(k)} "
                         f"— governor must be identical across legs")
    base = legs[0]
    if base["batch"] != BASE_BATCH:
        f.append(f"leg[0] must be the B={BASE_BATCH} baseline, got "
                 f"batch {base['batch']}")
    if _lr_of(base) != FROZEN_LR:
        f.append(f"baseline lr must be frozen {FROZEN_LR}, got "
                 f"{_lr_of(base)}")
    cands = legs[1:]
    if cands and len({leg["batch"] for leg in cands}) != 1:
        f.append("all candidate legs must share ONE candidate batch "
                 "(the ladder is one candidate per pair receipt)")
    for i, leg in enumerate(cands, 1):
        if leg["batch"] not in CANDIDATES:
            f.append(f"leg[{i}] candidate batch {leg['batch']} not in "
                     f"frozen ladder {CANDIDATES}")
        if leg["batch"] == 24 and leg["free_vram_gib_min"] < B24_MARGIN_GIB:
            f.append(f"B=24 requires free-VRAM margin >= {B24_MARGIN_GIB} "
                     f"GiB held in the real trainer; leg[{i}] min was "
                     f"{leg['free_vram_gib_min']}")
    if len(cands) >= 1 and _lr_of(cands[0]) != FROZEN_LR:
        f.append(f"first candidate leg must run the FROZEN lr {FROZEN_LR} "
                 f"(rule 1), got {_lr_of(cands[0])}")
    if len(cands) == 2 and _lr_of(cands[1]) != SCALED_LR:
        f.append(f"the single permitted retry leg must run exactly "
                 f"{SCALED_LR} (rule 2), got {_lr_of(cands[1])}")
    return f


def verdict(pr):
    """Frozen rule applied to a BINDING pair receipt. Returns
    (verdict, detail)."""
    legs = pr["legs"]
    base, cands = legs[0], legs[1:]
    if not cands:
        return "FAIL", {"reason": "no candidate leg present"}
    bar = base["ce_final10"] * TOLERANCE
    primary = cands[0]
    detail = {"candidate_batch": primary["batch"],
              "ce_base_final10": base["ce_final10"],
              "bar_base_x_1.02": round(bar, 6),
              "ce_candidate_frozen_lr": primary["ce_final10"]}
    if primary["ce_final10"] <= bar:
        return "PASS", detail
    if len(cands) == 2:
        retry = cands[1]
        detail["ce_candidate_scaled_lr"] = retry["ce_final10"]
        if retry["ce_final10"] <= bar:
            return "PASS-SCALED-LR", detail
    detail["deviation"] = ("KILLED — B=4 stands; #225 closes on this "
                           "negative receipt; no third configuration")
    return "FAIL", detail


def build_receipt(ts, pr):
    v, detail = verdict(pr)
    return {
        "ticket": "FP32-E1B-VERDICT",
        "ts": ts,
        "issue": 225,
        "prereg": "research/fp32-e1b-prereg.md (frozen 2026-06-11 "
                  "pre-shards)",
        "pair_ticket": pr["ticket"],
        "pair_ts": pr["ts"],
        "shard_set_sha256": pr["shard_set_sha256"],
        "pins_audited": True,
        "result": {"verdict": v, **detail,
                   "deviation_action": {
                       "PASS": "registered-deviation PR amends "
                               "throughput.batch to the candidate",
                       "PASS-SCALED-LR": "deviation PR amends batch AND "
                                         "records the scaled lr",
                       "FAIL": "deviation killed; B=4 stands"}[v]},
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def _leg(batch, ce, lr=FROZEN_LR, free=10.0, tokens=TOKEN_BUDGET):
    return {"batch": batch, "lr_muon": lr["lr_muon"],
            "lr_adamw": lr["lr_adamw"], "steps": tokens // (batch * 1024),
            "tokens": tokens, "ce_final10": ce, "wall_s": 500.0,
            "governor": {"vram_fraction": 0.8, "margin_gib_floor": 1.5,
                         "pace_s_per_step": 0.05},
            "free_vram_gib_min": free}


def _pair(legs):
    return {"ticket": "FP32-E1B-LOSSMATCH", "ts": "x",
            "shard_set_sha256": "a" * 64, "init_seed": 23, "seq": 1024,
            "token_budget": TOKEN_BUDGET,
            "data_order_basis": "shard prefix, frozen order",
            "legs": legs, "sha_convention": "x"}


def _selftest():
    # PASS at frozen lr
    p = _pair([_leg(4, 2.500), _leg(16, 2.530)])
    assert check_pair(p) == [], check_pair(p)[:3]
    assert verdict(p)[0] == "PASS"
    # exactly on the bar passes (<=)
    assert verdict(_pair([_leg(4, 2.5), _leg(16, 2.55)]))[0] == "PASS"
    # frozen-lr miss, scaled-lr retry lands
    p2 = _pair([_leg(4, 2.500), _leg(16, 2.600),
                _leg(16, 2.540, lr=SCALED_LR)])
    assert check_pair(p2) == [], check_pair(p2)[:3]
    assert verdict(p2)[0] == "PASS-SCALED-LR"
    # both miss -> FAIL, deviation killed
    p3 = _pair([_leg(4, 2.500), _leg(16, 2.700),
                _leg(16, 2.650, lr=SCALED_LR)])
    v, d = verdict(p3)
    assert v == "FAIL" and "KILLED" in d["deviation"]
    # pin refusals
    assert any("CONFOUND" in x for x in check_pair(_pair([
        _leg(4, 2.5), dict(_leg(16, 2.5),
                           governor={"vram_fraction": 0.85,
                                     "margin_gib_floor": 1.5,
                                     "pace_s_per_step": 0.05})])))
    assert any("token_budget" in x for x in check_pair(
        dict(_pair([_leg(4, 2.5), _leg(16, 2.5)]), token_budget=5)))
    assert any("frozen lr" in x.lower() or "FROZEN lr" in x
               for x in check_pair(_pair([_leg(4, 2.5),
                                          _leg(16, 2.5, lr=SCALED_LR)])))
    assert any("retry leg" in x for x in check_pair(_pair([
        _leg(4, 2.5), _leg(16, 2.6),
        _leg(16, 2.55, lr={"lr_muon": 0.08, "lr_adamw": 0.0006})])))
    assert any("ladder" in x for x in check_pair(
        _pair([_leg(4, 2.5), _leg(32, 2.5)])))
    assert any("B=24 requires" in x for x in check_pair(
        _pair([_leg(4, 2.5), _leg(24, 2.5, free=0.9)])))
    assert any("baseline" in x for x in check_pair(
        _pair([_leg(8, 2.5), _leg(16, 2.5)])))
    # emitted verdict receipt is receipt_check-clean
    r = build_receipt("20260101T000000Z", p)
    assert validate_receipt(r) == [], validate_receipt(r)
    assert r["result"]["verdict"] == "PASS"
    print("FP32_E1B_GATE_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--pair", metavar="RECEIPT")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if not a.pair:
        print("FP32_E1B_GATE_STAGED (refuses until the trainer's "
              "FP32-E1B-LOSSMATCH pair receipt exists; executes after "
              "#218 + shard rerun, before --live)")
        return
    pr = json.load(open(a.pair, encoding="utf-8"))
    f = check_pair(pr)
    if f:
        for x in f:
            print(f"PAIR VIOLATION: {x}")
        raise SystemExit("FP32_E1B_GATE_REFUSED — pair receipt does not "
                         "bind")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = build_receipt(ts, pr)
    out = f"{NC}/receipts/fp32-e1b-verdict-{ts}.json"
    checked_write(out, receipt)
    f2 = validate_receipt(json.load(open(out, encoding="utf-8")))
    if f2:
        raise SystemExit(f"emitted verdict receipt FAILS receipt_check: "
                         f"{f2}")
    print(json.dumps(receipt["result"], indent=2))
    print(f"FP32_E1B_GATE_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
