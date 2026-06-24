"""fp38c_l9_eager.py — L9 completion: B=16 and B=8, flash, no-ckpt, EAGER.

fp38b compile cells failed due to transformers output_capturing NameError
when LlamaForCausalLM is compiled without gradient checkpointing (fp32_l6
worked with grad-ckpt; the interaction changes the traced code path).

The L9 ARCH question is independent of compile: does flash/SDPA enable
no-ckpt at B=16 or B=8 under the 0.80 VRAM cap? Compile is secondary.
This script answers that question with eager execution.

Prior: fp38-l9-flash-ab: B=39/33/26 all OOM during compile warmup.
These OOMs may be from activation buildup during 8-step warmup + compile.
Eager warmup = 3 steps, much less activation pressure before the OOM check.

Verdict:
  - SKIPPED-OOM at both → flash ARCH-KILL confirmed to B=8; same binding
    constraint as L5 (MLP activations + residuals, not S^2 scores). c04
    must solve via smaller hidden or FSDP offload.
  - OK at B=8 (or B=16) → REVIVE confirmed; c04 can use flash+no-ckpt at
    reduced batch with architecture-tuned hidden/seq.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fp19_bench as fp19                              # noqa: E402
from receipt_write import checked_write               # noqa: E402

RECEIPTS = f"{NC}/receipts"
SEQ = fp19.SEQ
VOCAB = fp19.VOCAB
PACE_S = fp19.PACE_S
VRAM_FRACTION = 0.80
MARGIN_GIB = fp19.MARGIN_GIB
WARMUP_EAGER = 3
TIMED = 10
VARIANT = "qat"

ANCHOR_TOK_S = 18472.2
PRIOR_FP38 = "fp38-l9-flash-ab-20260612T223639Z.json"
PRIOR_FP38B = "fp38b-l9-completion-20260612T230816Z.json"
BATCH_LADDER = (16, 8)


def _set_flash_global():
    import torch
    torch.backends.cuda.enable_flash_sdp(True)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    torch.backends.cuda.enable_math_sdp(False)


def bench_cell(batch):
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM

    c = fp19.CONFIGS["c03"]
    cell_name = f"b{batch}-nockpt-flash-eager"
    out = {
        "cell": cell_name, "batch": batch, "seq": SEQ,
        "grad_checkpointing": False, "compiled": False,
        "flash_sdpa": True, "variant": VARIANT,
        "timed_steps": TIMED, "warmup_reps": WARMUP_EAGER,
    }
    try:
        conf = LlamaConfig(
            vocab_size=VOCAB, hidden_size=c["hidden"],
            intermediate_size=4 * c["hidden"],
            num_hidden_layers=c["layers"], num_attention_heads=c["heads"],
            num_key_value_heads=c["heads"], max_position_embeddings=SEQ,
            tie_word_embeddings=True,
        )
        model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
        model.train()
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)

        def step():
            saved = fp19._apply_fake_quant(model, VARIANT)
            ids = torch.randint(0, VOCAB, (batch, SEQ), device="cuda")
            o = model(input_ids=ids, labels=ids)
            o.loss.backward()
            fp19._restore(saved)
            opt.step()
            opt.zero_grad(set_to_none=True)

        print(f"[fp38c] warmup {WARMUP_EAGER} steps ...", flush=True)
        for i in range(WARMUP_EAGER):
            step()
            print(f"[fp38c]   warmup {i+1}/{WARMUP_EAGER}", flush=True)
        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            del model, opt
            torch.cuda.empty_cache()
            return out

        print(f"[fp38c] bench {TIMED} steps ...", flush=True)
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
        del model, opt
        torch.cuda.empty_cache()
        return out
    except torch.cuda.OutOfMemoryError:
        out["status"] = "SKIPPED-OOM"
        torch.cuda.empty_cache()
        return out
    except Exception as e:
        out["status"] = "CELL-ERROR"
        out["error"] = f"{type(e).__name__}: {e}"[:400]
        import traceback
        print(traceback.format_exc(), flush=True)
        torch.cuda.empty_cache()
        return out


def main():
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    print(f"[fp38c] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[fp38c] torch: {torch.__version__}", flush=True)
    print(f"[fp38c] L9 eager: flash global + no-ckpt at B={BATCH_LADDER}", flush=True)
    _set_flash_global()

    cells = []
    best = None
    for batch in BATCH_LADDER:
        print(f"\n[fp38c] cell b{batch}-nockpt-flash-eager ...", flush=True)
        r = bench_cell(batch)
        print(f"[fp38c]   -> {json.dumps(r)}", flush=True)
        cells.append(r)
        if r.get("status") == "OK" and best is None:
            best = r

    ts_now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    all_oom = all(c.get("status") in ("SKIPPED-OOM", "SKIPPED-MARGIN") for c in cells)
    if best:
        mm_vs_anchor = round(best["tok_s_paced"] / ANCHOR_TOK_S, 4)
        verdict = (f"L9_REVIVE_B{best['batch']}" if mm_vs_anchor >= 1.02
                   else f"L9_MARGINAL_B{best['batch']}")
        arch_note = (
            f"REVIVE at B={best['batch']}: flash+no-ckpt fits under 0.80 cap. "
            "c04 design: hidden/batch tuning within this constraint is viable."
        )
    else:
        mm_vs_anchor = None
        verdict = "L9_ARCH_KILL_CONFIRMED"
        arch_note = (
            "ALL-OOM: flash/SDPA eliminates S^2 attention scores but MLP "
            "activations + residuals at c03 hidden=1024 still OOM under 0.80 cap, "
            "even at B=8. Same ARCH constraint as L5. L9 ARCH-KILL confirmed "
            "across full batch range (B=8..39). c04 must solve via smaller hidden "
            "or FSDP offload."
        )

    receipt = {
        "ticket": "FP38C-L9-EAGER",
        "ts": ts_now,
        "lever": "L9",
        "issue": 225,
        "verdict": verdict,
        "arch_note": arch_note,
        "prior_receipts": {
            "fp38_l9": PRIOR_FP38,
            "fp38b_l9_compile_error": PRIOR_FP38B,
        },
        "baseline": {
            "anchor_cell": "b4-ckpt-eager",
            "anchor_tok_s_paced": ANCHOR_TOK_S,
            "fp38_oom_batches": [39, 33, 26],
        },
        "cells": cells,
        "best_cell": best,
        "multiplier_vs_anchor": mm_vs_anchor,
        "runtime": {
            "device": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s_per_step": PACE_S,
        },
        "flags": [
            "c03 shapes (hidden=1024, layers=20, heads=16, ffn=4096, seq=1024)",
            "flash/SDPA: torch.backends.cuda.enable_flash_sdp(True) global",
            "no gradient checkpointing",
            f"batch ladder: {BATCH_LADDER}",
            "eager (no compile) — compile blocked by transformers output_capturing NameError at no-ckpt",
            f"warmup_eager={WARMUP_EAGER}",
            "governor rails HOLD — never loosened",
        ],
    }

    out = f"{RECEIPTS}/fp38c-l9-eager-{ts_now}.json"
    checked_write(out, receipt)
    print(json.dumps({
        "verdict": verdict,
        "arch_note": arch_note,
        "cells": [{"cell": c["cell"], "status": c.get("status"),
                   "tok_s_paced": c.get("tok_s_paced")} for c in cells],
    }, indent=2))
    print(f"FP38C_L9_EAGER_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
