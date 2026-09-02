# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c04_bf16ns5_qat_throughput.py — Measure the REAL QAT tax in the bf16-NS5 context.

WHY THIS PROBE EXISTS
=====================
Every prior bf16-NS5 throughput measurement (C-EFF regime, ~19500-20000 tok/s) was
measured WITHOUT fake-quant (no-qat).  The only QAT number on record (18737.7 tok/s)
came from fp19_bench on fp32-NS5 in a different harness — NOT transferable to the
bf16-NS5 context.  Before QAT can be priced against the bf16-NS5 lever, the tax must
be measured apples-to-apples in the same bf16-NS5 harness.

PROBE DESIGN
============
Two cells, one model build, one receipt:

  Cell A  "bf16ns5_noqat"
    bf16-NS5 patch ON (ts._zeropower_via_newtonschulz5 = _zeropower_bf16 at module
    level).  No fake-quant.  EXPECT ~19500-20000 tok/s — reproduces the C-EFF
    bf16-NS5 regime.  If this cell is short, the harness is wrong — flagged in receipt.

  Cell B  "bf16ns5_qat"
    bf16-NS5 patch ON + fp19_bench._apply_fake_quant("qat") applied before each
    forward (int8-grid STE on linear weights; restored after backward, per fp19
    semantics — gradients flow to full-precision weights).

Outputs per cell:
  tok_s_paced, tok_s_raw, mean_step_ms, free_vram_gib_post_warmup, eff_days

Derived:
  qat_tax_ratio = B.tok_s_paced / A.tok_s_paced          (measured in THIS harness)
  eff_days per cell = K_floor / tok_s_paced

K_floor = 19190.52  (anchor: effective_days_anchor * tok_s_anchor, same as c04 family)
tokens_to_match_ref = 45.22M (from the REAL conv-muon_split run).

GOVERNED LAUNCH
===============
Same as c04_chunk_tf32_lever.py:
  VRAM fraction <= 0.80  (set_per_process_memory_fraction)
  margin assert >= 1.5 GiB post-warmup  (fail-closed, no fix-forward)
  inter-step pace sleep >= 0.05s  (duty-cycle governor)

Receipt: receipts/c04-bf16ns5-qat-probe-<UTCstamp>.json

Selftest (CPU, no GPU):
  python c04_bf16ns5_qat_throughput.py --selftest
  -> BF16NS5_QAT_THROUGHPUT_SELFTEST_PASS

Dispatch: via train MCP (GPU; one model at a time).
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

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[4].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py    # noqa: E402  (light; no torch)

# ── Harness window (matches c04 family for comparability) ───────────────────
WARMUP = 10    # probe spec: ~10 steps
TIMED  = 40    # probe spec: ~40 steps

BATCH           = 16
SEQ             = 1024
CE_CHUNK_TOKENS = 1024   # C-EFF lever (numerically identical to 256 for loss)
TOTAL_STEPS_NOMINAL = 449651   # WSD denominator — affects lr scalar only

# ── Frozen anchor (same provenance as c04 family) ───────────────────────────
# K = effective_days_anchor * tok_s_anchor  (c04_eager_bf16_throughput.py)
EFFECTIVE_DAYS_ANCHOR = 0.96557
TOK_S_ANCHOR          = 19874.8
K_FLOOR               = EFFECTIVE_DAYS_ANCHOR * TOK_S_ANCHOR   # 19190.52

# bf16-NS5 noqat regime expectation (sanity check on Cell A)
BF16NS5_NOQAT_EXPECT_MIN = 19000.0   # flag if Cell A is below this

EFFECTIVE_DAYS_FLOOR = 1.0


def effective_days(tok_s_paced: float) -> float:
    if tok_s_paced <= 0:
        return float("inf")
    return K_FLOOR / tok_s_paced


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── BF16 Newton-Schulz5 (from conv_c03_muon_split_bf16ns5.py) ───────────────

def _zeropower_bf16(G, steps: int = 5, eps: float = 1e-7):
    """BF16 Newton-Schulz5 orthogonalization (tensor-core path).

    Identical to timeshare_pretrain._zeropower_via_newtonschulz5 except the
    internal matmuls run in bfloat16 instead of float32.
    External contract: same shape returned; dtype = G.dtype."""
    import torch
    assert G.ndim == 2, "Newton-Schulz operates on 2D matrices only"
    a, b, c = 3.4445, -4.7750, 2.0315
    orig_dtype = G.dtype
    X = G.to(torch.bfloat16)          # BF16 cast — tensor-core path
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T
        transposed = True
    X = X / (X.norm() + eps)
    for _ in range(steps):
        A = X @ X.T
        B_mat = b * A + c * (A @ A)
        X = a * X + B_mat @ X
    if transposed:
        X = X.T
    return X.to(orig_dtype)


# ── QAT fake-quant (from fp19_bench.py) ─────────────────────────────────────

def _apply_fake_quant(model, mode: str):
    """STE-style weight transform applied in-place pre-forward each step.
    Returns a restore list.  int8-grid for 'qat'.

    Matches fp19_bench._apply_fake_quant exactly so the overhead is
    the same proxy measured there."""
    import torch
    saved = []
    for m in model.modules():
        if isinstance(m, torch.nn.Linear):
            w = m.weight.data
            saved.append((m, w.clone()))
            if mode == "qat":
                s = w.abs().amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.0
                m.weight.data = (w / s).round().clamp(-127, 127) * s
    return saved


def _restore(saved):
    for m, w in saved:
        m.weight.data = w


# ── Bench ────────────────────────────────────────────────────────────────────

def _run_bench() -> dict:
    import torch
    import timeshare_pretrain as ts

    # ── Governed launch (fail-closed; never fix-forward) ────────────────────
    gov = ts._apply_governor()

    # ── Patch bf16-NS5 at module level BEFORE building the optimizer ─────────
    # This ensures every Muon.step() in build_split_optimizer's per-param
    # _Muon instances calls the BF16 variant.  We patch the module-level
    # function so all Muon instances that call ts._zeropower_via_newtonschulz5
    # see the patch.
    _orig_zeropower = ts._zeropower_via_newtonschulz5
    ts._zeropower_via_newtonschulz5 = _zeropower_bf16

    # Verify the patch bound correctly before doing any compute.
    assert ts._zeropower_via_newtonschulz5 is _zeropower_bf16, \
        "BF16NS5_PATCH_FAILED: ts._zeropower_via_newtonschulz5 is not _zeropower_bf16"

    torch.manual_seed(42)

    cfg = ts.load_contract()
    seq         = cfg["model"]["seq"]
    mtp_cfg     = cfg["objective"]["mtp_aux_heads"]
    mtp_weight  = mtp_cfg["weight"]
    mtp_enabled = bool(mtp_cfg["enabled"])
    pace_s      = ts.FP19_PACE_S

    print(f"[bf16ns5-qat] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[bf16ns5-qat] torch:  {torch.__version__}", flush=True)
    print(f"[bf16ns5-qat] bf16-NS5 patch: ts._zeropower_via_newtonschulz5 = _zeropower_bf16", flush=True)
    print(f"[bf16ns5-qat] batch={BATCH} seq={seq} ce_chunk={CE_CHUNK_TOKENS} "
          f"warmup={WARMUP} timed={TIMED} pace_s={pace_s}", flush=True)

    model, vocab, hidden, n_mtp = ts.build_v0_model(cfg, live=True)
    optimizers, base_lrs, routing = ts.build_split_optimizer(model, cfg)
    ce_impl, ce_fn = ts.resolve_ce_impl(prefer_liger=True)
    print(f"[bf16ns5-qat] routing mode={routing.get('mode')} "
          f"n_muon={routing.get('n_muon')} n_adamw={routing.get('n_adamw')} "
          f"ce_impl={ce_impl}", flush=True)

    def make_batch():
        x  = torch.randint(1, vocab, (BATCH, seq), device="cuda")
        y0 = torch.randint(1, vocab, (BATCH, seq), device="cuda")
        ym = [torch.randint(1, vocab, (BATCH, seq), device="cuda") for _ in range(n_mtp)]
        return x, y0, ym

    def fwd_bwd(apply_qat: bool, global_step: int):
        if apply_qat:
            saved = _apply_fake_quant(model, "qat")
        x, y0, y_mtp = make_batch()
        hidden_out = model.backbone(x)
        h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
        primary_ce, _ = ce_fn(h_flat, model.head.weight, y0.reshape(-1),
                              chunk_tokens=CE_CHUNK_TOKENS)
        mtp_ces = []
        if mtp_enabled:
            for k, head in enumerate(model.mtp_heads):
                ce_k, _ = ce_fn(h_flat, head.weight, y_mtp[k].reshape(-1),
                                chunk_tokens=CE_CHUNK_TOKENS)
                mtp_ces.append(ce_k)
        loss = ts.mtp_total_loss(primary_ce, mtp_ces, mtp_weight)
        ts.apply_wsd(optimizers, base_lrs, global_step, TOTAL_STEPS_NOMINAL, cfg["schedule"])
        loss.backward()
        if apply_qat:
            # Restore AFTER backward — gradients flow to full-precision weights (STE).
            _restore(saved)
        for opt in optimizers.values():
            opt.step()
        for opt in optimizers.values():
            opt.zero_grad(set_to_none=True)

    def run_cell(cell_name: str, apply_qat: bool, step_offset: int) -> dict:
        """Run warmup + timed window for one cell.  Returns measurement dict."""
        print(f"[bf16ns5-qat] [{cell_name}] warmup {WARMUP} steps ...", flush=True)
        for i in range(WARMUP):
            fwd_bwd(apply_qat, step_offset + i)

        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        free_b, total_b = torch.cuda.mem_get_info()
        free_gib  = free_b  / (1 << 30)
        total_gib = total_b / (1 << 30)
        margin_floor = ts.FP19_MARGIN_GIB
        print(f"[bf16ns5-qat] [{cell_name}] VRAM post-warmup {free_gib:.2f}/{total_gib:.2f} GiB "
              f"(need {margin_floor} GiB margin)", flush=True)
        if free_gib < margin_floor:
            return {
                "status": "SKIPPED-MARGIN",
                "free_vram_gib": round(free_gib, 3),
                "total_vram_gib": round(total_gib, 2),
            }

        print(f"[bf16ns5-qat] [{cell_name}] bench {TIMED} steps ...", flush=True)
        step_times = []
        t0 = time.perf_counter()
        for i in range(TIMED):
            t_s = time.perf_counter()
            fwd_bwd(apply_qat, step_offset + WARMUP + i)
            torch.cuda.synchronize()
            t_step = time.perf_counter() - t_s
            time.sleep(pace_s)
            step_times.append(t_step)
            if (i + 1) % 10 == 0:
                print(f"[bf16ns5-qat] [{cell_name}]   step {i+1}/{TIMED} "
                      f"step={t_step*1000:.1f}ms", flush=True)

        total_dt   = time.perf_counter() - t0
        toks       = TIMED * BATCH * seq
        tok_s_paced = toks / total_dt
        tok_s_raw   = toks / (total_dt - TIMED * pace_s)
        mean_step   = sum(step_times) / len(step_times)
        eff_d       = effective_days(tok_s_paced)

        print(f"[bf16ns5-qat] [{cell_name}] tok_s_paced={tok_s_paced:.1f} "
              f"tok_s_raw={tok_s_raw:.1f} mean_step={mean_step*1000:.2f}ms "
              f"eff_days={eff_d:.5f}", flush=True)

        return {
            "status": "OK",
            "tok_s_paced": round(tok_s_paced, 1),
            "tok_s_raw":   round(tok_s_raw, 1),
            "mean_step_ms": round(mean_step * 1000, 2),
            "eff_days":     round(eff_d, 5),
            "free_vram_gib_post_warmup": round(free_gib, 2),
        }

    # ── Cell A: bf16-NS5, no QAT ─────────────────────────────────────────────
    print("[bf16ns5-qat] === Cell A: bf16ns5_noqat ===", flush=True)
    cell_a = run_cell("bf16ns5_noqat", apply_qat=False, step_offset=0)

    # Sanity check: Cell A must reproduce the bf16-NS5 regime.
    cell_a_flag = None
    if cell_a.get("status") == "OK":
        if cell_a["tok_s_paced"] < BF16NS5_NOQAT_EXPECT_MIN:
            cell_a_flag = (
                f"HARNESS_WARNING: Cell A tok_s_paced={cell_a['tok_s_paced']} < "
                f"expected {BF16NS5_NOQAT_EXPECT_MIN} — bf16-NS5 regime not reproduced; "
                f"QAT tax measurement may not be meaningful"
            )
            print(f"[bf16ns5-qat] {cell_a_flag}", flush=True)

    # ── Cell B: bf16-NS5 + QAT ───────────────────────────────────────────────
    # Step offset past Cell A's warmup+timed window so WSD lr schedule continues.
    step_offset_b = WARMUP + TIMED
    print("[bf16ns5-qat] === Cell B: bf16ns5_qat ===", flush=True)
    cell_b = run_cell("bf16ns5_qat", apply_qat=True, step_offset=step_offset_b)

    # ── Compute QAT tax ──────────────────────────────────────────────────────
    qat_tax_ratio = None
    qat_tax_pct   = None
    if cell_a.get("status") == "OK" and cell_b.get("status") == "OK":
        qat_tax_ratio = round(cell_b["tok_s_paced"] / cell_a["tok_s_paced"], 5)
        qat_tax_pct   = round((1.0 - qat_tax_ratio) * 100.0, 2)
        print(f"[bf16ns5-qat] QAT tax: ratio={qat_tax_ratio} ({qat_tax_pct:.2f}% overhead) "
              f"A={cell_a['tok_s_paced']} -> B={cell_b['tok_s_paced']}", flush=True)

    return {
        "status": "OK",
        "governor": gov,
        "recipe": {
            "source": "timeshare_pretrain production builders (build_v0_model/build_split_optimizer/resolve_ce_impl)",
            "bf16ns5_patch": "ts._zeropower_via_newtonschulz5 = _zeropower_bf16 (BF16 tensor-core NS5)",
            "optimizer_mode": routing.get("mode"),
            "n_muon": routing.get("n_muon"),
            "n_adamw": routing.get("n_adamw"),
            "ce_impl": ce_impl,
            "ce_chunk_tokens": CE_CHUNK_TOKENS,
            "qat_mode": "int8-grid STE (fp19_bench._apply_fake_quant semantics)",
            "batch": BATCH, "seq": seq, "n_mtp": n_mtp,
            "mtp_enabled": mtp_enabled, "mtp_weight": mtp_weight,
            "vocab": vocab, "hidden": hidden,
            "pace_s": pace_s,
            "warmup_steps": WARMUP,
            "timed_steps": TIMED,
        },
        "cells": {
            "bf16ns5_noqat": cell_a,
            "bf16ns5_qat":   cell_b,
        },
        "analysis": {
            "qat_tax_ratio":  qat_tax_ratio,
            "qat_tax_pct_overhead": qat_tax_pct,
            "interpretation": (
                "qat_tax_ratio = cell_B.tok_s_paced / cell_A.tok_s_paced; "
                "< 1.0 means QAT is slower; "
                "prior fp32-NS5 QAT tax (18737.7 / ~19500) ≈ 0.96 for reference"
            ),
            "cell_a_harness_flag": cell_a_flag,
        },
        "floor": {
            "K_floor": round(K_FLOOR, 2),
            "effective_days_floor": EFFECTIVE_DAYS_FLOOR,
            "provenance": "effective_days_anchor=0.96557 * tok_s_anchor=19874.8 (c04 family)",
        },
    }


# ── Receipt ───────────────────────────────────────────────────────────────────

def run_and_emit() -> Path:
    result = _run_bench()
    stamp = _ts()
    receipt = {
        "ticket": "C04-BF16NS5-QAT-PROBE",
        "ts": stamp,
        "scope": "Measure real QAT tax in bf16-NS5 context; prior QAT number (18737.7) was fp32-NS5 — NOT transferable",
        "harness": {
            "warmup": WARMUP,
            "timed": TIMED,
            "note": "production builders reused; two cells A(noqat) + B(qat); same model build, same bf16-NS5 patch",
        },
        "harness_sha": _harness_sha(),
        **result,
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"c04-bf16ns5-qat-probe-{stamp}.json")
    checked_write(path, receipt)
    print(f"[bf16ns5-qat] receipt: {path}", flush=True)

    if result.get("status") == "OK":
        an = result["analysis"]
        ca = result["cells"]["bf16ns5_noqat"]
        cb = result["cells"]["bf16ns5_qat"]
        print(
            f"[bf16ns5-qat] RESULT: "
            f"A(noqat)={ca.get('tok_s_paced')} tok/s eff_days={ca.get('eff_days')} | "
            f"B(qat)={cb.get('tok_s_paced')} tok/s eff_days={cb.get('eff_days')} | "
            f"qat_tax={an['qat_tax_ratio']} ({an['qat_tax_pct_overhead']}% overhead)",
            flush=True,
        )
        if an["cell_a_harness_flag"]:
            print(f"[bf16ns5-qat] {an['cell_a_harness_flag']}", flush=True)
    else:
        print(f"[bf16ns5-qat] status={result.get('status')}", flush=True)

    print(f"BF16NS5_QAT_THROUGHPUT_DONE status={result.get('status')}", flush=True)
    return Path(path)


# ── Schema verifier ──────────────────────────────────────────────────────────

def _verify_receipt_schema(r: dict) -> None:
    assert r["ticket"] == "C04-BF16NS5-QAT-PROBE", f"wrong ticket: {r.get('ticket')}"
    assert "ts" in r
    assert "cells" in r
    cells = r["cells"]
    for cell_key in ("bf16ns5_noqat", "bf16ns5_qat"):
        assert cell_key in cells, f"missing cell '{cell_key}'"
    an = r.get("analysis", {})
    for key in ("qat_tax_ratio", "qat_tax_pct_overhead"):
        assert key in an, f"analysis missing '{key}'"
    rec = r.get("recipe", {})
    for key in ("bf16ns5_patch", "optimizer_mode", "n_muon", "n_adamw",
                "ce_impl", "ce_chunk_tokens", "qat_mode"):
        assert key in rec, f"recipe missing '{key}'"


# ── Selftest (CPU, no GPU) ────────────────────────────────────────────────────

def selftest() -> None:
    print("[c04_bf16ns5_qat_throughput] selftest: math + schema + patch-binding + qat (no GPU)", flush=True)

    # 1. K_FLOOR identity
    rt = effective_days(TOK_S_ANCHOR)
    assert abs(rt - EFFECTIVE_DAYS_ANCHOR) < 1e-5, f"K_FLOOR identity broken: {rt} != {EFFECTIVE_DAYS_ANCHOR}"
    print(f"  K_FLOOR identity: effective_days({TOK_S_ANCHOR}) = {rt:.5f} == {EFFECTIVE_DAYS_ANCHOR}  PASS")

    # 2. Floor boundary
    assert abs(effective_days(K_FLOOR) - 1.0) < 1e-9, "floor boundary != 1.0"
    assert effective_days(K_FLOOR + 1000.0) < 1.0
    assert effective_days(K_FLOOR - 1000.0) > 1.0
    print(f"  floor boundary: tok_s>={K_FLOOR:.2f} <=> eff_days<=1.0  PASS")

    # 3. bf16-NS5 patch binds — CPU tensor, no CUDA
    import torch
    import timeshare_pretrain as ts

    # Capture original before patching
    orig = ts._zeropower_via_newtonschulz5
    ts._zeropower_via_newtonschulz5 = _zeropower_bf16
    assert ts._zeropower_via_newtonschulz5 is _zeropower_bf16, \
        "bf16-NS5 patch did not bind"
    print("  bf16-NS5 patch binds: ts._zeropower_via_newtonschulz5 is _zeropower_bf16  PASS")
    # Restore original so selftest is non-destructive
    ts._zeropower_via_newtonschulz5 = orig

    # 4. _zeropower_bf16 runs on a CPU tensor (shape check)
    g_cpu = torch.randn(4, 8)   # 2D, CPU
    out = _zeropower_bf16(g_cpu, steps=5)
    assert out.shape == g_cpu.shape, f"shape mismatch: {out.shape} vs {g_cpu.shape}"
    assert out.dtype == g_cpu.dtype, f"dtype mismatch: {out.dtype} vs {g_cpu.dtype}"
    print(f"  _zeropower_bf16 CPU shape/dtype: {out.shape} {out.dtype}  PASS")

    # 5. _apply_fake_quant runs on a toy CPU model
    import torch.nn as nn
    toy = nn.Sequential(nn.Linear(8, 4), nn.Linear(4, 2))
    saved = _apply_fake_quant(toy, "qat")
    # After qat: weights should be rounded (not equal to originals in general)
    assert len(saved) == 2, f"expected 2 linear layers in saved, got {len(saved)}"
    _restore(saved)
    print(f"  _apply_fake_quant('qat') on toy model: {len(saved)} layers patched/restored  PASS")

    # 6. Schema verify on synthetic receipt
    syn = {
        "ticket": "C04-BF16NS5-QAT-PROBE",
        "ts": "20260623T000000Z",
        "cells": {
            "bf16ns5_noqat": {"status": "OK", "tok_s_paced": 19800.0, "eff_days": round(K_FLOOR / 19800.0, 5)},
            "bf16ns5_qat":   {"status": "OK", "tok_s_paced": 19100.0, "eff_days": round(K_FLOOR / 19100.0, 5)},
        },
        "analysis": {
            "qat_tax_ratio": round(19100.0 / 19800.0, 5),
            "qat_tax_pct_overhead": round((1.0 - 19100.0 / 19800.0) * 100.0, 2),
        },
        "recipe": {
            "bf16ns5_patch": "ts._zeropower_via_newtonschulz5 = _zeropower_bf16",
            "optimizer_mode": "muon_split", "n_muon": 140, "n_adamw": 44,
            "ce_impl": "cut_ce_chunked", "ce_chunk_tokens": 1024,
            "qat_mode": "int8-grid STE",
        },
    }
    _verify_receipt_schema(syn)
    # tax should be < 1 (qat is slower)
    assert syn["analysis"]["qat_tax_ratio"] < 1.0
    print(f"  schema verify (synthetic receipt, tax={syn['analysis']['qat_tax_ratio']:.4f}): PASS")

    # 7. QAT tax ratio math
    tax = 19100.0 / 19800.0
    assert abs(tax - syn["analysis"]["qat_tax_ratio"]) < 1e-4
    print(f"  qat_tax_ratio math: B/A={tax:.5f}  PASS")

    print("BF16NS5_QAT_THROUGHPUT_SELFTEST_PASS")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Measure the real QAT tax in the bf16-NS5 context (apples-to-apples)"
    )
    ap.add_argument("--selftest", action="store_true",
                    help="CPU-only: math + patch-binding + schema; no GPU")
    args, _ = ap.parse_known_args()
    if args.selftest:
        selftest()
    else:
        run_and_emit()


if __name__ == "__main__":
    main()
