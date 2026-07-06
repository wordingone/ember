"""fp32_step_econ_bench.py — pretrain step-economics sweep on the frozen
v0 shape (#225, fp-32 row R1/R2): is the frozen batch=4 a measured choice
or an inherited bench-harness default costing wall-days on the critical
path?

First-principles claim under test (fp-32 ledger rows R1+R2):
  wall_days = T / (B*SEQ / (t_compute(B) + PACE_S)) / 86400
  - At B=4, t_compute ~= 0.169 s (fp19-bench c03-qat raw 24,294.7 tok/s),
    so the 0.05 s/step governor pace is a 22.9% wall tax (RECEIPTED:
    1 - 18737.7/24294.7) and the SMs are scheduling-starved (0.37B model,
    4k tokens/step, 17.19 GiB VRAM left idle).
  - Raising B amortizes BOTH the pace sleep and the per-step fixed costs
    (QAT clone+quant of every Linear weight each step) WITHOUT loosening
    the governor: PACE_S stays 0.05, VRAM fraction stays 0.80, the margin
    assert stays 1.5 GiB. Duty-cycle pacing is preserved; it just buys
    more tokens per paced step.

Anchor discipline: cell 1 re-runs the exact fp19-bench c03-qat cell
(batch 4, grad-ckpt ON, eager). If it fails to reproduce the receipted
baseline within ANCHOR_TOL, the whole comparison is VOID (anchor_ok
false, verdict ANCHOR-DRIFT) — gains are only claimable against a
reproduced baseline, never against a number from a different day's
conditions.

Safety: same rails as fp19_bench — set_per_process_memory_fraction(0.80),
post-warmup free-VRAM margin assert >= 1.5 GiB, PACE_S sleep inside the
timed loop. A cell that OOMs or violates the margin is recorded
SKIPPED-* and the next cell launches fresh (cell-granular kill-and-
relaunch; no in-place retry, no fix-forward). torch.compile failure on
the QAT graph records the cell COMPILE-FAILED and continues (the frozen
config itself names eager fallback as the receipted deviation path).

Projection binds the LIVE tokenizer-freeze total via fp-30's binder, so
the receipt can never quote a stale corpus total (#216 discipline).

Run via daemon (GPU window). `--selftest` is pure-logic, no GPU.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fp19_bench as fp19                               # noqa: E402
import fp30_total_consistency as fp30                   # noqa: E402
from receipt_write import checked_write                 # noqa: E402
from receipt_check import validate_receipt              # noqa: E402

RECEIPTS = f"{NC}/receipts"
SEQ = fp19.SEQ
VOCAB = fp19.VOCAB
PACE_S = fp19.PACE_S            # governor floor — NEVER loosened here
VRAM_FRACTION = 0.80
MARGIN_GIB = fp19.MARGIN_GIB
WARMUP = 3
WARMUP_COMPILE = 8              # inductor compiles on first calls
TIMED = 10
VARIANT = "qat"                 # the frozen v0 precision shape

ANCHOR_EXPECTED = 18737.7       # fp19-bench-20260611T024648Z c03-qat paced
ANCHOR_RECEIPT = "fp19-bench-20260611T024648Z.json"
ANCHOR_TOL = 0.10               # |drift| <= 10% or the comparison is void
GAIN_FLOOR = 1.05               # >=5% over the REPRODUCED anchor to claim

# (batch, grad_ckpt, compile) — anchor first; eager batch sweep; then
# recompute-off; the compile cell is appended at the best feasible batch.
CELLS = (
    (4, True, False),           # ANCHOR — exact fp19 c03-qat conditions
    (8, True, False),
    (16, True, False),
    (24, True, False),
    (32, True, False),
    (48, True, False),          # L2 — B-ladder knee probe
    (4, False, False),           # L5 completeness
    (8, False, False),           # L5 completeness
    (16, False, False),
    (32, False, False),
    (48, False, False),         # L5 — checkpointing-OFF knee probe
)
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")


def cell_id(batch, ckpt, comp):
    return (f"b{batch}-{'ckpt' if ckpt else 'nockpt'}-"
            f"{'compile' if comp else 'eager'}")


def pacing_tax(paced, raw):
    return round(1.0 - paced / raw, 4) if raw else None


def v0_days(tok_s_paced, total):
    return round(total / (tok_s_paced * 86400.0), 3)


def bench_cell(batch, ckpt, comp):
    """One governed cell on the c03/qat shape. Returns a result dict;
    never raises on OOM/margin/compile failure (records and moves on)."""
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM

    c = fp19.CONFIGS["c03"]
    out = {"cell": cell_id(batch, ckpt, comp), "batch": batch, "seq": SEQ,
           "grad_checkpointing": ckpt, "compiled": comp, "variant": VARIANT,
           "timed_steps": TIMED}
    try:
        conf = LlamaConfig(
            vocab_size=VOCAB, hidden_size=c["hidden"],
            intermediate_size=4 * c["hidden"],
            num_hidden_layers=c["layers"], num_attention_heads=c["heads"],
            num_key_value_heads=c["heads"], max_position_embeddings=SEQ,
            tie_word_embeddings=True,
        )
        model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
        if ckpt:
            model.gradient_checkpointing_enable()
        model.train()
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)

        fwd = model
        if comp:
            try:
                fwd = torch.compile(model)
            except Exception as e:
                out["status"] = "COMPILE-FAILED"
                out["error"] = f"{type(e).__name__}: {e}"[:300]
                del model, opt
                torch.cuda.empty_cache()
                return out

        def step():
            saved = fp19._apply_fake_quant(model, VARIANT)
            ids = torch.randint(0, VOCAB, (batch, SEQ), device="cuda")
            o = fwd(input_ids=ids, labels=ids)
            o.loss.backward()
            fp19._restore(saved)
            opt.step()
            opt.zero_grad(set_to_none=True)

        for _ in range(WARMUP_COMPILE if comp else WARMUP):
            step()
        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            del model, opt
            torch.cuda.empty_cache()
            return out

        t0 = time.perf_counter()
        for _ in range(TIMED):
            step()
            torch.cuda.synchronize()
            time.sleep(PACE_S)
        dt = time.perf_counter() - t0
        toks = TIMED * batch * SEQ
        paced, raw = toks / dt, toks / (dt - TIMED * PACE_S)
        out.update(status="OK", tok_s_paced=round(paced, 1),
                   tok_s_raw=round(raw, 1),
                   pacing_tax=pacing_tax(paced, raw))
        del model, opt
        torch.cuda.empty_cache()
        return out
    except torch.cuda.OutOfMemoryError:
        out["status"] = "SKIPPED-OOM"
        torch.cuda.empty_cache()
        return out
    except Exception as e:
        # a cell must NEVER take the run down (the first run lost all its
        # measured cells to an un-contained dynamo NameError in the
        # compile cell — the receipt has to survive any single cell)
        out["status"] = "CELL-ERROR"
        out["error"] = f"{type(e).__name__}: {e}"[:300]
        torch.cuda.empty_cache()
        return out


def analyze(cells, total, anchor_expected=ANCHOR_EXPECTED,
            anchor_tol=ANCHOR_TOL, gain_floor=GAIN_FLOOR):
    """Pure logic: anchor check, best safe cell, projection, verdict."""
    anchor = cells[0]
    ok_cells = [c for c in cells if c.get("status") == "OK"]
    res = {"anchor": {"receipt": ANCHOR_RECEIPT,
                      "expected_tok_s_paced": anchor_expected}}
    if anchor.get("status") != "OK":
        res["anchor"]["anchor_ok"] = False
        res["verdict"] = "ANCHOR-DRIFT"
        return res
    drift = anchor["tok_s_paced"] / anchor_expected - 1.0
    anchor_ok = abs(drift) <= anchor_tol
    res["anchor"].update(measured_tok_s_paced=anchor["tok_s_paced"],
                         drift_pct=round(100 * drift, 2),
                         anchor_ok=anchor_ok)
    if not ok_cells:
        res["verdict"] = "NO-FEASIBLE-CELL"
        return res
    best = max(ok_cells, key=lambda c: c["tok_s_paced"])
    speedup = best["tok_s_paced"] / anchor["tok_s_paced"]
    res["best_safe"] = {"cell": best["cell"],
                        "tok_s_paced": best["tok_s_paced"],
                        "speedup_vs_anchor": round(speedup, 3)}
    res["projection_live_total"] = {
        "real_token_total": total,
        "v0_days_at_anchor": v0_days(anchor["tok_s_paced"], total),
        "v0_days_at_best": v0_days(best["tok_s_paced"], total),
    }
    res["projection_live_total"]["days_saved"] = round(
        res["projection_live_total"]["v0_days_at_anchor"]
        - res["projection_live_total"]["v0_days_at_best"], 3)
    if not anchor_ok:
        res["verdict"] = "ANCHOR-DRIFT"
    elif speedup >= gain_floor:
        res["verdict"] = "GAIN"
    else:
        res["verdict"] = "NO-GAIN"
    return res


def build_receipt(ts, cells, freeze_name, total):
    return {
        "ticket": "FP32-STEP-ECON",
        "ts": ts,
        "issue": 225,
        "shape": "c03 (frozen v0: hidden 1024, layers 20, heads 16, "
                 "seq 1024) variant qat",
        "governor": {"vram_fraction": VRAM_FRACTION,
                     "margin_gib_floor": MARGIN_GIB,
                     "pace_s_per_step": PACE_S,
                     "note": "pace/fraction/margin identical to the fp19 "
                             "baseline — amortized by batch, never "
                             "loosened"},
        "live_freeze_receipt": freeze_name,
        "cells": cells,
        "result": analyze(cells, total),
        "deviation_note": "a GAIN here is EVIDENCE for a registered "
                          "deviation to configs/v0-pretrain-config.json "
                          "throughput.batch (+ optimizer-coupling note); "
                          "it changes NOTHING by itself — the config stays "
                          "frozen until the deviation PR lands through "
                          "the gate",
        "sha_convention": SHA_CONVENTION,
    }


def _selftest():
    # projection + pacing math
    assert v0_days(18737.7, 6_973_632_296) == 4.308, \
        v0_days(18737.7, 6_973_632_296)
    assert abs(pacing_tax(18737.7, 24294.7) - 0.2287) < 1e-4
    # analyze: GAIN branch
    mk = lambda cid, p, r: {"cell": cid, "status": "OK",  # noqa: E731
                            "tok_s_paced": p, "tok_s_raw": r}
    cells = [mk("b4-ckpt-eager", 18800.0, 24300.0),
             mk("b32-ckpt-eager", 36000.0, 38000.0),
             {"cell": "b32-nockpt-eager", "status": "SKIPPED-OOM"}]
    r = analyze(cells, 7_000_000_000)
    assert r["anchor"]["anchor_ok"] and r["verdict"] == "GAIN", r
    assert r["best_safe"]["cell"] == "b32-ckpt-eager"
    assert r["projection_live_total"]["days_saved"] > 2.0
    # NO-GAIN branch (below the 5% floor)
    r2 = analyze([mk("b4-ckpt-eager", 18800.0, 24300.0),
                  mk("b8-ckpt-eager", 19100.0, 24400.0)], 7_000_000_000)
    assert r2["verdict"] == "NO-GAIN", r2
    # ANCHOR-DRIFT voids the comparison even with a fast cell
    r3 = analyze([mk("b4-ckpt-eager", 25000.0, 30000.0),
                  mk("b32-ckpt-eager", 50000.0, 52000.0)], 7_000_000_000)
    assert r3["verdict"] == "ANCHOR-DRIFT", r3
    # anchor cell itself failed -> void
    r4 = analyze([{"cell": "b4-ckpt-eager", "status": "SKIPPED-OOM"}],
                 7_000_000_000)
    assert r4["verdict"] == "ANCHOR-DRIFT", r4
    # receipt shape
    rec = build_receipt("20260101T000000Z", cells,
                        "tokenizer-freeze-x.json", 7_000_000_000)
    assert validate_receipt(rec) == [], validate_receipt(rec)
    print("FP32_STEP_ECON_SELFTEST_PASS")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    freeze_name, total = fp30.live_freeze(NC)
    assert freeze_name, "no clean tokenizer-freeze receipt — projection " \
                        "has no live total to bind"
    cells = []
    for batch, ckpt, comp in CELLS:
        print(f"[fp32] cell {cell_id(batch, ckpt, comp)} ...", flush=True)
        cells.append(bench_cell(batch, ckpt, comp))
        print(f"[fp32]   -> {json.dumps(cells[-1])}", flush=True)
    ok = [c for c in cells if c.get("status") == "OK"]
    if ok:
        best = max(ok, key=lambda c: c["tok_s_paced"])
        cells.append(bench_cell(best["batch"], best["grad_checkpointing"],
                                True))
        print(f"[fp32]   -> {json.dumps(cells[-1])}", flush=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = build_receipt(ts, cells, freeze_name, total)
    out = f"{RECEIPTS}/fp32-step-econ-{ts}.json"
    checked_write(out, receipt)
    f = validate_receipt(json.load(open(out, encoding="utf-8")))
    if f:
        raise SystemExit(f"emitted receipt FAILS receipt_check: {f}")
    print(json.dumps(receipt["result"], indent=2))
    print(f"FP32_STEP_ECON_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
