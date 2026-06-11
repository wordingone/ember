"""fp32_e1b_gate.py — fire-time gate for the E1b batch-deviation
loss-match (#225), STAGED FAIL-CLOSED.

The decision rule is frozen in research/fp32-e1b-prereg.md (frozen
2026-06-11 BEFORE any v0 shard existed). This executor makes the fire
mechanical: the eng-54 trainer emits the FP32-E1B-LOSSMATCH pair
receipt; this gate validates it against the frozen pins and applies the
rule. Zero decisions at fire time — the emitter's claims are AUDITED
(identical-pins, single-variable, accounting, shard provenance), never
trusted.

Hardened per Kai checkpoint 14639 (fail-open surfaces at f3076ae):
  - bare invocation (no --pair) EXITS NONZERO — a caller can never read
    the staged state as a passed gate;
  - ticket and seq are enforced values, not just present fields;
  - step/token accounting must be exact: steps == ceil(budget/(B*seq)),
    tokens == steps*B*seq (B=24 legitimately overshoots the budget by
    <1 step — the old tokens==budget check was wrong there);
  - a scaled-lr retry leg is REFUSED unless the frozen-lr candidate
    actually missed the CE bar (rule 2 is a retry, not an extra arm);
  - shard provenance is BOUND, not trusted: the pair receipt names the
    TOKEN-SHARDS-V0 receipt; the gate loads it (receipt_check-clean,
    git-tracked, correct ticket), re-derives pair.shard_set_sha256 as
    the sha256 of that receipt's on-disk bytes, and requires its
    total_stream_tokens to equal the LIVE tokenizer-freeze total (fp-30
    binder) — a pair receipt built on pre-#218 stale shards can never
    certify the deviation.

Frozen rule (verbatim from the prereg):
  PASS            iff ce_final10(candidate) <= ce_final10(B4) * 1.02
                  at frozen lr (muon 0.02 / adamw 3e-4).
  PASS-SCALED-LR  same inequality on the single permitted retry leg
                  (muon 0.04 / adamw 6e-4), permitted ONLY after the
                  frozen-lr candidate missed.
  FAIL            both legs miss -> deviation KILLED, B=4 stands, #225
                  closes on the negative receipt. No third
                  configuration, no tolerance widening (fp-22 class).
  B=24 candidate additionally requires free-VRAM margin >= 1.5 GiB held
  in the REAL trainer.
"""
import argparse
import hashlib
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

PAIR_TICKET = "FP32-E1B-LOSSMATCH"
SHARDS_TICKET = "TOKEN-SHARDS-V0"
SEQ = 1024
TOKEN_BUDGET = 10_485_760
TOLERANCE = 1.02
FROZEN_LR = {"lr_muon": 0.02, "lr_adamw": 0.0003}
SCALED_LR = {"lr_muon": 0.04, "lr_adamw": 0.0006}
BASE_BATCH = 4
CANDIDATES = (16, 24)
B24_MARGIN_GIB = 1.5
GOVERNOR_KEYS = ("vram_fraction", "margin_gib_floor", "pace_s_per_step")
PAIR_REQUIRED = ("ticket", "ts", "shard_receipt", "shard_set_sha256",
                 "init_seed", "seq", "token_budget", "data_order_basis",
                 "legs", "sha_convention")
LEG_REQUIRED = ("batch", "lr_muon", "lr_adamw", "steps", "tokens",
                "ce_final10", "wall_s", "governor", "free_vram_gib_min")
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")


def _lr_of(leg):
    return {"lr_muon": leg["lr_muon"], "lr_adamw": leg["lr_adamw"]}


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _tracked(nc):
    """Set of git-tracked relative paths (forward-slash), or None outside
    a git tree (selftest tmpdir fallback — same pattern as sp-3)."""
    import subprocess
    out = subprocess.run(["git", "-C", nc, "ls-files"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return set(out.stdout.splitlines())


def check_shard_provenance(pr, nc=NC):
    """The pair receipt's shard premise, audited: named TOKEN-SHARDS-V0
    receipt exists, is clean, is git-tracked, matches the claimed set
    sha byte-true, and reproduces the LIVE freeze total (post-#218
    proof — stale shards can never bind)."""
    f = []
    name = pr["shard_receipt"]
    path = f"{nc}/receipts/{name}"
    if not os.path.exists(path):
        return [f"shard_receipt {name} not found under receipts/"]
    tracked = _tracked(nc)
    if tracked is not None and f"receipts/{name}" not in tracked:
        f.append(f"shard_receipt {name} is not git-tracked — untracked "
                 f"evidence cannot certify a deviation (Kai 14631 class)")
    try:
        sd = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        return f + [f"shard_receipt {name} unreadable: {e}"]
    if validate_receipt(sd):
        f.append(f"shard_receipt {name} fails receipt_check: "
                 f"{validate_receipt(sd)[:2]}")
    if sd.get("ticket") != SHARDS_TICKET:
        f.append(f"shard_receipt ticket {sd.get('ticket')!r} != "
                 f"{SHARDS_TICKET!r}")
    got_sha = _sha(path)
    if pr["shard_set_sha256"] != got_sha:
        f.append(f"shard_set_sha256 {pr['shard_set_sha256'][:12]}... does "
                 f"not match the shard receipt's on-disk bytes "
                 f"{got_sha[:12]}...")
    freeze_name, live_total = fp30.live_freeze(nc)
    if freeze_name is None:
        f.append("no clean live tokenizer-freeze receipt — the shard "
                 "premise has nothing to bind against")
    elif sd.get("total_stream_tokens") != live_total:
        f.append(f"STALE SHARDS: shard receipt total_stream_tokens "
                 f"{sd.get('total_stream_tokens')} != live freeze total "
                 f"{live_total} ({freeze_name}) — E1b on pre-#218 shards "
                 f"cannot certify the deviation")
    return f


def check_pair(pr, nc=NC):
    """Findings list (empty = the pair receipt binds)."""
    f = list(validate_receipt(pr))
    for k in PAIR_REQUIRED:
        if k not in pr:
            f.append(f"missing field: {k}")
    if f:
        return f
    if pr["ticket"] != PAIR_TICKET:
        f.append(f"ticket {pr['ticket']!r} != {PAIR_TICKET!r}")
    if pr["seq"] != SEQ:
        f.append(f"seq {pr['seq']} != frozen {SEQ}")
    legs = pr["legs"]
    if not isinstance(legs, list) or not 2 <= len(legs) <= 3:
        f.append(f"legs must be 2 (pair) or 3 (pair + one scaled-lr "
                 f"retry), got "
                 f"{len(legs) if isinstance(legs, list) else legs!r}")
        return f
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
        b = leg["batch"]
        if not (isinstance(b, int) and b > 0):
            f.append(f"leg[{i}] batch must be a positive int, got {b!r}")
            continue
        want_steps = math.ceil(TOKEN_BUDGET / (b * SEQ))
        if leg["steps"] != want_steps:
            f.append(f"leg[{i}] accounting: steps {leg['steps']} != "
                     f"ceil(budget/(B*seq)) = {want_steps} at B={b}")
        if leg["tokens"] != want_steps * b * SEQ:
            f.append(f"leg[{i}] accounting: tokens {leg['tokens']} != "
                     f"steps*B*seq = {want_steps * b * SEQ}")
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
    if len(cands) == 2:
        if _lr_of(cands[1]) != SCALED_LR:
            f.append(f"the single permitted retry leg must run exactly "
                     f"{SCALED_LR} (rule 2), got {_lr_of(cands[1])}")
        # rule 2 is a RETRY: it exists only after rule 1 missed
        if (not f and cands[0]["ce_final10"]
                <= base["ce_final10"] * TOLERANCE):
            f.append("retry leg present although the frozen-lr candidate "
                     "PASSED rule 1 — the scaled-lr leg is a retry after "
                     "a miss, never an extra arm (prereg rule 2)")
    f.extend(check_shard_provenance(pr, nc))
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
                  "pre-shards; contract tightened per Kai 14639)",
        "pair_ticket": pr["ticket"],
        "pair_ts": pr["ts"],
        "shard_receipt": pr["shard_receipt"],
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


def _leg(batch, ce, lr=FROZEN_LR, free=10.0):
    steps = math.ceil(TOKEN_BUDGET / (batch * SEQ))
    return {"batch": batch, "lr_muon": lr["lr_muon"],
            "lr_adamw": lr["lr_adamw"], "steps": steps,
            "tokens": steps * batch * SEQ, "ce_final10": ce,
            "wall_s": 500.0,
            "governor": {"vram_fraction": 0.8, "margin_gib_floor": 1.5,
                         "pace_s_per_step": 0.05},
            "free_vram_gib_min": free}


def _selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(f"{td}/receipts")
        json.dump({"ticket": "TOK", "ts": "20260101T000000Z",
                   "real_token_counts": {"total": 7_000_000_000},
                   "sha_convention": "x"},
                  open(f"{td}/receipts/tokenizer-freeze-"
                       f"20260101T000000Z.json", "w"))
        shard_name = "token-shards-v0-20260101T000001Z.json"
        json.dump({"ticket": SHARDS_TICKET, "ts": "20260101T000001Z",
                   "total_stream_tokens": 7_000_000_000,
                   "sha_convention": "x"},
                  open(f"{td}/receipts/{shard_name}", "w"))
        shard_sha = _sha(f"{td}/receipts/{shard_name}")
        # a second shard receipt with a STALE total (pre-re-freeze)
        stale_name = "token-shards-v0-20251231T000000Z.json"
        json.dump({"ticket": SHARDS_TICKET, "ts": "20251231T000000Z",
                   "total_stream_tokens": 6_900_000_000,
                   "sha_convention": "x"},
                  open(f"{td}/receipts/{stale_name}", "w"))
        stale_sha = _sha(f"{td}/receipts/{stale_name}")

        def pair(legs, name=shard_name, sha=shard_sha, **kw):
            p = {"ticket": PAIR_TICKET, "ts": "x", "shard_receipt": name,
                 "shard_set_sha256": sha, "init_seed": 23, "seq": SEQ,
                 "token_budget": TOKEN_BUDGET,
                 "data_order_basis": "shard prefix, frozen order",
                 "legs": legs, "sha_convention": "x"}
            p.update(kw)
            return p

        # PASS at frozen lr (B=16) and boundary (exactly on the bar)
        p = pair([_leg(4, 2.500), _leg(16, 2.530)])
        assert check_pair(p, nc=td) == [], check_pair(p, nc=td)[:3]
        assert verdict(p)[0] == "PASS"
        assert verdict(pair([_leg(4, 2.5), _leg(16, 2.55)]))[0] == "PASS"
        # B=24 accounting (427 steps, overshoot tokens) binds
        p24 = pair([_leg(4, 2.5), _leg(24, 2.52, free=2.0)])
        assert check_pair(p24, nc=td) == [], check_pair(p24, nc=td)[:3]
        # frozen-lr miss -> scaled retry lands
        p2 = pair([_leg(4, 2.500), _leg(16, 2.600),
                   _leg(16, 2.540, lr=SCALED_LR)])
        assert check_pair(p2, nc=td) == [], check_pair(p2, nc=td)[:3]
        assert verdict(p2)[0] == "PASS-SCALED-LR"
        # both miss -> FAIL, deviation killed
        p3 = pair([_leg(4, 2.500), _leg(16, 2.700),
                   _leg(16, 2.650, lr=SCALED_LR)])
        assert check_pair(p3, nc=td) == []
        v, d = verdict(p3)
        assert v == "FAIL" and "KILLED" in d["deviation"]
        # --- Kai 14639 repro set: every one must now REFUSE ---
        assert any("ticket" in x for x in check_pair(
            pair([_leg(4, 2.5), _leg(16, 2.5)], ticket="WRONG"), nc=td))
        assert any("seq" in x for x in check_pair(
            pair([_leg(4, 2.5), _leg(16, 2.5)], seq=2048), nc=td))
        bad = pair([_leg(4, 2.5), dict(_leg(16, 2.5), steps=999)])
        assert any("accounting: steps" in x for x in check_pair(bad, nc=td))
        bad2 = pair([_leg(4, 2.5), dict(_leg(16, 2.5),
                                        tokens=TOKEN_BUDGET - 1)])
        assert any("accounting: tokens" in x
                   for x in check_pair(bad2, nc=td))
        retry_after_pass = pair([_leg(4, 2.500), _leg(16, 2.510),
                                 _leg(16, 2.505, lr=SCALED_LR)])
        assert any("PASSED rule 1" in x
                   for x in check_pair(retry_after_pass, nc=td))
        # shard provenance refusals
        assert any("STALE SHARDS" in x for x in check_pair(
            pair([_leg(4, 2.5), _leg(16, 2.5)], name=stale_name,
                 sha=stale_sha), nc=td))
        assert any("does not match" in x for x in check_pair(
            pair([_leg(4, 2.5), _leg(16, 2.5)], sha="f" * 64), nc=td))
        assert any("not found" in x for x in check_pair(
            pair([_leg(4, 2.5), _leg(16, 2.5)], name="absent.json"),
            nc=td))
        # untracked shard receipt refused when a tracked-set exists:
        # simulate by checking the message path via a git-less tmpdir is
        # exercised above (tracked None fallback); the tracked branch is
        # enforced in the live tree where _tracked() returns a set.
        # --- original refusal classes still hold ---
        assert any("CONFOUND" in x for x in check_pair(pair([
            _leg(4, 2.5), dict(_leg(16, 2.5),
                               governor={"vram_fraction": 0.85,
                                         "margin_gib_floor": 1.5,
                                         "pace_s_per_step": 0.05})]),
            nc=td))
        assert any("token_budget" in x for x in check_pair(
            pair([_leg(4, 2.5), _leg(16, 2.5)], token_budget=5), nc=td))
        assert any("FROZEN lr" in x or "frozen lr" in x.lower()
                   for x in check_pair(pair([_leg(4, 2.5),
                                             _leg(16, 2.5,
                                                  lr=SCALED_LR)]), nc=td))
        assert any("retry leg" in x for x in check_pair(pair([
            _leg(4, 2.5), _leg(16, 2.6),
            _leg(16, 2.55, lr={"lr_muon": 0.08, "lr_adamw": 0.0006})]),
            nc=td))
        assert any("ladder" in x for x in check_pair(
            pair([_leg(4, 2.5), _leg(32, 2.5)]), nc=td))
        assert any("B=24 requires" in x for x in check_pair(
            pair([_leg(4, 2.5), _leg(24, 2.5, free=0.9)]), nc=td))
        assert any("baseline" in x for x in check_pair(
            pair([_leg(8, 2.5), _leg(16, 2.5)]), nc=td))
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
        # nonzero on purpose (Kai 14639): the staged state must never be
        # readable as a passed gate by any caller
        print("FP32_E1B_GATE_STAGED (refuses until the trainer's "
              "FP32-E1B-LOSSMATCH pair receipt exists; executes after "
              "#218 + shard rerun, before --live)")
        raise SystemExit(1)
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
