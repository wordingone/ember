"""c04_fp8_ab.py — C-1 per-shape fp8 A/B for c04 candidate grid (#353).

For each candidate in docs/c04-candidate-grid-v1.md, measures bf16 vs
weight-cache fp8 on the ACTUAL GEMM shapes (QKV proj, output proj,
MLP up/down, LM head) at that candidate's widths.

Decision rule (C-1): fp8 adopted for a given candidate IFF the
FLOP-weighted per-shape product beats bf16 (product > 1.0); otherwise
bf16 stays and fp8 is receipted-killed for that candidate.

Runs on Windows Python (NOT via train MCP). Outputs one receipt per
candidate + a summary receipt covering all candidates.

Governor: VRAM_FRACTION=0.80, MARGIN_GIB=1.5.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")
GRID_DOC = os.path.join(NC, "docs", "c04-candidate-grid-v1.md")

VOCAB = 32000
SEQ = 1024
BATCH = 4
SEEDS = [16, 17, 18]
WARMUP_REPS = 5
BENCH_REPS = 20
VRAM_FRACTION = 0.80
MARGIN_GIB = 1.5


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Candidate grid — parsed from docs/c04-candidate-grid-v1.md
# ---------------------------------------------------------------------------

def _parse_candidates() -> list[dict]:
    """Parse candidate table rows from c04-candidate-grid-v1.md.

    Expected table format:
      | candidate | params | mode (flash) | B_knee | proj tok/s | tokens/day | 7B budget |
      | c03-shape h1024 d20 | 284M | ...
    """
    try:
        text = open(GRID_DOC, encoding="utf-8").read()
    except FileNotFoundError:
        return _hardcoded_candidates()

    candidates = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "candidate" in line.lower():
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 2:
            continue
        name_col = cols[0]
        # Parse h<hidden> d<depth> from the name
        h_m = re.search(r"h(\d+)", name_col)
        d_m = re.search(r"d(\d+)", name_col)
        if not h_m or not d_m:
            continue
        h = int(h_m.group(1))
        d = int(d_m.group(1))
        # Infer heads: h/64 for standard MHA (min 16)
        heads = max(16, h // 64)
        prefix = "c03-" if "c03" in name_col else ""
        cname = f"{prefix}h{h}-d{d}"
        candidates.append({"name": cname, "hidden": h, "layers": d,
                           "heads": heads, "mlp_dim": 4 * h})

    return candidates if candidates else _hardcoded_candidates()


def _hardcoded_candidates() -> list[dict]:
    """Fallback: candidates from grid arithmetic — used if doc parse fails."""
    return [
        {"name": "c03-h1024-d20", "hidden": 1024, "layers": 20, "heads": 16, "mlp_dim": 4096},
        {"name": "h2048-d12",     "hidden": 2048, "layers": 12, "heads": 32, "mlp_dim": 8192},
        {"name": "h2048-d14",     "hidden": 2048, "layers": 14, "heads": 32, "mlp_dim": 8192},
        {"name": "h2304-d12",     "hidden": 2304, "layers": 12, "heads": 36, "mlp_dim": 9216},
        {"name": "h2560-d12",     "hidden": 2560, "layers": 12, "heads": 40, "mlp_dim": 10240},
    ]


def _gemm_shapes(cand: dict) -> list[tuple[str, int, int]]:
    """Return (name, K, N) GEMM shapes for this candidate, each measured independently.

    Shapes:
      qkv_proj:     K=H  -> N=3H     (expansion)
      output_proj:  K=H  -> N=H      (square)
      mlp_up:       K=H  -> N=4H     (expansion)
      mlp_down:     K=4H -> N=H      (contraction)
      lm_head:      K=H  -> N=V      (expansion, V=32000)
    """
    H = cand["hidden"]
    return [
        ("qkv_proj",    H,       3 * H),
        ("output_proj", H,       H),
        ("mlp_up",      H,       4 * H),
        ("mlp_down",    4 * H,   H),
        ("lm_head",     H,       VOCAB),
    ]


def _gemm_flops(M: int, K: int, N: int) -> int:
    """FLOPs for one forward pass of a (M,K) @ (K,N) GEMM (2MKN)."""
    return 2 * M * K * N


# ---------------------------------------------------------------------------
# fp8 weight-cache helpers (from fp35c)
# ---------------------------------------------------------------------------

def _make_fp8_KN_col(weight):
    import torch
    return weight.to(torch.float8_e4m3fn).t()


def _make_fp8_NK_col(weight):
    import torch
    return weight.t().contiguous().to(torch.float8_e4m3fn).t()


def _bench_gemm_arm(x, weight, weight_fp8_KN, weight_fp8_NK, scale_one,
                    use_fp8: bool, reps: int):
    import torch

    def _step():
        # Forward-only: _scaled_mm backward not implemented on Windows torch 2.x.
        # Forward GEMM ratio is representative for the C-1 dtype decision.
        with torch.no_grad():
            if use_fp8:
                a_fp8 = x.to(torch.float8_e4m3fn)
                sa = torch.tensor(1.0, dtype=torch.float32, device=x.device)
                _ = torch._scaled_mm(a_fp8, weight_fp8_KN, scale_a=sa, scale_b=scale_one,
                                     out_dtype=torch.bfloat16)
            else:
                _ = x @ weight.t()
        torch.cuda.synchronize()

    for _ in range(WARMUP_REPS):
        _step()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(reps):
        _step()
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) / reps


def _run_candidate_fp8_ab(cand: dict) -> dict:
    """Run per-shape fp8 A/B for one candidate. Returns per-shape results + verdict."""
    import torch

    M = BATCH * SEQ
    shapes = _gemm_shapes(cand)
    shape_results: list[dict] = []
    total_flops = 0
    weighted_ratio_sum = 0.0

    for seed in SEEDS:
        for (shape_name, K, N) in shapes:
            torch.manual_seed(seed)
            x = torch.randn(M, K, dtype=torch.bfloat16, device="cuda")
            w = torch.randn(N, K, dtype=torch.bfloat16, device="cuda")
            scale_one = torch.tensor(1.0, dtype=torch.float32, device="cuda")

            with torch.no_grad():
                w_fp8_KN = _make_fp8_KN_col(w)
                w_fp8_NK = _make_fp8_NK_col(w)

            t_bf16 = _bench_gemm_arm(x, w, w_fp8_KN, w_fp8_NK, scale_one,
                                     use_fp8=False, reps=BENCH_REPS)
            t_fp8 = _bench_gemm_arm(x, w, w_fp8_KN, w_fp8_NK, scale_one,
                                    use_fp8=True, reps=BENCH_REPS)
            ratio = t_bf16 / t_fp8
            flops = _gemm_flops(M, K, N)

            print(f"[c04_fp8] {cand['name']} seed={seed} {shape_name}({M}x{K}->{N}): "
                  f"bf16={t_bf16*1e3:.2f}ms fp8={t_fp8*1e3:.2f}ms ratio={ratio:.3f}x",
                  flush=True)
            shape_results.append({
                "candidate": cand["name"], "seed": seed, "shape": shape_name,
                "M": M, "K": K, "N": N,
                "t_bf16_ms": round(t_bf16 * 1000, 3),
                "t_fp8_ms":  round(t_fp8  * 1000, 3),
                "ratio":     round(ratio, 4),
                "flops":     flops,
            })
            total_flops += flops
            weighted_ratio_sum += ratio * flops
            torch.cuda.empty_cache()

    flop_weighted_ratio = weighted_ratio_sum / total_flops if total_flops > 0 else 0.0
    dtype_verdict = "FP8" if flop_weighted_ratio > 1.0 else "BF16"
    print(f"[c04_fp8] {cand['name']} FLOP-weighted ratio={flop_weighted_ratio:.4f} "
          f"-> dtype={dtype_verdict}", flush=True)

    return {
        "candidate": cand["name"],
        "hidden": cand["hidden"],
        "layers": cand["layers"],
        "flop_weighted_ratio": round(flop_weighted_ratio, 4),
        "dtype_verdict": dtype_verdict,
        "shapes": shape_results,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    print(f"[c04_fp8] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[c04_fp8] torch:  {torch.__version__}", flush=True)
    sm_maj, sm_min = torch.cuda.get_device_capability(0)
    cuda_ver = torch.version.cuda
    print(f"[c04_fp8] sm{sm_maj}{sm_min}, CUDA {cuda_ver}", flush=True)

    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    print(f"[c04_fp8] VRAM: {free_gib:.2f}/{total_b/(1<<30):.2f} GiB free", flush=True)
    if free_gib < MARGIN_GIB:
        raise RuntimeError(f"VRAM margin violated: {free_gib:.2f} GiB free")

    if not hasattr(torch, "float8_e4m3fn") or not hasattr(torch, "_scaled_mm"):
        raise RuntimeError("fp8 / _scaled_mm unavailable — wrong torch build")

    candidates = _parse_candidates()
    print(f"[c04_fp8] {len(candidates)} candidates: "
          f"{[c['name'] for c in candidates]}", flush=True)

    all_results = []
    for cand in candidates:
        print(f"\n[c04_fp8] === {cand['name']} "
              f"(h={cand['hidden']} d={cand['layers']}) ===", flush=True)
        r = _run_candidate_fp8_ab(cand)
        all_results.append(r)

    ts = _ts()
    receipt = {
        "ticket": "C04-FP8-AB",
        "ts":     ts,
        "issue":  "#353",
        "constraint": "C-1",
        "config": {
            "batch": BATCH, "seq": SEQ, "vocab": VOCAB,
            "seeds": SEEDS, "warmup_reps": WARMUP_REPS, "bench_reps": BENCH_REPS,
            "vram_fraction": VRAM_FRACTION, "margin_gib": MARGIN_GIB,
        },
        "runtime": {
            "python": sys.executable,
            "torch":  torch.__version__,
            "cuda":   cuda_ver,
            "device": torch.cuda.get_device_name(0),
            "sm":     f"{sm_maj}{sm_min}",
        },
        "candidates": all_results,
        "dtype_summary": {r["candidate"]: r["dtype_verdict"] for r in all_results},
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    out_path = os.path.join(RECEIPTS, f"c04-fp8-ab-{ts}.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(f"\n[c04_fp8] receipt: {out_path}", flush=True)
    print(f"[c04_fp8] dtype summary: {receipt['dtype_summary']}", flush=True)
    print("C04_FP8_AB_DONE", flush=True)


if __name__ == "__main__":
    main()
