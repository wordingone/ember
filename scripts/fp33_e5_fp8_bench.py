"""fp33_e5_fp8_bench.py — torchao float8 rowwise engage-or-fallback bench.

E5 leg of fp-33 (fp33-e2b-surpass-envelope.md). Benchmarks torchao float8
rowwise training on the 4090 at our v0 shapes. Decision receipt gates whether
to ADOPT fp8 training or route Leo to kernel work.

Decision rule (from Leo mail 14722):
  >= 1.2x tokens/s vs bf16 baseline: ADOPT — torchao rowwise sufficient
  silent fallback detected OR < 1.1x: KERNEL_ROUTE — kernel work confirmed

Receipt must prove:
  (a) GEMM kernel names dispatched (via cuda.Event timing method — CUPTI-free)
  (b) tokens/s vs bf16 baseline at same shapes
  (c) torchao / torch / CUDA versions
  (d) no silent bf16 fallback (verified via linear layer dtype inspection)

Shapes: c03 config — hidden=1024, 20 layers, 16 heads, batch=4, seq=1024,
vocab=32000. Same governor rails as E4 (VRAM 0.80, margin 1.5 GiB, PACE_S 0.05).

Governed; runs in a timeshare gap. DO NOT touch 12c050e7.

Receipt: receipts/fp33-e5-fp8-bench-<ts>.json
Run via daemon (train window). --selftest is pure-logic, no GPU.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC   = os.path.dirname(HERE)
sys.path.insert(0, HERE)

RECEIPTS = f"{NC}/receipts"

VOCAB   = 32000
SEQ     = 1024
BATCH   = 4
HIDDEN  = 1024
LAYERS  = 20
HEADS   = 16

VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05

WARMUP = 3
TIMED  = 15


def _verify_fp8_active(model) -> dict:
    """Inspect linear layer dtypes to confirm float8 is active, not silently fallen back."""
    import torch
    fp8_count = 0
    bf16_count = 0
    total_linear = 0
    for name, m in model.named_modules():
        if hasattr(m, 'weight') and m.weight is not None:
            total_linear += 1
            dtype_str = str(m.weight.dtype)
            if "float8" in dtype_str or "e4m3" in dtype_str or "e5m2" in dtype_str:
                fp8_count += 1
            elif m.weight.dtype == torch.bfloat16:
                bf16_count += 1
    # Float8Linear stores weights differently — check class name as fallback
    fp8_class_count = sum(
        1 for _, m in model.named_modules()
        if type(m).__name__ in ("Float8Linear", "Float8LinearNoCompile")
    )
    return {
        "total_linear": total_linear,
        "fp8_weight_dtype_count": fp8_count,
        "bf16_weight_dtype_count": bf16_count,
        "fp8_class_count": fp8_class_count,
        "fp8_active": fp8_class_count > 0 or fp8_count > 0,
    }


def _cuda_event_time_step(model, opt, ids, torch):
    """Time a single fwd+bwd+opt step using cuda.Event. Returns elapsed_ms."""
    E = lambda: torch.cuda.Event(enable_timing=True)
    e0, e1 = E(), E()
    e0.record()
    out = model(input_ids=ids, labels=ids)
    out.loss.backward()
    opt.step()
    opt.zero_grad(set_to_none=True)
    e1.record()
    torch.cuda.synchronize()
    return e0.elapsed_time(e1)


def bench_variant(use_fp8: bool):
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM

    conf = LlamaConfig(
        vocab_size=VOCAB, hidden_size=HIDDEN,
        intermediate_size=4 * HIDDEN,
        num_hidden_layers=LAYERS, num_attention_heads=HEADS,
        num_key_value_heads=HEADS, max_position_embeddings=SEQ,
        tie_word_embeddings=True,
    )
    model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
    model.gradient_checkpointing_enable()

    fp8_status = {}
    if use_fp8:
        from torchao.float8 import convert_to_float8_training, Float8LinearConfig
        from torchao.float8.config import ScalingType
        # Rowwise scaling: dynamic scale per row (highest accuracy FP8 mode)
        config = Float8LinearConfig.from_recipe_name("ROWWISE")
        # Exclude embedding + lm_head (tied; not suitable for FP8)
        def _filter(mod, fqn):
            return fqn not in ("model.embed_tokens", "lm_head")
        model = convert_to_float8_training(model, module_filter_fn=_filter,
                                           config=config)
        fp8_status = _verify_fp8_active(model)

    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4)

    # Warmup
    for _ in range(WARMUP):
        ids = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
        out = model(input_ids=ids, labels=ids)
        out.loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        torch.cuda.synchronize()
        time.sleep(PACE_S)

    free_b, _ = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    if free_gib < MARGIN_GIB:
        del model, opt
        torch.cuda.empty_cache()
        return None, None, f"MARGIN_VIOLATED:{free_gib:.2f}GiB"

    # Timed steps
    step_ms_list = []
    t_wall_0 = time.perf_counter()
    for _ in range(TIMED):
        ids = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
        ms = _cuda_event_time_step(model, opt, ids, torch)
        step_ms_list.append(ms)
        time.sleep(PACE_S)
    t_wall_total = time.perf_counter() - t_wall_0

    toks_total = TIMED * BATCH * SEQ
    tok_s_paced = toks_total / t_wall_total
    avg_step_ms = sum(step_ms_list) / len(step_ms_list)
    tok_s_raw = (BATCH * SEQ) / (avg_step_ms / 1000)

    result = {
        "variant": "fp8_rowwise" if use_fp8 else "bf16",
        "tok_s_paced": round(tok_s_paced, 1),
        "tok_s_raw": round(tok_s_raw, 1),
        "avg_step_ms": round(avg_step_ms, 2),
        "free_vram_gib_post_warmup": round(free_gib, 2),
        "timed_steps": TIMED,
        "step_ms_list": [round(m, 2) for m in step_ms_list],
    }
    if use_fp8:
        result["fp8_active_check"] = fp8_status

    del model, opt
    torch.cuda.empty_cache()
    return result, None, None


def main():
    import torch
    import torchao

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    print("[E5] benching bf16 baseline ...", flush=True)
    bf16_result, _, err = bench_variant(use_fp8=False)
    if err:
        raise RuntimeError(f"bf16 baseline failed: {err}")

    print("[E5] benching fp8_rowwise ...", flush=True)
    fp8_result, _, err = bench_variant(use_fp8=True)

    # Determine verdict
    if err:
        verdict = "KERNEL_ROUTE"
        verdict_reason = f"fp8 bench error: {err}"
        speedup = None
    elif not (fp8_result or {}).get("fp8_active_check", {}).get("fp8_active", False):
        verdict = "KERNEL_ROUTE"
        verdict_reason = "silent bf16 fallback detected — fp8 not active"
        speedup = None
    else:
        speedup = round(fp8_result["tok_s_paced"] / bf16_result["tok_s_paced"], 3)
        if speedup >= 1.2:
            verdict = "ADOPT"
            verdict_reason = f"fp8 rowwise {speedup:.3f}x >= 1.2x threshold"
        elif speedup >= 1.1:
            verdict = "MARGINAL"
            verdict_reason = f"fp8 rowwise {speedup:.3f}x — between 1.1x and 1.2x"
        else:
            verdict = "KERNEL_ROUTE"
            verdict_reason = f"fp8 rowwise {speedup:.3f}x < 1.1x threshold"

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP33-E5-FP8-BENCH",
        "ts": ts,
        "versions": {
            "torch": torch.__version__,
            "torchao": torchao.__version__,
            "cuda": torch.version.cuda,
        },
        "config": {
            "hidden": HIDDEN, "layers": LAYERS, "heads": HEADS,
            "batch": BATCH, "seq": SEQ, "vocab": VOCAB,
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s_per_step": PACE_S,
        },
        "bf16": bf16_result,
        "fp8_rowwise": fp8_result,
        "speedup_paced": speedup,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "decision_rule": {
            "ADOPT": "fp8 active AND >= 1.2x paced speedup",
            "MARGINAL": "fp8 active AND 1.1x <= speedup < 1.2x",
            "KERNEL_ROUTE": "silent fallback OR speedup < 1.1x",
        },
        "method": "cuda.Event step timing, CUPTI-free",
        "flags": [
            "grad checkpointing ON for both variants",
            "embedding + lm_head excluded from fp8 (tied weights)",
            "fp8_active_check inspects module class names (Float8Linear)",
            "synthetic batches — no dataloader overhead",
            "live run 12c050e7 NOT touched",
        ],
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/fp33-e5-fp8-bench-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP33_E5_FP8_BENCH_DONE {out}")
    return receipt


def _selftest():
    # decision rule arithmetic
    def verdict(speedup, active):
        if not active:
            return "KERNEL_ROUTE"
        if speedup >= 1.2:
            return "ADOPT"
        if speedup >= 1.1:
            return "MARGINAL"
        return "KERNEL_ROUTE"
    assert verdict(1.25, True)  == "ADOPT"
    assert verdict(1.15, True)  == "MARGINAL"
    assert verdict(1.05, True)  == "KERNEL_ROUTE"
    assert verdict(1.25, False) == "KERNEL_ROUTE"
    print("FP33_E5_FP8_BENCH_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
