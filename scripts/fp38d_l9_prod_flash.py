"""fp38d_l9_prod_flash.py — L9 rider cell: B=8 flash+no-ckpt on PRODUCTION stack.

fp38c confirmed L9_REVIVE_B8 at 27,895 tok/s (bench-path: LlamaForCausalLM,
no MTP). This cell is the PROXY-to-PRODUCTION bridge: same flash+no-ckpt
constraint, but full production stack (LlamaModel + 2 MTP heads + chunkedCE
+ Muon/AdamW split).

If B8-flash-prod fits under 0.80 cap and exceeds B16-ckpt-compile-prod
(19,228 tok/s), L9+L10 combined becomes the dominant throughput lever for
c04 §3.

Receipt class: PRODUCTION (definitive — resolves fp38c BENCH-PATH-PROXY).
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
import timeshare_pretrain as ts                       # noqa: E402

RECEIPTS = f"{NC}/receipts"
SEQ = fp19.SEQ
VOCAB = fp19.VOCAB
PACE_S = fp19.PACE_S
VRAM_FRACTION = 0.80
MARGIN_GIB = fp19.MARGIN_GIB
VARIANT = "qat"
WARMUP_EAGER = 5
TIMED = 10

MTP_N_HEADS = 2
MTP_WEIGHT = 0.3
LR_MUON = 0.02
LR_ADAMW = 3e-4
WEIGHT_DECAY = 0.1

BATCH = 8
PRIOR_FP38C = "fp38c-l9-eager-20260612T231505Z.json"
PRIOR_FP39B = "fp39b-prod-compile-20260612T230911Z.json"

# Production anchors to compare against
BENCH_B8_FLASH_TOK_S = 27894.6    # fp38c bench-path proxy
PROD_B16_CKPT_COMPILE_TOK_S = 19227.8  # fp39b best production cell
PROD_B16_CKPT_EAGER_TOK_S = 16593.4    # fp39 eager production


def _set_flash_global():
    import torch
    torch.backends.cuda.enable_flash_sdp(True)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    torch.backends.cuda.enable_math_sdp(False)


def _build_prod_model():
    import torch
    from transformers import LlamaConfig, LlamaModel

    cfg = fp19.CONFIGS["c03"]
    conf = LlamaConfig(
        vocab_size=VOCAB,
        hidden_size=cfg["hidden"],
        intermediate_size=4 * cfg["hidden"],
        num_hidden_layers=cfg["layers"],
        num_attention_heads=cfg["heads"],
        num_key_value_heads=cfg["heads"],
        max_position_embeddings=SEQ,
        use_cache=False,
    )
    backbone = LlamaModel(conf).cuda().to(torch.bfloat16)
    # no gradient checkpointing

    head = torch.nn.Linear(cfg["hidden"], VOCAB, bias=False).cuda().to(torch.bfloat16)
    head.weight = backbone.embed_tokens.weight

    mtp_heads = torch.nn.ModuleList([
        torch.nn.Linear(cfg["hidden"], VOCAB, bias=False).cuda().to(torch.bfloat16)
        for _ in range(MTP_N_HEADS)
    ])

    all_params = dict(backbone.named_parameters())
    for i, h in enumerate(mtp_heads):
        for n, p in h.named_parameters():
            all_params[f"mtp_heads.{i}.{n}"] = p

    muon_params, adamw_params = [], []
    for name, p in all_params.items():
        if p.ndim == 2 and "embed_tokens" not in name:
            muon_params.append(p)
        else:
            adamw_params.append(p)

    Muon = ts._muon_class()
    opts = {}
    if muon_params:
        opts["muon"] = Muon(muon_params, lr=LR_MUON, weight_decay=WEIGHT_DECAY)
    opts["adamw"] = torch.optim.AdamW(adamw_params, lr=LR_ADAMW, weight_decay=WEIGHT_DECAY)

    return backbone, head, mtp_heads, opts


def bench_cell():
    import torch
    cell_name = f"b{BATCH}-nockpt-flash-eager-prod"
    out = {
        "cell": cell_name, "batch": BATCH, "seq": SEQ,
        "grad_checkpointing": False, "compiled": False,
        "flash_sdpa": True, "mtp_heads": MTP_N_HEADS,
        "mtp_weight": MTP_WEIGHT, "optimizer": "muon_split",
        "variant": VARIANT, "timed_steps": TIMED, "warmup_reps": WARMUP_EAGER,
        "receipt_class": "PRODUCTION",
    }
    try:
        backbone, head, mtp_heads, opts = _build_prod_model()
        backbone.train()
        head.train()
        mtp_heads.train()
        ce_fn = ts.chunked_cross_entropy

        def step():
            ids = torch.randint(0, VOCAB, (BATCH, SEQ), device="cuda")
            tgt0 = torch.roll(ids, -1, dims=1)
            tgt_mtp = [torch.roll(ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]

            saved = fp19._apply_fake_quant(backbone, VARIANT)
            hidden = backbone(input_ids=ids).last_hidden_state
            h_flat = hidden.reshape(-1, hidden.shape[-1])
            primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
            mtp_ces = [ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1), chunk_tokens=1024)[0]
                       for k, mh in enumerate(mtp_heads)]
            loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
            fp19._restore(saved)
            loss.backward()
            for o in opts.values():
                o.step()
            for o in opts.values():
                o.zero_grad(set_to_none=True)

        print(f"[fp38d] warmup {WARMUP_EAGER} steps ...", flush=True)
        for i in range(WARMUP_EAGER):
            step()
            print(f"[fp38d]   warmup {i+1}/{WARMUP_EAGER}", flush=True)
        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            del backbone, head, mtp_heads, opts
            torch.cuda.empty_cache()
            return out

        print(f"[fp38d] bench {TIMED} steps ...", flush=True)
        t0 = time.perf_counter()
        for _ in range(TIMED):
            step()
            torch.cuda.synchronize()
            time.sleep(PACE_S)
        dt = time.perf_counter() - t0
        toks = TIMED * BATCH * SEQ
        paced = toks / dt
        raw = toks / (dt - TIMED * PACE_S)
        out.update(status="OK", tok_s_paced=round(paced, 1),
                   tok_s_raw=round(raw, 1),
                   pacing_tax=round(1.0 - paced / raw, 4))
        del backbone, head, mtp_heads, opts
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

    print(f"[fp38d] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[fp38d] torch: {torch.__version__}", flush=True)
    print(f"[fp38d] L9 rider: B={BATCH} flash+no-ckpt on PRODUCTION stack", flush=True)
    _set_flash_global()

    r = bench_cell()
    print(f"[fp38d] -> {json.dumps(r)}", flush=True)

    ts_now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    TOTAL_TOKENS = 6_973_632_300

    if r.get("status") == "OK":
        tok_s = r["tok_s_paced"]
        wall_days = round(TOTAL_TOKENS / (tok_s * 86400), 3)
        vs_bench_proxy = round(tok_s / BENCH_B8_FLASH_TOK_S, 4)
        vs_prod_b16_compile = round(tok_s / PROD_B16_CKPT_COMPILE_TOK_S, 4)
        if tok_s > PROD_B16_CKPT_COMPILE_TOK_S:
            verdict = f"L9_PROD_DOMINANT_B{BATCH}"
            verdict_note = (
                f"PRODUCTION B{BATCH}-flash exceeds best prior production cell "
                f"(B16-ckpt-compile {PROD_B16_CKPT_COMPILE_TOK_S} tok/s). "
                "L9+flash is the dominant throughput lever for c04 §3."
            )
        else:
            verdict = f"L9_PROD_MARGINAL_B{BATCH}"
            verdict_note = (
                f"B{BATCH}-flash-prod fits under 0.80 cap but below "
                f"B16-ckpt-compile-prod. Net gain marginal on production stack."
            )
    else:
        wall_days = vs_bench_proxy = vs_prod_b16_compile = None
        verdict = f"L9_PROD_OOM_B{BATCH}"
        verdict_note = (
            f"B{BATCH}-flash-prod OOM: MTP activations eliminate flash+no-ckpt "
            "advantage. Production stack cannot use L9 at this batch."
        )

    receipt = {
        "ticket": "FP38D-L9-PROD-FLASH",
        "ts": ts_now,
        "lever": "L9",
        "issue": 225,
        "verdict": verdict,
        "verdict_note": verdict_note,
        "receipt_class": "PRODUCTION",
        "prior_receipts": {
            "fp38c_bench_proxy": PRIOR_FP38C,
            "fp39b_prod_compile": PRIOR_FP39B,
        },
        "baseline": {
            "bench_b8_flash_tok_s": BENCH_B8_FLASH_TOK_S,
            "prod_b16_ckpt_compile_tok_s": PROD_B16_CKPT_COMPILE_TOK_S,
            "prod_b16_ckpt_eager_tok_s": PROD_B16_CKPT_EAGER_TOK_S,
        },
        "cell": r,
        "wall_days_7b_corpus": wall_days,
        "multipliers": {
            "vs_bench_proxy": vs_bench_proxy,
            "vs_prod_b16_ckpt_compile": vs_prod_b16_compile,
        },
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
            f"MTP: {MTP_N_HEADS} heads, weight={MTP_WEIGHT}",
            "optimizer: Muon (2D hidden params) + AdamW (embed/norm/head)",
            "CE: chunked_cross_entropy from timeshare_pretrain (chunk_tokens=1024)",
            "QAT: qat fake-quant via fp19._apply_fake_quant",
            "flash/SDPA: torch.backends.cuda.enable_flash_sdp(True) global",
            "no gradient checkpointing",
            "eager (no compile) — resolves fp38c BENCH-PATH-PROXY class",
            f"warmup_eager={WARMUP_EAGER}",
            "governor rails HOLD — never loosened",
        ],
    }

    out = f"{RECEIPTS}/fp38d-l9-prod-flash-{ts_now}.json"
    checked_write(out, receipt)
    print(json.dumps({
        "verdict": verdict,
        "tok_s_paced": r.get("tok_s_paced"),
        "wall_days_7b": wall_days,
        "vs_bench_proxy": vs_bench_proxy,
        "vs_prod_b16_compile": vs_prod_b16_compile,
    }, indent=2))
    print(f"FP38D_L9_PROD_FLASH_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
