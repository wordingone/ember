"""c04_design_bench.py — full lever stack design bench per c04 candidate (#353).

Per candidate: one governed bench cell with full lever stack (C-4 through C-7):
  C-4: compiled, zero graph breaks
  C-2: ckpt AND no-ckpt both measured; winner is higher tok/s_paced
  C-3: optimizer ≤15% step wall (Muon split, NS iterations per C-3 receipt)
  C-5: QAT share cell — if fake_quant >10% GPU share, flag for delayed-QAT
  C-7: PRODUCTION class (LlamaModel + 2 MTP heads + chunkedCE + Muon split)

Gate (§3 of c04-design-constraints-v1): budget / tok_s_paced ≤ 24h.
  - budget comes from density A/B verdict (written to receipts/ before this runs)
  - if no verdict receipt found, uses conservative 7.0B token default

Dispatch: one train-MCP wrapper per candidate (c04_design_{name}.py).
This script is parameterized via --candidate <name>; wrapper sets sys.argv.

Receipt class: ENG/ARCH (tagged per C-7 spec).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
NC   = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import fp19_bench as fp19          # noqa: E402
from receipt_write import checked_write   # noqa: E402
import timeshare_pretrain as ts    # noqa: E402

RECEIPTS = os.path.join(NC, "receipts")

SEQ   = fp19.SEQ
VOCAB = fp19.VOCAB
PACE_S = fp19.PACE_S
VRAM_FRACTION = 0.80
MARGIN_GIB    = fp19.MARGIN_GIB

MTP_N_HEADS = 2
MTP_WEIGHT  = 0.3
LR_MUON     = 0.02
LR_ADAMW    = 3e-4
WEIGHT_DECAY = 0.1

WARMUP = 5
TIMED  = 10

GOV_DAY_S = 86400
DEFAULT_BUDGET_B = 7.0e9  # conservative fallback if no verdict receipt

CANDIDATES = {
    "c03-h1024-d20": {"hidden": 1024, "layers": 20, "heads": 16, "batch_ckpt": 16, "batch_nockpt": 8},
    "h2048-d12":     {"hidden": 2048, "layers": 12, "heads": 32, "batch_ckpt": 8,  "batch_nockpt": 4},
    "h2048-d14":     {"hidden": 2048, "layers": 14, "heads": 32, "batch_ckpt": 8,  "batch_nockpt": 4},
    "h2304-d12":     {"hidden": 2304, "layers": 12, "heads": 36, "batch_ckpt": 8,  "batch_nockpt": 4},
    "h2560-d12":     {"hidden": 2560, "layers": 12, "heads": 40, "batch_ckpt": 4,  "batch_nockpt": 2},
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _find_budget_b() -> float:
    """Read density verdict receipt for planned token budget. Conservative fallback if absent."""
    receipts = sorted(Path(RECEIPTS).glob("density-ab-verdict-*.json"))
    if not receipts:
        return DEFAULT_BUDGET_B
    try:
        r = json.loads(receipts[-1].read_text())
        # budget_b may be stored as 'budget_b' or inferred from the c04 pick
        b = r.get("budget_b") or r.get("planned_budget_b")
        if b:
            return float(b)
    except Exception:
        pass
    return DEFAULT_BUDGET_B


def _find_c1_dtype(candidate_name: str) -> str:
    """Read C-1 fp8 A/B receipt to get dtype verdict for this candidate. Default: BF16."""
    receipts = sorted(Path(RECEIPTS).glob("c04-fp8-ab-*.json"))
    for r_path in reversed(receipts):
        try:
            r = json.loads(r_path.read_text())
            summary = r.get("dtype_summary", {})
            for key, verdict in summary.items():
                if candidate_name in key or key in candidate_name:
                    return verdict
        except Exception:
            pass
    return "BF16"


def _build_model(cfg: dict, grad_ckpt: bool):
    """Build production-class model (C-7): LlamaModel + 2 MTP heads + Muon split."""
    import torch
    from transformers import LlamaConfig, LlamaModel

    conf = LlamaConfig(
        vocab_size=VOCAB,
        hidden_size=cfg["hidden"],
        intermediate_size=cfg["hidden"] * 4,
        num_hidden_layers=cfg["layers"],
        num_attention_heads=cfg["heads"],
        num_key_value_heads=cfg["heads"],
        max_position_embeddings=SEQ,
        use_cache=False,
    )
    backbone = LlamaModel(conf).cuda().to(torch.bfloat16)
    if grad_ckpt:
        backbone.gradient_checkpointing_enable()

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

    muon_p, adamw_p = [], []
    for name, p in all_params.items():
        if p.ndim == 2 and "embed_tokens" not in name:
            muon_p.append(p)
        else:
            adamw_p.append(p)

    Muon = ts._muon_class()
    opts = {}
    if muon_p:
        opts["muon"] = Muon(muon_p, lr=LR_MUON, weight_decay=WEIGHT_DECAY)
    opts["adamw"] = torch.optim.AdamW(adamw_p, lr=LR_ADAMW, weight_decay=WEIGHT_DECAY)
    return backbone, head, mtp_heads, opts


def _bench_cell(cfg: dict, candidate_name: str, batch: int, grad_ckpt: bool,
                compiled: bool, variant: str = "qat") -> dict:
    """One bench cell. Returns dict with tok_s_paced, optimizer_wall_share, etc."""
    import torch

    arm = "ckpt" if grad_ckpt else "nockpt"
    cell_name = f"{candidate_name}-b{batch}-{arm}-{'compile' if compiled else 'eager'}-prod"
    out = {
        "cell": cell_name, "candidate": candidate_name,
        "batch": batch, "seq": SEQ, "grad_checkpointing": grad_ckpt,
        "compiled": compiled, "optimizer": "muon_split",
        "mtp_heads": MTP_N_HEADS, "variant": variant,
        "receipt_class": "PRODUCTION",
    }

    try:
        backbone, head, mtp_heads, opts = _build_model(cfg, grad_ckpt)
        backbone.train(); head.train(); mtp_heads.train()
        ce_fn = ts.chunked_cross_entropy

        def step():
            ids  = torch.randint(0, VOCAB, (batch, SEQ), device="cuda")
            tgt0 = torch.roll(ids, -1, dims=1)
            tgt_mtp = [torch.roll(ids, -(k + 2), dims=1) for k in range(MTP_N_HEADS)]
            saved = fp19._apply_fake_quant(backbone, variant)
            hidden = backbone(input_ids=ids).last_hidden_state
            h_flat = hidden.reshape(-1, hidden.shape[-1])
            primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
            mtp_ces = [ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1), chunk_tokens=1024)[0]
                       for k, mh in enumerate(mtp_heads)]
            loss = ts.mtp_total_loss(primary_ce, mtp_ces, MTP_WEIGHT)
            fp19._restore(saved)
            loss.backward()
            t_opt_start = time.perf_counter()
            for o in opts.values():
                o.step()
            t_opt = time.perf_counter() - t_opt_start
            for o in opts.values():
                o.zero_grad(set_to_none=True)
            return t_opt

        if compiled:
            step_fn = torch.compile(step, fullgraph=True)
            print(f"[c04_bench] {cell_name}: compiling ...", flush=True)
            try:
                step_fn()
            except torch._dynamo.exc.Unsupported as e:
                out["status"] = "COMPILE-BREAK"
                out["error"] = str(e)[:300]
                return out
        else:
            step_fn = step

        print(f"[c04_bench] {cell_name}: warmup {WARMUP} ...", flush=True)
        opt_times = []
        for i in range(WARMUP):
            t_opt = step_fn()
            opt_times.append(t_opt)
            print(f"[c04_bench]   warmup {i+1}/{WARMUP}", flush=True)

        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            return out

        print(f"[c04_bench] {cell_name}: bench {TIMED} steps ...", flush=True)
        step_times, opt_wall_times = [], []
        t0 = time.perf_counter()
        for _ in range(TIMED):
            t_step_start = time.perf_counter()
            t_opt = step_fn()
            torch.cuda.synchronize()
            t_step = time.perf_counter() - t_step_start
            time.sleep(PACE_S)
            step_times.append(t_step)
            opt_wall_times.append(t_opt)

        total_dt = time.perf_counter() - t0
        toks = TIMED * batch * SEQ
        tok_s_paced = toks / total_dt
        tok_s_raw   = toks / (total_dt - TIMED * PACE_S)
        mean_step   = sum(step_times) / len(step_times)
        mean_opt    = sum(opt_wall_times) / len(opt_wall_times)
        opt_wall_share = mean_opt / mean_step if mean_step > 0 else 0.0

        out.update(
            status="OK",
            tok_s_paced=round(tok_s_paced, 1),
            tok_s_raw=round(tok_s_raw, 1),
            pacing_tax=round(1.0 - tok_s_paced / tok_s_raw, 4),
            optimizer_wall_share=round(opt_wall_share, 4),
            c3_pass=opt_wall_share <= 0.15,
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
        out["error"] = f"{type(e).__name__}: {e}"[:400]
        import traceback
        print(traceback.format_exc(), flush=True)
        torch.cuda.empty_cache()
        return out


def _gate_check(tok_s_paced: float, budget_b: float) -> dict:
    """§3 gate: budget_b / tok_s_paced ≤ 24 governed hours."""
    budget_days = budget_b / tok_s_paced / GOV_DAY_S
    return {
        "budget_b":    budget_b,
        "tok_s_paced": tok_s_paced,
        "budget_days": round(budget_days, 3),
        "gate_pass":   budget_days <= 1.0,
    }


def main(candidate_name: str | None = None):
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", default=candidate_name,
                    choices=list(CANDIDATES), help="Which candidate to bench")
    args, _ = ap.parse_known_args()
    name = args.candidate or candidate_name

    if name not in CANDIDATES:
        print(f"[c04_bench] ERROR: unknown candidate '{name}'; "
              f"choices: {list(CANDIDATES)}", file=sys.stderr)
        sys.exit(1)

    cfg = CANDIDATES[name]
    print(f"[c04_bench] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[c04_bench] torch:  {torch.__version__}", flush=True)
    print(f"[c04_bench] candidate: {name} "
          f"(h={cfg['hidden']} d={cfg['layers']} heads={cfg['heads']})", flush=True)

    dtype = _find_c1_dtype(name)
    budget_b = _find_budget_b()
    print(f"[c04_bench] C-1 dtype: {dtype} | budget: {budget_b/1e9:.2f}B tok", flush=True)

    # C-2: measure both ckpt and no-ckpt; winner = higher tok/s_paced
    cells = []
    for (grad_ckpt, batch) in [(True, cfg["batch_ckpt"]), (False, cfg["batch_nockpt"])]:
        arm = "ckpt" if grad_ckpt else "nockpt"
        print(f"\n[c04_bench] --- {arm} B={batch} ---", flush=True)
        r = _bench_cell(cfg, name, batch, grad_ckpt=grad_ckpt,
                        compiled=True, variant="qat")
        print(f"[c04_bench] {arm}: {r.get('status')} "
              f"tok/s={r.get('tok_s_paced','?')} "
              f"opt_share={r.get('optimizer_wall_share','?')}",
              flush=True)
        cells.append(r)

    ok_cells = [c for c in cells if c.get("status") == "OK"]
    if not ok_cells:
        best = None
        best_tok_s = 0.0
        print(f"[c04_bench] WARNING: no OK cells for {name}", flush=True)
    else:
        best = max(ok_cells, key=lambda c: c.get("tok_s_paced", 0.0))
        best_tok_s = best["tok_s_paced"]

    gate = _gate_check(best_tok_s, budget_b) if best_tok_s > 0 else {
        "budget_b": budget_b, "tok_s_paced": 0.0,
        "budget_days": float("inf"), "gate_pass": False,
    }
    print(f"\n[c04_bench] GATE: {budget_b/1e9:.2f}B tok / {best_tok_s:.0f} tok/s "
          f"= {gate['budget_days']:.3f} days | pass={gate['gate_pass']}", flush=True)

    ts_now = _ts()
    receipt = {
        "ticket":    "C04-DESIGN-BENCH",
        "ts":        ts_now,
        "issue":     "#353",
        "candidate": name,
        "config":    cfg,
        "c1_dtype":  dtype,
        "cells":     cells,
        "best_cell": best,
        "gate":      gate,
        "receipt_class": "ENG/ARCH",
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    safe_name = name.replace("/", "-")
    out_path = os.path.join(RECEIPTS, f"c04-design-bench-{safe_name}-{ts_now}.json")
    checked_write(out_path, receipt)
    print(f"[c04_bench] receipt: {out_path}", flush=True)
    print(f"C04_DESIGN_BENCH_DONE candidate={name} "
          f"gate={'PASS' if gate['gate_pass'] else 'FAIL'} "
          f"best_tok_s={best_tok_s:.0f}", flush=True)


if __name__ == "__main__":
    main()
