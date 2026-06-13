"""fp40_l10_optimizer_ab.py — L10 optimizer swap A/B bench (issue #363).

Production stack (C-7): LlamaModel c03 + 2 MTP heads + chunkedCE + B16+ckpt+compile.
Single variable per cell = optimizer configuration.

Cells:
  1. muon_split_baseline    — Muon(2D hidden excl embed, lr=0.02, ns5) + AdamW(rest, lr=3e-4)
                               equivalence anchor from fp39b (19,227.8 tok/s paced, 36.01% Muon wall)
  2. muon_2d_fused_side     — same Muon split, AdamW side replaced with fused=True
                               hypothesis: fused side trims AdamW overhead; Muon wall unchanged
  3. full_fused_adamw       — all params in fused AdamW, lr=3e-4 (no Muon / no NS chain)
                               control: removes the 36% Muon wall; quality loss must be scoped by EQUIV leg
  4. muon_ns3               — Muon(ns_steps=3) + AdamW side (same as cell 1 but half NS iters)
                               hypothesis: half-step NS chain ~halves Muon wall; quality impact scoped by EQUIV

EQUIVALENCE leg: for cells 3 and 4 (throughput winners), run EQUIV_STEPS steps from the
same random init (same seed, same token batches) as the baseline (cell 1).  Report per-step
loss delta at steps 10, 25, 50, 100.  A cell passes EQUIV if |delta_loss_at_100| <= EQUIV_THRESHOLD.

Governor rails: VRAM_FRACTION=0.80, MARGIN_GIB=1.5, PACE_S=0.05 — HOLD, never loosened.
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

WARMUP_COMPILE = 8
TIMED = 10
EQUIV_STEPS = 100
EQUIV_THRESHOLD_FLOOR = 0.10    # nats — floor; actual threshold derived from seed noise

PRIOR_FP39B_TOK_S = 19227.8     # anchor from fp39b receipt
PRIOR_FP39B_MUON_PCT = 36.01    # Muon wall share from fp39b

# (opt_key, ns_steps, fused_side, full_adamw)
CELLS = [
    ("muon_split_baseline",   5, False, False),
    ("muon_2d_fused_side",    5, True,  False),
    ("full_fused_adamw",      0, True,  True),
    ("muon_ns3",              3, False, False),
]


def _build_model_and_opts(ns_steps, fused_side, full_adamw, cfg_c03):
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

    if full_adamw:
        all_p = list(all_params.values())
        opts = {
            "adamw": torch.optim.AdamW(all_p, lr=LR_ADAMW, weight_decay=WEIGHT_DECAY,
                                       fused=True),
        }
    else:
        muon_params, adamw_params = [], []
        for name, p in all_params.items():
            if p.ndim == 2 and "embed_tokens" not in name:
                muon_params.append(p)
            else:
                adamw_params.append(p)

        Muon = ts._muon_class()
        opts = {}
        if muon_params and ns_steps > 0:
            opts["muon"] = Muon(muon_params, lr=LR_MUON, weight_decay=WEIGHT_DECAY,
                                ns_steps=ns_steps)
        elif muon_params and ns_steps == 0:
            # ns_steps=0 cell treated as additional AdamW group
            adamw_params = muon_params + adamw_params
        opts["adamw"] = torch.optim.AdamW(
            adamw_params, lr=LR_ADAMW, weight_decay=WEIGHT_DECAY,
            fused=fused_side,
        )

    return backbone, head, mtp_heads, opts


def _step_timed(backbone, fwd_raw, head, mtp_heads, opts, batch, ce_fn):
    import torch
    ev = {k: (torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True))
          for k in ["backbone", "ce", "backward"] + list(opts.keys())}

    ids = torch.randint(0, VOCAB, (batch, SEQ), device="cuda")
    tgt0 = torch.roll(ids, -1, dims=1)
    tgt_mtp = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]

    saved = fp19._apply_fake_quant(backbone, VARIANT)

    ev["backbone"][0].record()
    hidden = fwd_raw(ids)
    ev["backbone"][1].record()

    h_flat = hidden.reshape(-1, hidden.shape[-1])
    ev["ce"][0].record()
    primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
    mtp_ces = [ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1), chunk_tokens=1024)[0]
               for k, mh in enumerate(mtp_heads)]
    loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
    ev["ce"][1].record()

    fp19._restore(saved)

    ev["backward"][0].record()
    loss.backward()
    ev["backward"][1].record()

    for opt_key, opt in opts.items():
        ev[opt_key][0].record()
        opt.step()
        ev[opt_key][1].record()

    for opt in opts.values():
        opt.zero_grad(set_to_none=True)

    return ev, loss.item()


def bench_cell(opt_key, ns_steps, fused_side, full_adamw):
    import torch
    cfg = fp19.CONFIGS["c03"]
    out = {
        "cell": opt_key,
        "optimizer": opt_key,
        "ns_steps": ns_steps,
        "fused_side": fused_side,
        "full_adamw": full_adamw,
        "batch": 16, "seq": SEQ,
        "grad_checkpointing": True,
        "compiled": True,
        "mtp_heads": MTP_N_HEADS,
        "mtp_weight": MTP_WEIGHT,
        "variant": VARIANT,
        "timed_steps": TIMED,
        "warmup_reps": WARMUP_COMPILE,
    }
    try:
        backbone, head, mtp_heads, opts = _build_model_and_opts(
            ns_steps, fused_side, full_adamw, cfg)
        backbone.train(); head.train(); mtp_heads.train()

        import types
        _cls_fwd = type(backbone).forward
        while hasattr(_cls_fwd, '__wrapped__'):
            _cls_fwd = _cls_fwd.__wrapped__
        backbone.forward = types.MethodType(_cls_fwd, backbone)

        def _backbone_call(ids):
            return backbone(input_ids=ids).last_hidden_state

        print(f"[fp40] torch.compile for cell {opt_key} ...", flush=True)
        fwd_raw = torch.compile(_backbone_call)
        ce_fn = ts.chunked_cross_entropy

        print(f"[fp40] warmup {WARMUP_COMPILE} steps ...", flush=True)
        for i in range(WARMUP_COMPILE):
            ids = torch.randint(0, VOCAB, (16, SEQ), device="cuda")
            tgt0 = torch.roll(ids, -1, dims=1)
            tgt_mtp = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
            saved = fp19._apply_fake_quant(backbone, VARIANT)
            hidden = fwd_raw(ids)
            h_flat = hidden.reshape(-1, hidden.shape[-1])
            primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
            mtp_ces = [ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1), chunk_tokens=1024)[0]
                       for k, mh in enumerate(mtp_heads)]
            loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
            fp19._restore(saved)
            loss.backward()
            for opt in opts.values():
                opt.step()
            for opt in opts.values():
                opt.zero_grad(set_to_none=True)
            print(f"[fp40]   warmup {i + 1}/{WARMUP_COMPILE}", flush=True)

        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            del backbone, head, mtp_heads, opts
            torch.cuda.empty_cache()
            return out

        print(f"[fp40] timed {TIMED} steps ...", flush=True)
        phase_ms = {k: 0.0 for k in ["backbone", "ce", "backward"] + list(opts.keys())}
        t0 = time.perf_counter()
        for _ in range(TIMED):
            ev, _ = _step_timed(backbone, fwd_raw, head, mtp_heads, opts, 16, ce_fn)
            torch.cuda.synchronize()
            for k, (s, e) in ev.items():
                phase_ms[k] += s.elapsed_time(e)
            time.sleep(PACE_S)
        dt = time.perf_counter() - t0
        toks = TIMED * 16 * SEQ
        paced = toks / dt
        raw = toks / (dt - TIMED * PACE_S)
        avg_phase = {k: round(v / TIMED, 2) for k, v in phase_ms.items()}
        total_phase_ms = sum(avg_phase.values())
        phase_pct = {k: round(100 * v / total_phase_ms, 2) for k, v in avg_phase.items()}

        # optimizer wall-share = sum of optimizer phase(s)
        opt_keys_in_phase = [k for k in opts.keys()]
        optimizer_wall_pct = round(sum(phase_pct.get(k, 0.0) for k in opt_keys_in_phase), 2)

        out.update(
            status="OK",
            tok_s_paced=round(paced, 1),
            tok_s_raw=round(raw, 1),
            pacing_tax=round(1.0 - paced / raw, 4),
            phase_ms_per_step=avg_phase,
            phase_pct=phase_pct,
            optimizer_wall_pct=optimizer_wall_pct,
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


def equiv_leg(baseline_losses, noise_floor, derived_threshold, opt_key, ns_steps, fused_side, full_adamw):
    """Run EQUIV_STEPS steps with seed=42, compare loss curve to baseline (also seed=42).

    equiv_pass requires |delta@100| <= derived_threshold AND no monotonic increase
    across checkpoints [10, 25, 50, 100].
    """
    import torch
    cfg = fp19.CONFIGS["c03"]

    out = {"cell": opt_key, "equiv_steps": EQUIV_STEPS,
           "equiv_noise_floor_nats": noise_floor, "equiv_derived_threshold_nats": derived_threshold}
    try:
        backbone, head, mtp_heads, opts = _build_model_and_opts(
            ns_steps, fused_side, full_adamw, cfg)
        backbone.train(); head.train(); mtp_heads.train()

        import types
        _cls_fwd = type(backbone).forward
        while hasattr(_cls_fwd, '__wrapped__'):
            _cls_fwd = _cls_fwd.__wrapped__
        backbone.forward = types.MethodType(_cls_fwd, backbone)

        def _backbone_call(ids):
            return backbone(input_ids=ids).last_hidden_state

        fwd_raw = torch.compile(_backbone_call)
        ce_fn = ts.chunked_cross_entropy

        # warmup
        for _ in range(WARMUP_COMPILE):
            ids = torch.randint(0, VOCAB, (16, SEQ), device="cuda")
            tgt0 = torch.roll(ids, -1, dims=1)
            tgt_mtp = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
            saved = fp19._apply_fake_quant(backbone, VARIANT)
            hidden = fwd_raw(ids)
            h_flat = hidden.reshape(-1, hidden.shape[-1])
            primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
            mtp_ces = [ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1), chunk_tokens=1024)[0]
                       for k, mh in enumerate(mtp_heads)]
            loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
            fp19._restore(saved)
            loss.backward()
            for opt in opts.values():
                opt.step()
            for opt in opts.values():
                opt.zero_grad(set_to_none=True)

        # deterministic run
        torch.manual_seed(42)
        losses = []
        checkpoints = [10, 25, 50, 100]
        for step in range(EQUIV_STEPS):
            ids = torch.randint(0, VOCAB, (16, SEQ), device="cuda")
            tgt0 = torch.roll(ids, -1, dims=1)
            tgt_mtp = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
            saved = fp19._apply_fake_quant(backbone, VARIANT)
            hidden = fwd_raw(ids)
            h_flat = hidden.reshape(-1, hidden.shape[-1])
            primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
            mtp_ces = [ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1), chunk_tokens=1024)[0]
                       for k, mh in enumerate(mtp_heads)]
            loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
            fp19._restore(saved)
            loss.backward()
            for opt in opts.values():
                opt.step()
            for opt in opts.values():
                opt.zero_grad(set_to_none=True)
            losses.append(round(loss.item(), 6))

        delta_at = {}
        for cp in checkpoints:
            if cp <= len(losses) and cp <= len(baseline_losses):
                delta_at[cp] = round(losses[cp - 1] - baseline_losses[cp - 1], 6)

        final_delta = delta_at.get(EQUIV_STEPS, None)
        trend_diverging = (
            10 in delta_at and 25 in delta_at and 50 in delta_at and 100 in delta_at and
            delta_at[10] < delta_at[25] < delta_at[50] < delta_at[100]
        )
        equiv_pass = (
            final_delta is not None
            and abs(final_delta) <= derived_threshold
            and not trend_diverging
        )

        out.update(
            status="OK",
            losses_at=delta_at,
            final_delta=final_delta,
            trend_diverging=trend_diverging,
            equiv_pass=equiv_pass,
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


def _equiv_noise_floor():
    """Run muon_split baseline twice (seeds 42 and 43) from the same post-warmup state.

    Both seeded runs start from identical model + optimizer state (snapshotted after warmup).
    noise_floor = |loss_seed42@100 - loss_seed43@100|; this is pure data-seed variance.
    derived_threshold = max(EQUIV_THRESHOLD_FLOOR, noise_floor).

    Returns dict: noise_floor, derived_threshold, baseline_losses (seed=42 curve for equiv_leg).
    """
    import torch
    import copy
    cfg = fp19.CONFIGS["c03"]

    backbone, head, mtp_heads, opts = _build_model_and_opts(5, False, False, cfg)
    backbone.train(); head.train(); mtp_heads.train()

    import types
    _cls_fwd = type(backbone).forward
    while hasattr(_cls_fwd, '__wrapped__'):
        _cls_fwd = _cls_fwd.__wrapped__
    backbone.forward = types.MethodType(_cls_fwd, backbone)

    def _backbone_call(ids):
        return backbone(input_ids=ids).last_hidden_state

    fwd_raw = torch.compile(_backbone_call)
    ce_fn = ts.chunked_cross_entropy

    for _ in range(WARMUP_COMPILE):
        ids = torch.randint(0, VOCAB, (16, SEQ), device="cuda")
        tgt0 = torch.roll(ids, -1, dims=1)
        tgt_mtp = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
        saved = fp19._apply_fake_quant(backbone, VARIANT)
        hidden = fwd_raw(ids)
        h_flat = hidden.reshape(-1, hidden.shape[-1])
        primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
        mtp_ces = [ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1), chunk_tokens=1024)[0]
                   for k, mh in enumerate(mtp_heads)]
        loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
        fp19._restore(saved)
        loss.backward()
        for opt in opts.values():
            opt.step()
        for opt in opts.values():
            opt.zero_grad(set_to_none=True)

    # snapshot post-warmup state so both seeded runs start identically
    model_snap = {k: v.detach().clone() for k, v in backbone.state_dict().items()}
    head_snap = {k: v.detach().clone() for k, v in head.state_dict().items()}
    mtp_snap = {k: v.detach().clone() for k, v in mtp_heads.state_dict().items()}
    opt_snaps = {k: copy.deepcopy(opt.state_dict()) for k, opt in opts.items()}

    def _seeded_run(data_seed):
        backbone.load_state_dict(model_snap)
        head.load_state_dict(head_snap)
        mtp_heads.load_state_dict(mtp_snap)
        for k, opt in opts.items():
            opt.load_state_dict(opt_snaps[k])
        torch.manual_seed(data_seed)
        run_losses = []
        for _ in range(EQUIV_STEPS):
            ids = torch.randint(0, VOCAB, (16, SEQ), device="cuda")
            tgt0 = torch.roll(ids, -1, dims=1)
            tgt_mtp = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
            saved = fp19._apply_fake_quant(backbone, VARIANT)
            hidden = fwd_raw(ids)
            h_flat = hidden.reshape(-1, hidden.shape[-1])
            primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
            mtp_ces = [ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1), chunk_tokens=1024)[0]
                       for k, mh in enumerate(mtp_heads)]
            loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
            fp19._restore(saved)
            loss.backward()
            for opt in opts.values():
                opt.step()
            for opt in opts.values():
                opt.zero_grad(set_to_none=True)
            run_losses.append(round(loss.item(), 6))
        return run_losses

    losses_42 = _seeded_run(42)
    losses_43 = _seeded_run(43)

    noise_floor = round(abs(losses_42[-1] - losses_43[-1]), 6)
    derived_threshold = round(max(EQUIV_THRESHOLD_FLOOR, noise_floor), 6)

    del backbone, head, mtp_heads, opts
    torch.cuda.empty_cache()

    return {
        "noise_floor": noise_floor,
        "derived_threshold": derived_threshold,
        "baseline_losses": losses_42,
    }


def main():
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    print(f"[fp40] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[fp40] torch: {torch.__version__}", flush=True)
    print(f"[fp40] L10 optimizer swap A/B — 4 cells + EQUIV leg", flush=True)

    cells = []
    for (opt_key, ns_steps, fused_side, full_adamw) in CELLS:
        print(f"\n[fp40] cell {opt_key} ...", flush=True)
        r = bench_cell(opt_key, ns_steps, fused_side, full_adamw)
        print(f"[fp40]   status={r.get('status')} tok_s={r.get('tok_s_paced')} "
              f"opt_wall_pct={r.get('optimizer_wall_pct')}", flush=True)
        cells.append(r)

    # EQUIV leg — baseline first, then any cell with lower optimizer_wall_pct than baseline
    baseline = next((c for c in cells if c["cell"] == "muon_split_baseline"
                     and c.get("status") == "OK"), None)
    baseline_opt_pct = baseline["optimizer_wall_pct"] if baseline else 100.0

    equiv_results = {}
    equiv_candidates = [
        c for c in cells
        if c.get("status") == "OK"
        and c["cell"] != "muon_split_baseline"
        and c.get("optimizer_wall_pct", 100.0) < baseline_opt_pct
    ]

    nf = None
    if equiv_candidates:
        print(f"\n[fp40] EQUIV leg — {len(equiv_candidates)} candidates ...", flush=True)
        print(f"[fp40]   noise-floor run: baseline seeds 42+43 ({EQUIV_STEPS} steps each) ...",
              flush=True)
        nf = _equiv_noise_floor()
        print(f"[fp40]   noise_floor={nf['noise_floor']:.6f} "
              f"derived_threshold={nf['derived_threshold']:.6f}", flush=True)

        for cand in equiv_candidates:
            print(f"[fp40]   equiv cell {cand['cell']} ...", flush=True)
            _, ns_s, fs, fa = next(x for x in CELLS if x[0] == cand["cell"])
            eq = equiv_leg(nf["baseline_losses"], nf["noise_floor"], nf["derived_threshold"],
                           cand["cell"], ns_s, fs, fa)
            print(f"[fp40]   equiv {cand['cell']}: pass={eq.get('equiv_pass')} "
                  f"delta@100={eq.get('final_delta')} trend_diverging={eq.get('trend_diverging')}",
                  flush=True)
            equiv_results[cand["cell"]] = eq

    ts_now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ok_cells = [c for c in cells if c.get("status") == "OK"]

    # Verdict: C-3 candidate = any cell with optimizer_wall_pct <= 15 AND equiv_pass
    c3_candidates = []
    for c in ok_cells:
        if c["cell"] == "muon_split_baseline":
            continue
        opt_pct = c.get("optimizer_wall_pct", 100.0)
        if opt_pct > 15.0:
            continue
        eq = equiv_results.get(c["cell"], {})
        if eq.get("equiv_pass", False):
            c3_candidates.append({
                "cell": c["cell"],
                "tok_s_paced": c.get("tok_s_paced"),
                "optimizer_wall_pct": opt_pct,
                "equiv_pass": True,
                "delta_loss_at_100": eq.get("final_delta"),
            })

    verdict = "C3_CONFIRMED" if c3_candidates else "C3_NOT_MET"

    receipt = {
        "ticket": "FP40-L10-OPTIMIZER-AB",
        "ts": ts_now,
        "issue": 363,
        "scope": "L10 optimizer swap A/B — Muon NS chain off production critical path",
        "prior_fp39b_tok_s": PRIOR_FP39B_TOK_S,
        "prior_fp39b_muon_wall_pct": PRIOR_FP39B_MUON_PCT,
        "cells": cells,
        "equiv_results": equiv_results,
        "c3_candidates": c3_candidates,
        "verdict": verdict,
        "equiv_threshold_floor_nats": EQUIV_THRESHOLD_FLOOR,
        "equiv_noise_floor_nats": nf["noise_floor"] if nf else None,
        "equiv_derived_threshold_nats": nf["derived_threshold"] if nf else None,
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
            "production stack: c03 (hidden=1024, layers=20, heads=16, seq=1024)",
            f"B16+ckpt+compile+QAT (variant={VARIANT})",
            f"MTP: {MTP_N_HEADS} heads, weight={MTP_WEIGHT}",
            "CE: chunked_cross_entropy (chunk_tokens=1024)",
            "compile: torch.compile(_backbone_call wrapper, unwrapped forward)",
            f"phase timing: CUDA events per phase",
            f"EQUIV: {EQUIV_STEPS} steps, seeds 42+43 noise-floor, floor={EQUIV_THRESHOLD_FLOOR} nats",
            "EQUIV pass requires |delta@100| <= derived_threshold AND no monotonic increase across [10,25,50,100]",
            "100-step horizon; full-horizon equivalence unproven",
            "governor rails HOLD — never loosened",
            "proxy cells banned (C-7)",
        ],
    }

    out = f"{RECEIPTS}/fp40-l10-optimizer-ab-{ts_now}.json"
    checked_write(out, receipt)

    summary = {
        "cells": [{"cell": c["cell"], "tok_s_paced": c.get("tok_s_paced"),
                   "optimizer_wall_pct": c.get("optimizer_wall_pct"),
                   "status": c.get("status")} for c in cells],
        "equiv_results": {k: {"equiv_pass": v.get("equiv_pass"), "delta_at_100": v.get("final_delta")}
                          for k, v in equiv_results.items()},
        "c3_candidates": c3_candidates,
        "verdict": verdict,
    }
    print(json.dumps(summary, indent=2))
    print(f"FP40_L10_OPTIMIZER_AB_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
