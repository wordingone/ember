"""fp44_horizon_equiv_gate.py — pre-registered gate for the c04 optimizer commit.

FROZEN BEFORE eli's horizon-equiv receipt exists (anti-goalpost-moving, the
fp39/fp42 discipline): the decision boundary and the noise-floor definition are
fixed here, so when the receipt lands the verdict is mechanical, not
re-interpreted against the data.

CONTEXT
-------
eng-363 broke the §3 throughput wall via the optimizer axis: c03 + full_fused_adamw
= 27,703 tok/s (clears 25,463). The fused-Muon kernel (#329/fp35) is VIABLE but
only +8.1% — far short of the ~3.2x needed to keep Muon under the ≤1-day bar. So
the §3-clearing optimizer is AdamW, which DROPS Muon (the C-3 design optimizer).

eli's eng-363 equiv_pass is 100-step (losses→0 by step 25) — structurally blind
to a cross-optimizer swap (the fp-40 pseudo-replication class). fp-44 is the
2000-step REAL-data equiv that actually certifies whether AdamW matches Muon's
quality at a pretrain-relevant horizon. THIS gate scores that receipt.

THE FROZEN DECISION RULE (val_loss in nats; delta = muon − adamw, so delta<0 ⇒
Muon lower loss ⇒ Muon better)
-----------------------------------------------------------------------------
At the terminal step T (2000):
  1. AdamW diverging (adamw val_loss monotone-increasing over the last 3 points)
       → HOLD_INCONCLUSIVE (never commit a diverging optimizer).
  2. sign(delta) unstable across the last 3 points (a crossover)
       → HOLD_INCONCLUSIVE (noisy; needs a longer horizon, not a coin-flip).
  3. |delta@T| ≤ noise_floor                  → COMMIT_ADAMW (equivalent; AdamW
       is strictly preferable since it clears §3 at ≤1 day, Muon does not).
  4. delta@T >  +noise_floor (AdamW lower)    → COMMIT_ADAMW (AdamW faster AND
       better — strict win).
  5. delta@T <  −noise_floor (Muon lower)     → ESCALATE_USER_TRADEOFF (Muon's
       sample-efficiency is real: Muon 19,223 tok/s = 1.32 governed days vs
       AdamW ≤1 day. The ≤1-day relaxation is the user's call, §4.5 residual.
       Leo presents the measured delta; AdamW is NOT auto-picked to dodge it).

noise_floor (frozen definition): max(harness-derived equiv threshold,
paired-seed val_loss std at T). If the receipt carries a derived noise floor
(the #367 equiv-harness convention), it is the lower bound; the seed spread can
only widen it. Default floor 0.05 nats if neither present (conservative — a
real density/quality gap exceeds it).

EXPECTED RECEIPT SCHEMA (documented so eli's eng/329c harness can match it; the
loader is tolerant and falls back across key spellings):
  ticket: "FP44-HORIZON-OPTIMIZER-EQUIV" (or contains "horizon" + "equiv")
  arms: { "muon"|"muon_split_baseline": {"val_loss": {"250":.., "2000":..},
                                          "seed_val_loss_at_T": [.., ..]},
          "adamw"|"full_fused_adamw":   {"val_loss": {...}, ...} }
  noise_floor_nats / derived_threshold_nats: optional harness-derived floor.

Emits a verdict receipt; selftest validates the decision logic on synthetic cases.
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
TERMINAL_STEP = "2000"
DEFAULT_NOISE_FLOOR = 0.05          # nats, conservative fallback
ADAMW_TOK_S = 27702.8               # eng-363 paced
MUON_TOK_S = 19223.3               # eng-363 muon_split_baseline paced
S3_THRESHOLD = 2.2e9 / 86400       # 25463 tok/s
MUON_ARM_KEYS = ("muon", "muon_split_baseline", "muon_ns5", "muon_baseline")
ADAMW_ARM_KEYS = ("adamw", "full_fused_adamw", "fused_adamw")


def _traj(arm):
    """Pull the {step: val_loss} trajectory from an arm block, tolerant of keys.
    `val_losses` (plural) is eli's eng/329c spelling; the rest are doc spellings."""
    for k in ("val_loss", "val_losses", "val_loss_nats", "losses_at", "val_loss_at"):
        if isinstance(arm.get(k), dict):
            return {str(s): float(v) for s, v in arm[k].items() if v is not None}
    return {}


def _seed_spread_at_T(arm, T=TERMINAL_STEP):
    """Paired-seed std of val_loss at T, if the arm carries per-seed values."""
    for k in ("seed_val_loss_at_T", "seed_val_loss", f"seed_val_loss_{T}"):
        v = arm.get(k)
        if isinstance(v, list) and len(v) >= 2:
            m = sum(v) / len(v)
            return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5
    return None


def _pick_arm(arms, keys):
    for k in keys:
        if k in arms:
            return arms[k]
    return None


def _last3(traj):
    """val_loss at the last 3 available ascending steps."""
    steps = sorted(traj.keys(), key=lambda s: int(s))
    return [traj[s] for s in steps[-3:]]


def _monotone_increasing(xs):
    return len(xs) >= 2 and all(b > a for a, b in zip(xs, xs[1:]))


def decide(muon_traj, adamw_traj, noise_floor, T=TERMINAL_STEP):
    """The frozen rule. Returns (verdict, detail dict)."""
    if T not in muon_traj or T not in adamw_traj:
        return "HOLD_INCONCLUSIVE", {"reason": f"no terminal step {T} in one/both arms"}
    delta_T = muon_traj[T] - adamw_traj[T]          # <0 ⇒ Muon lower (better)
    a_last3 = _last3(adamw_traj)
    # last-3 deltas for crossover detection
    common = sorted(set(muon_traj) & set(adamw_traj), key=lambda s: int(s))[-3:]
    d_last3 = [muon_traj[s] - adamw_traj[s] for s in common]

    if _monotone_increasing(a_last3):
        return "HOLD_INCONCLUSIVE", {"reason": "adamw val_loss diverging (monotone↑ last3)",
                                     "adamw_last3": a_last3}
    # crossover = genuine sign flip, counting only deltas that EXCEED the noise
    # floor on each side (a within-noise 0-ish delta is not a Muon/AdamW vote).
    signs = {(_d > noise_floor) - (_d < -noise_floor) for _d in d_last3}
    if 1 in signs and -1 in signs:
        return "HOLD_INCONCLUSIVE", {"reason": "sign(delta) crossover in last3 (noisy)",
                                     "delta_last3": d_last3}
    if abs(delta_T) <= noise_floor:
        return "COMMIT_ADAMW", {"reason": "|delta|<=noise → equivalent; AdamW clears §3 at ≤1 day",
                                "delta_T": delta_T, "noise_floor": noise_floor}
    if delta_T > noise_floor:
        return "COMMIT_ADAMW", {"reason": "AdamW lower loss AND faster — strict win",
                                "delta_T": delta_T, "noise_floor": noise_floor}
    return "ESCALATE_USER_TRADEOFF", {
        "reason": "Muon meaningfully lower loss — sample-efficiency real",
        "delta_T": delta_T, "noise_floor": noise_floor,
        "muon_days": round(2.2e9 / MUON_TOK_S / 86400, 3),
        "adamw_days": round(2.2e9 / ADAMW_TOK_S / 86400, 3)}


def _load_receipt():
    chosen = None
    for p in sorted(glob.glob(f"{RECEIPTS}/*.json")):
        try:
            r = json.load(open(p))
        except Exception:
            continue
        tk = str(r.get("ticket", "")).lower()
        if "horizon" in tk and "equiv" in tk or r.get("ticket") == "FP44-HORIZON-OPTIMIZER-EQUIV":
            if chosen is None or r.get("ts", "") > chosen.get("ts", ""):
                chosen = r
    return chosen


def score_receipt(r):
    """Full receipt → verdict pipeline (loader + arm-pick + noise-floor + decide).
    Returns a dict with status SCORED / SCHEMA_MISMATCH. Pure (no I/O) so the
    selftest can exercise the whole path on synthetic receipts."""
    arms = r.get("arms") or r.get("cells") or {}
    if isinstance(arms, list):  # cells-as-list fallback
        arms = {c.get("arm") or c.get("cell"): c for c in arms}
    if not arms:
        # eli's eng/329c schema: no `arms` block — per-arm results sit at the top
        # level as {muon,adamw}_result, each {arm, val_losses, ...}. Build the
        # arms map from any *_result dict carrying an `arm` label + a trajectory.
        arms = {v["arm"]: v for k, v in r.items()
                if k.endswith("_result") and isinstance(v, dict) and v.get("arm")}
    muon = _pick_arm(arms, MUON_ARM_KEYS)
    adamw = _pick_arm(arms, ADAMW_ARM_KEYS)
    if not muon or not adamw:
        return {"status": "SCHEMA_MISMATCH", "arms_seen": list(arms.keys())}
    mt, at = _traj(muon), _traj(adamw)
    # noise-floor reader — tolerant across key spellings. eli's Phase-1 harness
    # log prints `noise_floor=` / `derived_threshold=` (NO _nats suffix); the
    # receipt may carry either spelling. Reading ONLY the _nats variants would
    # silently miss a real ~0.6-nat floor and fall back to DEFAULT 0.05 — a far
    # TIGHTER floor that would FALSE-ESCALATE a within-noise delta to a user
    # decision (delta -0.3 is equivalent under 0.6 but Muon-better under 0.05).
    # eli nests the derived floor under noise_floor_run.{derived_threshold,
    # noise_floor}; top-level spellings are the doc convention. Read both.
    nfr = r.get("noise_floor_run") if isinstance(r.get("noise_floor_run"), dict) else {}
    derived = (r.get("noise_floor_nats") or r.get("derived_threshold_nats")
               or r.get("noise_floor") or r.get("derived_threshold")
               or nfr.get("derived_threshold") or nfr.get("noise_floor") or 0.0)
    seed_spread = _seed_spread_at_T(adamw) or _seed_spread_at_T(muon) or 0.0
    floor_candidates = {"derived": float(derived),
                        "seed_spread": float(seed_spread),
                        "default": DEFAULT_NOISE_FLOOR}
    noise_floor = max(floor_candidates.values())
    # source is the RED FLAG: "default" means no derived floor was read — if a
    # Phase-1 noise floor was expected, that signals a schema/key mismatch.
    noise_floor_source = max(floor_candidates, key=floor_candidates.get)
    verdict, detail = decide(mt, at, noise_floor)
    return {"status": "SCORED", "verdict": verdict, "detail": detail,
            "noise_floor": noise_floor, "noise_floor_source": noise_floor_source,
            "muon_traj": mt, "adamw_traj": at}


def analyze():
    r = _load_receipt()
    if r is None:
        print(json.dumps({"verdict": "NO_RECEIPT_YET",
                          "note": "fp-44 horizon-equiv receipt not on disk; gate frozen + selftested"}))
        sys.exit(2)
    s = score_receipt(r)
    if s["status"] != "SCORED":
        print(json.dumps(s))
        sys.exit(2)
    verdict, detail, noise_floor, mt, at = (
        s["verdict"], s["detail"], s["noise_floor"], s["muon_traj"], s["adamw_traj"])

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP44-HORIZON-EQUIV-GATE", "ts": ts, "issue": 377,
        "scored_receipt_ts": r.get("ts"), "verdict": verdict, "detail": detail,
        "noise_floor_nats": noise_floor,
        "noise_floor_source": s.get("noise_floor_source"), "terminal_step": TERMINAL_STEP,
        "muon_val_loss_traj": mt, "adamw_val_loss_traj": at,
        "s3_threshold_tok_s": round(S3_THRESHOLD, 1),
        "consequence": {
            "COMMIT_ADAMW": "c04 pick = c03-class + AdamW → gate-9 → pretrain (≤1 day @27703 tok/s)",
            "ESCALATE_USER_TRADEOFF": "present Muon-quality vs ≤1-day bar to user (§4.5); no auto-pick",
            "HOLD_INCONCLUSIVE": "longer horizon / re-seed before any commit",
        }[verdict],
    }
    out = f"{RECEIPTS}/fp44-horizon-equiv-gate-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps({"verdict": verdict, "detail": detail, "noise_floor": noise_floor}, indent=2))
    print(f"FP44_HORIZON_EQUIV_GATE_DONE {os.path.relpath(out, NC)}")
    return verdict


def selftest():
    nf = 0.1
    cases = [
        # (muon_traj, adamw_traj, expected, label)
        ({"250": 2.0, "1000": 1.2, "2000": 1.00}, {"250": 2.0, "1000": 1.2, "2000": 1.00},
         "COMMIT_ADAMW", "exact equiv -> AdamW (clears s3)"),
        ({"250": 2.0, "1000": 1.2, "2000": 1.04}, {"250": 2.0, "1000": 1.2, "2000": 1.00},
         "COMMIT_ADAMW", "within-noise (d=0.04<=0.1) -> AdamW"),
        ({"250": 2.0, "1000": 1.3, "2000": 1.50}, {"250": 2.0, "1000": 1.2, "2000": 1.00},
         "COMMIT_ADAMW", "AdamW lower (d=+0.5) -> strict win"),
        ({"250": 2.0, "1000": 1.0, "2000": 0.50}, {"250": 2.0, "1000": 1.2, "2000": 1.00},
         "ESCALATE_USER_TRADEOFF", "Muon lower (d=-0.5) -> user tradeoff"),
        ({"1000": 1.0, "1500": 1.0, "2000": 1.0}, {"1000": 0.8, "1500": 0.9, "2000": 1.0},
         "HOLD_INCONCLUSIVE", "adamw diverging (monotone-up) -> hold"),
        ({"1000": 1.3, "1500": 0.9, "2000": 1.30}, {"1000": 1.0, "1500": 1.1, "2000": 1.00},
         "HOLD_INCONCLUSIVE", "sign crossover last3 -> hold"),
    ]
    ok = True
    for mt, at, exp, lbl in cases:
        got, _ = decide(mt, at, nf)
        match = got == exp
        ok = ok and match
        print(f"  [{'PASS' if match else 'FAIL'}] {lbl}: {got}")
    # noise-floor monotonicity: a derived floor can only widen, never shrink, the boundary
    c_floor = (max(0.2, 0.0, DEFAULT_NOISE_FLOOR) == 0.2)
    print(f"  [{'PASS' if c_floor else 'FAIL'}] noise_floor = max(derived, seed_spread, default)")
    ok = ok and c_floor

    # FULL-PIPELINE cases on synthetic receipts matching eli's eng/329c protocol
    # (Phase-1 noise floor + Phase-2 muon_split_baseline & full_fused_adamw arms,
    # val_loss @{250,500,1000,1500,2000}). Exercises score_receipt (loader +
    # arm-pick + noise-floor assembly), which the decide() cases above do not.
    def _rcpt(muon2k, adamw2k, nf=None, adamw_seeds=None):
        steps = {"250": 2.2, "500": 1.8, "1000": 1.4, "1500": 1.2}
        m = dict(steps, **{"2000": muon2k})
        a = dict(steps, **{"2000": adamw2k})
        r = {"ticket": "FP44-HORIZON-OPTIMIZER-EQUIV",
             "arms": {"muon_split_baseline": {"val_loss": m},
                      "full_fused_adamw": {"val_loss": a}}}
        if nf is not None:
            r["noise_floor_nats"] = nf
        if adamw_seeds is not None:
            r["arms"]["full_fused_adamw"]["seed_val_loss_at_T"] = adamw_seeds
        return r
    pipe = [
        (_rcpt(1.00, 1.00, nf=0.08), "COMMIT_ADAMW", None, "receipt equiv (nf=0.08) -> AdamW"),
        (_rcpt(0.50, 1.00, nf=0.08), "ESCALATE_USER_TRADEOFF", None, "receipt muon-ahead -> tradeoff"),
        # no derived floor; adamw seed spread [1.0,1.3] std~0.212 sets the floor, so
        # a muon=1.15 vs adamw=1.00 (delta 0.15) is WITHIN noise -> COMMIT_ADAMW
        (_rcpt(1.15, 1.00, adamw_seeds=[1.0, 1.3]), "COMMIT_ADAMW", 0.21, "receipt seed-std floor -> AdamW"),
    ]
    for r, exp_v, exp_nf, lbl in pipe:
        s = score_receipt(r)
        match = s.get("status") == "SCORED" and s.get("verdict") == exp_v
        if exp_nf is not None:
            match = match and abs(s.get("noise_floor", 0) - exp_nf) < 0.02
        ok = ok and match
        print(f"  [{'PASS' if match else 'FAIL'}] {lbl}: {s.get('verdict', s.get('status'))}"
              + (f" nf={s.get('noise_floor'):.3f}" if "noise_floor" in s else ""))
    # noise-floor field-name tolerance: receipt carries `noise_floor` (NO _nats
    # — eli's Phase-1 log spelling). muon=1.0 adamw=1.3 (delta=-0.3, Muon lower):
    # with the 0.605 floor READ -> COMMIT_ADAMW (within noise); if the field were
    # MISSED -> default 0.05 -> would ESCALATE. Proves the field is consumed AND
    # noise_floor_source flags it 'derived', not 'default'.
    r_nf = {"ticket": "FP44-HORIZON-OPTIMIZER-EQUIV", "noise_floor": 0.605,
            "arms": {"muon_split_baseline": {"val_loss": {"250": 2.2, "1000": 1.4, "2000": 1.0}},
                     "full_fused_adamw":   {"val_loss": {"250": 2.2, "1000": 1.5, "2000": 1.3}}}}
    s_nf = score_receipt(r_nf)
    c_nf = (s_nf.get("verdict") == "COMMIT_ADAMW"
            and abs(s_nf.get("noise_floor", 0) - 0.605) < 1e-9
            and s_nf.get("noise_floor_source") == "derived")
    print(f"  [{'PASS' if c_nf else 'FAIL'}] noise_floor (no _nats) consumed -> "
          f"{s_nf.get('verdict')} nf={s_nf.get('noise_floor')} src={s_nf.get('noise_floor_source')}")
    ok = ok and c_nf
    # default-fallback flag: no derived floor + no seed spread -> source 'default'
    s_def = score_receipt({"ticket": "x-horizon-equiv",
                           "arms": {"muon": {"val_loss": {"2000": 1.0}},
                                    "adamw": {"val_loss": {"2000": 1.0}}}})
    c_def = s_def.get("noise_floor_source") == "default" and s_def.get("noise_floor") == DEFAULT_NOISE_FLOOR
    print(f"  [{'PASS' if c_def else 'FAIL'}] no derived floor -> source 'default' (red flag) "
          f"src={s_def.get('noise_floor_source')}")
    ok = ok and c_def

    # eli's eng/329c REAL schema (the exact shape of the landed receipt
    # fp44-horizon-optimizer-equiv-20260613T102516Z): NO `arms` block — per-arm
    # {muon,adamw}_result with val_losses (plural); noise floor nested under
    # noise_floor_run.derived_threshold. Locks the loader against regression.
    r_eli = {"ticket": "FP44-HORIZON-OPTIMIZER-EQUIV",
             "noise_floor_run": {"derived_threshold": 0.605468, "noise_floor": 0.605468},
             "muon_result": {"arm": "muon_split_baseline",
                             "val_losses": {"250": 8.86, "500": 7.74, "1000": 6.38,
                                            "1500": 7.08, "2000": 6.2305}},
             "adamw_result": {"arm": "full_fused_adamw",
                              "val_losses": {"250": 9.39, "500": 8.98, "1000": 7.32,
                                             "1500": 7.39, "2000": 6.9766}}}
    s_eli = score_receipt(r_eli)
    c_eli = (s_eli.get("status") == "SCORED"
             and s_eli.get("verdict") == "ESCALATE_USER_TRADEOFF"
             and s_eli.get("noise_floor_source") == "derived"
             and abs(s_eli.get("noise_floor", 0) - 0.605468) < 1e-6)
    print(f"  [{'PASS' if c_eli else 'FAIL'}] eli real schema (muon_result/adamw_result/"
          f"noise_floor_run) -> {s_eli.get('verdict')} src={s_eli.get('noise_floor_source')}")
    ok = ok and c_eli

    # schema-mismatch path
    sm = score_receipt({"arms": {"sgd": {"val_loss": {"2000": 1.0}}}})
    c_sm = sm.get("status") == "SCHEMA_MISMATCH"
    print(f"  [{'PASS' if c_sm else 'FAIL'}] unknown arms -> SCHEMA_MISMATCH")
    ok = ok and c_sm

    print("FP44_HORIZON_EQUIV_GATE_SELFTEST_" + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    analyze()
