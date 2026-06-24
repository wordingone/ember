"""fp39b_prod_compile.py — production-path compiled cells only.

fp39_prod_path_bench covered B4/B16 eager (OK) and B4/B16 compiled
(CELL-ERROR: transformers output_capturing NameError during JIT trace).
This script re-runs ONLY the compiled cells with the _backbone_call
wrapper fix: compiles a plain Python function instead of LlamaModel
directly, bypassing the transformers decorator scope issue.

Prior receipt: fp39-prod-path-bench-20260612T225120Z.json
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

MTP_N_HEADS = 2
MTP_WEIGHT = 0.3
LR_MUON = 0.02
LR_ADAMW = 3e-4
WEIGHT_DECAY = 0.1

PRIOR_FP39 = "fp39-prod-path-bench-20260612T225120Z.json"
L6_ANCHOR_TOK_S = 18472.2
L7_PROD_TOK_S = 8872.3
WARMUP_COMPILE = 8
TIMED = 10

CELLS = [
    # (batch, grad_ckpt)
    (4,  False),
    (16, True),
]


def _build_prod_model(batch, grad_ckpt, cfg_c03):
    import torch
    from transformers import LlamaConfig, LlamaModel

    conf = LlamaConfig(
        vocab_size=VOCAB,
        hidden_size=cfg_c03["hidden"],
        intermediate_size=4 * cfg_c03["hidden"],
        num_hidden_layers=cfg_c03["layers"],
        num_attention_heads=cfg_c03["heads"],
        num_key_value_heads=cfg_c03["heads"],
        max_position_embeddings=SEQ,
        use_cache=False,
    )
    backbone = LlamaModel(conf).cuda().to(torch.bfloat16)
    if grad_ckpt:
        backbone.gradient_checkpointing_enable()

    head = torch.nn.Linear(cfg_c03["hidden"], VOCAB, bias=False).cuda().to(torch.bfloat16)
    head.weight = backbone.embed_tokens.weight

    mtp_heads = torch.nn.ModuleList([
        torch.nn.Linear(cfg_c03["hidden"], VOCAB, bias=False).cuda().to(torch.bfloat16)
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


def bench_compile_cell(batch, grad_ckpt):
    import torch
    cfg = fp19.CONFIGS["c03"]
    cell_name = f"b{batch}-{'ckpt' if grad_ckpt else 'nockpt'}-compile-prod"
    out = {
        "cell": cell_name, "batch": batch, "seq": SEQ,
        "grad_checkpointing": grad_ckpt, "compiled": True,
        "mtp_heads": MTP_N_HEADS, "mtp_weight": MTP_WEIGHT,
        "optimizer": "muon_split",
        "variant": VARIANT, "timed_steps": TIMED, "warmup_reps": WARMUP_COMPILE,
    }
    try:
        backbone, head, mtp_heads, opts = _build_prod_model(batch, grad_ckpt, cfg)
        backbone.train()
        head.train()
        mtp_heads.train()

        ce_fn = ts.chunked_cross_entropy

        # LlamaModel.forward is wrapped by transformers' output_capturing
        # decorator, which references `torch` in a scope JIT can't resolve
        # (NameError during trace). Unwrap the decorator chain on the class
        # method so torch.compile sees the raw implementation.
        import types
        _cls_fwd = type(backbone).forward
        while hasattr(_cls_fwd, '__wrapped__'):
            _cls_fwd = _cls_fwd.__wrapped__
        # Rebind as a bound method on this instance only (don't mutate class)
        backbone.forward = types.MethodType(_cls_fwd, backbone)

        def _backbone_call(ids):
            return backbone(input_ids=ids).last_hidden_state

        print(f"[fp39b] torch.compile(backbone wrapper, unwrapped forward) ...", flush=True)
        fwd_raw = torch.compile(_backbone_call)

        def step_timed():
            ev = {k: (torch.cuda.Event(enable_timing=True),
                      torch.cuda.Event(enable_timing=True))
                  for k in ["backbone", "ce", "backward", "muon", "adamw"]}

            ids = torch.randint(0, VOCAB, (batch, SEQ), device="cuda")
            tgt0 = torch.roll(ids, -1, dims=1)
            tgt_mtp = [torch.roll(ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]

            saved = fp19._apply_fake_quant(backbone, VARIANT)

            ev["backbone"][0].record()
            hidden = fwd_raw(ids)
            ev["backbone"][1].record()

            h_flat = hidden.reshape(-1, hidden.shape[-1])
            ev["ce"][0].record()
            primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
            mtp_ces = []
            for k, mh in enumerate(mtp_heads):
                ce_k, _ = ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1), chunk_tokens=1024)
                mtp_ces.append(ce_k)
            loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
            ev["ce"][1].record()

            fp19._restore(saved)

            ev["backward"][0].record()
            loss.backward()
            ev["backward"][1].record()

            ev["muon"][0].record()
            if "muon" in opts:
                opts["muon"].step()
            ev["muon"][1].record()

            ev["adamw"][0].record()
            opts["adamw"].step()
            ev["adamw"][1].record()

            for o in opts.values():
                o.zero_grad(set_to_none=True)

            return ev

        print(f"[fp39b] warmup {WARMUP_COMPILE} steps ...", flush=True)
        for i in range(WARMUP_COMPILE):
            ids = torch.randint(0, VOCAB, (batch, SEQ), device="cuda")
            tgt0 = torch.roll(ids, -1, dims=1)
            tgt_mtp = [torch.roll(ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]
            saved = fp19._apply_fake_quant(backbone, VARIANT)
            hidden = fwd_raw(ids)
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
            print(f"[fp39b]   warmup {i+1}/{WARMUP_COMPILE}", flush=True)

        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            del backbone, head, mtp_heads, opts
            torch.cuda.empty_cache()
            return out

        print(f"[fp39b] timed {TIMED} steps ...", flush=True)
        phase_ms = {"backbone": 0.0, "ce": 0.0, "backward": 0.0, "muon": 0.0, "adamw": 0.0}
        t0 = time.perf_counter()
        for _ in range(TIMED):
            ev = step_timed()
            torch.cuda.synchronize()
            for k, (s, e) in ev.items():
                phase_ms[k] += s.elapsed_time(e)
            time.sleep(PACE_S)
        dt = time.perf_counter() - t0
        toks = TIMED * batch * SEQ
        paced = toks / dt
        raw = toks / (dt - TIMED * PACE_S)
        avg_phase = {k: round(v / TIMED, 2) for k, v in phase_ms.items()}
        total_phase_ms = sum(avg_phase.values())
        phase_pct = {k: round(100 * v / total_phase_ms, 2) for k, v in avg_phase.items()}

        out.update(
            status="OK",
            tok_s_paced=round(paced, 1),
            tok_s_raw=round(raw, 1),
            pacing_tax=round(1.0 - paced / raw, 4),
            phase_ms_per_step=avg_phase,
            phase_pct=phase_pct,
            phase_tag={
                "backbone": "ARCH",
                "ce": "ENG (chunked-CE implementation)",
                "backward": "ARCH+ENG (backbone grad=ARCH, optimizer-prep=ENG)",
                "muon": "ENG (replaceable optimizer)",
                "adamw": "ENG (replaceable optimizer)",
            },
        )
        del backbone, head, mtp_heads, opts
        torch.cuda.empty_cache()
        return out
    except torch.cuda.OutOfMemoryError:
        out["status"] = "SKIPPED-OOM"
        torch.cuda.empty_cache()
        return out
    except Exception as e:
        out["status"] = "CELL-ERROR"
        out["error"] = f"{type(e).__name__}: {e}"[:500]
        import traceback
        print(traceback.format_exc(), flush=True)
        torch.cuda.empty_cache()
        return out


def main():
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    print(f"[fp39b] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[fp39b] torch: {torch.__version__}", flush=True)
    print(f"[fp39b] compiled-cells retry (backbone-wrapper fix)", flush=True)

    cells = []
    for batch, grad_ckpt in CELLS:
        label = f"b{batch}-{'ckpt' if grad_ckpt else 'nockpt'}-compile-prod"
        print(f"\n[fp39b] cell {label} ...", flush=True)
        r = bench_compile_cell(batch, grad_ckpt)
        print(f"[fp39b]   status={r.get('status')} tok_s={r.get('tok_s_paced')}", flush=True)
        if r.get("phase_pct"):
            print(f"[fp39b]   phases: {r['phase_pct']}", flush=True)
        cells.append(r)

    ts_now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    ok_cells = [c for c in cells if c.get("status") == "OK"]
    TOTAL_TOKENS = 6_973_632_300
    wall_days = {c["cell"]: round(TOTAL_TOKENS / (c["tok_s_paced"] * 86400), 3)
                 for c in ok_cells}

    receipt = {
        "ticket": "FP39B-PROD-COMPILE",
        "ts": ts_now,
        "issue": 225,
        "scope": "production-path compiled cells — backbone-wrapper fix for transformers NameError",
        "prior_receipt": PRIOR_FP39,
        "cells": cells,
        "wall_days_7b_corpus": wall_days,
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
            "compile: torch.compile(_backbone_call) — plain wrapper, no transformers decorator",
            "phase timing: CUDA events per phase (backbone/CE/backward/muon/adamw)",
            "governor rails HOLD — never loosened",
        ],
    }

    out = f"{RECEIPTS}/fp39b-prod-compile-{ts_now}.json"
    checked_write(out, receipt)

    summary = {
        "cells": [{"cell": c["cell"], "tok_s_paced": c.get("tok_s_paced"),
                   "status": c.get("status"), "phase_pct": c.get("phase_pct")}
                  for c in cells],
        "wall_days_7b": wall_days,
    }
    print(json.dumps(summary, indent=2))
    print(f"FP39B_PROD_COMPILE_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
