"""fp35_fused_muon_kernel_ab.py — fused Newton-Schulz kernel A/B bench (Closes #329).

Step-time A/B comparing Muon optimizer with unfused vs torch.compile-fused Newton-Schulz
orthogonalization chain. Optimizer is 45.9% of phase GPU time (fp33-e4 profiler receipt) —
largest remaining kernel-route target at c03 shapes.

Arms:
  muon-baseline : Muon with unfused NS5 (3 separate matmul dispatches per iteration)
  muon-fused    : Muon with torch.compile(ns5, mode="reduce-overhead") fused chain

Claim:
  NS5 chain (A=X@X.T, B=b*A+c*(A@A), X=a*X+B@X) is memory-bound at c03 HIDDEN=1024.
  Fusing collapses repeated HBM round-trips into a single inductor kernel per iteration.
  Expected effect: optimizer step wall-time cut; total step MM = 45.9% * kernel_gain.

Protocol:
  warmup_steps=5, bench_steps=20, seeds={16,17,18}, c03 shapes, grad-ckpt disabled.
  Metric: tokens/s; measured_multiplier = fused_tok_s / baseline_tok_s.
  Bar: all-seed mean MM >= 1.02 + no errors -> MUON_FUSED_VIABLE; else MUON_FUSED_PARK.

Governed: VRAM_FRACTION=0.80, MARGIN_GIB=1.5, PACE_S=0.05 (fp19 floor).
Live run 12c050e7 NOT touched.

Selftest: python fp35_fused_muon_kernel_ab.py --selftest
  Marker: MUON_FUSED_AB_SELFTEST_PASS

Run: via train MCP (WSL2/CUDA). Uses synthetic data — no shard dependency.
  Previous Windows-Python attempt failed: TRITON_NO_C_COMPILER (no gcc on host).
  WSL2 has gcc; torch.compile(ns5, fullgraph=False) works without the transformers
  co_varnames issue (we compile only the standalone NS5 function, not LlamaModel).

Arm-first ordering: all muon-baseline seeds first, then all muon-fused seeds (prevents
a fused-variant failure from polluting the CUDA context of control measurements).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

import torch
import torch.nn as nn

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")

# c03 shapes (v0 training config — same as E4 profiler)
HIDDEN      = 1024
LAYERS      = 20
HEADS       = 16
FFN         = 4096
VOCAB       = 32000
SEQ         = 1024
BATCH       = 4
WARMUP_REPS = 5
BENCH_REPS  = 20

SEEDS = [16, 17, 18]

# Governor rails (fp19 floor — never relax)
VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05

LIVE_RUN_SHA = "12c050e7"

# Newton-Schulz quintic coefficients (Muon / Bernstein-Newhouse)
_NS_A     = 3.4445
_NS_B     = -4.7750
_NS_C     = 2.0315
_NS_STEPS = 5
_NS_EPS   = 1e-7


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    """sha256 of this script's on-disk bytes (binary read, no normalization)."""
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Synthetic batch generator (no shard dependency — timing bench only)
# ---------------------------------------------------------------------------

class SyntheticDataset:
    def __init__(self, vocab: int, seq: int, seed: int):
        self._vocab = vocab
        self._seq = seq
        self._rng = torch.Generator()
        self._rng.manual_seed(seed)

    def next_batch(self, batch: int):
        x = torch.randint(0, self._vocab, (batch, self._seq), generator=self._rng)
        y = torch.randint(0, self._vocab, (batch, self._seq), generator=self._rng)
        return x, y


# ---------------------------------------------------------------------------
# Newton-Schulz orthogonalization — baseline (unfused) and fused variants
# ---------------------------------------------------------------------------

def _ns5_baseline(G):
    """Unfused NS5: 3 separate kernel dispatches per iteration."""
    X = G.to(torch.float32)
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T
        transposed = True
    X = X / (X.norm() + _NS_EPS)
    for _ in range(_NS_STEPS):
        A = X @ X.T
        B = _NS_B * A + _NS_C * (A @ A)
        X = _NS_A * X + B @ X
    if transposed:
        X = X.T
    return X


# Fused: torch.compile with reduce-overhead fuses the iteration kernels via inductor.
# Warmup_steps (5) absorb the tracing cost; bench_steps measure steady-state.
_ns5_fused = torch.compile(_ns5_baseline, mode="reduce-overhead", fullgraph=False)

_EQUIV_TOL = 1e-3


def _check_ns5_equiv(fused_fn, tol: float = _EQUIV_TOL, device: str = "cpu") -> float:
    """NS5 baseline vs fused_fn numeric equivalence on device. Returns max-abs delta.

    Raises SystemExit with MUON_FUSED_EQUIV_FAIL if delta exceeds tol, refusing the bench.
    Uses a small shape on CPU (selftest), representative c03 shape on CUDA (main).
    """
    shape = (64, 128) if device == "cpu" else (1024, 4096)
    torch.manual_seed(7)
    G = torch.randn(*shape, dtype=torch.float32, device=device)
    with torch.no_grad():
        X_base = _ns5_baseline(G.to(device))
        if device != "cpu":
            torch.cuda.synchronize()
        X_fuse = fused_fn(G.to(device))
        if device != "cpu":
            torch.cuda.synchronize()
    delta = (X_base - X_fuse).abs().max().item()
    if delta > tol:
        raise SystemExit(
            f"MUON_FUSED_EQUIV_FAIL: ns5 baseline vs fused max-abs-delta="
            f"{delta:.2e} > tol={tol:.2e} — "
            "compiled kernel numerics diverged, bench refused"
        )
    return delta


# ---------------------------------------------------------------------------
# Muon optimizer factory
# ---------------------------------------------------------------------------

def _build_muon_class(ns_fn):
    """Return a Muon optimizer class using the given Newton-Schulz function."""
    class _Muon(torch.optim.Optimizer):
        def __init__(self, params, lr=0.02, momentum=0.95, nesterov=True,
                     weight_decay=0.0):
            defaults = dict(lr=lr, momentum=momentum, nesterov=nesterov,
                            weight_decay=weight_decay)
            super().__init__(params, defaults)

        @torch.no_grad()
        def step(self, closure=None):
            loss = None
            if closure is not None:
                with torch.enable_grad():
                    loss = closure()
            for group in self.param_groups:
                lr = group["lr"]
                mom = group["momentum"]
                nesterov = group["nesterov"]
                wd = group["weight_decay"]
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    g = p.grad
                    if g.ndim != 2:
                        raise ValueError("Muon received a non-2D parameter")
                    state = self.state[p]
                    if "momentum_buffer" not in state:
                        state["momentum_buffer"] = torch.zeros_like(g)
                    buf = state["momentum_buffer"]
                    buf.mul_(mom).add_(g)
                    upd = g.add(buf, alpha=mom) if nesterov else buf
                    upd = ns_fn(upd)
                    scale = max(1.0, p.shape[0] / p.shape[1]) ** 0.5
                    if wd != 0.0:
                        p.mul_(1.0 - lr * wd)
                    p.add_(upd, alpha=-lr * scale)
            return loss

    return _Muon


def split_param_groups(model):
    """Route params: 2D non-embed non-head -> Muon; rest -> AdamW."""
    muon, adamw = [], []
    seen = set()
    for name, p in model.named_parameters():
        if not p.requires_grad or id(p) in seen:
            continue
        seen.add(id(p))
        low = name.lower()
        is_2d = p.ndim == 2
        is_embed = "embed" in low
        is_head = "head" in low
        if is_2d and not is_embed and not is_head:
            muon.append((name, p))
        else:
            adamw.append((name, p))
    return muon, adamw


def _build_split_optimizer(model, arm: str):
    muon_named, adamw_named = split_param_groups(model)
    ns_fn = _ns5_baseline if arm == "muon-baseline" else _ns5_fused
    MuonCls = _build_muon_class(ns_fn)
    opts = {}
    if muon_named:
        opts["muon"] = MuonCls(
            [p for _, p in muon_named], lr=0.02, momentum=0.95,
            nesterov=True, weight_decay=0.1,
        )
    opts["adamw"] = torch.optim.AdamW(
        [p for _, p in adamw_named], lr=3e-4, weight_decay=0.1,
    )
    return opts, len(muon_named)


# ---------------------------------------------------------------------------
# Per-arm training measurement
# ---------------------------------------------------------------------------

def _build_model():
    from transformers import LlamaConfig, LlamaForCausalLM
    conf = LlamaConfig(
        vocab_size=VOCAB, hidden_size=HIDDEN,
        intermediate_size=FFN,
        num_hidden_layers=LAYERS, num_attention_heads=HEADS,
        num_key_value_heads=HEADS,
        max_position_embeddings=SEQ * 2,
        tie_word_embeddings=True,
        bos_token_id=1, eos_token_id=2,
    )
    model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
    model.gradient_checkpointing_disable()
    model.train()
    return model


def measure_arm(seed: int, arm: str) -> dict:
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.empty_cache()

    free_before, _ = torch.cuda.mem_get_info()

    try:
        model = _build_model()
    except torch.cuda.OutOfMemoryError as e:
        torch.cuda.empty_cache()
        return {"arm": arm, "seed": seed, "error": f"OOM_AT_BUILD: {e}",
                "measured_multiplier": None}

    try:
        opts, n_muon = _build_split_optimizer(model, arm)
    except Exception as e:
        del model
        torch.cuda.empty_cache()
        return {"arm": arm, "seed": seed, "error": f"OPT_BUILD_ERROR: {e}",
                "measured_multiplier": None}

    dataset = SyntheticDataset(VOCAB, SEQ, seed)

    # Warmup — absorbs torch.compile tracing cost for fused arm
    for _ in range(WARMUP_REPS):
        x, y = dataset.next_batch(BATCH)
        x, y = x.cuda(), y.cuda()
        try:
            out = model(input_ids=x, labels=y)
            out.loss.backward()
        except torch.cuda.OutOfMemoryError as e:
            del model, opts, dataset
            torch.cuda.empty_cache()
            return {"arm": arm, "seed": seed, "error": f"OOM_AT_WARMUP: {e}",
                    "measured_multiplier": None}
        for opt in opts.values():
            opt.step()
        for opt in opts.values():
            opt.zero_grad(set_to_none=True)
        time.sleep(PACE_S)

    # Bench
    step_times = []
    for _ in range(BENCH_REPS):
        x, y = dataset.next_batch(BATCH)
        x, y = x.cuda(), y.cuda()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        try:
            out = model(input_ids=x, labels=y)
            out.loss.backward()
            for opt in opts.values():
                opt.step()
            for opt in opts.values():
                opt.zero_grad(set_to_none=True)
        except torch.cuda.OutOfMemoryError as e:
            del model, opts, dataset
            torch.cuda.empty_cache()
            return {"arm": arm, "seed": seed, "error": f"OOM_AT_BENCH: {e}",
                    "measured_multiplier": None}
        torch.cuda.synchronize()
        step_times.append(time.perf_counter() - t0)
        time.sleep(PACE_S)

    free_after, _ = torch.cuda.mem_get_info()
    vram_used_gib = (free_before - free_after) / (1 << 30)

    tokens_per_step = BATCH * SEQ
    mean_step_s     = sum(step_times) / len(step_times)
    tokens_per_s    = tokens_per_step / mean_step_s

    del model, opts, dataset
    torch.cuda.empty_cache()

    return {
        "arm": arm,
        "seed": seed,
        "bench_reps": BENCH_REPS,
        "mean_step_s": round(mean_step_s, 5),
        "tokens_per_step": tokens_per_step,
        "tokens_per_s": round(tokens_per_s, 1),
        "vram_used_gib": round(vram_used_gib, 3),
        "step_times_s": [round(t, 5) for t in step_times],
        "n_muon_params": n_muon,
        "error": None,
        "measured_multiplier": None,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    if free_gib < MARGIN_GIB:
        raise SystemExit(
            f"MUON_FUSED_AB_GOVERNOR_FAIL: {free_gib:.2f} GiB free < "
            f"{MARGIN_GIB} GiB — refusing launch"
        )

    governor = {
        "vram_fraction": VRAM_FRACTION,
        "margin_gib_floor": MARGIN_GIB,
        "pace_s_per_step": PACE_S,
        "free_gib_at_launch": round(free_gib, 2),
        "total_gib": round(total_b / (1 << 30), 2),
    }

    arms = ["muon-baseline", "muon-fused"]
    config = {
        "hidden": HIDDEN, "layers": LAYERS, "heads": HEADS,
        "ffn": FFN, "vocab": VOCAB, "seq": SEQ, "batch": BATCH,
        "warmup_reps": WARMUP_REPS, "bench_reps": BENCH_REPS,
        "vram_fraction": VRAM_FRACTION, "seeds": SEEDS,
        "arms": arms,
        "ns_steps": _NS_STEPS,
        "ns_coefficients": {"a": _NS_A, "b": _NS_B, "c": _NS_C},
        "muon_lr": 0.02, "muon_momentum": 0.95, "muon_nesterov": True,
        "muon_weight_decay": 0.1, "adamw_lr": 3e-4, "adamw_weight_decay": 0.1,
        "compile_mode": "reduce-overhead",
        "data": "synthetic (timing bench — no shard dependency)",
    }

    print(
        f"[fp35_fused_muon_kernel_ab] c03 hidden={HIDDEN} layers={LAYERS} "
        f"ffn={FFN} seq={SEQ} batch={BATCH}",
        flush=True,
    )
    print(f"  torch: {torch.__version__}  device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"  seeds: {SEEDS}, warmup={WARMUP_REPS}, bench={BENCH_REPS}", flush=True)
    print(f"  fused arm: torch.compile(ns5, mode='reduce-overhead')", flush=True)

    # GPU-side NS5 equivalence check — must pass before bench may proceed.
    # Catches torch.compile miscompile / fusion-reorder on this specific GPU/driver.
    # CPU inductor is unavailable on Windows without MSVC, so this is the only
    # place where fused kernel numerics are validated.
    print("  Checking NS5 equiv on CUDA (1024×4096, seed=7)...", flush=True)
    ns5_equiv_max_abs_delta = _check_ns5_equiv(_ns5_fused, tol=_EQUIV_TOL, device="cuda")
    print(
        f"  NS5 equiv PASS: max_abs_delta={ns5_equiv_max_abs_delta:.2e} "
        f"(tol={_EQUIV_TOL:.2e})",
        flush=True,
    )
    torch.cuda.empty_cache()

    results: dict[str, list[dict]] = {arm: [] for arm in arms}

    for arm in arms:
        for seed in SEEDS:
            print(f"  arm={arm} seed={seed} ...", flush=True)
            r = measure_arm(seed, arm)
            if r.get("error"):
                print(f"    ERROR: {r['error']}", flush=True)
            else:
                print(
                    f"    {r['tokens_per_s']:.0f} tok/s, "
                    f"step={r['mean_step_s']*1000:.1f}ms, "
                    f"vram={r['vram_used_gib']:.2f} GiB, "
                    f"muon_params={r.get('n_muon_params')}",
                    flush=True,
                )
            results[arm].append(r)

    # Aggregate per arm
    arm_agg: dict[str, dict] = {}
    for arm in arms:
        valid = [r for r in results[arm] if r.get("error") is None]
        if not valid:
            arm_agg[arm] = {
                "status": "FAIL",
                "reason": results[arm][0].get("error", "all seeds failed"),
                "mean_tokens_per_s": None,
            }
        else:
            arm_agg[arm] = {
                "status": "PASS",
                "n_valid_seeds": len(valid),
                "mean_tokens_per_s": round(
                    sum(r["tokens_per_s"] for r in valid) / len(valid), 1
                ),
                "mean_step_s": round(
                    sum(r["mean_step_s"] for r in valid) / len(valid), 5
                ),
                "mean_vram_used_gib": round(
                    sum(r["vram_used_gib"] for r in valid) / len(valid), 3
                ),
            }

    # measured_multiplier relative to muon-baseline control
    ctrl_tok_s = arm_agg["muon-baseline"].get("mean_tokens_per_s") or 0.0
    for arm in arms:
        agg = arm_agg[arm]
        arm_tok_s = agg.get("mean_tokens_per_s")
        if arm_tok_s and ctrl_tok_s > 0:
            agg["measured_multiplier"] = round(arm_tok_s / ctrl_tok_s, 4)
        else:
            agg["measured_multiplier"] = None

    # Per-seed multipliers
    ctrl_seed_tok: dict[int, float] = {}
    for r in results["muon-baseline"]:
        if r.get("error") is None:
            ctrl_seed_tok[r["seed"]] = r["tokens_per_s"]
    for r in results["muon-fused"]:
        s = r.get("seed")
        if r.get("error") is None and s in ctrl_seed_tok and ctrl_seed_tok[s] > 0:
            r["measured_multiplier"] = round(r["tokens_per_s"] / ctrl_seed_tok[s], 4)

    fused_mm     = arm_agg["muon-fused"].get("measured_multiplier")
    fused_status = arm_agg["muon-fused"].get("status")

    if fused_status == "PASS" and fused_mm is not None and fused_mm >= 1.02:
        verdict = "MUON_FUSED_VIABLE"
    elif fused_status == "PASS" and fused_mm is not None:
        verdict = "MUON_FUSED_PARK"
    else:
        verdict = "MUON_FUSED_ERROR"

    ts = _ts()
    receipt = {
        "ticket": "MUON_FUSED_AB",
        "ts": ts,
        "verdict": verdict,
        "issue": "#329",
        "harness_sha": _harness_sha(),
        "runtime": {
            "device": str(torch.cuda.get_device_name(0)),
            "sm": str(
                torch.cuda.get_device_capability(0)[0] * 10
                + torch.cuda.get_device_capability(0)[1]
            ),
            "torch": torch.__version__,
        },
        "config": config,
        "governor": governor,
        "arm_aggregate": arm_agg,
        "per_seed_results": {arm: results[arm] for arm in arms},
        "measured_multiplier_vs_baseline": fused_mm,
        "ns5_equiv_check": {
            "max_abs_delta": round(ns5_equiv_max_abs_delta, 8),
            "tolerance": _EQUIV_TOL,
            "shape_tested": [1024, 4096],
            "seed": 7,
            "pass": True,
        },
        "flags": [
            "c03 shapes (v0 training config — same as E4 profiler)",
            f"live run {LIVE_RUN_SHA} NOT touched",
            "governor rails HOLD — never loosened",
            "fused arm: torch.compile(ns5, mode='reduce-overhead') — inductor kernel fusion",
            "muon-baseline: unfused NS5 (3 separate matmul dispatches per iteration)",
            "optimizer claim: NS5 chain memory-bound at c03 HIDDEN=1024 (45.9% phase time per fp33-e4)",
            "arm-first ordering: all muon-baseline seeds before muon-fused seeds",
            "split optimizer: Muon on 2D non-embed non-head; AdamW on rest",
            "VIABLE bar: mean MM >= 1.02; below bar -> PARK with receipt",
            "sha_convention: sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
            "data: synthetic (torch.randint) — timing bench; no shard dependency",
            "platform: WSL2 CUDA via train MCP (prior Windows attempt: TRITON_NO_C_COMPILER)",
        ],
        "live_run_untouched": LIVE_RUN_SHA,
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
    }

    print(f"\n[fp35_fused_muon_kernel_ab] verdict: {verdict}", flush=True)
    for arm in arms:
        agg = arm_agg[arm]
        mm = agg.get("measured_multiplier")
        if agg["status"] == "PASS":
            print(
                f"  {arm}: {agg['mean_tokens_per_s']:.0f} tok/s, MM={mm:.4f}x",
                flush=True,
            )
        else:
            print(f"  {arm}: {agg['status']} — {agg.get('reason', '')}", flush=True)

    os.makedirs(RECEIPTS, exist_ok=True)
    out = os.path.join(RECEIPTS, f"fp35-fused-muon-kernel-ab-{ts}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"MUON_FUSED_AB_DONE {out}")
    return receipt


# ---------------------------------------------------------------------------
# Selftest (CPU-only; no GPU, no shards required)
# ---------------------------------------------------------------------------

def _selftest():
    # 1. Governor constants satisfy fp19 floor
    assert VRAM_FRACTION <= 0.80, "VRAM_FRACTION must not exceed 0.80"
    assert MARGIN_GIB >= 1.5,    "MARGIN_GIB must not be below 1.5"
    assert PACE_S >= 0.05,       "PACE_S must not be below 0.05"

    # 2. Live run pin unchanged
    assert LIVE_RUN_SHA == "12c050e7"

    # 3. NS5 baseline CPU: correct shape, finite values, singular values bounded near 1
    torch.manual_seed(42)
    G = torch.randn(8, 8)
    X = _ns5_baseline(G)
    assert X.shape == G.shape, f"NS5 output shape: {X.shape}"
    assert torch.isfinite(X).all(), "NS5 output contains non-finite values"
    # Singular values should be bounded (NS5 is semi-orthogonal, not exact at 5 steps)
    sv = torch.linalg.svdvals(X.float())
    assert sv.max().item() < 5.0, f"NS5 singular values too large: max={sv.max():.3f}"
    assert sv.min().item() > 0.0, f"NS5 singular values collapsed to zero"

    # 4. Tall matrix: transpose path exercises correctly
    torch.manual_seed(7)
    G_tall = torch.randn(16, 8)
    X_tall = _ns5_baseline(G_tall)
    assert X_tall.shape == (16, 8), f"tall matrix output shape: {X_tall.shape}"
    assert torch.isfinite(X_tall).all(), "NS5 tall output has non-finite values"

    # 5. torch.compile wraps the function (callable attribute present)
    assert callable(_ns5_fused), "_ns5_fused must be callable"

    # 6. NS5 baseline == fused on CPU where C++ compiler available; else skip.
    # On Windows without MSVC, inductor raises InductorError — this is expected and
    # only affects CPU selftesting. GPU (CUDA) compile does not require cl.
    try:
        torch.manual_seed(42)
        G2 = torch.randn(6, 8)
        X_base = _ns5_baseline(G2)
        X_fuse = _ns5_fused(G2)
        diff = (X_base - X_fuse).abs().max().item()
        assert diff < 1e-4, f"baseline/fused CPU mismatch: {diff:.2e}"
    except Exception as e:
        msg = str(e)
        if "Compiler" in msg or "cl is not found" in msg or "InductorError" in msg:
            pass  # no MSVC — CPU inductor unavailable; GPU compile unaffected
        else:
            raise

    # 7. _check_ns5_equiv PASS path: baseline vs baseline on CPU -> delta=0
    delta_ok = _check_ns5_equiv(_ns5_baseline, tol=1e-3, device="cpu")
    assert delta_ok < 1e-3, f"baseline vs baseline delta unexpectedly large: {delta_ok:.2e}"

    # 8. _check_ns5_equiv FAIL path: monkeypatched fused fn with large delta
    def _bad_ns5(G):
        return _ns5_baseline(G) * 2.0  # wildly wrong output
    try:
        _check_ns5_equiv(_bad_ns5, tol=1e-3, device="cpu")
        raise AssertionError("FAIL path did not raise SystemExit")
    except SystemExit as se:
        assert "MUON_FUSED_EQUIV_FAIL" in str(se), \
            f"wrong SystemExit message: {se}"

    # 9. Muon optimizer builds and steps with baseline NS (CPU tensors, 2D param)
    for arm in ("muon-baseline", "muon-fused"):
        torch.manual_seed(0)
        p = nn.Parameter(torch.randn(8, 8))
        # Both arms tested with baseline NS in selftest — structure test only;
        # actual fused dispatch tested on GPU at bench time.
        MuonCls = _build_muon_class(_ns5_baseline)
        opt = MuonCls([p], lr=0.01)
        p.grad = torch.randn_like(p)
        before = p.data.clone()
        opt.step()
        assert not torch.equal(before, p.data), f"{arm}: Muon step was a no-op"

    # 10. split_param_groups routing: 2D non-embed non-head -> Muon
    class _FakeModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.layer_weight = nn.Parameter(torch.zeros(4, 4))   # 2D -> Muon
            self.embed_tokens  = nn.Parameter(torch.zeros(8, 4))  # embed -> AdamW
            self.lm_head       = nn.Parameter(torch.zeros(4, 4))  # head -> AdamW
            self.bias          = nn.Parameter(torch.zeros(4))     # 1D -> AdamW

    fake = _FakeModel()
    muon_params, adamw_params = split_param_groups(fake)
    muon_names  = {n for n, _ in muon_params}
    adamw_names = {n for n, _ in adamw_params}
    assert "layer_weight" in muon_names,  f"layer_weight not in Muon: {muon_names}"
    assert "embed_tokens"  in adamw_names, f"embed_tokens not in AdamW: {adamw_names}"
    assert "lm_head"       in adamw_names, f"lm_head not in AdamW: {adamw_names}"
    assert "bias"          in adamw_names, f"bias not in AdamW: {adamw_names}"

    # 11. NS coefficients match timeshare_pretrain.py values
    assert _NS_A == 3.4445 and _NS_B == -4.7750 and _NS_C == 2.0315, \
        f"NS coefficients drifted: a={_NS_A}, b={_NS_B}, c={_NS_C}"

    # 12. SyntheticDataset: correct shapes, reproducible with same seed
    ds1 = SyntheticDataset(vocab=100, seq=8, seed=42)
    ds2 = SyntheticDataset(vocab=100, seq=8, seed=42)
    x1, y1 = ds1.next_batch(2)
    x2, y2 = ds2.next_batch(2)
    assert x1.shape == (2, 8), f"SyntheticDataset x shape: {x1.shape}"
    assert y1.shape == (2, 8), f"SyntheticDataset y shape: {y1.shape}"
    assert torch.equal(x1, x2) and torch.equal(y1, y2), \
        "SyntheticDataset not reproducible with same seed"
    assert x1.max().item() < 100 and x1.min().item() >= 0, \
        "SyntheticDataset tokens out of vocab range"

    print("MUON_FUSED_AB_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
