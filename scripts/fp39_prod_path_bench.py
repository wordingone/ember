"""fp39_prod_path_bench.py — production-path throughput anchor.

Every compound number in the ceiling program is bench-path (L6 =
LlamaForCausalLM + AdamW). This bench measures the ACTUAL production
step: LlamaModel backbone + 2 MTP heads + chunked CE + Muon/AdamW
split optimizer + QAT fake-quant. That ~2x throughput gap is now
receipted; this calibrates the wall-day price for c04 design.

Cells:
  B4-nockpt-eager       — production config (actual run batch, matches 12c050e7)
  B4-nockpt-compile     — compiled production config
  B16-ckpt-prod-eager   — bench best-safe batch, grad-ckpt, eager
  B16-ckpt-prod-compile — bench best-safe batch, grad-ckpt, compiled

Phase timing via CUDA events on each cell (backbone-fwd / CE /
backward / muon-step / adamw-step) for ENG/ARCH split.

Anchor for comparison: fp32-l6-compile-ab-20260612T215844Z (bench-path
b16-ckpt-compile = 31,377 tok/s). Governor: VRAM 0.80, MARGIN 1.5 GiB,
PACE 0.05s — never loosened.
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

# Import production step components from timeshare_pretrain
sys.path.insert(0, HERE)
import timeshare_pretrain as ts                       # noqa: E402

RECEIPTS = f"{NC}/receipts"
SEQ = fp19.SEQ         # 1024
VOCAB = fp19.VOCAB     # 32000
PACE_S = fp19.PACE_S   # 0.05
VRAM_FRACTION = 0.80
MARGIN_GIB = fp19.MARGIN_GIB  # 1.5
VARIANT = "qat"

# v0 config constants (from v0-pretrain-config.json)
MTP_N_HEADS = 2
MTP_WEIGHT = 0.3
LR_MUON = 0.02
LR_ADAMW = 3e-4
WEIGHT_DECAY = 0.1

# Anchor from L6 bench-path receipt
L6_ANCHOR_TOK_S = 18472.2       # b4-ckpt-eager bench-path anchor
L6_COMPILE_TOK_S = 31377.4      # b16-ckpt-compile bench-path
L7_PROD_TOK_S = 8872.3          # measured production throughput (12c050e7 L7)
L6_RECEIPT = "fp32-l6-compile-ab-20260612T215844Z.json"
L7_RECEIPT = "fp37-l7-duty-cycle-20260612T222145Z.json"

WARMUP_EAGER = 3
WARMUP_COMPILE = 8
TIMED = 10


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

    # Tied embedding head + MTP heads (match production layout)
    head = torch.nn.Linear(cfg_c03["hidden"], VOCAB, bias=False).cuda().to(torch.bfloat16)
    head.weight = backbone.embed_tokens.weight  # tied

    mtp_heads = torch.nn.ModuleList([
        torch.nn.Linear(cfg_c03["hidden"], VOCAB, bias=False).cuda().to(torch.bfloat16)
        for _ in range(MTP_N_HEADS)
    ])

    # Build split optimizer (Muon on 2D params, AdamW on rest)
    all_params = dict(backbone.named_parameters())
    for i, h in enumerate(mtp_heads):
        for n, p in h.named_parameters():
            all_params[f"mtp_heads.{i}.{n}"] = p
    # head.weight is tied to backbone — skip duplicate

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


def bench_prod_cell(batch, grad_ckpt, compiled, warmup_steps):
    import torch
    cfg = fp19.CONFIGS["c03"]
    cell_name = (f"b{batch}-{'ckpt' if grad_ckpt else 'nockpt'}"
                 f"-{'compile' if compiled else 'eager'}-prod")
    out = {
        "cell": cell_name, "batch": batch, "seq": SEQ,
        "grad_checkpointing": grad_ckpt, "compiled": compiled,
        "mtp_heads": MTP_N_HEADS, "mtp_weight": MTP_WEIGHT,
        "optimizer": "muon_split",
        "variant": VARIANT, "timed_steps": TIMED, "warmup_reps": warmup_steps,
    }
    try:
        backbone, head, mtp_heads, opts = _build_prod_model(batch, grad_ckpt, cfg)
        backbone.train()
        head.train()
        mtp_heads.train()

        ce_fn = ts.chunked_cross_entropy

        # Wrap in a plain function so torch.compile never sees the
        # transformers output_capturing decorator (NameError: 'torch' in
        # the transformers wrapper scope during JIT trace — workaround).
        def _backbone_call(ids):
            return backbone(input_ids=ids).last_hidden_state

        fwd_raw = _backbone_call
        if compiled:
            print(f"[fp39] torch.compile(backbone wrapper) ...", flush=True)
            fwd_raw = torch.compile(_backbone_call)

        def step_timed():
            # Phase events
            ev = {k: (torch.cuda.Event(enable_timing=True),
                      torch.cuda.Event(enable_timing=True))
                  for k in ["backbone", "ce", "backward", "muon", "adamw"]}

            ids = torch.randint(0, VOCAB, (batch, SEQ), device="cuda")
            # MTP targets: shift by 1 and 2 positions
            tgt0 = torch.roll(ids, -1, dims=1)
            tgt_mtp = [torch.roll(ids, -(k+2), dims=1) for k in range(MTP_N_HEADS)]

            saved = fp19._apply_fake_quant(backbone, VARIANT)

            ev["backbone"][0].record()
            hidden = fwd_raw(ids)
            ev["backbone"][1].record()

            h_flat = hidden.reshape(-1, hidden.shape[-1])
            ev["ce"][0].record()
            primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1),
                                  chunk_tokens=1024)
            mtp_ces = []
            for k, mh in enumerate(mtp_heads):
                ce_k, _ = ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1),
                                chunk_tokens=1024)
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

        print(f"[fp39] warmup {warmup_steps} steps ...", flush=True)
        for i in range(warmup_steps):
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
            print(f"[fp39]   warmup {i+1}/{warmup_steps}", flush=True)

        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            del backbone, head, mtp_heads, opts
            torch.cuda.empty_cache()
            return out

        print(f"[fp39] timed {TIMED} steps ...", flush=True)
        phase_ms = {"backbone": 0.0, "ce": 0.0, "backward": 0.0,
                    "muon": 0.0, "adamw": 0.0}
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

    print(f"[fp39] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[fp39] torch: {torch.__version__}", flush=True)
    print(f"[fp39] production stack: backbone+{MTP_N_HEADS}MTP+chunkedCE+MuonSplit+QAT", flush=True)
    print(f"[fp39] L6 bench anchor: {L6_COMPILE_TOK_S} tok/s | L7 prod: {L7_PROD_TOK_S} tok/s", flush=True)

    CELLS = [
        # (batch, grad_ckpt, compiled, warmup)
        (4,  False, False, WARMUP_EAGER),    # production config: B=4, no-ckpt, eager
        (4,  False, True,  WARMUP_COMPILE),  # production config + compile
        (16, True,  False, WARMUP_EAGER),    # bench best-safe: B=16, ckpt, eager
        (16, True,  True,  WARMUP_COMPILE),  # bench best-safe + compile
    ]

    cells = []
    for batch, grad_ckpt, compiled, warmup in CELLS:
        label = (f"b{batch}-{'ckpt' if grad_ckpt else 'nockpt'}"
                 f"-{'compile' if compiled else 'eager'}-prod")
        print(f"\n[fp39] cell {label} ...", flush=True)
        r = bench_prod_cell(batch, grad_ckpt, compiled, warmup)
        print(f"[fp39]   status={r.get('status')} tok_s={r.get('tok_s_paced')}", flush=True)
        if r.get("phase_pct"):
            print(f"[fp39]   phases: {r['phase_pct']}", flush=True)
        cells.append(r)

    ts_now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Find best prod-compiled cell for anchor recalibration
    ok_cells = [c for c in cells if c.get("status") == "OK"]
    prod_b4_eager = next((c for c in ok_cells if c["batch"] == 4 and not c["compiled"]), None)
    prod_b4_compile = next((c for c in ok_cells if c["batch"] == 4 and c["compiled"]), None)
    prod_b16_compile = next((c for c in ok_cells
                             if c["batch"] == 16 and c["compiled"]), None)

    gap_b4_eager = None
    if prod_b4_eager:
        gap_b4_eager = round(L6_ANCHOR_TOK_S / prod_b4_eager["tok_s_paced"], 4)
    gap_b4_compile = None
    if prod_b4_compile and prod_b16_compile:
        gap_b4_compile = round(prod_b16_compile["tok_s_paced"] / prod_b4_compile["tok_s_paced"], 4)

    # Wall-day recalibration for 7B-token c03 run
    TOTAL_TOKENS = 6_973_632_300
    wall_days = {}
    for c in ok_cells:
        wd = TOTAL_TOKENS / (c["tok_s_paced"] * 86400)
        wall_days[c["cell"]] = round(wd, 3)

    receipt = {
        "ticket": "FP39-PROD-PATH-BENCH",
        "ts": ts_now,
        "issue": 225,
        "scope": (
            "production-path throughput anchor — full v0 step: "
            "LlamaModel backbone + 2 MTP heads + chunked CE + "
            "Muon/AdamW split optimizer + QAT fake-quant"
        ),
        "prior_receipts": {
            "bench_path_anchor": L6_RECEIPT,
            "prod_path_measured": L7_RECEIPT,
        },
        "cells": cells,
        "recalibration": {
            "bench_path_b4_eager_tok_s": L6_ANCHOR_TOK_S,
            "prod_path_b4_eager_tok_s": prod_b4_eager.get("tok_s_paced") if prod_b4_eager else None,
            "bench_vs_prod_gap_factor": gap_b4_eager,
            "l7_checkpoint_tok_s": L7_PROD_TOK_S,
            "note": ("gap_factor = bench/prod; >1 means bench overestimates. "
                     "L7 measured 8,872 tok/s from checkpoints; this bench gives "
                     "the synthetic equiv on the same production stack.")
        },
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
            f"QAT: {VARIANT} fake-quant via fp19._apply_fake_quant",
            "phase timing: CUDA events per phase (backbone/CE/backward/muon/adamw)",
            "governor rails HOLD — never loosened",
        ],
    }

    out = f"{RECEIPTS}/fp39-prod-path-bench-{ts_now}.json"
    checked_write(out, receipt)

    summary = {
        "cells": [
            {"cell": c["cell"], "tok_s_paced": c.get("tok_s_paced"),
             "status": c.get("status"), "phase_pct": c.get("phase_pct")}
            for c in cells
        ],
        "wall_days_7b": wall_days,
        "bench_vs_prod_gap": gap_b4_eager,
    }
    print(json.dumps(summary, indent=2))
    print(f"FP39_PROD_PATH_BENCH_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
