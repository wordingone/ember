# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c04_chunk_tf32_lever.py — CE-chunk + TF32 throughput levers (C-EFF wall-break, no compile).

WHY
===
After 4 compile-lever runs, the design bench's OWN comment (c04_design_bench.py:197) states
torch.compile speedup is only 1.024x on this hardware — so compile is NOT the lever and the
production compile-break is moot. The real, self-consistent no-qat production throughput is
~16400 tok/s (c04-eager + conv-muon_split-20260623T072149Z, effective_days=1.159 — NOT shatter).

The design bench (19874.8) differs from the production eager path (16394) in ONE numerically-
identical way the eager bench never isolated: CE chunk_tokens=1024 (design bench :212) vs
production's default 256 (timeshare_pretrain.run_v0_segment ce_chunk_tokens=256, ts:1173).
chunked_cross_entropy is DETERMINISTIC accumulation over a fixed chunk order (ts:929) — chunk
size changes ONLY kernel-launch / tiling overhead, NEVER the loss. With MTP (3 CE calls/step),
chunk256 does 64*3=192 chunk-iterations vs chunk1024's 16*3=48. If CE is a meaningful step
fraction, chunk1024 is a FREE, numerically-IDENTICAL throughput lever.

Second free lever: TF32. Muon NS5 orthogonalization runs in float32 (per-param _Muon casts to
fp32); TF32 (set_float32_matmul_precision('high')) accelerates float32 matmuls on tensor cores.
The inductor TF32 warning has fired in every run. TF32 changes float32-matmul precision (19-bit
mantissa) -> a quality re-check is required before it can be load-bearing; here it is a THROUGHPUT
probe only (flagged tf32_needs_quality_recheck in the receipt).

This is break-the-wall (the SHATTER recipe used chunk1024; production deviated to chunk256), not
escalate. NO compile, NO qat, NO optimizer change — production builders, eager, real recipe.

SWEEP (one model build, per-cell re-measure):
  c0: chunk256  tf32=off  (production baseline — must reproduce ~16400)
  c1: chunk1024 tf32=off  (CE-chunk lever alone — NUMERICALLY IDENTICAL to c0)
  c2: chunk1024 tf32=on   (CE-chunk + TF32 stacked)
  c3: chunk256  tf32=on   (TF32 alone, isolates its contribution)

FLOOR (self-consistent no-qat keystone; tokens_to_match_ref=45,219,840 from the REAL conv run):
  effective_days(tok_s) = K / tok_s,  K = (2.2e9 * 45219840/60e6) / 86400 = 19190.51
  CLEARS  <=>  tok_s_paced >= 19190.51  (effective_days <= 1.0)
  c1 (chunk1024, tf32 off) clearing the floor = CLEAN SHATTER (numerically identical to production).

Receipt : receipts/c04-chunk-tf32-lever-{ts}.json
Selftest: python c04_chunk_tf32_lever.py --selftest -> CHUNK_TF32_LEVER_SELFTEST_PASS
Dispatch: via train MCP (GPU; one model at a time). Production governor applied (fail-closed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")
sys.path.insert(0, HERE)

from receipt_write import checked_write    # noqa: E402

WARMUP = 5
TIMED  = 20
BATCH  = 16

EFFECTIVE_DAYS_FLOOR = 1.0
# Self-consistent no-qat keystone floor (ceff-shatter-recipe-mixing-correction-20260623.json):
# K = (BUDGET_B * tokens_to_match_ref / BUDGET_TOKENS) / 86400, tokens_to_match_ref from the REAL
# conv-muon_split run (45,219,840). This is recipe-correct as long as the measured recipe's
# convergence == the conv run's (chunk size is numerically identical, so 45.22M transfers exactly).
BUDGET_B           = 2_200_000_000.0
BUDGET_TOKENS      = 60_000_000.0
TOKENS_TO_MATCH    = 45_219_840.0
K_TOK_S_FLOOR      = (BUDGET_B * TOKENS_TO_MATCH / BUDGET_TOKENS) / 86400.0  # 19190.51


def effective_days(tok_s_paced: float) -> float:
    if tok_s_paced <= 0:
        return float("inf")
    return K_TOK_S_FLOOR / tok_s_paced


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_bench() -> dict:
    import torch
    # issue2015 exact-local-import:src/ember/governance/scripts/timeshare_pretrain.py
    import importlib.util as _ember_d9c5c82c124e1dc8_importlib
    import sys as _ember_d9c5c82c124e1dc8_sys
    from pathlib import Path as _ember_d9c5c82c124e1dc8_Path
    _ember_d9c5c82c124e1dc8_path = _ember_d9c5c82c124e1dc8_Path(__file__).resolve().parent.joinpath('timeshare_pretrain.py')
    if not _ember_d9c5c82c124e1dc8_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_aliases = ('_ember_issue2015_d9c5c82c124e1dc8', 'src.ember.governance.scripts.timeshare_pretrain', 'timeshare_pretrain')
    _ember_d9c5c82c124e1dc8_existing = []
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_candidate = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_candidate is not None and all(_ember_d9c5c82c124e1dc8_candidate is not item for item in _ember_d9c5c82c124e1dc8_existing):
            _ember_d9c5c82c124e1dc8_existing.append(_ember_d9c5c82c124e1dc8_candidate)
    if len(_ember_d9c5c82c124e1dc8_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/timeshare_pretrain.py')
    if _ember_d9c5c82c124e1dc8_existing:
        _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_existing[0]
        _ember_d9c5c82c124e1dc8_observed = getattr(_ember_d9c5c82c124e1dc8_module, '__file__', None)
        if _ember_d9c5c82c124e1dc8_observed is None or _ember_d9c5c82c124e1dc8_Path(_ember_d9c5c82c124e1dc8_observed).resolve() != _ember_d9c5c82c124e1dc8_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/timeshare_pretrain.py')
    else:
        _ember_d9c5c82c124e1dc8_spec = _ember_d9c5c82c124e1dc8_importlib.spec_from_file_location('_ember_issue2015_d9c5c82c124e1dc8', _ember_d9c5c82c124e1dc8_path)
        if _ember_d9c5c82c124e1dc8_spec is None or _ember_d9c5c82c124e1dc8_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_importlib.module_from_spec(_ember_d9c5c82c124e1dc8_spec)
        for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
            _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
            if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/timeshare_pretrain.py')
            _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
        try:
            _ember_d9c5c82c124e1dc8_spec.loader.exec_module(_ember_d9c5c82c124e1dc8_module)
        except BaseException:
            for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
                if _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias) is _ember_d9c5c82c124e1dc8_module:
                    _ember_d9c5c82c124e1dc8_sys.modules.pop(_ember_d9c5c82c124e1dc8_alias, None)
            raise
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
    ts = _ember_d9c5c82c124e1dc8_module
    # issue2015 exact-local-import-end:src/ember/governance/scripts/timeshare_pretrain.py

    gov = ts._apply_governor()
    torch.manual_seed(42)

    cfg = ts.load_contract()
    seq         = cfg["model"]["seq"]
    mtp_cfg     = cfg["objective"]["mtp_aux_heads"]
    mtp_weight  = mtp_cfg["weight"]
    mtp_enabled = bool(mtp_cfg["enabled"])
    pace_s      = ts.FP19_PACE_S

    model, vocab, hidden, n_mtp = ts.build_v0_model(cfg, live=True)
    optimizers, base_lrs, routing = ts.build_split_optimizer(model, cfg)
    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=True)
    print(f"[chunk-tf32] routing mode={routing.get('mode')} n_muon={routing.get('n_muon')} "
          f"n_adamw={routing.get('n_adamw')} ce_impl={ce_impl}", flush=True)

    def make_batch():
        x  = torch.randint(1, vocab, (BATCH, seq), device="cuda")
        y0 = torch.randint(1, vocab, (BATCH, seq), device="cuda")
        ym = [torch.randint(1, vocab, (BATCH, seq), device="cuda") for _ in range(n_mtp)]
        return x, y0, ym

    def build_fwd(chunk_tokens):
        def fwd(x, y0, y_mtp):
            h = model.backbone(x)                       # production wrapper (faithful)
            hf = h.reshape(-1, h.shape[-1])
            pce, _ = ce_fn(hf, model.head.weight, y0.reshape(-1), chunk_tokens=chunk_tokens)
            mces = []
            if mtp_enabled:
                for k in range(n_mtp):
                    ce_k, _ = ce_fn(hf, model.mtp_heads[k].weight, y_mtp[k].reshape(-1),
                                    chunk_tokens=chunk_tokens)
                    mces.append(ce_k)
            return ts.mtp_total_loss(pce, mces, mtp_weight)
        return fwd

    def timed_cell(chunk_tokens):
        fwd = build_fwd(chunk_tokens)
        for _ in range(WARMUP):
            loss = fwd(*make_batch())
            loss.backward()
            for opt in optimizers.values():
                opt.step()
            for opt in optimizers.values():
                opt.zero_grad(set_to_none=True)
        torch.cuda.empty_cache(); torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        if free_gib < ts.FP19_MARGIN_GIB:
            return {"status": "SKIPPED-MARGIN", "free_vram_gib": round(free_gib, 3)}
        step_times = []
        t0 = time.perf_counter()
        for _ in range(TIMED):
            t_s = time.perf_counter()
            loss = fwd(*make_batch())
            loss.backward()
            for opt in optimizers.values():
                opt.step()
            for opt in optimizers.values():
                opt.zero_grad(set_to_none=True)
            torch.cuda.synchronize()
            step_times.append(time.perf_counter() - t_s)
            time.sleep(pace_s)
        total_dt = time.perf_counter() - t0
        toks = TIMED * BATCH * seq
        tp = toks / total_dt
        return {"status": "OK", "tok_s_paced": round(tp, 1),
                "tok_s_raw": round(toks / (total_dt - TIMED * pace_s), 1),
                "mean_step_ms": round(sum(step_times) / len(step_times) * 1000, 2),
                "effective_days": round(effective_days(tp), 5),
                "free_vram_gib_post_warmup": round(free_gib, 2)}

    def set_tf32(on: bool):
        torch.backends.cuda.matmul.allow_tf32 = on
        torch.backends.cudnn.allow_tf32 = on
        torch.set_float32_matmul_precision("high" if on else "highest")

    cells = {}
    # c0: chunk256 tf32 off — production baseline
    set_tf32(False)
    cells["c0_chunk256_tf32off"] = timed_cell(256)
    print(f"[chunk-tf32] c0 chunk256 tf32off: {cells['c0_chunk256_tf32off']}", flush=True)
    # c1: chunk1024 tf32 off — CE-chunk lever alone (numerically identical to c0)
    cells["c1_chunk1024_tf32off"] = timed_cell(1024)
    print(f"[chunk-tf32] c1 chunk1024 tf32off: {cells['c1_chunk1024_tf32off']}", flush=True)
    # c2: chunk1024 tf32 on — stacked
    set_tf32(True)
    cells["c2_chunk1024_tf32on"] = timed_cell(1024)
    print(f"[chunk-tf32] c2 chunk1024 tf32on: {cells['c2_chunk1024_tf32on']}", flush=True)
    # c3: chunk256 tf32 on — TF32 alone
    cells["c3_chunk256_tf32on"] = timed_cell(256)
    print(f"[chunk-tf32] c3 chunk256 tf32on: {cells['c3_chunk256_tf32on']}", flush=True)
    set_tf32(False)

    def tps(c):
        v = cells.get(c, {})
        return v.get("tok_s_paced") if v.get("status") == "OK" else None

    # Clean lever = c1 (chunk1024, tf32 OFF — numerically identical to production).
    clean_tps = tps("c1_chunk1024_tf32off")
    clean_clears = bool(clean_tps is not None and clean_tps >= K_TOK_S_FLOOR)
    # Best overall (incl TF32 — needs a quality re-check before it is load-bearing).
    all_tps = [(k, tps(k)) for k in cells if tps(k) is not None]
    best_cell, best_tps = max(all_tps, key=lambda kv: kv[1]) if all_tps else (None, None)
    best_clears = bool(best_tps is not None and best_tps >= K_TOK_S_FLOOR)
    tf32_in_best = best_cell is not None and "tf32on" in best_cell

    if clean_clears:
        verdict = "CHUNK-LEVER-CLEAN-SHATTER"   # numerically identical, no quality re-check
    elif best_clears and tf32_in_best:
        verdict = "CLEARS-WITH-TF32-QUALITY-RECHECK-REQUIRED"
    elif best_clears:
        verdict = "CLEARS-CLEAN"
    else:
        verdict = "LEVERS-INSUFFICIENT-PRICED-RESIDUAL"

    return {
        "status": "OK",
        "governor": gov,
        "recipe": {
            "source": "timeshare_pretrain production builders (build_v0_model/build_split_optimizer/resolve_ce_impl)",
            "optimizer_mode": routing.get("mode"), "n_muon": routing.get("n_muon"),
            "n_adamw": routing.get("n_adamw"), "ce_impl": ce_impl,
            "batch": BATCH, "seq": seq, "n_mtp": n_mtp,
            "compile": "NONE (eager; compile is only 1.024x on this hw per c04_design_bench:197)",
            "qat": "NONE (no-qat production graph)",
            "levers_tested": "CE chunk_tokens {256,1024} x TF32 {off,on}",
        },
        "cells": cells,
        "floor": {
            "K_tok_s_floor": round(K_TOK_S_FLOOR, 2), "effective_days_floor": EFFECTIVE_DAYS_FLOOR,
            "tokens_to_match_ref": TOKENS_TO_MATCH, "budget_b": BUDGET_B, "budget_tokens": BUDGET_TOKENS,
            "provenance": "ceff-shatter-recipe-mixing-correction-20260623.json (self-consistent no-qat keystone)",
        },
        "gate": {
            "baseline_chunk256_tf32off": tps("c0_chunk256_tf32off"),
            "clean_lever_chunk1024_tf32off": clean_tps,
            "clean_lever_clears_floor": clean_clears,
            "best_cell": best_cell, "best_tok_s": best_tps, "best_clears_floor": best_clears,
            "tf32_in_best": tf32_in_best,
            "tf32_needs_quality_recheck": True,
            "tok_s_floor": round(K_TOK_S_FLOOR, 2),
            "verdict": verdict,
        },
    }


def run_and_emit() -> Path:
    result = _run_bench()
    receipt = {"ticket": "C04-CHUNK-TF32-LEVER", "ts": _ts(),
               "scope": "C-EFF wall-break: CE-chunk + TF32 throughput levers on the no-qat production eager path",
               "harness_sha": _harness_sha(), **result}
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"c04-chunk-tf32-lever-{receipt['ts']}.json")
    checked_write(path, receipt)
    g = result["gate"]
    print(f"[chunk-tf32] receipt: {path}", flush=True)
    print(f"[chunk-tf32] VERDICT: {g['verdict']} | baseline={g['baseline_chunk256_tf32off']} "
          f"clean(chunk1024)={g['clean_lever_chunk1024_tf32off']} clears={g['clean_lever_clears_floor']} "
          f"| best={g['best_cell']}={g['best_tok_s']} clears={g['best_clears_floor']} (floor>={g['tok_s_floor']})", flush=True)
    print(f"CHUNK_TF32_LEVER_DONE verdict={g['verdict']} clean_clears={g['clean_lever_clears_floor']}", flush=True)
    return Path(path)


def selftest() -> None:
    print("[c04_chunk_tf32_lever] selftest: floor math + schema (no GPU)", flush=True)
    assert abs(K_TOK_S_FLOOR - 19190.51) < 0.5, K_TOK_S_FLOOR
    assert abs(effective_days(K_TOK_S_FLOOR) - 1.0) < 1e-9
    assert effective_days(19874.8) < 1.0 and effective_days(16394.0) > 1.0
    print(f"  floor: tok_s>={K_TOK_S_FLOOR:.2f} <=> effective_days<=1.0  PASS")
    # verdict logic
    assert effective_days(20000.0) < 1.0  # clears
    assert effective_days(17000.0) > 1.0  # short
    print("  verdict thresholds PASS")
    print("CHUNK_TF32_LEVER_SELFTEST_PASS")


def main() -> None:
    ap = argparse.ArgumentParser(description="CE-chunk + TF32 throughput lever probe for C-EFF")
    ap.add_argument("--selftest", action="store_true")
    args, _ = ap.parse_known_args()
    if args.selftest:
        selftest()
    else:
        run_and_emit()


if __name__ == "__main__":
    main()
