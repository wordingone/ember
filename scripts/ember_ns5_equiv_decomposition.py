#!/usr/bin/env python3
"""ember_ns5_equiv_decomposition.py — decompose the bf16-fused-vs-baseline
NS5 numerics delta into its dtype and compile components.

WHY THIS EXISTS
  receipts/ceff-composition-ab-20260703T103635Z.json verdicted
  COMPOSITION_PARK_NUMERICS_FAIL because its bf16_fused_vs_baseline cell
  measured max_abs_delta=4.36e-3 > NS5_EQUIV_TOL=1e-3.

  CODE-LEVEL CORRECTION to the brief that commissioned this script: the
  brief describes that cell as comparing "COMPILED-bf16 NS5 output against
  the FP32-EAGER baseline", i.e. conflating dtype-swap and compile deltas in
  one number. Reading scripts/ember_ceff_composition_ab.py::_run_bench_live
  line-by-line shows this is NOT what the code does:

      equiv_bf16 = _ns5_equiv_cell(_ns5_bf16, ns5_bf16_fused, ...)
                                    ^^^^^^^^^  baseline_fn = bf16-EAGER
                                               (NOT orig_ns5 / fp32-eager)

  _ns5_equiv_cell's "baseline_fn" parameter is the bf16-eager function, not
  the production fp32-eager function. So the AB script's own
  bf16_fused_vs_baseline cell ALREADY isolates the pure compile-on-bf16
  delta (this script's compile_only_bf16 cell) — it never touches fp32-eager
  at all. Measured here at the IDENTICAL shape+seed (1024,4096, seed=7) the
  AB script uses: compile_only_bf16=0.0043641366, bit-for-bit identical to
  the AB receipt's 0.0043641366. See "reproduction_check" in the receipt.

  So the actual, corrected finding is: the AB script's numerics-fail verdict
  is driven by a PURE compile delta on the bf16 chain (torch.compile applied
  to bf16 matmuls), not by a dtype/compile conflation. This script still
  measures the dtype-only delta (bf16-eager vs fp32-eager) and the
  bf16-compiled-vs-fp32-eager delta (the full composed stack against the
  ORIGINAL production floor, which the AB check never directly measures
  either) for completeness, since both numbers are informative even though
  neither is "the thing baked into the AB script's failing check".

MEASUREMENT ONLY. No verdict field. Interpretation is deferred to whoever
reads this receipt — this script does not adjudicate PASS/FAIL/park/keep.

FOUR CELLS PER SHAPE (same seeded G, reused across all four within a shape)
  (1) dtype_only          : bf16-EAGER   vs fp32-EAGER   — pure dtype swap
  (2) compile_only_bf16   : bf16-COMPILED vs bf16-EAGER  — pure compile-on-bf16
                             delta. THIS IS the AB script's own
                             bf16_fused_vs_baseline comparison (see
                             CODE-LEVEL CORRECTION above) — reproduced here
                             bit-for-bit at the matching shape+seed as proof.
  (3) full_stack_vs_floor : bf16-COMPILED vs fp32-EAGER  — the full composed
                             stack against the ORIGINAL fp32/eager production
                             floor. Nobody's check computes this directly
                             (the AB script never runs it); included because
                             it answers "how far did the whole D-arm drift
                             from what shipped before either lever" — a
                             different question from either (1) or (2) alone.
  (4) compile_only_fp32   : fp32-COMPILED vs fp32-EAGER  — control; this is
                             EXACTLY the AB script's fp32_fused_vs_baseline
                             cell (receipted 1.9e-7), reproduced as a sanity
                             anchor that this script's measurement plumbing
                             agrees with the AB script's own numbers before
                             trusting cells (1)-(3).

FUNCTIONS REUSED VERBATIM (imported, not reimplemented, from
scripts/ember_ceff_composition_ab.py — see ab_harness_sha256 in the receipt
for the exact byte-version mirrored)
  orig_ns5        = timeshare_pretrain._zeropower_via_newtonschulz5 (fp32 eager)
  ns5_bf16        = ember_ceff_composition_ab._ns5_bf16              (bf16 eager)
  ns5_fp32_fused  = ember_ceff_composition_ab._make_fused(orig_ns5)
  ns5_bf16_fused  = ember_ceff_composition_ab._make_fused(ns5_bf16)
_make_fused is torch.compile(fn, mode="reduce-overhead", fullgraph=False) —
identical to the AB script's own fusion recipe. Delta measurement mirrors
ember_ceff_composition_ab.py::_check_ns5_equiv exactly: same .to(device) /
torch.cuda.synchronize() placement, same (X_a - X_b).abs().max().item().

G-MATRIX SHAPES — real per-param Muon shapes, not a single square matrix
  Verified by direct model introspection (built a 1-layer LlamaModel with
  this contract's real dims — hidden=1024, intermediate=4096, heads=16,
  kv_heads=16 — via transformers.LlamaConfig/LlamaModel, the SAME class
  build_v0_model(live=True) instantiates, and enumerated every 2D non-embed
  parameter's shape). Result: the v0 c03 architecture routes exactly THREE
  distinct 2D shapes to Muon (split_param_groups: any 2D weight that is not
  an embedding and not a head) —
    attn_qkvo_square   (1024, 1024)  q_proj/k_proj/v_proj/o_proj
    mlp_gate_up_tall   (4096, 1024)  gate_proj/up_proj (shape[0]>shape[1] —
                                     _zeropower_via_newtonschulz5's own
                                     transpose branch fires on this one)
    mlp_down_wide      (1024, 4096)  down_proj — IDENTICAL to the shape the
                                     AB script (and its ancestor
                                     fp35_fused_muon_kernel_ab.py) already
                                     uses as "representative c03 shape"
  A fourth cell (mlp_down_wide_seed17) reruns mlp_down_wide's shape at a
  different seed — NOT a fourth distinct production shape (there are only
  three; ground-truthed above, not assumed) — to check the finding is not a
  seed-specific artifact of the one seed (7) the AB script happens to use.

GOVERNOR (never loosened; matches ember_ceff_composition_ab.py's own call)
  ts._apply_governor() runs before any CUDA tensor is allocated — VRAM
  fraction cap, margin assert, fail-closed SystemExit on violation. This
  probe never builds a model/optimizer and never runs a training step (pure
  NS5-function tensor math), so it is far lighter than the AB harness, but
  the governor call is unconditional per standing rail.

MODES
  (no flag)   Live CUDA measurement, all shape cells, writes the receipt.
  --selftest  CPU-only, no CUDA, no torch.compile. Proves the delta-
              measurement machinery (a) reports exactly 0 for a function
              compared against itself (not a false-positive detector) and
              (b) reports the exact expected nonzero magnitude for a
              deliberately hand-perturbed clone (not a vacuous always-0
              detector). Prints NS5_EQUIV_DECOMPOSITION_SELFTEST_PASS.

No git commits. No downloads. No founder/user names anywhere in this file
or its receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")
sys.path.insert(0, HERE)

from receipt_write import checked_write  # noqa: E402  (light; no torch)

NS5_EQUIV_TOL = 1e-3  # ember_ceff_composition_ab.py's own tolerance — quoted, not re-derived

# Ground-truthed against a real transformers.LlamaModel build at this
# contract's dims (see module docstring "G-MATRIX SHAPES" for the
# introspection that produced this list).
SHAPE_CELLS = [
    {
        "label": "attn_qkvo_square",
        "shape": (1024, 1024),
        "seed": 7,
        "note": "real q_proj/k_proj/v_proj/o_proj weight shape "
                "(LlamaAttention, hidden=1024, heads=16=kv_heads)",
    },
    {
        "label": "mlp_gate_up_tall",
        "shape": (4096, 1024),
        "seed": 7,
        "note": "real gate_proj/up_proj weight shape (intermediate=4096, "
                "hidden=1024); shape[0]>shape[1] so "
                "_zeropower_via_newtonschulz5's transpose branch fires",
    },
    {
        "label": "mlp_down_wide",
        "shape": (1024, 4096),
        "seed": 7,
        "note": "real down_proj weight shape (hidden=1024, intermediate=4096) "
                "-- IDENTICAL to ember_ceff_composition_ab.py's own "
                "_check_ns5_equiv CUDA shape+seed; this cell's "
                "conflated_original delta is the reproduction check against "
                "the AB receipt's 4.36e-3",
    },
    {
        "label": "mlp_down_wide_seed17",
        "shape": (1024, 4096),
        "seed": 17,
        "note": "seed-robustness replicate of mlp_down_wide -- NOT a 4th "
                "distinct production shape (ground-truthed: exactly 3 exist). "
                "Checks the finding isn't a seed=7-specific artifact",
    },
]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _harness_sha() -> str:
    return _sha256_of(__file__)


# ---------------------------------------------------------------------------
# Delta measurement — mirrors ember_ceff_composition_ab.py::_check_ns5_equiv
# exactly (same .to(device)/synchronize placement, same abs().max().item()).
# ---------------------------------------------------------------------------

def _delta(fn_a, fn_b, G, device: str) -> float:
    import torch
    with torch.no_grad():
        Xa = fn_a(G.to(device))
        if device == "cuda":
            torch.cuda.synchronize()
        Xb = fn_b(G.to(device))
        if device == "cuda":
            torch.cuda.synchronize()
    return (Xa - Xb).abs().max().item()


def _measure_cell(cell: dict, fns: dict, device: str) -> dict:
    import torch
    torch.manual_seed(cell["seed"])
    G = torch.randn(*cell["shape"], dtype=torch.float32, device=device)

    d_dtype_only = _delta(fns["fp32_eager"], fns["bf16_eager"], G, device)
    d_compile_only_bf16 = _delta(fns["bf16_eager"], fns["bf16_compiled"], G, device)
    d_full_stack_vs_floor = _delta(fns["fp32_eager"], fns["bf16_compiled"], G, device)
    d_compile_only_fp32 = _delta(fns["fp32_eager"], fns["fp32_compiled"], G, device)

    return {
        "label": cell["label"],
        "shape": list(cell["shape"]),
        "seed": cell["seed"],
        "note": cell["note"],
        "dtype_only__bf16eager_vs_fp32eager": round(d_dtype_only, 10),
        "compile_only_bf16__bf16compiled_vs_bf16eager": round(d_compile_only_bf16, 10),
        "full_stack_vs_floor__bf16compiled_vs_fp32eager": round(d_full_stack_vs_floor, 10),
        "compile_only_fp32__fp32compiled_vs_fp32eager": round(d_compile_only_fp32, 10),
        "tolerance": NS5_EQUIV_TOL,
    }


# ---------------------------------------------------------------------------
# Live GPU run
# ---------------------------------------------------------------------------

def _run_live() -> dict:
    import torch
    import timeshare_pretrain as ts_mod
    import ember_ceff_composition_ab as ab_mod

    # ── Governor (never loosened) — no model build here, pure NS5-function
    #    tensor math, but the rail is unconditional per standing discipline ──
    gov = ts_mod._apply_governor()

    print(f"[ns5-equiv-decomposition] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[ns5-equiv-decomposition] torch:  {torch.__version__}", flush=True)
    print(f"[ns5-equiv-decomposition] governor: {gov}", flush=True)

    orig_ns5 = ts_mod._zeropower_via_newtonschulz5  # fp32 eager, unpatched
    ns5_bf16 = ab_mod._ns5_bf16                     # bf16 eager
    ns5_fp32_fused = ab_mod._make_fused(orig_ns5)   # fp32 compiled
    ns5_bf16_fused = ab_mod._make_fused(ns5_bf16)   # bf16 compiled

    fns = {
        "fp32_eager": orig_ns5,
        "bf16_eager": ns5_bf16,
        "fp32_compiled": ns5_fp32_fused,
        "bf16_compiled": ns5_bf16_fused,
    }

    cells = []
    for cell in SHAPE_CELLS:
        print(f"[ns5-equiv-decomposition] cell={cell['label']} shape={cell['shape']} "
              f"seed={cell['seed']} ...", flush=True)
        r = _measure_cell(cell, fns, "cuda")
        cells.append(r)
        print(f"[ns5-equiv-decomposition]   dtype_only={r['dtype_only__bf16eager_vs_fp32eager']:.3e} "
              f"compile_only_bf16={r['compile_only_bf16__bf16compiled_vs_bf16eager']:.3e} "
              f"full_stack_vs_floor={r['full_stack_vs_floor__bf16compiled_vs_fp32eager']:.3e} "
              f"compile_only_fp32={r['compile_only_fp32__fp32compiled_vs_fp32eager']:.3e}", flush=True)
        torch.cuda.empty_cache()

    max_of = lambda key: round(max(c[key] for c in cells), 10)  # noqa: E731
    summary = {
        "max_dtype_only__bf16eager_vs_fp32eager": max_of("dtype_only__bf16eager_vs_fp32eager"),
        "max_compile_only_bf16__bf16compiled_vs_bf16eager": max_of("compile_only_bf16__bf16compiled_vs_bf16eager"),
        "max_full_stack_vs_floor__bf16compiled_vs_fp32eager": max_of("full_stack_vs_floor__bf16compiled_vs_fp32eager"),
        "max_compile_only_fp32__fp32compiled_vs_fp32eager": max_of("compile_only_fp32__fp32compiled_vs_fp32eager"),
    }

    # Reproduction anchor: find the SAME shape+seed cell the AB script itself
    # used ((1024,4096), seed=7 -- "mlp_down_wide" here) and compare against
    # THE CORRECT cell for what the AB script actually computed. Per the
    # CODE-LEVEL CORRECTION above, bf16_fused_vs_baseline in the AB script is
    # bf16-COMPILED vs bf16-EAGER (this script's compile_only_bf16), NOT
    # bf16-compiled vs fp32-eager -- so the reproduction check targets
    # compile_only_bf16, not full_stack_vs_floor.
    ab_anchor_cell = next(c for c in cells if c["label"] == "mlp_down_wide")
    ab_path = os.path.join(HERE, "ember_ceff_composition_ab.py")
    reproduction_check = {
        "ab_receipt": "receipts/ceff-composition-ab-20260703T103635Z.json",
        "note": "the AB script's bf16_fused_vs_baseline cell passes baseline_fn="
                "_ns5_bf16 (bf16-eager), NOT orig_ns5 (fp32-eager) -- see "
                "_run_bench_live's equiv_bf16 = _ns5_equiv_cell(_ns5_bf16, "
                "ns5_bf16_fused, ...). So it measures compile_only_bf16, not "
                "a dtype+compile conflation. The correct reproduction target "
                "is this script's compile_only_bf16 cell at the matching "
                "shape+seed (mlp_down_wide, (1024,4096), seed=7), not "
                "full_stack_vs_floor.",
        "ab_receipt_bf16_fused_vs_baseline_max_abs_delta": 0.0043641366,
        "this_script_mlp_down_wide_compile_only_bf16": ab_anchor_cell["compile_only_bf16__bf16compiled_vs_bf16eager"],
        "reproduces_ab_finding": bool(
            abs(ab_anchor_cell["compile_only_bf16__bf16compiled_vs_bf16eager"] - 0.0043641366) < 1e-6
        ),
        "ab_receipt_fp32_fused_vs_baseline_max_abs_delta": 1.9e-07,
        "this_script_mlp_down_wide_compile_only_fp32": ab_anchor_cell["compile_only_fp32__fp32compiled_vs_fp32eager"],
        "reproduces_ab_control": bool(
            abs(ab_anchor_cell["compile_only_fp32__fp32compiled_vs_fp32eager"] - 1.9e-07) < 1e-7
        ),
    }

    return {
        "status": "OK",
        "governor": gov,
        "device": torch.cuda.get_device_name(0),
        "torch_version": torch.__version__,
        "ab_harness_sha256": _sha256_of(ab_path),
        "cells": cells,
        "summary": summary,
        "reproduction_check": reproduction_check,
    }


def run_and_emit_live():
    result = _run_live()
    ts = _ts()
    receipt = {
        "ticket": "CEFF-NS5-EQUIV-DECOMPOSITION",
        "ts": ts,
        "mode": "live",
        "issue": "#24",
        "scope": "decompose ceff-composition-ab-20260703T103635Z.json's "
                 "bf16_fused_vs_baseline 4.36e-3 max_abs_delta into its "
                 "dtype-swap and compile contributions -- MEASUREMENT ONLY",
        "harness_sha": _harness_sha(),
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "interpretation": "NONE -- this receipt is measurement only, no verdict field, "
                          "per the session rules governing this probe",
        "api_spend_usd": 0,
        "flags": [
            "governor rail HOLD -- never loosened",
            "no git commits, no downloads, no founder/user names",
            "no verdict / no kill-keep judgment in this receipt",
        ],
        **result,
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"ceff-ns5-equiv-decomposition-{ts}.json")
    checked_write(path, receipt)
    print(f"[ns5-equiv-decomposition] receipt: {path}", flush=True)
    s = result["summary"]
    print(f"[ns5-equiv-decomposition] max_dtype_only={s['max_dtype_only__bf16eager_vs_fp32eager']:.3e} "
          f"max_compile_only_bf16={s['max_compile_only_bf16__bf16compiled_vs_bf16eager']:.3e} "
          f"max_full_stack_vs_floor={s['max_full_stack_vs_floor__bf16compiled_vs_fp32eager']:.3e} "
          f"max_compile_only_fp32={s['max_compile_only_fp32__fp32compiled_vs_fp32eager']:.3e}", flush=True)
    print(f"[ns5-equiv-decomposition] reproduction_check: "
          f"reproduces_ab_finding={result['reproduction_check']['reproduces_ab_finding']} "
          f"reproduces_ab_control={result['reproduction_check']['reproduces_ab_control']}", flush=True)
    print(f"NS5_EQUIV_DECOMPOSITION_DONE receipt={path}", flush=True)
    return path


# ---------------------------------------------------------------------------
# Selftest — pure CPU, no torch.compile, no CUDA. Proves the delta machinery
# detects a forced nonzero and doesn't false-positive on identical functions.
# ---------------------------------------------------------------------------

def selftest() -> None:
    import torch

    print("[ember_ns5_equiv_decomposition] selftest: delta-measurement calibration (CPU, no compile)", flush=True)

    torch.manual_seed(11)
    G = torch.randn(32, 48)

    def identity_fn(x):
        return x.clone()

    PERTURB = 0.0137  # arbitrary, known, nonzero

    def perturbed_fn(x):
        out = x.clone()
        out[0, 0] = out[0, 0] + PERTURB  # deliberately hand-perturbed clone
        return out

    # 1. Same function compared against itself -> exactly 0 (not a
    #    false-positive detector: if the machinery always reported nonzero,
    #    this would fail).
    d_zero = _delta(identity_fn, identity_fn, G, "cpu")
    assert d_zero == 0.0, f"expected exact 0 for identical fn, got {d_zero}"
    print(f"  identity-vs-itself delta={d_zero}  (expected exactly 0)  PASS")

    # 2. Deliberately-perturbed clone -> the exact known nonzero magnitude
    #    (not a vacuous always-0 detector: proves a real compile-sized
    #    divergence would be caught, not silently swallowed).
    d_perturbed = _delta(identity_fn, perturbed_fn, G, "cpu")
    assert abs(d_perturbed - PERTURB) < 1e-6, f"expected {PERTURB}, got {d_perturbed}"
    print(f"  identity-vs-perturbed-clone delta={d_perturbed}  (expected {PERTURB})  PASS")

    # 3. The perturbation is well above NS5_EQUIV_TOL -- confirms this
    #    magnitude of forced divergence WOULD have failed the AB script's own
    #    tolerance gate, i.e. the detector operates at the resolution the
    #    real decision (NS5_EQUIV_TOL=1e-3) actually needs.
    assert d_perturbed > NS5_EQUIV_TOL, (d_perturbed, NS5_EQUIV_TOL)
    print(f"  perturbation {PERTURB} > NS5_EQUIV_TOL={NS5_EQUIV_TOL}  (detector resolves at the real decision bar)  PASS")

    # 4. _measure_cell's full 4-fn wiring, using deliberately DISTINCT stand-in
    #    functions (not the real NS5 math) so this selftest never needs torch.
    #    compile/CUDA: fp32_eager=identity, bf16_eager=+PERTURB_A,
    #    fp32_compiled=+PERTURB_B, bf16_compiled=+PERTURB_A+PERTURB_C -- checks
    #    the four-cell decomposition arithmetic wires the right pairs together.
    PERTURB_A, PERTURB_B, PERTURB_C = 0.01, 0.0002, 0.003

    def _shift(k):
        def f(x):
            out = x.clone()
            out[0, 0] = out[0, 0] + k
            return out
        return f

    stand_in_fns = {
        "fp32_eager": identity_fn,
        "bf16_eager": _shift(PERTURB_A),
        "fp32_compiled": _shift(PERTURB_B),
        "bf16_compiled": _shift(PERTURB_A + PERTURB_C),
    }
    cell = {"label": "selftest_stand_in", "shape": (32, 48), "seed": 11,
            "note": "synthetic stand-in functions, not real NS5 math"}
    r = _measure_cell(cell, stand_in_fns, "cpu")
    assert abs(r["dtype_only__bf16eager_vs_fp32eager"] - PERTURB_A) < 1e-6, r
    assert abs(r["compile_only_bf16__bf16compiled_vs_bf16eager"] - PERTURB_C) < 1e-6, r
    assert abs(r["full_stack_vs_floor__bf16compiled_vs_fp32eager"] - (PERTURB_A + PERTURB_C)) < 1e-6, r
    assert abs(r["compile_only_fp32__fp32compiled_vs_fp32eager"] - PERTURB_B) < 1e-6, r
    print("  _measure_cell 4-cell wiring (stand-in fns, dtype+compile add linearly as constructed)  PASS")

    print("NS5_EQUIV_DECOMPOSITION_SELFTEST_PASS")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Decompose the ceff-composition-ab bf16-fused-vs-baseline "
                    "NS5 delta into dtype and compile contributions (measurement only)")
    ap.add_argument("--selftest", action="store_true",
                    help="CPU-only, no CUDA/compile: calibrate the delta-measurement machinery")
    args, _ = ap.parse_known_args()

    if args.selftest:
        selftest()
        return 0
    run_and_emit_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
