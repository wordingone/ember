"""fp33_e4_profiler.py — cuda.Event wall-clock decomposition for v0-r1s1.

E4 leg of fp-33 (e2b-surpass objective, fp33-e2b-surpass-envelope.md).
Measures wall-clock share of each major compute category in a governed
v0-r1s1 training step using cuda.Event timing (CUPTI-free):
  - forward   : full forward pass (attention + MLP + lm-head)
  - backward  : full backward pass (incl gradient checkpointing recompute)
  - optimizer : AdamW parameter update
  - qat       : fake-quant weight transforms (STE pre/post per step)
  - governor  : mandatory inter-step sleep (wall cost, not GPU cost)

torch.profiler + CUPTI is skipped — WSL2 / torch 2.6.0+cu124 CUPTI is
unreliable for per-kernel data. cuda.Event timing measures elapsed device
time for each phase accurately without CUPTI. Phase boundaries are
demarcated by explicit cuda.synchronize() pairs.

Config: c03-qat — hidden=1024, 20 layers, 16 heads, batch=4, seq=1024,
vocab=32000 — identical to the live v0-r1s1 run (12c050e7).
Governor: VRAM 0.80, margin 1.5 GiB, PACE_S 0.05 (fp19_bench floor).

DO NOT MODIFY the live run (12c050e7). This is a standalone short segment.

Receipt: runs/v0-r1s1/receipts/fp33-e4-profiler-<ts>.json
Run via daemon (train window). --selftest is pure-logic, no GPU.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RECEIPT_DIR = "/mnt/b/M/avir/eli/state/ember-eng/runs/v0-r1s1/receipts"

VOCAB    = 32000
SEQ      = 1024
BATCH    = 4
HIDDEN   = 1024
LAYERS   = 20
HEADS    = 16

VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05   # governor floor — never loosened

WARMUP   = 3
TIMED    = 15   # steps with cuda.Event timing


def _apply_fake_quant(model, torch):
    saved = []
    for m in model.modules():
        if isinstance(m, torch.nn.Linear):
            w = m.weight.data
            saved.append((m, w.clone()))
            s = w.abs().amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.0
            m.weight.data = (w / s).round().clamp(-127, 127) * s
    return saved


def _restore(saved):
    for m, w in saved:
        m.weight.data = w


def run_profile():
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    conf = LlamaConfig(
        vocab_size=VOCAB, hidden_size=HIDDEN,
        intermediate_size=4 * HIDDEN,
        num_hidden_layers=LAYERS, num_attention_heads=HEADS,
        num_key_value_heads=HEADS, max_position_embeddings=SEQ,
        tie_word_embeddings=True,
    )
    model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
    model.gradient_checkpointing_enable()
    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
    n_params = sum(p.numel() for p in model.parameters())

    def plain_step():
        saved = _apply_fake_quant(model, torch)
        ids = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
        out = model(input_ids=ids, labels=ids)
        out.loss.backward()
        _restore(saved)
        opt.step()
        opt.zero_grad(set_to_none=True)

    # Warmup
    print(f"[E4] warming up {WARMUP} steps ...", flush=True)
    for _ in range(WARMUP):
        plain_step()
        torch.cuda.synchronize()
        time.sleep(PACE_S)

    free_b, _ = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    assert free_gib >= MARGIN_GIB, \
        f"VRAM margin violated: {free_gib:.2f} GiB < {MARGIN_GIB}"
    print(f"[E4] VRAM margin OK: {free_gib:.2f} GiB free", flush=True)

    # Phase timing accumulators (cuda.Event elapsed in ms)
    phase_ms = {"qat_fwd": 0.0, "forward": 0.0, "backward": 0.0,
                "qat_bwd_restore": 0.0, "optimizer": 0.0}

    def E():
        return torch.cuda.Event(enable_timing=True)

    print(f"[E4] timing {TIMED} steps with cuda.Event ...", flush=True)
    t_wall_0 = time.perf_counter()
    for _ in range(TIMED):
        ids = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")

        e0, e1 = E(), E()
        e0.record()
        saved = _apply_fake_quant(model, torch)
        e1.record(); torch.cuda.synchronize()
        phase_ms["qat_fwd"] += e0.elapsed_time(e1)

        e0, e1 = E(), E()
        e0.record()
        out = model(input_ids=ids, labels=ids)
        e1.record(); torch.cuda.synchronize()
        phase_ms["forward"] += e0.elapsed_time(e1)

        e0, e1 = E(), E()
        e0.record()
        out.loss.backward()
        e1.record(); torch.cuda.synchronize()
        phase_ms["backward"] += e0.elapsed_time(e1)

        e0, e1 = E(), E()
        e0.record()
        _restore(saved)
        e1.record(); torch.cuda.synchronize()
        phase_ms["qat_bwd_restore"] += e0.elapsed_time(e1)

        e0, e1 = E(), E()
        e0.record()
        opt.step()
        opt.zero_grad(set_to_none=True)
        e1.record(); torch.cuda.synchronize()
        phase_ms["optimizer"] += e0.elapsed_time(e1)

        time.sleep(PACE_S)

    t_wall_total = time.perf_counter() - t_wall_0

    # Averages per step
    avg = {k: round(v / TIMED, 2) for k, v in phase_ms.items()}
    total_gpu_ms = sum(phase_ms.values())
    shares = {k: round(v / total_gpu_ms * 100, 1) if total_gpu_ms > 0 else 0.0
              for k, v in phase_ms.items()}

    t_governor_s = PACE_S * TIMED
    governor_wall_pct = round(t_governor_s / t_wall_total * 100, 1)
    toks_total = TIMED * BATCH * SEQ
    tok_s_paced = toks_total / t_wall_total

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP33-E4-PROFILER",
        "ts": ts,
        "method": "cuda.Event per-phase timing (CUPTI-free, WSL2 safe)",
        "torch_version": torch.__version__,
        "config": {
            "model": "ember-v0 c03-qat",
            "hidden": HIDDEN, "layers": LAYERS, "heads": HEADS,
            "batch": BATCH, "seq": SEQ, "vocab": VOCAB,
            "n_params": n_params,
            "variant": "qat",
            "grad_checkpointing": True,
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s_per_step": PACE_S,
        },
        "run": {
            "warmup_steps": WARMUP,
            "timed_steps": TIMED,
            "free_vram_gib_post_warmup": round(free_gib, 2),
        },
        "wall_clock": {
            "total_s": round(t_wall_total, 4),
            "governor_sleep_s": round(t_governor_s, 4),
            "governor_wall_pct": governor_wall_pct,
            "tok_s_paced": round(tok_s_paced, 1),
        },
        "phase_avg_ms_per_step": avg,
        "phase_gpu_shares_pct": shares,
        "phase_gpu_total_ms": round(total_gpu_ms, 2),
        "flags": [
            "cuda.Event timing: each phase demarcated by explicit synchronize()",
            "governor sleep measured from wall time (CPU-side, not CUDA)",
            "synthetic random batches — no dataloader (share = 0 by design)",
            "gradient checkpointing ON — backward includes activation recompute",
            "live run 12c050e7 NOT touched",
        ],
    }

    os.makedirs(RECEIPT_DIR, exist_ok=True)
    out = f"{RECEIPT_DIR}/fp33-e4-profiler-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP33_E4_PROFILER_DONE {out}")

    del model, opt
    torch.cuda.empty_cache()
    return receipt


def _selftest():
    # arithmetic sanity (no GPU)
    phases = {"a": 100.0, "b": 300.0, "c": 100.0}
    total = sum(phases.values())
    shares = {k: round(v / total * 100, 1) for k, v in phases.items()}
    assert shares["b"] == 60.0, shares
    assert abs(sum(shares.values()) - 100.0) < 0.2
    print("FP33_E4_PROFILER_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        run_profile()
