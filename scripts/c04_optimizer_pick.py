#!/usr/bin/env python3
"""c04 optimizer/throughput PICK — the frozen cross-receipt decision.

FROZEN BEFORE THE DECIDING DATA LANDS (fp-39/fp-44 anti-goalpost-moving
discipline). The c04 design bench (eli) measures each candidate; fp44 measures
optimizer-equivalence; the batched-NS5 bench measures the Muon-throughput lever.
NONE of them makes the cross-receipt PICK. This does, mechanically.

THE WALL (measured, eli c04-receipt3 + dynamo-patch + fp40):
  clean c03-h1024-d20 eager = 16,834 tok/s paced; S3 gate needs 25,463
  (2.2e9 / 86400, one governed day). Levers, with MEASURED status:
    - torch.compile (torch 2.6): 1.024x  -> FALSIFIED (Tensor.backward
      Unsupported in fullgraph; forward-only ceiling). NOT the 1.5x assumed.
    - fused-muon (fp35):        ~1.08x   -> insufficient alone.
    - batched-NS5 Muon (fp45):  UNMEASURED in production -> the deciding lever.
    - AdamW-swap:               ADAMW_TOK_S=27702.8 >= 25463 -> clears S3 by
      ELIMINATING the 36% muon wall (fp40: adamw 3.69ms vs muon 285.83ms/step).
      Cost is optimizer QUALITY, measured by fp44 horizon-equiv.

THE FROZEN PRECEDENCE (best -> last-resort):
  P1 COMMIT_MUON_BATCHED  batched-NS5 production paced >= 25463 AND
                          ns5_equiv max_abs_delta <= 2e-7.
                          Best: design-preserving (keeps Muon), no env change,
                          S3 met -> fp44 AdamW/Muon comparison is MOOT.
  P2 (batched-NS5 short or absent) consult fp44 horizon-equiv:
     COMMIT_ADAMW         fp44 == COMMIT_ADAMW (|delta|<=noise or AdamW-lower)
                          AND ADAMW_TOK_S >= 25463. S3 cleared free, no env
                          change, quality equivalent. CHEAPER than torch bump.
     ESCALATE_TORCH_OR_TRADEOFF
                          fp44 == ESCALATE_USER_TRADEOFF (Muon strictly lower
                          loss beyond noise). To keep Muon-quality AND clear S3
                          needs the torch>=2.7 compile lever (shared-env major
                          bump) OR accept AdamW's quality gap. USER decides.
     HOLD                 fp44 == HOLD_INCONCLUSIVE (diverging / crossover).
  PENDING                 neither deciding receipt present.

Only the user moves the threshold or the precedence. Pure stdlib; reuses
fp44_horizon_equiv_gate.score_receipt() for the equiv leg.
"""
import sys, os, glob, json, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
RECEIPTS = f"{NC}/receipts"
sys.path.insert(0, HERE)
import fp44_horizon_equiv_gate as fp44   # reuse the frozen equiv gate

S3_THRESHOLD = 2.2e9 / 86400.0           # 25463.0 tok/s (one governed day)
NS5_EQUIV_TOL = 2e-7                      # fp45 kernel equivalence bar
ADAMW_TOK_S = fp44.ADAMW_TOK_S           # 27702.8, eng-363 paced (clears S3)
MUON_TOK_S = fp44.MUON_TOK_S             # 19223.3, muon_split_baseline paced


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ---- tolerant loaders -------------------------------------------------------

def _batched_ns5_paced(r):
    """Extract the production batched-NS5 (muon-batched arm) paced tok/s.
    Accepts top-level tok_s_paced, or arm_aggregate[muon-batched] mean_tok_s_paced
    / mean_tokens_per_s. Returns float or None."""
    if r is None:
        return None
    if isinstance(r.get("tok_s_paced"), (int, float)):
        return float(r["tok_s_paced"])
    agg = r.get("arm_aggregate") or {}
    for key in ("muon-batched", "muon_batched", "batched", "muon-2d-batched"):
        arm = agg.get(key)
        if isinstance(arm, dict):
            for f in ("mean_tok_s_paced", "mean_tokens_per_s", "tok_s_paced"):
                if isinstance(arm.get(f), (int, float)):
                    return float(arm[f])
    return None


def _ns5_equiv_max_delta(r):
    """Max abs NS5 equivalence delta across shapes. Accepts top-level
    max_abs_delta, ns5_equiv list of {max_abs_delta}, or ns5_equiv dict. None if absent."""
    if r is None:
        return None
    if isinstance(r.get("ns5_equiv_max_abs_delta"), (int, float)):
        return float(r["ns5_equiv_max_abs_delta"])
    eq = r.get("ns5_equiv")
    deltas = []
    if isinstance(eq, list):
        for e in eq:
            if isinstance(e, dict) and isinstance(e.get("max_abs_delta"), (int, float)):
                deltas.append(float(e["max_abs_delta"]))
    elif isinstance(eq, dict):
        if isinstance(eq.get("max_abs_delta"), (int, float)):
            deltas.append(float(eq["max_abs_delta"]))
        for v in eq.values():
            if isinstance(v, dict) and isinstance(v.get("max_abs_delta"), (int, float)):
                deltas.append(float(v["max_abs_delta"]))
    if isinstance(r.get("max_abs_delta"), (int, float)):
        deltas.append(float(r["max_abs_delta"]))
    return max(deltas) if deltas else None


def _load_batched_ns5(receipts_dir=RECEIPTS):
    """Latest c04 batched-NS5 production bench receipt (by ts/filename)."""
    chosen = None
    for p in sorted(glob.glob(f"{receipts_dir}/*.json")):
        try:
            r = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        tk = str(r.get("ticket", "")).lower()
        name = os.path.basename(p).lower()
        is_bns5 = ("batched" in tk and "ns5" in tk) or ("batched-ns5" in name) \
            or ("c04" in name and "batched" in name) or (tk == "c04-batched-ns5-bench")
        if is_bns5:
            if chosen is None or r.get("ts", os.path.basename(p)) > chosen.get("ts", ""):
                chosen = r
    return chosen


# ---- the frozen pick --------------------------------------------------------

def pick(batched_ns5_receipt, fp44_score):
    """The frozen precedence. Inputs:
       batched_ns5_receipt: dict or None (production batched-NS5 bench)
       fp44_score: dict from fp44.score_receipt(), or None if no fp44 receipt
    Returns the pick dict."""
    bns5_paced = _batched_ns5_paced(batched_ns5_receipt)
    bns5_equiv = _ns5_equiv_max_delta(batched_ns5_receipt)

    # P1 — batched-NS5 clears S3 with the kernel proven exact.
    if bns5_paced is not None and bns5_equiv is not None:
        if bns5_paced >= S3_THRESHOLD and bns5_equiv <= NS5_EQUIV_TOL:
            return {
                "pick": "COMMIT_MUON_BATCHED",
                "config": "c03-h1024-d20", "optimizer": "muon-batched-ns5",
                "dtype": "FP8", "ckpt": True, "compile": "fwd-only",
                "s3_met": True, "fp44_moot": True,
                "detail": (f"batched-NS5 paced {bns5_paced:.1f} >= {S3_THRESHOLD:.0f} "
                           f"AND ns5_equiv {bns5_equiv:.2e} <= {NS5_EQUIV_TOL:.0e}; "
                           "design-preserving, no env change, fp44 moot."),
                "measured_distance": 0.0,
            }
        # batched-NS5 present but short / not-exact -> fall to P2, record distance
        short_reason = []
        if bns5_paced < S3_THRESHOLD:
            short_reason.append(f"paced {bns5_paced:.1f} < {S3_THRESHOLD:.0f}")
        if bns5_equiv > NS5_EQUIV_TOL:
            short_reason.append(f"ns5_equiv {bns5_equiv:.2e} > {NS5_EQUIV_TOL:.0e}")
        bns5_note = "batched-NS5 SHORT (" + "; ".join(short_reason) + ")"
        bns5_distance = max(0.0, S3_THRESHOLD - bns5_paced)
    else:
        bns5_note = "batched-NS5 bench ABSENT"
        bns5_distance = None

    # P2 — consult fp44 horizon-equiv.
    if fp44_score is None or fp44_score.get("status") != "SCORED":
        return {
            "pick": "PENDING",
            "s3_met": False,
            "detail": f"{bns5_note}; fp44 horizon-equiv "
                      + ("SCHEMA_MISMATCH" if fp44_score else "ABSENT")
                      + " -> neither deciding receipt usable yet.",
            "measured_distance": bns5_distance,
        }
    v = fp44_score["verdict"]
    if v == "COMMIT_ADAMW":
        s3 = ADAMW_TOK_S >= S3_THRESHOLD
        return {
            "pick": "COMMIT_ADAMW",
            "config": "c03-h1024-d20", "optimizer": "adamw",
            "dtype": "FP8", "ckpt": True, "compile": "fwd-only",
            "s3_met": s3, "fp44_moot": False,
            "detail": (f"{bns5_note}; fp44 COMMIT_ADAMW ({fp44_score['detail'].get('reason','')}); "
                       f"AdamW paced {ADAMW_TOK_S:.1f} {'>=' if s3 else '<'} {S3_THRESHOLD:.0f} "
                       "-> eliminates 36% muon wall, S3 cleared free, no env change."),
            "measured_distance": 0.0 if s3 else (S3_THRESHOLD - ADAMW_TOK_S),
            "fp44_noise_floor": fp44_score.get("noise_floor"),
        }
    if v == "ESCALATE_USER_TRADEOFF":
        d = fp44_score["detail"]
        return {
            "pick": "ESCALATE_TORCH_OR_TRADEOFF",
            "s3_met": False, "fp44_moot": False,
            "detail": (f"{bns5_note}; fp44 ESCALATE_USER_TRADEOFF "
                       f"(Muon delta_T={d.get('delta_T')}, noise={d.get('noise_floor')}). "
                       "Muon-quality is real; keeping it AND clearing S3 needs the "
                       "torch>=2.7 compile lever (shared-env major bump) OR accept "
                       "AdamW's quality gap. USER decides quality-vs-env-risk-vs-deadline."),
            "muon_days": round(2.2e9 / MUON_TOK_S / 86400, 3),
            "adamw_days": round(2.2e9 / ADAMW_TOK_S / 86400, 3),
            "measured_distance": bns5_distance,
        }
    # HOLD_INCONCLUSIVE
    return {
        "pick": "HOLD",
        "s3_met": False,
        "detail": f"{bns5_note}; fp44 HOLD_INCONCLUSIVE "
                  f"({fp44_score['detail'].get('reason','')}) -> fp44 needs more data.",
        "measured_distance": bns5_distance,
    }


def analyze(receipts_dir=RECEIPTS):
    bns5 = _load_batched_ns5(receipts_dir)
    fp44_r = fp44._load_receipt()
    fp44_score = fp44.score_receipt(fp44_r) if fp44_r else None
    result = pick(bns5, fp44_score)
    result["ticket"] = "C04-OPTIMIZER-PICK"
    result["s3_threshold_tok_s"] = round(S3_THRESHOLD, 1)
    result["inputs"] = {
        "batched_ns5_receipt": bns5.get("ts") if bns5 else None,
        "fp44_receipt": fp44_r.get("ts") if fp44_r else None,
    }
    return result


# ---- selftest (synthetic receipts — all branches) ---------------------------

def _fp44_synth(verdict):
    """Build a synthetic fp44_score dict as score_receipt would return it."""
    return {"status": "SCORED", "verdict": verdict,
            "detail": {"reason": "synthetic", "delta_T": -0.3, "noise_floor": 0.05},
            "noise_floor": 0.05, "muon_traj": {}, "adamw_traj": {}}


def selftest():
    _utf8_stdout()
    print("[c04-pick] selftest: frozen 3-way precedence on synthetic receipts")
    ok = True

    # P1: batched-NS5 clears -> COMMIT_MUON_BATCHED, fp44 moot (even if escalate).
    r = pick({"tok_s_paced": 25600.0, "ns5_equiv": [{"max_abs_delta": 0.0}]},
             _fp44_synth("ESCALATE_USER_TRADEOFF"))
    cond = r["pick"] == "COMMIT_MUON_BATCHED" and r["s3_met"] and r["fp44_moot"]
    print(f"  P1 batched-NS5 clears (paced 25600, equiv 0) -> {r['pick']} "
          f"[{'PASS' if cond else 'FAIL'}]"); ok &= cond

    # P1 boundary: exactly at threshold passes (>=).
    r = pick({"tok_s_paced": S3_THRESHOLD, "ns5_equiv_max_abs_delta": NS5_EQUIV_TOL},
             None)
    cond = r["pick"] == "COMMIT_MUON_BATCHED"
    print(f"  P1 boundary (paced==thr, equiv==tol) -> {r['pick']} "
          f"[{'PASS' if cond else 'FAIL'}]"); ok &= cond

    # P1 fails equiv (kernel not exact) -> falls to P2.
    r = pick({"tok_s_paced": 26000.0, "ns5_equiv_max_abs_delta": 1e-5},
             _fp44_synth("COMMIT_ADAMW"))
    cond = r["pick"] == "COMMIT_ADAMW"
    print(f"  P1 equiv-fail (1e-5>2e-7) -> P2 -> {r['pick']} "
          f"[{'PASS' if cond else 'FAIL'}]"); ok &= cond

    # P2 batched-NS5 short + fp44 COMMIT_ADAMW -> COMMIT_ADAMW, S3 met (27702>=25463).
    r = pick({"tok_s_paced": 21000.0, "ns5_equiv_max_abs_delta": 0.0},
             _fp44_synth("COMMIT_ADAMW"))
    cond = r["pick"] == "COMMIT_ADAMW" and r["s3_met"] and r["measured_distance"] == 0.0
    print(f"  P2 ns5-short + fp44 AdamW-equiv -> {r['pick']} s3_met={r['s3_met']} "
          f"[{'PASS' if cond else 'FAIL'}]"); ok &= cond

    # P2 batched-NS5 short + fp44 ESCALATE -> ESCALATE_TORCH_OR_TRADEOFF.
    r = pick({"tok_s_paced": 21000.0, "ns5_equiv_max_abs_delta": 0.0},
             _fp44_synth("ESCALATE_USER_TRADEOFF"))
    cond = r["pick"] == "ESCALATE_TORCH_OR_TRADEOFF" and not r["s3_met"]
    print(f"  P2 ns5-short + fp44 Muon-better -> {r['pick']} "
          f"[{'PASS' if cond else 'FAIL'}]"); ok &= cond

    # P2 batched-NS5 short + fp44 HOLD -> HOLD.
    r = pick({"tok_s_paced": 21000.0, "ns5_equiv_max_abs_delta": 0.0},
             _fp44_synth("HOLD_INCONCLUSIVE"))
    cond = r["pick"] == "HOLD"
    print(f"  P2 ns5-short + fp44 HOLD -> {r['pick']} "
          f"[{'PASS' if cond else 'FAIL'}]"); ok &= cond

    # PENDING: batched-NS5 absent + fp44 absent.
    r = pick(None, None)
    cond = r["pick"] == "PENDING" and not r["s3_met"]
    print(f"  PENDING (both absent) -> {r['pick']} "
          f"[{'PASS' if cond else 'FAIL'}]"); ok &= cond

    # PENDING: batched-NS5 absent + fp44 schema-mismatch.
    r = pick(None, {"status": "SCHEMA_MISMATCH", "arms_seen": []})
    cond = r["pick"] == "PENDING"
    print(f"  PENDING (ns5 absent, fp44 schema-mismatch) -> {r['pick']} "
          f"[{'PASS' if cond else 'FAIL'}]"); ok &= cond

    # loader tolerance: arm_aggregate form.
    paced = _batched_ns5_paced({"arm_aggregate": {"muon-batched": {"mean_tokens_per_s": 25500.0}}})
    cond = paced == 25500.0
    print(f"  loader arm_aggregate form -> {paced} [{'PASS' if cond else 'FAIL'}]"); ok &= cond

    # equiv loader: list-of-shapes max.
    mx = _ns5_equiv_max_delta({"ns5_equiv": [{"max_abs_delta": 1e-8}, {"max_abs_delta": 5e-8}]})
    cond = mx == 5e-8
    print(f"  loader ns5_equiv list-max -> {mx} [{'PASS' if cond else 'FAIL'}]"); ok &= cond

    print("C04_OPTIMIZER_PICK_SELFTEST_" + ("PASS" if ok else "FAIL"))
    return ok


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--receipts", default=RECEIPTS)
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    result = analyze(args.receipts)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
