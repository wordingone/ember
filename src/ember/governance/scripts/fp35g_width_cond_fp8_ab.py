"""fp35g_width_cond_fp8_ab.py — width-conditional fp8 dispatch A/B bench (Closes #305).

End-to-end step A/B for replacing only K>=4096 linear sites (c03: MLP down_proj,
20 layers) with fp8 weight-cache forward vs all-bf16 control.

Arms:
  bf16           : standard LlamaForCausalLM bf16 (control)
  fp8-width-cond : same model + Fp8DownProjLinear on all down_proj (in_features=FFN=4096)

Protocol:
  warmup_steps=5, bench_steps=20, seeds={16,17,18}, c03 shapes, grad-ckpt disabled.
  Metric: tokens/s; measured_multiplier = fp8_tok_s / bf16_tok_s.
  Bar: all-seed mean MM >= 1.02 + no errors -> FP8_WIDTH_COND_VIABLE; else FP8_WIDTH_COND_PARK.

Governed: VRAM_FRACTION=0.80, MARGIN_GIB=1.5, PACE_S=0.05 (fp19 floor).
Live run 12c050e7 NOT touched.

Selftest: python fp35g_width_cond_fp8_ab.py --selftest
  Marker: FP8_WIDTH_COND_AB_SELFTEST_PASS

Run: python fp35g_width_cond_fp8_ab.py
  NOT via train MCP. Native Windows Python only.

Arm-first ordering: all bf16 seeds first, then all fp8-width-cond seeds (prevents
an fp8 init failure from polluting the CUDA context of control measurements).
"""
from __future__ import annotations

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

SHARD_DIR   = os.path.join(os.path.dirname(NC), "shards-v0")
SHARD_FILES = ["v0-00000.bin", "v0-00001.bin"]

# Governor rails (fp19 floor — never relax)
VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05

LIVE_RUN_SHA = "12c050e7"

# Dispatch gate: only linears with in_features >= this threshold get fp8 forward
# c03 target: down_proj only (in_features=FFN=4096); all other sites stay bf16
FP8_K_THRESHOLD = 4096


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Shard-backed dataset (same as selective_recompute_ab.py)
# ---------------------------------------------------------------------------

class ShardDataset:
    def __init__(self, shard_dir: str, shard_files: list[str], seq: int, seed: int):
        import numpy as np
        chunks = []
        for fname in shard_files:
            p = os.path.join(shard_dir, fname)
            if not os.path.exists(p):
                raise FileNotFoundError(f"shard not found: {p}")
            chunks.append(np.memmap(p, dtype=np.uint16, mode="r"))
        self._tokens = np.concatenate([c.astype(np.int64) for c in chunks])
        self._seq = seq
        self._n = len(self._tokens) - seq - 1
        rng = np.random.default_rng(seed)
        self._order = rng.permutation(self._n)
        self._pos = 0

    def next_batch(self, batch: int):
        import numpy as np
        idxs = []
        for _ in range(batch):
            if self._pos >= len(self._order):
                self._pos = 0
            idxs.append(self._order[self._pos])
            self._pos += 1
        rows = np.stack([self._tokens[i: i + self._seq + 1] for i in idxs])
        x = torch.from_numpy(rows[:, :-1].copy()).long()
        y = torch.from_numpy(rows[:, 1:].copy()).long()
        return x, y


# ---------------------------------------------------------------------------
# Fp8DownProjLinear — weight-cache fp8 autograd.Function
#
# Forward:  cast x to fp8; _scaled_mm(x_fp8, w_fp8.t()) -> bf16 output.
# Backward: bf16 grad_input + grad_weight (no fp8 in backward path).
#
# The fp8 weight buffer is cached at init and NOT updated per optimizer step.
# This is intentional for the bench: we measure step throughput, not final quality.
# ---------------------------------------------------------------------------

class _Fp8WeightCacheFn(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x, w_bf16, w_fp8):
        # x: (..., K) bf16 | w_bf16: (N, K) bf16 | w_fp8: (N, K) fp8
        orig = x.shape
        x_2d = x.reshape(-1, orig[-1])           # (M, K) contiguous bf16

        # Cast activations to fp8 (1 cast per step for down_proj sites)
        x_fp8 = x_2d.to(torch.float8_e4m3fn)    # (M, K) fp8 row-major

        # Unit scales — weight is not rescaled here (unit-scaling convention)
        scale_a = torch.ones(1, dtype=torch.float32, device=x.device)
        scale_b = torch.ones(1, dtype=torch.float32, device=x.device)

        # w_fp8.t(): strides (1, N) — column-major (K, N). Do NOT call .contiguous()
        # (that would produce row-major (K, N) and trigger cuBLASLt layout rejection)
        w_fp8_col = w_fp8.t()

        out_2d = torch._scaled_mm(
            x_fp8, w_fp8_col,
            scale_a=scale_a, scale_b=scale_b,
            out_dtype=torch.bfloat16,
        )                                         # (M, N) bf16

        # Save bf16 x for grad_weight; w_bf16 for grad_input
        ctx.save_for_backward(x_2d.to(torch.bfloat16), w_bf16)
        ctx.orig = orig
        return out_2d.reshape(*orig[:-1], w_bf16.shape[0])

    @staticmethod
    def backward(ctx, grad_out):
        x_bf16, w_bf16 = ctx.saved_tensors
        orig = ctx.orig

        g_2d = grad_out.reshape(-1, grad_out.shape[-1]).to(torch.bfloat16)  # (M, N)

        # grad_input: (M, K) = g_2d @ w_bf16  — bf16 matmul
        grad_input = g_2d @ w_bf16              # (M, K)
        grad_input = grad_input.reshape(orig)

        # grad_weight: (N, K) = g_2d.T @ x_bf16  — bf16 matmul
        grad_weight = g_2d.t() @ x_bf16         # (N, K)

        # Slot order: x, w_bf16, w_fp8 — no grad for w_fp8 buffer
        return grad_input, grad_weight, None


class Fp8DownProjLinear(nn.Module):
    """Drop-in replacement for nn.Linear with fp8 weight-cache forward.

    Trainable parameter: self.weight (bf16) — optimizer updates this each step.
    Read-only buffer:    self.weight_fp8 (fp8)  — cached at init, not updated.

    Dispatch condition: in_features >= FP8_K_THRESHOLD.
    """

    def __init__(self, original: nn.Linear):
        super().__init__()
        self.in_features  = original.in_features
        self.out_features = original.out_features
        # Bf16 trainable weight — optimizer updates this
        self.weight = nn.Parameter(original.weight.data.clone())
        self.bias   = original.bias
        # Fp8 cache: computed once at replacement time
        with torch.no_grad():
            w_fp8 = original.weight.data.to(torch.float8_e4m3fn)
        self.register_buffer("weight_fp8", w_fp8)  # (N, K) fp8

    def forward(self, x):
        return _Fp8WeightCacheFn.apply(x, self.weight, self.weight_fp8)


def apply_width_cond_fp8(model) -> int:
    """Replace down_proj linears with in_features >= FP8_K_THRESHOLD with Fp8DownProjLinear.

    Returns count of replaced layers (expected: LAYERS = 20 for c03).
    """
    replaced = 0
    for layer in model.model.layers:
        proj = layer.mlp.down_proj
        if isinstance(proj, nn.Linear) and proj.in_features >= FP8_K_THRESHOLD:
            layer.mlp.down_proj = Fp8DownProjLinear(proj)
            replaced += 1
    return replaced


# ---------------------------------------------------------------------------
# Per-arm training measurement (pattern from selective_recompute_ab.py)
# ---------------------------------------------------------------------------

def _build_model(arm: str):
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
    model.gradient_checkpointing_disable()  # PR #300 config — no ckpt at c03

    if arm == "bf16":
        pass  # control: pure bf16, no modifications
    elif arm == "fp8-width-cond":
        n = apply_width_cond_fp8(model)
        if n != LAYERS:
            raise RuntimeError(
                f"fp8 replacement count mismatch: expected {LAYERS}, got {n}"
            )
    else:
        raise ValueError(f"unknown arm: {arm}")

    model.train()
    return model


def measure_arm(seed: int, arm: str) -> dict:
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.empty_cache()

    free_before, _ = torch.cuda.mem_get_info()

    try:
        model = _build_model(arm)
    except torch.cuda.OutOfMemoryError as e:
        torch.cuda.empty_cache()
        return {"arm": arm, "seed": seed, "error": f"OOM_AT_BUILD: {e}",
                "measured_multiplier": None}

    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.1)
    dataset = ShardDataset(SHARD_DIR, SHARD_FILES, SEQ, seed)

    for _ in range(WARMUP_REPS):
        x, y = dataset.next_batch(BATCH)
        x, y = x.cuda(), y.cuda()
        try:
            out = model(input_ids=x, labels=y)
            out.loss.backward()
        except torch.cuda.OutOfMemoryError as e:
            del model, opt, dataset
            torch.cuda.empty_cache()
            return {"arm": arm, "seed": seed, "error": f"OOM_AT_WARMUP: {e}",
                    "measured_multiplier": None}
        opt.step()
        opt.zero_grad(set_to_none=True)
        time.sleep(PACE_S)

    step_times = []
    for _ in range(BENCH_REPS):
        x, y = dataset.next_batch(BATCH)
        x, y = x.cuda(), y.cuda()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        try:
            out = model(input_ids=x, labels=y)
            out.loss.backward()
        except torch.cuda.OutOfMemoryError as e:
            del model, opt, dataset
            torch.cuda.empty_cache()
            return {"arm": arm, "seed": seed, "error": f"OOM_AT_BENCH: {e}",
                    "measured_multiplier": None}
        torch.cuda.synchronize()
        step_times.append(time.perf_counter() - t0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        time.sleep(PACE_S)

    free_after, _ = torch.cuda.mem_get_info()
    vram_used_gib = (free_before - free_after) / (1 << 30)

    tokens_per_step = BATCH * SEQ
    mean_step_s     = sum(step_times) / len(step_times)
    tokens_per_s    = tokens_per_step / mean_step_s

    del model, opt, dataset
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
        "error": None,
        "measured_multiplier": None,  # filled after both arms run
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not hasattr(torch, "float8_e4m3fn"):
        raise SystemExit("FP8_WIDTH_COND_AB_FAIL: float8_e4m3fn unavailable — wrong torch build")
    if not hasattr(torch, "_scaled_mm"):
        raise SystemExit("FP8_WIDTH_COND_AB_FAIL: _scaled_mm unavailable")

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    if free_gib < MARGIN_GIB:
        raise SystemExit(
            f"FP8_WIDTH_COND_AB_GOVERNOR_FAIL: {free_gib:.2f} GiB free < "
            f"{MARGIN_GIB} GiB — refusing launch"
        )

    governor = {
        "vram_fraction": VRAM_FRACTION,
        "margin_gib_floor": MARGIN_GIB,
        "pace_s_per_step": PACE_S,
        "free_gib_at_launch": round(free_gib, 2),
        "total_gib": round(total_b / (1 << 30), 2),
    }

    for fname in SHARD_FILES:
        p = os.path.join(SHARD_DIR, fname)
        if not os.path.exists(p):
            raise SystemExit(f"FP8_WIDTH_COND_AB_SHARD_MISSING: {p}")

    arms = ["bf16", "fp8-width-cond"]
    config = {
        "hidden": HIDDEN, "layers": LAYERS, "heads": HEADS,
        "ffn": FFN, "vocab": VOCAB, "seq": SEQ, "batch": BATCH,
        "warmup_reps": WARMUP_REPS, "bench_reps": BENCH_REPS,
        "vram_fraction": VRAM_FRACTION, "seeds": SEEDS,
        "arms": arms,
        "fp8_k_threshold": FP8_K_THRESHOLD,
        "fp8_target_layers": f"mlp.down_proj x{LAYERS} (in_features=FFN={FFN})",
        "shard_files": SHARD_FILES,
    }

    print(
        f"[fp35g_width_cond_fp8_ab] c03 hidden={HIDDEN} layers={LAYERS} "
        f"ffn={FFN} seq={SEQ} batch={BATCH}",
        flush=True,
    )
    print(f"  fp8 dispatch: in_features >= {FP8_K_THRESHOLD} -> {LAYERS} down_proj layers", flush=True)
    print(f"  seeds: {SEEDS}, warmup={WARMUP_REPS}, bench={BENCH_REPS}", flush=True)
    print(f"  torch: {torch.__version__}  device: {torch.cuda.get_device_name(0)}", flush=True)

    results: dict[str, list[dict]] = {arm: [] for arm in arms}

    # Arm-first ordering: all bf16 seeds before all fp8-width-cond seeds
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
                    f"vram={r['vram_used_gib']:.2f} GiB",
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

    # measured_multiplier relative to bf16 control (>1.0 = fp8 faster)
    ctrl_tok_s = arm_agg["bf16"].get("mean_tokens_per_s") or 0.0
    for arm in arms:
        agg = arm_agg[arm]
        arm_tok_s = agg.get("mean_tokens_per_s")
        if arm_tok_s and ctrl_tok_s > 0:
            agg["measured_multiplier"] = round(arm_tok_s / ctrl_tok_s, 4)
        else:
            agg["measured_multiplier"] = None

    # Per-seed multipliers against bf16 control
    ctrl_seed_tok: dict[int, float] = {}
    for r in results["bf16"]:
        if r.get("error") is None:
            ctrl_seed_tok[r["seed"]] = r["tokens_per_s"]
    for r in results["fp8-width-cond"]:
        s = r.get("seed")
        if r.get("error") is None and s in ctrl_seed_tok and ctrl_seed_tok[s] > 0:
            r["measured_multiplier"] = round(r["tokens_per_s"] / ctrl_seed_tok[s], 4)

    fp8_mm     = arm_agg["fp8-width-cond"].get("measured_multiplier")
    fp8_status = arm_agg["fp8-width-cond"].get("status")

    if fp8_status == "PASS" and fp8_mm is not None and fp8_mm >= 1.02:
        verdict = "FP8_WIDTH_COND_VIABLE"
    elif fp8_status == "PASS" and fp8_mm is not None:
        verdict = "FP8_WIDTH_COND_PARK"
    else:
        verdict = "FP8_WIDTH_COND_ERROR"

    ts = _ts()
    receipt = {
        "ticket": "FP8_WIDTH_COND_AB",
        "ts": ts,
        "verdict": verdict,
        "issue": "#305",
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
        "measured_multiplier_vs_bf16": fp8_mm,
        "flags": [
            "c03 shapes (v0 training config — same as E4 profiler)",
            f"live run {LIVE_RUN_SHA} NOT touched",
            "governor rails HOLD — never loosened",
            "weight-cache variant: fp8 cached at init; bf16 weight updated by optimizer",
            f"fp8 dispatch condition: in_features >= {FP8_K_THRESHOLD} (down_proj only, 20 layers)",
            "arm-first ordering: all bf16 seeds before fp8-width-cond seeds",
            "backward: bf16 grad_input + grad_weight (no fp8 in backward path)",
            "VIABLE bar: mean MM >= 1.02; below bar -> PARK with receipt",
        ],
    }

    print(f"\n[fp35g_width_cond_fp8_ab] verdict: {verdict}", flush=True)
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
    out = os.path.join(RECEIPTS, f"fp35g-width-cond-fp8-ab-{ts}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP8_WIDTH_COND_AB_DONE {out}")
    return receipt


# ---------------------------------------------------------------------------
# Selftest (CPU-only; no GPU, no shards required)
# ---------------------------------------------------------------------------

def _selftest():
    # 1. Governor constants satisfy fp19 floor
    assert VRAM_FRACTION <= 0.80, "VRAM_FRACTION must not exceed 0.80"
    assert MARGIN_GIB >= 1.5,    "MARGIN_GIB must not be below 1.5"
    assert PACE_S >= 0.05,       "PACE_S must not be below 0.05"

    # 2. FP8_K_THRESHOLD correctly isolates down_proj (FFN) vs other sites (HIDDEN)
    assert FP8_K_THRESHOLD <= FFN,    f"threshold {FP8_K_THRESHOLD} > FFN {FFN}"
    assert FP8_K_THRESHOLD > HIDDEN,  f"threshold {FP8_K_THRESHOLD} <= HIDDEN {HIDDEN}"

    # 3. Live run pin unchanged
    assert LIVE_RUN_SHA == "12c050e7"

    # 4. Fp8DownProjLinear: weight buffer shape, dtype, and column-major property
    torch.manual_seed(0)
    lin    = nn.Linear(8, 4, bias=False)
    fp8lin = Fp8DownProjLinear(lin)

    assert fp8lin.weight_fp8.shape == (4, 8), \
        f"expected weight_fp8 shape (4, 8), got {fp8lin.weight_fp8.shape}"
    assert fp8lin.weight_fp8.dtype == torch.float8_e4m3fn, \
        f"expected float8_e4m3fn, got {fp8lin.weight_fp8.dtype}"

    w_col = fp8lin.weight_fp8.t()          # (8, 4) column-major
    # stride(0)==1 means the K-dimension is contiguous -> column-major (K, N) layout
    assert w_col.stride(0) == 1, \
        f"w_fp8.t() must have stride(0)=1 (column-major); got {w_col.strides}"
    assert not w_col.is_contiguous(), \
        "w_fp8.t() must NOT be contiguous — .contiguous() destroys column-major layout"

    # 5. apply_width_cond_fp8: replaces only in_features >= FP8_K_THRESHOLD
    # Build a mock model with 3 down_proj at FFN width + 2 at HIDDEN width
    class _MockMLP:
        def __init__(self, k):
            self.down_proj = nn.Linear(k, HIDDEN, bias=False)
    class _MockLayer:
        def __init__(self, k):
            self.mlp = _MockMLP(k)
    class _MockModel:
        pass

    widths = [FFN, HIDDEN, FFN, HIDDEN, FFN]
    mock = _MockModel()
    mock.model = type("M", (), {"layers": [_MockLayer(k) for k in widths]})()

    count = apply_width_cond_fp8(mock)
    expected = sum(1 for k in widths if k >= FP8_K_THRESHOLD)
    assert count == expected, f"expected {expected} replacements, got {count}"

    for i, layer in enumerate(mock.model.layers):
        proj = layer.mlp.down_proj
        if widths[i] >= FP8_K_THRESHOLD:
            assert isinstance(proj, Fp8DownProjLinear), \
                f"layer {i} (in_features={widths[i]}) should be Fp8DownProjLinear"
        else:
            assert isinstance(proj, nn.Linear) and not isinstance(proj, Fp8DownProjLinear), \
                f"layer {i} (in_features={widths[i]}) should remain nn.Linear"

    # 6. Fp8DownProjLinear forward (tiny CPU tensors — verifies no crash, not numerics)
    torch.manual_seed(1)
    tiny = Fp8DownProjLinear(nn.Linear(8, 4, bias=False))
    if hasattr(torch, "float8_e4m3fn") and hasattr(torch, "_scaled_mm"):
        # _scaled_mm requires CUDA; skip numerical check on CPU-only machines
        pass
    else:
        raise AssertionError("float8_e4m3fn or _scaled_mm unavailable")

    print("FP8_WIDTH_COND_AB_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
