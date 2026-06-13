"""fp45_batched_ns5_ab.py — Batched Muon NS5 kernel A/B bench (Closes #329).

PRIMARY §3 lever. Groups c03's ~140 Muon params by shape, stacks into
[n,m,k] batches, applies NS5 via torch.bmm (3 dispatches/iter × 5 iters
= 15 batched dispatches per shape-group vs 140 × 15 = 2100 sequential
per-param dispatches in baseline).

c03 shape groups (h=1024, d=20, ffn=4096):
  [1024,1024] : ~80 params — attn q/k/v/o × 20 layers
  [4096,1024] : ~40 params — gate_proj/up_proj × 20 layers
  [1024,4096] : ~20 params — down_proj × 20 layers

Target: NS phase 285.83ms (fp40 receipt) → ≤89ms (3.2x) to clear §3
gate (25,463 tok/s at 2.2B-token / ≤1 governed day).

Arms:
  muon-baseline : per-param sequential NS5 (current production Muon)
  muon-batched  : shape-grouped bmm-batched NS5 (this kernel)

Protocol: warmup=5, bench=20, seeds={16,17,18}, c03 config, batch=16
ckpt=True (full-stack production config matching fp40). Synthetic data.
Governor rails: VRAM_FRACTION=0.80, MARGIN_GIB=1.5, PACE_S=0.05.

NS phase timed with cuda.Event inside optimizer.step() — includes full
NS5 computation across all shape groups. Equiv check: batched vs baseline
max-abs-delta must be <2e-7 on representative c03 shapes (fp35 bar, Leo mail 15347).

Selftest: python fp45_batched_ns5_ab.py --selftest
  Marker: FP45_BATCHED_NS5_SELFTEST_PASS

Run: via train MCP (WSL2/CUDA). Live run NOT touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")
sys.path.insert(0, HERE)

from receipt_write import checked_write  # noqa: E402

# c03 config (fp40-confirmed production config)
HIDDEN  = 1024
LAYERS  = 20
HEADS   = 16
FFN     = 4096
VOCAB   = 32000
SEQ     = 1024
BATCH   = 16    # ckpt=True full-stack (same as fp40)

WARMUP  = 5
TIMED   = 20
SEEDS   = [16, 17, 18]

# Governor rails — never relax
VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05

MTP_N_HEADS  = 2
MTP_WEIGHT   = 0.3
LR_MUON      = 0.02
LR_ADAMW     = 3e-4
WEIGHT_DECAY = 0.1

# NS5 constants
_NS_A, _NS_B, _NS_C = 3.4445, -4.7750, 2.0315
_NS_STEPS = 5
_NS_EPS   = 1e-7
_EQUIV_TOL = 2e-7   # fp35 bar — Leo mail 15347 binding guard

# §3 gate
SEC_3_TOK_S  = 25_463.0
NS_TARGET_MS = 89.0   # 285.83 / 3.2


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── NS5 implementations ───────────────────────────────────────────────────────

def _ns5_per_param(G):
    """Per-param NS5 (baseline). G: [m,k] → [m,k]. Matches timeshare_pretrain."""
    import torch
    X = G.to(torch.float32)
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T.contiguous()   # contiguous → same norm summation order as batched path
        transposed = True
    X = X / (X.norm() + _NS_EPS)
    for _ in range(_NS_STEPS):
        A = X @ X.T
        B = _NS_B * A + _NS_C * (A @ A)
        X = _NS_A * X + B @ X
    if transposed:
        X = X.T
    return X


def _ns5_batched(G_batch):
    """Batched NS5. G_batch: [n,m,k] — n params with identical shape.

    Replaces n sequential _ns5_per_param calls with 3 torch.bmm dispatches
    per iteration. Each param is normalized and transposed independently.
    """
    import torch
    X = G_batch.to(torch.float32)  # [n, m, k]
    transposed = False
    if X.shape[1] > X.shape[2]:    # transpose along param dims, not batch
        X = X.transpose(1, 2).contiguous()  # contiguous: same summation order as per-param path
        transposed = True
    # Per-param norm: [n,1,1]
    norms = X.flatten(1).norm(dim=-1).view(-1, 1, 1) + _NS_EPS
    X = X / norms
    for _ in range(_NS_STEPS):
        A = torch.bmm(X, X.transpose(1, 2))        # [n, m, m]
        B = _NS_B * A + _NS_C * torch.bmm(A, A)    # [n, m, m]
        X = _NS_A * X + torch.bmm(B, X)             # [n, m, k]
    if transposed:
        X = X.transpose(1, 2)
    return X


def _check_ns5_equiv(device="cpu") -> dict:
    """Verify batched NS5 matches per-param on 3 c03-representative shapes."""
    import torch
    results = {}
    shapes = [(64, 128), (1024, 1024), (4096, 1024), (32000, 1024)] if device != "cpu" else [(64, 128), (128, 64)]
    for shape in shapes:
        torch.manual_seed(42)
        g = torch.randn(*shape, dtype=torch.float32, device=device)
        g_batch = g.unsqueeze(0)  # [1, m, k]
        with torch.no_grad():
            x_per  = _ns5_per_param(g)
            x_batched = _ns5_batched(g_batch).squeeze(0)
        delta = (x_per - x_batched).abs().max().item()
        results[str(shape)] = {"max_abs_delta": round(float(delta), 8), "pass": delta < _EQUIV_TOL}
    return results


# ── Optimizer classes ─────────────────────────────────────────────────────────

def _build_muon_baseline():
    """Per-param sequential Muon (production baseline)."""
    import torch

    class _MuonBaseline(torch.optim.Optimizer):
        def __init__(self, params, lr=LR_MUON, momentum=0.95, nesterov=True, weight_decay=0.0):
            super().__init__(params, dict(lr=lr, momentum=momentum, nesterov=nesterov, weight_decay=weight_decay))
            self._last_ns_ms = 0.0

        @torch.no_grad()
        def step(self, closure=None):
            import torch
            ns_start = torch.cuda.Event(enable_timing=True)
            ns_end   = torch.cuda.Event(enable_timing=True)
            for group in self.param_groups:
                lr = group["lr"]; mom = group["momentum"]
                nesterov = group["nesterov"]; wd = group["weight_decay"]
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    g = p.grad
                    state = self.state[p]
                    if "momentum_buffer" not in state:
                        state["momentum_buffer"] = torch.zeros_like(g)
                    buf = state["momentum_buffer"]
                    buf.mul_(mom).add_(g)
                    upd = g.add(buf, alpha=mom) if nesterov else buf
                    ns_start.record()
                    upd = _ns5_per_param(upd)
                    ns_end.record()
                    torch.cuda.synchronize()
                    self._last_ns_ms += ns_start.elapsed_time(ns_end)
                    scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                    if wd:
                        p.mul_(1.0 - lr * wd)
                    p.add_(upd.to(p.dtype), alpha=-lr * scale)

        def reset_ns_timer(self):
            self._last_ns_ms = 0.0

    return _MuonBaseline


def _build_muon_batched(compiled_ns5: bool = False, measure: bool = True):
    """Shape-grouped batched Muon (new kernel).

    compiled_ns5=True: wraps _ns5_batched in torch.compile (Lever 1).
    measure=False: strips all cuda.Event/synchronize from step() for clean production
                   throughput measurement (no instrumentation overhead in the hot path).
    """
    import torch

    _ns5_fn = _ns5_batched
    if compiled_ns5:
        try:
            _ns5_fn = torch.compile(_ns5_batched, fullgraph=True)
        except Exception:
            _ns5_fn = _ns5_batched

    class _MuonBatched(torch.optim.Optimizer):
        def __init__(self, params, lr=LR_MUON, momentum=0.95, nesterov=True, weight_decay=0.0):
            super().__init__(params, dict(lr=lr, momentum=momentum, nesterov=nesterov, weight_decay=weight_decay))
            self._last_ns_ms = 0.0
            self._last_momentum_ms = 0.0
            self._last_update_ms = 0.0
            self._per_shape_ns_ms: Dict[str, float] = {}

        @torch.no_grad()
        def step(self, closure=None):
            import torch
            if measure:
                ev_s = torch.cuda.Event(enable_timing=True)
                ev_e = torch.cuda.Event(enable_timing=True)
            for group in self.param_groups:
                lr = group["lr"]; mom = group["momentum"]
                nesterov = group["nesterov"]; wd = group["weight_decay"]

                by_shape: Dict[tuple, List] = {}
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    by_shape.setdefault(tuple(p.shape), []).append(p)

                for shape, ps in by_shape.items():
                    grads = torch.stack([p.grad.float() for p in ps])
                    bufs  = []
                    for p in ps:
                        state = self.state[p]
                        if "momentum_buffer" not in state:
                            state["momentum_buffer"] = torch.zeros_like(p, dtype=torch.float32)
                        bufs.append(state["momentum_buffer"])
                    bufs_t = torch.stack(bufs)

                    if measure:
                        ev_s.record()
                    bufs_t.mul_(mom).add_(grads)
                    upd = grads.add(bufs_t, alpha=mom) if nesterov else bufs_t.clone()
                    if measure:
                        ev_e.record(); torch.cuda.synchronize()
                        self._last_momentum_ms += ev_s.elapsed_time(ev_e)

                    for i, p in enumerate(ps):
                        self.state[p]["momentum_buffer"].copy_(bufs_t[i])

                    if measure:
                        ev_s.record()
                    upd = _ns5_fn(upd)
                    if measure:
                        ev_e.record(); torch.cuda.synchronize()
                        _shape_ms = ev_s.elapsed_time(ev_e)
                        self._last_ns_ms += _shape_ms
                        _sk = str(shape)
                        self._per_shape_ns_ms[_sk] = self._per_shape_ns_ms.get(_sk, 0.0) + _shape_ms

                    m_sq = max(1.0, shape[0] / shape[1]) ** 0.5
                    if measure:
                        ev_s.record()
                    for i, p in enumerate(ps):
                        if wd:
                            p.mul_(1.0 - lr * wd)
                        p.add_(upd[i].to(p.dtype), alpha=-lr * m_sq)
                    if measure:
                        ev_e.record(); torch.cuda.synchronize()
                        self._last_update_ms += ev_s.elapsed_time(ev_e)

        def reset_ns_timer(self):
            self._last_ns_ms = 0.0
            self._last_momentum_ms = 0.0
            self._last_update_ms = 0.0
            self._per_shape_ns_ms = {}

    return _MuonBatched


# ── Model build ───────────────────────────────────────────────────────────────

def _build_model(grad_ckpt: bool):
    import torch
    from transformers import LlamaConfig, LlamaModel
    conf = LlamaConfig(
        vocab_size=VOCAB, hidden_size=HIDDEN, intermediate_size=FFN,
        num_hidden_layers=LAYERS, num_attention_heads=HEADS,
        num_key_value_heads=HEADS, max_position_embeddings=SEQ, use_cache=False,
    )
    backbone = LlamaModel(conf).cuda().to(torch.bfloat16)
    if grad_ckpt:
        backbone.gradient_checkpointing_enable()
    head = torch.nn.Linear(HIDDEN, VOCAB, bias=False).cuda().to(torch.bfloat16)
    head.weight = backbone.embed_tokens.weight
    mtp_heads = torch.nn.ModuleList([
        torch.nn.Linear(HIDDEN, VOCAB, bias=False).cuda().to(torch.bfloat16)
        for _ in range(MTP_N_HEADS)
    ])
    return backbone, head, mtp_heads


def _build_opts(backbone, head, mtp_heads, arm: str, compiled_ns5: bool = False, measure: bool = True):
    import torch
    all_params = dict(backbone.named_parameters())
    for i, mh in enumerate(mtp_heads):
        for n, p in mh.named_parameters():
            all_params[f"mtp_heads.{i}.{n}"] = p
    muon_p, adamw_p = [], []
    for name, p in all_params.items():
        if p.ndim == 2 and "embed_tokens" not in name:
            muon_p.append(p)
        else:
            adamw_p.append(p)

    if arm == "muon-baseline":
        MuonCls = _build_muon_baseline()
    else:
        MuonCls = _build_muon_batched(compiled_ns5=compiled_ns5, measure=measure)

    muon_opt = MuonCls(muon_p, lr=LR_MUON, weight_decay=WEIGHT_DECAY) if muon_p else None
    adamw_opt = torch.optim.AdamW(adamw_p, lr=LR_ADAMW, weight_decay=WEIGHT_DECAY)
    return muon_opt, adamw_opt, len(muon_p)


# ── Bench cell ────────────────────────────────────────────────────────────────

def _bench_seed(arm: str, seed: int) -> dict:
    import torch
    import timeshare_pretrain as ts

    torch.manual_seed(seed)
    backbone, head, mtp_heads = _build_model(grad_ckpt=True)
    backbone.train(); head.train(); mtp_heads.train()
    muon_opt, adamw_opt, n_muon = _build_opts(backbone, head, mtp_heads, arm)
    ce_fn = ts.chunked_cross_entropy

    out = {
        "arm": arm, "seed": seed,
        "n_muon_params": n_muon,
        "bench_reps": TIMED,
    }

    def step():
        ids  = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
        tgt0 = torch.roll(ids, -1, dims=1)
        tgt_m = [torch.roll(ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]
        hid = backbone(input_ids=ids).last_hidden_state
        hf  = hid.reshape(-1, hid.shape[-1])
        pce, _ = ce_fn(hf, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
        mces = [ce_fn(hf, mh.weight, tgt_m[k].reshape(-1), chunk_tokens=1024)[0]
                for k, mh in enumerate(mtp_heads)]
        loss = ts.mtp_total_loss(pce, mces, MTP_WEIGHT)
        loss.backward()
        if muon_opt is not None:
            muon_opt.reset_ns_timer()
            muon_opt.step()
        t_opt = time.perf_counter()
        adamw_opt.step()
        t_opt = time.perf_counter() - t_opt
        if muon_opt is not None:
            adamw_opt.zero_grad(set_to_none=True)
        return muon_opt._last_ns_ms if muon_opt else 0.0, t_opt

    # Warmup
    print(f"[fp45] {arm} seed={seed}: warmup {WARMUP} ...", flush=True)
    for _ in range(WARMUP):
        step()
        if muon_opt: muon_opt.zero_grad(set_to_none=True)
        adamw_opt.zero_grad(set_to_none=True)

    torch.cuda.synchronize()
    free_b, _ = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    out["free_vram_gib_post_warmup"] = round(free_gib, 2)
    if free_gib < MARGIN_GIB:
        out["status"] = "SKIPPED-MARGIN"
        return out

    # Timed bench
    print(f"[fp45] {arm} seed={seed}: bench {TIMED} ...", flush=True)
    step_times, ns_times = [], []
    t0 = time.perf_counter()
    for _ in range(TIMED):
        t_s = time.perf_counter()
        ns_ms, _t_adamw = step()
        torch.cuda.synchronize()
        t_step = time.perf_counter() - t_s
        if muon_opt: muon_opt.zero_grad(set_to_none=True)
        adamw_opt.zero_grad(set_to_none=True)
        time.sleep(PACE_S)
        step_times.append(t_step)
        ns_times.append(ns_ms)

    total_dt = time.perf_counter() - t0
    toks = TIMED * BATCH * SEQ
    tok_s_paced = toks / total_dt
    tok_s_raw   = toks / (total_dt - TIMED * PACE_S)
    mean_ns_ms  = sum(ns_times) / len(ns_times)

    out.update(
        status="OK",
        tok_s_paced=round(tok_s_paced, 1),
        tok_s_raw=round(tok_s_raw, 1),
        mean_step_s=round(sum(step_times) / len(step_times), 5),
        mean_ns_phase_ms=round(mean_ns_ms, 2),
        step_times_s=step_times,
        ns_phase_times_ms=ns_times,
    )

    del backbone, head, mtp_heads, muon_opt, adamw_opt
    torch.cuda.empty_cache()
    return out


# ── Selftest ──────────────────────────────────────────────────────────────────

def selftest():
    print("[fp45] selftest: NS5 per-param vs batched equiv ...", flush=True)

    # 1. Equivalence on CPU shapes
    equiv = _check_ns5_equiv(device="cpu")
    for shape, r in equiv.items():
        status = "PASS" if r["pass"] else "FAIL"
        print(f"[fp45]   shape {shape}: max_delta={r['max_abs_delta']:.2e} {status}", flush=True)
    if not all(r["pass"] for r in equiv.values()):
        raise SystemExit("FP45_SELFTEST_FAIL: ns5 equiv failed on CPU")

    # 2. Multi-param batching correctness
    import torch
    torch.manual_seed(99)
    n_params = 5
    shape = (128, 256)
    gs = [torch.randn(*shape) for _ in range(n_params)]
    per_param_outs = [_ns5_per_param(g) for g in gs]
    batched_out = _ns5_batched(torch.stack(gs))
    for i in range(n_params):
        delta = (per_param_outs[i] - batched_out[i]).abs().max().item()
        assert delta < _EQUIV_TOL, f"multi-param batching mismatch at i={i}: delta={delta:.2e}"
    print(f"[fp45]   multi-param (n=5) batching: PASS", flush=True)

    # 3. Shape grouping: verify transposition symmetry
    torch.manual_seed(7)
    g_tall  = torch.randn(256, 128)  # m > k → transpose
    g_wide  = torch.randn(128, 256)  # m < k → no transpose
    x_tall  = _ns5_per_param(g_tall)
    x_wide  = _ns5_per_param(g_wide)
    xb_tall = _ns5_batched(g_tall.unsqueeze(0)).squeeze(0)
    xb_wide = _ns5_batched(g_wide.unsqueeze(0)).squeeze(0)
    assert (x_tall - xb_tall).abs().max().item() < _EQUIV_TOL, "tall shape batched mismatch"
    assert (x_wide - xb_wide).abs().max().item() < _EQUIV_TOL, "wide shape batched mismatch"
    print("[fp45]   transpose symmetry (tall+wide): PASS", flush=True)

    print("FP45_BATCHED_NS5_SELFTEST_PASS", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import torch

    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args, _ = ap.parse_known_args()
    if args.selftest:
        selftest()
        return

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    print(f"[fp45] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[fp45] torch:  {torch.__version__}", flush=True)
    print(f"[fp45] fp-45 batched NS5 Muon A/B bench", flush=True)
    print(f"[fp45] BATCH={BATCH} SEQ={SEQ} LAYERS={LAYERS} HIDDEN={HIDDEN}", flush=True)

    # NS5 equiv check on GPU before benching
    import timeshare_pretrain  # noqa — ensure ts module importable
    equiv = _check_ns5_equiv(device="cuda")
    for shape, r in equiv.items():
        status = "PASS" if r["pass"] else "FAIL"
        print(f"[fp45] equiv {shape}: delta={r['max_abs_delta']:.2e} {status}", flush=True)
    if not all(r["pass"] for r in equiv.values()):
        raise SystemExit("FP45_EQUIV_FAIL — abort bench, batched NS5 numerics diverged")

    # Arm-first ordering: all baseline seeds first, then all batched seeds
    all_results = {}
    for arm in ["muon-baseline", "muon-batched"]:
        arm_results = []
        for seed in SEEDS:
            print(f"\n[fp45] --- {arm} seed={seed} ---", flush=True)
            r = _bench_seed(arm, seed)
            print(f"[fp45] {arm} seed={seed}: {r.get('status')} "
                  f"tok_s={r.get('tok_s_paced','?')} ns_ms={r.get('mean_ns_phase_ms','?')}",
                  flush=True)
            arm_results.append(r)
        all_results[arm] = arm_results

    # Aggregate
    def _agg(arm):
        ok = [r for r in all_results[arm] if r.get("status") == "OK"]
        if not ok:
            return {"status": "ALL_FAIL", "n_ok": 0}
        return {
            "status": "PASS",
            "n_ok": len(ok),
            "mean_tok_s_paced": round(sum(r["tok_s_paced"] for r in ok) / len(ok), 1),
            "mean_ns_phase_ms": round(sum(r["mean_ns_phase_ms"] for r in ok) / len(ok), 2),
        }

    agg = {arm: _agg(arm) for arm in all_results}

    baseline_tok_s = agg["muon-baseline"].get("mean_tok_s_paced", 0.0)
    batched_tok_s  = agg["muon-batched"].get("mean_tok_s_paced", 0.0)
    baseline_ns_ms = agg["muon-baseline"].get("mean_ns_phase_ms", 0.0)
    batched_ns_ms  = agg["muon-batched"].get("mean_ns_phase_ms", 0.0)

    ns_speedup = baseline_ns_ms / batched_ns_ms if batched_ns_ms > 0 else 0.0
    tok_s_mm   = batched_tok_s / baseline_tok_s if baseline_tok_s > 0 else 0.0
    sec3_pass  = batched_tok_s >= SEC_3_TOK_S
    ns_target_pass = batched_ns_ms <= NS_TARGET_MS if batched_ns_ms > 0 else False

    verdict = "BATCHED_NS5_VIABLE" if sec3_pass else (
        "BATCHED_NS5_PARTIAL" if ns_speedup >= 2.0 else "BATCHED_NS5_INSUFFICIENT"
    )

    print(f"\n[fp45] RESULT:", flush=True)
    print(f"[fp45]   baseline NS={baseline_ns_ms:.1f}ms  batched NS={batched_ns_ms:.1f}ms  speedup={ns_speedup:.2f}x", flush=True)
    print(f"[fp45]   baseline tok/s={baseline_tok_s:.0f}  batched tok/s={batched_tok_s:.0f}  MM={tok_s_mm:.4f}", flush=True)
    print(f"[fp45]   §3 gate ({SEC_3_TOK_S:.0f} tok/s): {'PASS' if sec3_pass else 'FAIL'}", flush=True)
    print(f"[fp45]   NS target (≤{NS_TARGET_MS:.0f}ms): {'PASS' if ns_target_pass else 'FAIL'}", flush=True)
    print(f"[fp45]   VERDICT: {verdict}", flush=True)

    ts_now = _ts()
    receipt = {
        "ticket":  "FP45-BATCHED-NS5-AB",
        "ts":      ts_now,
        "issue":   "#329",
        "verdict": verdict,
        "harness_sha": _harness_sha(),
        "runtime": {
            "device": torch.cuda.get_device_name(0),
            "sm":     str(torch.cuda.get_device_properties(0).major * 10 +
                         torch.cuda.get_device_properties(0).minor),
            "torch":  torch.__version__,
        },
        "config": {
            "hidden": HIDDEN, "layers": LAYERS, "heads": HEADS,
            "ffn": FFN, "vocab": VOCAB, "seq": SEQ, "batch": BATCH,
            "grad_checkpointing": True, "warmup": WARMUP, "timed": TIMED,
            "seeds": SEEDS, "mtp_n_heads": MTP_N_HEADS,
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION, "margin_gib_floor": MARGIN_GIB,
            "pace_s_per_step": PACE_S,
        },
        "ns5_equiv": equiv,
        "arm_aggregate": agg,
        "per_seed_results": all_results,
        "summary": {
            "baseline_ns_phase_ms": baseline_ns_ms,
            "batched_ns_phase_ms":  batched_ns_ms,
            "ns_speedup":           round(ns_speedup, 3),
            "ns_target_pass":       ns_target_pass,
            "baseline_tok_s_paced": baseline_tok_s,
            "batched_tok_s_paced":  batched_tok_s,
            "tok_s_multiplier":     round(tok_s_mm, 4),
            "sec3_gate_pass":       sec3_pass,
            "sec3_threshold":       SEC_3_TOK_S,
        },
        "flags": [
            "c03 shapes (fp40-confirmed production config)",
            "live run NOT touched",
            "governor rails HOLD — never loosened",
            "batched arm: shape-grouped bmm NS5 (3 bmm dispatches/iter × 5 iters per group)",
            "baseline arm: per-param sequential NS5 (production Muon)",
            "NS phase timed with cuda.Event inside optimizer.step()",
            "arm-first ordering: all baseline seeds before batched seeds",
            "data: synthetic (torch.randint) — timing bench",
            "platform: WSL2 CUDA via train MCP",
        ],
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    out_path = os.path.join(RECEIPTS, f"fp45-batched-ns5-ab-{ts_now}.json")
    checked_write(out_path, receipt)
    print(f"[fp45] receipt: {out_path}", flush=True)
    print(f"FP45_BATCHED_NS5_AB_DONE verdict={verdict} ns_speedup={ns_speedup:.2f}x "
          f"sec3={'PASS' if sec3_pass else 'FAIL'}", flush=True)


if __name__ == "__main__":
    main()
