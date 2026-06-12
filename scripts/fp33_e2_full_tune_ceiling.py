"""fp33_e2_full_tune_ceiling.py — E2 full-tune ceiling OOM probe on 24GB.

E2 leg of fp-33 (fp33-e2b-surpass-envelope.md). Measures the maximum
batch size achievable for full fine-tuning of Qwen2.5-Coder-3B (2.274B,
the only on-disk viable open base from E1) on the 4090 (24GB) with:
  - bf16 weights
  - gradient checkpointing
  - paged_adamw_8bit optimizer (bitsandbytes); falls back to AdamW if bnb unavailable
  - seq=1024 (ember training seq length)

OOM probe: binary-search from batch=[1,2,4,8]. Records max fitting batch,
VRAM at that batch, and tok/s throughput (cuda.Event timed).

Governor: VRAM_FRACTION=0.80, MARGIN_GIB=1.5, PACE_S=0.05.

Receipt: receipts/fp33-e2-full-tune-ceiling-<ts>.json
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
RECEIPTS = f"{NC}/receipts"

# Qwen2.5-Coder-3B-Instruct snapshot (E1 finding)
MODEL_PATH = (
    "/mnt/c/Users/Admin/.cache/huggingface/hub/"
    "models--Qwen--Qwen2.5-Coder-3B-Instruct/snapshots/"
    "488639f1ff808d1d3d0ba301aef8c11461451ec5"
)
MODEL_ID = "Qwen/Qwen2.5-Coder-3B-Instruct"

SEQ      = 1024
PROBE_BATCHES = [1, 2, 4, 8]

VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05

WARMUP = 2
TIMED  = 8


def _make_optimizer(model, use_bnb: bool):
    if use_bnb:
        import bitsandbytes as bnb
        return bnb.optim.PagedAdamW8bit(model.parameters(), lr=1e-4), "paged_adamw_8bit"
    return __import__("torch").optim.AdamW(model.parameters(), lr=1e-4), "adamw_bf16"


def _try_batch(model, opt, batch: int, vocab: int, seq: int, torch) -> dict | str:
    """Attempt warmup + timed steps at given batch. Returns result dict or error string."""
    try:
        for _ in range(WARMUP):
            ids = torch.randint(0, vocab, (batch, seq), device="cuda")
            out = model(input_ids=ids, labels=ids)
            out.loss.backward()
            opt.step()
            opt.zero_grad(set_to_none=True)
            torch.cuda.synchronize()
            time.sleep(PACE_S)

        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        if free_gib < MARGIN_GIB:
            return f"MARGIN_VIOLATED:{free_gib:.2f}GiB"

        step_ms_list = []
        E = lambda: torch.cuda.Event(enable_timing=True)
        for _ in range(TIMED):
            ids = torch.randint(0, vocab, (batch, seq), device="cuda")
            e0, e1 = E(), E()
            e0.record()
            out = model(input_ids=ids, labels=ids)
            out.loss.backward()
            opt.step()
            opt.zero_grad(set_to_none=True)
            e1.record()
            torch.cuda.synchronize()
            step_ms_list.append(e0.elapsed_time(e1))
            time.sleep(PACE_S)

        avg_ms = sum(step_ms_list) / len(step_ms_list)
        tok_s = (batch * seq) / (avg_ms / 1000)
        allocated_gib = torch.cuda.memory_allocated() / (1 << 30)
        reserved_gib  = torch.cuda.memory_reserved()  / (1 << 30)
        return {
            "batch": batch,
            "avg_step_ms": round(avg_ms, 2),
            "tok_s": round(tok_s, 1),
            "allocated_gib": round(allocated_gib, 2),
            "reserved_gib":  round(reserved_gib, 2),
            "free_gib_post_warmup": round(free_gib, 2),
            "step_ms_list": [round(m, 2) for m in step_ms_list],
        }
    except torch.cuda.OutOfMemoryError as e:
        return f"OOM:{e}"
    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            return f"OOM:{e}"
        return f"RuntimeError:{e}"


def main():
    import torch
    from transformers import AutoConfig, AutoModelForCausalLM

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    # Diagnose VRAM before loading
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib  = free_b  / (1 << 30)
    total_gib = total_b / (1 << 30)
    print(f"[E2] VRAM pre-load: {free_gib:.2f} GiB free / {total_gib:.2f} GiB total", flush=True)
    if free_gib < 5.0:
        raise RuntimeError(f"Insufficient VRAM for E2: only {free_gib:.2f} GiB free, need >=5 GiB for weights")

    # Check bitsandbytes
    try:
        import bitsandbytes as bnb
        bnb_version = bnb.__version__
        use_bnb = True
    except ImportError:
        bnb_version = None
        use_bnb = False
    print(f"[E2] bitsandbytes: {'available v' + bnb_version if use_bnb else 'NOT available — fallback to AdamW'}", flush=True)

    print(f"[E2] loading {MODEL_ID} from local cache ...", flush=True)
    t_load0 = time.perf_counter()
    # Load to CPU first (bulk safetensors read), then move to CUDA.
    # device_map="cuda" with low_cpu_mem_usage materializes params one-at-a-time
    # over NTFS/WSL2 — extremely slow (~15 min). CPU-load then .cuda() is much faster.
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        dtype=torch.bfloat16,
        trust_remote_code=False,
    )
    model = model.cuda()
    model.gradient_checkpointing_enable()
    model.train()
    t_load = time.perf_counter() - t_load0

    cfg = AutoConfig.from_pretrained(MODEL_PATH, trust_remote_code=False)
    vocab = cfg.vocab_size
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[E2] model loaded in {t_load:.1f}s, {n_params/1e9:.3f}B params, vocab={vocab}", flush=True)

    opt, opt_name = _make_optimizer(model, use_bnb)
    print(f"[E2] optimizer: {opt_name}", flush=True)

    probe_results = []
    max_ok_batch = 0
    max_ok_result = None

    for batch in PROBE_BATCHES:
        print(f"[E2] probing batch={batch} ...", flush=True)
        torch.cuda.reset_peak_memory_stats()
        result = _try_batch(model, opt, batch, vocab, SEQ, torch)
        if isinstance(result, str):
            print(f"  batch={batch}: {result}", flush=True)
            probe_results.append({"batch": batch, "status": result})
            if result.startswith("OOM"):
                break  # No point trying larger batches
        else:
            print(f"  batch={batch}: {result['tok_s']:.0f} tok/s, {result['allocated_gib']:.2f} GiB alloc", flush=True)
            probe_results.append({"batch": batch, "status": "OK", **result})
            max_ok_batch = batch
            max_ok_result = result
        torch.cuda.empty_cache()
        time.sleep(0.5)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if max_ok_result:
        verdict = f"FITS_BATCH_{max_ok_batch}"
        verdict_detail = (f"Full fine-tune of {MODEL_ID} ({n_params/1e9:.3f}B) "
                          f"fits at batch={max_ok_batch}, seq={SEQ} "
                          f"with {opt_name} + grad_ckpt. "
                          f"Throughput: {max_ok_result['tok_s']:.0f} tok/s.")
    else:
        verdict = "OOM_BATCH_1"
        verdict_detail = f"Full fine-tune of {MODEL_ID} OOMs at batch=1, seq={SEQ}."

    receipt = {
        "ticket": "FP33-E2-FULL-TUNE-CEILING",
        "ts": ts,
        "model": {
            "id": MODEL_ID,
            "path": MODEL_PATH,
            "n_params": n_params,
            "params_b": round(n_params / 1e9, 3),
            "vocab": vocab,
        },
        "config": {
            "seq": SEQ,
            "optimizer": opt_name,
            "dtype": "bfloat16",
            "grad_checkpointing": True,
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s_per_step": PACE_S,
        },
        "versions": {
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "bitsandbytes": bnb_version,
        },
        "probe_results": probe_results,
        "max_ok_batch": max_ok_batch,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "method": "cuda.Event step timing (CUPTI-free), OOM boundary by ascending batch probe",
        "flags": [
            "bf16 weights + gradient checkpointing ON",
            f"optimizer: {opt_name}",
            "synthetic batches — no dataloader",
            "binary probe: stop at first OOM",
            "live run 12c050e7 NOT touched",
        ],
    }

    del model, opt
    torch.cuda.empty_cache()

    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/fp33-e2-full-tune-ceiling-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP33_E2_FULL_TUNE_CEILING_DONE {out}")
    return receipt


def _selftest():
    # probe result logic
    results = [
        {"batch": 1, "status": "OK", "tok_s": 800},
        {"batch": 2, "status": "OK", "tok_s": 1400},
        {"batch": 4, "status": "OOM:out of memory"},
    ]
    ok = [r for r in results if r["status"] == "OK"]
    assert ok[-1]["batch"] == 2
    assert ok[-1]["tok_s"] == 1400
    print("FP33_E2_FULL_TUNE_CEILING_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
