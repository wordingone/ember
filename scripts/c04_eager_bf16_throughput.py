"""c04_eager_bf16_throughput.py — Production-recipe (BF16-eager) throughput gate.

KEYSTONE-TRANSFER GATE
======================
The SHATTER verdict's tok_s_paced=19874.8 (muon_split) was measured by
c04_batched_ns5_bench.py WITH fp19 fake-quant (qat) + torch.compile(fwd) AND with
fp45's shape-grouped _MuonBatched optimizer + chunk_tokens=1024. PRODUCTION —
run_v0_segment / cbase_v0_segment_live, the path the smoke ee2eb165 actually ran —
is BF16-EAGER with the PER-PARAM SEQUENTIAL _Muon (build_split_optimizer), liger/cut
CE at ce_chunk_tokens=256, no fake-quant, no torch.compile.

Banking the keystone off the faster qat+compile+batched-muon+chunk1024 number is a
silent-recipe-mismatch (a does-NOT-count token). This bench measures the EXACT
production per-step recipe by REUSING the production builders themselves — zero
reconstruction drift — on c04's clean windowed harness (warmup-excluded, no disk I/O,
paced), and gates effective_days <= 1.0 on the MEASURED production throughput.

FIDELITY — every component comes from timeshare_pretrain (the production trainer),
NOT a hand-rebuild:
  governor : ts._apply_governor()                         # production VRAM frac + margin assert (fail-closed)
  cfg      : ts.load_contract()                           # configs/v0-pretrain-config.json
  model    : ts.build_v0_model(cfg, live=True)            # _V0Real: .backbone(ids)/.head/.mtp_heads, bf16, grad_ckpt
  opt      : ts.build_split_optimizer(model, cfg)         # per-param _Muon split + AdamW (n_muon/n_adamw routed by NAME)
  ce       : ts.resolve_ce_impl(prefer_liger=True)        # liger_flce if importable else cut_ce_chunked (smoke: cut_ce)
  step     : model.backbone(x) -> ce_fn(...,chunk_tokens=256) primary + per-MTP -> mtp_total_loss -> apply_wsd -> backward -> opt.step
  shape    : batch=16 (production --live override), seq=cfg.model.seq, ce_chunk=256, paced FP19_PACE_S
The receipt records routing.n_muon / routing.n_adamw / ce_impl so a reviewer can
confirm they match the smoke receipt (n_muon=140, n_adamw=44, cut_ce_chunked).

CELL: eager-bf16 only (THE GATE). The compile lever is a CONTINGENCY — run a separate
focused compile-probe ONLY if eager is short. Measure the real thing first.

FLOOR (frozen SHATTER anchor — shatter-verdict-canonical-20260623.json):
  effective_days = (BUDGET_B * tokens_to_match_ref/BUDGET_TOKENS)/tok_s_paced/86400.
  The numerator (convergence work to reach ref_loss) is throughput-INDEPENDENT and
  recipe-independent up to the optimizer's UPDATE MATH (per-param _Muon and batched
  _MuonBatched compute numerically-equivalent NS5 updates, fp45 ns5_equiv<2e-7, so
  tokens_to_match_ref is identical; only wall-time differs). Hence:
    effective_days(tok_s) = K / tok_s,  K = effective_days_anchor * tok_s_anchor
                                           = 0.96557 * 19874.8 = 19190.5
  (Identity: K / tok_s_anchor = 0.96557 = anchor. OK.)
  GATE: effective_days_eager <= 1.0  <=>  tok_s_eager_paced >= 19190.5

Receipt : receipts/c04-eager-bf16-throughput-{ts}.json
Selftest: python c04_eager_bf16_throughput.py --selftest  -> EAGER_BF16_THROUGHPUT_SELFTEST_PASS
Dispatch: via train MCP (GPU; one model at a time). Production governor applied
          (ts._apply_governor: VRAM frac + margin assert); SystemExit on margin
          violation — never fix-forward.
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

from receipt_write import checked_write    # noqa: E402  (light; no torch)
# NOTE: timeshare_pretrain (pulls torch) is imported lazily inside _run_bench so that
# --selftest stays hermetic (pure math + schema, no torch).

# ── Harness window (matches c04/fp45 so tok_s_paced is comparable to the anchor) ──
WARMUP = 5
TIMED  = 20

BATCH              = 16     # production --live override (timeshare_pretrain.py:2544)
CE_CHUNK_TOKENS    = 256    # production run_v0_segment default (timeshare_pretrain.py:1173)
TOTAL_STEPS_NOMINAL = 449651  # WSD denominator; affects only the lr scalar, not compute

# ── Frozen SHATTER anchor (provenance: shatter-verdict-canonical-20260623.json) ──
EFFECTIVE_DAYS_ANCHOR = 0.96557     # muon_split frozen verdict
TOK_S_ANCHOR          = 19874.8     # muon_split tok_s_paced (qat+compile+batched recipe)
EFFECTIVE_DAYS_FLOOR  = 1.0         # <= 1 governed GPU-day on the 2.2e9 ceiling
BUDGET_B              = 2_200_000_000.0   # documentation only (folded into K)

K_TOK_S_FLOOR = EFFECTIVE_DAYS_ANCHOR * TOK_S_ANCHOR  # 19190.5 ; effective_days==1.0 boundary


def effective_days(tok_s_paced: float) -> float:
    """effective_days at a measured paced throughput, per the frozen anchor."""
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


# ── Bench ───────────────────────────────────────────────────────────────────────

def _run_bench() -> dict:
    import torch
    import timeshare_pretrain as ts  # lazy: pulls torch; only on the GPU path

    # Production governor (VRAM fraction + margin assert; raises SystemExit on
    # violation — fail-closed, never fix-forward).
    gov = ts._apply_governor()
    torch.manual_seed(42)

    cfg = ts.load_contract()
    seq         = cfg["model"]["seq"]
    mtp_cfg     = cfg["objective"]["mtp_aux_heads"]
    mtp_weight  = mtp_cfg["weight"]
    mtp_enabled = bool(mtp_cfg["enabled"])
    pace_s      = ts.FP19_PACE_S

    print(f"[eager-bf16] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[eager-bf16] torch:  {torch.__version__}", flush=True)
    print(f"[eager-bf16] recipe: production builders (build_v0_model/build_split_optimizer/"
          f"resolve_ce_impl), batch={BATCH} seq={seq} ce_chunk={CE_CHUNK_TOKENS} pace_s={pace_s}", flush=True)

    # Production model + optimizer + CE (the real builders — zero reconstruction drift).
    # MODE FIDELITY: run_v0_segment calls build_v0_model then NEVER touches .train()/.eval()
    # (timeshare_pretrain.py:1211-1212 + the 1264-1302 loop). So we do the same — NO .train()
    # call — making the bench's mode identical to production BY CONSTRUCTION. nn.Module defaults
    # to training=True (PyTorch contract; bare LlamaModel(conf), not from_pretrained), so grad_ckpt
    # is ACTIVE — matching the 19874.8 anchor (fp45._bench_seed calls backbone.train()).
    # Fail closed if the mode is ever NOT training: a bypassed grad_ckpt would silently OVER-state
    # throughput (recompute skipped), which is the dangerous (false-PASS) direction.
    model, vocab, hidden, n_mtp = ts.build_v0_model(cfg, live=True)
    model_training = bool(model.training)
    bb_training = bool(getattr(model, "backbone_model", model).training)
    if not (model_training and bb_training):
        raise SystemExit(
            f"EAGER_BF16_MODE_FAIL: model.training={model_training} "
            f"backbone.training={bb_training} — production build_v0_model yields training=True "
            f"(grad_ckpt active); refusing to measure a grad_ckpt-bypassed regime as production.")
    optimizers, base_lrs, routing = ts.build_split_optimizer(model, cfg)
    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=True)
    # ce_chunk_tokens=256 controls compute granularity ONLY on the cut_ce_chunked path; on
    # liger_flce the kernel self-tiles and chunk_tokens is a no-op (timeshare_pretrain.py:962-965).
    # The smoke ee2eb165 resolved cut_ce_chunked, so 256 was load-bearing there. Recorded per-run.
    ce_chunk_effective = CE_CHUNK_TOKENS if ce_impl != "liger_flce" else "n/a (liger kernel-tiled)"
    print(f"[eager-bf16] optimizer routing: mode={routing.get('mode')} "
          f"n_muon={routing.get('n_muon')} n_adamw={routing.get('n_adamw')} | ce_impl={ce_impl}", flush=True)

    def make_batch():
        # Throughput is data-value independent; match production shapes/dtypes.
        # ids in [1, vocab) avoid ignore_index=-100 in the CE valid-count path.
        x  = torch.randint(1, vocab, (BATCH, seq), device="cuda")
        y0 = torch.randint(1, vocab, (BATCH, seq), device="cuda")
        ym = [torch.randint(1, vocab, (BATCH, seq), device="cuda") for _ in range(n_mtp)]
        return x, y0, ym

    def step(global_step):
        x, y0, y_mtp = make_batch()
        hidden_out = model.backbone(x)
        h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
        primary_ce, _ = ce_fn(h_flat, model.head.weight, y0.reshape(-1), chunk_tokens=CE_CHUNK_TOKENS)
        mtp_ces = []
        if mtp_enabled:
            for k, head in enumerate(model.mtp_heads):
                ce_k, _ = ce_fn(h_flat, head.weight, y_mtp[k].reshape(-1), chunk_tokens=CE_CHUNK_TOKENS)
                mtp_ces.append(ce_k)
        loss = ts.mtp_total_loss(primary_ce, mtp_ces, mtp_weight)
        ts.apply_wsd(optimizers, base_lrs, global_step, TOTAL_STEPS_NOMINAL, cfg["schedule"])
        loss.backward()
        for opt in optimizers.values():
            opt.step()
        for opt in optimizers.values():
            opt.zero_grad(set_to_none=True)

    # Warmup (excluded from timing).
    print(f"[eager-bf16] warmup {WARMUP} ...", flush=True)
    for i in range(WARMUP):
        step(i)

    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib  = free_b  / (1 << 30)
    total_gib = total_b / (1 << 30)
    margin_floor = ts.FP19_MARGIN_GIB
    print(f"[eager-bf16] VRAM post-warmup {free_gib:.2f}/{total_gib:.2f} GiB "
          f"(need {margin_floor} GiB margin)", flush=True)
    if free_gib < margin_floor:
        return {"status": "SKIPPED-MARGIN", "free_vram_gib": round(free_gib, 3),
                "total_vram_gib": round(total_gib, 2), "governor": gov,
                "routing": routing, "ce_impl": ce_impl}

    # Timed window (paced; warmup-excluded; cuda.synchronize per step).
    print(f"[eager-bf16] bench {TIMED} steps ...", flush=True)
    step_times = []
    t0 = time.perf_counter()
    for i in range(TIMED):
        t_s = time.perf_counter()
        step(WARMUP + i)
        torch.cuda.synchronize()
        t_step = time.perf_counter() - t_s
        time.sleep(pace_s)
        step_times.append(t_step)
        if (i + 1) % 5 == 0:
            print(f"[eager-bf16]   step {i+1}/{TIMED} step={t_step*1000:.1f}ms", flush=True)

    total_dt = time.perf_counter() - t0
    toks = TIMED * BATCH * seq
    tok_s_paced = toks / total_dt
    tok_s_raw   = toks / (total_dt - TIMED * pace_s)
    mean_step   = sum(step_times) / len(step_times)

    eff_days = effective_days(tok_s_paced)
    gate_pass = eff_days <= EFFECTIVE_DAYS_FLOOR

    return {
        "status": "OK",
        "governor": gov,
        "recipe": {
            "source": "timeshare_pretrain production builders",
            "optimizer_mode": routing.get("mode"),
            "n_muon": routing.get("n_muon"),
            "n_adamw": routing.get("n_adamw"),
            "ce_impl": ce_impl,
            "ce_chunk_tokens": CE_CHUNK_TOKENS,
            "ce_chunk_effective": ce_chunk_effective,
            "model_training_mode": model_training,
            "backbone_training_mode": bb_training,
            "grad_ckpt_active": bool(model_training and bb_training),
            "batch": BATCH, "seq": seq, "n_mtp": n_mtp,
            "mtp_enabled": mtp_enabled, "mtp_weight": mtp_weight,
            "vocab": vocab, "hidden": hidden,
            "pace_s": pace_s,
        },
        "measurement": {
            "tok_s_paced": round(tok_s_paced, 1),
            "tok_s_raw":   round(tok_s_raw, 1),
            "mean_step_ms": round(mean_step * 1000, 2),
            "warmup": WARMUP, "timed": TIMED,
            "free_vram_gib_post_warmup": round(free_gib, 2),
        },
        "anchor": {
            "effective_days_anchor": EFFECTIVE_DAYS_ANCHOR,
            "tok_s_anchor": TOK_S_ANCHOR,
            "anchor_recipe": "qat fake-quant + torch.compile(fwd) + fp45 batched-muon + chunk1024",
            "K_tok_s_floor": round(K_TOK_S_FLOOR, 2),
            "provenance": "shatter-verdict-canonical-20260623.json",
        },
        "gate": {
            "recipe": "BF16-eager production (per-param _Muon, cut/liger CE chunk=256, no fake-quant, no torch.compile)",
            "tok_s_eager_paced": round(tok_s_paced, 1),
            "tok_s_floor": round(K_TOK_S_FLOOR, 2),
            "effective_days_eager": round(eff_days, 5),
            "effective_days_floor": EFFECTIVE_DAYS_FLOOR,
            "gate_pass": gate_pass,
            "verdict": "PRODUCTION-SHATTER-HOLDS" if gate_pass else "EAGER-SHORT-LEVER-NEEDED",
        },
    }


# ── Receipt ───────────────────────────────────────────────────────────────────

def run_and_emit() -> Path:
    result = _run_bench()
    receipt = {
        "ticket": "C04-EAGER-BF16-THROUGHPUT",
        "ts": _ts(),
        "scope": "keystone-transfer gate: measured production BF16-eager tok_s -> effective_days",
        "harness": {"warmup": WARMUP, "timed": TIMED,
                    "note": "production builders reused; warmup-excluded paced window; no disk I/O"},
        "harness_sha": _harness_sha(),
        **result,
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"c04-eager-bf16-throughput-{receipt['ts']}.json")
    checked_write(path, receipt)
    print(f"[eager-bf16] receipt: {path}", flush=True)
    if result.get("status") == "OK":
        g = result["gate"]
        print(f"[eager-bf16] VERDICT: {g['verdict']} | "
              f"tok_s_eager={g['tok_s_eager_paced']} (floor>={g['tok_s_floor']}) | "
              f"effective_days={g['effective_days_eager']} (<= {g['effective_days_floor']}) | "
              f"gate_pass={g['gate_pass']}", flush=True)
        print(f"EAGER_BF16_THROUGHPUT_DONE verdict={g['verdict']} gate_pass={g['gate_pass']}", flush=True)
    else:
        print(f"[eager-bf16] status={result.get('status')} — no verdict", flush=True)
        print(f"EAGER_BF16_THROUGHPUT_DONE status={result.get('status')}", flush=True)
    return Path(path)


# ── Schema verifier + selftest (CPU, no GPU) ────────────────────────────────────

def _verify_receipt_schema(r: dict) -> None:
    assert r["ticket"] == "C04-EAGER-BF16-THROUGHPUT"
    g = r["gate"]
    for key in ("tok_s_eager_paced", "tok_s_floor", "effective_days_eager",
                "effective_days_floor", "gate_pass", "verdict"):
        assert key in g, f"gate missing '{key}'"
    rec = r["recipe"]
    for key in ("optimizer_mode", "n_muon", "n_adamw", "ce_impl", "ce_chunk_tokens"):
        assert key in rec, f"recipe missing '{key}'"


def selftest() -> None:
    print("[c04_eager_bf16_throughput] selftest: math + schema (no GPU)", flush=True)

    # 1. Anchor identity: K / tok_s_anchor == effective_days_anchor
    rt = effective_days(TOK_S_ANCHOR)
    assert abs(rt - EFFECTIVE_DAYS_ANCHOR) < 1e-6, f"anchor identity broken: {rt} != {EFFECTIVE_DAYS_ANCHOR}"
    print(f"  anchor identity: effective_days({TOK_S_ANCHOR}) = {rt:.5f} == {EFFECTIVE_DAYS_ANCHOR}  PASS")

    # 2. Floor boundary: tok_s == K_TOK_S_FLOOR -> effective_days == 1.0 exactly
    assert abs(effective_days(K_TOK_S_FLOOR) - 1.0) < 1e-9, "floor boundary != 1.0"
    assert effective_days(K_TOK_S_FLOOR + 1000.0) < 1.0
    assert effective_days(K_TOK_S_FLOOR - 1000.0) > 1.0
    print(f"  floor boundary: tok_s>={K_TOK_S_FLOOR:.1f} <=> effective_days<=1.0  PASS")

    # 3. Synthetic PASS receipt (eager fits floor)
    syn_pass = {
        "ticket": "C04-EAGER-BF16-THROUGHPUT",
        "recipe": {"optimizer_mode": "muon_split", "n_muon": 140, "n_adamw": 44,
                   "ce_impl": "cut_ce_chunked", "ce_chunk_tokens": 256},
        "gate": {"tok_s_eager_paced": 20500.0, "tok_s_floor": round(K_TOK_S_FLOOR, 2),
                 "effective_days_eager": round(effective_days(20500.0), 5),
                 "effective_days_floor": 1.0, "gate_pass": True,
                 "verdict": "PRODUCTION-SHATTER-HOLDS"},
    }
    _verify_receipt_schema(syn_pass)
    assert syn_pass["gate"]["effective_days_eager"] < 1.0 and syn_pass["gate"]["gate_pass"]
    print("  schema verify (PASS synthetic, eager>=floor): PASS")

    # 4. Synthetic SHORT receipt (eager below floor -> lever contingency)
    syn_short = {
        "ticket": "C04-EAGER-BF16-THROUGHPUT",
        "recipe": {"optimizer_mode": "muon_split", "n_muon": 140, "n_adamw": 44,
                   "ce_impl": "cut_ce_chunked", "ce_chunk_tokens": 256},
        "gate": {"tok_s_eager_paced": 12000.0, "tok_s_floor": round(K_TOK_S_FLOOR, 2),
                 "effective_days_eager": round(effective_days(12000.0), 5),
                 "effective_days_floor": 1.0, "gate_pass": False,
                 "verdict": "EAGER-SHORT-LEVER-NEEDED"},
    }
    _verify_receipt_schema(syn_short)
    assert syn_short["gate"]["effective_days_eager"] > 1.0 and not syn_short["gate"]["gate_pass"]
    print("  schema verify (SHORT synthetic, eager<floor): PASS")

    # 5. Round-trip via file
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "c04-eager-bf16-throughput-test.json")
        with open(p, "w") as f:
            json.dump(syn_pass, f, indent=2)
        _verify_receipt_schema(json.loads(open(p).read()))
    print("  round-trip file read: PASS")

    print("EAGER_BF16_THROUGHPUT_SELFTEST_PASS")


def main() -> None:
    ap = argparse.ArgumentParser(description="Production BF16-eager throughput keystone-transfer gate")
    ap.add_argument("--selftest", action="store_true")
    args, _ = ap.parse_known_args()
    if args.selftest:
        selftest()
    else:
        run_and_emit()


if __name__ == "__main__":
    main()
