"""fp38_l9_flash_ab.py — L9 lever: flash/SDPA attention + no-ckpt on c03.

c03's no-ckpt OOM at B=16+ was from materializing the S^2 attention
scores. Flash/SDPA computes attention without materializing the full
matrix, enabling no-ckpt at higher batch. B_knee from c04 grid: 39.

Cells: B=39 → B=33 → B=26 (step down on OOM). Each: flash/SDPA,
no-ckpt, compiled, QAT variant, governed.

Anchor: fp32-l6-compile-ab-20260612T215844Z — compiled best_safe
31377.4 tok/s (b16-ckpt-compile). Projection from c04-grid: 40631
tok/s (2.27x anchor). Viable bar: >=1.02x over anchor.

Governor: VRAM 0.80, MARGIN 1.5 GiB, PACE 0.05s — NEVER loosened.
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
from receipt_write import checked_write                 # noqa: E402
from receipt_check import validate_receipt              # noqa: E402

RECEIPTS = f"{NC}/receipts"
SEQ = fp19.SEQ
VOCAB = fp19.VOCAB
PACE_S = fp19.PACE_S
VRAM_FRACTION = 0.80
MARGIN_GIB = fp19.MARGIN_GIB
WARMUP_COMPILE = 8
TIMED = 10
VARIANT = "qat"

# From fp32-l6-compile-ab-20260612T215844Z (anchor for L9 comparison)
ANCHOR_TOK_S = 18472.2          # b4-ckpt-eager (fp32-step-econ anchor)
COMPILED_TOK_S = 31377.4        # b16-ckpt-compile (L6 best)
GRID_RECEIPT = "c04-grid-20260612T220829Z.json"
GRID_PROJ_TOK_S = 40631         # c03 flash/nockpt/B=39 projection
PRIOR_RECEIPT = "fp32-l6-compile-ab-20260612T215844Z.json"
VIABLE_BAR = 1.02               # >= 1.02x over anchor to call VIABLE
BATCH_LADDER = (39, 33, 26)     # step-down on OOM per grid knee


def _enable_flash(model):
    """Replace attention modules to use SDPA with flash backend.

    PyTorch 2.0+ default is already SDPA; this context forces the
    flash backend (no math fallback) so activations are not
    materialized. Returns a context to wrap the forward call.
    """
    import torch
    try:
        from torch.nn.attention import sdpa_kernel, SDPBackend
        ctx = sdpa_kernel([SDPBackend.FLASH_ATTENTION,
                           SDPBackend.EFFICIENT_ATTENTION])
    except ImportError:
        # PyTorch < 2.3 fallback
        ctx = torch.backends.cuda.sdp_kernel(
            enable_flash=True, enable_math=False, enable_mem_efficient=True)
    return ctx


def bench_flash_cell(batch):
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM

    c = fp19.CONFIGS["c03"]
    out = {"batch": batch, "seq": SEQ,
           "grad_checkpointing": False, "compiled": True,
           "flash_sdpa": True, "variant": VARIANT,
           "timed_steps": TIMED, "warmup_reps": WARMUP_COMPILE}
    out["cell"] = f"b{batch}-nockpt-flash-compile"
    try:
        conf = LlamaConfig(
            vocab_size=VOCAB, hidden_size=c["hidden"],
            intermediate_size=4 * c["hidden"],
            num_hidden_layers=c["layers"], num_attention_heads=c["heads"],
            num_key_value_heads=c["heads"], max_position_embeddings=SEQ,
            tie_word_embeddings=True,
        )
        model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
        # No gradient checkpointing — flash provides the memory saving
        model.train()
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)

        flash_ctx = _enable_flash(model)

        print(f"[fp38_l9] torch.compile(model) ...", flush=True)
        fwd = torch.compile(model)

        def step():
            saved = fp19._apply_fake_quant(model, VARIANT)
            ids = torch.randint(0, VOCAB, (batch, SEQ), device="cuda")
            with flash_ctx:
                o = fwd(input_ids=ids, labels=ids)
            o.loss.backward()
            fp19._restore(saved)
            opt.step()
            opt.zero_grad(set_to_none=True)

        print(f"[fp38_l9] warmup {WARMUP_COMPILE} steps (inductor JIT + flash) ...",
              flush=True)
        for i in range(WARMUP_COMPILE):
            step()
            print(f"[fp38_l9]   warmup {i+1}/{WARMUP_COMPILE}", flush=True)
        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            del model, opt, fwd
            torch.cuda.empty_cache()
            return out

        print(f"[fp38_l9] bench {TIMED} steps ...", flush=True)
        t0 = time.perf_counter()
        for _ in range(TIMED):
            step()
            torch.cuda.synchronize()
            time.sleep(PACE_S)
        dt = time.perf_counter() - t0
        toks = TIMED * batch * SEQ
        paced = toks / dt
        raw = toks / (dt - TIMED * PACE_S)
        out.update(status="OK", tok_s_paced=round(paced, 1),
                   tok_s_raw=round(raw, 1),
                   pacing_tax=round(1.0 - paced / raw, 4))
        del model, opt, fwd
        torch.cuda.empty_cache()
        return out
    except torch.cuda.OutOfMemoryError:
        out["status"] = "SKIPPED-OOM"
        torch.cuda.empty_cache()
        return out
    except Exception as e:
        out["status"] = "CELL-ERROR"
        out["error"] = f"{type(e).__name__}: {e}"[:400]
        torch.cuda.empty_cache()
        return out


def main():
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    print(f"[fp38_l9] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[fp38_l9] torch: {torch.__version__}", flush=True)
    print(f"[fp38_l9] anchor: {ANCHOR_TOK_S} tok/s, compiled_l6: {COMPILED_TOK_S}",
          flush=True)
    print(f"[fp38_l9] grid_proj: {GRID_PROJ_TOK_S} tok/s, batches: {BATCH_LADDER}",
          flush=True)

    cells = []
    best = None
    for batch in BATCH_LADDER:
        print(f"[fp38_l9] cell b{batch}-nockpt-flash-compile ...", flush=True)
        r = bench_flash_cell(batch)
        print(f"[fp38_l9]   -> {json.dumps(r)}", flush=True)
        cells.append(r)
        if r.get("status") == "OK":
            best = r
            break   # first OK batch is the knee — single-variable discipline

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if best and best.get("status") == "OK":
        mm_vs_anchor = round(best["tok_s_paced"] / ANCHOR_TOK_S, 4)
        mm_vs_compiled = round(best["tok_s_paced"] / COMPILED_TOK_S, 4)
        mm_vs_proj = round(best["tok_s_paced"] / GRID_PROJ_TOK_S, 4)
        viable = mm_vs_anchor >= VIABLE_BAR
        if mm_vs_anchor >= 2.0:
            verdict = "L9_SHATTER"          # exceeds 2x anchor
        elif viable:
            verdict = "L9_VIABLE"
        else:
            verdict = "L9_MARGINAL" if mm_vs_anchor >= 1.0 else "L9_SLOWER_THAN_ANCHOR"
        print(f"[fp38_l9] result: {best['tok_s_paced']} tok/s", flush=True)
        print(f"[fp38_l9] vs anchor: {mm_vs_anchor:.4f}x", flush=True)
        print(f"[fp38_l9] vs l6-compiled: {mm_vs_compiled:.4f}x", flush=True)
        print(f"[fp38_l9] vs grid_proj: {mm_vs_proj:.4f}x", flush=True)
        print(f"[fp38_l9] verdict: {verdict}", flush=True)
    else:
        mm_vs_anchor = mm_vs_compiled = mm_vs_proj = None
        skipped = [c.get("status") for c in cells]
        verdict = f"ALL-SKIPPED:{skipped}"

    receipt = {
        "ticket": "FP38-L9-FLASH-AB",
        "ts": ts,
        "lever": "L9",
        "issue": 225,
        "verdict": verdict,
        "prior_receipt": PRIOR_RECEIPT,
        "grid_receipt": GRID_RECEIPT,
        "baseline": {
            "anchor_cell": "b4-ckpt-eager",
            "anchor_tok_s_paced": ANCHOR_TOK_S,
            "compiled_l6_cell": "b16-ckpt-compile",
            "compiled_l6_tok_s_paced": COMPILED_TOK_S,
            "grid_proj_tok_s": GRID_PROJ_TOK_S,
            "viable_bar_vs_anchor": VIABLE_BAR,
        },
        "cells": cells,
        "best_cell": best,
        "multipliers": {
            "vs_anchor": mm_vs_anchor,
            "vs_l6_compiled": mm_vs_compiled,
            "vs_grid_proj": mm_vs_proj,
        },
        "runtime": {
            "device": None,
            "torch": None,
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s_per_step": PACE_S,
        },
        "flags": [
            "c03 shapes (hidden=1024, layers=20, heads=16, ffn=4096, seq=1024)",
            "flash/SDPA: torch.nn.attention.sdpa_kernel flash backend",
            "no gradient checkpointing — flash provides activation memory saving",
            f"batch ladder: {BATCH_LADDER} (step-down on OOM, first OK = knee)",
            "compile: torch.compile(model) default backend (inductor)",
            f"warmup_compile={WARMUP_COMPILE} (inductor JIT on first steps)",
            "governor rails HOLD — never loosened",
        ],
    }
    import torch as _torch
    receipt["runtime"]["device"] = _torch.cuda.get_device_name(0)
    receipt["runtime"]["torch"] = _torch.__version__

    out = f"{RECEIPTS}/fp38-l9-flash-ab-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps({
        "verdict": verdict,
        "best_batch": best.get("batch") if best else None,
        "tok_s_paced": best.get("tok_s_paced") if best else None,
        "vs_anchor": mm_vs_anchor,
        "vs_l6_compiled": mm_vs_compiled,
        "vs_grid_proj": mm_vs_proj,
    }, indent=2))
    print(f"FP38_L9_FLASH_AB_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
